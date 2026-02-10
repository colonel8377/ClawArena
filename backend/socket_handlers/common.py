"""Common Socket.IO handlers and shared socket helpers."""

import asyncio
from datetime import datetime
from typing import Any, Dict, Iterable, Optional

from backend.games.werewolf.werewolf_game import WerewolfPhase
from backend.app.anti_bot_manager import (
    get_agent_instructions,
    verify_socket_auth,
)


POKER_SPECTATOR_ROOM_PREFIX = "spectate:poker:"
WEREWOLF_SPECTATOR_ROOM_PREFIX = "spectate:werewolf:"


def _poker_spectator_room(table_id: str) -> str:
    return f"{POKER_SPECTATOR_ROOM_PREFIX}{table_id}"


def _werewolf_spectator_room(game_id: str) -> str:
    return f"{WEREWOLF_SPECTATOR_ROOM_PREFIX}{game_id}"


def _mark_poker_disconnected(state, table_id: str, player_id: str,
                              seen_at: Optional[datetime] = None) -> None:
    if not table_id or not player_id:
        return
    table_map = state.poker_disconnected_since.setdefault(table_id, {})
    table_map[player_id] = seen_at or datetime.utcnow()


def _clear_poker_disconnected(state, table_id: str, player_id: str) -> None:
    table_map = state.poker_disconnected_since.get(table_id)
    if not table_map:
        return
    table_map.pop(player_id, None)
    if not table_map:
        state.poker_disconnected_since.pop(table_id, None)


def _forget_poker_disconnect_table(state, table_id: str) -> None:
    state.poker_disconnected_since.pop(table_id, None)


def _set_spectator_subscription(
    state,
    sid: str,
    game_type: str,
    room_id: str,
    reveal: bool,
) -> None:
    """Track spectator reveal preference per room."""
    sid_subs = state.spectator_subscriptions.setdefault(sid, {"poker": {}, "werewolf": {}})
    room_subs = sid_subs.setdefault(game_type, {})
    room_subs[room_id] = bool(reveal)


def _remove_spectator_subscription(
    state,
    sid: str,
    game_type: str,
    room_id: Optional[str] = None,
) -> None:
    """Remove one or all spectator subscriptions for a sid/game type."""
    sid_subs = state.spectator_subscriptions.get(sid)
    if not sid_subs:
        return

    if room_id:
        sid_subs.get(game_type, {}).pop(room_id, None)
    else:
        sid_subs[game_type] = {}

    if not sid_subs.get("poker") and not sid_subs.get("werewolf"):
        state.spectator_subscriptions.pop(sid, None)


def _is_read_only_session(state, sid: str) -> bool:
    session = state.player_sessions.get(sid) or {}
    return bool(session.get("read_only") or session.get("spectator_mode"))


async def _reject_if_read_only(sio, state, sid: str, action_name: str) -> bool:
    """Return True when action should be stopped due to read-only session."""
    if _is_read_only_session(state, sid):
        await sio.emit(
            "error",
            {
                "message": f"Read-only spectator session cannot perform '{action_name}'",
                "error_code": "SPECTATOR_READ_ONLY",
            },
            room=sid,
        )
        return True
    return False


def _iter_reveal_spectators(state, game_type: str, room_id: str) -> Iterable[str]:
    """Yield sids that subscribed with reveal=True for this room."""
    for sid, sid_subs in state.spectator_subscriptions.items():
        if sid_subs.get(game_type, {}).get(room_id) and _is_read_only_session(state, sid):
            yield sid


async def _emit_to_sids(sio, event: str, payload: Dict, sids: Iterable[str]) -> None:
    """Emit same payload to many sockets concurrently."""
    sids = list(sids)
    if not sids:
        return
    await asyncio.gather(
        *(sio.emit(event, payload, room=target_sid) for target_sid in sids),
        return_exceptions=True,
    )


