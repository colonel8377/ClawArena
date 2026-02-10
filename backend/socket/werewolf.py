"""Werewolf Socket.IO handlers and helpers."""

import asyncio
from datetime import datetime
from decimal import Decimal
from typing import Optional

from config import WEREWOLF_PRIZE_MULTIPLIER
from database.models import TransactionType
from database.persistence_manager import persistence_manager
from database.redis_manager import redis_manager
from economy.account import add_balance, lock_balance, unlock_balance, get_balance
from games.werewolf.werewolf_game import WerewolfGame, WerewolfPhase
from socket.common import (
    _emit_werewolf_action_trace,
    _emit_werewolf_event,
    _emit_to_sids,
    _iter_reveal_spectators,
    _reject_if_read_only,
    _werewolf_spectator_room,
)


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


def _get_werewolf_settlement_lock(state, game_id: str) -> asyncio.Lock:
    lock = state.werewolf_settlement_locks.get(game_id)
    if lock is None:
        lock = asyncio.Lock()
        state.werewolf_settlement_locks[game_id] = lock
    return lock


async def _unlock_werewolf_entry_fees(game: WerewolfGame, game_id: str, description: str) -> None:
    for player in game.players:
        entry_fee = player.get("entry_fee_paid") or Decimal("0")
        if entry_fee <= 0:
            continue
        await unlock_balance(
            player["wallet_address"],
            entry_fee,
            game_session_id=game_id,
            description=description,
        )


async def handle_werewolf_game_end(state, sio, game_id: str, winners: list) -> None:
    lock = _get_werewolf_settlement_lock(state, game_id)
    async with lock:
        if game_id in state.werewolf_finalized_games:
            print(f"[WerewolfSettle] Game {game_id} already finalized")
            return
        state.werewolf_finalized_games[game_id] = "ended"

        game = state.werewolf_games.get(game_id)

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
                await _unlock_werewolf_entry_fees(
                    game,
                    game_id,
                    description="Werewolf entry fee principal unlock",
                )

            if game and winners:
                prize_per_winner = prize_pool / len(winners)
                print(
                    f"Werewolf game prize pool: {float(prize_pool)} tokens from {len(winners)} winners"
                )

                for winner_address in winners:
                    await add_balance(
                        winner_address,
                        prize_per_winner,
                        tx_type=TransactionType.GAME_WIN,
                        description="Werewolf game prize",
                    )
                    print(
                        f"Awarded {float(prize_per_winner)} tokens to winner: {winner_address[:8]}..."
                    )
            elif game and not winners:
                print("Werewolf game ended without winners, refunding entry fees")
            else:
                print("No game data found for prize distribution")
        except Exception as exc:
            print(f"Failed to handle prize distribution: {exc}")
            import traceback

            traceback.print_exc()


