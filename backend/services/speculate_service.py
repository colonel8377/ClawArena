
from datetime import datetime
from typing import Optional, Dict, Any, List

from sqlalchemy import select, or_, and_, desc

from backend.constant.api_error import GameNotFoundError
from backend.constant.speculate import STALE_THRESHOLD
from backend.database.connection import get_async_db_session
from backend.database.models import GameSession, GameStatus, GameType, GameTypeInt, UserLedger
from backend.database.redis_manager import redis_manager
from backend.games.texas.texas_game import TexasGame
from backend.games.werewolf.werewolf_game import WerewolfGame
from backend.utils.number_util import _to_decimal_safe
from backend.views.api.spectate_view import ActiveGamesResponse, GameCounts


async def get_active_games(q: Optional[str] = None) -> ActiveGamesResponse:
    """
    List active poker tables and werewolf games for spectators.
    Queries the database GameSession table for games with active status and recent updates.
    """
    cutoff = datetime.utcnow() - STALE_THRESHOLD

    async with get_async_db_session() as db:
        query = select(GameSession).where(
            or_(
                GameSession.status == GameStatus.WAITING.value,
                GameSession.status == GameStatus.ACTIVE.value
            ),
            GameSession.updated_at > cutoff
        )

        if q:
            query = query.where(GameSession.id.contains(q))

        query = query.limit(100)
        result = await db.execute(query)
        sessions = result.scalars().all()

    poker_ids = []
    werewolf_ids = []

    for s in sessions:
        # Use game_type_id if available, otherwise fallback to string check
        if s.game_type_id == GameTypeInt.TEXAS.value or s.game_type == GameType.TEXAS.value:
            poker_ids.append(s.id)
        elif s.game_type_id == GameTypeInt.WEREWOLF.value or s.game_type == GameType.WEREWOLF.value:
            werewolf_ids.append(s.id)

    return ActiveGamesResponse(
        poker_tables=poker_ids,
        werewolf_games=werewolf_ids,
        total=GameCounts(
            poker=len(poker_ids),
            werewolf=len(werewolf_ids)
        )
    )


async def get_spectate_state(game_id: str, reveal: bool) -> Dict[str, Any]:
    """
    Get public state of a game (poker or werewolf) from database snapshot.
    Unified method handling both game types.
    """
    async with get_async_db_session() as db:
        query = select(GameSession).where(
            and_(
                GameSession.game_id == game_id,
                GameSession.state_snapshot.isnot(None)
            )
        )

        result = await db.execute(query)
        session = result.scalar_one_or_none()

    if not session:
        raise GameNotFoundError(f"Game {game_id} not found or state unavailable")

    try:

        if session.game_type == GameType.TEXAS.value:
            game = TexasGame.from_dict(session.state_snapshot)
            return game.get_game_state(for_spectator=True, reveal_all=reveal)

        elif session.game_type == GameType.WEREWOLF.value:
            game = WerewolfGame.from_dict(session.state_snapshot)
            return game.get_game_state(reveal_all=reveal)

        else:
            # Fallback for unknown types if they sneak in
            raise GameNotFoundError(f"Unsupported game type for spectating: {session.game_type}")

    except Exception as e:
        raise GameNotFoundError(f"Failed to load game state: {str(e)}")


async def get_leaderboard(is_default: bool,  limit: int) -> List[Dict[str, Any]]:
    """
    Get top players by token balance.

    Uses Redis cache for the default top-10 leaderboard with 60s TTL.

    Args:
        is_default: bool
        limit: Number of players to return

    Returns:
        List of leaderboard entries sorted by offchain balance descending
    """

    # Cache only the canonical top-10 query.
    if is_default:
        try:
            cached_entries = await redis_manager.get_cached_leaderboard()
            if cached_entries:
                entries = []
                for idx, row in enumerate(cached_entries, start=1):
                    balance = _to_decimal_safe(row.get("offchain_balance", "0"))
                    entries.append({
                        "rank": idx,
                        "player_id": row.get("player_id", ""),
                        "player_name": row.get("player_name", "Player"),
                        "balance": str(balance),
                    })
                return entries
        except Exception:
            # Fall through to DB query on cache errors.
            pass

    async with get_async_db_session() as db:
        stmt = (
            select(UserLedger.player_id, UserLedger.player_name, UserLedger.offchain_balance)
            .order_by(desc(UserLedger.offchain_balance), UserLedger.player_id)
            .limit(limit)
        )
        result = await db.execute(stmt)
        rows = result.all()

    entries: List[Dict[str, Any]] = []
    cache_payload: List[Dict[str, str]] = []

    for idx, row in enumerate(rows, start=1):
        player_id = row[0] if len(row) > 0 else ""
        player_name = row[1] if len(row) > 1 else "Player"
        balance = _to_decimal_safe(row[2] if len(row) > 2 else None)
        entries.append({
            "rank": idx,
            "player_id": player_id or "",
            "player_name": player_name or "Player",
            "balance": str(balance),
        })
        cache_payload.append({
            "player_id": player_id or "",
            "player_name": player_name or "Player",
            "offchain_balance": str(balance),
        })

    if is_default:
        try:
            await redis_manager.set_cached_leaderboard(cache_payload)
        except Exception:
            # Cache write failure should not affect response.
            pass
