from typing import Optional

from fastapi import APIRouter, Query
from fastapi.responses import JSONResponse

from backend.app.limiter import ip_limiter
from backend.constant.error import ApiError, payload_from_error, error_payload
from backend.services.speculate_service import (
    get_active_games, get_spectate_state, get_leaderboard
)
from backend.views.response import StandardResponse
from backend.views.spectate_view import (
    ActiveGamesResponse,
    TexasSpectateResponse,
    WerewolfSpectateResponse,
    LeaderboardResponse
)

router = APIRouter()

@ip_limiter.limit("30/minute")
@router.get("/api/spectate/active", response_model=StandardResponse[ActiveGamesResponse])
async def api_list_active_games(q: Optional[str] = Query(None)):
    """
    List active poker tables and werewolf games for spectators.
    """
    try:
        data = await get_active_games(q)
        return StandardResponse(data=data)
    except ApiError as e:
        return JSONResponse(status_code=e.http_status, content=payload_from_error(e))
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "server", f"Token issuance failed: {str(e)}"),
        )

@ip_limiter.limit("20/minute")
@router.get("/api/spectate/texas/{table_id}", response_model=StandardResponse[TexasSpectateResponse])
async def api_spectate_texas(table_id: str, reveal: bool = False):
    """
    Get public state of a poker table.
    """
    try:
        data = await get_spectate_state(table_id, reveal)
        # Pydantic will validate 'data' dict against TexasSpectateResponse
        return StandardResponse(data=data)
    except ApiError as e:
        return JSONResponse(status_code=e.http_status, content=payload_from_error(e))
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "server", f"Token issuance failed: {str(e)}"),
        )

@ip_limiter.limit("20/minute")
@router.get("/api/spectate/werewolf/{game_id}", response_model=StandardResponse[WerewolfSpectateResponse])
async def api_spectate_werewolf(game_id: str, reveal: bool = False):
    """
    Get public state of a werewolf game.
    """
    try:
        data = await get_spectate_state(game_id, reveal)
        return StandardResponse(data=data)
    except ApiError as e:
        return JSONResponse(status_code=e.http_status, content=payload_from_error(e))
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "server", f"Token issuance failed: {str(e)}"),
        )


@router.get("/api/leaderboard", response_model=StandardResponse[LeaderboardResponse])
@ip_limiter.limit("20/minute")
async def api_get_leaderboard(limit: int = 10):
    """Get top players ranked by off-chain token balance."""
    try:
        if limit > 100:
            limit = 100
        if limit < 0:
            return StandardResponse(data={})
        data = await get_leaderboard(limit=limit)
        return StandardResponse(data=data)
    except ApiError as e:
        return JSONResponse(status_code=e.http_status, content=payload_from_error(e))
    except Exception as e:
        return JSONResponse(
            status_code=500,
            content=error_payload("INTERNAL_ERROR", "server", f"Token issuance failed: {str(e)}"),
        )