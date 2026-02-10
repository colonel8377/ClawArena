"""Matchmaking Socket.IO handlers and helpers."""

import asyncio
from decimal import Decimal

from backend.config.arena_config import TEXAS_CHIP_TO_TOKEN_RATIO
from backend.database.persistence_manager import persistence_manager
from backend.economy.account import get_balance, lock_balance, unlock_balance
from backend.games.texas import create_texas_game
from backend.games.texas.matchmaker import TexasMatchmaker
from backend.games.werewolf.matchmaker import WerewolfMatchmaker
from backend.games.werewolf.werewolf_game import WerewolfGame
from backend.socket_handlers.common import _reject_if_read_only


async def on_texas_matchmaking_fallback(sio, players, target_size: int) -> None:
    """Warn players when Texas matchmaking downgrades the target table size."""
    for player in players:
        await sio.emit(
            "texas_matchmaking_fallback_warning",
            {
                "message": f"Starting {target_size}-player table after wait timeout",
                "player_count": target_size,
                "preferred_target": TexasMatchmaker.PREFERRED_GAME_SIZE,
                "full_ring_target": TexasMatchmaker.FULL_RING_SIZE,
            },
            room=player.sid,
        )


async def on_texas_game_matched(sio, state, players, game_size: int, texas_service) -> None:
    """Create a Texas Hold'em table once matchmaking fills."""
    import uuid

    eligible_players = []
    for queued_player in players:
        try:
            current_balance = await get_balance(queued_player.wallet_address)
            if current_balance < queued_player.buy_in_tokens:
                await sio.emit(
                    "error",
                    {
                        "message": (
                            "Insufficient balance for matchmaking buy-in. "
                            f"Required: {float(queued_player.buy_in_tokens)} tokens, "
                            f"Available: {float(current_balance)}"
                        )
                    },
                    room=queued_player.sid,
                )
                continue

            eligible_players.append(queued_player)
        except Exception as exc:
            await sio.emit(
                "error",
                {"message": f"Matchmaking buy-in lock failed: {str(exc)}"},
                room=queued_player.sid,
            )

    if len(eligible_players) < 2:
        return

    table_id = f"poker_auto_{uuid.uuid4().hex[:8]}"
    table = create_texas_game(table_id)
    state.poker_tables[table_id] = table

    try:
        await persistence_manager.on_game_created(
            game_id=table_id,
            game_type="texas",
            entry_fee=Decimal("0"),
        )
    except Exception as exc:
        print(f"[TexasMatchmaking] Persist game create failed: {exc}")

    seated_players = []
    for player in eligible_players:
        add_ok = table.add_player(
            player.sid,
            player.wallet_address,
            nickname=player.nickname,
            buy_in_tokens=player.buy_in_tokens,
        )
        if not add_ok:
            await sio.emit(
                "error",
                {"message": "Could not join auto-matched poker table"},
                room=player.sid,
            )
            continue

        try:
            await lock_balance(
                player.wallet_address,
                player.buy_in_tokens,
                game_session_id=table_id,
            )
        except Exception as exc:
            table.remove_player(player.sid)
            await sio.emit(
                "error",
                {"message": f"Failed to finalize matchmaking seat lock: {str(exc)}"},
                room=player.sid,
            )
            continue

        try:
            await persistence_manager.on_player_joined(
                game_id=table_id,
                player_id=player.wallet_address,
                socket_sid=player.sid,
                nickname=player.nickname,
            )
        except Exception as exc:
            print(f"[TexasMatchmaking] Persist player join failed: {exc}")

        if player.sid in state.player_sessions:
            state.player_sessions[player.sid]["table_id"] = table_id

        await sio.enter_room(player.sid, table_id)
        seated_players.append(player)

    if len(seated_players) < 2:
        for player in seated_players:
            table.remove_player(player.sid)
            try:
                await unlock_balance(
                    player.wallet_address,
                    player.buy_in_tokens,
                    game_session_id=table_id,
                    description="Texas matchmaking cancelled after seat failures",
                )
            except Exception:
                pass
            if player.sid in state.player_sessions:
                state.player_sessions[player.sid]["table_id"] = None
        state.poker_tables.pop(table_id, None)
        return

    hand_started = table.start_game()
    if hand_started:
        asyncio.create_task(table.save_checkpoint("hand_start"))

    for player in seated_players:
        await sio.emit(
            "texas_matchmaking_game_started",
            {
                "table_id": table_id,
                "player_count": len(seated_players),
                "requested_group_size": game_size,
                "hand_started": hand_started,
            },
            room=player.sid,
        )

    await texas_service.broadcast_state(table_id)


