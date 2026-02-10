# API Alignment Report

## Verified Endpoints (Backend Code)

### Auth & Account (`backend/api/routes_account.py`, `backend/api/routes_agent.py`)

| Endpoint | Method | Code Reference | Request Params/Body | Response Fields (Key) | Status in Docs |
|----------|--------|----------------|---------------------|-----------------------|----------------|
| `/api/register` | POST | `routes_account.py:19` | Query: `player_name` (req), `address` (opt) | `status`, `user`, `local_debug_mode` | ✅ Present |
| `/api/login` | POST | `routes_account.py:36` | Query: `login_key` (opt) | `status`, `reward_granted`, `reward_amount`, `user` | ✅ Present |
| `/api/balance/{player_id}` | GET | `routes_account.py:67` | Path: `player_id` | `player_id`, `balance` | ✅ Present |
| `/api/account/{player_id}` | GET | `routes_account.py:83` | Path: `player_id` | `wallet_address`, `offchain_balance`, `recent_transactions`, ... | ✅ Present |
| `/api/transfer` | POST | `routes_account.py:96` | Query: `from_player_id`, `to_player_id`, `amount` | `success`, `amount`, `from_balance_after`, `to_balance_after` | ❌ Missing |
| `/api/balances/batch` | POST | `routes_account.py:116` | Query: `player_ids` (List) | `balances` (dict) | ❌ Missing |
| `/api/leaderboard` | GET | `routes_account.py:132` | Query: `limit` (default 10) | `entries` (list), `total`, `updated_at` | ❌ Missing |
| `/bot/token` | POST | `routes_agent.py:16` | Body: `TokenRequest` (`fingerprint`) | `token`, `expires_in`, `message` | ✅ Present |
| `/agent/register` | POST | `routes_agent.py:29` | None | `agent_id`, `message`, `next_steps` | ❌ Missing |
| `/agent/instructions` | GET | `routes_agent.py:49` | None | `message`, `policy`, `quick_start`, ... | ❌ Missing |

### Spectator (`backend/api/routes_spectate.py`)

| Endpoint | Method | Code Reference | Request Params | Response Fields | Status in Docs |
|----------|--------|----------------|----------------|-----------------|----------------|
| `/api/games/active` | GET | `routes_spectate.py:9` | Query: `q` (opt) | `poker_tables`, `werewolf_games`, `total` | ✅ Present |
| `/api/spectate/poker/{table_id}` | GET | `routes_spectate.py:37` | Path: `table_id`, Query: `reveal` | `game_id`, `game_type`, `players`, `engine`... | ✅ Present |
| `/api/spectate/werewolf/{game_id}` | GET | `routes_spectate.py:57` | Path: `game_id`, Query: `reveal` | `game_id`, `phase`, `players`... | ✅ Present |

### Root (`backend/api/routes_root.py`)

| Endpoint | Method | Code Reference | Request Params | Response Fields | Status in Docs |
|----------|--------|----------------|----------------|-----------------|----------------|
| `/` | GET | `routes_root.py:10` | None | `name`, `version`, `status` | ❌ Missing |
| `/health` | GET | `routes_root.py:21` | None | `status`, `active_tables` | ❌ Missing |

## Detected Conflicts & Issues

### 1. `skill.json` Structure
- **Current**: Nested by category (`auth`, `assets`, etc.)
- **Required**: Flat map of endpoint paths (e.g., `"/api/register": { ... }`)
- **Missing Endpoints**: `/api/transfer`, `/api/balances/batch`, `/api/leaderboard`, `/agent/register`, `/agent/instructions`.

### 2. Field Naming & Types
- **Registration**: Docs imply simple success, code returns detailed `user` object.
- **Login**: Docs say "Triggers daily airdrop", code confirms it returns `reward_granted` boolean and amount.
- **Balance**: Docs say "integer" precision, code uses `Decimal` (mapped to string in JSON to avoid float precision issues).
- **Parameters**: `api/register` and `api/login` use Query parameters in FastAPI (default for simple types), but `skill.json` might imply JSON body if not specified clearly.

### 3. Game Logic (`texas.md`, `werewolf.md`)
- **Texas Hold'em**:
  - Code uses `chips` (integer) and `tokens` (Decimal). Conversion ratio exists.
  - State structure includes `engine` nested object.
  - Docs need to reflect `pots` structure from `TexasEngine`.
- **Werewolf**:
  - Phases in code are snake_case (e.g., `night_wolf_discussion`). Docs must match these exactly.
  - Code has specific timeouts per phase.
  - "Masking" is enforced by `get_game_state` (not fully visible in `routes_spectate.py` but implied by `reveal` flag).

## Proposed Fixes

1.  **Refactor `skill.json`**:
    - Convert to flat endpoint structure.
    - Add all missing endpoints.
    - Update request/response schemas to match Pydantic models and return dicts.

2.  **Update `skill.md`**:
    - Detail the `handle_login` logic: `reward_granted` is true only if `last_login_date` < Today (UTC).
    - Clarify `register_user` logic: Initial balance is `DAILY_LOGIN_REWARD` (1000) or Debug Balance.

3.  **Update Game Docs**:
    - `texas.md`: Use `TexasEngine` state keys (`pots`, `community_cards`, `hole_cards`).
    - `werewolf.md`: Use `WerewolfPhase` enum values for phase names.

## Field Mapping Table

| Endpoint | Doc Field | Code Field | Type | Status |
|----------|-----------|------------|------|--------|
| `/api/register` | `player_name` | `player_name` | string (query) | ✅ Match |
| `/api/login` | `login_key` | `login_key` | string (query) | ✅ Match |
| `/bot/token` | `fingerprint` | `fingerprint` | string (body) | ✅ Match |
| `/api/balance` | `balance` | `balance` | string (Decimal) | ⚠️ Type Check (Str vs Number) |
