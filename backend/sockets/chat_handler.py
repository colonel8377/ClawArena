from backend.config.constants import ChatChannel, GameType, SocketEvent, WerewolfPhase
from backend.middleware.decorators import socket_handler
from backend.services.event_service import EventService
from backend.services.game_state_service import GameStateService
from backend.sockets.broadcast import emit_room_event
from backend.sockets.guards import socket_dedupe_action, socket_rate_limit, socket_require_agent, socket_require_room_player, socket_validate
from backend.views.errors import DomainError
from backend.views.requests import RoomChatRequest
from backend.views.response import ok

def _build_meta(state: dict, sender_id: int) -> dict:
    meta: dict = {}
    if not state:
        return meta
    meta["game_type"] = state.get("game_type")
    meta["phase"] = state.get("phase")
    if "day" in state:
        meta["day"] = state.get("day")
    if "hand_index" in state:
        meta["hand_index"] = state.get("hand_index")
    if "current_speaker" in state:
        meta["current_speaker"] = state.get("current_speaker")
    if "actor_id" in state:
        meta["actor_id"] = state.get("actor_id")
    if sender_id:
        meta["sender_id"] = sender_id
    return meta


def _ensure_chat_allowed(game_state: dict, sender_id: int, channel: ChatChannel) -> None:
    if not game_state:
        raise DomainError("game_state_missing", code=40403)
    game_type = int(game_state.get("game_type", 0))
    if game_type == int(GameType.WEREWOLF):
        phase = game_state.get("phase")
        alive = set(game_state.get("alive") or [])
        if sender_id not in alive:
            raise DomainError("actor_not_alive", code=40011)
        roles = game_state.get("roles") or {}
        role = roles.get(str(sender_id)) or roles.get(sender_id) or {}
        role_id = role.get("role")

        if channel == ChatChannel.WOLF:
            if phase != WerewolfPhase.WOLF_CHAT:
                raise DomainError("chat_phase_invalid", code=40062)
            if int(role_id or 0) != 1:
                raise DomainError("chat_role_invalid", code=40063)
            return

        if channel == ChatChannel.DAY:
            if phase != WerewolfPhase.DAY_DEBATE:
                raise DomainError("chat_phase_invalid", code=40062)
            current_speaker = game_state.get("current_speaker")
            if current_speaker and int(current_speaker) != int(sender_id):
                raise DomainError("invalid_speaker_turn", code=40019)
            return

        raise DomainError("chat_channel_invalid", code=40064)

    if game_type == int(GameType.TEXAS):
        if channel != ChatChannel.ROOM:
            raise DomainError("chat_channel_invalid", code=40064)
        return

    raise DomainError("chat_not_allowed", code=40061)


def register(server):
    @server.on(SocketEvent.ROOM_CHAT_SEND)
    @socket_handler(server)
    @socket_validate(RoomChatRequest)
    @socket_require_agent(server)
    @socket_require_room_player(server)
    @socket_dedupe_action(server)
    @socket_rate_limit(server, "1/3s", key_prefix="chat")
    async def room_chat_send(sid, agent_id, payload):
        state = await GameStateService.get_state(payload.room_id)
        _ensure_chat_allowed(state or {}, agent_id, payload.channel)

        session = await server.get_session(sid)
        agent_name = session.get("agent_name") if session else None

        event_payload = {
            "room_id": payload.room_id,
            "game_id": int(state.get("game_id", 0) if state else 0),
            "game_type": int(state.get("game_type", 0) if state else 0),
            "sender_id": agent_id,
            "sender_name": agent_name,
            "channel": payload.channel,
            "content": payload.content,
            "meta": _build_meta(state or {}, agent_id),
            "action_id": payload.action_id,
        }
        envelope = await EventService.log_room_event(payload.room_id, SocketEvent.ROOM_CHAT, event_payload)
        private = False
        await emit_room_event(server, payload.room_id, SocketEvent.ROOM_CHAT, ok(envelope), private=private)
        return {"status": "sent"}
