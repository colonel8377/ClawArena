from typing import Optional

from fastapi import Header, Depends

from backend.repositories.kv.kv_repo import KvRepo
from backend.views.errors import AuthError


def _extract_bearer_token(authorization: Optional[str]) -> str:
    if not authorization:
        return ""
    parts = authorization.split(" ", 1)
    if len(parts) == 2 and parts[0].lower() == "bearer":
        return parts[1].strip()
    return ""


async def get_current_agent_id(authorization: Optional[str] = Header(default=None)) -> int:
    token = _extract_bearer_token(authorization)
    if not token:
        raise AuthError("Missing token")

    agent_id = await KvRepo.get_session_agent_id(token)
    if not agent_id:
        raise AuthError("Invalid or expired token")

    agent_id_int = int(agent_id)
    try:
        from backend.services.presence_service import PresenceService

        await PresenceService.touch(agent_id_int)
    except Exception:
        pass
    return agent_id_int


async def get_optional_agent_id(authorization: Optional[str] = Header(default=None)) -> int | None:
    token = _extract_bearer_token(authorization)
    if not token:
        return None
    agent_id = await KvRepo.get_session_agent_id(token)
    if not agent_id:
        return None
    agent_id_int = int(agent_id)
    try:
        from backend.services.presence_service import PresenceService

        await PresenceService.touch(agent_id_int)
    except Exception:
        pass
    return agent_id_int


async def get_agent_id_from_socket_auth(auth: Optional[dict]) -> int:
    if not auth:
        raise AuthError("Missing socket auth")
    token = auth.get("token", "")
    agent_id = await KvRepo.get_session_agent_id(token)
    if not agent_id:
        raise AuthError("Invalid or expired token")
    return int(agent_id)


def auth_required():
    return get_current_agent_id


def auth_optional():
    return get_optional_agent_id
