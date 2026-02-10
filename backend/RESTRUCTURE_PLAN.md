# Backend Restructure Plan

## Goals

- Make `main.py` a thin composition entry (app/sio wiring + startup hooks only)
- Move game orchestration out of transport layer (HTTP/Socket handlers)
- Keep `games/` as domain rules (engine/state machine), not infrastructure glue
- Make it easy to add a new game with minimal cross-file changes
- Drop backward compatibility and remove unused/legacy code before migration

## Proposed Target Structure

```text
backend/
  app/
    app_factory.py          # FastAPI creation + middleware setup
    sio_factory.py          # Socket.IO server creation
    startup.py              # startup/shutdown lifecycle orchestration
    state.py                # in-memory runtime registries

  api/
    routes_root.py          # /, /health
    routes_agent.py         # /agent/*, /bot/*
    routes_account.py       # register/login/balance/leaderboard
    routes_spectate.py      # /api/spectate/* and active games listing

  socket/
    common.py               # connect/disconnect/auth/spectate join-leave
    texas.py                # poker socket events
    werewolf.py             # werewolf socket events
    matchmaking.py          # matchmaking socket events

  services/
    base.py                 # BaseService lifecycle
    game_service.py         # BaseGameService shared helpers
    texas_service.py        # Texas orchestration + broadcasting + timeout loop
    werewolf_service.py     # Werewolf orchestration + timeout loop
    settlement_service.py   # token lock/unlock/prize/auto-settlement

  games/                    # keep existing domain logic
  database/                 # keep existing persistence + models
  economy/                  # keep existing account APIs
  manager/                  # anti-bot and request guard
```

## Responsibilities by Layer

### 1) `games/` (Domain Rules)

- `TexasEngine`: betting rounds, side pots, showdown logic
- `TexasGame`: table wrapper over engine + snapshots/checkpoints
- `WerewolfGame`: phase state machine, role actions, timeout defaults
- `TexasMatchmaker` / `WerewolfMatchmaker`: queue algorithms only

Keep these classes independent of FastAPI/Socket.IO internals.

### 2) `services/` (Orchestration)

- Own runtime maps and game instance lifecycle
- Bridge socket payloads to domain calls
- Trigger persistence (`redis_manager`, `persistence_manager`) at event boundaries
- Centralize settlement rules (leave table, game end, abort, auto-away)
- Run and stop background workers (timeout checkers, matchmakers)

### 3) `socket/` and `api/` (Transport)

- Parse/validate request payloads
- Invoke service methods
- Emit transport-level response/error events
- No game rules or accounting decisions directly in handlers

### 4) `app/` (Composition)

- Build FastAPI and Socket.IO instances
- Register middlewares and exception handlers
- Wire route modules and socket handler registration
- Boot services on startup and stop them on shutdown

## Migration Plan (Safe, Incremental)

### Phase 0: Cleanup (before any migration)

1. Delete unused or legacy code paths that are not required after the redesign.
2. Remove backward-compat logic (e.g., legacy payload aliases) so new structure is clean.
3. Ensure the running behavior stays identical after removals.

### Phase 1: Introduce runtime state + service shells

1. Add `app/state.py` and move global dicts from `main.py`:
   - poker/werewolf game registries
   - player sessions
   - spectator subscriptions
   - disconnect trackers and settlement locks
2. Add `services/base.py` and `services/game_service.py` as thin abstractions.
3. Keep behavior unchanged by importing state from the new module.

### Phase 2: Extract socket event handlers

1. Move common events (`connect`, `disconnect`, `authenticate`, spectate join/leave).
2. Move poker events to `socket/texas.py`.
3. Move werewolf events to `socket/werewolf.py`.
4. Keep the same event names and payload shapes for frontend compatibility.

### Phase 3: Move orchestration into services

1. Create `TexasService`:
   - `join_table/start_hand/player_move/leave_table`
   - `broadcast_state`
   - poker timeout checker + auto-away settlement
2. Create `WerewolfService`:
   - `create/join/start/action/advance_phase`
   - `broadcast_state`
   - werewolf timeout checker + end/abort handling
3. Move all settlement logic to `SettlementService`.

### Phase 4: Extract HTTP routers

1. Group endpoints by concern into `api/routes_*.py`.
2. Add `app.include_router(...)` in `app_factory.py`.

### Phase 5: Remove legacy glue and dead code

1. Delete old handler functions and compatibility shims left in `main.py`.
2. Keep only new module wiring and required imports.

### Phase 6: Replace `main.py` with thin bootstrap

`main.py` only does:

- create app/sio using factories
- register startup/shutdown hooks
- expose `asgi_app`
- optional local `uvicorn.run(...)`

## Mapping From Current `main.py` to New Modules

- Middlewares -> `app/app_factory.py`
- Startup restore logic -> `app/startup.py`
- Poker timeout checker -> `services/texas_service.py`
- Werewolf timeout checker -> `services/werewolf_service.py`
- Broadcast helpers -> each game service
- Socket event functions -> `socket/*.py`
- HTTP endpoints -> `api/routes_*.py`

## Compatibility Rules (Intentional Removal)

- Do not preserve backward compatibility.
- Remove legacy payload aliases and unused endpoints early.
- Keep runtime behavior identical after each phase by verification before commit.

## Expected Outcomes

- Smaller files and clearer ownership boundaries
- New game integration becomes predictable (domain + service + handlers)
- Lower risk of regressions when editing matchmaking/settlement/timeout logic
- `main.py` becomes stable and rarely touched

## Per-Phase Verification & Commit

- Before each phase commit: confirm logic is identical to current behavior.
- Each phase ends with a dedicated git commit.