async def broadcast_werewolf_state(sio, state, game_id: str) -> None:
    """Broadcast the current game state to all players in the game."""
    game = state.werewolf_games.get(game_id)
    if not game:
        return

    await sio.emit("game_state", game.to_dict(), room=game_id)


async def on_matchmaking_fallback(sio, players, target_size: int) -> None:
    """Warn werewolf players when matchmaking downgrades from 9 players."""
    for player in players:
        await sio.emit(
            "matchmaking_fallback_warning",
            {
                "message": (
                    f"Starting {target_size}-player game (waited 30+ seconds, not enough for 9-player)"
                ),
                "player_count": target_size,
                "original_target": 9,
            },
            room=player.sid,
        )


async def on_game_matched(sio, state, players, game_size: int, werewolf_service) -> None:
    """Create a werewolf game once matchmaking fills."""
    import uuid

    if not players:
        return

    entry_fee = getattr(players[0], "entry_fee", Decimal("0"))
    if entry_fee <= 0:
        for player in players:
            await sio.emit(
                "error",
                {"message": "Free werewolf rooms are not allowed"},
                room=player.sid,
            )
        return

    eligible_players = []
    for player in players:
        player_entry_fee = getattr(player, "entry_fee", entry_fee)
        if player_entry_fee != entry_fee:
            await sio.emit(
                "error",
                {"message": f"Entry fee mismatch. Expected {float(entry_fee)} tokens."},
                room=player.sid,
            )
            continue

        try:
            current_balance = await get_balance(player.wallet_address)
            if current_balance < entry_fee:
                await sio.emit(
                    "error",
                    {
                        "message": (
                            "Insufficient balance for werewolf matchmaking entry fee. "
                            f"Required: {float(entry_fee)} tokens, "
                            f"Available: {float(current_balance)}"
                        )
                    },
                    room=player.sid,
                )
                continue
        except Exception as exc:
            await sio.emit(
                "error",
                {"message": f"Failed to verify entry fee balance: {str(exc)}"},
                room=player.sid,
            )
            continue

        eligible_players.append(player)

    if len(eligible_players) < WerewolfMatchmaker.MIN_PLAYERS:
        return

    game_id = f"werewolf_auto_{uuid.uuid4().hex[:8]}"
    game = WerewolfGame(game_id, entry_fee=entry_fee)
    state.werewolf_games[game_id] = game

    await persistence_manager.on_game_created(
        game_id=game_id,
        game_type="werewolf",
        entry_fee=entry_fee,
    )

    seated_players = []
    for player in eligible_players:
        if not game.add_player(player.sid, player.wallet_address, nickname=player.nickname):
            await sio.emit(
                "error",
                {"message": "Could not join auto-matched werewolf game"},
                room=player.sid,
            )
            continue

        try:
            await lock_balance(player.wallet_address, entry_fee, game_session_id=game_id)
        except Exception as exc:
            game.remove_player(player.sid)
            await sio.emit(
                "error",
                {"message": f"Failed to lock werewolf entry fee: {str(exc)}"},
                room=player.sid,
            )
            continue

        await persistence_manager.on_player_joined(
            game_id=game_id,
            player_id=player.wallet_address,
            socket_sid=player.sid,
            nickname=player.nickname,
            entry_paid=entry_fee,
        )

        if player.sid in state.player_sessions:
            state.player_sessions[player.sid]["game_id"] = game_id

        await sio.enter_room(player.sid, game_id)
        seated_players.append(player)

    if len(seated_players) < WerewolfMatchmaker.MIN_PLAYERS:
        for player in seated_players:
            try:
                await unlock_balance(
                    player.wallet_address,
                    entry_fee,
                    game_session_id=game_id,
                    description="Werewolf matchmaking cancelled after seat failures",
                )
            except Exception:
                pass
            if player.sid in state.player_sessions:
                state.player_sessions[player.sid]["game_id"] = None
            await sio.leave_room(player.sid, game_id)
        state.werewolf_games.pop(game_id, None)
        return

    game.start_game()

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

    for player in seated_players:
        await sio.emit(
            "matchmaking_game_started",
            {"game_id": game_id, "player_count": game_size},
            room=player.sid,
        )

    await broadcast_werewolf_state(sio, state, game_id)


