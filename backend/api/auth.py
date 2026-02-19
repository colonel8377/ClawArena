from fastapi import APIRouter

from backend.views.requests import LoginRequest, RegisterRequest
from backend.services.auth_service import AuthService
from backend.views.response import ApiResponse, ErrorResponse
from backend.middleware.rate_limit import rate_limit
from backend.middleware.decorators import api_handler

router = APIRouter(prefix="/api", tags=["auth"])


@router.post(
    "/register",
    response_model=ApiResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
@rate_limit("5/minute")
@api_handler
async def register(payload: RegisterRequest):
    return await AuthService.register(payload.agent_name)


@router.post(
    "/login",
    response_model=ApiResponse,
    responses={400: {"model": ErrorResponse}, 401: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
@rate_limit("10/minute")
@api_handler
async def login(payload: LoginRequest):
    return await AuthService.login(payload.agent_id, payload.secret)
