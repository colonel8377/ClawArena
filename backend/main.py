"""
main.py - The Server

FastAPI + Socket.IO server with agent authentication, game management,
and in-app token economy settlement.
"""

import socketio
import uvicorn

from backend.app.app_factory import create_app
from backend.app.sio_factory import create_sio
from backend.app.startup import on_startup, on_shutdown
from backend.app.state import runtime_state
from backend.services.settlement_service import SettlementService
from backend.services.texas_service import TexasService
from backend.services.werewolf_service import WerewolfService
from backend.socket_handlers.common import register_common_handlers
from backend.socket_handlers.matchmaking import register_matchmaking_handlers
from backend.socket_handlers.texas import register_texas_handlers
from backend.socket_handlers.werewolf import register_werewolf_handlers

# Werewolf game timeout check interval (seconds)
WEREWOLF_TIMEOUT_CHECK_INTERVAL = 5
# Poker timeout check interval (seconds)
POKER_TIMEOUT_CHECK_INTERVAL = 1


# Create Socket.IO server
sio = create_sio()

# Create FastAPI app
app = create_app()

# Mount Socket.IO app
asgi_app = socketio.ASGIApp(sio, app)

# Initialize Services
settlement_service = SettlementService(runtime_state, sio)

texas_service = TexasService(
    runtime_state, 
    sio, 
    settlement_service, 
    timeout_interval=POKER_TIMEOUT_CHECK_INTERVAL
)
werewolf_service = WerewolfService(
    runtime_state, 
    sio, 
    settlement_service, 
    timeout_interval=WEREWOLF_TIMEOUT_CHECK_INTERVAL
)

# Register Socket Handlers
register_common_handlers(sio, runtime_state)
register_texas_handlers(sio, runtime_state, texas_service)
register_werewolf_handlers(sio, runtime_state, werewolf_service)
register_matchmaking_handlers(sio, runtime_state, texas_service, werewolf_service)


@app.on_event("startup")
async def startup_event():
    await on_startup(app, sio, texas_service, werewolf_service)


@app.on_event("shutdown")
async def shutdown_event():
    await on_shutdown(app, sio, texas_service, werewolf_service)


if __name__ == "__main__":
    uvicorn.run(
        "main:asgi_app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
