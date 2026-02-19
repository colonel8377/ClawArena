import asyncio

from backend.config.constants import GameEventType, GameType, SocketEvent, TexasPhase, WerewolfPhase
from backend.domain.werewolf.engine import WerewolfEngine
from backend.domain.texas.engine import TexasEngine
from backend.services.event_service import EventService
from backend.services.game_state_service import GameStateService
from backend.services.timer_service import TimerService
from backend.services.texas_settlement_service import TexasSettlementService
from backend.services.werewolf_settlement_service import WerewolfSettlementService
from backend.socket.server import sio
from backend.services.settlement_emitter import SettlementEmitter
from backend.utils.redis_lock import RedisLock
from backend.views.response import ok
from backend.views.errors import DomainError


class GameActionService:
    @staticmethod
    async def handle_werewolf(room_id: int, actor_id: int, action: int, payload: dict) -> list[dict]:
        lock_key = f"lock:action:{room_id}"
        async with RedisLock(lock_key, ttl_ms=3000) as lock:
            if not lock.acquired:
                raise DomainError("action_in_progress", code=40911)
            state = await GameStateService.get_state(room_id)
            if not state:
                raise DomainError("game_state_missing", code=40403)
            engine = WerewolfEngine.from_state(state)
            events = engine.apply_action(actor_id, action, payload)
            saved_state = await GameStateService.save_state(
                room_id,
                engine.dump_state(),
                prev_state=state,
                public_state=engine.build_public_state(),
            )
            timers = TimerService.build(saved_state) or {}
            if timers:
                for event in events:
                    if event.get("event_type") == GameEventType.PHASE_CHANGE:
                        payload = event.get("payload") or {}
                        payload["timers"] = timers
                        event["payload"] = payload
            if engine.phase == WerewolfPhase.FINISHED:
                await WerewolfSettlementService.settle(engine)
            return events

    @staticmethod
    async def handle_texas(room_id: int, actor_id: int, action: int, payload: dict) -> list[dict]:
        lock_key = f"lock:action:{room_id}"
        async with RedisLock(lock_key, ttl_ms=3000) as lock:
            if not lock.acquired:
                raise DomainError("action_in_progress", code=40911)
            state = await GameStateService.get_state(room_id)
            if not state:
                raise DomainError("game_state_missing", code=40403)
            engine = TexasEngine.from_state(state)
            events = engine.apply_action(actor_id, action, payload)
            saved_state = await GameStateService.save_state(
                room_id,
                engine.dump_state(),
                prev_state=state,
                public_state=engine.build_public_state(),
            )
            timers = TimerService.build(saved_state) or {}
            if timers:
                for event in events:
                    if event.get("event_type") == GameEventType.PHASE_CHANGE:
                        payload = event.get("payload") or {}
                        payload["timers"] = timers
                        event["payload"] = payload
            if engine.phase == TexasPhase.FINISHED:
                result = await TexasSettlementService.settle(engine)
                await SettlementEmitter.emit_texas(sio, room_id, result)
            return events

    @staticmethod
    async def handle_action(game_type: int, room_id: int, actor_id: int, action: int, payload: dict) -> list[dict]:
        if game_type == int(GameType.WEREWOLF):
            return await GameActionService.handle_werewolf(room_id, actor_id, action, payload)
        if game_type == int(GameType.TEXAS):
            return await GameActionService.handle_texas(room_id, actor_id, action, payload)
        raise DomainError("unsupported_game_type", code=40022)

    @staticmethod
    async def handle_leave(room_id: int, actor_id: int) -> None:
        lock_key = f"lock:action:{room_id}"
        for _ in range(3):
            async with RedisLock(lock_key, ttl_ms=3000) as lock:
                if not lock.acquired:
                    await asyncio.sleep(0.05)
                    continue
                state = await GameStateService.get_state(room_id)
                if not state:
                    return
                game_type = int(state.get("game_type") or 0)
                if game_type == int(GameType.WEREWOLF):
                    engine = WerewolfEngine.from_state(state)
                    events = engine.apply_leave(actor_id)
                    saved_state = await GameStateService.save_state(
                        room_id,
                        engine.dump_state(),
                        prev_state=state,
                        public_state=engine.build_public_state(),
                    )
                    timers = TimerService.build(saved_state) or {}
                    from backend.services.offline_monitor_service import _EventEmitter
                    from backend.socket.broadcast import emit_room_event
                    from backend.socket.server import sio

                    for event in events:
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
                    if engine.phase == WerewolfPhase.FINISHED:
                        await WerewolfSettlementService.settle(engine)
                    return

                if game_type == int(GameType.TEXAS):
                    engine = TexasEngine.from_state(state)
                    events = engine.apply_leave(actor_id)
                    saved_state = await GameStateService.save_state(
                        room_id,
                        engine.dump_state(),
                        prev_state=state,
                        public_state=engine.build_public_state(),
                    )
                    timers = TimerService.build(saved_state) or {}
                    from backend.services.offline_monitor_service import _EventEmitter
                    from backend.socket.broadcast import emit_room_event
                    from backend.socket.server import sio

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
                    return
                return
        raise DomainError("action_in_progress", code=40911)

    @staticmethod
    async def handle_leave_async(room_id: int, actor_id: int) -> None:
        try:
            await GameActionService.handle_leave(room_id, actor_id)
        except Exception:
            return
