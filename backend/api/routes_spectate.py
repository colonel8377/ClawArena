"""Spectate routes."""

from typing import Optional
from fastapi import APIRouter, Request, HTTPException
from app.state import runtime_state

router = APIRouter()

@router.get("/api/games/active")
async def api_list_active_games(request: Request, q: Optional[str] = None):
    """
    List active poker tables and werewolf games for spectators.
    Optional substring filter via `q`.
    """
    q_lower = q.lower() if q else None

    def _filter(items):
        if not q_lower:
            return items
        return [item for item in items if q_lower in item.lower()]

    poker_list = _filter(list(runtime_state.poker_tables.keys()))
    werewolf_list = _filter(list(runtime_state.werewolf_games.keys()))

    return {
        "poker_tables": poker_list,
        "werewolf_games": werewolf_list,
        "total": {
            "poker": len(poker_list),
            "werewolf": len(werewolf_list)
        }
    }


@router.get("/api/spectate/poker/{table_id}")
async def api_spectate_poker(request: Request, table_id: str, reveal: bool = False):
    if reveal:
        raise HTTPException(
            status_code=400,
            detail="Reveal mode is only available via read-only Socket.IO spectate",
        )

    table = runtime_state.poker_tables.get(table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Poker table not found")

    return table.get_game_state(for_spectator=True, reveal_all=False)


@router.get("/api/spectate/werewolf/{game_id}")
async def api_spectate_werewolf(request: Request, game_id: str, reveal: bool = False):
    if reveal:
        raise HTTPException(
            status_code=400,
            detail="Reveal mode is only available via read-only Socket.IO spectate",
        )

    game = runtime_state.werewolf_games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Werewolf game not found")

    return game.get_game_state(reveal_all=False)