async def _emit_poker_event(sio, table_id: str, event: str, payload: Dict) -> None:
    """Emit an event to poker players and spectator room."""
    await sio.emit(event, payload, room=table_id)
    await sio.emit(event, payload, room=_poker_spectator_room(table_id))


async def _emit_werewolf_event(sio, game_id: str, event: str, payload: Dict) -> None:
    """Emit an event to werewolf players and spectator room."""
    await sio.emit(event, payload, room=game_id)
    await sio.emit(event, payload, room=_werewolf_spectator_room(game_id))


def _is_night_phase(phase: str) -> bool:
    return phase.startswith("night_")


def _build_werewolf_action_trace(
    game,
    sid: str,
    action: str,
    result: Dict[str, Any],
    target_sid: Optional[str],
    message: Optional[str],
    reveal: bool,
) -> Dict[str, Any]:
    """Build spectator action trace payload with masked/reveal variants."""
    actor = next((p for p in game.players if p.get("sid") == sid), None)
    actor_nickname = actor.get("nickname", "Unknown") if actor else "Unknown"
    phase = game.phase.value
    target_player = (
        next((p for p in game.players if p.get("sid") == target_sid), None)
        if target_sid
        else None
    )
    target_nickname = target_player.get("nickname") if target_player else None

    payload: Dict[str, Any] = {
        "game_id": game.game_id,
        "phase": phase,
        "actor_sid": sid,
        "actor_nickname": actor_nickname,
        "action": action,
        "timestamp": datetime.utcnow().isoformat(),
    }

    hide_target = _is_night_phase(phase) and not reveal
    if action == "wolf_chat":
        payload["message"] = (message or "") if reveal else "[hidden wolf chat]"
        payload["visibility"] = "reveal_only" if reveal else "hidden"
    elif action in {"chat", "speak"}:
        payload["message"] = message or ""
        payload["visibility"] = "public"
    elif action in {"night_kill", "seer_check", "witch_poison", "hunter_shoot", "vote"}:
        if target_sid is None:
            payload["target"] = None
        elif hide_target:
            payload["target"] = {"sid": target_sid, "nickname": "Hidden Target"}
        else:
            payload["target"] = {
                "sid": target_sid,
                "nickname": target_nickname or "Unknown",
            }
    elif action == "witch_save":
        payload["target"] = None if hide_target else {
            "sid": game.pending_wolf_kill,
            "nickname": (
                next(
                    (
                        p.get("nickname")
                        for p in game.players
                        if p.get("sid") == game.pending_wolf_kill
                    ),
                    None,
                )
                or "Unknown"
            )
            if game.pending_wolf_kill
            else None,
        }

    if action == "seer_check" and reveal and result.get("result"):
        payload["seer_result"] = result.get("result")

    return payload


async def _emit_werewolf_action_trace(
    sio,
    state,
    game,
    sid: str,
    action: str,
    result: Dict[str, Any],
    target_sid: Optional[str],
    message: Optional[str],
) -> None:
    """Emit action timeline events to spectators (masked + reveal modes)."""
    game_id = game.game_id
    masked_payload = _build_werewolf_action_trace(
        game, sid, action, result, target_sid, message, reveal=False
    )
    await sio.emit(
        "werewolf_action_trace",
        masked_payload,
        room=_werewolf_spectator_room(game_id),
    )

    reveal_sids = list(_iter_reveal_spectators(state, "werewolf", game_id))
    if reveal_sids:
        reveal_payload = _build_werewolf_action_trace(
            game, sid, action, result, target_sid, message, reveal=True
        )
        await _emit_to_sids(sio, "werewolf_action_trace", reveal_payload, reveal_sids)


