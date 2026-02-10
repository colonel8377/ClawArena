"""Account and Economy routes."""

from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import List, Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from backend.economy.account import (
    register_user, handle_login, get_balance,
    get_account_summary, transfer_balance, batch_get_balances,
    InvalidAmountError, InsufficientBalanceError, UserNotFoundError, InvalidWalletAddressError,
    AmbiguousLoginIdentifierError,
    get_leaderboard
)
from backend.app.limiter import limiter
from backend.app.dependencies import get_current_user
from backend.database.models import UserLedger

router = APIRouter()

@router.post("/api/register")
@limiter.limit("5/minute")
async def api_register(request: Request, player_name: str, address: Optional[str] = None):
    """
    Register a new user account.
    
    Creates a user account in the database with initial balance.
    """
    try:
        result = await register_user(player_name, address)
        return result
    except (InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@router.post("/api/login")
@limiter.limit("10/minute")
async def api_login(
    request: Request,
    login_key: Optional[str] = None,
):
    """
    Handle user login with daily reward check.
    
    Checks if it's a new UTC day and grants daily login reward if applicable.

    Accepts:
    - login_key: canonical login identifier
    """
    try:
        resolved_login_key = (login_key or "").strip()
        if not resolved_login_key:
            raise HTTPException(status_code=400, detail="login_key is required")

        result = await handle_login(resolved_login_key)
        return result
    except InvalidWalletAddressError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except UserNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except AmbiguousLoginIdentifierError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


@router.get("/api/balance/{player_id}")
@limiter.limit("60/minute")
async def api_get_balance(request: Request, player_id: str):
    """Get user's current balance."""
    try:
        balance = await get_balance(player_id)
        return {
            "player_id": player_id,
            "balance": str(balance)
        }
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get balance: {str(e)}")


@router.get("/api/account/{player_id}")
@limiter.limit("30/minute")
async def api_get_account_summary(request: Request, player_id: str):
    """Get comprehensive account summary including validation and recent transactions."""
    try:
        summary = await get_account_summary(player_id)
        return summary
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get account summary: {str(e)}")


@router.post("/api/transfer")
@limiter.limit("10/minute")
async def api_transfer_balance(
    request: Request, 
    from_player_id: str, 
    to_player_id: str, 
    amount: str,
    current_user: UserLedger = Depends(get_current_user)
):
    """Transfer balance between two accounts."""
    if from_player_id != current_user.wallet_address:
        raise HTTPException(status_code=403, detail="Cannot transfer from another player's account")

    try:
        parsed_amount = Decimal(amount)
        result = await transfer_balance(from_player_id, to_player_id, parsed_amount)
        return result
    except (InvalidOperation, ValueError) as e:
        raise HTTPException(status_code=400, detail="Invalid amount")
    except InvalidAmountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InsufficientBalanceError as e:
        raise HTTPException(status_code=402, detail=str(e))  # 402 Payment Required
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transfer failed: {str(e)}")


@router.post("/api/balances/batch")
async def api_batch_get_balances(request: Request, player_ids: List[str]):
    """Get balances for multiple player identifiers efficiently."""
    try:
        if len(player_ids) > 50:
            raise HTTPException(status_code=400, detail="Too many player IDs (max 50)")
        balances = await batch_get_balances(player_ids)
        return {
            "balances": {addr: str(bal) for addr, bal in balances.items()}
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch balance query failed: {str(e)}")


@router.get("/api/leaderboard")
@limiter.limit("20/minute")
async def api_get_leaderboard(request: Request, limit: int = 10):
    """Get top players ranked by off-chain token balance."""
    try:
        if limit > 100:
            raise HTTPException(status_code=400, detail="Limit too large (max 100)")

        entries = await get_leaderboard(limit=limit)
        return {
            "entries": entries,
            "total": len(entries),
            "updated_at": datetime.utcnow().isoformat(),
        }
    except InvalidAmountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get leaderboard: {str(e)}")
