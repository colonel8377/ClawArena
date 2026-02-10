"""
main.py - The Server

FastAPI + Socket.IO server with agent authentication, game management,
and in-app token economy settlement.
"""

import asyncio
import signal
from datetime import datetime
from decimal import Decimal
from typing import Optional, List

import socketio
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from config.config import (
    LOCAL_DEBUG_MODE,
    ALLOWED_ORIGINS,
    ALLOWED_HOSTS,
    SOCKET_IO_LOGGER,
    SOCKET_ENGINEIO_LOGGER,
)
from database.connection import init_db
from database.persistence_manager import persistence_manager
from database.redis_manager import redis_manager
from app.state import runtime_state
from socket.common import register_common_handlers
from socket.texas import (
    POKER_ACTIVE_PHASES,
    broadcast_game_state,
    check_disconnected_texas_players,
    register_texas_handlers,
)
from socket.werewolf import (
    WEREWOLF_SIGNIFICANT_PHASES,
    handle_werewolf_game_abort,
    handle_werewolf_game_end,
    register_werewolf_handlers,
)
from socket.matchmaking import register_matchmaking_handlers
from economy.account import (
    register_user, handle_login, get_balance,
    get_account_summary, transfer_balance, batch_get_balances,
    InvalidAmountError, InsufficientBalanceError, UserNotFoundError, InvalidWalletAddressError,
    get_leaderboard
)
from games.texas import TexasGame
from games.texas.texas_engine import PokerPhase
from games.werewolf.werewolf_game import WerewolfGame, WerewolfPhase
from manager.anti_bot_manager import (
    TokenRequest,
    get_token,
    verify_request,
    generate_agent_id,
    get_agent_instructions,
    is_public_endpoint,
)

# Werewolf game timeout check interval (seconds)
WEREWOLF_TIMEOUT_CHECK_INTERVAL = 5
# Poker timeout check interval (seconds)
POKER_TIMEOUT_CHECK_INTERVAL = 1


# Rate limiting
limiter = Limiter(key_func=get_remote_address)

# Create Socket.IO server with proper configuration
socketio_origins = '*' if '*' in ALLOWED_ORIGINS else ALLOWED_ORIGINS
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=socketio_origins,
    logger=SOCKET_IO_LOGGER,
    engineio_logger=SOCKET_ENGINEIO_LOGGER,
    ping_timeout=60,
    ping_interval=25
)

# Create FastAPI app
app = FastAPI(
    title="Arena Poker Game Engine",
    description="Real-time Texas Hold'em and Werewolf for AI agents",
    version="2.1.0"
)

# Add rate limiter to app
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Anti-bot middleware
@app.middleware("http")
async def bot_protection_middleware(request: Request, call_next):
    allowed, error_msg = await verify_request(request)
    if not allowed:
        return JSONResponse(
            status_code=403,
            content={
                "error": "bot_protection",
                "message": error_msg or "Bot protection rejected the request.",
            },
        )
    return await call_next(request)


# Agent-only middleware (ensures only AI agents can access game endpoints)
@app.middleware("http")
async def agent_only_middleware(request: Request, call_next):
    """
    Verify that non-public endpoints are accessed by AI agents only.
    
    Humans can ONLY access public endpoints (spectate, docs, etc).
    Everything else requires agent verification.
    """
    # Public endpoints are open to everyone
    if is_public_endpoint(request.url.path):
        return await call_next(request)
    
    # Verify agent for protected endpoints
    is_valid, error_msg = await verify_request(request)
    
    if not is_valid:
        return JSONResponse(
            status_code=403,
            content={
                "error": "AGENT_ONLY",
                "message": error_msg,
                "help": "This arena is for AI agents only. Humans can spectate at /api/spectate/*",
                "instructions": get_agent_instructions()
            }
        )
    
    return await call_next(request)

# CORS middleware with configurable origins
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    # Include OPTIONS so browser CORS preflight requests are accepted.
    allow_methods=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=ALLOWED_HOSTS,
)

# Game state management (moved to centralized runtime_state in app/state.py)
poker_tables = runtime_state.poker_tables  # table_id -> TexasGame
werewolf_games = runtime_state.werewolf_games  # game_id -> WerewolfGame

