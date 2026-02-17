"""Common Socket.IO service helpers and handlers."""

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, Optional


from backend.games.werewolf.werewolf_game import WerewolfPhase
from backend.constant.socket_error import emit_error
from backend.utils.socket_util import verify_socket_auth
from backend.views.socket.response import SocketResponse, emit_response
from backend.views.socket.common import JoinSpectateRequest, LeaveSpectateRequest

from backend.utils import log

POKER_SPECTATOR_ROOM_PREFIX = "spectate:poker:"
WEREWOLF_SPECTATOR_ROOM_PREFIX = "spectate:werewolf:"


def poker_spectator_room(table_id: str) -> str:
    return f"{POKER_SPECTATOR_ROOM_PREFIX}{table_id}"


def werewolf_spectator_room(game_id: str) -> str:
    return f"{WEREWOLF_SPECTATOR_ROOM_PREFIX}{game_id}"


def mark_poker_disconnected(state, table_id: str, player_id: str,
                             seen_at: Optional[datetime] = None) -> None:
    state.poker_disconnected_since.mark(table_id, player_id, seen_at)


def clear_poker_disconnected(state, table_id: str, player_id: str) -> None:
    state.poker_disconnected_since.clear(table_id, player_id)


def forget_poker_disconnect_table(state, table_id: str) -> None:
    state.poker_disconnected_since.clear_table(table_id)


def set_spectator_subscription(
    state,
    sid: str,
    game_type: str,
    room_id: str,
    reveal: bool,
) -> None:
    """Track spectator reveal preference per room."""
    sid_subs = state.spectator_subscriptions.get(sid)
    if game_type == "poker":
        room_subs = sid_subs.poker if sid_subs else {}
    elif game_type == "werewolf":
        room_subs = sid_subs.werewolf if sid_subs else {}
    else:
        return
    # Cap subscriptions per game type to prevent unbounded memory growth
    max_subs_per_type = 50
    if room_id not in room_subs and len(room_subs) >= max_subs_per_type:
        return
    state.spectator_subscriptions.subscribe(sid, game_type, room_id, bool(reveal))


def remove_spectator_subscription(
    state,
    sid: str,
    game_type: str,
    room_id: Optional[str] = None,
) -> None:
    """Remove one or all spectator subscriptions for a sid/game type."""
    state.spectator_subscriptions.unsubscribe(sid, game_type, room_id)


def is_read_only_session(state, sid: str) -> bool:
    return state.player_sessions.is_read_only(sid)


def verify_reveal_permission(state, sid: str, game_type: str, room_id: str) -> bool:
    """
    Verify if a socket session has permission to reveal hidden state.

    This should be strictly controlled. Currently relies on 'read_only' flag
    set during connection (which might come from admin auth).
    """
    session = state.player_sessions.get(sid)
    is_spectator = bool(session and session.is_read_only())

    # Audit log for security monitoring
    status = "Granted" if is_spectator else "Denied"
    agent_id = session.agent_id if session else "unknown"
    log.info(f"[RevealAccess] {status}: sid={sid}, game={game_type}:{room_id}, agent={agent_id}")

    return is_spectator


async def reject_if_read_only(sio, state, sid: str, action_name: str) -> bool:
    """Return True when action should be stopped due to read-only session."""
    if is_read_only_session(state, sid):
        await emit_error(
            sio,
            f"Read-only spectator session cannot perform '{action_name}'",
            room=sid,
            error_code="SPECTATOR_READ_ONLY",
        )
        return True
    return False


def iter_reveal_spectators(state, game_type: str, room_id: str) -> Iterable[str]:
    """Yield sids that subscribed with reveal=True for this room."""
    for sid, sid_subs in state.spectator_subscriptions.items():
        if sid_subs.is_reveal_enabled(game_type, room_id) and is_read_only_session(state, sid):
            yield sid


async def emit_to_sids(sio, event: str, payload: Dict, sids: Iterable[str]) -> None:
    """Emit same payload to many sockets concurrently."""
    sids = list(sids)
    if not sids:
        return
    await asyncio.gather(
        *(sio.emit(event, payload, room=target_sid) for target_sid in sids),
        return_exceptions=True,
    )


async def emit_poker_event(sio, table_id: str, event: str, payload: Dict) -> None:
    """Emit an event to poker players and spectator room."""
    await sio.emit(event, payload, room=table_id)
    await sio.emit(event, payload, room=poker_spectator_room(table_id))


async def emit_werewolf_event(sio, game_id: str, event: str, payload: Dict) -> None:
    """Emit an event to werewolf players and spectator room."""
    await sio.emit(event, payload, room=game_id)
    await sio.emit(event, payload, room=werewolf_spectator_room(game_id))


def is_night_phase(phase: str) -> bool:
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
        "timestamp": datetime.now(timezone.utc).isoformat(),
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


async def emit_werewolf_action_trace(
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
        room=werewolf_spectator_room(game_id),
    )

    reveal_sids = list(iter_reveal_spectators(state, "werewolf", game_id))
    if reveal_sids:
        reveal_payload = _build_werewolf_action_trace(
            game, sid, action, result, target_sid, message, reveal=True
        )
        await emit_to_sids(sio, "werewolf_action_trace", reveal_payload, reveal_sids)


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
                    log.info(f"[Reconnect] Player {player_id} reconnected to game {game_id}")

                state.player_sessions.set_game_id(sid, game_id)
                await sio.enter_room(sid, game_id)
                snapshot = game.get_game_snapshot(sid)
                await sio.emit("GAME_SNAPSHOT", snapshot, room=sid)
                log.info(f"[Reconnect] Sent GAME_SNAPSHOT to {player_id} for game {game_id}")
                return

    for table_id, table in state.poker_tables.items():
        for player in table.players:
            if player.get("player_id", "") == player_id:
                old_sid = player.get("sid")

                if old_sid and old_sid != sid:
                    table.engine.update_player_sid(old_sid, sid)
                    player["sid"] = sid
                    asyncio.create_task(table.save_checkpoint("reconnect_rebind"))

                state.player_sessions.set_table_id(sid, table_id)
                clear_poker_disconnected(state, table_id, player_id)
                await sio.enter_room(sid, table_id)
                await sio.emit("GAME_SNAPSHOT", table.get_game_snapshot(sid), room=sid)
                log.info(
                    f"[Reconnect] Sent GAME_SNAPSHOT to {player_id} for poker table {table_id}"
                )
                return


