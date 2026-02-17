from typing import Optional, Dict, Any

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from backend.database.redis_manager import redis_manager


async def _verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify a token via Redis and return its metadata."""
    if not token:
        return None
    data = await redis_manager.get_bot_token_data(token)
    if not data:
        return None
    if not data.get("player_id"):
        return None
    return data


class TokenResolutionMiddleware(BaseHTTPMiddleware):
    """
    Middleware to resolve Bot Token into user context.
    Parses 'x-bot-token' or 'Authorization: Bearer <token>'.
    Injects `player_id` and `user_payload` into `request.state`.
    Does NOT enforce authentication (that's for other layers).
    """
    async def dispatch(self, request: Request, call_next):
        token = request.headers.get("x-bot-token")

        request.state.player_id = None
        request.state.user_payload = None
        request.state.user_token = None

        if token:
            request.state.user_token = token
            try:
                payload = await _verify_token(token)
                if payload:
                    request.state.user_payload = payload
                    request.state.player_id = payload.get("player_id")
            except Exception:
                pass
                
        response = await call_next(request)
        return response

