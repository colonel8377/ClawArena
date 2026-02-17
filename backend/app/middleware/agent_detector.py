from functools import wraps

from fastapi import Request, HTTPException
from starlette.middleware.base import BaseHTTPMiddleware

from backend.utils.http_util import detect_agent

PUBLIC_PREFIX_ENDPOINTS = (
    "/docs",
    "/redoc",
    "/api/spectate/",
    "/agent/",
    "/bot/",
    "/socket.io/",
)

class AgentDetectionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        user_agent = request.headers.get("user-agent", "")
        is_agent, reason = detect_agent(user_agent)
        request.state.is_agent = is_agent
        request.state.agent_detection_reason = reason
        response = await call_next(request)
        return response



def require_agent(func):
    """
    Decorator that enforces the client MUST be an AI agent.
    If not, raises 403 Forbidden.
    Requires `request: Request` parameter.
    """

    @wraps(func)
    async def wrapper(*args, **kwargs):
        request = kwargs.get('request') or next((arg for arg in args if isinstance(arg, Request)), None)

        if not getattr(request.state, "is_agent", False):
            reason = getattr(request.state, "agent_detection_reason", "unknown")
            raise HTTPException(
                status_code=403,
                detail=f"Access forbidden: Browser detected ({reason}). Only AI agents allowed."
            )
        return await func(*args, **kwargs)

    return wrapper