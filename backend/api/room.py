from fastapi import APIRouter, Depends

from backend.middleware.auth import auth_required
from backend.middleware.rate_limit import rate_limit
from backend.services.room_service import RoomService
from backend.middleware.decorators import api_handler
from backend.views.response import ApiResponse, ErrorResponse
from backend.views.requests import RoomJoinRequest
from backend.config.constants import RoomRole

router = APIRouter(prefix="/api/room", tags=["room"])


@router.post(
    "/join",
    response_model=ApiResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
@rate_limit("20/minute")
@api_handler
async def join(payload: RoomJoinRequest, agent_id: int = Depends(auth_required())):
    if payload.role == RoomRole.SPECTATOR:
        return await RoomService.join_as_spectator(agent_id, payload.room_id)
    return await RoomService.join_as_player(agent_id, payload.room_id)


@router.post(
    "/leave",
    response_model=ApiResponse,
    responses={401: {"model": ErrorResponse}},
)
@rate_limit("20/minute")
@api_handler
async def leave(agent_id: int = Depends(auth_required())):
    return await RoomService.leave(agent_id)
