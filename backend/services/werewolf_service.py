"""Werewolf orchestration service."""

import asyncio
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional, Dict

from backend.config.arena_config import WEREWOLF_PRIZE_MULTIPLIER, is_local_debug_mode
from backend.database.persistence_manager import persistence_manager
from backend.database.redis_manager import redis_manager
from backend.economy.account_service import lock_balance, get_available_balance
from backend.games.werewolf.werewolf_game import WerewolfGame, WerewolfPhase
from backend.services.base import BaseService
from backend.services.settlement_service import SettlementService

from backend.utils import log

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

WEREWOLF_INACTIVE_GAME_ABORT_SECONDS = 3600


class WerewolfService(BaseService):
    """Coordinates werewolf background orchestration and game logic."""

    WEREWOLF_SPECTATOR_ROOM_PREFIX = "spectate:werewolf:"

    def __init__(self, state, sio, settlement_service: SettlementService, timeout_interval: int = 5) -> None:
        self._state = state
        self._sio = sio
        self._settlement_service = settlement_service
        self._timeout_interval = timeout_interval
        self._game_locks = {}

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

    def _get_game_lock(self, game_id: str) -> asyncio.Lock:
        if game_id not in self._game_locks:
            self._game_locks[game_id] = asyncio.Lock()
        return self._game_locks[game_id]

    async def start(self) -> None:
        if self._state.werewolf_timeout_task and not self._state.werewolf_timeout_task.done():
            return
        self._state.werewolf_timeout_task = self._create_task(self._timeout_loop(), name="werewolf_timeout_loop")

    async def stop(self) -> None:
        if self._state.werewolf_timeout_task and not self._state.werewolf_timeout_task.done():
            self._state.werewolf_timeout_task.cancel()
            await asyncio.gather(self._state.werewolf_timeout_task, return_exceptions=True)

    def _werewolf_spectator_room(self, game_id: str) -> str:
        return f"{self.WEREWOLF_SPECTATOR_ROOM_PREFIX}{game_id}"

    async def _acquire_game_state_lock(self, game_id: str):
        """Return a Redis lock context for game state transitions.

        This lock is shared by join/start flows to prevent cross-node races
        where a game could start while a player is mid-join.
        """
        return redis_manager.lock(f"game_state:{game_id}", timeout=10)

    async def broadcast_state(self, game_id: str) -> None:
        """Broadcast werewolf state to players and spectators."""
        game = self._state.werewolf_games.get(game_id)
        if not game:
            return

        tasks = []
        for player in game.players:
            tasks.append(self._sio.emit("werewolf_state", game.get_game_state(player["sid"]), room=player["sid"]))
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        spectator_state = game.get_game_state(reveal_all=False)
        await self._sio.emit("werewolf_state", spectator_state, room=self._werewolf_spectator_room(game_id))

        # Handle reveal spectators
        reveal_sids = []
        for sid, sid_subs in self._state.spectator_subscriptions.items():
            if sid_subs.is_reveal_enabled("werewolf", game_id):
                 if self._state.player_sessions.is_read_only(sid):
                     reveal_sids.append(sid)

        if reveal_sids:
            reveal_state = game.get_game_state(reveal_all=True)
            await asyncio.gather(
                *(self._sio.emit("werewolf_state", reveal_state, room=target_sid) for target_sid in reveal_sids),
                return_exceptions=True)

        self._create_task(redis_manager.refresh_game_ttl(game_id), name=f"refresh_ttl_{game_id}")

    async def create_game(self, sid: str, game_id: str, entry_fee: Decimal) -> None:
        if not self._state.player_sessions.is_authenticated(sid):
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

            game = WerewolfGame(game_id, entry_fee=entry_fee)
            # Track host identity for start-game authorization checks.
            game.created_by_sid = sid
            self._state.werewolf_games[game_id] = game

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
        session = self._state.player_sessions.get(sid)
        if not session or not session.authenticated:
            await self._sio.emit("error", {"message": "Not authenticated"}, room=sid)
            return

        nickname = session.player_name or "Player"

        if not game_id or game_id not in self._state.werewolf_games:
            await self._sio.emit("error", {"message": "Invalid game_id"}, room=sid)
            return

        player_id = session.player_id
        game = self._state.werewolf_games[game_id]

        if game.entry_fee <= 0:
            await self._sio.emit(
                "error",
                {"message": "Free werewolf rooms are not allowed"},
                room=sid,
            )
            return

        async with self._get_game_lock(game_id):
            # Balance check inside lock to eliminate TOCTOU window
            try:
                available_balance = await get_available_balance(player_id)
                if available_balance < game.entry_fee:
                    await self._sio.emit(
                        "error",
                        {
                            "message": (
                                f"Insufficient balance. Required: {str(game.entry_fee)} tokens, "
                                f"Available: {str(available_balance)}"
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

            if player_id and game.has_wallet(player_id):
                await self._sio.emit(
                    "error",
                    {"message": "Player already joined this game"},
                    room=sid,
                )
                return

            if not game.add_player(sid, player_id, nickname=nickname):
                await self._sio.emit("error", {"message": "Could not join game"}, room=sid)
                return

            try:
                await lock_balance(player_id, game.entry_fee)
            except Exception as exc:
                await self._sio.emit(
                    "error",
                    {"message": f"Failed to lock entry fee: {str(exc)}"},
                    room=sid,
                )
                game.remove_player(sid)
                return

            self._state.player_sessions.set_game_id(sid, game_id)

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

        async with redis_manager.lock(f"game_start:{game_id}", timeout=5):
            async with self._get_game_lock(game_id):
                game = self._state.werewolf_games[game_id]

                if getattr(game, "started", False):
                    return

                player_sids = {player.get("sid") for player in game.players}
                if sid not in player_sids:
                    await self._sio.emit(
                        "error",
                        {"message": "Only players in this game can start it"},
                        room=sid,
                    )
                    return

                host_sid = getattr(game, "created_by_sid", None)
                if host_sid and sid != host_sid:
                    await self._sio.emit(
                        "error",
                        {"message": "Only game host can start the game"},
                        room=sid,
                    )
                    return

                if game.phase != WerewolfPhase.WAITING:
                    await self._sio.emit(
                        "error",
                        {"message": "Game already started"},
                        room=sid,
                    )
                    return

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
            "timestamp": datetime.now(timezone.utc).isoformat(),
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
            if sid_subs.is_reveal_enabled("werewolf", game_id):
                 if self._state.player_sessions.is_read_only(s):
                     reveal_sids.append(s)

        if reveal_sids:
            reveal_payload = self._build_werewolf_action_trace(
                game, sid, action, result, target_sid, message, reveal=True
            )
            for target_sid in reveal_sids:
                await self._sio.emit("werewolf_action_trace", reveal_payload, room=target_sid)

    async def advance_phase(self, sid: str, game_id: str) -> None:
        """Manually advance the game phase (debug/admin or fallback)."""
        if not is_local_debug_mode():
            await self._sio.emit(
                "error",
                {
                    "message": "advance_werewolf_phase is only available in LOCAL_DEBUG_MODE",
                    "error_code": "DEBUG_ONLY",
                },
                room=sid,
            )
            return
        log.info(f"[Werewolf] Manual phase advance triggered by {sid} for game {game_id}")
        await self._advance_phase_logic(game_id)

    async def _advance_phase_logic(self, game_id: str) -> None:
        """Core logic to advance phase and handle side effects."""
        async with self._get_game_lock(game_id):
            game = self._state.werewolf_games.get(game_id)
            if not game:
                return
            
            # If game is already finished, do nothing
            if game.phase == WerewolfPhase.FINISHED:
                return

            old_phase = game.phase.value
            phase_result = game.advance_phase()
            new_phase = phase_result.get("new_phase")
            
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
            
            # Broadcast full state update as well
            await self.broadcast_state(game_id)
            
            # Handle game over
            if phase_result.get("game_over"):
                winners = phase_result.get("winners", [])
                log.info(f"Game {game_id} finished. Winners: {winners}")
                await self._handle_game_end(game_id, winners)
                # Remove finished game from memory after settlement
                self._state.werewolf_games.pop(game_id, None)

    async def process_action(self, sid: str, game_id: str, action: str, target_sid: Optional[str] = None, message: Optional[str] = None) -> None:
        async with self._get_game_lock(game_id):
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

            # Snapshot game state while still holding the lock to avoid
            # reading data that a concurrent action could modify.
            phase_value = game.phase.value
            game_type = game.game_type
            player_by_sid = {p["sid"]: p for p in game.players}
            wolf_sids = [
                p["sid"]
                for p in game.players
                if p.get("role")
                and hasattr(p["role"], "role_type")
                and p["role"].role_type.value == "wolf"
                and p["is_alive"]
            ]
            core_state = game.get_core_state() if action not in ["chat", "wolf_chat"] else None
            all_actions_complete = result.get("all_actions_complete")

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
            player = player_by_sid.get(sid)
            if player:
                metadata = {
                    "phase": phase_value,
                    "is_wolf_chat": action == "wolf_chat",
                }
                self._create_task(
                    persistence_manager.save_chat_message(
                        game_id=game_id,
                        game_type=game_type,
                        player_id=player["wallet_address"],
                        nickname=player["nickname"],
                        message=message,
                        message_type=action,
                        metadata=metadata,
                    ),
                    name=f"save_chat_{game_id}"
                )

        if action == "wolf_chat" and result.get("wolf_only"):
            for wolf_sid in wolf_sids:
                if wolf_sid != sid:
                    await self._sio.emit("wolf_chat_message", result.get("chat"), room=wolf_sid)

            reveal_sids = []
            for s, sid_subs in self._state.spectator_subscriptions.items():
                if sid_subs.is_reveal_enabled("werewolf", game_id):
                    if self._state.player_sessions.is_read_only(s):
                        reveal_sids.append(s)

            for rsid in reveal_sids:
                 await self._sio.emit("wolf_chat_message", result.get("chat"), room=rsid)

        elif action == "chat":
             payload = result.get("chat")
             await self._sio.emit("chat_message", payload, room=game_id)
             await self._sio.emit("chat_message", payload, room=self._werewolf_spectator_room(game_id))

        elif action == "speak":
            player = player_by_sid.get(sid)
            if player:
                self._create_task(
                    persistence_manager.save_speech(
                        game_id=game_id,
                        player_id=player["wallet_address"],
                        nickname=player["nickname"],
                        message=message or "",
                        phase=phase_value,
                        game_type=game_type,
                    ),
                    name=f"save_speech_{game_id}"
                )

        if core_state is not None:
            await redis_manager.save_game_core(
                game_id,
                core_state,
                game_type="werewolf",
            )

        if all_actions_complete:
            log.info(f"[AutoAdvance] All actions complete for game {game_id}, advancing...")
            await self._advance_phase_logic(game_id)

        await self.broadcast_state(game_id)

    def _get_settlement_lock(self, game_id: str) -> asyncio.Lock:
        lock = self._state.werewolf_settlement_locks.get(game_id)
        if lock is None:
            lock = asyncio.Lock()
            self._state.werewolf_settlement_locks[game_id] = lock
        return lock

    def _persist_timeout_audit(self, game_id: str, game_type: str, timeout_actions: list) -> None:
        """Persist timeout default actions as lightweight system audit messages."""
        for action in timeout_actions:
            action_name = action.get("action", "unknown")
            actor = action.get("actor_nickname", "unknown")
            phase = action.get("phase", "unknown")
            target = action.get("target_nickname")
            target_part = f", target={target}" if target else ""

            message = f"[timeout] phase={phase}, actor={actor}, action={action_name}{target_part}"

            self._create_task(
                persistence_manager.save_chat_message(
                    game_id=game_id,
                    game_type=game_type,
                    player_id="system",
                    nickname="System",
                    message=message,
                    message_type="timeout_audit",
                    metadata=action,
                ),
                name=f"timeout_audit_{game_id}"
            )

    async def _handle_game_end(self, game_id: str, winners: list) -> None:
        lock = self._get_settlement_lock(game_id)
        async with lock:
            if self._state.werewolf_finalized_games.is_finalized(game_id):
                log.info(f"[WerewolfSettle] Game {game_id} already finalized")
                return
            self._state.werewolf_finalized_games.mark_ended(game_id)

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
                log.error(f"Failed to persist game end: {exc}")
                import traceback
                traceback.print_exc()

            try:
                if game:
                    if not winners:
                        # No winners — treat as abort and refund all players
                        log.info(f"[WerewolfSettle] Game {game_id} ended without winners, refunding entry fees")
                        should_refund = await redis_manager.mark_settlement_stage_once(
                            game_id,
                            "werewolf_refund",
                        )
                        if should_refund:
                            await self._settlement_service.refund_werewolf_entry_fees(
                                game.players,
                                game_id,
                                description="Werewolf game refund - no winners",
                            )
                        return

                    should_settle = await redis_manager.mark_settlement_stage_once(
                        game_id,
                        "werewolf_settlement",
                    )
                    if not should_settle:
                        log.warning(f"[WerewolfSettle] Skip duplicate settlement for game {game_id}")
                        return

                    try:
                        log.info(
                            f"Werewolf game prize pool: {str(prize_pool)} tokens from {len(winners)} winners"
                        )
                        await self._settlement_service.process_werewolf_settlement(
                            game.players,
                            winners,
                            game_id,
                            prize_pool,
                        )
                    except Exception:
                        await redis_manager.clear_settlement_stage(
                            game_id,
                            "werewolf_settlement",
                        )
                        raise
                else:
                    log.info("No game data found for prize distribution")
            except Exception as exc:
                log.error(f"Failed to handle prize distribution: {exc}")
                import traceback
                traceback.print_exc()

    async def _handle_game_abort(self, game_id: str, reason: Optional[str] = None) -> None:
        lock = self._get_settlement_lock(game_id)
        async with lock:
            if self._state.werewolf_finalized_games.is_finalized(game_id):
                log.warning(f"[WerewolfSettle] Abort skipped; game {game_id} already finalized")
                return
            self._state.werewolf_finalized_games.mark_aborted(game_id)

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
                log.error(f"Failed to persist aborted game end: {exc}")
                import traceback
                traceback.print_exc()

            try:
                if game:
                    should_refund = await redis_manager.mark_settlement_stage_once(
                        game_id,
                        "werewolf_refund",
                    )
                    if should_refund:
                        await self._settlement_service.refund_werewolf_entry_fees(
                            game.players,
                            game_id,
                            description="Werewolf game refund - aborted",
                        )
                        log.info(
                            f"Werewolf game aborted: refunded entry fees ({reason or 'no reason'})"
                        )
                    else:
                        log.warning(f"[WerewolfSettle] Skip duplicate abort refund stage for game {game_id}")
                else:
                    log.info("No game data found for aborted refund")
            except Exception as exc:
                log.error(f"Failed to refund aborted werewolf game: {exc}")
                import traceback
                traceback.print_exc()

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
    def _get_game_last_activity_at(game) -> datetime:
        """Best-effort real-player activity timestamp for inactivity cleanup."""
        candidates = [
            getattr(game, "created_at", None),
            getattr(game, "started_at", None),
        ]

        last_action_map = getattr(game, "last_action_time", None)
        if isinstance(last_action_map, dict):
            candidates.extend(ts for ts in last_action_map.values() if ts)

        valid = [WerewolfService._to_utc(ts) for ts in candidates if isinstance(ts, datetime)]
        return max(valid) if valid else datetime.now(timezone.utc)

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
                now = datetime.now(timezone.utc)

                # Copy keys to avoid modification during iteration
                game_ids = list(self._state.werewolf_games.keys())

                for game_id in game_ids:
                    async with self._get_game_lock(game_id):
                        if game_id not in self._state.werewolf_games:
                            continue
                        game = self._state.werewolf_games[game_id]

                        # 0. End games with no real player actions for a long time.
                        # Timeout-driven phase auto-advances are intentionally ignored
                        # so zombie-only games are eventually aborted+refunded.
                        if game.phase not in {WerewolfPhase.FINISHED, WerewolfPhase.ABORTED}:
                            last_activity_at = self._get_game_last_activity_at(game)
                            if (now - last_activity_at).total_seconds() > WEREWOLF_INACTIVE_GAME_ABORT_SECONDS:
                                log.info(f"[Timeout] Aborting inactive game {game_id} (no player actions > 1h)")
                                await self._handle_game_abort(
                                    game_id,
                                    "Game cancelled due to inactivity (> 1h without player actions)",
                                )
                                self._state.werewolf_games.pop(game_id, None)
                                continue

                        # 1. Check for stale waiting games (> 1 hour)
                        if game.phase == WerewolfPhase.WAITING:
                            created_at = self._to_utc(getattr(game, 'created_at', None))
                            if created_at and (now - created_at).total_seconds() > 3600:
                                log.info(f"[Timeout] Aborting stale waiting game {game_id}")
                                await self._handle_game_abort(
                                    game_id, 
                                    "Game cancelled due to inactivity (waiting > 1h)"
                                )
                                # Ensure removed from memory
                                self._state.werewolf_games.pop(game_id, None)
                                continue

                        # 2. Check for stuck active games (> 1 hour in same phase)
                        if game.phase in active_phases:
                            phase_start = self._to_utc(getattr(game, '_phase_start_time', None))
                            if phase_start and (now - phase_start).total_seconds() > 3600:
                                log.info(f"[Timeout] Aborting stuck active game {game_id}")
                                await self._handle_game_abort(
                                    game_id,
                                    f"Game cancelled due to stuck phase {game.phase.value} (> 1h)"
                                )
                                self._state.werewolf_games.pop(game_id, None)
                                continue

                        if game.phase not in active_phases:
                            continue

                        if game.get_time_remaining() > 0:
                            continue

                        log.info(f"[Timeout] Game {game_id} phase {game.phase.value} timed out")

                        try:
                            old_phase = game.phase.value
                            result = await game.handle_phase_timeout()
                            new_phase = result.get("new_phase", game.phase.value)
                            timeout_actions = result.get("timeout_actions", []) or []
                            if timeout_actions:
                                self._persist_timeout_audit(game_id, game.game_type, timeout_actions)

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
                                            "timestamp": datetime.now(timezone.utc).isoformat(),
                                        },
                                        room=game_id,
                                    )

                            if result.get("aborted"):
                                abort_payload = {
                                    "message": result.get("reason", "Game aborted"),
                                    "refund_players": result.get("refund_players", []),
                                    "timestamp": datetime.now(timezone.utc).isoformat(),
                                }
                                await self._sio.emit(
                                    "GAME_ABORTED",
                                    abort_payload,
                                    room=game_id,
                                )
                                await self._sio.emit(
                                    "GAME_ABORTED",
                                    abort_payload,
                                    room=self._werewolf_spectator_room(game_id),
                                )
                                await self._handle_game_abort(
                                    game_id,
                                    result.get("reason"),
                                )
                                self._state.werewolf_games.pop(game_id, None)
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
                                self._state.werewolf_games.pop(game_id, None)
                                continue

                            await self.broadcast_state(game_id)

                        except Exception as exc:
                            log.error(f"[Timeout] Error handling timeout for game {game_id}: {exc}")
                            import traceback
                            traceback.print_exc()

            except asyncio.CancelledError:
                log.info("Werewolf timeout checker stopped")
                break
            except Exception as exc:
                log.error(f"[Timeout] Error in werewolf timeout checker: {exc}")
