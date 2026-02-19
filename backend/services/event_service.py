import json
import time
import uuid

from backend.config.constants import GameEventType
from backend.repositories.redis_repo import RedisRepo
from backend.services.game_state_service import GameStateService
from backend.utils.log import get_logger
from backend.workers.saq_client import enqueue_task

logger = get_logger(__name__)


class EventService:
    @staticmethod
    async def log_room_event(room_id: int, event_type: str, payload: dict) -> int:
        event_id = uuid.uuid4().hex
        ts_ms = int(time.time() * 1000)
        await RedisRepo.add_game_event(room_id, event_id, event_type, payload, ts_ms)
        actor_id = None
        actor_name = None
        if payload:
            actor_id = payload.get("actor_id") or payload.get("agent_id")
            actor_name = payload.get("actor_name") or payload.get("agent_name")
        try:
            await enqueue_task(
                "persist_game_event",
                event_id=event_id,
                room_id=room_id,
                game_id=int(payload.get("game_id", 0)) if payload else 0,
                actor_id=actor_id,
                actor_name=actor_name,
                phase=payload.get("phase") if payload and payload.get("phase") else "room",
                action_type=event_type,
                payload=payload,
            )
            if payload and payload.get("event_type") == GameEventType.PHASE_CHANGE:
                state = await GameStateService.get_state(room_id)
                if state:
                    await enqueue_task(
                        "persist_game_snapshot",
                        game_id=int(state.get("game_id", 0)),
                        room_id=int(state.get("room_id", room_id)),
                        phase=str(state.get("phase", "")),
                        state_json=json.dumps(state, ensure_ascii=True),
                    )
        except Exception as exc:
            logger.warning("event_enqueue_failed event_id=%s error=%s", event_id, exc)
        return ts_ms