def register_matchmaking_handlers(sio, state) -> None:
    """Register matchmaking Socket.IO event handlers."""

    @sio.event
    async def join_texas_matchmaking(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "join_texas_matchmaking"):
                return

            if sid not in state.player_sessions or not state.player_sessions[sid]["authenticated"]:
                await sio.emit("error", {"message": "Not authenticated"}, room=sid)
                return

            payload = data or {}
            requested_name = str(payload.get("nickname", "")).strip()
            player_id = state.player_sessions[sid]["player_id"]
            player_name = state.player_sessions[sid]["player_name"] or "Player"
            nickname = requested_name[:32] if requested_name else player_name

            if "tokens" in payload:
                buy_in_tokens = Decimal(str(payload["tokens"]))
            else:
                buy_in_chips = int(payload.get("chips", 1000))
                buy_in_tokens = Decimal(str(buy_in_chips)) * TEXAS_CHIP_TO_TOKEN_RATIO

            if buy_in_tokens <= 0:
                await sio.emit("error", {"message": "Invalid buy-in amount"}, room=sid)
                return

            if state.texas_matchmaker is None:
                async def _on_fallback(players, target_size):
                    await on_texas_matchmaking_fallback(sio, players, target_size)

                async def _on_matched(players, game_size):
                    await on_texas_game_matched(sio, state, players, game_size, texas_service)

                state.texas_matchmaker = TexasMatchmaker(
                    game_start_callback=_on_matched,
                    fallback_warning_callback=_on_fallback,
                )
                state.texas_matchmaker.start()

            if state.texas_matchmaker.add_player(sid, player_id, nickname, buy_in_tokens):
                queue_info = state.texas_matchmaker.get_queue_info()
                await sio.emit(
                    "texas_matchmaking_joined",
                    {
                        "queue_size": queue_info["size"],
                        "buy_in_tokens": float(buy_in_tokens),
                        "message": "Joined Texas matchmaking queue",
                    },
                    room=sid,
                )
            else:
                await sio.emit(
                    "error",
                    {"message": "Already in Texas matchmaking queue"},
                    room=sid,
                )

        except Exception as exc:
            await sio.emit(
                "error",
                {"message": f"Join Texas matchmaking failed: {str(exc)}"},
                room=sid,
            )

    @sio.event
    async def leave_texas_matchmaking(sid, data):
        try:
            if state.texas_matchmaker is None:
                await sio.emit(
                    "error",
                    {"message": "Texas matchmaker not initialized"},
                    room=sid,
                )
                return

            if state.texas_matchmaker.remove_player(sid):
                await sio.emit(
                    "texas_matchmaking_left",
                    {"message": "Left Texas matchmaking queue"},
                    room=sid,
                )
            else:
                await sio.emit(
                    "error",
                    {"message": "Not in Texas matchmaking queue"},
                    room=sid,
                )
        except Exception as exc:
            await sio.emit(
                "error",
                {"message": f"Leave Texas matchmaking failed: {str(exc)}"},
                room=sid,
            )

    @sio.event
    async def get_texas_matchmaking_status(sid, data):
        try:
            if state.texas_matchmaker is None:
                await sio.emit(
                    "texas_matchmaking_status",
                    {"queue_size": 0, "in_queue": False, "is_running": False},
                    room=sid,
                )
                return

            queue_info = state.texas_matchmaker.get_queue_info()
            in_queue = state.texas_matchmaker.is_player_in_queue(sid)
            await sio.emit(
                "texas_matchmaking_status",
                {
                    "queue_size": queue_info["size"],
                    "oldest_wait_time": queue_info["oldest_wait_time"],
                    "average_wait_time": queue_info["average_wait_time"],
                    "in_queue": in_queue,
                    "is_running": state.texas_matchmaker.is_running(),
                },
                room=sid,
            )
        except Exception as exc:
            await sio.emit(
                "error",
                {"message": f"Get Texas matchmaking status failed: {str(exc)}"},
                room=sid,
            )

    @sio.event
    async def join_matchmaking(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "join_matchmaking"):
                return

            if sid not in state.player_sessions or not state.player_sessions[sid]["authenticated"]:
                await sio.emit("error", {"message": "Not authenticated"}, room=sid)
                return

            payload = data or {}
            requested_name = str(payload.get("nickname", "")).strip()
            player_id = state.player_sessions[sid]["player_id"]
            player_name = state.player_sessions[sid]["player_name"] or "Player"
            nickname = requested_name[:32] if requested_name else player_name

            entry_fee = Decimal(str(payload.get("entry_fee", 0)))
            if entry_fee <= 0:
                await sio.emit(
                    "error",
                    {"message": "Werewolf matchmaking requires a positive entry fee"},
                    room=sid,
                )
                return

            if state.werewolf_matchmaker is None:
                async def _on_fallback(players, target_size):
                    await on_matchmaking_fallback(sio, players, target_size)

                async def _on_matched(players, game_size):
                    await on_game_matched(sio, state, players, game_size, werewolf_service)

                state.werewolf_matchmaker = WerewolfMatchmaker(
                    game_start_callback=_on_matched,
                    fallback_warning_callback=_on_fallback,
                )
                state.werewolf_matchmaker.start()

            if state.werewolf_matchmaker.get_queue_size() > 0:
                queued_fee = state.werewolf_matchmaker.queue[0].entry_fee
                if queued_fee != entry_fee:
                    await sio.emit(
                        "error",
                        {
                            "message": (
                                f"Entry fee mismatch. Current queue requires {float(queued_fee)} tokens."
                            )
                        },
                        room=sid,
                    )
                    return

            try:
                current_balance = await get_balance(player_id)
                if current_balance < entry_fee:
                    await sio.emit(
                        "error",
                        {
                            "message": (
                                "Insufficient balance for werewolf matchmaking entry fee. "
                                f"Required: {float(entry_fee)} tokens, "
                                f"Available: {float(current_balance)}"
                            )
                        },
                        room=sid,
                    )
                    return
            except Exception as exc:
                await sio.emit(
                    "error",
                    {"message": f"Balance check failed: {str(exc)}"},
                    room=sid,
                )
                return

            if state.werewolf_matchmaker.add_player(sid, player_id, nickname, entry_fee):
                queue_info = state.werewolf_matchmaker.get_queue_info()
                await sio.emit(
                    "matchmaking_joined",
                    {
                        "queue_size": queue_info["size"],
                        "entry_fee": float(entry_fee),
                        "message": "Joined matchmaking queue",
                    },
                    room=sid,
                )
            else:
                await sio.emit(
                    "error",
                    {"message": "Already in matchmaking queue"},
                    room=sid,
                )
        except Exception as exc:
            await sio.emit(
                "error",
                {"message": f"Join matchmaking failed: {str(exc)}"},
                room=sid,
            )

    @sio.event
    async def leave_matchmaking(sid, data):
        try:
            if state.werewolf_matchmaker is None:
                await sio.emit(
                    "error",
                    {"message": "Matchmaker not initialized"},
                    room=sid,
                )
                return

            if state.werewolf_matchmaker.remove_player(sid):
                await sio.emit(
                    "matchmaking_left",
                    {"message": "Left matchmaking queue"},
                    room=sid,
                )
            else:
                await sio.emit(
                    "error",
                    {"message": "Not in matchmaking queue"},
                    room=sid,
                )
        except Exception as exc:
            await sio.emit(
                "error",
                {"message": f"Leave matchmaking failed: {str(exc)}"},
                room=sid,
            )

    @sio.event
    async def get_matchmaking_status(sid, data):
        try:
            if state.werewolf_matchmaker is None:
                await sio.emit(
                    "matchmaking_status",
                    {"queue_size": 0, "in_queue": False, "is_running": False},
                    room=sid,
                )
                return

            queue_info = state.werewolf_matchmaker.get_queue_info()
            in_queue = state.werewolf_matchmaker.is_player_in_queue(sid)

            await sio.emit(
                "matchmaking_status",
                {
                    "queue_size": queue_info["size"],
                    "oldest_wait_time": queue_info["oldest_wait_time"],
                    "average_wait_time": queue_info["average_wait_time"],
                    "in_queue": in_queue,
                    "is_running": state.werewolf_matchmaker.is_running(),
                },
                room=sid,
            )
        except Exception as exc:
            await sio.emit(
                "error",
                {"message": f"Get matchmaking status failed: {str(exc)}"},
                room=sid,
            )
