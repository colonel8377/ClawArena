from backend.config.constants import GameEventType, SocketEvent, TexasAction
from backend.middleware.decorators import socket_handler
from backend.services.event_service import EventService
from backend.services.game_action_service import GameActionService
from backend.socket.broadcast import emit_room_event
from backend.socket.guards import socket_dedupe_action, socket_rate_limit, socket_require_agent, socket_require_room_player, socket_validate
from backend.views.requests import TexasActionRequest
from backend.views.response import ok
from backend.views.errors import DomainError


def register(server):
    @server.on(SocketEvent.TX_ACTION)
    @socket_validate(TexasActionRequest)
    @socket_require_agent(server)
    @socket_require_room_player(server)
    @socket_dedupe_action(server)
    @socket_rate_limit(server, "10/second")
    @socket_handler(server)
    async def tx_action(sid, agent_id, payload):
        events = await GameActionService.handle_texas(
            payload.room_id,
            agent_id,
            payload.action.value,
            payload.payload,
        )
        for event in events:
            event_type = event.get("event_type")
            action_type = event.get("action_type")
            if event_type == GameEventType.PHASE_CHANGE:
                event_name = SocketEvent.TX_PHASE_CHANGE
            else:
                if action_type not in {a.value for a in TexasAction}:
                    raise DomainError("invalid_action_type", code=40027)
                action_name = TexasAction(action_type).name.lower()
                event_name = f"tx:{action_name}"
            await EventService.log_room_event(payload.room_id, event_name, event)
            await emit_room_event(server, payload.room_id, event_name, ok(event), private=False)
        return {"events": events}
