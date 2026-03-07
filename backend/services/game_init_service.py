import time

from backend.config.constants import DEFAULT_ENTRY_FEE, GameStatus, GameType, PlayerStatus, RoomState, TxType
from backend.domain.texas.engine import TexasEngine
from backend.domain.werewolf.engine import WerewolfEngine
from backend.repositories.agent_repo import AgentRepo
from backend.repositories.db import db_session
from backend.repositories.game_player_repo import GamePlayerRepo
from backend.repositories.game_repo import GameRepo
from backend.repositories.kset.room_repo import RoomCache
from backend.repositories.room_repo import RoomRepo
from backend.repositories.redis_repo import RedisRepo
from backend.repositories.transaction_repo import TransactionRepo
from backend.repositories.wallet_repo import WalletRepo
from backend.services.event_service import EventService
from backend.services.game_state_service import GameStateService
from backend.services.room_service import RoomService
from backend.utils.log import get_logger
from backend.utils.money import to_token
from backend.utils.action_guard import ActionGuard
from backend.views.errors import DomainError

logger = get_logger(__name__)


class GameInitService:
    @staticmethod
    async def start_game(room_id: int, game_type: int) -> dict:
        # 使用 ActionGuard 替代 RedisLock，允许 5 秒排队等待
        # key_prefix="lock:room" 对应原来的 lock:room:{room_id}
        async with ActionGuard(room_id, timeout=5.0, lock_ttl_ms=8000, key_prefix="lock:room"):
            room = RoomRepo.get_by_id(room_id)
            if not room:
                raise DomainError("room_not_found", code=40402)

            members = await RoomCache.get_room_members(room_id)
            if len(members) < room.min_players:
                raise DomainError("not_enough_players", code=40031)
            if len(members) > room.max_players:
                raise DomainError("too_many_players", code=40032)

            name_map = AgentRepo.get_names_by_ids(members)
            players = []
            entry_fee = to_token(DEFAULT_ENTRY_FEE)
            for idx, agent_id in enumerate(members, start=1):
                players.append(
                    {
                        "agent_id": agent_id,
                        "agent_name": name_map.get(agent_id, f"agent_{agent_id}"),
                        "seat": idx,
                        "status": int(PlayerStatus.ALIVE),
                        "chips": 1000 if game_type == int(GameType.TEXAS) else 0,
                    }
                )

            with db_session() as session:
                prize_pool = to_token(entry_fee * len(players))
                game = GameRepo.create(game_type, int(GameStatus.ACTIVE), prize_pool_tokens=prize_pool, session=session)
                attached = RoomRepo.attach_game(
                    room_id,
                    game.id,
                    int(RoomState.ACTIVE),
                    expected_state=int(RoomState.IDLE),
                    session=session,
                )
                if not attached:
                    raise DomainError("room_start_in_progress", code=40901)

                for player in players:
                    locked = WalletRepo.lock_tokens(player["agent_id"], entry_fee, session=session)
                    if not locked:
                        raise DomainError("insufficient_tokens", code=40033)
                    TransactionRepo.insert(
                        player["agent_id"],
                        player["agent_name"],
                        int(TxType.ENTRY_FEE),
                        -entry_fee,
                        {"room_id": room_id, "game_type": game_type},
                        session=session,
                    )

                GamePlayerRepo.create_many(game.id, room_id, players, session=session)

            await RedisRepo.set_room_state(room_id, int(RoomState.ACTIVE))
            await RedisRepo.add_active_room(room_id)

            seed = int(time.time() * 1000)
            if game_type == int(GameType.WEREWOLF):
                engine = WerewolfEngine(game.id, room_id, players, seed=seed)
            elif game_type == int(GameType.TEXAS):
                engine = TexasEngine(game.id, room_id, players, seed=seed)
            else:
                raise DomainError("unsupported_game_type", code=40022)

            await GameStateService.save_state(
                room_id,
                engine.dump_state(),
                public_state=engine.build_public_state(),
            )
            await RoomService.broadcast_update(room_id, "game_start")

            logger.info("game_start room_id=%s game_id=%s game_type=%s", room_id, game.id, game_type)
            return {"game_id": game.id, "room_id": room_id, "game_type": game_type}
