import asyncio
import time
from datetime import datetime, timedelta
from decimal import Decimal

from backend.config.constants import DEFAULT_ENTRY_FEE, GameEventType, GameStatus, GameType, RoomState, SocketEvent, TexasAction, TexasPhase, WerewolfAction, WerewolfPhase, WerewolfWinner
from backend.config.settings import get_settings
from backend.domain.werewolf.engine import WerewolfEngine
from backend.domain.texas.engine import TexasEngine
from backend.repositories.db import db_session
from backend.repositories.game_player_repo import GamePlayerRepo
from backend.repositories.game_repo import GameRepo
from backend.repositories.redis_repo import RedisRepo
from backend.repositories.wallet_repo import WalletRepo
from backend.services.event_service import EventService
from backend.services.game_state_service import GameStateService
from backend.services.presence_service import PresenceService
from backend.services.timer_service import TimerService
from backend.services.texas_settlement_service import TexasSettlementService
from backend.services.werewolf_settlement_service import WerewolfSettlementService
from backend.services.settlement_emitter import SettlementEmitter
from backend.utils.money import to_token
from backend.utils.action_guard import ActionGuard
from backend.views.response import ok
from backend.views.errors import DomainError
from backend.sockets.broadcast import emit_room_event
from backend.sockets.server import sio
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
            return SocketEvent.WW_CHAT_WOLF, False
        if action_type == WerewolfAction.SPEAK.value:
            return SocketEvent.WW_CHAT_DAY, False
        if action_type == WerewolfAction.VOTE.value:
            return SocketEvent.WW_DAY_VOTE, False
        return SocketEvent.WW_NIGHT_ACTION, False

    @staticmethod
    def resolve_texas(event: dict) -> str | None:
        event_type = event.get("event_type")
        if event_type == GameEventType.PHASE_CHANGE:
            return SocketEvent.TX_PHASE_CHANGE
        if event_type == "hand_result":
            return SocketEvent.TX_HAND_RESULT
        action_type = event.get("action_type")
        if action_type not in {a.value for a in TexasAction}:
            return None
        action_name = TexasAction(action_type).name.lower()
        return f"tx:{action_name}"