# Register common socket handlers (connect/auth/spectate).
register_common_handlers(sio, runtime_state)
register_texas_handlers(sio, runtime_state)
register_werewolf_handlers(sio, runtime_state)
register_matchmaking_handlers(sio, runtime_state)


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

# Note: Database initialization with retry logic is performed in the async startup handler
# to properly wait for MySQL to be ready in Docker environments.
# The init_db() function now includes retry logic for container startup scenarios.


# ============================================================================
# STARTUP AND SHUTDOWN HANDLERS
# ============================================================================

@app.on_event("startup")
async def startup_event():
    """
    Initialize services and restore persisted game states on server startup.
    
    This handler runs after the app is created and properly waits for:
    - MySQL database to be ready (with retry logic)
    - Redis connection
    - Game state restoration
    """
    # Initialize database with retry logic (waits for MySQL to be ready)
    print("Initializing database...")
    db_success = init_db(retry=True)
    if db_success:
        print("✓ Database initialized and tables created")
    else:
        print("⚠ Database initialization failed - some features may not work")
        print("  Make sure MySQL is running and credentials are correct")
    
    # Connect to Redis
    await redis_manager.connect()
    print("✓ RedisManager connected")
    
    # Restore persisted games from Redis
    try:
        active_game_ids = await redis_manager.list_active_games()

        if active_game_ids:
            print(f"Found {len(active_game_ids)} persisted games")
            restored_count = 0
            
            for game_id in active_game_ids:
                try:
                    state_data = await persistence_manager.restore_game_state(game_id)
                    
                    if state_data and state_data.get('state'):
                        state = state_data['state']
                        game_type = state_data.get('game_type', 'unknown')
                        
                        phase = state.get('phase', 'unknown')
                        
                        if game_type == 'werewolf':
                            # Only restore active werewolf games.
                            if phase in ['waiting', 'finished', 'aborted']:
                                print(f"  ⚠ Skipping inactive werewolf game: {game_id} (phase: {phase})")
                                await redis_manager.delete_game_data(game_id)
                                continue

                            # Restore werewolf game using from_dict
                            game = WerewolfGame.from_dict(state)
                            werewolf_games[game_id] = game
                            restored_count += 1
                            print(f"  ✓ Restored werewolf game: {game_id} (phase: {phase}, day: {game.day_count})")
                        elif game_type == 'texas':
                            # Restore poker tables even when waiting so players can
                            # reconnect to lobby state after restart.
                            if phase in ['finished', 'aborted']:
                                print(f"  ⚠ Skipping inactive poker table: {game_id} (phase: {phase})")
                                await redis_manager.delete_game_data(game_id)
                                continue

                            table = TexasGame.from_dict(state)
                            poker_tables[game_id] = table
                            restored_count += 1
                            print(f"  ✓ Restored poker table: {game_id} (phase: {phase})")
                        else:
                            print(f"  ⚠ Unknown game type: {game_type} for {game_id}")
                            
                except Exception as e:
                    print(f"  ⚠ Error restoring game {game_id}: {e}")
                    import traceback
                    traceback.print_exc()
            
            print(f"✓ Restored {restored_count} active games")
        else:
            print("No persisted games found")
    except Exception as e:
        print(f"⚠ Game restoration check failed: {e}")
        import traceback
        traceback.print_exc()
    
    # Start werewolf game timeout checker
    runtime_state.werewolf_timeout_task = asyncio.create_task(werewolf_timeout_checker())
    print("✓ Werewolf game timeout checker started")

    # Start poker game timeout checker
    runtime_state.poker_timeout_task = asyncio.create_task(poker_timeout_checker())
    print("✓ Poker game timeout checker started")


