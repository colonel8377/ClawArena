import asyncio
import os
from typing import Any, Dict, Set

from shared import (
    Player,
    _err,
    _ok_data,
    attach_basic_handlers,
    log_system,
    new_action_id,
    _log,
)

GAME_TYPE_WEREWOLF = 1


def _pick_target(alive: Set[int], exclude: int) -> int:
    for aid in sorted(alive):
        if aid != exclude:
            return aid
    return exclude


async def _send_edge_cases(player: Player) -> None:
    if not player.room_id:
        return

    # Invalid vote target.
    payload = {"room_id": player.room_id, "action_id": new_action_id(), "action": 9, "payload": {"target_id": 999999}}
    try:
        res = await player.call("ww:action", payload)
        err = _err(res)
        if err:
            _log(player, f"edge invalid vote => {err.get('code')} {err.get('message')}")
    except Exception as exc:
        _log(player, f"edge invalid vote exception={exc}")

    # Duplicate action_id.
    action_id = new_action_id()
    payload = {"room_id": player.room_id, "action_id": action_id, "action": 1, "payload": {}}
    try:
        res1 = await player.call("ww:action", payload)
        _log(player, f"edge dup action first => ok={res1.get('ok')}")
        res2 = await player.call("ww:action", payload)
        err = _err(res2)
        if err:
            _log(player, f"edge dup action second => {err.get('code')} {err.get('message')}")
    except Exception as exc:
        _log(player, f"edge dup action exception={exc}")


async def _handle_phase(player: Player, game_state: Dict[str, Any], acted: Set[str]) -> None:
    if not player.room_id or not player.agent_id:
        return
    phase = game_state.get("phase")
    day = int(game_state.get("day") or 0)
    roles = game_state.get("roles") or {}
    role_info = roles.get(player.agent_id) or {}
    role = int(role_info.get("role") or 0)
    alive = set(int(aid) for aid in (game_state.get("alive") or []))

    if phase is None or phase == "finished":
        return

    phase_key = f"{phase}:{day}:{player.agent_id}"
    if phase_key in acted:
        return

    # Lobby ready.
    if phase == "lobby":
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 1, "payload": {}})
        acted.add(phase_key)
        _log(player, "READY")
        return

    # Wolf chat / kill.
    if phase == "wolf_chat" and role == 1:
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 10, "payload": {}})
        acted.add(phase_key)
        _log(player, "WOLF_CHAT SKIP")
        return

    if phase == "wolf_kill" and role == 1:
        target_id = _pick_target(alive, player.agent_id)
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 4, "payload": {"target_id": target_id}})
        acted.add(phase_key)
        _log(player, f"WOLF_KILL {target_id}")
        return

    # Seer, guard, witch.
    if phase == "seer" and role == 2:
        target_id = _pick_target(alive, player.agent_id)
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 5, "payload": {"target_id": target_id}})
        acted.add(phase_key)
        _log(player, f"SEER_CHECK {target_id}")
        return

    if phase == "guard" and role == 5:
        target_id = _pick_target(alive, player.agent_id)
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 3, "payload": {"target_id": target_id}})
        acted.add(phase_key)
        _log(player, f"GUARD {target_id}")
        return

    if phase == "witch" and role == 3:
        # Skip to avoid invalid save/poison without context.
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 10, "payload": {}})
        acted.add(phase_key)
        _log(player, "WITCH SKIP")
        return

    # Day debate / vote.
    if phase == "day_debate" and int(game_state.get("current_speaker") or 0) == player.agent_id:
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 8, "payload": {"content": "auto speak"}})
        acted.add(phase_key)
        _log(player, "SPEAK")
        return

    if phase == "day_vote" and player.agent_id in alive:
        target_id = _pick_target(alive, player.agent_id)
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 9, "payload": {"target_id": target_id}})
        acted.add(phase_key)
        _log(player, f"VOTE {target_id}")
        return


