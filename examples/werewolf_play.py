import asyncio
import os
import random
import time
from typing import Any, Dict, Optional, Set

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

GAME_TYPE_WEREWOLF = 1
CHAT_COOLDOWN_SECONDS = float(os.getenv("WEREWOLF_CHAT_COOLDOWN_SECONDS", "2.0"))
SPEAK_BURST_MIN = int(os.getenv("WEREWOLF_SPEAK_BURST_MIN", "1"))
SPEAK_BURST_MAX = int(os.getenv("WEREWOLF_SPEAK_BURST_MAX", "2"))
WOLF_CHAT_BURST_MIN = int(os.getenv("WEREWOLF_WOLF_CHAT_BURST_MIN", "1"))
WOLF_CHAT_BURST_MAX = int(os.getenv("WEREWOLF_WOLF_CHAT_BURST_MAX", "2"))
WITCH_SAVE_CHANCE = float(os.getenv("WEREWOLF_WITCH_SAVE_CHANCE", "0.5"))
WITCH_POISON_CHANCE = float(os.getenv("WEREWOLF_WITCH_POISON_CHANCE", "0.25"))
DAY_CHAT_LINES = [
    "Any info from last night?",
    "I am villager.",
    "Let's track votes carefully.",
    "Who looked suspicious?",
    "I don't trust that claim.",
    "We need more data.",
    "I'm not convinced yet.",
    "Let's hear from everyone.",
    "Vote patterns matter.",
    "I'm leaning toward a mid seat.",
    "Claim your role if you have info.",
    "Watch who avoids speaking.",
    "We should compare notes.",
    "Don't pile on without reason.",
    "I need more info before voting.",
    "Can we recap who spoke?",
    "I feel uneasy about seat 3.",
    "Let's not rush.",
    "Share your reads.",
]
DAY_CHAT_TEMPLATES = [
    "I'm watching {target}.",
    "Question for {target}.",
    "Leaning {target}.",
]
WOLF_CHAT_LINES = [
    "Pick a quiet target.",
    "Let's avoid the loud ones.",
    "Push suspicion elsewhere.",
    "Agree on one target.",
    "Watch the seer claims.",
    "Keep the pressure on.",
    "Let them argue and split.",
    "Quietly agree and move.",
    "Stick to the plan.",
]
WOLF_CHAT_TEMPLATES = [
    "Let's hit {target}.",
    "Target {target}.",
]


def _pick_target(alive: Set[int], exclude: int) -> int:
    for aid in sorted(alive):
        if aid != exclude:
            return aid
    return exclude


def _seat_label(game_state: Dict[str, Any], agent_id: int) -> str:
    players = game_state.get("players") or []
    for idx, player in enumerate(players, start=1):
        pid = player.get("agent_id") or player.get("sid")
        if pid is not None and int(pid) == int(agent_id):
            seat = player.get("seat") or idx
            return f"SEAT {seat}"
    return f"PLAYER {agent_id}"


def _prepare_lines(base: list[str], templates: list[str], target_label: Optional[str]) -> list[str]:
    if not target_label:
        return list(base)
    return list(base) + [tmpl.format(target=target_label) for tmpl in templates]


def _pick_random_target(alive: Set[int], exclude: int) -> int:
    candidates = [aid for aid in alive if aid != exclude]
    if not candidates:
        return exclude
    return random.choice(candidates)


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


async def _maybe_send_room_chat(
    player: Player,
    channel: str,
    last_chat_ts: Dict[str, float],
    lines: list[str],
    chance: float = 0.4,
) -> None:
    if not player.room_id:
        return
    now = time.monotonic()
    last = last_chat_ts.get(player.name, 0.0)
    if now - last < CHAT_COOLDOWN_SECONDS:
        return
    if random.random() > chance:
        return
    content = random.choice(lines)
    try:
        await player.call(
            "room:chat:send",
            {"room_id": player.room_id, "channel": channel, "content": content, "action_id": new_action_id()},
        )
        last_chat_ts[player.name] = now
    except Exception as exc:
        _log(player, f"chat send failed: {exc}")


async def _send_room_chat(
    player: Player,
    channel: str,
    last_chat_ts: Dict[str, float],
    content: str,
) -> None:
    if not player.room_id:
        return
    now = time.monotonic()
    last = last_chat_ts.get(player.name, 0.0)
    if now - last < CHAT_COOLDOWN_SECONDS:
        return
    try:
        await player.call(
            "room:chat:send",
            {"room_id": player.room_id, "channel": channel, "content": content, "action_id": new_action_id()},
        )
        last_chat_ts[player.name] = now
    except Exception as exc:
        _log(player, f"chat send failed: {exc}")


