import asyncio
import os
import random
import time
from typing import Any, Dict

from shared import (
    Player,
    _err,
    _event_parts,
    _ok_data,
    attach_basic_handlers,
    log_system,
    new_action_id,
    _log,
)

GAME_TYPE_TEXAS = 2
RAISE_CHANCE = float(os.getenv("TEXAS_RAISE_CHANCE", "0.01"))
CHAT_CHANCE = float(os.getenv("TEXAS_CHAT_CHANCE", "1"))
PLAY_HANDS = int(os.getenv("TEXAS_HANDS", "8"))
FOLD_CHANCE = float(os.getenv("TEXAS_FOLD_CHANCE", "0"))
EDGE_CASES = os.getenv("TEXAS_EDGE_CASES", "0").lower() not in {"0", "false", "no", "off"}
REFRESH_MIN_SECONDS = float(os.getenv("TEXAS_REFRESH_MIN_SECONDS", "6.5"))
REFRESH_DELAY_SECONDS = float(os.getenv("TEXAS_REFRESH_DELAY_SECONDS", "0.1"))
HAND_RESULT_PAUSE_SECONDS = float(os.getenv("TEXAS_HAND_RESULT_PAUSE_SECONDS", "3"))
SETTLEMENT_PAUSE_SECONDS = float(os.getenv("TEXAS_SETTLEMENT_PAUSE_SECONDS", "10"))

_HAND_COUNTS: Dict[int, int] = {}
_VOTE_END_SENT: Dict[int, bool] = {}
_LAST_TURN_SIGNATURE: Dict[int, tuple] = {}
_RAISE_USED: Dict[tuple[int, int, str], bool] = {}
_LAST_REFRESH_AT: Dict[int, float] = {}
_HAND_RESULT_SEEN: Dict[tuple[int, int], bool] = {}


async def _request_state_refresh(player: Player) -> None:
    if not player.room_id or not player.agent_id:
        return
    now = time.monotonic()
    last = _LAST_REFRESH_AT.get(player.agent_id, 0.0)
    if now - last < REFRESH_MIN_SECONDS:
        return
    _LAST_REFRESH_AT[player.agent_id] = now
    await asyncio.sleep(REFRESH_DELAY_SECONDS)
    if not player.socket or not player.socket.connected:
        return
    try:
        await player.call("room:join", {"room_id": player.room_id, "role": 1})
    except Exception:
        pass


def _coerce_int_map(value: Any) -> Dict[int, int] | Any:
    if not isinstance(value, dict):
        return value
    result: Dict[int, int] = {}
    for key, val in value.items():
        try:
            result[int(key)] = int(val)
        except (TypeError, ValueError):
            continue
    return result


def _coerce_bool_map(value: Any) -> Dict[int, bool] | Any:
    if not isinstance(value, dict):
        return value
    result: Dict[int, bool] = {}
    for key, val in value.items():
        try:
            result[int(key)] = bool(val)
        except (TypeError, ValueError):
            continue
    return result


def _normalize_state(state: Dict[str, Any]) -> Dict[str, Any]:
    if not state:
        return {}
    normalized = dict(state)
    if normalized.get("actor_id") is not None:
        try:
            normalized["actor_id"] = int(normalized["actor_id"])
        except (TypeError, ValueError):
            normalized["actor_id"] = None
    if "bets" in normalized:
        normalized["bets"] = _coerce_int_map(normalized.get("bets"))
    if "stacks" in normalized:
        normalized["stacks"] = _coerce_int_map(normalized.get("stacks"))
    if "statuses" in normalized:
        normalized["statuses"] = _coerce_bool_map(normalized.get("statuses"))
    for key in ("eligible_players", "in_hand_players", "active_players"):
        if key in normalized and isinstance(normalized.get(key), list):
            players = []
            for item in normalized[key]:
                try:
                    players.append(int(item))
                except (TypeError, ValueError):
                    continue
            normalized[key] = players
    return normalized


def _get_state(game_state: Dict[str, Any]) -> Dict[str, Any]:
    if not game_state:
        return {}
    return _normalize_state(game_state.get("state") or {})


