"""Texas orchestration service."""

import asyncio
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Optional, Dict, Any

from ..config.arena_config import TEXAS_CHIP_TO_TOKEN_RATIO
from ..database.models import TransactionType
from ..database.persistence_manager import persistence_manager
from ..economy.account import add_balance, deduct_balance, unlock_balance
from ..games.texas.texas_engine import PokerPhase
from ..services.base import BaseService
from ..services.settlement_service import SettlementService

POKER_ACTIVE_PHASES = {
    PokerPhase.PRE_FLOP,
    PokerPhase.FLOP,
    PokerPhase.TURN,
    PokerPhase.RIVER,
}

POKER_DISCONNECT_AUTO_LEAVE_SECONDS = 120


class TexasService(BaseService):
    """Coordinates poker background orchestration and game logic."""

    POKER_SPECTATOR_ROOM_PREFIX = "spectate:poker:"

    def __init__(self, state, sio, settlement_service: SettlementService, timeout_interval: int = 1) -> None:
        self._state = state
        self._sio = sio
        self._settlement_service = settlement_service
        self._timeout_interval = timeout_interval

    async def start(self) -> None:
        if self._state.poker_timeout_task and not self._state.poker_timeout_task.done():
            return
        self._state.poker_timeout_task = asyncio.create_task(self._timeout_loop())

    async def stop(self) -> None:
        if self._state.poker_timeout_task and not self._state.poker_timeout_task.done():
            self._state.poker_timeout_task.cancel()
            await asyncio.gather(self._state.poker_timeout_task, return_exceptions=True)

    def _poker_spectator_room(self, table_id: str) -> str:
        return f"{self.POKER_SPECTATOR_ROOM_PREFIX}{table_id}"

    async def broadcast_state(self, table_id: str) -> None:
        """Broadcast poker state with masked + private payloads."""
        table = self._state.poker_tables.get(table_id)
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

        await self._sio.emit("game_update", public_state, room=table_id)
        await self._sio.emit("game_update", public_state, room=self._poker_spectator_room(table_id))

        # Handle reveal spectators
        # Using a helper method or accessing state directly
        reveal_sids = []
        for sid, sid_subs in self._state.spectator_subscriptions.items():
            if sid_subs.get("poker", {}).get(table_id):
                 # Check read only session
                 session = self._state.player_sessions.get(sid) or {}
                 if bool(session.get("read_only") or session.get("spectator_mode")):
                     reveal_sids.append(sid)

        if reveal_sids:
            reveal_state = table.get_game_state(for_spectator=True, reveal_all=True)
            for target_sid in reveal_sids:
                await self._sio.emit("game_update", reveal_state, room=target_sid)

        if not is_showdown:
            for player_dict in table.players:
                player_sid = player_dict["sid"]
                player = engine.players.get(player_sid)
                if player and player.hole_cards:
                    await self._sio.emit(
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

    async def start_hand(self, table_id: str, sid: str) -> None:
        if not table_id or table_id not in self._state.poker_tables:
            await self._sio.emit("error", {"message": "Invalid table_id"}, room=sid)
            return

        table = self._state.poker_tables[table_id]
        if not table.start_game():
            await self._sio.emit("error", {"message": "Not enough players to start"}, room=sid)
            return

        asyncio.create_task(table.save_checkpoint("hand_start"))
        await self.broadcast_state(table_id)

    async def player_move(self, table_id: str, sid: str, action: str, amount: float = 0, chat_message: Optional[str] = None) -> None:
        if not table_id or table_id not in self._state.poker_tables:
            await self._sio.emit("error", {"message": "Invalid table_id"}, room=sid)
            return
        if not action:
            await self._sio.emit("error", {"message": "Action required"}, room=sid)
            return

        table = self._state.poker_tables[table_id]
        action_kwargs = {}
        if action == "raise":
            action_kwargs["amount"] = amount
        if chat_message:
            action_kwargs["message"] = chat_message

        result = table.process_action(sid, action, **action_kwargs)
        if not result.get("success"):
            await self._sio.emit(
                "error",
                {"message": result.get("error", "Action failed")},
                room=sid,
            )
            return

        if result.get("chat_blocked"):
            await self._sio.emit(
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

        await self.broadcast_state(table_id)

        if result.get("hand_over"):
            winner_info = result.get("winner", {})
            payload = {
                "winner": winner_info,
                "reason": "All other players folded",
                "pot": winner_info.get("amount", 0),
            }
            await self._sio.emit("hand_winner", payload, room=table_id)
            await self._sio.emit("hand_winner", payload, room=self._poker_spectator_room(table_id))
            
            asyncio.create_task(table.save_checkpoint("hand_end"))
            return

        if result.get("advance_phase"):
            phase_result = table.engine.advance_phase()
            await self.broadcast_state(table_id)
            asyncio.create_task(table.save_checkpoint("phase_change"))

            if table.engine.phase.value == "showdown":
                showdown_result = phase_result if isinstance(phase_result, dict) else {}
                payload = {
                    "player_hands": showdown_result.get(
                        "player_hands", table.engine.get_all_hole_cards()
                    ),
                    "community_cards": table.engine.cards_to_strings(
                        table.engine.community_cards
                    ),
                    "winners": showdown_result.get("winners", []),
                }
                await self._sio.emit("showdown_reveal", payload, room=table_id)
                await self._sio.emit("showdown_reveal", payload, room=self._poker_spectator_room(table_id))
                asyncio.create_task(table.save_checkpoint("showdown"))

        asyncio.create_task(table.save_checkpoint("action"))

    async def leave_game(self, table_id: str, sid: str) -> None:
        if not table_id or table_id not in self._state.poker_tables:
            await self._sio.emit("error", {"message": "Invalid table_id"}, room=sid)
            return

        table = self._state.poker_tables[table_id]
        if table.engine.phase in POKER_ACTIVE_PHASES:
            await self._sio.emit(
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
            await self._sio.emit(
                "error",
                {"message": "Leave request deferred until the current hand completes."},
                room=sid,
            )
            return

        await self._sio.leave_room(sid, table_id)

        if sid in self._state.player_sessions:
            self._state.player_sessions[sid]["table_id"] = None
        
        if player_dict:
             # Clean up disconnected tracking if exists
            table_map = self._state.poker_disconnected_since.get(table_id)
            if table_map:
                table_map.pop(player_dict.get("wallet_address", ""), None)
                if not table_map:
                    self._state.poker_disconnected_since.pop(table_id, None)

        if player_dict and engine_player:
            wallet_address = player_dict["wallet_address"]
            buy_in_tokens = Decimal(str(player_dict.get("buy_in_tokens", 0) or 0))
            chips_tokens = Decimal(str(engine_player.chips * TEXAS_CHIP_TO_TOKEN_RATIO))

            await self._settlement_service.settle_texas_player(
                wallet_address,
                buy_in_tokens,
                chips_tokens,
                table_id,
                principal_description="Texas Hold'em buy-in principal unlock",
                win_description="Texas Hold'em settlement profit",
                loss_description="Texas Hold'em settlement loss",
            )

        await self._sio.emit("left_game", {"table_id": table_id}, room=sid)
        await self.broadcast_state(table_id)

    async def _check_disconnected_players(self, table_id: str, table) -> None:
        """Auto-settle disconnected poker players after a grace period."""
        disconnected_map = self._state.poker_disconnected_since.get(table_id)
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
                # _clear_poker_disconnected
                table_map = self._state.poker_disconnected_since.get(table_id)
                if table_map:
                    table_map.pop(player_id, None)
                    if not table_map:
                        self._state.poker_disconnected_since.pop(table_id, None)
                continue

            player_sid = player_dict.get("sid")
            if player_sid in self._state.player_sessions:
                # Reconnected
                table_map = self._state.poker_disconnected_since.get(table_id)
                if table_map:
                    table_map.pop(player_id, None)
                    if not table_map:
                        self._state.poker_disconnected_since.pop(table_id, None)
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

            await self._settlement_service.settle_texas_player(
                wallet_address,
                buy_in_tokens,
                chips_tokens,
                table_id,
                principal_description="Texas Hold'em buy-in principal unlock (disconnect)",
                win_description="Texas Hold'em settlement profit (disconnect)",
                loss_description="Texas Hold'em settlement loss (disconnect)",
            )

            # Clear disconnected
            table_map = self._state.poker_disconnected_since.get(table_id)
            if table_map:
                table_map.pop(wallet_address or "", None)
                if not table_map:
                    self._state.poker_disconnected_since.pop(table_id, None)

            await self._sio.leave_room(player_sid, table_id)
            await self.broadcast_state(table_id)

        if not table.players:
            self._state.poker_tables.pop(table_id, None)
            self._state.poker_disconnected_since.pop(table_id, None)

    async def _timeout_loop(self) -> None:
        """Auto-resolve poker turns when action timers expire."""
        while True:
            try:
                await asyncio.sleep(self._timeout_interval)

                for table_id, table in list(self._state.poker_tables.items()):
                    await self._check_disconnected_players(table_id, table)
                    engine = table.engine
                    if engine.phase not in POKER_ACTIVE_PHASES:
                        continue

                    current_sid = engine.current_player_sid
                    if not current_sid:
                        continue

                    if engine.get_turn_time_remaining() > 0:
                        continue

                    print(f"[PokerTimeout] Table {table_id} player {current_sid} timed out")
                    result = engine.handle_timeout(current_sid)

                    if not result.get("success"):
                        print(
                            f"[PokerTimeout] Failed to auto-act on {table_id}: {result.get('error')}"
                        )
                        continue

                    table.update_player_action_time(current_sid)

                    await self._sio.emit(
                        "PLAYER_TIMEOUT",
                        {
                            "table_id": table_id,
                            "player_sid": current_sid,
                            "action": result.get("action", "fold"),
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                        room=table_id,
                    )

                    asyncio.create_task(table.save_checkpoint("timeout_action"))
                    await self.broadcast_state(table_id)

                    if result.get("hand_over"):
                        winner_info = result.get("winner", {})
                        payload = {
                            "winner": winner_info,
                            "reason": "All other players folded",
                            "pot": winner_info.get("amount", 0),
                        }
                        await self._sio.emit("hand_winner", payload, room=table_id)
                        await self._sio.emit("hand_winner", payload, room=self._poker_spectator_room(table_id))
                        
                        asyncio.create_task(table.save_checkpoint("hand_end"))
                        continue

                    if result.get("advance_phase"):
                        phase_result = engine.advance_phase()
                        await self.broadcast_state(table_id)
                        asyncio.create_task(table.save_checkpoint("phase_change"))

                        if engine.phase == PokerPhase.SHOWDOWN:
                            showdown_result = (
                                phase_result if isinstance(phase_result, dict) else {}
                            )
                            payload = {
                                "player_hands": showdown_result.get(
                                    "player_hands", engine.get_all_hole_cards()
                                ),
                                "community_cards": engine.cards_to_strings(
                                    engine.community_cards
                                ),
                                "winners": showdown_result.get("winners", []),
                            }
                            await self._sio.emit("showdown_reveal", payload, room=table_id)
                            await self._sio.emit("showdown_reveal", payload, room=self._poker_spectator_room(table_id))
                            asyncio.create_task(table.save_checkpoint("showdown"))

            except asyncio.CancelledError:
                print("Poker timeout checker stopped")
                break
            except Exception as exc:
                print(f"[PokerTimeout] Error in poker timeout checker: {exc}")
