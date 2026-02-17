"""Matchmaking Socket.IO handlers."""

from backend.app.middleware.socket_middleware import socket_auth, socket_event, socket_validate
from backend.views.socket.matchmaking import (
    GetMatchmakingStatusRequest,
    GetTexasMatchmakingStatusRequest,
    JoinTexasMatchmakingRequest,
    JoinWerewolfMatchmakingRequest,
    LeaveWerewolfMatchmakingRequest,
    LeaveTexasMatchmakingRequest,
)

def register_matchmaking_handlers(sio, state, coordinator) -> None:
    """Register matchmaking Socket.IO event handlers."""
    @sio.event
    @socket_event(sio, "Join Texas matchmaking failed")
    @socket_auth(state)
    @socket_validate(JoinTexasMatchmakingRequest)
    async def join_texas_matchmaking(sid, payload):
        await coordinator.join_texas_matchmaking(sid, payload)

    @sio.event
    @socket_event(sio, "Leave Texas matchmaking failed")
    @socket_auth(state)
    @socket_validate(LeaveTexasMatchmakingRequest)
    async def leave_texas_matchmaking(sid, payload):
        await coordinator.leave_texas_matchmaking(sid, payload)

    @sio.event
    @socket_event(sio, "Get Texas matchmaking status failed")
    @socket_auth(state)
    @socket_validate(GetTexasMatchmakingStatusRequest)
    async def get_texas_matchmaking_status(sid, payload):
        await coordinator.get_texas_matchmaking_status(sid, payload)

    @sio.event
    @socket_event(sio, "Join werewolf matchmaking failed")
    @socket_auth(state)
    @socket_validate(JoinWerewolfMatchmakingRequest)
    async def join_werewolf_matchmaking(sid, payload):
        await coordinator.join_werewolf_matchmaking(sid, payload)

    @sio.event
    @socket_event(sio, "Leave werewolf matchmaking failed")
    @socket_auth(state)
    @socket_validate(LeaveWerewolfMatchmakingRequest)
    async def leave_werewolf_matchmaking(sid, payload):
        await coordinator.leave_werewolf_matchmaking(sid, payload)

    @sio.event
    @socket_event(sio, "Get werewolf matchmaking status failed")
    @socket_auth(state)
    @socket_validate(GetMatchmakingStatusRequest)
    async def get_werewolf_matchmaking_status(sid, payload):
        await coordinator.get_werewolf_matchmaking_status(sid, payload)
