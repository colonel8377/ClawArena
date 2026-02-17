"""Texas Hold'em Socket.IO handlers."""

from backend.app.middleware.socket_middleware import socket_auth, socket_event, socket_validate
from backend.services.texas_socket_service import TexasSocketService
from backend.views.socket.texas import (
    GetStateRequest,
    LeaveGameRequest,
    PlayerMoveRequest,
    StartHandRequest,
)

def register_texas_handlers(sio, state, coordinator) -> None:
    """Register Texas Socket.IO event handlers."""
    socket_service = TexasSocketService(coordinator)

    @sio.event
    @socket_event(sio, "Start hand failed")
    @socket_auth(state)
    @socket_validate(StartHandRequest)
    async def start_hand(sid, payload):
        await socket_service.start_hand(sid, payload)

    @sio.event
    @socket_event(sio, "Player move failed")
    @socket_auth(state)
    @socket_validate(PlayerMoveRequest, message="Invalid amount: must be an integer")
    async def player_move(sid, payload):
        await socket_service.player_move(sid, payload)

    @sio.event
    @socket_event(sio, "Get state failed")
    @socket_auth(state)
    @socket_validate(GetStateRequest)
    async def get_state(sid, payload):
        await socket_service.get_state(sid, payload)

    @sio.event
    @socket_event(sio, "Leave game failed")
    @socket_auth(state)
    @socket_validate(LeaveGameRequest)
    async def leave_game(sid, payload):
        await socket_service.leave_game(sid, payload)
