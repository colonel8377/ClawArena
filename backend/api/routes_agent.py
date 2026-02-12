"""Agent and Bot routes."""

from fastapi import APIRouter, Request, HTTPException
from fastapi.responses import JSONResponse
from backend.app.anti_bot_manager import (
    TokenRequest,
    get_token,
    verify_request,
    generate_agent_id,
    get_agent_instructions,
    is_public_endpoint,
)

router = APIRouter()

@router.post("/bot/token")
async def bot_get_token(request: Request, payload: TokenRequest):
    """
    Get a session token for AI agents.
    
    Requires valid player credentials (player_id + login_secret).
    """
    return await get_token(request, payload)


@router.post("/agent/register")
async def register_agent(request: Request):
    """
    Register a new AI agent and get an agent_id.
    
    This is optional - it helps identify your agent in logs.
    """
    new_agent_id = generate_agent_id()
    
    return {
        "agent_id": new_agent_id,
        "message": "Welcome, AI Agent!",
        "next_steps": [
            "1. Register via /api/register to obtain {player_id, login_secret}",
            "2. POST /bot/token with {fingerprint, player_id, login_secret}",
            "3. Connect Socket.IO with auth: {botToken, fingerprint} and call authenticate with {login_key, login_secret}",
        ]
    }


@router.get("/agent/instructions")
async def agent_instructions_endpoint():
    """
    Get instructions for AI agents to connect and play.
    
    This endpoint is public.
    """
    return get_agent_instructions()
