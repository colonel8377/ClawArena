"""Werewolf Socket.IO handlers."""

from backend.app.middleware.socket_middleware import socket_auth, socket_event, socket_validate
from backend.services.werewolf_socket_service import WerewolfSocketService
from backend.views.socket.werewolf import (
    AdvanceWerewolfPhaseRequest,
    CreateWerewolfGameRequest,
    GetWerewolfStateRequest,
    JoinWerewolfGameRequest,
    StartWerewolfGameRequest,
    WerewolfActionRequest,
)

def register_werewolf_handlers(sio, state, coordinator) -> None:
    """Register Werewolf Socket.IO event handlers."""
    socket_service = WerewolfSocketService(coordinator)

    @sio.event
    @socket_event(sio, "Create game failed")
    @socket_auth(state)
    @socket_validate(CreateWerewolfGameRequest)
    async def create_werewolf_game(sid, payload):
        await socket_service.create_game(sid, payload)

    @sio.event
    @socket_event(sio, "Join werewolf game failed")
    @socket_auth(state)
    @socket_validate(JoinWerewolfGameRequest)
    async def join_werewolf_game(sid, payload):
        await socket_service.join_game(sid, payload)

    @sio.event
    @socket_event(sio, "Start werewolf game failed")
    @socket_auth(state)
    @socket_validate(StartWerewolfGameRequest)
    async def start_werewolf_game(sid, payload):
        await socket_service.start_game(sid, payload)

    @sio.event
    @socket_event(sio, "Werewolf action failed")
    @socket_auth(state)
    @socket_validate(WerewolfActionRequest)
    async def werewolf_action(sid, payload):
        await socket_service.process_action(sid, payload)

    @sio.event
    @socket_event(sio, "Advance phase failed")
    @socket_auth(state)
    @socket_validate(AdvanceWerewolfPhaseRequest)
    async def advance_werewolf_phase(sid, payload):
        await socket_service.advance_phase(sid, payload)

    @sio.event
    @socket_event(sio, "Get werewolf state failed")
    @socket_auth(state, allow_spectator=True)
    @socket_validate(GetWerewolfStateRequest)
    async def get_werewolf_state(sid, payload):
        await socket_service.get_state(sid, payload)