class OfflineMonitorService:
    _texas_deadline_seeded = False
    _texas_deadline_seeded_at_ms: int | None = None

    @staticmethod
    def _presence_active(presence: dict | None, room_id: int | None, now_ms: int, stale_seconds: int | None = None) -> bool:
        if not presence:
            return False
        if presence.get("status") in {"offline", "left"}:
            return False
        if room_id is not None:
            try:
                if presence.get("room_id") is not None and int(presence.get("room_id")) != int(room_id):
                    return False
            except Exception:
                pass
        if stale_seconds and stale_seconds > 0:
            ts_ms = int(presence.get("ts_ms", 0))
            if ts_ms and now_ms - ts_ms >= stale_seconds * 1000:
                return False
        return True

    @staticmethod
    async def _acquire_action_lock(room_id: int, ttl_ms: int = 3000) -> ActionGuard | None:
        # 使用 ActionGuard，设置较短的 timeout (0.5s) 以避免阻塞监控循环
        # key_prefix="lock:action" 与 GameActionService 保持一致
        try:
            guard = ActionGuard(room_id, timeout=0.5, lock_ttl_ms=ttl_ms, key_prefix="lock:action")
            await guard.__aenter__()
            return guard
        except DomainError:
            # 捕获 409 错误，返回 None 表示未获取到锁
            return None
        except Exception as e:
            logger.warning(f"monitor_lock_error room_id={room_id} error={e}")
            return None

    @staticmethod
    async def _seed_texas_deadlines(room_ids: list[int], now_ms: int, timeout_seconds: int) -> None:
        for room_id in room_ids:
            state = await GameStateService.get_state(room_id)
            if not state or int(state.get("game_type", 0)) != int(GameType.TEXAS):
                continue
            if state.get("phase") == TexasPhase.FINISHED:
                await RedisRepo.remove_texas_turn_deadline(room_id)
                continue
            meta = state.get("meta") or {}
            turn_started_ms = int(meta.get("turn_started_ms") or now_ms)
            deadline_ms = turn_started_ms + timeout_seconds * 1000
            await RedisRepo.set_texas_turn_deadline(room_id, deadline_ms)
    @staticmethod
    async def run_loop() -> None:
        settings = get_settings()
        interval = settings.offline_check_interval_seconds
        log_every = max(1, int(60 / max(1, interval)))
        tick = 0
        while True:
            try:
                await OfflineMonitorService.check_werewolf()
                await OfflineMonitorService.check_texas()
                tick += 1
                if tick % log_every == 0:
                    logger.info("offline_monitor_tick tick=%s interval=%ss", tick, interval)
                if tick % 10 == 0:
                    await OfflineMonitorService.check_stale_games()
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
            # 获取 action 锁，防止与 GameActionService 并发导致状态覆盖
            # 这里的 timeout 设置为 0.5s，避免阻塞监控循环太久
            guard = await OfflineMonitorService._acquire_action_lock(room_id)
            if not guard:
                continue
            
            try:
                state = await GameStateService.get_state(room_id)
                if not state or int(state.get("game_type", 0)) != int(GameType.WEREWOLF):
                    continue
                engine = WerewolfEngine.from_state(state)
                if engine.phase == WerewolfPhase.FINISHED:
                    try:
                        result = await WerewolfSettlementService.settle(engine)
                        if result.get("status") in {"settled", "already_settled"}:
                            await RedisRepo.remove_active_room(room_id)
                    except DomainError as exc:
                        logger.warning("werewolf_settlement_failed room_id=%s error=%s", room_id, exc)
                    continue

                events_to_emit: list[dict] = []
                if engine.phase == WerewolfPhase.LOBBY:
                    timeout_seconds = int(settings.werewolf_lobby_timeout_seconds or 0)
                    if timeout_seconds > 0:
                        meta = state.get("meta") or {}
                        phase_started_ms = int(meta.get("phase_started_ms") or now_ms)
                        if now_ms - phase_started_ms >= timeout_seconds * 1000:
                            alive = engine.get_state().get("alive", [])
                            any_online = False
                            for agent_id in alive:
                                presence = await PresenceService.get(int(agent_id))
                                if OfflineMonitorService._presence_active(
                                    presence,
                                    room_id=room_id,
                                    now_ms=now_ms,
                                    stale_seconds=settings.werewolf_offline_death_seconds,
                                ):
                                    any_online = True
                                    break
                            if any_online:
                                engine._ready = set(engine._alive)
                                engine._start_night(events_to_emit, is_new_day=True)
                            else:
                                winner = WerewolfWinner.NO_CONTEST
                                engine._winner = winner
                                engine._set_phase(WerewolfPhase.FINISHED)
                                events_to_emit.append(
                                    engine._phase_event(engine._phase_payload({"winner": winner, "reason": "all_offline"}))
                                )
                    if not events_to_emit:
                        continue
                else:
                    alive = engine.get_state().get("alive", [])
                    if not alive:
                        winner = engine._check_winner() or WerewolfWinner.VILLAGERS
                        engine._winner = winner
                        engine._set_phase(WerewolfPhase.FINISHED)
                        events_to_emit.append(engine._phase_event(engine._phase_payload({"winner": winner, "reason": "no_alive"})))
                    else:
                        all_offline = True
                        latest_ts_ms = 0
                        for agent_id in alive:
                            presence = await PresenceService.get(int(agent_id))
                            if OfflineMonitorService._presence_active(
                                presence,
                                room_id=room_id,
                                now_ms=now_ms,
                                stale_seconds=settings.werewolf_offline_death_seconds,
                            ):
                                all_offline = False
                                break
                            ts_ms = int((presence or {}).get("ts_ms", 0))
                            if ts_ms > latest_ts_ms:
                                latest_ts_ms = ts_ms

                        if all_offline:
                            threshold_ms = int(settings.werewolf_all_offline_seconds * 1000)
                            offline_age_ms = now_ms - latest_ts_ms
                            if threshold_ms <= 0 or offline_age_ms >= threshold_ms:
                                winner = WerewolfWinner.NO_CONTEST
                                engine._winner = winner
                                engine._set_phase(WerewolfPhase.FINISHED)
                                events_to_emit.append(
                                    engine._phase_event(engine._phase_payload({"winner": winner, "reason": "all_offline"}))
                                )
                            else:
                                continue
                        else:
                            for agent_id in alive:
                                presence = await PresenceService.get(int(agent_id))
                                if OfflineMonitorService._presence_active(
                                    presence,
                                    room_id=room_id,
                                    now_ms=now_ms,
                                    stale_seconds=settings.werewolf_offline_death_seconds,
                                ):
                                    continue
                                ts_ms = int((presence or {}).get("ts_ms", 0))
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
                    envelope = await EventService.log_room_event(room_id, event_name, event)
                    await emit_room_event(sio, room_id, event_name, ok(envelope), private=private)
            finally:
                await guard.__aexit__(None, None, None)

    @staticmethod
    async def check_texas() -> None:
        settings = get_settings()
        now_ms = int(time.time() * 1000)
        rooms = await RedisRepo.get_due_texas_rooms(now_ms)
        if not rooms:
            seed_interval_ms = max(60_000, int(settings.match_interval_seconds) * 1000 * 60)
            should_seed = (
                not OfflineMonitorService._texas_deadline_seeded
                or OfflineMonitorService._texas_deadline_seeded_at_ms is None
                or now_ms - OfflineMonitorService._texas_deadline_seeded_at_ms >= seed_interval_ms
            )
            if should_seed:
                active_rooms = await RedisRepo.get_active_rooms()
                if active_rooms:
                    await OfflineMonitorService._seed_texas_deadlines(
                        active_rooms,
                        now_ms=now_ms,
                        timeout_seconds=int(settings.texas_action_timeout_seconds),
                    )
                OfflineMonitorService._texas_deadline_seeded = True
                OfflineMonitorService._texas_deadline_seeded_at_ms = now_ms
                rooms = await RedisRepo.get_due_texas_rooms(now_ms)
            if not rooms:
                return

        for room_id in rooms:
            guard = await OfflineMonitorService._acquire_action_lock(room_id)
            if not guard:
                logger.info("texas_action_lock_busy room_id=%s", room_id)
                continue
            try:
                state_saved = False
                state = await GameStateService.get_state(room_id)
                if not state or int(state.get("game_type", 0)) != int(GameType.TEXAS):
                    await RedisRepo.remove_texas_turn_deadline(room_id)
                    continue
                try:
                    engine = TexasEngine.from_state(state)
                except DomainError as exc:
                    if exc.code == 50031:
                        logger.warning("texas_replay_mismatch_reset room_id=%s", room_id)
                        sanitized = dict(state)
                        sanitized["hand_actions"] = []
                        sanitized["end_votes"] = {}
                        engine = TexasEngine.from_state(sanitized)
                        await GameStateService.save_state(
                            room_id,
                            engine.dump_state(),
                            prev_state=state,
                            public_state=engine.build_public_state(),
                        )
                        state_saved = True
                        continue
                    raise
                if engine.phase == TexasPhase.FINISHED:
                    try:
                        result = await TexasSettlementService.settle(engine)
                        await SettlementEmitter.emit_texas(sio, room_id, result)
                        if result.get("status") in {"settled", "already_settled"}:
                            await RedisRepo.remove_active_room(room_id)
                    except DomainError as exc:
                        logger.warning("texas_settlement_failed room_id=%s error=%s", room_id, exc)
                    await RedisRepo.remove_texas_turn_deadline(room_id)
                    continue

                player_ids = [int(p.get("agent_id")) for p in (engine.players or []) if p.get("agent_id") is not None]
                if player_ids:
                    all_offline = True
                    for agent_id in player_ids:
                        presence = await PresenceService.get(int(agent_id))
                        if presence and presence.get("status") not in {"offline", "left"}:
                            all_offline = False
                            break
                    if all_offline:
                        engine._phase = TexasPhase.FINISHED
                        event = engine._phase_event(engine._phase_payload({"reason": "all_offline"}))
                        await GameStateService.save_state(
                            room_id,
                            engine.dump_state(),
                            prev_state=state,
                            public_state=engine.build_public_state(),
                        )
                        state_saved = True
                        envelope = await EventService.log_room_event(room_id, SocketEvent.TX_PHASE_CHANGE, event)
                        await emit_room_event(sio, room_id, SocketEvent.TX_PHASE_CHANGE, ok(envelope), private=False)
                        result = await TexasSettlementService.settle(engine)
                        await SettlementEmitter.emit_texas(sio, room_id, result)
                        continue

                meta = state.get("meta") or {}
                turn_started_ms = int(meta.get("turn_started_ms") or now_ms)
                schedule_deadline_ms = turn_started_ms + settings.texas_action_timeout_seconds * 1000
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
                    logger.info(
                        "texas_auto_fold room_id=%s actor_id=%s reason=%s",
                        room_id,
                        actor_id,
                        reason,
                    )
                    events = engine.apply_action(
                        int(actor_id),
                        int(TexasAction.FOLD),
                        {"meta": {"auto": True, "reason": reason}},
                    )
                    next_actor_id = engine.get_state().get("actor_id")
                    if next_actor_id is not None:
                        for event in events:
                            event["next_actor_id"] = int(next_actor_id)
                    turn_started_ms = now_ms
                    updated_state = await GameStateService.save_state(
                        room_id,
                        engine.dump_state(),
                        prev_state=state,
                        public_state=engine.build_public_state(),
                    )
                    state_saved = True
                    state = updated_state
                    timers = TimerService.build(updated_state) or {}
                    for event in events:
                        event_name = _EventEmitter.resolve_texas(event)
                        if not event_name:
                            continue
                        if event_name == SocketEvent.TX_PHASE_CHANGE and timers:
                            payload = event.get("payload") or {}
                            payload["timers"] = timers
                            event["payload"] = payload
                        if event_name == SocketEvent.TX_HAND_RESULT:
                            hand_index = event.get("payload", {}).get("hand_index")
                            if hand_index is not None:
                                ok_emit = await RedisRepo.set_hand_result_emitted(room_id, int(hand_index))
                                if not ok_emit:
                                    continue
                        envelope = await EventService.log_room_event(room_id, event_name, event)
                        await emit_room_event(sio, room_id, event_name, ok(envelope), private=False)

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
                if not state_saved:
                    await RedisRepo.set_texas_turn_deadline(room_id, schedule_deadline_ms)
            finally:
                await guard.__aexit__(None, None, None)

    @staticmethod
    async def check_stale_games() -> None:
        settings = get_settings()
        cutoff = datetime.utcnow() - timedelta(seconds=settings.stale_game_threshold_seconds)
        statuses = [int(GameStatus.ACTIVE), int(GameStatus.SETTLING)]
        games = GameRepo.find_stale(statuses, before=cutoff)
        if not games:
            return

        for game in games:
            try:
                players = GamePlayerRepo.list_by_game(int(game.id))
                if not players:
                    GameRepo.update_status(int(game.id), int(GameStatus.ENDED), ended_at=datetime.utcnow())
                    continue

                entry_fee = to_token(Decimal(game.prize_pool_tokens or 0) / len(players))
                if entry_fee <= 0:
                    entry_fee = to_token(DEFAULT_ENTRY_FEE)

                with db_session() as session:
                    for player in players:
                        WalletRepo.unlock_tokens(int(player.agent_id), entry_fee, session=session)
                    GameRepo.update_status(int(game.id), int(GameStatus.ENDED), ended_at=datetime.utcnow(), session=session)

                room_id = int(players[0].room_id) if players else None
                if room_id:
                    from backend.services.room_service import RoomService

                    await RoomService.update_state(room_id, int(RoomState.FINISHED))
                    await RoomService.broadcast_update(room_id, "game_finish")
                    await RedisRepo.remove_active_room(room_id)

                logger.warning(
                    "stale_game_refunded game_id=%s players=%s entry_fee=%s",
                    game.id, len(players), entry_fee,
                )
            except Exception as exc:
                logger.error("stale_game_refund_failed game_id=%s error=%s", game.id, exc)
