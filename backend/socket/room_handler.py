from backend.services.room_service import RoomService
from backend.services.room_state_service import RoomStateService
from backend.middleware.decorators import socket_handler
from backend.views.requests import RoomJoinRequest
from backend.config.constants import RoomRole, SocketEvent
from backend.socket.guards import socket_rate_limit, socket_require_agent, socket_validate, validate_response
from backend.views.response import RoomJoinResponse, RoomLeaveResponse, RoomStatePayload, RoomUpdatePayload, ok
from backend.socket.broadcast import join_room, leave_room, emit_room_event
from backend.services.event_service import EventService
from backend.repositories.redis_repo import RedisRepo
from backend.repositories.kset.room_repo import RoomCache


def register(server):
    @server.on(SocketEvent.ROOM_JOIN)
    @socket_validate(RoomJoinRequest)
    @socket_require_agent(server)
    @socket_rate_limit(server, "10/minute")
    @socket_handler(server)
    async def room_join(sid, agent_id, payload):
        if payload.role == RoomRole.SPECTATOR:
            result = await RoomService.join_as_spectator(agent_id, payload.room_id)
        else:
            result = await RoomService.join_as_player(agent_id, payload.room_id)
        await join_room(server, sid, payload.room_id, payload.role == RoomRole.SPECTATOR)
        state_payload = await RoomStateService.get_state_for_agent(payload.room_id, agent_id)
        await server.emit(
            SocketEvent.ROOM_STATE,
            ok(RoomStatePayload.model_validate(state_payload).model_dump()),
            to=sid,
        )
        room_state = await RedisRepo.get_room_state(payload.room_id)
        ts_ms = await EventService.log_room_event(
            payload.room_id,
            "room_join",
            {"agent_id": agent_id, "role": int(payload.role)},
        )
        members_count = await RoomCache.count_room_members(payload.room_id)
        spectators_count = await RoomCache.count_room_spectators(payload.room_id)
        update_payload = RoomUpdatePayload(
            type="room_join",
            room_id=payload.room_id,
            agent_id=agent_id,
            role=int(payload.role),
            room_state=room_state,
            members_count=members_count,
            spectators_count=spectators_count,
            ts_ms=ts_ms,
        ).model_dump()
        await emit_room_event(server, payload.room_id, SocketEvent.ROOM_UPDATE, ok(update_payload), private=False)
        return validate_response(RoomJoinResponse, result)

    @server.on(SocketEvent.ROOM_LEAVE)
    @socket_require_agent(server)
    @socket_rate_limit(server, "10/minute")
    @socket_handler(server)
    async def room_leave(sid, agent_id, data):
        result = await RoomService.leave(agent_id)
        if result.get("room_id"):
            await leave_room(server, sid, result["room_id"])
            room_state = await RedisRepo.get_room_state(result["room_id"])
            ts_ms = await EventService.log_room_event(
                result["room_id"],
                "room_leave",
                {"agent_id": agent_id},
            )
            members_count = await RoomCache.count_room_members(result["room_id"])
            spectators_count = await RoomCache.count_room_spectators(result["room_id"])
            update_payload = RoomUpdatePayload(
                type="room_leave",
                room_id=result["room_id"],
                agent_id=agent_id,
                role=None,
                room_state=room_state,
                members_count=members_count,
                spectators_count=spectators_count,
                ts_ms=ts_ms,
            ).model_dump()
            await emit_room_event(server, result["room_id"], SocketEvent.ROOM_UPDATE, ok(update_payload), private=False)
        return validate_response(RoomLeaveResponse, result)
