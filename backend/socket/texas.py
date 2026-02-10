"""Texas Hold'em Socket.IO handlers and helpers."""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal

from config import TEXAS_CHIP_TO_TOKEN_RATIO
from database.models import TransactionType
from database.persistence_manager import persistence_manager
from economy.account import add_balance, deduct_balance, unlock_balance
from games.texas.texas_engine import PokerPhase
from socket.common import (
    _clear_poker_disconnected,
    _emit_poker_event,
    _emit_to_sids,
    _forget_poker_disconnect_table,
    _iter_reveal_spectators,
    _poker_spectator_room,
    _reject_if_read_only,
)


POKER_ACTIVE_PHASES = {
    PokerPhase.PRE_FLOP,
    PokerPhase.FLOP,
    PokerPhase.TURN,
    PokerPhase.RIVER,
}

POKER_DISCONNECT_AUTO_LEAVE_SECONDS = 120


async def broadcast_game_state(sio, state, table_id: str):
    """Broadcast poker state with masked + private payloads."""
    table = state.poker_tables.get(table_id)
    if not table:
        return

    engine = table.engine
    is_showdown = engine.phase.value == "showdown"

    public_players = []
    for player_sid in engine.player_order:
        player = engine.players.get(player_sid)
        if not player:
            continue
        public_players.append(
            {
                "sid": player_sid,
                "wallet_address": player.wallet_address,
                "nickname": player.nickname,
                "chips": player.chips,
                "current_bet": player.current_bet,
                "status": player.status.value,
                "last_action": player.last_action,
                "hole_cards": engine.cards_to_strings(player.hole_cards)
                if is_showdown
                else ["??", "??"],
            }
        )

    current_player = None
    if engine.current_player_sid and engine.current_player_sid in engine.players:
        if engine.players[engine.current_player_sid].can_act():
            current_player = engine.current_player_sid

    public_state = {
        "game_id": table_id,
        "phase": engine.phase.value,
        "hand_number": engine.hand_number,
        "community_cards": engine.cards_to_strings(engine.community_cards),
        "pot": engine.get_total_pot(),
        "current_bet": engine.current_bet,
        "min_raise": engine.current_bet + engine.last_raise_amount,
        "current_player": current_player,
        "players": public_players,
        "chat_history": [
            {
                "nickname": msg.player_nickname,
                "message": msg.message,
                "action": msg.action,
                "timestamp": msg.timestamp,
            }
            for msg in engine.chat_history[-20:]
        ],
        "timestamp": datetime.utcnow().isoformat(),
    }

    await sio.emit("game_update", public_state, room=table_id)
    await sio.emit("game_update", public_state, room=_poker_spectator_room(table_id))

    reveal_sids = list(_iter_reveal_spectators(state, "poker", table_id))
    if reveal_sids:
        reveal_state = table.get_game_state(for_spectator=True, reveal_all=True)
        await _emit_to_sids(sio, "game_update", reveal_state, reveal_sids)

    if not is_showdown:
        for player_dict in table.players:
            player_sid = player_dict["sid"]
            player = engine.players.get(player_sid)
            if player and player.hole_cards:
                await sio.emit(
                    "private_hand",
                    {
                        "game_id": table_id,
                        "hole_cards": engine.cards_to_strings(player.hole_cards),
                        "your_turn": player_sid == current_player,
                        "timestamp": datetime.utcnow().isoformat(),
                    },
                    room=player_sid,
                )

    asyncio.create_task(table.save_state_to_redis())


