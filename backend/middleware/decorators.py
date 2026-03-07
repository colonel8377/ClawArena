from functools import wraps
from typing import Any, Awaitable, Callable

from pydantic import ValidationError as PydanticValidationError
from backend.config.constants import SocketEvent
from backend.utils.log import get_logger
from backend.views.context import ensure_trace_id
from backend.views.response import ok, fail
from backend.views.errors import AppError, SystemError, ValidationError

logger = get_logger(__name__)

def api_handler(func: Callable[..., Awaitable[Any]]):
    @wraps(func)
    async def wrapper(*args, **kwargs):
        trace_id = ensure_trace_id()
        logger.info(f"Trace {trace_id}: {func.__name__} called with args: {args}, kwargs: {kwargs}")
        result = await func(*args, **kwargs)
        if isinstance(result, dict) and "ok" in result:
            return result
        return ok(result if isinstance(result, dict) else {"result": result})

    return wrapper


def socket_handler(server=None):
    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            ensure_trace_id()
            sid = args[0] if args else None
            if server is None:
                raise SystemError("Socket server is required for socket_handler")
            try:
                result = await func(*args, **kwargs)
                if isinstance(result, dict) and "ok" in result:
                    return result
                return ok(result if isinstance(result, dict) else {"result": result})
            except AppError as exc:
                payload = fail(exc.message, exc.code)
                if sid:
                    await server.emit(SocketEvent.SYSTEM_ERROR, payload, to=sid)
                await _log_system_error(server, sid, exc.message, exc.code, payload)
                return payload
            except PydanticValidationError as exc:
                validation_error = ValidationError(str(exc))
                payload = fail(validation_error.message, validation_error.code)
                if sid:
                    await server.emit(SocketEvent.SYSTEM_ERROR, payload, to=sid)
                await _log_system_error(server, sid, validation_error.message, validation_error.code, payload)
                return payload
            except Exception as exc:  # noqa: BLE001 - provide generic error response
                system_error = SystemError(str(exc))
                payload = fail(system_error.message, system_error.code)
                if sid:
                    await server.emit(SocketEvent.SYSTEM_ERROR, payload, to=sid)
                await _log_system_error(server, sid, system_error.message, system_error.code, payload)
                return payload

        return wrapper

    return decorator


def sync_room_state(room_id_key: str = "room_id", state_key: str = "room_state", state_value: int | None = None):
    def decorator(func: Callable[..., Awaitable[Any]]):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            result = await func(*args, **kwargs)
            try:
                room_id = None
                room_state = state_value
                if isinstance(result, dict):
                    room_id = result.get(room_id_key) or kwargs.get(room_id_key)
                    if room_state is None:
                        room_state = result.get(state_key)
                else:
                    room_id = kwargs.get(room_id_key)
                    if room_state is None:
                        room_state = kwargs.get(state_key)

                if room_id is not None and room_state is not None:
                    from backend.repositories.redis_repo import RedisRepo

                    await RedisRepo.set_room_state(int(room_id), int(room_state))
            except Exception:
                return result
            return result

        return wrapper

    return decorator
async def _log_system_error(server, sid: str | None, message: str, code: int, payload: dict) -> None:
    try:
        from backend.services.system_event_service import SystemEventService

        session = await server.get_session(sid) if sid else None
        agent_id = session.get("agent_id") if session else None
        agent_name = session.get("agent_name") if session else None
        await SystemEventService.enqueue(
            event_type="system_error",
            message=message,
            payload={**payload, "code": code},
            agent_id=agent_id,
            agent_name=agent_name,
        )
    except Exception:
        return
