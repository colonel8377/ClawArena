"""Socket.IO middleware-style helpers."""

from functools import wraps
from typing import Any, Callable, Optional

from backend.constant.socket_error import SocketError, emit_error
from backend.utils.socket_util import parse_payload


def _extract_sid(args, kwargs) -> Optional[str]:
    if args:
        return args[0]
    return kwargs.get("sid")


def _extract_data(args, kwargs) -> Any:
    if len(args) >= 2:
        return args[1]
    return kwargs.get("data")


def socket_event(sio, error_prefix: str) -> Callable:
    """Decorator to standardize Socket.IO error handling."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            sid = _extract_sid(args, kwargs)
            try:
                return await func(*args, **kwargs)
            except SocketError as exc:
                if sid is not None:
                    await emit_error(sio, exc.message, room=sid, error_code=exc.error_code)
                return None
            except Exception as exc:
                if sid is not None:
                    await emit_error(sio, f"{error_prefix}: {str(exc)}", room=sid)
                return None

        return wrapper

    return decorator


def socket_validate(model, message: str = "Invalid payload") -> Callable:
    """Decorator to parse/validate socket payloads before calling handlers."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            data = _extract_data(args, kwargs)
            payload = parse_payload(model, data, message=message)
            args = list(args)
            if len(args) >= 2:
                args[1] = payload
            else:
                kwargs["payload"] = payload
            kwargs.pop("data", None)
            return await func(*args, **kwargs)

        return wrapper

    return decorator


def socket_auth(
    state,
    *,
    allow_spectator: bool = False,
    message: str = "Not authenticated",
    error_code: str = "NOT_AUTHENTICATED",
) -> Callable:
    """Decorator to enforce authenticated (or spectator) socket sessions."""
    def decorator(func: Callable) -> Callable:
        @wraps(func)
        async def wrapper(*args, **kwargs):
            sid = _extract_sid(args, kwargs)
            session = state.player_sessions.get(sid) if sid else None
            if not session:
                raise SocketError(message, error_code=error_code)
            if session.authenticated:
                return await func(*args, **kwargs)
            if allow_spectator:
                return await func(*args, **kwargs)
            raise SocketError(message, error_code=error_code)

        return wrapper

    return decorator