async def check_disconnected_texas_players(state, sio, table_id: str, table) -> None:
    """Auto-settle disconnected poker players after a grace period."""
    disconnected_map = state.poker_disconnected_since.get(table_id)
    if not disconnected_map:
        return

    now = datetime.utcnow()
    to_remove = []
    for player_id, disconnected_at in list(disconnected_map.items()):
        player_dict = next(
            (p for p in table.players if p.get("wallet_address") == player_id),
            None,
        )
        if not player_dict:
            _clear_poker_disconnected(state, table_id, player_id)
            continue

        player_sid = player_dict.get("sid")
        if player_sid in state.player_sessions:
            _clear_poker_disconnected(state, table_id, player_id)
            continue

        if now - disconnected_at >= timedelta(seconds=POKER_DISCONNECT_AUTO_LEAVE_SECONDS):
            to_remove.append((player_sid, player_dict))

    for player_sid, player_dict in to_remove:
        if table.engine.phase in POKER_ACTIVE_PHASES:
            continue

        engine_player = table.engine.players.get(player_sid)
        table.remove_player(player_sid)

        wallet_address = player_dict.get("wallet_address")
        buy_in_tokens = Decimal(str(player_dict.get("buy_in_tokens", 0) or 0))
        chips_tokens = (
            Decimal(str(engine_player.chips * TEXAS_CHIP_TO_TOKEN_RATIO))
            if engine_player
            else Decimal("0")
        )

        if wallet_address and buy_in_tokens > 0:
            await unlock_balance(
                wallet_address,
                buy_in_tokens,
                game_session_id=table_id,
                description="Texas Hold'em buy-in principal unlock (disconnect)",
            )

        pnl_delta = chips_tokens - buy_in_tokens
        if wallet_address and pnl_delta > 0:
            await add_balance(
                wallet_address,
                pnl_delta,
                tx_type=TransactionType.GAME_WIN,
                description="Texas Hold'em settlement profit (disconnect)",
            )
        elif wallet_address and pnl_delta < 0:
            await deduct_balance(
                wallet_address,
                -pnl_delta,
                tx_type=TransactionType.GAME_ENTRY,
                description="Texas Hold'em settlement loss (disconnect)",
            )

        _clear_poker_disconnected(state, table_id, wallet_address or "")
        await sio.leave_room(player_sid, table_id)
        await broadcast_game_state(sio, state, table_id)

    if not table.players:
        state.poker_tables.pop(table_id, None)
        _forget_poker_disconnect_table(state, table_id)


