import asyncio
import time

from backend.config.constants import GameEventType, GameType, SocketEvent, TexasAction, TexasPhase, WerewolfAction, WerewolfPhase, WerewolfWinner
from backend.config.settings import get_settings
from backend.domain.werewolf.engine import WerewolfEngine
from backend.domain.texas.engine import TexasEngine
from backend.repositories.redis_repo import RedisRepo
from backend.services.event_service import EventService
from backend.services.game_state_service import GameStateService
from backend.services.presence_service import PresenceService
from backend.services.timer_service import TimerService
from backend.services.texas_settlement_service import TexasSettlementService
from backend.services.werewolf_settlement_service import WerewolfSettlementService
from backend.services.settlement_emitter import SettlementEmitter
from backend.views.response import ok
from backend.socket.broadcast import emit_room_event
from backend.socket.server import sio
from backend.utils.log import get_logger
logger = get_logger(__name__)


class _EventEmitter:
    @staticmethod
    def resolve_werewolf(event: dict) -> tuple[str, bool] | None:
        if event.get("event_type") == GameEventType.PHASE_CHANGE:
            return SocketEvent.WW_PHASE_CHANGE, False
        action_type = event.get("action_type")
        if action_type not in {a.value for a in WerewolfAction}:
            return None
        if action_type == WerewolfAction.WOLF_CHAT.value:
            return SocketEvent.WW_CHAT_WOLF, True
        if action_type == WerewolfAction.SPEAK.value:
            return SocketEvent.WW_CHAT_DAY, False
        if action_type == WerewolfAction.VOTE.value:
            return SocketEvent.WW_DAY_VOTE, False
        return SocketEvent.WW_NIGHT_ACTION, False

    @staticmethod
    def resolve_texas(event: dict) -> str | None:
        if event.get("event_type") == GameEventType.PHASE_CHANGE:
            return SocketEvent.TX_PHASE_CHANGE
        action_type = event.get("action_type")
        if action_type not in {a.value for a in TexasAction}:
            return None
        action_name = TexasAction(action_type).name.lower()
        return f"tx:{action_name}"