class CommonSocketService:
    def __init__(self, sio, state) -> None:
        self._sio = sio
        self._state = state

    async def connect(self, sid, environ, auth):
        allowed, reason, payload = await verify_socket_auth(environ, auth)
        if not allowed:
            log.info(f"Rejected socket connection: {sid} ({reason})")
            return False

        is_spectator_connection = reason == "spectator"
        player_id = payload.get("player_id") if payload else None
        role_label = "spectator" if is_spectator_connection else "agent"
        log.info(f"Client connected: {sid} (player_id: {player_id}, role: {role_label})")

        self._state.player_sessions.create(
            sid,
            player_id=player_id,
            player_name=None,
            table_id=None,
            game_id=None,
            authenticated=bool(player_id) and not is_spectator_connection,
            read_only=is_spectator_connection,
            spectator_mode=is_spectator_connection,
        )
        response = SocketResponse(
            "connected",
            {
                "sid": sid,
                "player_id": player_id,
                "read_only": is_spectator_connection,
                "message": "Welcome, AI Agent! You are connected to the arena.",
            },
        )
        await emit_response(self._sio, response, room=sid)
        return True

    async def disconnect(self, sid: str) -> bool:
        log.info(f"Client disconnected: {sid}")
        player_id = None

        if sid in self._state.player_sessions:
            session = self._state.player_sessions.get(sid)
            if not session:
                return True

            if session.table_id and session.table_id in self._state.poker_tables:
                table_id = session.table_id
                table = self._state.poker_tables[table_id]
                player_id = session.player_id
                if player_id:
                    mark_poker_disconnected(self._state, table_id, player_id)
                if table.engine.phase.value in {"pre_flop", "flop", "turn", "river"}:
                    log.info(
                        "[Disconnect] Preserving poker seat for reconnect: "
                        f"sid={sid}, table={session.table_id}"
                    )
                    asyncio.create_task(table.save_state_to_redis())

            if self._state.werewolf_matchmaker:
                await self._state.werewolf_matchmaker.remove_player(sid)
            if self._state.texas_matchmaker:
                await self._state.texas_matchmaker.remove_player(sid)

            self._state.player_sessions.remove(sid)

        self._state.spectator_subscriptions.clear_sid(sid)
        response = SocketResponse(
            "connected",
            {
                "sid": sid,
                "player_id": player_id,
                "message": "Bye",
            },
        )
        await emit_response(self._sio, response, room=sid)
        return True

    async def _set_spectate_room_membership(self, sid: str, room: str, reveal_allowed: bool) -> None:
        if reveal_allowed:
            await self._sio.leave_room(sid, room)
        else:
            await self._sio.enter_room(sid, room)

    async def _join_poker_spectate(self, sid: str, table_id: Optional[str], reveal_allowed: bool) -> bool:
        if not table_id:
            return False
        table = self._state.poker_tables.get(table_id)
        if not table:
            return False

        await self._set_spectate_room_membership(sid, poker_spectator_room(table_id), reveal_allowed)
        set_spectator_subscription(self._state, sid, "poker", table_id, reveal_allowed)
        await self._sio.emit(
            "game_state",
            table.get_game_state(for_spectator=True, reveal_all=reveal_allowed),
            room=sid,
        )
        return True

    async def _join_werewolf_spectate(self, sid: str, game_id: Optional[str], reveal_allowed: bool) -> bool:
        if not game_id:
            return False
        game = self._state.werewolf_games.get(game_id)
        if not game:
            return False

        await self._set_spectate_room_membership(sid, werewolf_spectator_room(game_id), reveal_allowed)
        set_spectator_subscription(self._state, sid, "werewolf", game_id, reveal_allowed)
        await self._sio.emit(
            "werewolf_state",
            game.get_game_state(reveal_all=reveal_allowed),
            room=sid,
        )
        return True

    async def join_spectate(self, sid: str, payload: JoinSpectateRequest) -> None:
        reveal_requested = bool(payload.reveal)
        reveal_allowed = reveal_requested and is_read_only_session(self._state, sid)

        if reveal_requested and not reveal_allowed:
            await emit_error(
                self._sio,
                "Reveal mode is only available to read-only spectator sessions",
                room=sid,
                error_code="SPECTATOR_REVEAL_FORBIDDEN",
            )

        joined_poker = await self._join_poker_spectate(sid, payload.table_id, reveal_allowed)
        joined_werewolf = await self._join_werewolf_spectate(sid, payload.game_id, reveal_allowed)
        if not joined_poker and not joined_werewolf:
            await emit_error(self._sio, "No valid table_id/game_id to spectate", room=sid)

    async def leave_spectate(self, sid: str, payload: LeaveSpectateRequest) -> None:
        table_id = payload.table_id
        game_id = payload.game_id

        if table_id:
            await self._sio.leave_room(sid, poker_spectator_room(table_id))
            remove_spectator_subscription(self._state, sid, "poker", table_id)
        if game_id:
            await self._sio.leave_room(sid, werewolf_spectator_room(game_id))
            remove_spectator_subscription(self._state, sid, "werewolf", game_id)
