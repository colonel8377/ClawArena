"""Texas Hold'em Socket.IO handlers."""

import asyncio

from backend.socket_handlers.common import _reject_if_read_only

def register_texas_handlers(sio, state, texas_service) -> None:
    """Register Texas Socket.IO event handlers."""

    @sio.event
    async def start_hand(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "start_hand"):
                return

            table_id = (data or {}).get("table_id")
            await texas_service.start_hand(table_id, sid)
        except Exception as exc:
            await sio.emit("error", {"message": f"Start hand failed: {str(exc)}"}, room=sid)

    @sio.event
    async def player_move(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "player_move"):
                return

            data = data or {}
            table_id = data.get("table_id")
            action = data.get("action")
            amount = data.get("amount", 0)
            chat_message = data.get("message")

            await texas_service.player_move(table_id, sid, action, amount, chat_message)
        except Exception as exc:
            await sio.emit("error", {"message": f"Player move failed: {str(exc)}"}, room=sid)

    @sio.event
    async def get_state(sid, data):
        try:
            table_id = (data or {}).get("table_id")
            if not table_id or table_id not in state.poker_tables:
                await sio.emit("error", {"message": "Invalid table_id"}, room=sid)
                return

            table = state.poker_tables[table_id]
            await sio.emit("game_state", table.get_game_state(sid), room=sid)
        except Exception as exc:
            await sio.emit("error", {"message": f"Get state failed: {str(exc)}"}, room=sid)

    @sio.event
    async def leave_game(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "leave_game"):
                return

            table_id = (data or {}).get("table_id")
            await texas_service.leave_game(table_id, sid)
        except Exception as exc:
            await sio.emit("error", {"message": f"Leave game failed: {str(exc)}"}, room=sid)

