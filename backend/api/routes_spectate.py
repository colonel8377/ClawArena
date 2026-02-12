"""Spectate routes."""

from typing import Optional
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Request, HTTPException
from backend.app.state import runtime_state
from backend.config.arena_config import is_local_debug_mode

router = APIRouter()


def _format_dt(value) -> Optional[str]:
    parsed = _as_utc(value)
    return parsed.isoformat() if parsed else None


def _coerce_datetime(value) -> Optional[datetime]:
    """Best-effort parse of datetime values loaded from memory/redis."""
    if isinstance(value, datetime):
        return value
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        # Accept both `...Z` and normal ISO format strings.
        if text.endswith("Z"):
            text = f"{text[:-1]}+00:00"
        try:
            return datetime.fromisoformat(text)
        except ValueError:
            return None
    return None


def _as_utc(dt) -> Optional[datetime]:
    """Normalize datetime values into timezone-aware UTC for safe comparisons."""
    parsed = _coerce_datetime(dt)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _phase_to_str(phase_value) -> str:
    """Normalize enum/string phase values into a comparable lowercase token."""
    raw = getattr(phase_value, "value", phase_value)
    text = str(raw or "").strip().lower()
    # Handles values like "WerewolfPhase.FINISHED" from mixed serializers.
    if "." in text:
        text = text.split(".")[-1]
    return text


def _poker_last_activity_at(table, fallback: datetime) -> datetime:
    """Best-effort activity timestamp for poker active-session filtering."""
    candidates = [getattr(table, "created_at", None)]

    last_action_map = getattr(table, "last_action_time", None)
    if isinstance(last_action_map, dict):
        candidates.extend(ts for ts in last_action_map.values() if ts)

    engine = getattr(table, "engine", None)
    if engine is not None:
        turn_started_at = getattr(engine, "turn_started_at", None)
        if turn_started_at:
            candidates.append(turn_started_at)

        engine_players = getattr(engine, "players", {}) or {}
        for player in engine_players.values():
            player_last_action = getattr(player, "last_action_time", None)
            if player_last_action:
                candidates.append(player_last_action)

    valid = [converted for ts in candidates if (converted := _as_utc(ts)) is not None]
    return max(valid) if valid else fallback


def _is_terminal_poker_table(table) -> bool:
    """Defensive terminal check for poker table lifecycle."""
    engine = getattr(table, "engine", None)
    phase_val = _phase_to_str(getattr(engine, "phase", None) or getattr(table, "phase", None))
    # During active hand phases, a table can be non-restartable (e.g., all-in)
    # but still in-progress and must remain visible to spectators.
    if phase_val in ("pre_flop", "flop", "turn", "river"):
        return False

    if phase_val in ("finished", "aborted"):
        return True

    is_game_over = getattr(table, "is_game_over", None)
    if callable(is_game_over) and is_game_over():
        return True

    return False


def _werewolf_last_activity_at(game, fallback: datetime) -> datetime:
    """Best-effort activity timestamp for werewolf active-session filtering."""
    candidates = [
        getattr(game, "created_at", None),
        getattr(game, "started_at", None),
    ]

    last_action_map = getattr(game, "last_action_time", None)
    if isinstance(last_action_map, dict):
        candidates.extend(ts for ts in last_action_map.values() if ts)

    # Important: do NOT use phase heartbeat timestamps here. Timeout-driven
    # auto-advances can keep refreshing phase time even when no real player
    # has acted for a long time, which would make stale games look "active".

    valid = [converted for ts in candidates if (converted := _as_utc(ts)) is not None]
    return max(valid) if valid else fallback

