from fastapi import APIRouter, Depends, Query, Request

from backend.middleware.auth import auth_optional
from backend.middleware.rate_limit import rate_limit
from backend.middleware.decorators import api_handler
from backend.services.history_service import HistoryService
from backend.views.response import ApiResponse, ErrorResponse
from backend.views.errors import AuthError

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
    agent_id: int | None = Depends(auth_optional()),
    target_agent_id: int | None = Query(default=None, ge=1, alias="agent_id"),
):
    resolved_id = int(target_agent_id or 0) or agent_id
    if not resolved_id:
        raise AuthError("Invalid agent_id")
    return HistoryService.list_history(int(resolved_id), page_size, offset)


@router.get(
    "/history/summary",
    response_model=ApiResponse,
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
@rate_limit("30/minute")
@api_handler
async def history_summary(
    request: Request,
    agent_id: int | None = Depends(auth_optional()),
    target_agent_id: int | None = Query(default=None, ge=1, alias="agent_id"),
):
    resolved_id = int(target_agent_id or 0) or agent_id
    if not resolved_id:
        raise AuthError("Invalid agent_id")
    return await HistoryService.summary(int(resolved_id))