async def poker_timeout_checker():
    """
    Background task that enforces poker turn timeouts.

    Runs every POKER_TIMEOUT_CHECK_INTERVAL seconds and:
    1. Finds the current acting player for active hands
    2. Auto-check/fold on timeout
    3. Advances phase and emits showdown/reward events like manual actions
    """
    while True:
        try:
            await asyncio.sleep(POKER_TIMEOUT_CHECK_INTERVAL)

            for table_id, table in list(poker_tables.items()):
                await check_disconnected_texas_players(runtime_state, sio, table_id, table)
                engine = table.engine
                if engine.phase not in POKER_ACTIVE_PHASES:
                    continue

                current_sid = engine.current_player_sid
                if not current_sid:
                    continue

                if engine.get_turn_time_remaining() > 0:
                    continue

                print(f"[PokerTimeout] Table {table_id} player {current_sid} timed out")
                result = engine.handle_timeout(current_sid)

                if not result.get('success'):
                    print(f"[PokerTimeout] Failed to auto-act on {table_id}: {result.get('error')}")
                    continue

                # Keep wrapper timeout tracking aligned with engine state.
                table.update_player_action_time(current_sid)

                await sio.emit(
                    'PLAYER_TIMEOUT',
                    {
                        'table_id': table_id,
                        'player_sid': current_sid,
                        'action': result.get('action', 'fold'),
                        'timestamp': datetime.utcnow().isoformat(),
                    },
                    room=table_id,
                )

                # Keep hot/cold snapshot eventually consistent on auto-play paths.
                asyncio.create_task(table.save_checkpoint('timeout_action'))

                await broadcast_game_state(sio, runtime_state, table_id)

                if result.get('hand_over'):
                    winner_info = result.get('winner', {})
                    await sio.emit(
                        'hand_winner',
                        {
                            'winner': winner_info,
                            'reason': 'All other players folded',
                            'pot': winner_info.get('amount', 0),
                        },
                        room=table_id,
                    )
                    asyncio.create_task(table.save_checkpoint('hand_end'))
                    continue

                if result.get('advance_phase'):
                    phase_result = engine.advance_phase()
                    await broadcast_game_state(sio, runtime_state, table_id)
                    asyncio.create_task(table.save_checkpoint('phase_change'))

                    if engine.phase == PokerPhase.SHOWDOWN:
                        showdown_result = phase_result if isinstance(phase_result, dict) else {}
                        await sio.emit(
                            'showdown_reveal',
                            {
                                'player_hands': showdown_result.get(
                                    'player_hands', engine.get_all_hole_cards()
                                ),
                                'community_cards': engine.cards_to_strings(engine.community_cards),
                                'winners': showdown_result.get('winners', []),
                            },
                            room=table_id,
                        )
                        asyncio.create_task(table.save_checkpoint('showdown'))

        except asyncio.CancelledError:
            print("Poker timeout checker stopped")
            break
        except Exception as e:
            print(f"[PokerTimeout] Error in poker timeout checker: {e}")


# ============================================================================
# WEREWOLF GAME TIMEOUT CHECKER
# ============================================================================

