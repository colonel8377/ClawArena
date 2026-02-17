"""Socket.IO service for matchmaking events."""

from decimal import Decimal

from backend.constant.texas import TEXAS_FIXED_BUY_IN_CHIPS, TEXAS_FIXED_ENTRY_FEE_TOKENS
from backend.constant.socket_error import SocketError, emit_error
from backend.constant.werewolf import WEREWOLF_ENTRY_FEE
from backend.database.redis_manager import redis_manager
from backend.database.persistence_manager import persistence_manager
from backend.games.texas import create_texas_game
from backend.games.texas.matchmaker import TexasMatchmaker
from backend.games.werewolf.matchmaker import WerewolfMatchmaker
from backend.games.werewolf.werewolf_game import WerewolfGame
from backend.services.account_service import (
    get_balance,
    lock_balance,
    unlock_balance,
)
from backend.services.common_socket_service import reject_if_read_only
from backend.utils import log


class MatchmakingSocketService:
    def __init__(self, sio, state, texas_service, werewolf_service) -> None:
        self._sio = sio
        self._state = state
        self._texas_service = texas_service
        self._werewolf_service = werewolf_service

    async def _ensure_sufficient_balance(
        self,
        player_id: str,
        required_amount: Decimal,
    ) -> None:
        try:
            available_tokens = await get_balance(player_id)
        except Exception as exc:
            raise SocketError(f"Balance check failed: {str(exc)}") from exc

        if available_tokens < required_amount:
            raise SocketError(
                "Insufficient balance for matchmaking entry fee. "
                f"Required: {str(required_amount)} tokens, "
                f"Available: {str(available_tokens)}"
            )

    async def _resolve_join_player(self, sid: str):
        session = self._state.player_sessions.get(sid)
        if not session or not session.authenticated:
            raise SocketError("Not authenticated")

        player_id = session.player_id
        if not player_id:
            raise SocketError("Player ID not found in session")

        player_name = session.player_name or f"Player{player_id[:5]}"
        return player_id, player_name

    def _ensure_matchmaker(self, attr_name: str, factory):
        matchmaker = getattr(self._state, attr_name)
        if matchmaker is None:
            matchmaker = factory()
            setattr(self._state, attr_name, matchmaker)
            matchmaker.start()
        return matchmaker

    async def _join_queue_and_emit(
        self,
        *,
        matchmaker,
        sid: str,
        player_id: str,
        player_name: str,
        amount: Decimal,
        joined_event: str,
        build_payload,
        already_in_queue_message: str,
    ) -> None:
        added = await matchmaker.add_player(sid, player_id, player_name, amount)
        if not added:
            raise SocketError(already_in_queue_message)

        queue_info = matchmaker.get_queue_info()
        await self._sio.emit(joined_event, build_payload(queue_info), room=sid)

    async def _join_matchmaking(
        self,
        *,
        sid: str,
        queue_key: str,
        amount: Decimal,
        action_name: str,
        ensure_matchmaker,
        joined_event: str,
        build_payload,
        already_in_queue_message: str,
    ) -> None:
        if await reject_if_read_only(self._sio, self._state, sid, action_name):
            return

        player_id, player_name = await self._resolve_join_player(sid)
        await self._ensure_sufficient_balance(player_id, amount)

        lock_key = f"matchmaking:join:{queue_key}:{player_id}"
        try:
            async with redis_manager.lock(lock_key, timeout=5):
                matchmaker = ensure_matchmaker()
                await self._join_queue_and_emit(
                    matchmaker=matchmaker,
                    sid=sid,
                    player_id=player_id,
                    player_name=player_name,
                    amount=amount,
                    joined_event=joined_event,
                    build_payload=build_payload,
                    already_in_queue_message=already_in_queue_message,
                )
        except RuntimeError as exc:
            raise SocketError(f"Matchmaking join locked or unavailable: {str(exc)}") from exc

    async def _leave_matchmaking(
        self,
        *,
        sid: str,
        matchmaker,
        not_initialized_message: str,
        not_in_queue_message: str,
        left_event: str,
        left_payload: dict,
    ) -> None:
        if matchmaker is None:
            raise SocketError(not_initialized_message)

        if await matchmaker.remove_player(sid):
            await self._sio.emit(left_event, left_payload, room=sid)
            return
        raise SocketError(not_in_queue_message)

    async def _emit_matchmaking_status(
        self,
        *,
        sid: str,
        matchmaker,
        status_event: str,
    ) -> None:
        if matchmaker is None:
            await self._sio.emit(
                status_event,
                {"queue_size": 0, "in_queue": False, "is_running": False},
                room=sid,
            )
            return

        queue_info = matchmaker.get_queue_info()
        in_queue = matchmaker.is_player_in_queue(sid)
        await self._sio.emit(
            status_event,
            {
                "queue_size": queue_info["size"],
                "oldest_wait_time": queue_info["oldest_wait_time"],
                "average_wait_time": queue_info["average_wait_time"],
                "in_queue": in_queue,
                "is_running": matchmaker.is_running(),
            },
            room=sid,
        )

    async def _emit_to_players(self, players, event: str, payload: dict) -> None:
        for player in players:
            await self._sio.emit(event, payload, room=player.sid)

    async def _persist_game_created(
        self,
        *,
        game_id: str,
        game_type: str,
        entry_fee: Decimal,
        log_prefix: str,
    ) -> None:
        try:
            await persistence_manager.on_game_created(
                game_id=game_id,
                game_type=game_type,
                entry_fee=entry_fee,
            )
        except Exception as exc:
            log.error(f"[{log_prefix}] Persist game create failed: {exc}")

    async def _persist_player_joined(
        self,
        *,
        game_id: str,
        player_id: str,
        sid: str,
        player_name: str,
        log_prefix: str,
    ) -> None:
        try:
            await persistence_manager.on_player_joined(
                game_id=game_id,
                player_id=player_id,
                socket_sid=sid,
                nickname=player_name,
            )
        except Exception as exc:
            log.error(f"[{log_prefix}] Persist player join failed: {exc}")

    async def _bind_player_to_room(self, *, sid: str, room_id: str, bind_session) -> None:
        if sid in self._state.player_sessions:
            bind_session(sid, room_id)
        await self._sio.enter_room(sid, room_id)

    async def _emit_seat_failed_and_unlock(
        self,
        *,
        player,
        unlock_single_player,
        unlock_description: str,
        seat_failed_message: str,
    ) -> None:
        await unlock_single_player(player, unlock_description)
        await emit_error(self._sio, seat_failed_message, room=player.sid)

    async def _finalize_seated_player(
        self,
        *,
        game_id: str,
        player,
        bind_session,
        log_prefix: str,
    ) -> None:
        await self._persist_player_joined(
            game_id=game_id,
            player_id=player.player_id,
            sid=player.sid,
            player_name=player.player_name,
            log_prefix=log_prefix,
        )
        await self._bind_player_to_room(
            sid=player.sid,
            room_id=game_id,
            bind_session=bind_session,
        )

    async def _seat_players(
        self,
        *,
        players,
        game_id: str,
        pre_seat,
        add_player,
        unlock_single_player,
        unlock_description: str,
        seat_failed_message: str,
        bind_session,
        log_prefix: str,
    ):
        seated_players = []
        for player in players:
            if pre_seat is not None:
                pre_seat_ok = await pre_seat(player)
                if not pre_seat_ok:
                    continue

            add_ok = add_player(player)
            if not add_ok:
                await self._emit_seat_failed_and_unlock(
                    player=player,
                    unlock_single_player=unlock_single_player,
                    unlock_description=unlock_description,
                    seat_failed_message=seat_failed_message,
                )
                continue

            await self._finalize_seated_player(
                game_id=game_id,
                player=player,
                bind_session=bind_session,
                log_prefix=log_prefix,
            )
            seated_players.append(player)

        return seated_players

    async def _rollback_seated_players(
        self,
        *,
        seated_players,
        remove_from_game,
        unlock_players,
        clear_session_binding,
        remove_runtime_game,
    ) -> None:
        for player in seated_players:
            remove_from_game(player.sid)
        await unlock_players(seated_players)
        for player in seated_players:
            if player.sid in self._state.player_sessions:
                clear_session_binding(player.sid, None)
        remove_runtime_game()

    async def _emit_match_started(self, *, players, event: str, payload: dict) -> None:
        await self._emit_to_players(players, event, payload)

    async def _on_texas_matchmaking_fallback(self, players, target_size: int) -> None:
        await self._emit_to_players(
            players,
            "texas_matchmaking_fallback_warning",
            {
                "message": f"Starting {target_size}-player table after wait timeout",
                "player_count": target_size,
                "preferred_target": TexasMatchmaker.PREFERRED_GAME_SIZE,
                "full_ring_target": TexasMatchmaker.FULL_RING_SIZE,
            },
        )

    async def _unlock_texas_players(self, players, table_id: str, description: str) -> None:
        for player in players:
            try:
                await unlock_balance(
                    player.player_id,
                    player.buy_in_tokens,
                    description=description,
                )
            except Exception:
                pass

    async def _seat_texas_players(self, table, table_id: str, players):
        async def pre_seat(player) -> bool:
            try:
                await lock_balance(
                    player.player_id,
                    player.buy_in_tokens,
                )
                return True
            except Exception as exc:
                await emit_error(
                    self._sio,
                    f"Insufficient balance or lock failed: {str(exc)}",
                    room=player.sid,
                )
                return False

        return await self._seat_players(
            players=players,
            game_id=table_id,
            pre_seat=pre_seat,
            add_player=lambda player: table.add_player(
                player.sid,
                player.player_id,
                nickname=player.player_name,
                buy_in_tokens=player.buy_in_tokens,
            ),
            unlock_single_player=lambda p, desc: self._unlock_texas_players([p], table_id, desc),
            unlock_description="Texas matchmaking seat allocation failed",
            seat_failed_message="Could not join auto-matched poker table",
            bind_session=self._state.player_sessions.set_table_id,
            log_prefix="TexasMatchmaking",
        )

    async def _cleanup_failed_texas_match(self, table, table_id: str, seated_players) -> None:
        await self._rollback_seated_players(
            seated_players=seated_players,
            remove_from_game=table.remove_player,
            unlock_players=lambda players: self._unlock_texas_players(
                players,
                table_id,
                "Texas matchmaking cancelled after seat failures",
            ),
            clear_session_binding=self._state.player_sessions.set_table_id,
            remove_runtime_game=lambda: self._state.remove_poker_table(table_id),
        )

    async def _on_texas_game_matched(self, players, game_size: int) -> None:
        import uuid

        async with redis_manager.lock("matchmaking:texas:create_table", timeout=10):
            table_id = f"poker_auto_{uuid.uuid4().hex[:8]}"
            table = create_texas_game(table_id)
            self._state.register_poker_table(table_id, table)

            await self._persist_game_created(
                game_id=table_id,
                game_type="texas",
                entry_fee=TEXAS_FIXED_ENTRY_FEE_TOKENS,
                log_prefix="TexasMatchmaking",
            )

            seated_players = await self._seat_texas_players(table, table_id, players)

            if len(seated_players) < 2:
                await self._cleanup_failed_texas_match(table, table_id, seated_players)
                return

            hand_started = table.start_game()
            if hand_started:
                self._texas_service._create_task(
                    table.save_checkpoint("hand_start"),
                    name=f"checkpoint_hand_start_{table_id}",
                )

            await self._emit_match_started(
                players=seated_players,
                event="texas_matchmaking_game_started",
                payload={
                    "table_id": table_id,
                    "player_count": len(seated_players),
                    "requested_group_size": game_size,
                    "hand_started": hand_started,
                },
            )

            await self._texas_service.broadcast_state(table_id)

    async def _broadcast_werewolf_state(self, game_id: str) -> None:
        game = self._state.werewolf_games.get(game_id)
        if not game:
            return

        await self._sio.emit("game_state", game.to_dict(), room=game_id)

    async def _on_matchmaking_fallback(self, players, target_size: int) -> None:
        await self._emit_to_players(
            players,
            "matchmaking_fallback_warning",
            {
                "message": (
                    f"Starting {target_size}-player game (waited 30+ seconds, not enough for 9-player)"
                ),
                "player_count": target_size,
                "original_target": 9,
            },
        )

    async def _unlock_werewolf_players(self, players, entry_fee: Decimal, description: str) -> None:
        for player in players:
            try:
                await unlock_balance(
                    player.player_id,
                    entry_fee,
                    description=description,
                )
            except Exception:
                pass

    async def _collect_eligible_werewolf_players(self, players):
        entry_fee = WEREWOLF_ENTRY_FEE
        eligible_players = []
        for player in players:
            try:
                available_balance = await get_balance(player.player_id)
                if available_balance < entry_fee:
                    await emit_error(
                        self._sio,
                        (
                            "Insufficient balance for werewolf matchmaking entry fee. "
                            f"Required: {str(entry_fee)} tokens, "
                            f"Available: {str(available_balance)}"
                        ),
                        room=player.sid,
                    )
                    continue
            except Exception as exc:
                await emit_error(
                    self._sio,
                    f"Balance check failed: {str(exc)}",
                    room=player.sid,
                )
                continue

            try:
                await lock_balance(
                    player.player_id,
                    entry_fee,
                )
            except Exception as exc:
                await emit_error(
                    self._sio,
                    f"Insufficient balance or lock failed: {str(exc)}",
                    room=player.sid,
                )
                continue

            eligible_players.append(player)
        return eligible_players

    async def _seat_werewolf_players(self, game, game_id: str, players, entry_fee: Decimal):
        return await self._seat_players(
            players=players,
            game_id=game_id,
            pre_seat=None,
            add_player=lambda player: game.add_player(
                player.sid,
                player.player_id,
                nickname=player.player_name,
            ),
            unlock_single_player=lambda p, desc: self._unlock_werewolf_players([p], entry_fee, desc),
            unlock_description="Werewolf matchmaking seat allocation failed",
            seat_failed_message="Could not join auto-matched werewolf game",
            bind_session=self._state.player_sessions.set_game_id,
            log_prefix="Matchmaking",
        )

    async def _on_game_matched(self, players, game_size: int) -> None:
        import uuid

        if not players:
            return

        async with redis_manager.lock("matchmaking:werewolf:create_game", timeout=10):
            entry_fee = WEREWOLF_ENTRY_FEE

            eligible_players = await self._collect_eligible_werewolf_players(players)

            if len(eligible_players) < game_size:
                await self._unlock_werewolf_players(
                    eligible_players,
                    entry_fee,
                    "Werewolf matchmaking canceled",
                )
                return

            game_id = f"ww_auto_{uuid.uuid4().hex[:8]}"
            game = WerewolfGame(
                game_id=game_id,
                entry_fee=entry_fee,
            )
            self._state.register_werewolf_game(game_id, game)

            await self._persist_game_created(
                game_id=game_id,
                game_type="werewolf",
                entry_fee=entry_fee,
                log_prefix="Matchmaking",
            )

            seated_players = await self._seat_werewolf_players(
                game,
                game_id,
                eligible_players,
                entry_fee,
            )

            if len(seated_players) < 2:
                await self._rollback_seated_players(
                    seated_players=seated_players,
                    remove_from_game=game.remove_player,
                    unlock_players=lambda players: self._unlock_werewolf_players(
                        players,
                        entry_fee,
                        "Werewolf matchmaking canceled after seat failures",
                    ),
                    clear_session_binding=self._state.player_sessions.set_game_id,
                    remove_runtime_game=lambda: self._state.remove_werewolf_game(game_id),
                )
                return

            game_started = game.start_game()
            if game_started:
                await self._werewolf_service._persist_game_start(game)
                await self._broadcast_werewolf_state(game_id)

            await persistence_manager.on_game_started(game_id)
            await persistence_manager.on_game_snapshot(
                game_id=game_id,
                game_type="werewolf",
                state_snapshot=game.to_dict(),
                current_phase=game.phase.value,
                initial_state=game.to_dict(),
            )

            await self._emit_match_started(
                players=seated_players,
                event="matchmaking_game_started",
                payload={"game_id": game_id, "player_count": game_size},
            )

            await self._werewolf_service.broadcast_state(game_id)

    async def join_texas_matchmaking(self, sid: str) -> None:
        buy_in_tokens = TEXAS_FIXED_ENTRY_FEE_TOKENS
        await self._join_matchmaking(
            sid=sid,
            queue_key="texas",
            amount=buy_in_tokens,
            action_name="join_texas_matchmaking",
            ensure_matchmaker=lambda: self._ensure_matchmaker(
                "texas_matchmaker",
                lambda: TexasMatchmaker(
                    game_start_callback=self._on_texas_game_matched,
                    fallback_warning_callback=self._on_texas_matchmaking_fallback,
                ),
            ),
            joined_event="texas_matchmaking_joined",
            build_payload=lambda queue_info: {
                "queue_size": queue_info["size"],
                "buy_in_tokens": str(buy_in_tokens),
                "buy_in_chips": TEXAS_FIXED_BUY_IN_CHIPS,
                "message": "Joined Texas matchmaking queue",
            },
            already_in_queue_message="Already in Texas matchmaking queue",
        )

    async def leave_texas_matchmaking(self, sid: str) -> None:
        await self._leave_matchmaking(
            sid=sid,
            matchmaker=self._state.texas_matchmaker,
            not_initialized_message="Texas matchmaker not initialized",
            not_in_queue_message="Not in Texas matchmaking queue",
            left_event="texas_matchmaking_left",
            left_payload={"message": "Left Texas matchmaking queue"},
        )

    async def get_texas_matchmaking_status(self, sid: str) -> None:
        await self._emit_matchmaking_status(
            sid=sid,
            matchmaker=self._state.texas_matchmaker,
            status_event="texas_matchmaking_status",
        )

    async def join_werewolf_matchmaking(
        self,
        sid: str
    ) -> None:
        entry_fee = WEREWOLF_ENTRY_FEE
        await self._join_matchmaking(
            sid=sid,
            queue_key="werewolf",
            amount=entry_fee,
            action_name="join_werewolf_matchmaking",
            ensure_matchmaker=lambda: self._ensure_matchmaker(
                "werewolf_matchmaker",
                lambda: WerewolfMatchmaker(
                    game_start_callback=self._on_game_matched,
                    fallback_warning_callback=self._on_matchmaking_fallback,
                ),
            ),
            joined_event="matchmaking_joined",
            build_payload=lambda queue_info: {
                "queue_size": queue_info["size"],
                "entry_fee": str(entry_fee),
                "message": "Joined matchmaking queue",
            },
            already_in_queue_message="Already in matchmaking queue",
        )

    async def leave_werewolf_matchmaking(self, sid: str) -> None:
        await self._leave_matchmaking(
            sid=sid,
            matchmaker=self._state.werewolf_matchmaker,
            not_initialized_message="Matchmaker not initialized",
            not_in_queue_message="Not in matchmaking queue",
            left_event="matchmaking_left",
            left_payload={"message": "Left matchmaking queue"},
        )

    async def get_werewolf_matchmaking_status(self, sid: str) -> None:
        await self._emit_matchmaking_status(
            sid=sid,
            matchmaker=self._state.werewolf_matchmaker,
            status_event="matchmaking_status",
        )