async def _send_speaker_chat(
    player: Player,
    channel: str,
    last_chat_ts: Dict[str, float],
    lines: list[str],
    bursts: int = 2,
) -> None:
    for idx in range(max(1, bursts)):
        await _send_room_chat(player, channel, last_chat_ts, random.choice(lines))
        if idx < bursts - 1:
            await asyncio.sleep(CHAT_COOLDOWN_SECONDS + 0.1)


async def _handle_phase(
    player: Player,
    game_state: Dict[str, Any],
    acted: Set[str],
    last_chat_ts: Dict[str, float],
    wolf_targets: Dict[int, int],
    day_vote_targets: Dict[int, int],
    seer_history: Dict[int, Set[int]],
    guard_history: Dict[int, int],
    witch_state: Dict[int, Dict[str, bool]],
) -> None:
    if not player.room_id or not player.agent_id:
        return
    phase = game_state.get("phase")
    day = int(game_state.get("day") or 0)
    roles = game_state.get("roles") or {}
    role_info = roles.get(player.agent_id) or roles.get(str(player.agent_id)) or {}
    role = int(role_info.get("role") or 0)
    alive = set(int(aid) for aid in (game_state.get("alive") or []))
    speak_bursts = random.randint(SPEAK_BURST_MIN, SPEAK_BURST_MAX)
    wolf_chat_bursts = random.randint(WOLF_CHAT_BURST_MIN, WOLF_CHAT_BURST_MAX)

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
        target_label = None
        if day >= 1 and day in wolf_targets:
            target_label = _seat_label(game_state, wolf_targets[day])
        lines = _prepare_lines(WOLF_CHAT_LINES, WOLF_CHAT_TEMPLATES, target_label)
        await _send_speaker_chat(player, "wolf", last_chat_ts, lines, bursts=wolf_chat_bursts)
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 2, "payload": {}})
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 10, "payload": {}})
        acted.add(phase_key)
        _log(player, "WOLF_CHAT READY")
        return

    if phase == "wolf_kill" and role == 1:
        target_id = wolf_targets.get(day)
        if not target_id or target_id not in alive:
            target_id = _pick_random_target(alive, player.agent_id)
            wolf_targets[day] = target_id
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 4, "payload": {"target_id": target_id}})
        acted.add(phase_key)
        _log(player, f"WOLF_KILL {target_id}")
        return

    # Seer, guard, witch.
    if phase == "seer" and role == 2:
        seen = seer_history.setdefault(player.agent_id, set())
        target_id = _pick_random_target(alive, player.agent_id)
        if target_id in seen and len(alive) > 1:
            target_id = _pick_random_target(alive, player.agent_id)
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 5, "payload": {"target_id": target_id}})
        seen.add(target_id)
        acted.add(phase_key)
        _log(player, f"SEER_CHECK {target_id}")
        return

    if phase == "guard" and role == 5:
        last_guard = guard_history.get(player.agent_id)
        target_id = _pick_random_target(alive, player.agent_id)
        if last_guard and target_id == last_guard and len(alive) > 1:
            target_id = _pick_random_target(alive, player.agent_id)
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 3, "payload": {"target_id": target_id}})
        guard_history[player.agent_id] = target_id
        acted.add(phase_key)
        _log(player, f"GUARD {target_id}")
        return

    if phase == "witch" and role == 3:
        state = witch_state.setdefault(player.agent_id, {"save_used": False, "poison_used": False})
        action = 10
        payload = {}
        label = "WITCH SKIP"
        if not state.get("save_used") and random.random() < WITCH_SAVE_CHANCE and wolf_targets.get(day):
            action = 6
            label = "WITCH SAVE"
        elif not state.get("poison_used") and random.random() < WITCH_POISON_CHANCE:
            target_id = _pick_random_target(alive, player.agent_id)
            action = 7
            payload = {"target_id": target_id}
            label = f"WITCH POISON {target_id}"
        try:
            res = await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": action, "payload": payload})
            err = _err(res)
            if err:
                _log(player, f"{label} failed => {err.get('code')} {err.get('message')}")
            else:
                if action == 6:
                    state["save_used"] = True
                elif action == 7:
                    state["poison_used"] = True
                _log(player, label)
        except Exception as exc:
            _log(player, f"{label} exception={exc}")
        acted.add(phase_key)
        return

    # Day debate / vote.
    if phase == "day_debate":
        current_speaker = int(game_state.get("current_speaker") or 0)
        if current_speaker == player.agent_id:
            target_id = _pick_random_target(alive, player.agent_id)
            target_label = _seat_label(game_state, target_id)
            lines = _prepare_lines(DAY_CHAT_LINES, DAY_CHAT_TEMPLATES, target_label)
            content = random.choice(lines)
            await _send_speaker_chat(player, "day", last_chat_ts, lines, bursts=speak_bursts)
            await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 8, "payload": {"content": content}})
            acted.add(phase_key)
            _log(player, f"SPEAK {content}")
            return

    if phase == "day_vote" and player.agent_id in alive:
        target_id = day_vote_targets.get(day)
        if not target_id or target_id not in alive:
            target_id = _pick_random_target(alive, player.agent_id)
            day_vote_targets[day] = target_id
        await player.call("ww:action", {"room_id": player.room_id, "action_id": new_action_id(), "action": 9, "payload": {"target_id": target_id}})
        acted.add(phase_key)
        _log(player, f"VOTE {target_id}")
        return


