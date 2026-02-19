from fastapi import APIRouter, Depends

from backend.middleware.auth import auth_required
from backend.middleware.rate_limit import rate_limit
from backend.services.wallet_service import WalletService
from backend.middleware.decorators import api_handler
from backend.views.response import ApiResponse, ErrorResponse

router = APIRouter(prefix="/api", tags=["wallet"])


@router.get(
    "/wallet",
    response_model=ApiResponse,
    responses={401: {"model": ErrorResponse}, 404: {"model": ErrorResponse}},
)
@rate_limit("30/minute")
@api_handler
async def wallet(agent_id: int = Depends(auth_required())):
    return WalletService.get_balance(agent_id)
