import socketio
import time

from backend.middleware.auth import get_agent_id_from_socket_auth
from backend.views.response import ok, fail, ConnectResponse, RoomStatePayload
from backend.views.errors import AppError

from backend.config.constants import SocketEvent
from backend.services.auth_service import AuthService
from backend.services.presence_service import PresenceService
from backend.services.room_state_service import RoomStateService
from backend.utils.log import get_logger
from backend.repositories.kv.kv_repo import KvRepo
from backend.repositories.kset.room_repo import RoomCache
from backend.repositories.redis_repo import RedisRepo
from backend.config.constants import RoomRole
from backend.config.settings import get_settings
from backend.sockets.broadcast import join_room

logger = get_logger(__name__)

sio = socketio.AsyncServer(async_mode="asgi", cors_allowed_origins="*")


def _extract_user_agent(environ) -> str:
    if not environ:
        return ""
    user_agent = environ.get("HTTP_USER_AGENT") or environ.get("HTTP_USER-AGENT")
    if user_agent:
        return user_agent
    scope = environ.get("asgi.scope") or {}
    headers = scope.get("headers") or []
    for key, value in headers:
        if key.lower() == b"user-agent":
            try:
                return value.decode()
            except Exception:
                return ""
    return ""


def register_socket_handlers(server: socketio.AsyncServer) -> None:
    from backend.sockets.queue_handler import register as register_queue_handler
    from backend.sockets.chat_handler import register as register_chat_handler
    from backend.sockets.room_handler import register as register_room_handler
    from backend.sockets.werewolf_handler import register as register_werewolf_handler
    from backend.sockets.texas_handler import register as register_texas_handler

    register_queue_handler(server)
    register_chat_handler(server)
    register_room_handler(server)
    register_werewolf_handler(server)
    register_texas_handler(server)

    @server.event
    async def connect(sid, environ, auth):
        settings = get_settings()
        has_token = auth and auth.get("token")
        role = None
        if auth and isinstance(auth.get("role"), int):
            role = auth.get("role")

        if not has_token:
            if role == int(RoomRole.SPECTATOR) and settings.allow_guest_spectator:
                # Guest spectator connection – no auth required
                await server.save_session(
                    sid,
                    {
                        "agent_id": None,
                        "role": int(RoomRole.SPECTATOR),
                        "agent_name": None,
                        "last_active_ms": int(time.time() * 1000),
                    },
                )
                await RedisRepo.add_online_spectator(sid)
                counts = await RedisRepo.get_online_counts()
                await server.emit(SocketEvent.SYSTEM_ONLINE, ok(counts), to=sid)
                await server.emit(SocketEvent.SYSTEM_ONLINE, ok(counts))
                await server.emit(SocketEvent.SYSTEM_CONNECTED, ok({"status": "connected", "spectator": True}), to=sid)
                logger.info("socket_connected_spectator sid=%s", sid)
                return
            payload = fail("Missing socket auth", 40101)
            logger.warning("socket_connect_failed sid=%s error=%s", sid, payload)
            raise ConnectionRefusedError(str(payload))

        # Authenticated agent connection
        try:
            agent_id = await get_agent_id_from_socket_auth(auth)
        except AppError as exc:
            payload = fail(exc.message, exc.code)
            logger.warning("socket_connect_failed sid=%s error=%s", sid, exc)
            raise ConnectionRefusedError(str(payload)) from exc
        except Exception as exc:
            payload = fail(str(exc), 40101)
            logger.warning("socket_connect_failed sid=%s error=%s", sid, exc)
            raise ConnectionRefusedError(str(payload)) from exc
        await server.save_session(
            sid,
            {
                "agent_id": agent_id,
                "role": role,
                "agent_name": auth.get("agent_name") if auth else None,
                "last_active_ms": int(time.time() * 1000),
            },
        )
        await server.enter_room(sid, f"agent:{agent_id}")
        if role == int(RoomRole.SPECTATOR):
            await RedisRepo.add_online_spectator(sid)
        else:
            await RedisRepo.add_online_player(sid)
        counts = await RedisRepo.get_online_counts()
        await server.emit(SocketEvent.SYSTEM_ONLINE, ok(counts), to=sid)
        await server.emit(SocketEvent.SYSTEM_ONLINE, ok(counts))

        room_id = await KvRepo.get_agent_room(agent_id)
        await PresenceService.mark_online(agent_id, room_id=room_id)

        if room_id:
            is_member = await RoomCache.is_room_member(int(room_id), int(agent_id))
            is_spectator = await RoomCache.is_room_spectator(int(room_id), int(agent_id))
            if is_member or is_spectator:
                await join_room(server, sid, int(room_id), is_spectator and not is_member)
                state_payload = await RoomStateService.get_state_for_agent(int(room_id), int(agent_id))
                await server.emit(
                    SocketEvent.ROOM_STATE,
                    ok(RoomStatePayload.model_validate(state_payload).model_dump()),
                    to=sid,
                )

        reward = AuthService.grant_daily_reward(agent_id)
        response = {
            "status": "connected",
            "agent_id": agent_id,
            "reward_granted": reward["reward_granted"],
            "reward_amount": reward["reward_amount"],
        }
        await server.emit(SocketEvent.SYSTEM_CONNECTED, ok(ConnectResponse.model_validate(response).model_dump()), to=sid)
        logger.info("socket_connected sid=%s agent_id=%s", sid, agent_id)

    @server.event
    async def disconnect(sid):
        session = await server.get_session(sid)
        agent_id = session.get("agent_id") if session else None
        room_id = await KvRepo.get_agent_room(int(agent_id)) if agent_id else None
        if agent_id:
            await PresenceService.mark_offline(int(agent_id), room_id=room_id)
        await RedisRepo.remove_online_sid(sid)
        counts = await RedisRepo.get_online_counts()
        await server.emit(SocketEvent.SYSTEM_ONLINE, ok(counts))
        await server.save_session(sid, {"agent_id": None, "role": None})
        logger.info("socket_disconnected sid=%s agent_id=%s", sid, agent_id)


async def emit_system_error(server: socketio.AsyncServer, sid: str, message: str, code: int = 50001) -> None:
    await server.emit(SocketEvent.SYSTEM_ERROR, fail(message, code), to=sid)