class OfflineMonitorService:
    @staticmethod
    async def run_loop() -> None:
        settings = get_settings()
        interval = settings.offline_check_interval_seconds
        while True:
            try:
                await OfflineMonitorService.check_werewolf()
                await OfflineMonitorService.check_texas()
            except Exception as exc:
                logger.warning("offline_monitor_error error=%s", exc)
            await asyncio.sleep(interval)

    @staticmethod
    async def check_werewolf() -> None:
        settings = get_settings()
        rooms = await RedisRepo.get_active_rooms()
        if not rooms:
            return

        now_ms = int(time.time() * 1000)
        for room_id in rooms:
            state = await GameStateService.get_state(room_id)
            if not state or int(state.get("game_type", 0)) != int(GameType.WEREWOLF):
                continue
            engine = WerewolfEngine.from_state(state)
            if engine.phase == WerewolfPhase.FINISHED:
                await RedisRepo.remove_active_room(room_id)
                continue

            events_to_emit: list[dict] = []
            alive = engine.get_state().get("alive", [])
            if not alive:
                winner = engine._check_winner() or WerewolfWinner.VILLAGERS
                engine._winner = winner
                engine._set_phase(WerewolfPhase.FINISHED)
                events_to_emit.append(engine._phase_event(engine._phase_payload({"winner": winner, "reason": "no_alive"})))
            else:
                for agent_id in alive:
                    presence = await PresenceService.get(int(agent_id))
                    if not presence or presence.get("status") not in {"offline", "left"}:
                        continue
                    ts_ms = int(presence.get("ts_ms", 0))
                    if now_ms - ts_ms < settings.werewolf_offline_death_seconds * 1000:
                        continue
                    events = engine.apply_offline_death(int(agent_id))
                    if events:
                        events_to_emit.extend(events)

            if engine.phase != WerewolfPhase.FINISHED and not events_to_emit:
                meta = state.get("meta") or {}
                phase_started_ms = int(meta.get("phase_started_ms") or now_ms)
                speaker_started_ms = int(meta.get("speaker_started_ms") or phase_started_ms or now_ms)
                phase = engine.phase
                timeout_events: list[dict] = []
                if phase == WerewolfPhase.DAY_DEBATE:
                    if now_ms - speaker_started_ms >= settings.werewolf_speak_timeout_seconds * 1000:
                        timeout_events = engine.apply_speaker_timeout()
                elif phase == WerewolfPhase.DAY_VOTE:
                    if now_ms - phase_started_ms >= settings.werewolf_vote_timeout_seconds * 1000:
                        timeout_events = engine.apply_vote_timeout(settings.werewolf_max_idle_vote_rounds)
                elif phase in {
                    WerewolfPhase.WOLF_CHAT,
                    WerewolfPhase.WOLF_KILL,
                    WerewolfPhase.WITCH,
                    WerewolfPhase.SEER,
                    WerewolfPhase.GUARD,
                }:
                    if now_ms - phase_started_ms >= settings.werewolf_phase_timeout_seconds * 1000:
                        timeout_events = engine.apply_phase_timeout()
                if timeout_events:
                    events_to_emit.extend(timeout_events)

            if not events_to_emit:
                continue

            saved_state = await GameStateService.save_state(
                room_id,
                engine.dump_state(),
                prev_state=state,
                public_state=engine.build_public_state(),
            )
            timers = TimerService.build(saved_state) or {}
            if engine.phase == WerewolfPhase.FINISHED:
                await WerewolfSettlementService.settle(engine)
            for event in events_to_emit:
                resolved = _EventEmitter.resolve_werewolf(event)
                if not resolved:
                    continue
                event_name, private = resolved
                if event_name == SocketEvent.WW_PHASE_CHANGE and timers:
                    payload = event.get("payload") or {}
                    payload["timers"] = timers
                    event["payload"] = payload
                await EventService.log_room_event(room_id, event_name, event)
                await emit_room_event(sio, room_id, event_name, ok(event), private=private)

    @staticmethod
    async def check_texas() -> None:
        settings = get_settings()
        rooms = await RedisRepo.get_active_rooms()
        if not rooms:
            return

        now_ms = int(time.time() * 1000)
        for room_id in rooms:
            state = await GameStateService.get_state(room_id)
            if not state or int(state.get("game_type", 0)) != int(GameType.TEXAS):
                continue
            engine = TexasEngine.from_state(state)
            if engine.phase == TexasPhase.FINISHED:
                await RedisRepo.remove_active_room(room_id)
                continue

            meta = state.get("meta") or {}
            turn_started_ms = int(meta.get("turn_started_ms") or now_ms)
            max_auto_actions = 3
            actions_taken = 0
            while True:
                actor_id = engine.get_state().get("actor_id")
                if not actor_id:
                    break
                presence = await PresenceService.get(int(actor_id))
                offline_expired = False
                left_actor = engine.is_left(int(actor_id))
                if left_actor:
                    offline_expired = True
                if presence and presence.get("status") in {"offline", "left"}:
                    ts_ms = int(presence.get("ts_ms", 0))
                    offline_expired = now_ms - ts_ms >= settings.offline_kill_seconds * 1000

                idle_expired = now_ms - turn_started_ms >= settings.texas_action_timeout_seconds * 1000
                if not (offline_expired or idle_expired):
                    break

                reason = "leave" if left_actor else ("offline" if offline_expired else "timeout")
                prev_actor = actor_id
                events = engine.apply_action(
                    int(actor_id),
                    int(TexasAction.FOLD),
                    {"meta": {"auto": True, "reason": reason}},
                )
                turn_started_ms = now_ms
                saved_state = await GameStateService.save_state(
                    room_id,
                    engine.dump_state(),
                    prev_state=state,
                    public_state=engine.build_public_state(),
                )
                state = saved_state
                timers = TimerService.build(saved_state) or {}
                for event in events:
                    event_name = _EventEmitter.resolve_texas(event)
                    if not event_name:
                        continue
                    if event_name == SocketEvent.TX_PHASE_CHANGE and timers:
                        payload = event.get("payload") or {}
                        payload["timers"] = timers
                        event["payload"] = payload
                    await EventService.log_room_event(room_id, event_name, event)
                    await emit_room_event(sio, room_id, event_name, ok(event), private=False)

                if engine.phase == TexasPhase.FINISHED:
                    result = await TexasSettlementService.settle(engine)
                    await SettlementEmitter.emit_texas(sio, room_id, result)
                    break
                actions_taken += 1
                if actions_taken >= max_auto_actions:
                    logger.warning(
                        "texas_auto_action_limit room_id=%s actor_id=%s", room_id, actor_id
                    )
                    break
                new_actor = engine.get_state().get("actor_id")
                if new_actor == prev_actor:
                    logger.warning("texas_actor_stuck room_id=%s actor_id=%s", room_id, actor_id)
                    break
                if idle_expired and not offline_expired:
                    break