def _merge_phase_state(data: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(data, dict) and "event_type" in data and isinstance(data.get("payload"), dict):
        data = data.get("payload") or {}
    payload = data.get("payload")
    if not isinstance(payload, dict):
        payload = {}
    if not payload and isinstance(data, dict):
        payload = data
    if "actor_id" not in payload and data.get("actor_id") is not None:
        payload["actor_id"] = data.get("actor_id")
    if "phase" not in payload and data.get("phase") is not None:
        payload["phase"] = data.get("phase")
    return _normalize_state(payload)


def _winner_summary(payouts: Dict[Any, Any], players: list[Player]) -> str:
    if not payouts:
        return "winners=none"
    id_to_name = {int(p.agent_id): p.name for p in players if p.agent_id is not None}
    winners: list[str] = []
    for raw_id, amount in payouts.items():
        try:
            pid = int(raw_id)
        except (TypeError, ValueError):
            pid = raw_id
        name = id_to_name.get(pid, str(pid))
        winners.append(f"{name}+{amount}")
    return "winners=" + ", ".join(winners)


async def _send_edge_cases(player: Player, state: Dict[str, Any]) -> None:
    if not player.room_id:
        return

    if state.get("actor_id") != player.agent_id:
        return

    # Invalid channel for Texas (should be room-only).
    payload = {"room_id": player.room_id, "channel": "day", "content": "invalid channel", "action_id": new_action_id()}
    try:
        res = await player.call("room:chat:send", payload)
        err = _err(res)
        if err:
            _log(player, f"edge chat invalid_channel => {err.get('code')} {err.get('message')}")
    except Exception as exc:
        _log(player, f"edge chat invalid_channel exception={exc}")

    # Duplicate action_id should trigger dedupe error.
    action_id = new_action_id()
    payload = {"room_id": player.room_id, "action_id": action_id, "action": 2, "payload": {}}
    try:
        res1 = await player.call("tx:action", payload)
        if res1.get("ok"):
            _log(player, "edge dup action first => ok")
        else:
            _log(player, f"edge dup action first => {res1.get('code')} {res1.get('message')}")
        res2 = await player.call("tx:action", payload)
        err = _err(res2)
        if err:
            _log(player, f"edge dup action second => {err.get('code')} {err.get('message')}")
    except Exception as exc:
        _log(player, f"edge dup action exception={exc}")

    # Missing action_id (empty string).
    payload = {"room_id": player.room_id, "action_id": "", "action": 2, "payload": {}}
    try:
        res = await player.call("tx:action", payload)
        err = _err(res)
        if err:
            _log(player, f"edge missing action_id => {err.get('code')} {err.get('message')}")
    except Exception as exc:
        _log(player, f"edge missing action_id exception={exc}")


async def _play_turn(player: Player, state: Dict[str, Any]) -> None:
    state = _normalize_state(state)
    if not player.room_id:
        return
    if not player.socket or not player.socket.connected:
        return
    actor_id = state.get("actor_id")
    phase = state.get("phase")
    if phase in ("finished", None):
        return
    if actor_id != player.agent_id:
        return
    bets = state.get("bets") or {}
    stacks = state.get("stacks") or {}
    if player.agent_id not in bets or player.agent_id not in stacks:
        return
    max_bet = max(bets.values()) if bets else 0
    current_bet = int(bets.get(player.agent_id, 0))
    to_call = max_bet - current_bet
    big_blind = int(state.get("big_blind") or 2)
    max_raise_to = current_bet + int(stacks.get(player.agent_id, 0))
    hand_index = int(state.get("hand_index") or 0)
    raise_key = (int(player.room_id), hand_index, str(phase))
    turn_sig = (hand_index, phase, actor_id, max_bet)
    if _LAST_TURN_SIGNATURE.get(player.agent_id) == turn_sig:
        return
    _LAST_TURN_SIGNATURE[player.agent_id] = turn_sig

    if to_call > 0:
        if random.random() < FOLD_CHANCE:
            action = 1  # FOLD
            payload = {}
        else:
            action = 3  # CALL
            payload = {}
    else:
        # Allow at most one opening bet per phase to keep rounds moving.
        if max_bet == 0 and not _RAISE_USED.get(raise_key) and random.random() < RAISE_CHANCE:
            action = 4  # BET
            bet_to = max(big_blind * 2, 4)
            bet_to = min(bet_to, max_raise_to)
            if bet_to <= max_bet:
                action = 2
                payload = {}
            else:
                payload = {"amount": bet_to}
                _RAISE_USED[raise_key] = True
        else:
            action = 2  # CHECK
            payload = {}

    res = await player.call("tx:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": action, "payload": payload})
    err = _err(res)
    if err:
        _log(player, f"action error => {err.get('code')} {err.get('message')}")
    else:
        _log(player, f"action ok => {action}")
        await _maybe_chat(player)
    # Avoid extra round-trips to keep actions fast.


