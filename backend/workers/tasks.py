from typing import Any

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
