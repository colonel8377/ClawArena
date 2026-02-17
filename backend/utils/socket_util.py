"""Socket.IO view helpers."""

from typing import Any, Type, TypeVar

from pydantic import BaseModel, ValidationError

from backend.constant.socket_error import SocketError
from backend.utils.http_util import detect_agent

T = TypeVar("T", bound=BaseModel)


def parse_payload(model: Type[T], data: Any, message: str = "Invalid payload") -> T:
    """Parse and validate a Socket.IO payload using a Pydantic model."""
    try:
        if hasattr(model, "model_validate"):
            return model.model_validate(data or {})
        return model.parse_obj(data or {})
    except ValidationError as exc:
        raise SocketError(message, error_code="INVALID_PAYLOAD") from exc


"""Socket.IO authentication and bot-protection helpers."""

from typing import Any, Dict, Optional, Tuple

from backend.database.redis_manager import redis_manager

SOCKET_CONNECT_RATE_LIMIT = "60/minute"


def get_user_agent(environ: Dict[str, Any]) -> str:
    return (
        environ.get("HTTP_USER_AGENT")
        or environ.get("HTTP_USER-AGENT")
        or environ.get("USER_AGENT")
        or ""
    )


def get_remote_ip(environ: Dict[str, Any]) -> str:
    forwarded = environ.get("HTTP_X_FORWARDED_FOR")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return environ.get("REMOTE_ADDR") or ""


def parse_rate_limit(limit: str) -> Tuple[int, int]:
    count_str, period = limit.split("/")
    count = int(count_str)
    seconds = {
        "second": 1,
        "minute": 60,
        "hour": 3600,
        "day": 86400,
    }.get(period, 60)
    return count, seconds


async def check_rate_limit(ip: str, limit: str = SOCKET_CONNECT_RATE_LIMIT) -> bool:
    if not ip:
        return True
    if not redis_manager.client:
        return True

    count, seconds = parse_rate_limit(limit)
    key = f"rate_limit:socket_connect:{ip}"
    current = await redis_manager.client.incr(key)
    if current == 1:
        await redis_manager.client.expire(key, seconds)
    return current <= count




async def verify_token(token: str) -> Optional[Dict[str, Any]]:
    if not token:
        return None
    data = await redis_manager.get_bot_token_data(token)
    if not data:
        return None
    if not data.get("player_id"):
        return None
    return data


async def verify_socket_auth(
    environ: Dict[str, Any],
    auth: Optional[Dict[str, Any]],
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """
    Verify socket connection with agent detection, rate limiting, and token validation.

    Returns (allowed, reason, payload).
    """
    auth = auth or {}
    token = auth.get("x-bot-token")
    fingerprint = auth.get("fingerprint")
    is_spectator = bool(auth.get("is-spectator"))

    user_agent = get_user_agent(environ)
    is_agent, reason = detect_agent(user_agent)
    if not is_agent:
        return False, f"browser_detected:{reason}", None

    ip = get_remote_ip(environ)
    if not await check_rate_limit(ip):
        return False, "rate_limited", None

    if is_spectator and not token:
        return True, "spectator", None

    if not token:
        return False, "token_required", None

    payload = await verify_token(token)
    if not payload:
        return False, "invalid_token", None

    if fingerprint and payload.get("fp") and payload.get("fp") != fingerprint:
        return False, "fp_mismatch", None

    return True, "ok", payload
