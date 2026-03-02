from typing import Any

from backend.repositories.chat_message_repo import ChatMessageRepo
from backend.repositories.event_repo import EventRepo
from backend.repositories.game_snapshot_repo import GameSnapshotRepo
from backend.repositories.system_event_repo import SystemEventRepo
from backend.utils.log import get_logger

logger = get_logger(__name__)


async def persist_system_event(
    ctx: Any,
    *,
    event_id: str,
    event_type: str,
    message: str,
    payload: dict,
    agent_id: int | None = None,
    agent_name: str | None = None,
) -> None:
    SystemEventRepo.insert(event_id, event_type, message, payload, agent_id, agent_name)
    logger.info("system_event_persisted event_id=%s", event_id)


async def persist_game_event(
    ctx: Any,
    *,
    event_id: str,
    room_id: int,
    game_id: int = 0,
    actor_id: int | None = None,
    actor_name: str | None = None,
    phase: str = "room",
    action_type: str = "",
    payload: dict,
) -> None:
    EventRepo.insert_game_event(event_id, game_id, room_id, actor_id, actor_name, phase, action_type, payload)
    logger.info("game_event_persisted event_id=%s", event_id)


async def persist_game_snapshot(
    ctx: Any,
    *,
    game_id: int,
    room_id: int,
    phase: str,
    state_json: str,
) -> None:
    GameSnapshotRepo.insert(game_id, room_id, phase, state_json)
    logger.info("game_snapshot_persisted room_id=%s phase=%s", room_id, phase)


async def persist_chat_message(
    ctx: Any,
    *,
    stream_id: str,
    event_id: str | None = None,
    action_id: str | None = None,
    room_id: int,
    game_id: int,
    game_type: int,
    channel: int,
    sender_id: int | None = None,
    sender_name: str | None = None,
    content: str,
    ts_ms: int,
) -> None:
    ChatMessageRepo.insert(
        stream_id=stream_id,
        event_id=event_id,
        action_id=action_id,
        room_id=room_id,
        game_id=game_id,
        game_type=game_type,
        channel=channel,
        sender_id=sender_id,
        sender_name=sender_name,
        content=content,
        ts_ms=ts_ms,
    )
    logger.info("chat_message_persisted stream_id=%s", stream_id)
