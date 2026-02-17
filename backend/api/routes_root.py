"""Root routes."""
import os

from fastapi import APIRouter, Request

from backend.app.state import runtime_state
from backend.config.arena_config import LOCAL_DEBUG_MODE

router = APIRouter()

@router.get("/")
async def root():
    """Root endpoint."""
    return {
        "name": "Claw Arena",
        "status": "Running",
        "local_debug_mode": LOCAL_DEBUG_MODE
    }


@router.get("/health")
async def health():
    """Health check."""
    return {
        "status": "healthy",
        "active_tables": len(runtime_state.poker_tables),
        "local_debug_mode": LOCAL_DEBUG_MODE
    }


@router.get("/api/whoami")
async def whoami(request: Request):
    """
    Demonstrate AOP Agent Detection with Decorator.
    """
    is_agent = getattr(request.state, "is_agent", False)
    reason = getattr(request.state, "agent_detection_reason", "unknown")
    
    return {
        "is_agent": is_agent,
        "detection_reason": reason,
        "message": "Hello AI Agent!" if is_agent else "Hello Human!",
    }
