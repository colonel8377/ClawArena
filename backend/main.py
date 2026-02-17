"""
main.py - The Server

FastAPI + Socket.IO server with agent authentication, game management,
and in-app token economy settlement.
"""
import os

import socketio
import uvicorn

from backend.app.app_factory import create_app
from backend.app.sio_factory import create_sio
from backend.app.startup import on_startup, on_shutdown
from backend.app.state import runtime_state
from backend.constant.texas import POKER_TIMEOUT_CHECK_INTERVAL
from backend.constant.werewolf import WEREWOLF_TIMEOUT_CHECK_INTERVAL
from backend.services.settlement_service import SettlementService
from backend.services.state_coordinator import StateCoordinator
from backend.services.texas_service import TexasService
from backend.services.werewolf_service import WerewolfService
from backend.socket.common import register_common_handlers
from backend.socket.matchmaking import register_matchmaking_handlers
from backend.socket.texas import register_texas_handlers
from backend.socket.werewolf import register_werewolf_handlers


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
state_coordinator = StateCoordinator(
    sio=sio,
    state=runtime_state,
    texas_service=texas_service,
    werewolf_service=werewolf_service,
)

# Register Socket Handlers
register_common_handlers(sio, runtime_state)
register_texas_handlers(sio, runtime_state, state_coordinator)
register_werewolf_handlers(sio, runtime_state, state_coordinator)
register_matchmaking_handlers(sio, runtime_state, state_coordinator)


@app.on_event("startup")
async def startup_event():
    await on_startup(app, sio, texas_service, werewolf_service, state_coordinator)


@app.on_event("shutdown")
async def shutdown_event():
    await on_shutdown(app, sio, texas_service, werewolf_service)


if __name__ == "__main__":
    uvicorn.run(
        "main:asgi_app",
        host=os.getenv('HOST', '0.0.0.0'),
        port=os.getenv('PORT', 8080),
        reload=True,
        log_level="info"
    )
