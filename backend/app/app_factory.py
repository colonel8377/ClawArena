"""App factory for FastAPI application."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from backend.api.routes_agent import router as account_router
from backend.api.routes_root import router as root_router
from backend.api.routes_spectate import router as spectate_router

from backend.app.limiter import ip_limiter, player_id_limiter
from backend.app.middleware.agent_detector import AgentDetectionMiddleware
from backend.app.middleware.auth import TokenResolutionMiddleware
from backend.config.server_config import ALLOWED_ORIGINS, ALLOWED_HOSTS


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    app = FastAPI(
        title="Arena Poker Game Engine",
        description="Real-time Texas Hold'em and Werewolf for AI agents",
        version="2.1.0"
    )

    # Add rate limiter to app
    app.state.ip_limiter = ip_limiter
    app.state.player_id_limiter = player_id_limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    

    
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

    app.add_middleware(
        AgentDetectionMiddleware
    )

    app.add_middleware(
        TokenResolutionMiddleware
    )

    # Include routers
    app.include_router(root_router)
    app.include_router(account_router)
    app.include_router(spectate_router)

    return app