async def handle_werewolf_game_abort(
    state,
    sio,
    game_id: str,
    reason: Optional[str] = None,
) -> None:
    lock = _get_werewolf_settlement_lock(state, game_id)
    async with lock:
        if game_id in state.werewolf_finalized_games:
            print(f"[WerewolfSettle] Abort skipped; game {game_id} already finalized")
            return
        state.werewolf_finalized_games[game_id] = "aborted"

        game = state.werewolf_games.get(game_id)

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
                await _unlock_werewolf_entry_fees(
                    game,
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


async def broadcast_werewolf_state(sio, state, game_id: str) -> None:
    game = state.werewolf_games.get(game_id)
    if not game:
        return

    for player in game.players:
        await sio.emit("werewolf_state", game.get_game_state(player["sid"]), room=player["sid"])

    spectator_state = game.get_game_state(reveal_all=False)
    await sio.emit("werewolf_state", spectator_state, room=_werewolf_spectator_room(game_id))

    reveal_sids = list(_iter_reveal_spectators(state, "werewolf", game_id))
    if reveal_sids:
        reveal_state = game.get_game_state(reveal_all=True)
        await _emit_to_sids(sio, "werewolf_state", reveal_state, reveal_sids)

    asyncio.create_task(redis_manager.refresh_game_ttl(game_id))


def register_werewolf_handlers(sio, state) -> None:
    """Register Werewolf Socket.IO event handlers."""

    @sio.event
    async def create_werewolf_game(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "create_werewolf_game"):
                return

            if sid not in state.player_sessions or not state.player_sessions[sid]["authenticated"]:
                await sio.emit("error", {"message": "Not authenticated"}, room=sid)
                return

            payload = data or {}
            game_id = payload.get("game_id")
            entry_fee = Decimal(str(payload.get("entry_fee", 0)))

            if not game_id:
                await sio.emit("error", {"message": "game_id required"}, room=sid)
                return
            if entry_fee <= 0:
                await sio.emit(
                    "error",
                    {"message": "Werewolf games must require a positive entry fee"},
                    room=sid,
                )
                return

            async with redis_manager.lock(f"game_create:{game_id}"):
                if game_id in state.werewolf_games:
                    await sio.emit("error", {"message": "Game already exists"}, room=sid)
                    return

                state.werewolf_games[game_id] = WerewolfGame(game_id, entry_fee=entry_fee)

                await persistence_manager.on_game_created(
                    game_id=game_id,
                    game_type="werewolf",
                    entry_fee=entry_fee,
                )

                await redis_manager.save_game_core(
                    game_id,
                    state.werewolf_games[game_id].get_core_state(),
                    game_type="werewolf",
                )

            await sio.emit("werewolf_game_created", {"game_id": game_id}, room=sid)
        except Exception as exc:
            await sio.emit("error", {"message": f"Create game failed: {str(exc)}"}, room=sid)

    @sio.event
    async def join_werewolf_game(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "join_werewolf_game"):
                return

            if sid not in state.player_sessions or not state.player_sessions[sid]["authenticated"]:
                await sio.emit("error", {"message": "Not authenticated"}, room=sid)
                return

            payload = data or {}
            game_id = payload.get("game_id")
            nickname = state.player_sessions[sid]["player_name"] or "Player"

            if not game_id or game_id not in state.werewolf_games:
                await sio.emit("error", {"message": "Invalid game_id"}, room=sid)
                return

            player_id = state.player_sessions[sid]["player_id"]
            game = state.werewolf_games[game_id]

            if game.entry_fee <= 0:
                await sio.emit(
                    "error",
                    {"message": "Free werewolf rooms are not allowed"},
                    room=sid,
                )
                return

            try:
                current_balance = await get_balance(player_id)
                if current_balance < game.entry_fee:
                    await sio.emit(
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
                await sio.emit(
                    "error",
                    {"message": f"Balance check failed: {str(exc)}"},
                    room=sid,
                )
                return

            async with redis_manager.lock(f"game_join:{game_id}"):
                if not game.add_player(sid, player_id, nickname=nickname):
                    await sio.emit("error", {"message": "Could not join game"}, room=sid)
                    return

                try:
                    await lock_balance(player_id, game.entry_fee, game_session_id=game_id)
                except Exception as exc:
                    await sio.emit(
                        "error",
                        {"message": f"Failed to lock entry fee: {str(exc)}"},
                        room=sid,
                    )
                    game.remove_player(sid)
                    return

                state.player_sessions[sid]["game_id"] = game_id

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

            await sio.enter_room(sid, game_id)

            await sio.emit(
                "werewolf_joined",
                {
                    "game_id": game_id,
                    "player_id": player_id,
                    "player_name": nickname,
                },
                room=sid,
            )

            await broadcast_werewolf_state(sio, state, game_id)
        except Exception as exc:
            await sio.emit("error", {"message": f"Join werewolf game failed: {str(exc)}"}, room=sid)

    @sio.event
    async def start_werewolf_game(sid, data):
        try:
            if await _reject_if_read_only(sio, state, sid, "start_werewolf_game"):
                return

            game_id = (data or {}).get("game_id")
            if not game_id or game_id not in state.werewolf_games:
                await sio.emit("error", {"message": "Invalid game_id"}, room=sid)
                return

            game = state.werewolf_games[game_id]
            if not game.start_game():
                await sio.emit(
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

            await broadcast_werewolf_state(sio, state, game_id)
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

            if not game_id or game_id not in state.werewolf_games:
                await sio.emit("error", {"message": "Invalid game_id"}, room=sid)
                return

            if not action:
                await sio.emit("error", {"message": "Action required"}, room=sid)
                return

            game = state.werewolf_games[game_id]

            if action not in ["chat", "wolf_chat"]:
                await _emit_werewolf_event(
                    sio,
                    game_id,
                    "player_thinking",
                    {"game_id": game_id, "player_sid": sid, "action_type": action},
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
                await sio.emit("error", error_payload, room=sid)
                return

            await sio.emit("werewolf_action_result", result, room=sid)
            await _emit_werewolf_action_trace(
                sio,
                state,
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
                        await sio.emit("wolf_chat_message", result.get("chat"), room=wolf_sid)

                reveal_sids = list(_iter_reveal_spectators(state, "werewolf", game_id))
                await _emit_to_sids(sio, "wolf_chat_message", result.get("chat"), reveal_sids)
            elif action == "chat":
                await _emit_werewolf_event(sio, game_id, "chat_message", result.get("chat"))
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

                await _emit_werewolf_event(
                    sio,
                    game_id,
                    "werewolf_phase_change",
                    {
                        "phase": new_phase,
                        "day_count": phase_result.get("day_count"),
                        "deaths": phase_result.get("deaths", []),
                        "eliminated": phase_result.get("eliminated"),
                        "game_over": phase_result.get("game_over", False),
                        "winners": phase_result.get("winners", []),
                    },
                )

                if phase_result.get("game_over"):
                    await handle_werewolf_game_end(state, sio, game_id, phase_result.get("winners", []))

            await broadcast_werewolf_state(sio, state, game_id)
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
            if not game_id or game_id not in state.werewolf_games:
                await sio.emit("error", {"message": "Invalid game_id"}, room=sid)
                return

            game = state.werewolf_games[game_id]
            old_phase = game.phase.value
            result = game.advance_phase()
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

            await _emit_werewolf_event(sio, game_id, "werewolf_phase_change", result)

            if game.is_game_over():
                winners = game.get_winners()
                await handle_werewolf_game_end(state, sio, game_id, winners)

            await broadcast_werewolf_state(sio, state, game_id)
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