async def handle_reconnection(sio, state, sid: str, player_id: str) -> None:
    """
    Handle reconnection by checking if player was in an active game.

    If found, updates the player's sid and sends GAME_SNAPSHOT.
    """
    inactive_phases = {WerewolfPhase.FINISHED, WerewolfPhase.ABORTED}

    for game_id, game in state.werewolf_games.items():
        if game.phase in inactive_phases:
            continue

        for player in game.players:
            if player["wallet_address"] == player_id:
                old_sid = player["sid"]

                if old_sid != sid:
                    game.update_player_sid(old_sid, sid)
                    print(f"[Reconnect] Player {player_id} reconnected to game {game_id}")

                state.player_sessions[sid]["game_id"] = game_id
                await sio.enter_room(sid, game_id)
                snapshot = game.get_game_snapshot(sid)
                await sio.emit("GAME_SNAPSHOT", snapshot, room=sid)
                print(f"[Reconnect] Sent GAME_SNAPSHOT to {player_id} for game {game_id}")
                return

    for table_id, table in state.poker_tables.items():
        for player in table.players:
            if player.get("wallet_address", "") == player_id:
                old_sid = player.get("sid")

                if old_sid and old_sid != sid:
                    table.engine.update_player_sid(old_sid, sid)
                    player["sid"] = sid
                    asyncio.create_task(table.save_checkpoint("reconnect_rebind"))

                state.player_sessions[sid]["table_id"] = table_id
                _clear_poker_disconnected(state, table_id, player_id)
                await sio.enter_room(sid, table_id)
                await sio.emit("GAME_SNAPSHOT", table.get_game_snapshot(sid), room=sid)
                print(
                    f"[Reconnect] Sent GAME_SNAPSHOT to {player_id} for poker table {table_id}"
                )
                return


