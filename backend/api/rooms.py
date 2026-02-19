from fastapi import APIRouter, Depends, Path, Query, Request

from backend.config.constants import RoomRole
from backend.middleware.auth import auth_optional, auth_required
from backend.middleware.decorators import api_handler
from backend.middleware.rate_limit import rate_limit
from backend.services.chat_history_service import ChatHistoryService
from backend.services.room_directory_service import RoomDirectoryService
from backend.services.room_service import RoomService
from backend.views.response import ApiResponse, ErrorResponse
from backend.views.requests import RoomJoinRequest

router = APIRouter(prefix="/api/rooms", tags=["rooms"])


@router.post(
    "/join",
    response_model=ApiResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
@rate_limit("20/minute")
@api_handler
async def join(request: Request, payload: RoomJoinRequest, agent_id: int = Depends(auth_required())):
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
async def leave(request: Request, agent_id: int = Depends(auth_required())):
    return await RoomService.leave(agent_id)


@router.get(
    "/{room_id}/chat",
    response_model=ApiResponse,
    responses={400: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
@rate_limit("30/minute")
@api_handler
async def chat_history(
    request: Request,
    room_id: int = Path(ge=1),
    limit: int = Query(default=50, ge=1, le=200),
    before_id: str | None = Query(default=None),
    after_id: str | None = Query(default=None),
    agent_id: int | None = Depends(auth_optional()),
):
    return await ChatHistoryService.list_history(
        room_id=room_id,
        limit=limit,
        before_id=before_id,
        after_id=after_id,
        agent_id=agent_id,
    )


@router.get(
    "/active",
    response_model=ApiResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
)
@rate_limit("30/minute")
@api_handler
async def active_rooms(request: Request, limit: int = Query(default=50, ge=1, le=200)):
    return await RoomDirectoryService.list_active(limit)