async def _maybe_chat(player: Player) -> None:
    if not player.room_id:
        return
    if random.random() >= CHAT_CHANCE:
        return
    content = random.choice([
        "gl hf",
        "nice hand",
        "ok",
        "hmm",
        "thinking...",
        "let's go",
    ])
    try:
        res = await player.call(
            "room:chat:send",
            {"room_id": player.room_id, "channel": "room", "content": content, "action_id": new_action_id()},
        )
        if res.get("ok"):
            _log(player, f"chat sent: {content}")
        else:
            _log(player, f"chat send error => {res.get('code')} {res.get('message')}")
    except Exception as exc:
        _log(player, f"chat send failed: {exc}")


async def _maybe_vote_end(player: Player) -> None:
    if not player.room_id or not player.agent_id:
        return
    if _HAND_COUNTS.get(player.agent_id, 0) < PLAY_HANDS:
        return
    if _VOTE_END_SENT.get(player.agent_id):
        return
    _VOTE_END_SENT[player.agent_id] = True
    try:
        await player.call("tx:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 7, "payload": {"agree": True}})
    except Exception:
        pass


async def main() -> None:
    player_count = int(os.getenv("TEXAS_PLAYER_COUNT", "12"))
    if player_count < 2:
        raise RuntimeError("TEXAS_PLAYER_COUNT must be >= 2")

    spectator_count = int(os.getenv("TEXAS_SPECTATORS", "1"))
    rounds = int(os.getenv("TEXAS_ROUNDS", "100"))

    prefix = os.getenv("TEXAS_NAME_PREFIX", "tx_player")
    players = [Player(name=f"{prefix}_{i+1}_{int(1000 * random.random())}") for i in range(player_count)]
    spectators = [Player(name=f"{prefix}_spectator_{i+1}", role=2) for i in range(spectator_count)]

    for player in players:
        await player.register_or_login()
        wallet = await player.wallet()
        _log(player, f"wallet token_balance={wallet.get('token_balance')}")

    for round_idx in range(1, rounds + 1):
        log_system(f"round {round_idx}/{rounds} starting")
        _VOTE_END_SENT.clear()
        _RAISE_USED.clear()
        _LAST_TURN_SIGNATURE.clear()
        _LAST_REFRESH_AT.clear()

        room_state_events = {player.name: asyncio.Event() for player in players}
        last_state: Dict[int, Dict[str, Any]] = {}
        settlement_event = asyncio.Event()
        insufficient_event = asyncio.Event()
        refresh_tasks: Dict[int, asyncio.Task] = {}
        connected_events: Dict[str, asyncio.Event] = {player.name: asyncio.Event() for player in players}

        async def _start_refresh(player: Player) -> None:
            if not player.agent_id or player.agent_id in refresh_tasks:
                return

            async def _loop() -> None:
                while not settlement_event.is_set():
                    await asyncio.sleep(3)
                    if not player.room_id:
                        continue
                    if not player.socket or not player.socket.connected:
                        try:
                            await player.reconnect()
                        except Exception:
                            continue
                    try:
                        await player.call("room:join", {"room_id": player.room_id, "role": 1})
                    except Exception:
                        continue

            refresh_tasks[player.agent_id] = asyncio.create_task(_loop())

        for player in players:
            player.socket = None
            if not player.socket:
                player.init_socket()
            attach_basic_handlers(player)

            @player.socket.on("room:state")
            async def _on_room_state(payload, _player=player):
                data = _ok_data(payload)
                room_id = data.get("room_id")
                if room_id:
                    try:
                        _player.room_id = int(room_id)
                    except (TypeError, ValueError):
                        _player.room_id = room_id
                game_state = data.get("game_state") or {}
                state = _get_state(game_state)
                if _player.agent_id:
                    last_state[_player.agent_id] = state
                room_state_events[_player.name].set()
                _log(_player, f"room:state room_id={_player.room_id} phase={state.get('phase')}")
                if round_idx == 1 and EDGE_CASES:
                    await _send_edge_cases(_player, state)
                await _play_turn(_player, state)
                await _start_refresh(_player)

            @player.socket.on("tx:phase:change")
            async def _on_phase(payload, _player=player):
                data, event, inner = _event_parts(payload)
                room_id = data.get("room_id") or event.get("room_id")
                if room_id:
                    _player.room_id = room_id
                state = _merge_phase_state(event or data)
                if _player.agent_id:
                    last_state[_player.agent_id] = state
                _log(_player, f"tx:phase:change phase={state.get('phase')} actor_id={state.get('actor_id')}")
                if state.get("phase") == "preflop":
                    hand_count = _HAND_COUNTS.get(_player.agent_id, 0) + 1
                    _HAND_COUNTS[_player.agent_id] = hand_count
                    _log(_player, f"hand {hand_count}/{PLAY_HANDS}")
                    await _maybe_vote_end(_player)
                if round_idx == 1 and EDGE_CASES:
                    await _send_edge_cases(_player, state)
                await _play_turn(_player, state)

            @player.socket.on("tx:settlement")
            async def _on_settlement(payload, _player=player):
                data, event, inner = _event_parts(payload)
                payouts = inner.get("payouts") or {}
                summary = _winner_summary(payouts, players)
                _log(_player, f"tx:settlement prize_pool={inner.get('prize_pool')} payouts={payouts} {summary}")
                settlement_event.set()

            @player.socket.on("tx:hand:result")
            async def _on_hand_result(payload, _player=player):
                data, event, hand_payload = _event_parts(payload)
                payouts = hand_payload.get("payouts") or {}
                hand_index = hand_payload.get("hand_index")
                summary = _winner_summary(payouts, players)
                _log(_player, f"tx:hand:result hand_index={hand_index} payouts={payouts} {summary}")
                if _player.room_id is not None and hand_index is not None:
                    key = (int(_player.room_id), int(hand_index))
                    if not _HAND_RESULT_SEEN.get(key) and HAND_RESULT_PAUSE_SECONDS > 0:
                        _HAND_RESULT_SEEN[key] = True
                        log_system(f"hand result received; pausing {HAND_RESULT_PAUSE_SECONDS:.1f}s for UI verification")
                        await asyncio.sleep(HAND_RESULT_PAUSE_SECONDS)

            @player.socket.on("tx:bet")
            async def _on_bet(payload, _player=player):
                data, event, inner = _event_parts(payload)
                _log(_player, f"tx:bet actor_id={event.get('actor_id')} amount={inner.get('amount')}")
                asyncio.create_task(_request_state_refresh(_player))

            @player.socket.on("tx:check")
            async def _on_check(payload, _player=player):
                data, event, _inner = _event_parts(payload)
                _log(_player, f"tx:check actor_id={event.get('actor_id')}")
                asyncio.create_task(_request_state_refresh(_player))

            @player.socket.on("tx:call")
            async def _on_call(payload, _player=player):
                data, event, _inner = _event_parts(payload)
                _log(_player, f"tx:call actor_id={event.get('actor_id')}")
                asyncio.create_task(_request_state_refresh(_player))

            @player.socket.on("tx:fold")
            async def _on_fold(payload, _player=player):
                data, event, _inner = _event_parts(payload)
                _log(_player, f"tx:fold actor_id={event.get('actor_id')}")
                asyncio.create_task(_request_state_refresh(_player))

            @player.socket.on("tx:raise")
            async def _on_raise(payload, _player=player):
                data, event, inner = _event_parts(payload)
                _log(_player, f"tx:raise actor_id={event.get('actor_id')} amount={inner.get('amount')}")
                asyncio.create_task(_request_state_refresh(_player))

            @player.socket.on("tx:all_in")
            async def _on_all_in(payload, _player=player):
                data, event, inner = _event_parts(payload)
                _log(_player, f"tx:all_in actor_id={event.get('actor_id')} amount={inner.get('amount')}")
                asyncio.create_task(_request_state_refresh(_player))

            @player.socket.on("system:error")
            async def _on_system_error(payload, _player=player):
                if payload.get("code") == 40033:
                    info = (payload.get("data") or {})
                    _log(_player, f"insufficient_tokens game_type={info.get('game_type')} entry_fee={info.get('entry_fee')}")
                    insufficient_event.set()

            @player.socket.on("system:connected")
            async def _on_connected(payload, _player=player):
                data = _ok_data(payload)
                _log(_player, f"socket connected reward_granted={data.get('reward_granted')} amount={data.get('reward_amount')}")
                connected_events[_player.name].set()

        for player in players:
            await player.login()
            await player.connect()
            try:
                await asyncio.wait_for(connected_events[player.name].wait(), timeout=5)
            except asyncio.TimeoutError:
                _log(player, "system:connected timeout; retrying connect")
                await player.reconnect()
                await asyncio.wait_for(connected_events[player.name].wait(), timeout=5)

        for spectator in spectators:
            spectator.socket = None
            spectator.init_socket()
            attach_basic_handlers(spectator)

            @spectator.socket.on("room:state")
            async def _on_room_state_spectator(payload, _player=spectator):
                data = _ok_data(payload)
                room_id = data.get("room_id")
                if room_id:
                    try:
                        _player.room_id = int(room_id)
                    except (TypeError, ValueError):
                        _player.room_id = room_id
                game_state = data.get("game_state") or {}
                state = _get_state(game_state)
                _log(_player, f"room:state (spectator) room_id={_player.room_id} phase={state.get('phase')}")

            @spectator.socket.on("room:update")
            async def _on_room_update(payload, _player=spectator):
                data, event, inner = _event_parts(payload)
                _log(_player, f"room:update (spectator) type={inner.get('type')} members={inner.get('members_count')}")

            @spectator.socket.on("room:chat")
            async def _on_room_chat(payload, _player=spectator):
                data, event, inner = _event_parts(payload)
                _log(_player, f"room:chat (spectator) sender={inner.get('sender_name')} content={inner.get('content')}")

            @spectator.socket.on("tx:hand:result")
            async def _on_hand_result(payload, _player=spectator):
                data, event, hand_payload = _event_parts(payload)
                payouts = hand_payload.get("payouts") or {}
                hand_index = hand_payload.get("hand_index")
                summary = _winner_summary(payouts, players)
                _log(_player, f"tx:hand:result (spectator) hand_index={hand_index} payouts={payouts} {summary}")

            if os.getenv("CLAW_ALLOW_GUEST_SPECTATOR", "true").lower() in ("1", "true", "yes"):
                await spectator.connect()
            else:
                await spectator.register_or_login()
                await spectator.connect()

        log_system("joining queue")
        for player in players:
            res = await player.call("queue:join", {"game_type": GAME_TYPE_TEXAS})
            if res.get("ok"):
                _log(player, f"queue:join => {res.get('data')}")
            else:
                _log(player, f"queue:join error => {res.get('code')} {res.get('message')}")

        # Wait for room assignment. If one player gets a room, join others to it.
        max_wait = 60
        waited = 0
        room_id = None
        while waited < max_wait:
            if insufficient_event.is_set():
                log_system("insufficient_tokens received; aborting")
                return
            for p in players:
                if p.room_id:
                    room_id = p.room_id
                    break
            if room_id:
                break
            await asyncio.sleep(5)
            waited += 5
            for player in players:
                if not room_state_events[player.name].is_set():
                    _log(player, "reconnecting to pick up room assignment")
                    try:
                        await player.reconnect()
                    except Exception as exc:
                        _log(player, f"reconnect failed: {exc}; rebuilding socket")
                        player.socket = None
                        player.init_socket()
                        attach_basic_handlers(player)

                        @player.socket.on("room:state")
                        async def _on_room_state(payload, _player=player):
                            data = _ok_data(payload)
                            room_id = data.get("room_id")
                            if room_id:
                                try:
                                    _player.room_id = int(room_id)
                                except (TypeError, ValueError):
                                    _player.room_id = room_id
                            game_state = data.get("game_state") or {}
                            state = _get_state(game_state)
                            if _player.agent_id:
                                last_state[_player.agent_id] = state
                            room_state_events[_player.name].set()
                            _log(_player, f"room:state room_id={_player.room_id} phase={state.get('phase')}")
                            await _play_turn(_player, state)
                            await _start_refresh(_player)

                        @player.socket.on("tx:phase:change")
                        async def _on_phase(payload, _player=player):
                            data, event, _inner = _event_parts(payload)
                            room_id = data.get("room_id") or event.get("room_id")
                            if room_id:
                                _player.room_id = room_id
                            state = _merge_phase_state(event or data)
                            if _player.agent_id:
                                last_state[_player.agent_id] = state
                            _log(_player, f"tx:phase:change phase={state.get('phase')} actor_id={state.get('actor_id')}")
                            await _play_turn(_player, state)

                        @player.socket.on("tx:settlement")
                        async def _on_settlement(payload, _player=player):
                            data, _event, inner = _event_parts(payload)
                            payouts = inner.get("payouts") or {}
                            summary = _winner_summary(payouts, players)
                            _log(_player, f"tx:settlement prize_pool={inner.get('prize_pool')} payouts={payouts} {summary}")
                            settlement_event.set()

                        @player.socket.on("tx:hand:result")
                        async def _on_hand_result(payload, _player=player):
                            data, event, hand_payload = _event_parts(payload)
                            payouts = hand_payload.get("payouts") or {}
                            hand_index = hand_payload.get("hand_index")
                            summary = _winner_summary(payouts, players)
                            _log(_player, f"tx:hand:result hand_index={hand_index} payouts={payouts} {summary}")
                            if _player.room_id is not None and hand_index is not None:
                                key = (int(_player.room_id), int(hand_index))
                                if not _HAND_RESULT_SEEN.get(key) and HAND_RESULT_PAUSE_SECONDS > 0:
                                    _HAND_RESULT_SEEN[key] = True
                                    log_system(f"hand result received; pausing {HAND_RESULT_PAUSE_SECONDS:.1f}s for UI verification")
                                    await asyncio.sleep(HAND_RESULT_PAUSE_SECONDS)

                try:
                    await player.connect()
                except Exception as exc2:
                    _log(player, f"reconnect retry failed: {exc2}")
                    continue
                try:
                    res = await player.call("queue:join", {"game_type": GAME_TYPE_TEXAS})
                    if res.get("ok"):
                        _log(player, f"queue:join (reconnect) => {res.get('data')}")
                    else:
                        _log(player, f"queue:join (reconnect) error => {res.get('code')} {res.get('message')}")
                except Exception as exc:
                    _log(player, f"queue:join (reconnect) exception={exc}")

        if not room_id:
            log_system("room assignment timed out; aborting")
            return

        # Ensure all players are in the same room.
        for player in players:
            if player.room_id != room_id:
                try:
                    res = await player.call("room:join", {"room_id": room_id, "role": 1})
                    _log(player, f"room:join (force) => {res.get('data')}")
                except Exception as exc:
                    _log(player, f"room:join (force) failed: {exc}")
        # Wait for room state for all players.
        await asyncio.sleep(2)
        if not all(event.is_set() for event in room_state_events.values()):
            log_system("room assignment incomplete; continuing anyway")

        # Spectators join the room (read-only).
        room_id = players[0].room_id
        if room_id:
            for spectator in spectators:
                res = await spectator.call("room:join", {"room_id": room_id, "role": 2})
                _log(spectator, f"room:join (spectator) => {res.get('data')}")

                # Try forbidden action only when authenticated (avoid noisy guest errors).
                if spectator.token:
                    payload = {"room_id": room_id, "action_id": new_action_id(), "action": 2, "payload": {}}
                    try:
                        res2 = await spectator.call("tx:action", payload)
                        err = _err(res2)
                        if err:
                            _log(spectator, f"spectator action blocked => {err.get('code')} {err.get('message')}")
                    except Exception as exc:
                        _log(spectator, f"spectator action blocked (no ack): {exc}")

        # Wait for settlement before proceeding to the next round.
        play_for = int(os.getenv("TEXAS_PLAY_SECONDS", "3600"))
        log_system(f"playing until settlement (max {play_for}s)")
        try:
            await asyncio.wait_for(settlement_event.wait(), timeout=play_for)
        except asyncio.TimeoutError:
            log_system("settlement timeout; aborting further rounds")
            return
        if SETTLEMENT_PAUSE_SECONDS > 0:
            log_system(f"settlement received; pausing {SETTLEMENT_PAUSE_SECONDS:.1f}s for UI verification")
            await asyncio.sleep(SETTLEMENT_PAUSE_SECONDS)

        for task in refresh_tasks.values():
            task.cancel()

        for player in players:
            await player.disconnect()
        for spectator in spectators:
            await spectator.disconnect()

        # Wallet after settlement.
        for player in players:
            wallet = await player.wallet()
            _log(player, f"wallet post-round token_balance={wallet.get('token_balance')}")



if __name__ == "__main__":
    asyncio.run(main())
