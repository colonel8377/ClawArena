from backend.config.constants import GameEventType, SocketEvent, WerewolfAction
from backend.middleware.decorators import socket_handler
from backend.services.event_service import EventService
from backend.services.game_action_service import GameActionService
from backend.socket.broadcast import emit_room_event
from backend.socket.guards import socket_dedupe_action, socket_rate_limit, socket_require_agent, socket_require_room_player, socket_validate
from backend.views.requests import WerewolfActionRequest
from backend.views.response import ok
from backend.views.errors import DomainError


def register(server):
    @server.on(SocketEvent.WW_ACTION)
    @socket_validate(WerewolfActionRequest)
    @socket_require_agent(server)
    @socket_require_room_player(server)
    @socket_dedupe_action(server)
    @socket_rate_limit(server, "10/second")
    @socket_handler(server)
    async def ww_action(sid, agent_id, payload):
        events = await GameActionService.handle_werewolf(
            payload.room_id,
            agent_id,
            payload.action.value,
            payload.payload,
        )
        for event in events:
            event_name = SocketEvent.WW_NIGHT_ACTION
            private = False
            event_type = event.get("event_type")
            action_type = event.get("action_type")
            if event_type == GameEventType.PHASE_CHANGE:
                event_name = SocketEvent.WW_PHASE_CHANGE
            else:
                if action_type not in {a.value for a in WerewolfAction}:
                    raise DomainError("invalid_action_type", code=40017)
                if action_type == WerewolfAction.WOLF_CHAT.value:
                    event_name = SocketEvent.WW_CHAT_WOLF
                    private = True
                elif action_type == WerewolfAction.SPEAK.value:
                    event_name = SocketEvent.WW_CHAT_DAY
                elif action_type == WerewolfAction.VOTE.value:
                    event_name = SocketEvent.WW_DAY_VOTE
            await EventService.log_room_event(payload.room_id, event_name, event)
            await emit_room_event(server, payload.room_id, event_name, ok(event), private=private)
        return {"events": events}
