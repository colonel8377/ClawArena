"""Account and Economy routes."""

from fastapi import APIRouter, Request, Depends
from fastapi.responses import JSONResponse


from backend.app.limiter import ip_limiter, player_id_limiter
from backend.app.middleware.agent_detector import require_agent
from backend.constant.error import (
    ApiError,
    error_payload,
    payload_from_error,
)
from backend.database.models import UserLedger
from backend.services.account_service import (
    register_user,
    get_balance,
    get_account_summary,
    handle_check_in, get_token,
)
from backend.views.account_view import (
    BotTokenRequest,
    BotTokenResponse,
    LoginRequest,
    LoginResponse,
    RegisterQuery,
    RegisterResponse,
    BalanceResponse,
    AccountSummaryResponse,
)
from backend.views.response import StandardResponse

router = APIRouter()


@router.post("/bot/token", response_model=StandardResponse[BotTokenResponse])
@ip_limiter.limit("20/minute")
@require_agent
async def bot_get_token(payload: BotTokenRequest = Depends()):
    """
    Get a session token for AI agents.

    Requires valid player credentials (player_id + login_secret).
    """
    try:
        bot_token_resp = await get_token(payload)
        await handle_check_in(
            bot_token_resp.player_id,
            grant_reward=True,
        )
        return StandardResponse(data=bot_token_resp)
    except ApiError as e:
        return JSONResponse(status_code=e.http_status, content=payload_from_error(e))
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "server", f"Token issuance failed: {str(e)}"),
        )


@router.post("/api/register", response_model=StandardResponse[RegisterResponse])
@ip_limiter.limit("30/minute")
@require_agent
async def api_register(query: RegisterQuery = Depends()):
    """
    Register a new user account.
    
    Creates a user account in the database with initial balance.
    """
    try:
        result = await register_user(query.player_name, query.address)
        return StandardResponse(data=result)
    except ApiError as e:
        return JSONResponse(status_code=e.http_status, content=payload_from_error(e))
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "server", f"Registration failed: {str(e)}")
        )


@router.post("/api/check-in", response_model=StandardResponse[LoginResponse])
@ip_limiter.limit("20/minute")
@player_id_limiter.limit("20/minute")
@require_agent
async def api_check_in(request: Request, payload: LoginRequest) :
    """
    Handle user login with daily reward check.
    
    Checks if it's a new UTC day and grants daily login reward if applicable.
    """
    try:
        player_id = getattr(request.state, "player_id")
        result = await handle_check_in(
            player_id,
            grant_reward=payload.grant_reward,
        )
        return StandardResponse(data=result)
    except ApiError as e:
        return JSONResponse(status_code=e.http_status, content=payload_from_error(e))
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "server", f"Login failed: {str(e)}")
        )


@router.get("/api/balance/{player_id}", response_model=StandardResponse[BalanceResponse])
@ip_limiter.limit("60/minute")
@player_id_limiter.limit("60/minute")
@require_agent
async def api_get_balance(request: Request):
    """Get user's current balance. Requires bot token authentication."""
    try:
        player_id = getattr(request.state, "player_id")
        balance = await get_balance(player_id)
        return StandardResponse(
            data=BalanceResponse(
                player_id=player_id,
                balance=str(balance)
            )
        )
    except ApiError as e:
        return JSONResponse(status_code=e.http_status, content=payload_from_error(e))
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "server", f"Failed to get balance: {str(e)}")
        )


@router.get("/api/account/{player_id}", response_model=StandardResponse[AccountSummaryResponse])
@ip_limiter.limit("30/minute")
@player_id_limiter.limit("30/minute")
@require_agent
async def api_get_account_summary(request: Request,  _user: UserLedger = Depends()):
    """Get comprehensive account summary. Requires bot token authentication."""
    try:
        player_id = getattr(request.state, "player_id")
            
        summary = await get_account_summary(player_id)
        return StandardResponse(data=summary)
        
    except ApiError as e:
        return JSONResponse(status_code=e.http_status, content=payload_from_error(e))
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "server", f"Failed to get account summary: {str(e)}")
        )