async def main() -> None:
    player_count = int(os.getenv("WEREWOLF_PLAYER_COUNT", "6"))
    if player_count < 6:
        raise RuntimeError("WEREWOLF_PLAYER_COUNT must be >= 6")

    spectator_count = int(os.getenv("WEREWOLF_SPECTATORS", "1"))
    rounds = max(2, int(os.getenv("WEREWOLF_ROUNDS", "3")))

    prefix = os.getenv("WEREWOLF_NAME_PREFIX", "ww_player")
    players = [Player(name=f"{prefix}_{i+1}") for i in range(player_count)]
    spectators = [Player(name=f"{prefix}_spectator_{i+1}", role=2) for i in range(spectator_count)]

    initial_wallets: Dict[str, float] = {}
    for player in players:
        await player.register_or_login()
        wallet = await player.wallet()
        _log(player, f"wallet token_balance={wallet.get('token_balance')}")
        if wallet.get("token_balance") is not None:
            initial_wallets[player.name] = float(wallet.get("token_balance"))

    for round_idx in range(1, rounds + 1):
        log_system(f"round {round_idx}/{rounds} starting")

        room_state_events = {player.name: asyncio.Event() for player in players}
        last_state: Dict[int, Dict[str, Any]] = {}
        acted: Set[str] = set()
        finished_event = asyncio.Event()
        insufficient_event = asyncio.Event()
        winner_value: Dict[str, Any] = {"winner": None}
        round_wallets: Dict[str, float] = {}

        for player in players:
            wallet = await player.wallet()
            if wallet.get("token_balance") is not None:
                round_wallets[player.name] = float(wallet.get("token_balance"))
            _log(player, f"wallet pre-round token_balance={wallet.get('token_balance')}")

        for player in players:
            player.socket = None
            if not player.socket:
                player.init_socket()
            attach_basic_handlers(player)

            @player.socket.on("room:state")
            async def _on_room_state(payload, _player=player):
                data = _ok_data(payload)
                _player.room_id = data.get("room_id")
                game_state = data.get("game_state") or {}
                if _player.agent_id:
                    last_state[_player.agent_id] = game_state
                room_state_events[_player.name].set()
                _log(_player, f"room:state room_id={_player.room_id} phase={game_state.get('phase')}")
                if game_state.get("winner"):
                    winner_value["winner"] = game_state.get("winner")
                if game_state.get("phase") == "finished":
                    finished_event.set()
                await _handle_phase(_player, game_state, acted)

            @player.socket.on("ww:phase:change")
            async def _on_phase(payload, _player=player):
                data = _ok_data(payload)
                if _player.agent_id and _player.agent_id in last_state:
                    last_state[_player.agent_id]["phase"] = data.get("phase")
                _log(_player, f"ww:phase:change phase={data.get('phase')}")
                if data.get("payload", {}).get("winner"):
                    winner_value["winner"] = data.get("payload", {}).get("winner")
                if data.get("phase") == "finished":
                    finished_event.set()
                await _handle_phase(_player, last_state.get(_player.agent_id, data), acted)

            @player.socket.on("room:update")
            async def _on_room_update(payload, _player=player):
                data = _ok_data(payload)
                if data.get("type") == "game_finish":
                    finished_event.set()

            @player.socket.on("system:error")
            async def _on_system_error(payload, _player=player):
                if payload.get("code") == 40033:
                    info = (payload.get("data") or {})
                    _log(_player, f"insufficient_tokens game_type={info.get('game_type')} entry_fee={info.get('entry_fee')}")
                    insufficient_event.set()

        for player in players:
            await player.login()
            await player.connect()

        for spectator in spectators:
            spectator.socket = None
            spectator.init_socket()
            attach_basic_handlers(spectator)

            @spectator.socket.on("room:state")
            async def _on_room_state_spectator(payload, _player=spectator):
                data = _ok_data(payload)
                _player.room_id = data.get("room_id")
                game_state = data.get("game_state") or {}
                _log(_player, f"room:state (spectator) room_id={_player.room_id} phase={game_state.get('phase')}")

            @spectator.socket.on("room:update")
            async def _on_room_update(payload, _player=spectator):
                data = _ok_data(payload)
                _log(_player, f"room:update (spectator) type={data.get('type')} members={data.get('members_count')}")

            @spectator.socket.on("room:chat")
            async def _on_room_chat(payload, _player=spectator):
                data = _ok_data(payload)
                _log(_player, f"room:chat (spectator) sender={data.get('sender_name')} content={data.get('content')}")

            if os.getenv("CLAW_ALLOW_GUEST_SPECTATOR", "true").lower() in ("1", "true", "yes"):
                await spectator.connect()
            else:
                await spectator.register_or_login()
                await spectator.connect()

        log_system("joining queue")
        for player in players:
            res = await player.call("queue:join", {"game_type": GAME_TYPE_WEREWOLF})
            _log(player, f"queue:join => {res.get('data')}")

        # Wait for room assignment. If not received, reconnect periodically.
        max_wait = 90
        waited = 0
        while waited < max_wait:
            if insufficient_event.is_set():
                log_system("insufficient_tokens received; aborting")
                return
            if all(event.is_set() for event in room_state_events.values()):
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
                            _player.room_id = data.get("room_id")
                            game_state = data.get("game_state") or {}
                            if _player.agent_id:
                                last_state[_player.agent_id] = game_state
                            room_state_events[_player.name].set()
                            _log(_player, f"room:state room_id={_player.room_id} phase={game_state.get('phase')}")
                            if game_state.get("phase") == "finished":
                                finished_event.set()
                            await _handle_phase(_player, game_state, acted)

                        @player.socket.on("ww:phase:change")
                        async def _on_phase(payload, _player=player):
                            data = _ok_data(payload)
                            if _player.agent_id and _player.agent_id in last_state:
                                last_state[_player.agent_id]["phase"] = data.get("phase")
                            _log(_player, f"ww:phase:change phase={data.get('phase')}")
                            if data.get("phase") == "finished":
                                finished_event.set()
                            await _handle_phase(_player, last_state.get(_player.agent_id, data), acted)

                        @player.socket.on("system:error")
                        async def _on_system_error(payload, _player=player):
                            if payload.get("code") == 40033:
                                info = (payload.get("data") or {})
                                _log(_player, f"insufficient_tokens game_type={info.get('game_type')} entry_fee={info.get('entry_fee')}")
                                insufficient_event.set()

                        try:
                            await player.connect()
                        except Exception as exc2:
                            _log(player, f"reconnect retry failed: {exc2}")
                            continue
                        continue

        if not all(event.is_set() for event in room_state_events.values()):
            log_system("room assignment timed out; aborting")
            return

        # Spectators join the room (read-only).
        room_id = players[0].room_id
        if room_id:
            for spectator in spectators:
                res = await spectator.call("room:join", {"room_id": room_id, "role": 2})
                _log(spectator, f"room:join (spectator) => {res.get('data')}")

                # Try forbidden action.
                payload = {"room_id": room_id, "action_id": new_action_id(), "action": 1, "payload": {}}
                try:
                    res2 = await spectator.call("ww:action", payload)
                    err = _err(res2)
                    if err:
                        _log(spectator, f"spectator action blocked => {err.get('code')} {err.get('message')}")
                except Exception as exc:
                    _log(spectator, f"spectator action blocked (no ack): {exc}")

        # Edge cases on the first player (first round only).
        if round_idx == 1:
            await _send_edge_cases(players[0])

        play_for = int(os.getenv("WEREWOLF_PLAY_SECONDS", "240"))
        log_system(f"playing until finish (max {play_for}s)")
        try:
            await asyncio.wait_for(finished_event.wait(), timeout=play_for)
        except asyncio.TimeoutError:
            raise RuntimeError("game finish timeout; round failed")

        for player in players:
            await player.disconnect()
        for spectator in spectators:
            await spectator.disconnect()

        for player in players:
            wallet = await player.wallet()
            before = round_wallets.get(player.name) or initial_wallets.get(player.name)
            after = wallet.get("token_balance")
            delta = None if before is None or after is None else float(after) - float(before)
            _log(player, f"wallet post-round token_balance={after} delta={delta}")
        log_system(f"round {round_idx} winner={winner_value.get('winner')}")


if __name__ == "__main__":
    asyncio.run(main())
