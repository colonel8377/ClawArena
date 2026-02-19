from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from backend.config.constants import DEFAULT_ENTRY_FEE, GameStatus, PlayerResult, PlayerStatus, RoomState, TxType
from backend.models.game import Game
from backend.repositories.db import db_session
from backend.repositories.game_player_repo import GamePlayerRepo
from backend.repositories.transaction_repo import TransactionRepo
from backend.repositories.redis_repo import RedisRepo
from backend.repositories.wallet_repo import WalletRepo
from backend.services.room_service import RoomService
from backend.utils.log import get_logger
from backend.utils.money import TOKEN_SCALE, to_token
from backend.utils.redis_lock import RedisLock
from backend.views.errors import DomainError

logger = get_logger(__name__)


class TexasSettlementService:
    CHIPS_PER_TOKEN = 10

    @staticmethod
    async def settle(engine) -> dict:
        game_id = int(engine.game_id)
        room_id = int(engine.room_id)
        lock_key = f"lock:texas:settle:{room_id}"
        async with RedisLock(lock_key, ttl_ms=15000) as lock:
            if not lock.acquired:
                raise DomainError("settlement_in_progress", code=40902)

            with db_session() as session:
                game = (
                    session.execute(select(Game).where(Game.id == game_id).with_for_update())
                    .scalars()
                    .first()
                )
                if not game:
                    raise DomainError("game_not_found", code=40405)
                if int(game.status) == int(GameStatus.ENDED):
                    return {"status": "already_settled", "game_id": game_id, "room_id": room_id}
                if int(game.status) == int(GameStatus.SETTLING):
                    return {"status": "settling", "game_id": game_id, "room_id": room_id}

                players = engine.players
                if not players:
                    raise DomainError("no_players", code=40041)

                game.status = int(GameStatus.SETTLING)
                session.add(game)

                prize_pool = to_token(game.prize_pool_tokens or 0)
                entry_fee = to_token(DEFAULT_ENTRY_FEE)
                if prize_pool > 0:
                    entry_fee = to_token(prize_pool / len(players))
                else:
                    prize_pool = to_token(entry_fee * len(players))

                stacks = engine.get_state().get("stacks", {})
                for player in players:
                    agent_id = int(player["agent_id"])
                    stacks.setdefault(agent_id, 0)
                payouts = TexasSettlementService._calc_payouts(stacks, prize_pool)

                for player in players:
                    agent_id = int(player["agent_id"])
                    agent_name = player.get("agent_name", f"agent_{agent_id}")
                    chips = int(stacks.get(agent_id, 0))
                    GamePlayerRepo.update_chips(game_id, agent_id, chips, session=session)

                    consumed = WalletRepo.consume_locked(agent_id, entry_fee, session=session)
                    if not consumed:
                        raise DomainError("locked_balance_missing", code=40042)

                    amount = payouts.get(agent_id, Decimal("0.00"))
                    if amount:
                        WalletRepo.add_tokens(agent_id, amount, session=session)
                        TransactionRepo.insert(
                            agent_id,
                            agent_name,
                            int(TxType.WIN_SHARE),
                            amount,
                            {"game_id": game_id, "room_id": room_id, "chips": chips},
                            session=session,
                        )

                db_players = GamePlayerRepo.list_by_game(game_id, session=session)
                active_stacks = {int(pid): int(stacks.get(int(pid), 0)) for pid in stacks.keys()}
                winners: set[int] = set()
                if active_stacks:
                    max_stack = max(active_stacks.values())
                    winners = {int(pid) for pid, value in active_stacks.items() if value == max_stack}
                results: dict[int, int] = {}
                for row in db_players:
                    agent_id = int(row.agent_id)
                    if int(row.status) == int(PlayerStatus.LEFT):
                        results[agent_id] = int(PlayerResult.EXIT)
                    elif agent_id in winners:
                        results[agent_id] = int(PlayerResult.WIN)
                    else:
                        results[agent_id] = int(PlayerResult.LOSE)
                GamePlayerRepo.update_results(game_id, results, session=session)

                game.status = int(GameStatus.ENDED)
                game.ended_at = datetime.utcnow()
                session.add(game)

            await RoomService.update_state(room_id, int(RoomState.FINISHED))
            await RoomService.broadcast_update(room_id, "game_finish")
            await RedisRepo.remove_active_room(room_id)

            logger.info("texas_settled game_id=%s room_id=%s prize_pool=%s", game_id, room_id, prize_pool)
            return {
                "status": "settled",
                "game_id": game_id,
                "room_id": room_id,
                "prize_pool": prize_pool,
                "payouts": payouts,
                "stacks": stacks,
            }

    @staticmethod
    def _calc_payouts(stacks: dict[int, int], prize_pool: Decimal) -> dict[int, Decimal]:
        payouts: dict[int, Decimal] = {}
        total = Decimal("0.00")
        remainders: list[tuple[Decimal, int, int]] = []
        for agent_id, chips in stacks.items():
            tokens = to_token(Decimal(chips) / Decimal(TexasSettlementService.CHIPS_PER_TOKEN))
            payouts[int(agent_id)] = tokens
            total += tokens
            remainders.append((Decimal(chips) % Decimal(TexasSettlementService.CHIPS_PER_TOKEN), int(chips), int(agent_id)))

        remainder = prize_pool - total
        step = TOKEN_SCALE
        if remainder <= 0:
            return payouts

        ranked = sorted(remainders, key=lambda item: (item[0], item[1]), reverse=True)
        idx = 0
        while remainder >= step and ranked:
            agent_id = int(ranked[idx % len(ranked)][2])
            payouts[agent_id] = payouts.get(agent_id, Decimal("0.00")) + step
            remainder -= step
            idx += 1
        return payouts