@router.get("/api/games/active")
async def api_list_active_games(request: Request, q: Optional[str] = None):
    """
    List active poker tables and werewolf games for spectators.
    Optional substring filter via `q`.
    
    Filters out:
    - Finished/Aborted games
    - Stale games (no activity for > 30 mins)
    - Empty Poker tables created > 1 hour ago
    """
    q_lower = q.lower() if q else None
    now = datetime.now(timezone.utc)
    STALE_THRESHOLD = timedelta(minutes=30)
    WAITING_STALE_THRESHOLD = timedelta(hours=1)
    POKER_INACTIVE_THRESHOLD = timedelta(hours=1)
    WEREWOLF_INACTIVE_THRESHOLD = timedelta(hours=1)

    def _filter(items):
        if not q_lower:
            return items
        return [item for item in items if q_lower in item.lower()]

    # Filter active poker tables
    active_poker = []
    for tid, table in runtime_state.poker_tables.items():
        # Be defensive: terminal tables should never appear in /active.
        if _is_terminal_poker_table(table):
            continue

        # Skip tables with no player actions for a long time.
        # TexasService should abort these, but this keeps /active strict.
        last_activity = _poker_last_activity_at(table, now)
        if now - last_activity > POKER_INACTIVE_THRESHOLD:
            continue

        # Skip empty tables that are old
        if not table.players:
            created_at = _as_utc(getattr(table, 'created_at', None)) or now
            if now - created_at > WAITING_STALE_THRESHOLD:
                continue
        active_poker.append(tid)
        
    poker_list = _filter(active_poker)
    
    # Filter active werewolf games
    active_werewolf = []
    for gid, game in runtime_state.werewolf_games.items():
        phase_val = _phase_to_str(getattr(game, "phase", None))
        # Be defensive: terminal games should never appear in /active.
        if phase_val in ("finished", "aborted"):
            continue

        is_game_over = getattr(game, "is_game_over", None)
        if callable(is_game_over) and is_game_over():
            continue
            
        # Check for staleness
        if phase_val == 'waiting':
            created_at = _as_utc(getattr(game, 'created_at', None)) or now
            # If waiting for > 1 hour, consider stale/hidden
            if now - created_at > WAITING_STALE_THRESHOLD:
                continue
        else:
            # Hide games that have no meaningful activity for a long time.
            last_activity = _werewolf_last_activity_at(game, now)
            if now - last_activity > WEREWOLF_INACTIVE_THRESHOLD:
                continue

            # Active phase: check phase start time
            phase_start = _as_utc(getattr(game, '_phase_start_time', None))
            if phase_start and (now - phase_start > STALE_THRESHOLD):
                # Phase stuck for > 30 mins
                continue
            
        active_werewolf.append(gid)
            
    werewolf_list = _filter(active_werewolf)

    return {
        "poker_tables": poker_list,
        "werewolf_games": werewolf_list,
        "total": {
            "poker": len(poker_list),
            "werewolf": len(werewolf_list)
        }
    }


@router.get("/api/games/active/debug/werewolf/{game_id}")
async def api_debug_active_werewolf(game_id: str):
    """Inspect active filtering inputs for a single werewolf game (debug only)."""
    if not is_local_debug_mode():
        raise HTTPException(status_code=403, detail="Debug endpoint is only available in LOCAL_DEBUG_MODE")

    game = runtime_state.werewolf_games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Werewolf game not found")

    now = datetime.now(timezone.utc)
    phase_val = _phase_to_str(getattr(game, "phase", None))
    created_at_raw = getattr(game, "created_at", None)
    started_at_raw = getattr(game, "started_at", None)
    phase_start_raw = getattr(game, "_phase_start_time", None)
    last_action_map = getattr(game, "last_action_time", None)

    last_activity = _werewolf_last_activity_at(game, now)
    phase_start = _as_utc(phase_start_raw)

    filters = {
        "phase_finished": phase_val in ("finished", "aborted"),
        "waiting_too_old": False,
        "inactive_too_old": False,
        "phase_stuck_too_long": False,
    }

    if phase_val == "waiting":
        created_at = _as_utc(created_at_raw) or now
        filters["waiting_too_old"] = (now - created_at) > timedelta(hours=1)
    else:
        filters["inactive_too_old"] = (now - last_activity) > timedelta(hours=1)
        if phase_start:
            filters["phase_stuck_too_long"] = (now - phase_start) > timedelta(minutes=30)

    return {
        "game_id": game_id,
        "phase": phase_val,
        "now_utc": now.isoformat(),
        "created_at_raw": str(created_at_raw) if created_at_raw is not None else None,
        "started_at_raw": str(started_at_raw) if started_at_raw is not None else None,
        "phase_start_raw": str(phase_start_raw) if phase_start_raw is not None else None,
        "created_at_utc": _format_dt(created_at_raw),
        "started_at_utc": _format_dt(started_at_raw),
        "phase_start_utc": phase_start.isoformat() if phase_start else None,
        "last_action_time_raw": last_action_map if isinstance(last_action_map, dict) else None,
        "last_activity_utc": last_activity.isoformat() if last_activity else None,
        "filters": filters,
        "would_be_hidden": any(filters.values()),
    }


import os

@router.get("/api/spectate/poker/{table_id}")
async def api_spectate_poker(request: Request, table_id: str, reveal: bool = False):
    if reveal:
        admin_token = request.headers.get("X-Admin-Token")
        expected_token = os.getenv("ADMIN_SECRET_TOKEN")
        if not expected_token or admin_token != expected_token:
            raise HTTPException(
                status_code=403,
                detail="Reveal mode requires admin authentication",
            )

    table = runtime_state.poker_tables.get(table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Poker table not found")

    if _is_terminal_poker_table(table):
        raise HTTPException(status_code=404, detail="Poker table has ended")

    return table.get_game_state(for_spectator=True, reveal_all=reveal)


@router.get("/api/spectate/werewolf/{game_id}")
async def api_spectate_werewolf(request: Request, game_id: str, reveal: bool = False):
    if reveal:
        admin_token = request.headers.get("X-Admin-Token")
        expected_token = os.getenv("ADMIN_SECRET_TOKEN")
        if not expected_token or admin_token != expected_token:
            raise HTTPException(
                status_code=403,
                detail="Reveal mode requires admin authentication",
            )

    # In local debug mode, always reveal for human spectators
    effective_reveal = reveal or is_local_debug_mode()

    game = runtime_state.werewolf_games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Werewolf game not found")

    return game.get_game_state(reveal_all=reveal)
