import asyncio

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import socketio

from backend.api.root import router as root_router
from backend.api.auth import router as auth_router
from backend.api.leaderboard import router as leaderboard_router
from backend.api.wallet import router as wallet_router
from backend.api.queue import router as queue_router
from backend.api.history import router as history_router
from backend.api.rooms import router as rooms_router
from backend.config.settings import get_settings
from backend.views.handlers import register_exception_handlers
from backend.middleware.rate_limit import attach_rate_limiter
from backend.middleware.agent_check import agent_check_middleware
from backend.middleware.trace import trace_middleware
from backend.sockets.server import register_socket_handlers, sio
from backend.services.match_service import MatchService
from backend.services.offline_monitor_service import OfflineMonitorService
from backend.repositories.db import init_db


def create_app() -> FastAPI:
    settings = get_settings()
    app = FastAPI(title=settings.app_name)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.allowed_origins,
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(root_router)
    app.include_router(auth_router)
    app.include_router(leaderboard_router)
    app.include_router(wallet_router)
    app.include_router(queue_router)
    app.include_router(rooms_router)
    app.include_router(history_router)
    register_exception_handlers(app)
    attach_rate_limiter(app)
    app.middleware("http")(trace_middleware)
    app.middleware("http")(agent_check_middleware)

    @app.on_event("startup")
    async def on_startup() -> None:
        init_db()
        asyncio.create_task(MatchService.run_loop())
        asyncio.create_task(OfflineMonitorService.run_loop())

    return app


app = create_app()
register_socket_handlers(sio)
asgi_app = socketio.ASGIApp(sio, other_asgi_app=app)
