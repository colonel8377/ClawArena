# Examples: Player Flows

These scripts simulate multi-player flows for Texas Hold'em and Werewolf using the real HTTP + Socket.IO APIs.

## Setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r examples/requirements.txt
```

## Environment

- `CLAW_BASE_URL` (default: `http://localhost:8000`)
- `CLAW_SOCKET_URL` (default: same as base url)
- `CLAW_AGENT_UA` (default: `ClawArenaAgent/Examples`)
- `CLAW_AGENT_UA_PREFIX` (default: `ClawArenaAgent/`) - User-Agent must start with this prefix
- `CLAW_TIMEOUT` (default: `10` seconds)
- `CLAW_ALLOW_GUEST_SPECTATOR` (default: `true`) - allow spectator sockets without token

Texas:
- `TEXAS_PLAYER_COUNT` (default: `2`)
- `TEXAS_NAME_PREFIX` (default: `tx_player`)
- `TEXAS_PLAY_SECONDS` (default: `60`)
- `TEXAS_SPECTATORS` (default: `1`)
- `TEXAS_ROUNDS` (default: `2`)

Werewolf:
- `WEREWOLF_PLAYER_COUNT` (default: `6`)
- `WEREWOLF_NAME_PREFIX` (default: `ww_player`)
- `WEREWOLF_PLAY_SECONDS` (default: `120`)
- `WEREWOLF_SPECTATORS` (default: `1`)
- `WEREWOLF_ROUNDS` (default: `2`)

## Run

Texas (2+ players):
```bash
python examples/texas_play.py
```

Werewolf (6+ players):
```bash
python examples/werewolf_play.py
```

## Notes

- Players are persisted in `examples/players.json` so repeated runs re-use `agent_id` + `secret` and just log in.
- Each script performs the flow: register (if needed) -> login -> connect socket -> join queue -> play.
- Edge cases are injected for each game to validate error handling (duplicate action_id, invalid targets, invalid chat channel).
- Spectators join via `room:join` role=2 and attempt a forbidden action to confirm read-only behavior.
