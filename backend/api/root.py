from fastapi import APIRouter

from backend.middleware.decorators import api_handler
from backend.config.settings import get_settings
from backend.views.response import ApiResponse, ErrorResponse

router = APIRouter()


@router.get("/", response_model=ApiResponse, responses={500: {"model": ErrorResponse}})
@api_handler
async def root():
    settings = get_settings()
    return {
        "name": settings.app_name,
        "env": settings.env,
        "status": "running",
    }


@router.get("/health", response_model=ApiResponse, responses={500: {"model": ErrorResponse}})
@api_handler
async def health():
    return {"status": "healthy"}
