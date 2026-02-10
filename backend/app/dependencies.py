from typing import Optional
from fastapi import Header, HTTPException, Depends, Request
from sqlalchemy import select, or_
from backend.database.connection import get_async_db_session
from backend.database.models import UserLedger
from backend.app.anti_bot_manager import _verify_token

async def get_current_user(
    request: Request,
    x_bot_token: Optional[str] = Header(None, alias="x-bot-token"),
) -> UserLedger:
    """
    Authenticate user via x-bot-token (Agent Token).
    
    The token must be valid and the fingerprint within it must be bound to a UserLedger
    (via wallet_address or address field).
    """
    token = x_bot_token
    
    # Support Bearer token as fallback
    if not token:
        auth = request.headers.get("Authorization")
        if auth and auth.lower().startswith("bearer "):
            token = auth.split(" ")[1]
            
    if not token:
        raise HTTPException(status_code=401, detail="Missing authentication token")
        
    payload = _verify_token(token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
        
    fingerprint = payload.get("fp")
    if not fingerprint:
        raise HTTPException(status_code=401, detail="Token missing fingerprint")
        
    async with get_async_db_session() as db:
        # Find user bound to this fingerprint
        # We check both wallet_address and address fields
        stmt = select(UserLedger).filter(
            or_(
                UserLedger.wallet_address == fingerprint,
                UserLedger.address == fingerprint
            )
        )
        result = await db.execute(stmt)
        user = result.scalar_one_or_none()
        
        if not user:
            raise HTTPException(
                status_code=401, 
                detail=f"No user account found bound to agent fingerprint {fingerprint}. Please register with this fingerprint."
            )
            
        return user
