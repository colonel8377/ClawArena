from fastapi import APIRouter, Query

from backend.services.leaderboard_service import LeaderboardService
from backend.middleware.decorators import api_handler
from backend.views.response import ApiResponse, ErrorResponse

router = APIRouter(prefix="/api", tags=["leaderboard"])


@router.get(
    "/leaderboard",
    response_model=ApiResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
@api_handler
async def leaderboard(limit: int = Query(default=10, ge=1, le=100)):
    rows = await LeaderboardService.get_top_agents(limit)
    return {"items": rows}