def register_common_handlers(sio, state) -> None:
    """Register common Socket.IO events (connect/auth/spectate)."""

    @sio.event
    async def connect(sid, environ, auth):
        """
        Handle client connection.

        AGENT-ONLY: Only AI agents can connect via Socket.IO.
        Humans should use HTTP API endpoints for spectating.
        """
        allowed, reason = await verify_socket_auth(environ, auth)
        if not allowed:
            print(f"Rejected socket connection: {sid} ({reason})")
            return False

        auth = auth or {}
        agent_id = auth.get("agent_id") or auth.get("agentId") or "anonymous"

        is_spectator_connection = reason == "spectator"
        role_label = "spectator" if is_spectator_connection else "agent"
        print(f"AI Client connected: {sid} (agent_id: {agent_id}, role: {role_label})")

        state.player_sessions[sid] = {
            "player_id": None,
            "player_name": None,
            "table_id": None,
            "game_id": None,
            "authenticated": False,
            "agent_id": agent_id,
            "read_only": is_spectator_connection,
            "spectator_mode": is_spectator_connection,
        }
        await sio.emit(
            "connected",
            {
                "sid": sid,
                "agent_id": agent_id,
                "read_only": is_spectator_connection,
                "message": "Welcome, AI Agent! You are connected to the arena.",
            },
            room=sid,
        )

    @sio.event
    async def disconnect(sid):
        """Handle client disconnection."""
        print(f"Client disconnected: {sid}")

        if sid in state.player_sessions:
            session = state.player_sessions[sid]

            if session["table_id"] and session["table_id"] in state.poker_tables:
                table_id = session["table_id"]
                table = state.poker_tables[table_id]
                player_id = session.get("player_id")
                if player_id:
                    _mark_poker_disconnected(state, table_id, player_id)
                if table.engine.phase.value in {"pre_flop", "flop", "turn", "river"}:
                    print(
                        f"[Disconnect] Preserving poker seat for reconnect: "
                        f"sid={sid}, table={session['table_id']}"
                    )
                    asyncio.create_task(table.save_state_to_redis())

            if state.werewolf_matchmaker:
                state.werewolf_matchmaker.remove_player(sid)
            if state.texas_matchmaker:
                state.texas_matchmaker.remove_player(sid)

            del state.player_sessions[sid]

        state.spectator_subscriptions.pop(sid, None)

    @sio.event
    async def authenticate(sid, data):
        """
        Authenticate a client using a login key.

        Expected data: {'login_key': str}
        """
        try:
            if await _reject_if_read_only(sio, state, sid, "authenticate"):
                return

            data = data or {}
            login_key = data.get("login_key")
            if not login_key or not str(login_key).strip():
                await sio.emit("error", {"message": "Missing login_key"}, room=sid)
                return

            login_key = str(login_key).strip()
            if len(login_key) > 128:
                await sio.emit("error", {"message": "Login key too long (max 128)"}, room=sid)
                return

            from backend.economy.account import handle_login

            login_result = await handle_login(login_key, grant_reward=False)
            user = login_result.get("user", {})
            player_id = user.get("player_id", "")
            player_name = user.get("player_name", "Player")

            if not player_id:
                await sio.emit("error", {"message": "Login succeeded but player_id missing"}, room=sid)
                return

            state.player_sessions[sid]["player_id"] = player_id
            state.player_sessions[sid]["player_name"] = player_name
            state.player_sessions[sid]["authenticated"] = True

            await sio.emit(
                "authenticated",
                {
                    "player_id": player_id,
                    "player_name": player_name,
                },
                room=sid,
            )

            await handle_reconnection(sio, state, sid, player_id)

        except Exception as exc:
            await sio.emit("error", {"message": f"Authentication failed: {str(exc)}"}, room=sid)

    @sio.event
    async def join_spectate(sid, data):
        """Join spectator room for poker or werewolf."""
        try:
            payload = data or {}
            reveal_requested = bool(payload.get("reveal", False))
            reveal_allowed = reveal_requested and _is_read_only_session(state, sid)
            table_id = payload.get("table_id")
            game_id = payload.get("game_id")
            joined_any = False

            if reveal_requested and not reveal_allowed:
                await sio.emit(
                    "error",
                    {
                        "message": "Reveal mode is only available to read-only spectator sessions",
                        "error_code": "SPECTATOR_REVEAL_FORBIDDEN",
                    },
                    room=sid,
                )

            if table_id and table_id in state.poker_tables:
                poker_room = _poker_spectator_room(table_id)
                if reveal_allowed:
                    await sio.leave_room(sid, poker_room)
                else:
                    await sio.enter_room(sid, poker_room)
                _set_spectator_subscription(state, sid, "poker", table_id, reveal_allowed)
                table = state.poker_tables[table_id]
                state_payload = table.get_game_state(for_spectator=True, reveal_all=reveal_allowed)
                await sio.emit("game_state", state_payload, room=sid)
                joined_any = True

            if game_id and game_id in state.werewolf_games:
                werewolf_room = _werewolf_spectator_room(game_id)
                if reveal_allowed:
                    await sio.leave_room(sid, werewolf_room)
                else:
                    await sio.enter_room(sid, werewolf_room)
                _set_spectator_subscription(state, sid, "werewolf", game_id, reveal_allowed)
                game = state.werewolf_games[game_id]
                state_payload = game.get_game_state(reveal_all=reveal_allowed)
                await sio.emit("werewolf_state", state_payload, room=sid)
                joined_any = True

            if not joined_any:
                await sio.emit("error", {"message": "No valid table_id/game_id to spectate"}, room=sid)

        except Exception as exc:
            await sio.emit("error", {"message": f"Join spectate failed: {str(exc)}"}, room=sid)

    @sio.event
    async def leave_spectate(sid, data):
        """Leave spectator room for poker or werewolf."""
        try:
            table_id = (data or {}).get("table_id")
            game_id = (data or {}).get("game_id")

            if table_id:
                await sio.leave_room(sid, _poker_spectator_room(table_id))
                _remove_spectator_subscription(state, sid, "poker", table_id)
            if game_id:
                await sio.leave_room(sid, _werewolf_spectator_room(game_id))
                _remove_spectator_subscription(state, sid, "werewolf", game_id)

        except Exception as exc:
            await sio.emit("error", {"message": f"Leave spectate failed: {str(exc)}"}, room=sid)