async def werewolf_timeout_checker():
    """
    Background task that checks for phase timeouts in active werewolf games.
    
    Runs every WEREWOLF_TIMEOUT_CHECK_INTERVAL seconds and:
    1. Checks each active game for timeout
    2. If timeout, executes default actions and advances phase
    3. Broadcasts state updates to all players
    """
    # Active phases that can timeout
    ACTIVE_PHASES = {
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
            await asyncio.sleep(WEREWOLF_TIMEOUT_CHECK_INTERVAL)
            
            # Check each active game
            for game_id, game in list(werewolf_games.items()):
                # Skip games not in active phases
                if game.phase not in ACTIVE_PHASES:
                    continue
                
                # Check if phase has timed out
                time_remaining = game.get_time_remaining()
                if time_remaining <= 0:
                    print(f"[Timeout] Game {game_id} phase {game.phase.value} timed out")
                    
                    try:
                        # Handle timeout (executes default actions and advances phase)
                        old_phase = game.phase.value
                        result = await game.handle_phase_timeout()
                        new_phase = result.get('new_phase', game.phase.value)
                        
                        # Persist phase change
                        is_significant = (
                            new_phase in WEREWOLF_SIGNIFICANT_PHASES
                            or old_phase in WEREWOLF_SIGNIFICANT_PHASES
                        )
                        
                        await persistence_manager.on_phase_changed(
                            game_id=game_id,
                            new_phase=new_phase,
                            day_count=result.get('day_count', game.day_count),
                            game_state=game.to_dict(),
                            deaths=result.get('deaths', []),
                            significant=is_significant
                        )
                        
                        # Emit timeout notification
                        if result.get('timed_out_players'):
                            for nickname in result['timed_out_players']:
                                await sio.emit(
                                    'PLAYER_TIMEOUT',
                                    {
                                        'message': f'Player {nickname} Timed Out',
                                        'player': nickname,
                                        'timestamp': datetime.utcnow().isoformat(),
                                    },
                                    room=game_id,
                                )
                        
                        # Check if game was aborted
                        if result.get('aborted'):
                            await sio.emit(
                                'GAME_ABORTED',
                                {
                                    'message': result.get('reason', 'Game aborted'),
                                    'refund_players': result.get('refund_players', []),
                                    'timestamp': datetime.utcnow().isoformat(),
                                },
                                room=game_id,
                            )
                            await handle_werewolf_game_abort(
                                runtime_state,
                                sio,
                                game_id,
                                result.get('reason'),
                            )
                            continue
                        
                        # Emit phase change
                        await sio.emit(
                            'werewolf_phase_change',
                            {
                                'phase': result.get('new_phase'),
                                'day_count': result.get('day_count'),
                                'deaths': result.get('deaths', []),
                                'eliminated': result.get('eliminated'),
                                'game_over': result.get('game_over', False),
                                'winners': result.get('winners', []),
                            },
                            room=game_id,
                        )
                        
                        # Check if game ended
                        if result.get('game_over'):
                            await handle_werewolf_game_end(
                                runtime_state,
                                sio,
                                game_id,
                                result.get('winners', []),
                            )
                        
                        # Broadcast updated state to all players
                        await sio.emit(
                            'werewolf_state',
                            game.get_game_state(reveal_all=False),
                            room=game_id,
                        )
                        
                    except Exception as e:
                        print(f"[Timeout] Error handling timeout for game {game_id}: {e}")
                        import traceback
                        traceback.print_exc()
                        
        except asyncio.CancelledError:
            print("Werewolf timeout checker stopped")
            break
        except Exception as e:
            print(f"[Timeout] Error in werewolf timeout checker: {e}")



# ============================================================================
# FASTAPI ENDPOINTS
# ============================================================================

@app.get("/")
@limiter.limit("10/minute")
async def root(request: Request):
    """Root endpoint."""
    return {
        "name": "Arena Poker Game Engine",
        "version": "2.1.0",
        "status": "running",
        "local_debug_mode": LOCAL_DEBUG_MODE
    }


@app.get("/health")
@limiter.limit("30/minute")
async def health(request: Request):
    """Health check."""
    return {
        "status": "healthy",
        "active_tables": len(poker_tables),
        "local_debug_mode": LOCAL_DEBUG_MODE
    }


# ============================================================================
# BOT TOKEN ENDPOINT (Simplified - no challenge/PoW)
# ============================================================================

@app.post("/bot/token")
@limiter.limit("30/minute")
async def bot_get_token(request: Request, payload: TokenRequest):
    """
    Get a session token for AI agents.
    
    Simple flow: provide fingerprint → get token.
    No challenge, no proof-of-work needed.
    
    The token is used for Socket.IO authentication.
    """
    return await get_token(request, payload.fingerprint)


# ============================================================================
# AGENT ENDPOINTS
# ============================================================================

@app.post("/agent/register")
@limiter.limit("30/minute")
async def register_agent(request: Request):
    """
    Register a new AI agent and get an agent_id.
    
    This is optional - it helps identify your agent in logs.
    """
    new_agent_id = generate_agent_id()
    
    return {
        "agent_id": new_agent_id,
        "message": "Welcome, AI Agent!",
        "next_steps": [
            "1. POST /bot/token with {fingerprint} → get token",
            "2. Connect Socket.IO with auth: {botToken, fingerprint}",
            "3. Send authenticate event with {login_key} and start playing!"
        ]
    }


@app.get("/agent/instructions")
async def agent_instructions_endpoint():
    """
    Get instructions for AI agents to connect and play.
    
    This endpoint is public.
    """
    return get_agent_instructions()


# ============================================================================
# ECONOMY SYSTEM ENDPOINTS
# ============================================================================

@app.post("/api/register")
@limiter.limit("5/minute")
async def api_register(request: Request, player_name: str, address: Optional[str] = None):
    """
    Register a new user account.
    
    Creates a user account in the database with initial balance.
    """
    try:
        result = await register_user(player_name, address)
        return result
    except (InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@app.post("/api/login")
@limiter.limit("10/minute")
async def api_login(
    request: Request,
    login_key: Optional[str] = None,
):
    """
    Handle user login with daily reward check.
    
    Checks if it's a new UTC day and grants daily login reward if applicable.

    Accepts:
    - login_key: canonical login identifier
    """
    try:
        resolved_login_key = (login_key or "").strip()
        if not resolved_login_key:
            raise HTTPException(status_code=400, detail="login_key is required")

        result = await handle_login(resolved_login_key)
        return result
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


@app.get("/api/balance/{player_id}")
@limiter.limit("20/minute")
async def api_get_balance(request: Request, player_id: str):
    """Get user's current balance."""
    try:
        balance = await get_balance(player_id)
        return {
            "player_id": player_id,
            "balance": float(balance)
        }
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get balance: {str(e)}")


@app.get("/api/account/{player_id}")
@limiter.limit("10/minute")
async def api_get_account_summary(request: Request, player_id: str):
    """Get comprehensive account summary including validation and recent transactions."""
    try:
        summary = await get_account_summary(player_id)
        return summary
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get account summary: {str(e)}")


@app.post("/api/transfer")
@limiter.limit("5/minute")
async def api_transfer_balance(request: Request, from_player_id: str, to_player_id: str, amount: float):
    """Transfer balance between two accounts."""
    try:
        result = await transfer_balance(from_player_id, to_player_id, Decimal(str(amount)))
        return result
    except InvalidAmountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except InsufficientBalanceError as e:
        raise HTTPException(status_code=402, detail=str(e))  # 402 Payment Required
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Transfer failed: {str(e)}")


@app.post("/api/balances/batch")
@limiter.limit("10/minute")
async def api_batch_get_balances(request: Request, player_ids: List[str]):
    """Get balances for multiple player identifiers efficiently."""
    try:
        if len(player_ids) > 50:
            raise HTTPException(status_code=400, detail="Too many player IDs (max 50)")
        balances = await batch_get_balances(player_ids)
        return {
            "balances": {addr: float(bal) for addr, bal in balances.items()}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch balance query failed: {str(e)}")


@app.get("/api/games/active")
@limiter.limit("30/minute")
async def api_list_active_games(request: Request, q: Optional[str] = None):
    """
    List active poker tables and werewolf games for spectators.
    Optional substring filter via `q`.
    """
    q_lower = q.lower() if q else None

    def _filter(items):
        if not q_lower:
            return items
        return [item for item in items if q_lower in item.lower()]

    poker_list = _filter(list(poker_tables.keys()))
    werewolf_list = _filter(list(werewolf_games.keys()))

    return {
        "poker_tables": poker_list,
        "werewolf_games": werewolf_list,
        "total": {
            "poker": len(poker_list),
            "werewolf": len(werewolf_list)
        }
    }


@app.get("/api/leaderboard")
@limiter.limit("30/minute")
async def api_get_leaderboard(request: Request, limit: int = 10):
    """Get top players ranked by off-chain token balance."""
    try:
        if limit > 100:
            raise HTTPException(status_code=400, detail="Limit too large (max 100)")

        entries = await get_leaderboard(limit=limit)
        return {
            "entries": entries,
            "total": len(entries),
            "updated_at": datetime.utcnow().isoformat(),
        }
    except InvalidAmountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get leaderboard: {str(e)}")


@app.get("/api/spectate/poker/{table_id}")
@limiter.limit("30/minute")
async def api_spectate_poker(request: Request, table_id: str, reveal: bool = False):
    if reveal:
        raise HTTPException(
            status_code=400,
            detail="Reveal mode is only available via read-only Socket.IO spectate",
        )

    table = poker_tables.get(table_id)
    if not table:
        raise HTTPException(status_code=404, detail="Poker table not found")

    return table.get_game_state(for_spectator=True, reveal_all=False)


@app.get("/api/spectate/werewolf/{game_id}")
@limiter.limit("30/minute")
async def api_spectate_werewolf(request: Request, game_id: str, reveal: bool = False):
    if reveal:
        raise HTTPException(
            status_code=400,
            detail="Reveal mode is only available via read-only Socket.IO spectate",
        )

    game = werewolf_games.get(game_id)
    if not game:
        raise HTTPException(status_code=404, detail="Werewolf game not found")

    return game.get_game_state(reveal_all=False)



# ============================================================================
# GRACEFUL SHUTDOWN HANDLING
# ============================================================================

shutdown_event = asyncio.Event()

async def graceful_shutdown():
    """
    Handle graceful shutdown to prevent game state loss.
    
    Security improvement: Save active game states before shutdown.
    """
    print("\nGraceful shutdown initiated...")
    
    # Stop matchmaker
    if runtime_state.werewolf_matchmaker:
        runtime_state.werewolf_matchmaker.stop()
    if runtime_state.texas_matchmaker:
        runtime_state.texas_matchmaker.stop()

    # Stop background timeout task cleanly.
    if runtime_state.werewolf_timeout_task and not runtime_state.werewolf_timeout_task.done():
        runtime_state.werewolf_timeout_task.cancel()
        await asyncio.gather(runtime_state.werewolf_timeout_task, return_exceptions=True)

    if runtime_state.poker_timeout_task and not runtime_state.poker_timeout_task.done():
        runtime_state.poker_timeout_task.cancel()
        await asyncio.gather(runtime_state.poker_timeout_task, return_exceptions=True)
    
    # Notify all connected clients
    await sio.emit('server_shutdown', {
        'message': 'Server is shutting down',
        'timestamp': datetime.utcnow().isoformat()
    })
    
    # Save active game states to Redis for persistence
    print("Saving game states to Redis...")
    save_tasks = []
    
    # Save poker game states
    for table_id, game in poker_tables.items():
        save_tasks.append(game.save_checkpoint('shutdown'))
        save_tasks.append(game.close_redis())
    
    # Save werewolf game states
    for ww_game_id, game in werewolf_games.items():
        save_tasks.append(game.save_state_to_redis())
        save_tasks.append(game.close_redis())
    
    # Execute all save operations concurrently
    if save_tasks:
        await asyncio.gather(*save_tasks, return_exceptions=True)
    
    # Wait for ongoing operations to complete
    await asyncio.sleep(2)
    
    print("Shutdown complete")
    shutdown_event.set()


def handle_shutdown_signal(signum, frame):
    """Signal handler for graceful shutdown."""
    asyncio.create_task(graceful_shutdown())


# Register signal handlers
signal.signal(signal.SIGTERM, handle_shutdown_signal)
signal.signal(signal.SIGINT, handle_shutdown_signal)


# ============================================================================
# CREATE COMBINED ASGI APP
# ============================================================================

# Combine FastAPI and Socket.IO
asgi_app = socketio.ASGIApp(
    sio,
    other_asgi_app=app,
    socketio_path='/socket.io'
)


# ============================================================================
# MAIN ENTRY POINT
# ============================================================================

if __name__ == "__main__":
    import uvicorn
    
    print("=" * 70)
    if LOCAL_DEBUG_MODE:
        print("Arena Poker Server - LOCAL DEBUG MODE")
        print("⚠️  WARNING: Security features are DISABLED ⚠️")
    else:
        print("Arena Poker Server - Enhanced Security Edition")
    print("=" * 70)
    print(f"CORS allowed origins: {ALLOWED_ORIGINS}")
    print(f"Local Debug Mode: {LOCAL_DEBUG_MODE}")
    print("=" * 70)
    
    if LOCAL_DEBUG_MODE:
        print("\n⚠️  LOCAL DEBUG MODE FEATURES:")
        print("  ✓ Player ID based authentication")
        print("  ✓ Unlimited funds for all accounts")
        print("\n  ⚠️  DO NOT USE IN PRODUCTION!")
    else:
        print("\nSecurity features enabled:")
        print("  ✓ Rate limiting on all endpoints")
        print("  ✓ Configurable CORS whitelist")
        print("  ✓ Graceful shutdown handling")
    
    print("=" * 70)
    print("\nStarting server on http://0.0.0.0:8080")
    print("API docs available at: http://0.0.0.0:8080/docs")
    print("=" * 70)
    
    uvicorn.run(
        "main:asgi_app",
        host="0.0.0.0",
        port=8080,
        reload=True,
        log_level="info"
    )
