from backend.services.room_state_service import RoomStateService
from backend.middleware.decorators import socket_handler
from backend.views.requests import RoomJoinRequest
from backend.config.constants import RoomRole, SocketEvent
from backend.sockets.guards import socket_rate_limit, socket_validate, validate_response, socket_require_role
from backend.views.response import RoomJoinResponse, RoomLeaveResponse, RoomStatePayload, RoomUpdatePayload, ok
from backend.sockets.broadcast import join_room, leave_room, emit_room_event
from backend.services.event_service import EventService
from backend.repositories.redis_repo import RedisRepo
from backend.repositories.kset.room_repo import RoomCache
from backend.repositories.kv.kv_repo import KvRepo


def register(server):
    from backend.services.room_service import RoomService

    @server.on(SocketEvent.ROOM_JOIN)
    @socket_handler(server)
    @socket_validate(RoomJoinRequest)
    @socket_require_role(server, None)
    @socket_rate_limit(server, "10/minute")
    async def room_join(sid, agent_id, payload):
        is_spectator = payload.role == RoomRole.SPECTATOR
        if is_spectator and agent_id is None:
            await join_room(server, sid, payload.room_id, True)
            state_payload = await RoomStateService.get_state_for_spectator(payload.room_id)
            await server.emit(
                SocketEvent.ROOM_STATE,
                ok(RoomStatePayload.model_validate(state_payload).model_dump()),
                to=sid,
            )
            room_state = await RedisRepo.get_room_state(payload.room_id)
            members_count = await RoomCache.count_room_members(payload.room_id)
            spectators_count = await RoomCache.count_room_spectators(payload.room_id)
            update_payload = RoomUpdatePayload(
                type="room_join",
                room_id=payload.room_id,
                agent_id=None,
                role=int(payload.role),
                room_state=room_state,
                members_count=members_count,
                spectators_count=spectators_count,
            ).model_dump()
            envelope = await EventService.log_room_event(payload.room_id, SocketEvent.ROOM_UPDATE, update_payload)
            await emit_room_event(server, payload.room_id, SocketEvent.ROOM_UPDATE, ok(envelope), private=False)
            return validate_response(RoomJoinResponse, {"status": "joined", "room_id": payload.room_id, "role": int(RoomRole.SPECTATOR), "role_label": "spectator"})

        if is_spectator:
            result = await RoomService.join_as_spectator(int(agent_id), payload.room_id)
        else:
            result = await RoomService.join_as_player(int(agent_id), payload.room_id)

        await join_room(server, sid, payload.room_id, is_spectator)
        if is_spectator:
            state_payload = await RoomStateService.get_state_for_spectator(payload.room_id)
        else:
            state_payload = await RoomStateService.get_state_for_agent(payload.room_id, int(agent_id))
        await server.emit(
            SocketEvent.ROOM_STATE,
            ok(RoomStatePayload.model_validate(state_payload).model_dump()),
            to=sid,
        )
        room_state = await RedisRepo.get_room_state(payload.room_id)
        members_count = await RoomCache.count_room_members(payload.room_id)
        spectators_count = await RoomCache.count_room_spectators(payload.room_id)
        update_payload = RoomUpdatePayload(
            type="room_join",
            room_id=payload.room_id,
            agent_id=int(agent_id),
            role=int(payload.role),
            room_state=room_state,
            members_count=members_count,
            spectators_count=spectators_count,
        ).model_dump()
        envelope = await EventService.log_room_event(payload.room_id, SocketEvent.ROOM_UPDATE, update_payload)
        await emit_room_event(server, payload.room_id, SocketEvent.ROOM_UPDATE, ok(envelope), private=False)
        return validate_response(RoomJoinResponse, result)

    @server.on(SocketEvent.ROOM_LEAVE)
    @socket_handler(server)
    @socket_rate_limit(server, "10/minute")
    async def room_leave(sid, payload):
        payload_data = payload or {}
        if not isinstance(payload_data, dict):
            payload_data = {}
        payload_room_id = payload_data.get("room_id")
        payload_role = payload_data.get("role")
        role_value = None
        if payload_role is not None:
            try:
                role_value = int(payload_role)
            except Exception:
                role_value = None

        session = await server.get_session(sid)
        agent_id = session.get("agent_id") if session else None

        if agent_id is not None:
            try:
                current_room_id = await KvRepo.get_agent_room(int(agent_id))
            except Exception:
                current_room_id = None
            if role_value == int(RoomRole.SPECTATOR) and payload_room_id:
                if not current_room_id or int(payload_room_id) != int(current_room_id):
                    await leave_room(server, sid, int(payload_room_id))
                    return validate_response(RoomLeaveResponse, {"status": "left", "room_id": int(payload_room_id)})

            result = await RoomService.leave(int(agent_id))
            if result.get("room_id"):
                await leave_room(server, sid, result["room_id"])
                room_state = await RedisRepo.get_room_state(result["room_id"])
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
                ).model_dump()
                envelope = await EventService.log_room_event(result["room_id"], SocketEvent.ROOM_UPDATE, update_payload)
                await emit_room_event(server, result["room_id"], SocketEvent.ROOM_UPDATE, ok(envelope), private=False)
            return validate_response(RoomLeaveResponse, result)

        if payload_room_id:
            await leave_room(server, sid, int(payload_room_id))
            return validate_response(RoomLeaveResponse, {"status": "left", "room_id": int(payload_room_id)})
        return validate_response(RoomLeaveResponse, {"status": "left", "room_id": None})
