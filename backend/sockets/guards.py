from functools import wraps
import re
import time
from typing import Type, TypeVar, Callable, Awaitable, Any

from pydantic import BaseModel

from backend.views.errors import AuthError
from backend.views.errors import ForbiddenError
from backend.config.constants import RoomRole
from backend.repositories.kset.room_repo import RoomCache
from backend.repositories.redis_client import get_client
from backend.views.response import fail
from backend.config.constants import SocketEvent
from backend.config.settings import get_settings
from backend.views.errors import DomainError

T = TypeVar("T", bound=BaseModel)


async def require_agent_id(server, sid) -> int:
    session = await server.get_session(sid)
    agent_id = session.get("agent_id") if session else None
    if not agent_id:
        raise AuthError("Missing socket session")
    return int(agent_id)


def validate_request(model: Type[T], data) -> T:
    return model.model_validate(data or {})


def validate_response(model: Type[T], data) -> dict:
    return model.model_validate(data).model_dump()


def socket_validate(model: Type[T]):
    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(sid, data=None, *args, **kwargs):
            payload = validate_request(model, data)
            return await func(sid, payload, *args, **kwargs)

        return wrapper

    return decorator


def socket_require_agent(server):
    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(sid, *args, **kwargs):
            agent_id = await require_agent_id(server, sid)
            try:
                from backend.repositories.kv.kv_repo import KvRepo
                from backend.services.presence_service import PresenceService

                room_id = await KvRepo.get_agent_room(agent_id)
                await PresenceService.touch(agent_id, room_id=room_id, force=True)
            except Exception:
                pass
            return await func(sid, agent_id, *args, **kwargs)

        return wrapper

    return decorator


def socket_require_role(server, required_role: RoomRole | None, allow_guest: bool | None = None):
    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(sid, payload=None, *args, **kwargs):
            settings = get_settings()
            role = getattr(payload, "role", None)
            session = await server.get_session(sid)
            agent_id = session.get("agent_id") if session else None
            guest_allowed = settings.allow_guest_spectator if allow_guest is None else allow_guest
            if agent_id is not None:
                try:
                    from backend.repositories.kv.kv_repo import KvRepo
                    from backend.services.presence_service import PresenceService

                    room_id = await KvRepo.get_agent_room(int(agent_id))
                    await PresenceService.touch(int(agent_id), room_id=room_id, force=True)
                except Exception:
                    pass

            if role == RoomRole.SPECTATOR:
                if required_role is not None and required_role != RoomRole.SPECTATOR:
                    raise ForbiddenError("spectator_readonly")
                if agent_id is None and not guest_allowed:
                    raise ForbiddenError("spectator_readonly")
                return await func(sid, agent_id, payload, *args, **kwargs)

            if required_role == RoomRole.SPECTATOR:
                raise ForbiddenError("spectator_readonly")

            agent_id = await require_agent_id(server, sid)
            return await func(sid, agent_id, payload, *args, **kwargs)

        return wrapper

    return decorator


def socket_require_room_player(server):
    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(sid, agent_id, payload=None, *args, **kwargs):
            room_id = getattr(payload, "room_id", None) if payload else None
            if not room_id:
                raise AuthError("Missing room_id")
            if not await RoomCache.is_room_member(int(room_id), int(agent_id)):
                raise ForbiddenError("spectator_readonly")
            return await func(sid, agent_id, payload, *args, **kwargs)

        return wrapper

    return decorator


def _parse_rate_limit(limit: str) -> tuple[int, int]:
    raw = limit.strip().lower()
    parts = raw.split("/", 1)
    if len(parts) != 2:
        raise ValueError("invalid_rate_limit")
    count = int(parts[0])
    window_raw = parts[1].strip()
    match = re.match(r"^(?:(\d+)\s*)?(s|sec|second|m|min|minute|h|hour|d|day)$", window_raw)
    if not match:
        raise ValueError("invalid_rate_limit")
    value = int(match.group(1) or 1)
    unit = match.group(2)
    unit_seconds = {
        "s": 1,
        "sec": 1,
        "second": 1,
        "m": 60,
        "min": 60,
        "minute": 60,
        "h": 3600,
        "hour": 3600,
        "d": 86400,
        "day": 86400,
    }[unit]
    return count, value * unit_seconds


def socket_rate_limit(server, limit: str, key_prefix: str | None = None):
    max_count, window_seconds = _parse_rate_limit(limit)
    settings = get_settings()

    if settings.debug:
        def decorator(func: Callable[..., Awaitable[Any]]):
            @wraps(func)
            async def wrapper(sid, *args, **kwargs):
                return await func(sid, *args, **kwargs)
            return wrapper
        return decorator

    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(sid, *args, **kwargs):
            session = await server.get_session(sid)
            agent_id = session.get("agent_id") if session else None
            identifier = agent_id if agent_id is not None else sid
            window_id = int(time.time() // window_seconds)
            prefix = key_prefix or func.__name__
            key = f"rl:socket:{prefix}:{identifier}:{window_id}"
            client = get_client()
            current = await client.incr(key)
            if current == 1:
                await client.expire(key, window_seconds + 1)
            if current > max_count:
                payload = fail("Rate limited", 42901)
                if sid:
                    await server.emit(SocketEvent.SYSTEM_ERROR, payload, to=sid)
                return payload
            return await func(sid, *args, **kwargs)

        return wrapper

    return decorator


def socket_dedupe_action(server, ttl_seconds: int | None = None):
    settings = get_settings()
    ttl = ttl_seconds or settings.action_id_ttl_seconds

    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(sid, agent_id, payload, *args, **kwargs):
            action_id = getattr(payload, "action_id", None)
            if not action_id:
                raise DomainError("missing_action_id", code=40070)
            key = f"dedupe:action:{agent_id}:{action_id}"
            client = get_client()
            ok = await client.set(key, "1", ex=ttl, nx=True)
            if not ok:
                raise DomainError("duplicate_action", code=40902)
            return await func(sid, agent_id, payload, *args, **kwargs)

        return wrapper

    return decorator
