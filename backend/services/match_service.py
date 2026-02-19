import asyncio
import time

from backend.config.constants import GameType
from backend.config.settings import get_settings
from backend.queue.provider import match_queue

from backend.services.game_init_service import GameInitService
from backend.services.room_service import RoomService
from backend.repositories.kset.room_repo import RoomCache
from backend.repositories.kv.kv_repo import KvRepo
from backend.utils.log import get_logger
from backend.utils.redis_lock import RedisLock

logger = get_logger(__name__)


class MatchService:
    MATCH_CONFIG = {
        int(GameType.WEREWOLF): {"min": 6, "max": 12},
        int(GameType.TEXAS): {"min": 2, "max": 12},
    }

    @staticmethod
    async def try_start(game_type: int) -> None:
        config = MatchService.MATCH_CONFIG.get(game_type)
        if not config:
            return

        lock_key = f"lock:match:{game_type}"
        async with RedisLock(lock_key, ttl_ms=3000) as lock:
            if not lock.acquired:
                return

            queue_key = f"queue:{game_type}"
            size = await match_queue.size(queue_key)
            if size < config["min"]:
                return

            now_ms = int(time.time() * 1000)
            oldest_score = await match_queue.peek_min_score(queue_key)
            if size < config["max"] and oldest_score is not None:
                wait_ms = now_ms - oldest_score
                if wait_ms < get_settings().match_timeout_seconds * 1000:
                    return

            take_count = min(size, config["max"])
            popped = await match_queue.pop_min(queue_key, take_count)
            if not popped:
                return

            members = [agent_id for agent_id, _ in popped]
            room = await RoomService.create_room(0, config["min"], config["max"])
            room_id = room["room_id"]
            try:
                for agent_id in members:
                    await RoomCache.add_room_member(room_id, agent_id)
                    await KvRepo.set_agent_room(agent_id, room_id)
                    await KvRepo.clear_agent_queue(agent_id)
                await GameInitService.start_game(room_id, game_type)
                logger.info("match_started room_id=%s game_type=%s size=%s", room_id, game_type, len(members))
            except Exception as exc:
                logger.warning("match_start_failed room_id=%s error=%s", room_id, exc)
                for agent_id, score in popped:
                    await match_queue.add(queue_key, str(agent_id), score)
                    await KvRepo.set_agent_queue(agent_id, game_type)
                    await KvRepo.clear_agent_room(agent_id)
                    await RoomCache.remove_room_member(room_id, agent_id)
                raise

    @staticmethod
    async def run_loop() -> None:
        settings = get_settings()
        interval = settings.match_interval_seconds
        while True:
            try:
                await MatchService.try_start(int(GameType.WEREWOLF))
                await MatchService.try_start(int(GameType.TEXAS))
            except Exception as exc:
                logger.warning("match_loop_error error=%s", exc)
            await asyncio.sleep(interval)
