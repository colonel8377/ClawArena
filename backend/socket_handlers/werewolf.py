"""Werewolf Socket.IO handlers."""

import asyncio
from decimal import Decimal

from backend.socket_handlers.common import _reject_if_read_only

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

            game_id = (data or {}).get("game_id")
            # This endpoint seems redundant with auto-advance and timeouts, 
            # but if it exists it should probably just trigger a phase check or similar.
            # For now, leaving it empty or logging as it wasn't fully implemented in the original file
            # based on the truncation. Assuming it might be a debug/admin tool.
            
            if not game_id or game_id not in state.werewolf_games:
                 await sio.emit("error", {"message": "Invalid game_id"}, room=sid)
                 return
            
            # Logic for manual advance would go here if needed, 
            # likely calling a method on werewolf_service.
            
        except Exception as exc:
             await sio.emit("error", {"message": f"Advance phase failed: {str(exc)}"}, room=sid)

    @sio.event
    async def get_werewolf_state(sid, data):
        try:
            game_id = (data or {}).get("game_id")
            if not game_id or game_id not in state.werewolf_games:
                await sio.emit("error", {"message": "Invalid game_id"}, room=sid)
                return

            game = state.werewolf_games[game_id]
            await sio.emit("werewolf_state", game.get_game_state(sid), room=sid)
        except Exception as exc:
            await sio.emit("error", {"message": f"Get werewolf state failed: {str(exc)}"}, room=sid)