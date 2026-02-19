import time

from backend.queues.provider import queue_backend
from backend.repositories.kv.kv_repo import KvRepo
from backend.utils.log import get_logger

logger = get_logger(__name__)


class QueueService:
    @staticmethod
    async def join(agent_id: int, game_type: int) -> dict:
        now = int(time.time() * 1000)
        previous = await KvRepo.get_agent_queue(agent_id)
        if previous and int(previous) != game_type:
            await queue_backend.remove(f"queue:{int(previous)}", str(agent_id))

        await queue_backend.add(f"queue:{game_type}", str(agent_id), now)
        await KvRepo.set_agent_queue(agent_id, game_type)
        size = await queue_backend.size(f"queue:{game_type}")
        rank = await queue_backend.rank(f"queue:{game_type}", str(agent_id))

        logger.info("queue_join agent_id=%s game_type=%s size=%s", agent_id, game_type, size)
        return {
            "status": "joined",
            "game_type": game_type,
            "queue_size": size,
            "queue_rank": (rank + 1) if rank is not None else None,
        }

    @staticmethod
    async def leave(agent_id: int, game_type: int | None) -> dict:
        if game_type is None:
            previous = await KvRepo.get_agent_queue(agent_id)
            if previous:
                game_type = int(previous)

        if game_type is not None:
            await queue_backend.remove(f"queue:{game_type}", str(agent_id))

        await KvRepo.clear_agent_queue(agent_id)
        logger.info("queue_leave agent_id=%s game_type=%s", agent_id, game_type)
        return {"status": "left", "game_type": game_type}
