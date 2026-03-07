from fastapi import APIRouter, Depends, Request

from backend.middleware.auth import auth_required
from backend.middleware.rate_limit import rate_limit
from backend.services.queue_service import QueueService
from backend.middleware.decorators import api_handler
from backend.views.response import ApiResponse, ErrorResponse
from backend.views.requests import QueueJoinRequest, QueueLeaveRequest

router = APIRouter(prefix="/api/queue", tags=["queue"])


@router.post(
    "/join",
    response_model=ApiResponse,
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
@rate_limit("20/minute")
@api_handler
async def join(request: Request, payload: QueueJoinRequest, agent_id: int = Depends(auth_required())):
    return await QueueService.join(agent_id, payload.game_type)


@router.post(
    "/leave",
    response_model=ApiResponse,
    responses={401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
@rate_limit("20/minute")
@api_handler
async def leave(request: Request, payload: QueueLeaveRequest, agent_id: int = Depends(auth_required())):
    return await QueueService.leave(agent_id, payload.game_type)
