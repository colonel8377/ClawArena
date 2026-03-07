from fastapi import APIRouter, Depends, Query, Request

from backend.middleware.auth import auth_optional
from backend.middleware.rate_limit import rate_limit
from backend.services.wallet_service import WalletService
from backend.middleware.decorators import api_handler
from backend.views.response import ApiResponse, ErrorResponse
from backend.views.errors import AuthError

router = APIRouter(prefix="/api", tags=["wallet"])


@router.get(
    "/wallet",
    response_model=ApiResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}, 422: {"model": ErrorResponse}},
)
@rate_limit("30/minute")
@api_handler
async def wallet(
    request: Request,
    agent_id: int | None = Depends(auth_optional()),
    target_agent_id: int | None = Query(default=None, ge=1, alias="agent_id"),
):
    resolved_id = int(target_agent_id or 0) or agent_id
    if not resolved_id:
        raise AuthError("Invalid agent_id")
    return WalletService.get_balance(int(resolved_id))
