from typing import Optional
from fastapi import Header, HTTPException, Depends, Request
from sqlalchemy import select, or_
from backend.database.connection import get_async_db_session
from backend.database.models import UserLedger
from backend.app.anti_bot_manager import _verify_token
from backend.config.arena_config import BOT_ALLOW_BYPASS_LOCAL, LOCAL_DEBUG_MODE

async def get_current_user(
    request: Request,
    x_bot_token: Optional[str] = Header(None, alias="x-bot-token"),
) -> UserLedger:
    """
    Authenticate user via x-bot-token (Agent Token).

    The token must be valid and bound to a specific player_id + session_version pair.
    """
    token = x_bot_token

    # Support Bearer token as fallback
    if not token:
        auth = request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ")[1]

    # Local debug bypass: skip token verification
    if not token and BOT_ALLOW_BYPASS_LOCAL and LOCAL_DEBUG_MODE:
        # Extract player_id from path if available (e.g. /api/balance/{player_id})
        path_parts = request.url.path.strip("/").split("/")
        candidate_id = path_parts[-1] if len(path_parts) >= 3 else None
        async with get_async_db_session() as db:
            if candidate_id and candidate_id not in ("batch",):
                stmt = select(UserLedger).filter(
                    or_(
                        UserLedger.wallet_address == candidate_id,
                        UserLedger.address == candidate_id,
                    )
                )
            else:
                # Fallback: return any user as a gate placeholder
                stmt = select(UserLedger).limit(1)
            result = await db.execute(stmt)
            user = result.scalar_one_or_none()
            if user:
                return user
        raise HTTPException(status_code=401, detail="Local debug: no users found in database")

    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
        
    payload = _verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
        
    player_id = payload.get("player_id")
    session_version = payload.get("session_version")
    if not player_id:
        raise HTTPException(status_code=401, detail="Token missing player_id")
    if session_version is None:
        raise HTTPException(status_code=401, detail="Token missing session_version")

    async with get_async_db_session() as db:
        stmt = select(UserLedger).filter(
            or_(
                UserLedger.wallet_address == player_id,
                UserLedger.address == player_id,
            )
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=401, 
                detail=f"No user account found for player_id {player_id}. Please register first."
            )

        if user.session_token_version != session_version:
            raise HTTPException(
                status_code=401,
                detail="Session token expired. Please re-authenticate."
            )
            
        return user