async def main() -> None:
    player_count = int(os.getenv("WEREWOLF_PLAYER_COUNT", "12"))
    if player_count < 6:
        raise RuntimeError("WEREWOLF_PLAYER_COUNT must be >= 6")

    spectator_count = int(os.getenv("WEREWOLF_SPECTATORS", "2"))
    rounds = max(2, int(os.getenv("WEREWOLF_ROUNDS", "3")))

    prefix = os.getenv("WEREWOLF_NAME_PREFIX", "ww_player")
    players = [Player(name=f"{prefix}_{i+1}_{int(1000*random.random())}") for i in range(player_count)]
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

        last_chat_ts: Dict[str, float] = {}
        wolf_targets: Dict[int, int] = {}
        day_vote_targets: Dict[int, int] = {}
        seer_history: Dict[int, Set[int]] = {}
        guard_history: Dict[int, int] = {}
        witch_state: Dict[int, Dict[str, bool]] = {}
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
                try:
                    await _handle_phase(
                        _player,
                        game_state,
                        acted,
                        last_chat_ts,
                        wolf_targets,
                        day_vote_targets,
                        seer_history,
                        guard_history,
                        witch_state,
                    )
                except Exception as exc:
                    _log(_player, f"handle_phase error: {exc}")

            @player.socket.on("ww:phase:change")
            async def _on_phase(payload, _player=player):
                data, event, inner = _event_parts(payload)
                phase = inner.get("phase") or event.get("phase")
                merged_state = dict(last_state.get(_player.agent_id, {})) if _player.agent_id else {}
                if isinstance(inner, dict):
                    merged_state.update(inner)
                if phase:
                    merged_state["phase"] = phase
                if _player.agent_id:
                    last_state[_player.agent_id] = merged_state
                _log(_player, f"ww:phase:change phase={phase}")
                if inner.get("winner"):
                    winner_value["winner"] = inner.get("winner")
                if phase == "finished":
                    finished_event.set()
                try:
                    await _handle_phase(
                        _player,
                        merged_state or inner,
                        acted,
                        last_chat_ts,
                        wolf_targets,
                        day_vote_targets,
                        seer_history,
                        guard_history,
                        witch_state,
                    )
                except Exception as exc:
                    _log(_player, f"handle_phase error: {exc}")

            @player.socket.on("room:update")
            async def _on_room_update(payload, _player=player):
                data, event, inner = _event_parts(payload)
                if inner.get("type") == "game_finish":
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
                data, event, inner = _event_parts(payload)
                _log(_player, f"room:update (spectator) type={inner.get('type')} members={inner.get('members_count')}")

            @spectator.socket.on("room:chat")
            async def _on_room_chat(payload, _player=spectator):
                data, event, inner = _event_parts(payload)
                _log(_player, f"room:chat (spectator) sender={inner.get('sender_name')} content={inner.get('content')}")

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
                            try:
                                await _handle_phase(
                                    _player,
                                    game_state,
                                    acted,
                                    last_chat_ts,
                                    wolf_targets,
                                    day_vote_targets,
                                    seer_history,
                                    guard_history,
                                    witch_state,
                                )
                            except Exception as exc:
                                _log(_player, f"handle_phase error: {exc}")

                        @player.socket.on("ww:phase:change")
                        async def _on_phase(payload, _player=player):
                            data, event, inner = _event_parts(payload)
                            phase = inner.get("phase") or event.get("phase")
                            merged_state = dict(last_state.get(_player.agent_id, {})) if _player.agent_id else {}
                            if isinstance(inner, dict):
                                merged_state.update(inner)
                            if phase:
                                merged_state["phase"] = phase
                            if _player.agent_id:
                                last_state[_player.agent_id] = merged_state
                            _log(_player, f"ww:phase:change phase={phase}")
                            if phase == "finished":
                                finished_event.set()
                            try:
                                await _handle_phase(
                                    _player,
                                    merged_state or inner,
                                    acted,
                                    last_chat_ts,
                                    wolf_targets,
                                    day_vote_targets,
                                    seer_history,
                                    guard_history,
                                    witch_state,
                                )
                            except Exception as exc:
                                _log(_player, f"handle_phase error: {exc}")

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

        play_for = int(os.getenv("WEREWOLF_PLAY_SECONDS", "600"))
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
