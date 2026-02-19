from fastapi import APIRouter, Depends, Query, Request

from backend.middleware.auth import auth_required
from backend.middleware.rate_limit import rate_limit
from backend.middleware.decorators import api_handler
from backend.services.history_service import HistoryService
from backend.views.response import ApiResponse, ErrorResponse

router = APIRouter(prefix="/api", tags=["history"])


@router.get(
    "/history",
    response_model=ApiResponse,
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
@rate_limit("30/minute")
@api_handler
async def history(
    request: Request,
    page_size: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    agent_id: int = Depends(auth_required()),
):
    return HistoryService.list_history(agent_id, page_size, offset)
