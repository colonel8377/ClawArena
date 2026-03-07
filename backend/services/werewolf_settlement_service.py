from datetime import datetime
from decimal import Decimal

from sqlalchemy import select

from backend.config.constants import DEFAULT_ENTRY_FEE, GameStatus, PlayerResult, PlayerStatus, RoomState, TxType, WerewolfRole, WerewolfWinner
from backend.repositories.agent_repo import AgentRepo
from backend.models.game import Game
from backend.repositories.db import db_session
from backend.repositories.game_player_repo import GamePlayerRepo
from backend.repositories.transaction_repo import TransactionRepo
from backend.repositories.wallet_repo import WalletRepo
from backend.repositories.redis_repo import RedisRepo
from backend.utils.log import get_logger
from backend.utils.money import split_token_pool, to_token
from backend.utils.action_guard import ActionGuard
from backend.views.errors import DomainError

logger = get_logger(__name__)


class WerewolfSettlementService:
    WINNER_SHARE = 0.7

    @staticmethod
    async def settle(engine) -> dict:
        from backend.services.room_service import RoomService

        game_id = int(engine.game_id)
        room_id = int(engine.room_id)
        
        # 移除内部锁：调用方（GameActionService 或 OfflineMonitorService）已持有 lock:action:{room_id}
        # 此时房间状态是独占的，直接进行结算即可，避免嵌套锁死锁和额外的 Redis 开销
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

            state = engine.dump_state()
            winner = state.get("winner")
            roles = state.get("roles") or {}
            alive = set(state.get("alive") or [])
            players = engine.players

            if not winner:
                raise DomainError("winner_missing", code=40051)
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

            payouts: dict[int, Decimal] = {}

            if winner == WerewolfWinner.NO_CONTEST:
                for player in players:
                    agent_id = int(player["agent_id"])
                    unlocked = WalletRepo.unlock_tokens(agent_id, entry_fee, session=session)
                    if not unlocked:
                        raise DomainError("locked_balance_missing", code=40042)
                    payouts[agent_id] = entry_fee

                db_players = GamePlayerRepo.list_by_game(game_id, session=session)
                results: dict[int, int] = {}
                for row in db_players:
                    agent_id = int(row.agent_id)
                    if int(row.status) == int(PlayerStatus.LEFT):
                        results[agent_id] = int(PlayerResult.EXIT)
                    else:
                        results[agent_id] = int(PlayerResult.UNKNOWN)
                GamePlayerRepo.update_results(game_id, results, session=session)
            else:
                winners = WerewolfSettlementService._resolve_faction_members(winner, roles)
                survivors = {int(agent_id) for agent_id in alive}

                if not winners and survivors:
                    winners = survivors
                if not survivors and winners:
                    survivors = winners

                winner_pool = to_token(prize_pool * Decimal(str(WerewolfSettlementService.WINNER_SHARE)))
                survivor_pool = to_token(prize_pool - winner_pool)

                payouts = split_token_pool(winner_pool, winners)
                survivor_payouts = split_token_pool(survivor_pool, survivors)
                for agent_id, amount in survivor_payouts.items():
                    payouts[agent_id] = payouts.get(agent_id, Decimal("0.00")) + amount

                name_map = AgentRepo.get_names_by_ids([p["agent_id"] for p in players])
                for player in players:
                    agent_id = int(player["agent_id"])
                    agent_name = name_map.get(agent_id, player.get("agent_name", f"agent_{agent_id}"))
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
                            {"game_id": game_id, "room_id": room_id, "winner": winner},
                            session=session,
                        )

                db_players = GamePlayerRepo.list_by_game(game_id, session=session)
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

        logger.info("werewolf_settled game_id=%s room_id=%s prize_pool=%s", game_id, room_id, prize_pool)
        return {
            "status": "settled",
            "game_id": game_id,
            "room_id": room_id,
            "prize_pool": prize_pool,
            "winner": winner,
            "payouts": payouts,
        }

    @staticmethod
    def _resolve_faction_members(winner: str, roles: dict) -> set[int]:
        members: set[int] = set()
        for agent_id, role_info in roles.items():
            role_id = role_info.get("role") if isinstance(role_info, dict) else role_info
            if role_id is None:
                continue
            if winner == WerewolfWinner.WOLVES and int(role_id) == int(WerewolfRole.WEREWOLF):
                members.add(int(agent_id))
            if winner == WerewolfWinner.VILLAGERS and int(role_id) != int(WerewolfRole.WEREWOLF):
                members.add(int(agent_id))
        return members
