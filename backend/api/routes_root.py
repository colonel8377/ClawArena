"""Root routes."""

from fastapi import APIRouter, Request
from config.config import LOCAL_DEBUG_MODE
from app.state import runtime_state

router = APIRouter()

@router.get("/")
async def root(request: Request):
    """Root endpoint."""
    return {
        "name": "Arena Poker Game Engine",
        "version": "2.1.0",
        "status": "running",
        "local_debug_mode": LOCAL_DEBUG_MODE
    }


@router.get("/health")
async def health(request: Request):
    """Health check."""
    return {
        "status": "healthy",
        "active_tables": len(runtime_state.poker_tables),
        "local_debug_mode": LOCAL_DEBUG_MODE
    }