def register_texas_handlers(sio, state) -> None:
    """Register Texas Socket.IO event handlers."""

    @sio.event
    async def start_hand(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "start_hand"):
                return

            table_id = (data or {}).get("table_id")
            if not table_id or table_id not in state.poker_tables:
                await sio.emit("error", {"message": "Invalid table_id"}, room=sid)
                return

            table = state.poker_tables[table_id]
            if not table.start_game():
                await sio.emit("error", {"message": "Not enough players to start"}, room=sid)
                return

            asyncio.create_task(table.save_checkpoint("hand_start"))
            await broadcast_game_state(sio, state, table_id)
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

            if not table_id or table_id not in state.poker_tables:
                await sio.emit("error", {"message": "Invalid table_id"}, room=sid)
                return
            if not action:
                await sio.emit("error", {"message": "Action required"}, room=sid)
                return

            table = state.poker_tables[table_id]
            action_kwargs = {}
            if action == "raise":
                action_kwargs["amount"] = amount
            if chat_message:
                action_kwargs["message"] = chat_message

            result = table.process_action(sid, action, **action_kwargs)
            if not result.get("success"):
                await sio.emit(
                    "error",
                    {"message": result.get("error", "Action failed")},
                    room=sid,
                )
                return

            if result.get("chat_blocked"):
                await sio.emit(
                    "error",
                    {
                        "message": "Chat is not allowed during active hand",
                        "error_code": "CHAT_PHASE_RESTRICTED",
                    },
                    room=sid,
                )

            if chat_message and not result.get("chat_blocked"):
                player = next((p for p in table.players if p.get("sid") == sid), None)
                if player:
                    message_type = "chat" if action == "chat" else "action"
                    metadata = {"action": action} if action != "chat" else None
                    asyncio.create_task(
                        persistence_manager.save_chat_message(
                            game_id=table_id,
                            game_type=table.game_type,
                            player_id=player.get("wallet_address", ""),
                            nickname=player.get("nickname", "Player"),
                            message=chat_message,
                            message_type=message_type,
                            metadata=metadata,
                        )
                    )

            await broadcast_game_state(sio, state, table_id)

            if result.get("hand_over"):
                winner_info = result.get("winner", {})
                await _emit_poker_event(
                    sio,
                    table_id,
                    "hand_winner",
                    {
                        "winner": winner_info,
                        "reason": "All other players folded",
                        "pot": winner_info.get("amount", 0),
                    },
                )
                asyncio.create_task(table.save_checkpoint("hand_end"))
                return

            if result.get("advance_phase"):
                phase_result = table.engine.advance_phase()
                await broadcast_game_state(sio, state, table_id)
                asyncio.create_task(table.save_checkpoint("phase_change"))

                if table.engine.phase.value == "showdown":
                    showdown_result = phase_result if isinstance(phase_result, dict) else {}
                    await _emit_poker_event(
                        sio,
                        table_id,
                        "showdown_reveal",
                        {
                            "player_hands": showdown_result.get(
                                "player_hands", table.engine.get_all_hole_cards()
                            ),
                            "community_cards": table.engine.cards_to_strings(
                                table.engine.community_cards
                            ),
                            "winners": showdown_result.get("winners", []),
                        },
                    )
                    asyncio.create_task(table.save_checkpoint("showdown"))

            asyncio.create_task(table.save_checkpoint("action"))
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
            if not table_id or table_id not in state.poker_tables:
                await sio.emit("error", {"message": "Invalid table_id"}, room=sid)
                return

            table = state.poker_tables[table_id]
            if table.engine.phase in POKER_ACTIVE_PHASES:
                await sio.emit(
                    "error",
                    {
                        "message": "Cannot leave during active hand. Fold or wait for the hand to finish."
                    },
                    room=sid,
                )
                return

            player_dict = next((p for p in table.players if p.get("sid") == sid), None)
            engine_player = table.engine.players.get(sid)

            table.remove_player(sid)
            if sid in table.engine.players:
                await sio.emit(
                    "error",
                    {"message": "Leave request deferred until the current hand completes."},
                    room=sid,
                )
                return

            await sio.leave_room(sid, table_id)

            if sid in state.player_sessions:
                state.player_sessions[sid]["table_id"] = None
            if player_dict:
                _clear_poker_disconnected(
                    state,
                    table_id,
                    player_dict.get("wallet_address", ""),
                )

            if player_dict and engine_player:
                wallet_address = player_dict["wallet_address"]
                buy_in_tokens = Decimal(str(player_dict.get("buy_in_tokens", 0) or 0))
                chips_tokens = Decimal(str(engine_player.chips * TEXAS_CHIP_TO_TOKEN_RATIO))

                if buy_in_tokens > 0:
                    await unlock_balance(
                        wallet_address,
                        buy_in_tokens,
                        game_session_id=table_id,
                        description="Texas Hold'em buy-in principal unlock",
                    )

                pnl_delta = chips_tokens - buy_in_tokens
                if pnl_delta > 0:
                    await add_balance(
                        wallet_address,
                        pnl_delta,
                        tx_type=TransactionType.GAME_WIN,
                        description="Texas Hold'em settlement profit",
                    )
                elif pnl_delta < 0:
                    await deduct_balance(
                        wallet_address,
                        -pnl_delta,
                        tx_type=TransactionType.GAME_ENTRY,
                        description="Texas Hold'em settlement loss",
                    )

            await sio.emit("left_game", {"table_id": table_id}, room=sid)
            await broadcast_game_state(sio, state, table_id)
        except Exception as exc:
            await sio.emit("error", {"message": f"Leave game failed: {str(exc)}"}, room=sid)
