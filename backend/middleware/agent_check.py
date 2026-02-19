from fastapi import Request

from backend.config.settings import get_settings
from backend.views.errors import ForbiddenError


def _is_browser_user_agent(user_agent: str) -> bool:
    ua = user_agent.lower()
    browser_markers = ("chrome", "safari", "firefox", "edg", "opr", "opera")
    return any(marker in ua for marker in browser_markers)


def _is_agent_user_agent(user_agent: str, prefix: str) -> bool:
    if not prefix:
        return True
    return user_agent.startswith(prefix)


def validate_agent_user_agent(user_agent: str) -> None:
    settings = get_settings()
    if settings.agent_block_browsers and _is_browser_user_agent(user_agent):
        raise ForbiddenError("Agent-only endpoint")
    if not _is_agent_user_agent(user_agent, settings.agent_ua_prefix):
        raise ForbiddenError("Invalid agent user-agent")


async def agent_check_middleware(request: Request, call_next):
    user_agent = request.headers.get("user-agent", "")
    validate_agent_user_agent(user_agent)

    return await call_next(request)
