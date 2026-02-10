"""Werewolf orchestration service."""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Optional, Dict, Any

from config.arena_config import WEREWOLF_PRIZE_MULTIPLIER
from database.models import TransactionType
from database.persistence_manager import persistence_manager
from database.redis_manager import redis_manager
from economy.account import lock_balance, get_balance, unlock_balance
from games.werewolf.werewolf_game import WerewolfGame, WerewolfPhase
from services.base import BaseService
from services.settlement_service import SettlementService

WEREWOLF_SIGNIFICANT_PHASES = {
    "waiting",
    "night_wolf_voting",
    "night_seer",
    "night_witch",
    "night_hunter",
    "day_announcement",
    "day_voting",
    "day_hunter",
    "finished",
    "aborted",
}


class WerewolfService(BaseService):
    """Coordinates werewolf background orchestration and game logic."""

    WEREWOLF_SPECTATOR_ROOM_PREFIX = "spectate:werewolf:"

    def __init__(self, state, sio, settlement_service: SettlementService, timeout_interval: int = 5) -> None:
        self._state = state
        self._sio = sio
        self._settlement_service = settlement_service
        self._timeout_interval = timeout_interval

    async def start(self) -> None:
        if self._state.werewolf_timeout_task and not self._state.werewolf_timeout_task.done():
            return
        self._state.werewolf_timeout_task = asyncio.create_task(self._timeout_loop())

    async def stop(self) -> None:
        if self._state.werewolf_timeout_task and not self._state.werewolf_timeout_task.done():
            self._state.werewolf_timeout_task.cancel()
            await asyncio.gather(self._state.werewolf_timeout_task, return_exceptions=True)

    def _werewolf_spectator_room(self, game_id: str) -> str:
        return f"{self.WEREWOLF_SPECTATOR_ROOM_PREFIX}{game_id}"

    async def broadcast_state(self, game_id: str) -> None:
        """Broadcast werewolf state to players and spectators."""
        game = self._state.werewolf_games.get(game_id)
        if not game:
            return

        for player in game.players:
            await self._sio.emit("werewolf_state", game.get_game_state(player["sid"]), room=player["sid"])

        spectator_state = game.get_game_state(reveal_all=False)
        await self._sio.emit("werewolf_state", spectator_state, room=self._werewolf_spectator_room(game_id))

        # Handle reveal spectators
        reveal_sids = []
        for sid, sid_subs in self._state.spectator_subscriptions.items():
            if sid_subs.get("werewolf", {}).get(game_id):
                 # Check read only session
                 session = self._state.player_sessions.get(sid) or {}
                 if bool(session.get("read_only") or session.get("spectator_mode")):
                     reveal_sids.append(sid)

        if reveal_sids:
            reveal_state = game.get_game_state(reveal_all=True)
            for target_sid in reveal_sids:
                 await self._sio.emit("werewolf_state", reveal_state, room=target_sid)

        asyncio.create_task(redis_manager.refresh_game_ttl(game_id))

    async def create_game(self, sid: str, game_id: str, entry_fee: Decimal) -> None:
        if sid not in self._state.player_sessions or not self._state.player_sessions[sid]["authenticated"]:
            await self._sio.emit("error", {"message": "Not authenticated"}, room=sid)
            return

        if not game_id:
            await self._sio.emit("error", {"message": "game_id required"}, room=sid)
            return
        if entry_fee <= 0:
            await self._sio.emit(
                "error",
                {"message": "Werewolf games must require a positive entry fee"},
                room=sid,
            )
            return

        async with redis_manager.lock(f"game_create:{game_id}"):
            if game_id in self._state.werewolf_games:
                await self._sio.emit("error", {"message": "Game already exists"}, room=sid)
                return

            self._state.werewolf_games[game_id] = WerewolfGame(game_id, entry_fee=entry_fee)

            await persistence_manager.on_game_created(
                game_id=game_id,
                game_type="werewolf",
                entry_fee=entry_fee,
            )

            await redis_manager.save_game_core(
                game_id,
                self._state.werewolf_games[game_id].get_core_state(),
                game_type="werewolf",
            )

        await self._sio.emit("werewolf_game_created", {"game_id": game_id}, room=sid)

    async def join_game(self, sid: str, game_id: str) -> None:
        if sid not in self._state.player_sessions or not self._state.player_sessions[sid]["authenticated"]:
            await self._sio.emit("error", {"message": "Not authenticated"}, room=sid)
            return

        nickname = self._state.player_sessions[sid]["player_name"] or "Player"

        if not game_id or game_id not in self._state.werewolf_games:
            await self._sio.emit("error", {"message": "Invalid game_id"}, room=sid)
            return

        player_id = self._state.player_sessions[sid]["player_id"]
        game = self._state.werewolf_games[game_id]

        if game.entry_fee <= 0:
            await self._sio.emit(
                "error",
                {"message": "Free werewolf rooms are not allowed"},
                room=sid,
            )
            return

        try:
            current_balance = await get_balance(player_id)
            if current_balance < game.entry_fee:
                await self._sio.emit(
                    "error",
                    {
                        "message": (
                            f"Insufficient balance. Required: {float(game.entry_fee)} tokens, "
                            f"Available: {float(current_balance)}"
                        )
                    },
                    room=sid,
                )
                return
        except Exception as exc:
            await self._sio.emit(
                "error",
                {"message": f"Balance check failed: {str(exc)}"},
                room=sid,
            )
            return

        async with redis_manager.lock(f"game_join:{game_id}"):
            if not game.add_player(sid, player_id, nickname=nickname):
                await self._sio.emit("error", {"message": "Could not join game"}, room=sid)
                return

            try:
                await lock_balance(player_id, game.entry_fee, game_session_id=game_id)
            except Exception as exc:
                await self._sio.emit(
                    "error",
                    {"message": f"Failed to lock entry fee: {str(exc)}"},
                    room=sid,
                )
                game.remove_player(sid)
                return

            self._state.player_sessions[sid]["game_id"] = game_id

            await persistence_manager.on_player_joined(
                game_id=game_id,
                player_id=player_id,
                socket_sid=sid,
                nickname=nickname,
                entry_paid=game.entry_fee,
            )

            await redis_manager.save_game_core(
                game_id,
                game.get_core_state(),
                game_type="werewolf",
            )

        await self._sio.enter_room(sid, game_id)

        await self._sio.emit(
            "werewolf_joined",
            {
                "game_id": game_id,
                "player_id": player_id,
                "player_name": nickname,
            },
            room=sid,
        )

        await self.broadcast_state(game_id)

    async def start_game(self, sid: str, game_id: str) -> None:
        if not game_id or game_id not in self._state.werewolf_games:
            await self._sio.emit("error", {"message": "Invalid game_id"}, room=sid)
            return

        game = self._state.werewolf_games[game_id]
        if not game.start_game():
            await self._sio.emit(
                "error",
                {"message": "Cannot start game (need more players)"},
                room=sid,
            )
            return

        players_with_roles = []
        for player in game.players:
            players_with_roles.append(
                {
                    "wallet_address": player["wallet_address"],
                    "role_type": player["role"].role_type.value if player.get("role") else None,
                    "team": player["role"].team.value if player.get("role") else None,
                }
            )

        await persistence_manager.on_game_started(
            game_id=game_id,
            players_with_roles=players_with_roles,
            initial_state=game.to_dict(),
        )

        await self.broadcast_state(game_id)

    def _is_night_phase(self, phase: str) -> bool:
        return phase.startswith("night_")

    def _build_werewolf_action_trace(
        self,
        game,
        sid: str,
        action: str,
        result: Dict,
        target_sid: Optional[str],
        message: Optional[str],
        reveal: bool,
    ) -> Dict:
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

        payload: Dict = {
            "game_id": game.game_id,
            "phase": phase,
            "actor_sid": sid,
            "actor_nickname": actor_nickname,
            "action": action,
            "timestamp": datetime.utcnow().isoformat(),
        }

        hide_target = self._is_night_phase(phase) and not reveal
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
        self,
        game,
        sid: str,
        action: str,
        result: Dict,
        target_sid: Optional[str],
        message: Optional[str],
    ) -> None:
        """Emit action timeline events to spectators (masked + reveal modes)."""
        game_id = game.game_id
        masked_payload = self._build_werewolf_action_trace(
            game, sid, action, result, target_sid, message, reveal=False
        )
        await self._sio.emit(
            "werewolf_action_trace",
            masked_payload,
            room=self._werewolf_spectator_room(game_id),
        )

        reveal_sids = []
        for s, sid_subs in self._state.spectator_subscriptions.items():
            if sid_subs.get("werewolf", {}).get(game_id):
                 session = self._state.player_sessions.get(s) or {}
                 if bool(session.get("read_only") or session.get("spectator_mode")):
                     reveal_sids.append(s)

        if reveal_sids:
            reveal_payload = self._build_werewolf_action_trace(
                game, sid, action, result, target_sid, message, reveal=True
            )
            for target_sid in reveal_sids:
                await self._sio.emit("werewolf_action_trace", reveal_payload, room=target_sid)

    async def process_action(self, sid: str, game_id: str, action: str, target_sid: Optional[str] = None, message: Optional[str] = None) -> None:
        if not game_id or game_id not in self._state.werewolf_games:
            await self._sio.emit("error", {"message": "Invalid game_id"}, room=sid)
            return

        if not action:
            await self._sio.emit("error", {"message": "Action required"}, room=sid)
            return

        game = self._state.werewolf_games[game_id]

        if action not in ["chat", "wolf_chat"]:
             await self._sio.emit(
                 "player_thinking",
                 {"game_id": game_id, "player_sid": sid, "action_type": action},
                 room=game_id
             )
             await self._sio.emit(
                 "player_thinking",
                 {"game_id": game_id, "player_sid": sid, "action_type": action},
                 room=self._werewolf_spectator_room(game_id)
             )

        kwargs = {}
        if target_sid is not None:
            kwargs["target_sid"] = target_sid
        if message:
            kwargs["message"] = message

        result = game.process_action(sid, action, **kwargs)
        if not result.get("success"):
            error_payload = {"message": result.get("error", "Action failed")}
            if result.get("error_code"):
                error_payload["error_code"] = result.get("error_code")
            await self._sio.emit("error", error_payload, room=sid)
            return

        await self._sio.emit("werewolf_action_result", result, room=sid)
        await self._emit_werewolf_action_trace(
            game,
            sid,
            action,
            result,
            target_sid,
            message,
        )

        if action in ["chat", "wolf_chat"] and message:
            player = next((p for p in game.players if p["sid"] == sid), None)
            if player:
                metadata = {
                    "phase": game.phase.value,
                    "is_wolf_chat": action == "wolf_chat",
                }
                asyncio.create_task(
                    persistence_manager.save_chat_message(
                        game_id=game_id,
                        game_type=game.game_type,
                        player_id=player["wallet_address"],
                        nickname=player["nickname"],
                        message=message,
                        message_type=action,
                        metadata=metadata,
                    )
                )

        if action == "wolf_chat" and result.get("wolf_only"):
            wolf_sids = [
                p["sid"]
                for p in game.players
                if p.get("role")
                and hasattr(p["role"], "role_type")
                and p["role"].role_type.value == "wolf"
            ]
            for wolf_sid in wolf_sids:
                if wolf_sid != sid:
                    await self._sio.emit("wolf_chat_message", result.get("chat"), room=wolf_sid)

            reveal_sids = []
            for s, sid_subs in self._state.spectator_subscriptions.items():
                if sid_subs.get("werewolf", {}).get(game_id):
                    session = self._state.player_sessions.get(s) or {}
                    if bool(session.get("read_only") or session.get("spectator_mode")):
                        reveal_sids.append(s)

            for target_sid in reveal_sids:
                 await self._sio.emit("wolf_chat_message", result.get("chat"), room=target_sid)

        elif action == "chat":
             payload = result.get("chat")
             await self._sio.emit("chat_message", payload, room=game_id)
             await self._sio.emit("chat_message", payload, room=self._werewolf_spectator_room(game_id))

        elif action == "speak":
            player = next((p for p in game.players if p["sid"] == sid), None)
            if player:
                asyncio.create_task(
                    persistence_manager.save_speech(
                        game_id=game_id,
                        player_id=player["wallet_address"],
                        nickname=player["nickname"],
                        message=message or "",
                        phase=game.phase.value,
                        game_type=game.game_type,
                    )
                )

        if action not in ["chat", "wolf_chat"]:
            await redis_manager.save_game_core(
                game_id,
                game.get_core_state(),
                game_type="werewolf",
            )

        if result.get("all_actions_complete"):
            print(
                f"[AutoAdvance] All actions complete for game {game_id} phase {game.phase.value}, advancing..."
            )
            old_phase = game.phase.value
            phase_result = game.advance_phase()
            new_phase = phase_result.get("new_phase", "")

            is_significant = (
                new_phase in WEREWOLF_SIGNIFICANT_PHASES
                or old_phase in WEREWOLF_SIGNIFICANT_PHASES
            )

            await persistence_manager.on_phase_changed(
                game_id=game_id,
                new_phase=new_phase,
                day_count=phase_result.get("day_count", game.day_count),
                game_state=game.to_dict(),
                deaths=phase_result.get("deaths", []),
                significant=is_significant,
            )

            payload = {
                "phase": new_phase,
                "day_count": phase_result.get("day_count"),
                "deaths": phase_result.get("deaths", []),
                "eliminated": phase_result.get("eliminated"),
                "game_over": phase_result.get("game_over", False),
                "winners": phase_result.get("winners", []),
            }
            await self._sio.emit("werewolf_phase_change", payload, room=game_id)
            await self._sio.emit("werewolf_phase_change", payload, room=self._werewolf_spectator_room(game_id))

            if phase_result.get("game_over"):
                await self._handle_game_end(game_id, phase_result.get("winners", []))

        await self.broadcast_state(game_id)

    def _get_settlement_lock(self, game_id: str) -> asyncio.Lock:
        lock = self._state.werewolf_settlement_locks.get(game_id)
        if lock is None:
            lock = asyncio.Lock()
            self._state.werewolf_settlement_locks[game_id] = lock
        return lock

    async def _handle_game_end(self, game_id: str, winners: list) -> None:
        lock = self._get_settlement_lock(game_id)
        async with lock:
            if game_id in self._state.werewolf_finalized_games:
                print(f"[WerewolfSettle] Game {game_id} already finalized")
                return
            self._state.werewolf_finalized_games[game_id] = "ended"

            game = self._state.werewolf_games.get(game_id)

            total_entry_fees = Decimal("0")
            prize_pool = Decimal("0")
            winner_team = None
            if game:
                total_entry_fees = sum(player["entry_fee_paid"] for player in game.players)
                prize_pool = total_entry_fees * WEREWOLF_PRIZE_MULTIPLIER

                if winners:
                    for player in game.players:
                        if player["wallet_address"] in winners:
                            if player.get("role") and hasattr(player["role"], "team"):
                                winner_team = player["role"].team.value
                                break

            try:
                await persistence_manager.on_game_ended(
                    game_id=game_id,
                    winner_team=winner_team,
                    winners=winners,
                    was_aborted=False,
                    final_state=game.to_dict() if game else None,
                    prize_pool=prize_pool,
                )
            except Exception as exc:
                print(f"Failed to persist game end: {exc}")
                import traceback
                traceback.print_exc()

            try:
                if game:
                    await self._settlement_service.refund_werewolf_entry_fees(
                        game.players,
                        game_id,
                        description="Werewolf entry fee principal unlock",
                    )

                if game and winners:
                    print(
                        f"Werewolf game prize pool: {float(prize_pool)} tokens from {len(winners)} winners"
                    )
                    await self._settlement_service.award_werewolf_prizes(
                        winners,
                        prize_pool,
                        description="Werewolf game prize",
                    )

                elif game and not winners:
                    print("Werewolf game ended without winners, refunding entry fees")
                else:
                    print("No game data found for prize distribution")
            except Exception as exc:
                print(f"Failed to handle prize distribution: {exc}")
                import traceback
                traceback.print_exc()

    async def _handle_game_abort(self, game_id: str, reason: Optional[str] = None) -> None:
        lock = self._get_settlement_lock(game_id)
        async with lock:
            if game_id in self._state.werewolf_finalized_games:
                print(f"[WerewolfSettle] Abort skipped; game {game_id} already finalized")
                return
            self._state.werewolf_finalized_games[game_id] = "aborted"

            game = self._state.werewolf_games.get(game_id)

            try:
                await persistence_manager.on_game_ended(
                    game_id=game_id,
                    winner_team=None,
                    winners=[],
                    was_aborted=True,
                    final_state=game.to_dict() if game else None,
                    prize_pool=Decimal("0"),
                )
            except Exception as exc:
                print(f"Failed to persist aborted game end: {exc}")
                import traceback
                traceback.print_exc()

            try:
                if game:
                    await self._settlement_service.refund_werewolf_entry_fees(
                        game.players,
                        game_id,
                        description="Werewolf game refund - aborted",
                    )
                    print(
                        f"Werewolf game aborted: refunded entry fees ({reason or 'no reason'})"
                    )
                else:
                    print("No game data found for aborted refund")
            except Exception as exc:
                print(f"Failed to refund aborted werewolf game: {exc}")
                import traceback
                traceback.print_exc()

    async def _timeout_loop(self) -> None:
        """Auto-resolve werewolf phases when action timers expire."""
        active_phases = {
            WerewolfPhase.NIGHT_WOLF_DISCUSSION,
            WerewolfPhase.NIGHT_WOLF_VOTING,
            WerewolfPhase.NIGHT_SEER,
            WerewolfPhase.NIGHT_WITCH,
            WerewolfPhase.NIGHT_HUNTER,
            WerewolfPhase.DAY_ANNOUNCEMENT,
            WerewolfPhase.DAY_SPEAKING,
            WerewolfPhase.DAY_VOTING,
            WerewolfPhase.DAY_HUNTER,
        }

        while True:
            try:
                await asyncio.sleep(self._timeout_interval)

                for game_id, game in list(self._state.werewolf_games.items()):
                    if game.phase not in active_phases:
                        continue

                    if game.get_time_remaining() > 0:
                        continue

                    print(f"[Timeout] Game {game_id} phase {game.phase.value} timed out")

                    try:
                        old_phase = game.phase.value
                        result = await game.handle_phase_timeout()
                        new_phase = result.get("new_phase", game.phase.value)

                        is_significant = (
                            new_phase in WEREWOLF_SIGNIFICANT_PHASES
                            or old_phase in WEREWOLF_SIGNIFICANT_PHASES
                        )

                        await persistence_manager.on_phase_changed(
                            game_id=game_id,
                            new_phase=new_phase,
                            day_count=result.get("day_count", game.day_count),
                            game_state=game.to_dict(),
                            deaths=result.get("deaths", []),
                            significant=is_significant,
                        )

                        if result.get("timed_out_players"):
                            for nickname in result["timed_out_players"]:
                                await self._sio.emit(
                                    "PLAYER_TIMEOUT",
                                    {
                                        "message": f"Player {nickname} Timed Out",
                                        "player": nickname,
                                        "timestamp": datetime.utcnow().isoformat(),
                                    },
                                    room=game_id,
                                )

                        if result.get("aborted"):
                            await self._sio.emit(
                                "GAME_ABORTED",
                                {
                                    "message": result.get("reason", "Game aborted"),
                                    "refund_players": result.get("refund_players", []),
                                    "timestamp": datetime.utcnow().isoformat(),
                                },
                                room=game_id,
                            )
                            await self._handle_game_abort(
                                game_id,
                                result.get("reason"),
                            )
                            continue

                        payload = {
                            "phase": result.get("new_phase"),
                            "day_count": result.get("day_count"),
                            "deaths": result.get("deaths", []),
                            "eliminated": result.get("eliminated"),
                            "game_over": result.get("game_over", False),
                            "winners": result.get("winners", []),
                        }
                        await self._sio.emit("werewolf_phase_change", payload, room=game_id)
                        await self._sio.emit("werewolf_phase_change", payload, room=self._werewolf_spectator_room(game_id))

                        if result.get("game_over"):
                            await self._handle_game_end(
                                game_id,
                                result.get("winners", []),
                            )

                        await self.broadcast_state(game_id)

                    except Exception as exc:
                        print(f"[Timeout] Error handling timeout for game {game_id}: {exc}")
                        import traceback
                        traceback.print_exc()

            except asyncio.CancelledError:
                print("Werewolf timeout checker stopped")
                break
            except Exception as exc:
                print(f"[Timeout] Error in werewolf timeout checker: {exc}")
