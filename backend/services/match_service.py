import asyncio
import time
from decimal import Decimal

from sqlalchemy import select

from backend.config.constants import DEFAULT_ENTRY_FEE, GameType, RoomState
from backend.config.settings import get_settings
from backend.queues.provider import match_queue

from backend.services.game_init_service import GameInitService
from backend.services.room_service import RoomService
from backend.repositories.kset.room_repo import RoomCache
from backend.repositories.kv.kv_repo import KvRepo
from backend.repositories.db import db_session
from backend.models.wallet import AgentWallet
from backend.utils.money import to_token
from backend.utils.log import get_logger
from backend.utils.action_guard import ActionGuard
from backend.views.response import ok, fail
from backend.config.constants import SocketEvent
from backend.utils.log import get_logger
from backend.views.errors import DomainError, AppError

logger = get_logger(__name__)


class MatchService:
    MATCH_CONFIG = {
        int(GameType.WEREWOLF): {"min": 6, "max": 12},
        int(GameType.TEXAS): {"min": 2, "max": 12},
    }

    @staticmethod
    def _filter_sufficient_tokens(agent_ids: list[int], entry_fee: Decimal) -> set[int]:
        if not agent_ids:
            return set()
        with db_session() as session:
            rows = session.execute(
                select(AgentWallet.agent_id, AgentWallet.token_balance).where(AgentWallet.agent_id.in_(agent_ids))
            ).all()
        eligible: set[int] = set()
        for agent_id, balance in rows:
            if balance is not None and balance >= entry_fee:
                eligible.add(int(agent_id))
        return eligible

    @staticmethod
    async def _notify_insufficient(agent_ids: list[int], game_type: int, entry_fee: Decimal) -> None:
        if not agent_ids:
            return
        from backend.sockets.server import sio

        payload = fail("insufficient_tokens", 40033)
        payload["data"] = {"game_type": int(game_type), "entry_fee": float(entry_fee)}
        for agent_id in agent_ids:
            await sio.emit(SocketEvent.SYSTEM_ERROR, payload, room=f"agent:{int(agent_id)}")

    @staticmethod
    async def try_start(game_type: int) -> None:
        config = MatchService.MATCH_CONFIG.get(game_type)
        if not config:
            return

        queue_key = f"queue:{game_type}"
        size = await match_queue.size(queue_key)
        if size < config["min"]:
            return

        popped = []
        entry_fee = to_token(DEFAULT_ENTRY_FEE)
        
        # 优化：缩小锁范围，仅在操作队列时加锁
        try:
            async with ActionGuard(game_type, timeout=0.5, lock_ttl_ms=3000, key_prefix="lock:match"):
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
        except DomainError:
            return
        except Exception as e:
            logger.warning("match_queue_error game_type=%s error=%s", game_type, e)
            return

        if not popped:
            return

        # 以下逻辑移出锁外，提高并发度
        try:
            members = [int(agent_id) for agent_id, _ in popped]
            eligible = MatchService._filter_sufficient_tokens(members, entry_fee)
            members = [agent_id for agent_id in members if agent_id in eligible]

            if len(members) < config["min"]:
                # Re-add eligible players to queue, drop insufficient ones.
                dropped = [int(agent_id) for agent_id, _ in popped if int(agent_id) not in eligible]
                for agent_id, score in popped:
                    if int(agent_id) in eligible:
                        await match_queue.add(queue_key, str(agent_id), score)
                    else:
                        await KvRepo.clear_agent_queue(int(agent_id))
                await MatchService._notify_insufficient(dropped, game_type, entry_fee)
                logger.info(
                    "match_filtered_insufficient game_type=%s eligible=%s dropped=%s",
                    game_type,
                    len(eligible),
                    len(popped) - len(eligible),
                )
                return

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
                # 这里的异常处理逻辑保持不变，确保回滚
                if isinstance(exc, AppError) and exc.code == 40033:
                    eligible = MatchService._filter_sufficient_tokens([int(aid) for aid, _ in popped], entry_fee)
                    dropped = [int(agent_id) for agent_id, _ in popped if int(agent_id) not in eligible]
                    for agent_id, score in popped:
                        if int(agent_id) in eligible:
                            await match_queue.add(queue_key, str(agent_id), score)
                            await KvRepo.set_agent_queue(agent_id, game_type)
                        else:
                            await KvRepo.clear_agent_queue(int(agent_id))
                        await KvRepo.clear_agent_room(int(agent_id))
                        await RoomCache.remove_room_member(room_id, int(agent_id))
                    await MatchService._notify_insufficient(dropped, game_type, entry_fee)
                else:
                    for agent_id, score in popped:
                        await match_queue.add(queue_key, str(agent_id), score)
                        await KvRepo.set_agent_queue(agent_id, game_type)
                        await KvRepo.clear_agent_room(agent_id)
                        await RoomCache.remove_room_member(room_id, agent_id)
                try:
                    await RoomService.update_state(room_id, int(RoomState.FINISHED))
                except Exception as cleanup_exc:
                    logger.warning("match_cleanup_failed room_id=%s error=%s", room_id, cleanup_exc)
                if not (isinstance(exc, AppError) and exc.code == 40033):
                    raise
        except Exception as e:
            logger.warning("match_process_error game_type=%s error=%s", game_type, e)
            return

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
