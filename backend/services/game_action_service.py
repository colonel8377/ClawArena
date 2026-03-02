import asyncio

from backend.config.constants import GameEventType, GameType, SocketEvent, TexasPhase, WerewolfPhase
from backend.domain.werewolf.engine import WerewolfEngine
from backend.domain.texas.engine import TexasEngine
from backend.services.event_service import EventService
from backend.services.game_state_service import GameStateService
from backend.services.timer_service import TimerService
from backend.repositories.redis_repo import RedisRepo
from backend.services.texas_settlement_service import TexasSettlementService
from backend.services.werewolf_settlement_service import WerewolfSettlementService
from backend.sockets.server import sio
from backend.services.settlement_emitter import SettlementEmitter
from backend.utils.redis_lock import RedisLock
from backend.views.response import ok
from backend.views.errors import DomainError
from backend.utils.action_guard import ActionGuard


class GameActionService:
    @staticmethod
    async def handle_werewolf(room_id: int, actor_id: int, action: int, payload: dict, action_id: str | None = None) -> list[dict]:
        async with ActionGuard(room_id, action_id) as guard:
            if guard.is_cached:
                return guard.result

            state = await GameStateService.get_state(room_id)
            if not state:
                raise DomainError("game_state_missing", code=40403)
            engine = WerewolfEngine.from_state(state)
            events = engine.apply_action(actor_id, action, payload)
            if action_id:
                for event in events:
                    event["action_id"] = action_id
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
            
            guard.set_result(events)
            return events

    @staticmethod
    async def handle_texas(room_id: int, actor_id: int, action: int, payload: dict, action_id: str | None = None) -> list[dict]:
        async with ActionGuard(room_id, action_id) as guard:
            if guard.is_cached:
                return guard.result

            state = await GameStateService.get_state(room_id)
            if not state:
                raise DomainError("game_state_missing", code=40403)
            engine = TexasEngine.from_state(state)
            events = engine.apply_action(actor_id, action, payload)
            next_actor_id = engine.get_state().get("actor_id")
            if next_actor_id is not None:
                for event in events:
                    event["next_actor_id"] = int(next_actor_id)
            if action_id:
                for event in events:
                    event["action_id"] = action_id
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
            
            guard.set_result(events)
            return events

    @staticmethod
    async def handle_action(game_type: int, room_id: int, actor_id: int, action: int, payload: dict, action_id: str | None = None) -> list[dict]:
        if game_type == int(GameType.WEREWOLF):
            return await GameActionService.handle_werewolf(room_id, actor_id, action, payload, action_id=action_id)
        if game_type == int(GameType.TEXAS):
            return await GameActionService.handle_texas(room_id, actor_id, action, payload, action_id=action_id)
        raise DomainError("unsupported_game_type", code=40022)

    @staticmethod
    async def handle_leave(room_id: int, actor_id: int) -> None:
        # 优化：使用 ActionGuard 替代手写的 RedisLock 自旋循环
        # timeout=0.2s 相当于之前的 3次 * 0.05s + 开销
        async with ActionGuard(room_id, timeout=0.2, lock_ttl_ms=3000) as guard:
            if not guard.is_acquired:
                # 如果获取锁失败，说明房间正在处理密集动作，暂缓离开处理
                return
            
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
                from backend.sockets.broadcast import emit_room_event
                from backend.sockets.server import sio

                for event in events:
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
                from backend.sockets.broadcast import emit_room_event
                from backend.sockets.server import sio

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
                return
            return

    @staticmethod
    async def handle_leave_async(room_id: int, actor_id: int) -> None:
        try:
            await GameActionService.handle_leave(room_id, actor_id)
        except Exception:
            return
