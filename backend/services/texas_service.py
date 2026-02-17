"""Texas orchestration service."""

import asyncio
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from typing import Optional, Any

from backend.config.arena_config import TEXAS_CHIP_TO_TOKEN_RATIO
from backend.database.persistence_manager import persistence_manager
from backend.games.texas.phases import (
    POKER_ACTIVE_PHASE_VALUES,
    POKER_SHOWDOWN_PHASE,
    phase_value,
)
from backend.services.base import BaseService
from backend.services.settlement_service import SettlementService

from backend.utils import log

POKER_DISCONNECT_AUTO_LEAVE_SECONDS = 120
POKER_INACTIVE_TABLE_ABORT_SECONDS = 900


class TexasService(BaseService):
    """Coordinates poker background orchestration and game logic."""

    POKER_SPECTATOR_ROOM_PREFIX = "spectate:poker:"

    def __init__(self, state, sio, settlement_service: SettlementService, timeout_interval: int = 1) -> None:
        self._state = state
        self._sio = sio
        self._settlement_service = settlement_service
        self._timeout_interval = timeout_interval
        self._table_locks = {}

    def _create_task(self, coro, name=None):
        """Create a task with exception logging."""
        task = asyncio.create_task(coro, name=name)

        def _log_exception(t):
            try:
                t.result()
            except asyncio.CancelledError:
                pass
            except Exception as e:
                log.error(f"Task {name or 'unknown'} failed: {e}")
                import traceback
                traceback.print_exc()

        task.add_done_callback(_log_exception)
        return task

    def _get_table_lock(self, table_id: str) -> asyncio.Lock:
        if table_id not in self._table_locks:
            self._table_locks[table_id] = asyncio.Lock()
        return self._table_locks[table_id]

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

    @staticmethod
    def _coerce_raise_amount(amount: Any) -> int:
        """Validate and coerce raise amount to integer chips."""
        if isinstance(amount, bool):
            raise ValueError("Raise amount must be a positive integer")

        try:
            decimal_amount = Decimal(str(amount))
        except (InvalidOperation, ValueError, TypeError):
            raise ValueError("Invalid raise amount")

        if decimal_amount <= 0:
            raise ValueError("Raise amount must be greater than zero")

        if decimal_amount != decimal_amount.to_integral_value():
            raise ValueError("Raise amount must be an integer number of chips")

        return int(decimal_amount)

    async def broadcast_state(self, table_id: str) -> None:
        """Broadcast poker state with masked + private payloads."""
        table = self._state.poker_tables.get(table_id)
        if not table:
            return

        engine = table.engine
        is_showdown = phase_value(engine.phase) == POKER_SHOWDOWN_PHASE

        public_players = []
        for player_sid in engine.player_order:
            player = engine.players.get(player_sid)
            if not player:
                continue
            public_players.append(
                {
                    "sid": player_sid,
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
            "phase": phase_value(engine.phase),
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
            if sid_subs.is_reveal_enabled("poker", table_id):
                 if self._state.player_sessions.is_read_only(sid):
                     reveal_sids.append(sid)

        if reveal_sids:
            reveal_state = table.get_game_state(for_spectator=True, reveal_all=True)
            await asyncio.gather(
                *(self._sio.emit("game_update", reveal_state, room=target_sid) for target_sid in reveal_sids),
                return_exceptions=True
            )

        if not is_showdown:
            private_tasks = []
            for player_dict in table.players:
                player_sid = player_dict["sid"]
                player = engine.players.get(player_sid)
                if player and player.hole_cards:
                    private_tasks.append(self._sio.emit(
                        "private_hand",
                        {
                            "game_id": table_id,
                            "hole_cards": engine.cards_to_strings(player.hole_cards),
                            "your_turn": player_sid == current_player,
                            "timestamp": datetime.utcnow().isoformat(),
                        },
                        room=player_sid,
                    ))
            if private_tasks:
                await asyncio.gather(*private_tasks, return_exceptions=True)

        self._create_task(table.save_state_to_redis(), name=f"save_state_{table_id}")

    async def start_hand(self, table_id: str, sid: str) -> None:
        async with self._get_table_lock(table_id):
            if not table_id or table_id not in self._state.poker_tables:
                await self._sio.emit("error", {"message": "Invalid table_id"}, room=sid)
                return

            table = self._state.poker_tables[table_id]

            if sid not in table.engine.players:
                await self._sio.emit(
                    "error",
                    {"message": "Only seated players can start a hand"},
                    room=sid,
                )
                return

            if phase_value(table.engine.phase) in POKER_ACTIVE_PHASE_VALUES:
                await self._sio.emit(
                    "error",
                    {"message": "A hand is already in progress"},
                    room=sid,
                )
                return

            if not table.start_game():
                await self._sio.emit("error", {"message": "Not enough players to start"}, room=sid)
                return

            await self._create_task(table.save_checkpoint("hand_start"), name=f"checkpoint_hand_start_{table_id}")

        await self.broadcast_state(table_id)

    async def player_move(self, table_id: str, sid: str, action: str, amount: Any = 0, chat_message: Optional[str] = None) -> None:
        async with self._get_table_lock(table_id):
            if not table_id or table_id not in self._state.poker_tables:
                await self._sio.emit("error", {"message": "Invalid table_id"}, room=sid)
                return
            if not action:
                await self._sio.emit("error", {"message": "Action required"}, room=sid)
                return

            table = self._state.poker_tables[table_id]

            # Authorization: verify the caller is actually seated at this table
            if sid not in table.engine.players:
                await self._sio.emit("error", {"message": "You are not seated at this table"}, room=sid)
                return
            action_kwargs = {}
            if action == "raise":
                try:
                    action_kwargs["amount"] = self._coerce_raise_amount(amount)
                except ValueError as exc:
                    await self._sio.emit("error", {"message": str(exc)}, room=sid)
                    return
            if chat_message:
                action_kwargs["message"] = chat_message

            result = table.process_action(sid, action, **action_kwargs)
        if not result.get("success"):
            # Chat is decoupled from turn-based action validation. If chat was
            # accepted, persist and broadcast it even when the action fails.
            delivered_chat = result.get("chat")
            if delivered_chat and not result.get("chat_blocked"):
                player = next((p for p in table.players if p.get("sid") == sid), None)
                if player:
                    message_type = "chat" if action == "chat" else "action"
                    metadata = {"action": action} if action != "chat" else None
                    self._create_task(
                        persistence_manager.save_chat_message(
                            game_id=table_id,
                            game_type=table.game_type,
                            player_id=player.get("player_id", ""),
                            nickname=player.get("nickname", "Player"),
                            message=delivered_chat,
                            message_type=message_type,
                            metadata=metadata,
                        ),
                        name=f"save_chat_{table_id}"
                    )
                await self.broadcast_state(table_id)

            if result.get("chat_blocked"):
                await self._sio.emit(
                    "error",
                    {
                        "message": "Chat is not allowed during active hand",
                        "error_code": "CHAT_PHASE_RESTRICTED",
                    },
                    room=sid,
                )

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
                await asyncio.create_task(
                    persistence_manager.save_chat_message(
                        game_id=table_id,
                        game_type=table.game_type,
                        player_id=player.get("player_id", ""),
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
            
            await asyncio.create_task(table.save_checkpoint("hand_end"))
            return

        if result.get("advance_phase"):
            phase_result = table.engine.advance_phase()
            await self.broadcast_state(table_id)
            await asyncio.create_task(table.save_checkpoint("phase_change"))

            if phase_value(table.engine.phase) == POKER_SHOWDOWN_PHASE:
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
                await asyncio.create_task(table.save_checkpoint("showdown"))

        await asyncio.create_task(table.save_checkpoint("action"))

    async def leave_game(self, table_id: str, sid: str) -> None:
        async with self._get_table_lock(table_id):
            if not table_id or table_id not in self._state.poker_tables:
                await self._sio.emit("error", {"message": "Invalid table_id"}, room=sid)
                return

            table = self._state.poker_tables[table_id]
            if phase_value(table.engine.phase) in POKER_ACTIVE_PHASE_VALUES:
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
                self._state.player_sessions.set_table_id(sid, None)
            
            if player_dict:
                # Clean up disconnected tracking if exists
                self._state.poker_disconnected_since.clear(
                    table_id,
                    player_dict.get("player_id", ""),
                )

            if player_dict and engine_player:
                player_id = player_dict["player_id"]
                buy_in_tokens = Decimal(str(player_dict.get("buy_in_tokens", 0) or 0))
                chips_tokens = Decimal(str(engine_player.chips * TEXAS_CHIP_TO_TOKEN_RATIO))

                await self._settlement_service.settle_texas_player(
                    player_id,
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
        disconnected_map = self._state.poker_disconnected_since.get_table(table_id)
        if not disconnected_map:
            return

        now = datetime.utcnow()
        to_remove = []
        for player_id, disconnected_at in list(disconnected_map.items()):
            player_dict = next(
                (p for p in table.players if p.get("player_id") == player_id),
                None,
            )
            if not player_dict:
                self._state.poker_disconnected_since.clear(table_id, player_id)
                continue

            player_sid = player_dict.get("sid")
            if player_sid in self._state.player_sessions:
                self._state.poker_disconnected_since.clear(table_id, player_id)
                continue

            if now - disconnected_at >= timedelta(seconds=POKER_DISCONNECT_AUTO_LEAVE_SECONDS):
                to_remove.append((player_sid, player_dict))

        for player_sid, player_dict in to_remove:
            if phase_value(table.engine.phase) in POKER_ACTIVE_PHASE_VALUES:
                continue

            engine_player = table.engine.players.get(player_sid)
            table.remove_player(player_sid)

            disconnected_player_id = player_dict.get("player_id")
            buy_in_tokens = Decimal(str(player_dict.get("buy_in_tokens", 0) or 0))
            chips_tokens = (
                Decimal(str(engine_player.chips * TEXAS_CHIP_TO_TOKEN_RATIO))
                if engine_player
                else Decimal("0")
            )

            await self._settlement_service.settle_texas_player(
                disconnected_player_id,
                buy_in_tokens,
                chips_tokens,
                table_id,
                principal_description="Texas Hold'em buy-in principal unlock (disconnect)",
                win_description="Texas Hold'em settlement profit (disconnect)",
                loss_description="Texas Hold'em settlement loss (disconnect)",
                seat_session_id=player_sid,
            )

            # Clear disconnected
            self._state.poker_disconnected_since.clear(table_id, disconnected_player_id or "")

            await self._sio.leave_room(player_sid, table_id)
            await self.broadcast_state(table_id)

        if not table.players:
            self._state.poker_tables.pop(table_id, None)
            self._state.poker_disconnected_since.clear_table(table_id)

    @staticmethod
    def _to_utc(dt: Optional[datetime]) -> Optional[datetime]:
        """Normalize datetime to timezone-aware UTC."""
        if dt is None:
            return None
        if not isinstance(dt, datetime):
            return None
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    @staticmethod
    def _get_table_last_activity_at(table) -> datetime:
        """Best-effort table activity timestamp based on real player actions only."""
        candidates = [
            getattr(table, "created_at", None),
            getattr(table, "last_human_action_time", None),
        ]

        valid = [TexasService._to_utc(ts) for ts in candidates if isinstance(ts, datetime)]
        return max(valid) if valid else datetime.now(timezone.utc)

    @staticmethod
    def _is_terminal_table_ready_for_settlement(table) -> bool:
        """Return True when a table has ended and is safe to finalize now."""
        is_game_over = getattr(table, "is_game_over", None)
        if not callable(is_game_over) or not is_game_over():
            return False

        engine = getattr(table, "engine", None)
        phase = getattr(engine, "phase", None)
        # Do not finalize in the middle of an active hand.
        return phase_value(phase) not in POKER_ACTIVE_PHASE_VALUES

    async def _abort_inactive_table(self, table_id: str, table, reason: str) -> None:
        """End a long-inactive poker table and settle all seated players."""
        log.info(f"[PokerTimeout] Aborting inactive table {table_id}: {reason}")

        settle_tasks = []
        for player_dict in list(table.players):
            sid = player_dict.get("sid")
            player_id = player_dict.get("player_id")
            if not player_id:
                continue

            engine_player = table.engine.players.get(sid) if sid else None
            chips = engine_player.chips if engine_player else 0

            buy_in_tokens = Decimal(str(player_dict.get("buy_in_tokens", 0) or 0))
            chips_tokens = Decimal(str(chips * TEXAS_CHIP_TO_TOKEN_RATIO))

            settle_tasks.append(
                self._settlement_service.settle_texas_player(
                    player_id,
                    buy_in_tokens,
                    chips_tokens,
                    table_id,
                    principal_description="Texas Hold'em buy-in principal unlock (inactive table)",
                    win_description="Texas Hold'em settlement profit (inactive table)",
                    loss_description="Texas Hold'em settlement loss (inactive table)",
                    seat_session_id=sid,
                )
            )

            if sid and sid in self._state.player_sessions:
                self._state.player_sessions.set_table_id(sid, None)

        if settle_tasks:
            await asyncio.gather(*settle_tasks, return_exceptions=True)

        abort_payload = {
            "table_id": table_id,
            "reason": reason,
            "timestamp": datetime.now(timezone.utc).isoformat(),
        }
        # Emit to players before removing them from the room
        await self._sio.emit("TABLE_ABORTED", abort_payload, room=table_id)
        await self._sio.emit(
            "TABLE_ABORTED", abort_payload,
            room=self._poker_spectator_room(table_id),
        )

        for player_dict in list(table.players):
            sid = player_dict.get("sid")
            if sid:
                await self._sio.leave_room(sid, table_id)

        self._state.poker_tables.pop(table_id, None)
        self._state.poker_disconnected_since.clear_table(table_id)
        if self._state.texas_matchmaker:
            self._state.texas_matchmaker.remove_table(table_id)

    async def _timeout_loop(self) -> None:
        """Auto-resolve poker turns when action timers expire."""
        while True:
            try:
                await asyncio.sleep(self._timeout_interval)
                now = datetime.now(timezone.utc)

                # Copy keys to avoid modification during iteration
                table_ids = list(self._state.poker_tables.keys())

                for table_id in table_ids:
                    async with self._get_table_lock(table_id):
                        if table_id not in self._state.poker_tables:
                            continue
                        table = self._state.poker_tables[table_id]

                        # Ended tables should be settled/closed promptly so funds are
                        # unlocked and stale sessions disappear from runtime state.
                        if self._is_terminal_table_ready_for_settlement(table):
                            await self._abort_inactive_table(
                                table_id,
                                table,
                                "Table ended (insufficient active players)",
                            )
                            continue

                        # 0. End long-inactive tables and settle everyone.
                        last_activity_at = self._get_table_last_activity_at(table)
                        if (now - last_activity_at).total_seconds() > POKER_INACTIVE_TABLE_ABORT_SECONDS:
                            await self._abort_inactive_table(
                                table_id,
                                table,
                                "Table closed due to inactivity (> 1h without actions)",
                            )
                            continue
                        
                        # 1. Check for stale empty tables (> 1 hour)
                        if not table.players:
                            created_at = self._to_utc(getattr(table, 'created_at', None))
                            if created_at and (now - created_at).total_seconds() > 3600:
                                log.info(f"[PokerTimeout] Removing stale empty table {table_id}")
                                self._state.poker_tables.pop(table_id, None)
                                # Clean up from matchmaker if exists
                                if self._state.texas_matchmaker:
                                    self._state.texas_matchmaker.remove_table(table_id)
                                continue

                        await self._check_disconnected_players(table_id, table)
                        engine = table.engine
                        
                        # 2. Check for stuck active tables (> 30 mins since turn start)
                        if phase_value(engine.phase) in POKER_ACTIVE_PHASE_VALUES:
                            turn_started_at = self._to_utc(engine.turn_started_at)
                            if turn_started_at and (now - turn_started_at).total_seconds() > 1800:
                                log.info(f"[PokerTimeout] Force-folding stuck turn on table {table_id}")
                                # Force fold current player to unstick
                                if engine.current_player_sid:
                                    await engine.handle_timeout(engine.current_player_sid)
                                else:
                                    # If no current player but stuck in active phase, force reset/check
                                    pass
                        
                        if phase_value(engine.phase) not in POKER_ACTIVE_PHASE_VALUES:
                            continue

                        current_sid = engine.current_player_sid
                        if not current_sid:
                            continue

                        if engine.get_turn_time_remaining() > 0:
                            continue

                        log.info(f"[PokerTimeout] Table {table_id} player {current_sid} timed out")
                        result = engine.handle_timeout(current_sid)

                        if not result.get("success"):
                            log.info(
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
                                "timestamp": datetime.now(timezone.utc).isoformat(),
                            },
                            room=table_id,
                        )

                        await asyncio.create_task(table.save_checkpoint("timeout_action"))
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
                            
                            await asyncio.create_task(table.save_checkpoint("hand_end"))
                            continue

                        if result.get("advance_phase"):
                            phase_result = engine.advance_phase()
                            await self.broadcast_state(table_id)
                            await asyncio.create_task(table.save_checkpoint("phase_change"))

                            if phase_value(engine.phase) == POKER_SHOWDOWN_PHASE:
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
                                await asyncio.create_task(table.save_checkpoint("showdown"))

            except asyncio.CancelledError:
                log.info("Poker timeout checker stopped")
                break
            except Exception as exc:
                log.error(f"[PokerTimeout] Error in poker timeout checker: {exc}")
