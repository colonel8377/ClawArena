"""Common Socket.IO handlers and shared socket helpers."""

from backend.app.middleware.socket_middleware import socket_auth, socket_event, socket_validate
from backend.services.common_socket_service import (
    CommonSocketService,
)
from backend.views.socket.common import JoinSpectateRequest, LeaveSpectateRequest

def register_common_handlers(sio, state) -> None:
    """Register common Socket.IO events (connect/auth/spectate)."""
    socket_service = CommonSocketService(sio, state)

    @sio.event
    async def connect(sid, environ, auth):
        return await socket_service.connect(sid, environ, auth)

    @sio.event
    async def disconnect(sid):
        await socket_service.disconnect(sid)

    @sio.event
    @socket_event(sio, "Join spectate failed")
    @socket_auth(state, allow_spectator=True)
    @socket_validate(JoinSpectateRequest)
    async def join_spectate(sid, payload):
        await socket_service.join_spectate(sid, payload)

    @sio.event
    @socket_event(sio, "Leave spectate failed")
    @socket_auth(state, allow_spectator=True)
    @socket_validate(LeaveSpectateRequest)
    async def leave_spectate(sid, payload):
        await socket_service.leave_spectate(sid, payload)
