"""Werewolf Socket.IO handlers."""

import asyncio
from decimal import Decimal

from backend.config.arena_config import is_local_debug_mode
from backend.socket_handlers.common import _is_read_only_session, _reject_if_read_only

def register_werewolf_handlers(sio, state, werewolf_service) -> None:
    """Register Werewolf Socket.IO event handlers."""

    @sio.event
    async def create_werewolf_game(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "create_werewolf_game"):
                return

            payload = data or {}
            game_id = payload.get("game_id")
            entry_fee = Decimal(str(payload.get("entry_fee", 0)))
            
            await werewolf_service.create_game(sid, game_id, entry_fee)
        except Exception as exc:
            await sio.emit("error", {"message": f"Create game failed: {str(exc)}"}, room=sid)

    @sio.event
    async def join_werewolf_game(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "join_werewolf_game"):
                return

            payload = data or {}
            game_id = payload.get("game_id")
            
            await werewolf_service.join_game(sid, game_id)
        except Exception as exc:
            await sio.emit("error", {"message": f"Join werewolf game failed: {str(exc)}"}, room=sid)

    @sio.event
    async def start_werewolf_game(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "start_werewolf_game"):
                return

            game_id = (data or {}).get("game_id")
            await werewolf_service.start_game(sid, game_id)
        except Exception as exc:
            await sio.emit("error", {"message": f"Start werewolf game failed: {str(exc)}"}, room=sid)

    @sio.event
    async def werewolf_action(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "werewolf_action"):
                return

            payload = data or {}
            game_id = payload.get("game_id")
            action = payload.get("action")
            target_sid = payload.get("target_sid")
            message = payload.get("message")
            
            await werewolf_service.process_action(sid, game_id, action, target_sid, message)

        except Exception as exc:
            import traceback
            traceback.print_exc()
            await sio.emit("error", {"message": f"Werewolf action failed: {str(exc)}"}, room=sid)

    @sio.event
    async def advance_werewolf_phase(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "advance_werewolf_phase"):
                return

            if not is_local_debug_mode():
                await sio.emit(
                    "error",
                    {
                        "message": "advance_werewolf_phase is disabled outside LOCAL_DEBUG_MODE",
                        "error_code": "DEBUG_ONLY",
                    },
                    room=sid,
                )
                return

            game_id = (data or {}).get("game_id")
            
            if not game_id or game_id not in state.werewolf_games:
                 await sio.emit("error", {"message": "Invalid game_id"}, room=sid)
                 return
            
            await werewolf_service.advance_phase(sid, game_id)
            
        except Exception as exc:
             await sio.emit("error", {"message": f"Advance phase failed: {str(exc)}"}, room=sid)

    @sio.event
    async def get_werewolf_state(sid, data):
        try:
            payload = data or {}
            game_id = payload.get("game_id")
            if not game_id or game_id not in state.werewolf_games:
                await sio.emit("error", {"message": "Invalid game_id"}, room=sid)
                return

            game = state.werewolf_games[game_id]
            reveal_requested = bool(payload.get("reveal", False))
            # Only read-only spectator sessions may use reveal mode.
            # Agent players (non-read-only) are denied to prevent cheating.
            reveal = reveal_requested and _is_read_only_session(state, sid)
            if reveal_requested and not reveal:
                await sio.emit(
                    "error",
                    {
                        "message": "Reveal mode is only available to spectator sessions",
                        "error_code": "REVEAL_FORBIDDEN",
                    },
                    room=sid,
                )
                return
            await sio.emit("werewolf_state", game.get_game_state(sid, reveal_all=reveal), room=sid)
        except Exception as exc:
            await sio.emit("error", {"message": f"Get werewolf state failed: {str(exc)}"}, room=sid)
