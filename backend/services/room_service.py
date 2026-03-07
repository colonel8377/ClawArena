from datetime import datetime

from backend.repositories.kv.kv_repo import KvRepo
from backend.repositories.kset.room_repo import RoomCache
from backend.repositories.room_repo import RoomRepo
from backend.views.errors import DomainError
from backend.config.constants import PlayerResult, PlayerStatus, RoomRole, RoomState, SocketEvent
from backend.middleware.decorators import sync_room_state
from backend.repositories.redis_repo import RedisRepo
from backend.repositories.game_player_repo import GamePlayerRepo
from backend.services.event_service import EventService
from backend.services.game_action_service import GameActionService
from backend.services.presence_service import PresenceService
from backend.utils.log import get_logger
from backend.views.response import RoomUpdatePayload, ok

logger = get_logger(__name__)


class RoomService:
    @staticmethod
    @sync_room_state()
    async def create_room(game_id: int, min_players: int, max_players: int) -> dict:
        room = RoomRepo.create(game_id, min_players, max_players, int(RoomState.IDLE))
        logger.info("room_create room_id=%s game_id=%s", room.id, game_id)
        return {"room_id": room.id, "room_state": int(RoomState.IDLE)}

    @staticmethod
    @sync_room_state()
    async def update_state(room_id: int, room_state: int) -> dict:
        ended_at = datetime.utcnow() if room_state == int(RoomState.FINISHED) else None
        room = RoomRepo.update_state(room_id, room_state, ended_at)
        if not room:
            raise DomainError("room_not_found", code=40402)
        if room_state == int(RoomState.FINISHED):
            await RedisRepo.remove_active_room(room_id)
        logger.info("room_state_update room_id=%s room_state=%s", room_id, room_state)
        return {"room_id": room_id, "room_state": room_state}

    @staticmethod
    async def join_as_player(agent_id: int, room_id: int) -> dict:
        room = RoomRepo.get_by_id(room_id)
        if not room:
            raise DomainError("room_not_found", code=40402)

        await RoomCache.add_room_member(room_id, agent_id)
        await KvRepo.set_agent_room(agent_id, room_id)
        logger.info("room_join player agent_id=%s room_id=%s", agent_id, room_id)
        return {"status": "joined", "room_id": room_id, "role": int(RoomRole.PLAYER), "role_label": "player"}

    @staticmethod
    async def join_as_spectator(agent_id: int, room_id: int) -> dict:
        room = RoomRepo.get_by_id(room_id)
        if not room:
            raise DomainError("room_not_found", code=40402)

        await RoomCache.add_room_spectator(room_id, agent_id)
        await KvRepo.set_agent_room(agent_id, room_id)
        logger.info("room_join spectator agent_id=%s room_id=%s", agent_id, room_id)
        return {"status": "joined", "room_id": room_id, "role": int(RoomRole.SPECTATOR), "role_label": "spectator"}

    @staticmethod
    async def leave(agent_id: int) -> dict:
        room_id = await KvRepo.get_agent_room(agent_id)
        if not room_id:
            return {"status": "left", "room_id": None}

        was_member = await RoomCache.is_room_member(room_id, agent_id)
        room = RoomRepo.get_by_id(room_id)

        await RoomCache.remove_room_member(room_id, agent_id)
        await RoomCache.remove_room_spectator(room_id, agent_id)
        await KvRepo.clear_agent_room(agent_id)

        if was_member and room and int(room.room_state or 0) == int(RoomState.ACTIVE) and room.game_id:
            GamePlayerRepo.update_status_and_result(
                int(room.game_id),
                int(agent_id),
                int(PlayerStatus.LEFT),
                int(PlayerResult.EXIT),
            )
            await PresenceService.mark_left(int(agent_id), room_id=int(room_id))
            try:
                await GameActionService.handle_leave(int(room_id), int(agent_id))
            except Exception as exc:
                logger.warning("leave_engine_sync_failed room_id=%s agent_id=%s error=%s", room_id, agent_id, exc)
                from backend.sockets.server import sio

                sio.start_background_task(GameActionService.handle_leave_async, int(room_id), int(agent_id))

        logger.info("room_leave agent_id=%s room_id=%s", agent_id, room_id)
        return {"status": "left", "room_id": room_id}

    @staticmethod
    async def broadcast_update(
        room_id: int,
        update_type: str,
        agent_id: int | None = None,
        role: int | None = None,
    ) -> None:
        room_state = await RedisRepo.get_room_state(room_id)
        members_count = await RoomCache.count_room_members(room_id)
        spectators_count = await RoomCache.count_room_spectators(room_id)
        payload = {
            "type": update_type,
            "room_id": room_id,
            "agent_id": agent_id,
            "role": role,
            "room_state": room_state,
            "members_count": members_count,
            "spectators_count": spectators_count,
        }
        update_payload = RoomUpdatePayload.model_validate(payload).model_dump()
        envelope = await EventService.log_room_event(room_id, SocketEvent.ROOM_UPDATE, update_payload)
        from backend.sockets.broadcast import emit_room_event
        from backend.sockets.server import sio

        await emit_room_event(sio, room_id, SocketEvent.ROOM_UPDATE, ok(envelope), private=False)
