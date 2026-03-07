import uuid

from backend.repositories.redis_repo import RedisRepo
from backend.utils.log import get_logger
from backend.workers.saq_client import enqueue_task

logger = get_logger(__name__)


class SystemEventService:
    @staticmethod
    async def enqueue(event_type: str, message: str, payload: dict, agent_id: int | None, agent_name: str | None) -> None:
        event_id = uuid.uuid4().hex
        data = {
            "event_id": event_id,
            "event_type": event_type,
            "message": message,
            "payload": payload,
            "agent_id": agent_id,
            "agent_name": agent_name,
        }
        await RedisRepo.add_system_event(event_id, data)
        try:
            await enqueue_task(
                "persist_system_event",
                event_id=event_id,
                event_type=event_type,
                message=message,
                payload=payload,
                agent_id=agent_id,
                agent_name=agent_name,
            )
        except Exception as exc:
            logger.warning("system_event_enqueue_failed event_id=%s error=%s", event_id, exc)
