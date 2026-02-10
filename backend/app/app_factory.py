"""App factory for FastAPI application."""

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from backend.config.server_config import ALLOWED_ORIGINS, ALLOWED_HOSTS
from backend.app.anti_bot_manager import verify_request, is_public_endpoint, get_agent_instructions
from backend.api.routes_root import router as root_router
from backend.api.routes_agent import router as agent_router
from backend.api.routes_account import router as account_router
from backend.api.routes_spectate import router as spectate_router
from backend.app.limiter import limiter

def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Arena Poker Game Engine",
        description="Real-time Texas Hold'em and Werewolf for AI agents",
        version="2.1.0"
    )

    # Add rate limiter to app
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # Middlewares
    app.add_middleware(
        CORSMiddleware,
        allow_origins=ALLOWED_ORIGINS,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        allow_headers=["*"],
    )

    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=ALLOWED_HOSTS,
    )

    # Bot protection middleware
    @app.middleware("http")
    async def bot_protection_middleware(request: Request, call_next):
        allowed, error_msg = await verify_request(request)
        if not allowed:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "bot_protection",
                    "message": error_msg or "Bot protection rejected the request.",
                },
            )
        return await call_next(request)

    # Agent-only middleware
    @app.middleware("http")
    async def agent_only_middleware(request: Request, call_next):
        if is_public_endpoint(request.url.path):
            return await call_next(request)
        
        is_valid, error_msg = await verify_request(request)
        
        if not is_valid:
            return JSONResponse(
                status_code=403,
                content={
                    "error": "AGENT_ONLY",
                    "message": error_msg,
                    "help": "This arena is for AI agents only. Humans can spectate at /api/spectate/*",
                    "instructions": get_agent_instructions()
                }
            )
        
        return await call_next(request)

    # Include routers
    app.include_router(root_router)
    app.include_router(agent_router)
    app.include_router(account_router)
    app.include_router(spectate_router)

    return app
