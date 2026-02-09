"""
main.py - The Server

FastAPI + Socket.IO server with agent authentication, game management,
and in-app token economy settlement.
"""

import asyncio
import signal
from datetime import datetime
from decimal import Decimal
from typing import Dict, Optional, List, Any

import socketio
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from database.models import TransactionType
from config.config import (
    LOCAL_DEBUG_MODE,
    ALLOWED_ORIGINS,
    ALLOWED_HOSTS,
    SOCKET_IO_LOGGER,
    SOCKET_ENGINEIO_LOGGER,
)
from config import (
    TEXAS_CHIP_TO_TOKEN_RATIO,
    WEREWOLF_PRIZE_MULTIPLIER,
)
from database.connection import init_db
from database.persistence_manager import persistence_manager
from database.redis_manager import redis_manager
from economy.account import (
    register_user, handle_login, add_balance, get_balance,
    get_account_summary, transfer_balance, batch_get_balances, deduct_balance,
    InvalidAmountError, InsufficientBalanceError, UserNotFoundError, InvalidWalletAddressError, unlock_balance,
    lock_balance, get_leaderboard
)
from games.texas import TexasGame, create_texas_game
from games.texas.texas_engine import PokerPhase
from games.texas.matchmaker import TexasMatchmaker
from games.werewolf.matchmaker import WerewolfMatchmaker
from games.werewolf.werewolf_game import WerewolfGame, WerewolfPhase
from manager.anti_bot_manager import (
    TokenRequest,
    get_token,
    verify_request_bot_token,
    verify_socket_auth,
    verify_agent_request,
    generate_agent_id,
    get_agent_instructions,
    is_public_endpoint,
)

# Werewolf game timeout check interval (seconds)
WEREWOLF_TIMEOUT_CHECK_INTERVAL = 5
WEREWOLF_SIGNIFICANT_PHASES = {'day_announcement', 'day_voting', 'finished', 'aborted'}

# Poker timeout check interval (seconds)
POKER_TIMEOUT_CHECK_INTERVAL = 1
POKER_ACTIVE_PHASES = {
    PokerPhase.PRE_FLOP,
    PokerPhase.FLOP,
    PokerPhase.TURN,
    PokerPhase.RIVER,
}


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
    allowed, reason, risk = await verify_request_bot_token(request)
    if not allowed:
        status = 429 if reason == "risk_blocked" else 403
        return JSONResponse(
            status_code=status,
            content={
                "error": "bot_protection",
                "code": reason,
                "challenge_required": reason in {"challenge_required", "invalid_token", "token_mismatch"},
                "risk": risk,
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
    is_valid, error_msg = await verify_agent_request(request)
    
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

# Game state management
poker_tables: Dict[str, TexasGame] = {}  # Using unified TexasGame architecture
werewolf_games: Dict[str, WerewolfGame] = {}  # game_id -> WerewolfGame
player_sessions: Dict[str, Dict] = {}  # sid -> {player_id, player_name, table_id, game_id, authenticated}
# Spectator reveal subscriptions by sid. Shape:
# {
#   sid: {
#     'poker': {table_id: reveal_bool},
#     'werewolf': {game_id: reveal_bool}
#   }
# }
spectator_subscriptions: Dict[str, Dict[str, Dict[str, bool]]] = {}

POKER_SPECTATOR_ROOM_PREFIX = "spectate:poker:"
WEREWOLF_SPECTATOR_ROOM_PREFIX = "spectate:werewolf:"

# Matchmaker for Werewolf games
werewolf_matchmaker: Optional[WerewolfMatchmaker] = None
texas_matchmaker: Optional[TexasMatchmaker] = None
werewolf_timeout_task: Optional[asyncio.Task] = None
poker_timeout_task: Optional[asyncio.Task] = None


def _set_spectator_subscription(sid: str, game_type: str, room_id: str, reveal: bool) -> None:
    """Track spectator reveal preference per room."""
    sid_subs = spectator_subscriptions.setdefault(sid, {'poker': {}, 'werewolf': {}})
    room_subs = sid_subs.setdefault(game_type, {})
    room_subs[room_id] = bool(reveal)


def _remove_spectator_subscription(sid: str, game_type: str, room_id: Optional[str] = None) -> None:
    """Remove one or all spectator subscriptions for a sid/game type."""
    sid_subs = spectator_subscriptions.get(sid)
    if not sid_subs:
        return

    if room_id:
        sid_subs.get(game_type, {}).pop(room_id, None)
    else:
        sid_subs[game_type] = {}

    if not sid_subs.get('poker') and not sid_subs.get('werewolf'):
        spectator_subscriptions.pop(sid, None)


def _iter_reveal_spectators(game_type: str, room_id: str):
    """Yield sids that subscribed with reveal=True for this room."""
    for sid, sid_subs in spectator_subscriptions.items():
        # Defense-in-depth: only read-only spectator sessions can receive
        # reveal-all state so active players cannot subscribe to hidden info.
        if sid_subs.get(game_type, {}).get(room_id) and _is_read_only_session(sid):
            yield sid


def _poker_spectator_room(table_id: str) -> str:
    return f"{POKER_SPECTATOR_ROOM_PREFIX}{table_id}"


def _werewolf_spectator_room(game_id: str) -> str:
    return f"{WEREWOLF_SPECTATOR_ROOM_PREFIX}{game_id}"


async def _emit_poker_event(table_id: str, event: str, payload: Dict) -> None:
    """Emit an event to poker players and spectator room."""
    await sio.emit(event, payload, room=table_id)
    await sio.emit(event, payload, room=_poker_spectator_room(table_id))


def _is_read_only_session(sid: str) -> bool:
    session = player_sessions.get(sid) or {}
    return bool(session.get('read_only') or session.get('spectator_mode'))


async def _reject_if_read_only(sid: str, action_name: str) -> bool:
    """Return True when action should be stopped due to read-only spectator session."""
    if _is_read_only_session(sid):
        await sio.emit('error', {
            'message': f"Read-only spectator session cannot perform '{action_name}'",
            'error_code': 'SPECTATOR_READ_ONLY'
        }, room=sid)
        return True
    return False


async def _emit_werewolf_event(game_id: str, event: str, payload: Dict) -> None:
    """Emit an event to werewolf players and spectator room."""
    await sio.emit(event, payload, room=game_id)
    await sio.emit(event, payload, room=_werewolf_spectator_room(game_id))


def _is_night_phase(phase: str) -> bool:
    return phase.startswith('night_')


def _build_werewolf_action_trace(
    game: WerewolfGame,
    sid: str,
    action: str,
    result: Dict[str, Any],
    target_sid: Optional[str],
    message: Optional[str],
    reveal: bool,
) -> Dict[str, Any]:
    """Build spectator action trace payload with masked/reveal variants."""
    actor = next((p for p in game.players if p.get('sid') == sid), None)
    actor_nickname = actor.get('nickname', 'Unknown') if actor else 'Unknown'
    phase = game.phase.value
    target_player = next((p for p in game.players if p.get('sid') == target_sid), None) if target_sid else None
    target_nickname = target_player.get('nickname') if target_player else None

    payload: Dict[str, Any] = {
        'game_id': game.game_id,
        'phase': phase,
        'actor_sid': sid,
        'actor_nickname': actor_nickname,
        'action': action,
        'timestamp': datetime.utcnow().isoformat(),
    }

    # Hide hidden-information targets during night actions in masked mode.
    hide_target = _is_night_phase(phase) and not reveal
    if action == 'wolf_chat':
        payload['message'] = (message or '') if reveal else '[hidden wolf chat]'
        payload['visibility'] = 'reveal_only' if reveal else 'hidden'
    elif action in {'chat', 'speak'}:
        payload['message'] = message or ''
        payload['visibility'] = 'public'
    elif action in {'night_kill', 'seer_check', 'witch_poison', 'hunter_shoot', 'vote'}:
        if target_sid is None:
            payload['target'] = None
        elif hide_target:
            payload['target'] = {'sid': target_sid, 'nickname': 'Hidden Target'}
        else:
            payload['target'] = {'sid': target_sid, 'nickname': target_nickname or 'Unknown'}
    elif action == 'witch_save':
        payload['target'] = None if hide_target else {
            'sid': game.pending_wolf_kill,
            'nickname': (next((p.get('nickname') for p in game.players if p.get('sid') == game.pending_wolf_kill), None) or 'Unknown')
            if game.pending_wolf_kill else None
        }

    # Include seer result only for reveal subscribers.
    if action == 'seer_check' and reveal and result.get('result'):
        payload['seer_result'] = result.get('result')

    return payload


async def _emit_werewolf_action_trace(
    game: WerewolfGame,
    sid: str,
    action: str,
    result: Dict[str, Any],
    target_sid: Optional[str],
    message: Optional[str],
) -> None:
    """Emit action timeline events to spectators (masked + reveal modes)."""
    game_id = game.game_id
    masked_payload = _build_werewolf_action_trace(game, sid, action, result, target_sid, message, reveal=False)
    await sio.emit('werewolf_action_trace', masked_payload, room=_werewolf_spectator_room(game_id))

    reveal_sids = list(_iter_reveal_spectators('werewolf', game_id))
    if reveal_sids:
        reveal_payload = _build_werewolf_action_trace(game, sid, action, result, target_sid, message, reveal=True)
        await _emit_to_sids('werewolf_action_trace', reveal_payload, reveal_sids)


async def _emit_to_sids(event: str, payload: Dict, sids: List[str]) -> None:
    """Emit same payload to many sockets concurrently."""
    if not sids:
        return
    await asyncio.gather(
        *(sio.emit(event, payload, room=target_sid) for target_sid in sids),
        return_exceptions=True,
    )


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
        # Check new optimized storage first
        active_game_ids = await redis_manager.list_active_games()
        legacy_game_ids = await redis_manager.list_persisted_games()
        
        all_game_ids = set(active_game_ids + legacy_game_ids)
        
        if all_game_ids:
            print(f"Found {len(all_game_ids)} persisted games")
            restored_count = 0
            
            for game_id in all_game_ids:
                try:
                    # Try new optimized storage first
                    state_data = await persistence_manager.restore_game_state(game_id)
                    
                    # Fallback to legacy storage
                    if not state_data:
                        state_data = await redis_manager.restore_game_state(game_id)
                    
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
    global werewolf_timeout_task
    werewolf_timeout_task = asyncio.create_task(werewolf_timeout_checker())
    print("✓ Werewolf game timeout checker started")

    # Start poker game timeout checker
    global poker_timeout_task
    poker_timeout_task = asyncio.create_task(poker_timeout_checker())
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

                await _emit_poker_event(table_id, 'PLAYER_TIMEOUT', {
                    'table_id': table_id,
                    'player_sid': current_sid,
                    'action': result.get('action', 'fold'),
                    'timestamp': datetime.utcnow().isoformat()
                })

                # Keep hot/cold snapshot eventually consistent on auto-play paths.
                asyncio.create_task(table.save_checkpoint('timeout_action'))

                await broadcast_game_state(table_id)

                if result.get('hand_over'):
                    winner_info = result.get('winner', {})
                    await _emit_poker_event(table_id, 'hand_winner', {
                        'winner': winner_info,
                        'reason': 'All other players folded',
                        'pot': winner_info.get('amount', 0)
                    })
                    asyncio.create_task(table.save_checkpoint('hand_end'))
                    continue

                if result.get('advance_phase'):
                    phase_result = engine.advance_phase()
                    await broadcast_game_state(table_id)
                    asyncio.create_task(table.save_checkpoint('phase_change'))

                    if engine.phase == PokerPhase.SHOWDOWN:
                        showdown_result = phase_result if isinstance(phase_result, dict) else {}
                        await _emit_poker_event(table_id, 'showdown_reveal', {
                            'player_hands': showdown_result.get('player_hands', engine.get_all_hole_cards()),
                            'community_cards': engine.cards_to_strings(engine.community_cards),
                            'winners': showdown_result.get('winners', [])
                        })
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
                                await _emit_werewolf_event(game_id, 'PLAYER_TIMEOUT', {
                                    'message': f'Player {nickname} Timed Out',
                                    'player': nickname,
                                    'timestamp': datetime.utcnow().isoformat()
                                })
                        
                        # Check if game was aborted
                        if result.get('aborted'):
                            await _emit_werewolf_event(game_id, 'GAME_ABORTED', {
                                'message': result.get('reason', 'Game aborted'),
                                'refund_players': result.get('refund_players', []),
                                'timestamp': datetime.utcnow().isoformat()
                            })
                            await handle_werewolf_game_abort(game_id, result.get('reason'))
                            continue
                        
                        # Emit phase change
                        await _emit_werewolf_event(game_id, 'werewolf_phase_change', {
                            'phase': result.get('new_phase'),
                            'day_count': result.get('day_count'),
                            'deaths': result.get('deaths', []),
                            'eliminated': result.get('eliminated'),
                            'game_over': result.get('game_over', False),
                            'winners': result.get('winners', [])
                        })
                        
                        # Check if game ended
                        if result.get('game_over'):
                            await handle_werewolf_game_end(game_id, result.get('winners', []))
                        
                        # Broadcast updated state to all players
                        await broadcast_werewolf_state(game_id)
                        
                    except Exception as e:
                        print(f"[Timeout] Error handling timeout for game {game_id}: {e}")
                        import traceback
                        traceback.print_exc()
                        
        except asyncio.CancelledError:
            print("Werewolf timeout checker stopped")
            break
        except Exception as e:
            print(f"[Timeout] Error in werewolf timeout checker: {e}")


async def handle_werewolf_game_end(game_id: str, winners: list):
    """
    Handle game end: record results and award winnings.
    
    Uses PersistenceManager for unified MySQL persistence.
    """
    game = werewolf_games.get(game_id)
    
    total_entry_fees = Decimal("0")
    prize_pool = Decimal("0")
    winner_team = None
    if game:
        total_entry_fees = sum(player['entry_fee_paid'] for player in game.players)
        prize_pool = total_entry_fees * WEREWOLF_PRIZE_MULTIPLIER

        if winners:
            # Check if any winner is a wolf
            for player in game.players:
                if player['wallet_address'] in winners:
                    if player.get('role') and hasattr(player['role'], 'team'):
                        winner_team = player['role'].team.value
                        break
    
    # Persist game end to MySQL
    try:
        await persistence_manager.on_game_ended(
            game_id=game_id,
            winner_team=winner_team,
            winners=winners,
            was_aborted=False,
            final_state=game.to_dict() if game else None,
            prize_pool=prize_pool
        )
    except Exception as e:
        print(f"Failed to persist game end: {e}")
        import traceback
        traceback.print_exc()
    
    # Handle prize distribution and refunds
    try:
        if game:
            await _unlock_werewolf_entry_fees(
                game,
                game_id,
                description="Werewolf entry fee principal unlock"
            )

        if game and winners:
            prize_per_winner = prize_pool / len(winners)

            print(f"Werewolf game prize pool: {float(prize_pool)} tokens from {len(winners)} winners")

            for winner_address in winners:
                await add_balance(
                    winner_address,
                    prize_per_winner,
                    tx_type=TransactionType.GAME_WIN,
                    description="Werewolf game prize"
                )
                print(f"Awarded {float(prize_per_winner)} tokens to winner: {winner_address[:8]}...")
        elif game and not winners:
            print("Werewolf game ended without winners, refunding entry fees")
        else:
            print("No game data found for prize distribution")
    except Exception as e:
        print(f"Failed to handle prize distribution: {e}")
        import traceback
        traceback.print_exc()


async def handle_werewolf_game_abort(game_id: str, reason: Optional[str] = None):
    """Handle werewolf game abort: record results and refund entry fees."""
    game = werewolf_games.get(game_id)

    try:
        await persistence_manager.on_game_ended(
            game_id=game_id,
            winner_team=None,
            winners=[],
            was_aborted=True,
            final_state=game.to_dict() if game else None,
            prize_pool=Decimal("0")
        )
    except Exception as e:
        print(f"Failed to persist aborted game end: {e}")
        import traceback
        traceback.print_exc()

    try:
        if game:
            await _unlock_werewolf_entry_fees(
                game,
                game_id,
                description="Werewolf game refund - aborted"
            )
            print(f"Werewolf game aborted: refunded entry fees ({reason or 'no reason'})")
        else:
            print("No game data found for aborted refund")
    except Exception as e:
        print(f"Failed to refund aborted werewolf game: {e}")
        import traceback
        traceback.print_exc()


async def _unlock_werewolf_entry_fees(game: WerewolfGame, game_id: str, description: str) -> None:
    """Unlock entry fees for all players in a werewolf game."""
    for player in game.players:
        entry_fee = player.get('entry_fee_paid') or Decimal("0")
        if entry_fee <= 0:
            continue
        await unlock_balance(
            player['wallet_address'],
            entry_fee,
            game_session_id=game_id,
            description=description
        )


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


# Legacy endpoints (redirect to /bot/token)
@app.post("/bot/challenge")
@limiter.limit("30/minute")
async def bot_challenge_legacy(request: Request, payload: TokenRequest):
    """Legacy endpoint - now just returns a token directly."""
    return await get_token(request, payload.fingerprint)


@app.post("/bot/verify")
@limiter.limit("30/minute")
async def bot_verify_legacy(request: Request, payload: TokenRequest):
    """Legacy endpoint - now just returns a token directly."""
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
    player_id: Optional[str] = None,
):
    """
    Handle user login with daily reward check.
    
    Checks if it's a new UTC day and grants daily login reward if applicable.

    Accepts either:
    - login_key: canonical login identifier (recommended)
    - player_id: backward-compatible alias
    """
    try:
        resolved_login_key = (login_key or player_id or "").strip()
        if not resolved_login_key:
            raise HTTPException(status_code=400, detail="login_key or player_id is required")

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
    """Return poker state for spectators.

    `reveal=true` is intentionally blocked for public HTTP endpoints to avoid
    hidden-info leakage without an authenticated read-only socket session.
    """
    if table_id not in poker_tables:
        raise HTTPException(status_code=404, detail="Table not found")
    if reveal:
        raise HTTPException(
            status_code=403,
            detail="Reveal mode is only available to read-only spectator Socket.IO sessions"
        )
    table = poker_tables[table_id]
    return table.get_game_state(for_spectator=True, reveal_all=False)


@app.get("/api/spectate/werewolf/{game_id}")
@limiter.limit("30/minute")
async def api_spectate_werewolf(request: Request, game_id: str, reveal: bool = False):
    """Return werewolf state for spectators.

    `reveal=true` is intentionally blocked for public HTTP endpoints to avoid
    hidden-role leakage without an authenticated read-only socket session.
    """
    if game_id not in werewolf_games:
        raise HTTPException(status_code=404, detail="Game not found")
    if reveal:
        raise HTTPException(
            status_code=403,
            detail="Reveal mode is only available to read-only spectator Socket.IO sessions"
        )
    game = werewolf_games[game_id]
    return game.get_game_state(reveal_all=False)


# ============================================================================
# SOCKET.IO EVENT HANDLERS
# ============================================================================

@sio.event
async def connect(sid, environ, auth):
    """
    Handle client connection.
    
    AGENT-ONLY: Only AI agents can connect via Socket.IO.
    Humans should use HTTP API endpoints for spectating.
    
    Verification (all in verify_socket_auth):
    1. Bot token verification (proof-of-work)
    2. Agent detection (User-Agent check)
    """
    # Combined bot token + agent verification
    allowed, reason = await verify_socket_auth(environ, auth)
    if not allowed:
        print(f"Rejected socket connection: {sid} ({reason})")
        return False
    
    # Extract agent_id from auth (optional but recommended)
    auth = auth or {}
    agent_id = auth.get("agent_id") or auth.get("agentId") or "anonymous"
    
    is_spectator_connection = reason == "spectator"
    role_label = "spectator" if is_spectator_connection else "agent"
    print(f"AI Client connected: {sid} (agent_id: {agent_id}, role: {role_label})")
    
    player_sessions[sid] = {
        'player_id': None,
        'player_name': None,
        'table_id': None,
        'game_id': None,
        'authenticated': False,
        'agent_id': agent_id,
        'read_only': is_spectator_connection,
        'spectator_mode': is_spectator_connection,
    }
    await sio.emit('connected', {
        'sid': sid,
        'agent_id': agent_id,
        'read_only': is_spectator_connection,
        'message': 'Welcome, AI Agent! You are connected to the arena.'
    }, room=sid)


@sio.event
async def disconnect(sid):
    """Handle client disconnection."""
    global werewolf_matchmaker, texas_matchmaker
    
    print(f"Client disconnected: {sid}")
    
    if sid in player_sessions:
        session = player_sessions[sid]
        
        # Remove from table if in one
        if session['table_id'] and session['table_id'] in poker_tables:
            table = poker_tables[session['table_id']]
            # Keep in-hand seats for reconnection and timeout auto-play.
            # Remove only when no hand is active.
            if table.engine.phase in POKER_ACTIVE_PHASES:
                print(f"[Disconnect] Preserving poker seat for reconnect: sid={sid}, table={session['table_id']}")
                # Persist SID-preserving in-hand state immediately so restart can
                # still recover the table even when no further action happens.
                asyncio.create_task(table.save_state_to_redis())
            else:
                table.remove_player(sid)
                await broadcast_game_state(session['table_id'])
        
        # Remove from matchmaking queue if in one
        if werewolf_matchmaker:
            werewolf_matchmaker.remove_player(sid)
        if texas_matchmaker:
            texas_matchmaker.remove_player(sid)
        
        del player_sessions[sid]

    # Always clear spectator reveal subscriptions for disconnected sockets.
    spectator_subscriptions.pop(sid, None)


@sio.event
async def authenticate(sid, data):
    """
    Authenticate a client using a login key.
    
    On successful authentication, checks if player was in an active game and sends
    GAME_SNAPSHOT for reconnection recovery.
    
    Expected data: {'login_key': str}
    Backward compatible: {'player_id': str}
    """
    try:
        if await _reject_if_read_only(sid, 'authenticate'):
            return

        data = data or {}
        login_key = data.get('login_key') or data.get('player_id') or data.get('address')
        if not login_key or not str(login_key).strip():
            await sio.emit('error', {'message': 'Missing login_key (or player_id)'}, room=sid)
            return

        login_key = str(login_key).strip()
        if len(login_key) > 128:
            await sio.emit('error', {'message': 'Login key too long (max 128)'}, room=sid)
            return

        login_result = await handle_login(login_key)
        user = login_result.get('user', {})
        player_id = user.get('player_id', '')
        player_name = user.get('player_name', 'Player')

        if not player_id:
            await sio.emit('error', {'message': 'Login succeeded but player_id missing'}, room=sid)
            return

        # Mark as authenticated
        player_sessions[sid]['player_id'] = player_id
        player_sessions[sid]['player_name'] = player_name
        player_sessions[sid]['authenticated'] = True

        await sio.emit('authenticated', {
            'player_id': player_id,
            'player_name': player_name,
        }, room=sid)

        # Check for reconnection to active game
        await handle_reconnection(sid, player_id)

    except Exception as e:
        await sio.emit('error', {'message': f'Authentication failed: {str(e)}'}, room=sid)


async def handle_reconnection(sid: str, player_id: str):
    """
    Handle reconnection by checking if player was in an active game.
    
    If found, updates the player's sid and sends GAME_SNAPSHOT.
    
    Args:
        sid: New socket ID
        player_id: Player identifier
    """
    # Inactive werewolf phases (no need to reconnect)
    INACTIVE_PHASES = {WerewolfPhase.WAITING, WerewolfPhase.FINISHED, WerewolfPhase.ABORTED}
    
    # Check werewolf games for this player id
    for game_id, game in werewolf_games.items():
        # Skip finished/aborted/waiting games
        if game.phase in INACTIVE_PHASES:
            continue
        
        # Find player by stored legacy wallet_address field (value is player_id)
        for player in game.players:
            if player['wallet_address'] == player_id:
                old_sid = player['sid']
                
                # Update player's socket ID
                if old_sid != sid:
                    game.update_player_sid(old_sid, sid)
                    print(f"[Reconnect] Player {player_id} reconnected to game {game_id}")
                
                # Update session
                player_sessions[sid]['game_id'] = game_id
                
                # Join Socket.IO room
                await sio.enter_room(sid, game_id)
                
                # Send GAME_SNAPSHOT for recovery
                snapshot = game.get_game_snapshot(sid)
                await sio.emit('GAME_SNAPSHOT', snapshot, room=sid)
                
                print(f"[Reconnect] Sent GAME_SNAPSHOT to {player_id} for game {game_id}")
                return
    
    # Check poker tables for this player_id
    for table_id, table in poker_tables.items():
        for player in table.players:
            if player.get('wallet_address', '') == player_id:
                old_sid = player.get('sid')

                # Rebind player seat/state to the new socket id so turn checks,
                # private hand delivery, and action routing continue to work.
                if old_sid and old_sid != sid:
                    table.engine.update_player_sid(old_sid, sid)
                    player['sid'] = sid
                    asyncio.create_task(table.save_checkpoint('reconnect_rebind'))

                # Update session
                player_sessions[sid]['table_id'] = table_id
                
                # Join Socket.IO room
                await sio.enter_room(sid, table_id)
                
                # Send game state
                await sio.emit('GAME_SNAPSHOT', table.get_game_snapshot(sid), room=sid)
                
                print(f"[Reconnect] Sent GAME_SNAPSHOT to {player_id} for poker table {table_id}")
                return


@sio.event
async def join_game(sid, data):
    """
    Join or create a game table.
    
    Expected data: {'table_id': str, 'chips': int (optional)}
    """
    try:
        if await _reject_if_read_only(sid, 'join_game'):
            return

        # Check authentication
        if sid not in player_sessions or not player_sessions[sid]['authenticated']:
            await sio.emit('error', {'message': 'Not authenticated'}, room=sid)
            return
        
        table_id = data.get('table_id')
        player_id = player_sessions[sid]['player_id']
        player_name = player_sessions[sid]['player_name'] or 'Player'

        # 支持chips或tokens买入，默认使用chips
        if 'tokens' in data:
            buy_in_tokens = Decimal(str(data['tokens']))
            buy_in_chips = buy_in_tokens / TEXAS_CHIP_TO_TOKEN_RATIO
        else:
            buy_in_chips = Decimal(str(data.get('chips', 1000)))
            buy_in_tokens = buy_in_chips * TEXAS_CHIP_TO_TOKEN_RATIO

        if not table_id:
            await sio.emit('error', {'message': 'table_id required'}, room=sid)
            return

        # 检查余额是否足够
        try:
            current_balance = await get_balance(player_id)
            if current_balance < buy_in_tokens:
                await sio.emit('error', {
                    'message': f'Insufficient balance. Required: {float(buy_in_tokens)} tokens, Available: {float(current_balance)}'
                }, room=sid)
                return
        except Exception as e:
            await sio.emit('error', {'message': f'Balance check failed: {str(e)}'}, room=sid)
            return

        # Create table if it doesn't exist
        if table_id not in poker_tables:
            poker_tables[table_id] = create_texas_game(table_id)

        table = poker_tables[table_id]

        # Add player to table with token amount
        if not table.add_player(sid, player_id, nickname=player_name, buy_in_tokens=buy_in_tokens):
            await sio.emit('error', {'message': 'Could not join table'}, room=sid)
            return

        # 锁定资金
        try:
            await lock_balance(player_id, buy_in_tokens, game_session_id=table_id)
        except Exception as e:
            await sio.emit('error', {'message': f'Failed to lock funds: {str(e)}'}, room=sid)
            # 移除玩家
            table.remove_player(sid)
            return
        
        # Update session
        player_sessions[sid]['table_id'] = table_id
        
        # Join Socket.IO room
        await sio.enter_room(sid, table_id)
        
        # Notify player
        await sio.emit('joined_game', {
            'table_id': table_id,
            'player_id': player_id,
            'player_name': player_name,
        }, room=sid)
        
        # Broadcast updated state
        await broadcast_game_state(table_id)
        
    except Exception as e:
        await sio.emit('error', {'message': f'Join game failed: {str(e)}'}, room=sid)


@sio.event
async def start_hand(sid, data):
    """
    Start a new hand at the table.
    
    Expected data: {'table_id': str}
    """
    try:
        if await _reject_if_read_only(sid, 'start_hand'):
            return

        table_id = data.get('table_id')
        
        if not table_id or table_id not in poker_tables:
            await sio.emit('error', {'message': 'Invalid table_id'}, room=sid)
            return
        
        table = poker_tables[table_id]
        
        # TexasGame exposes start_game() in the BaseGame interface.
        if not table.start_game():
            await sio.emit('error', {'message': 'Not enough players to start'}, room=sid)
            return

        asyncio.create_task(table.save_checkpoint('hand_start'))
        
        # Broadcast updated state
        await broadcast_game_state(table_id)
        
    except Exception as e:
        await sio.emit('error', {'message': f'Start hand failed: {str(e)}'}, room=sid)


@sio.event
async def player_move(sid, data):
    """
    Process a player action.
    
    Expected data: {
        'table_id': str,
        'action': str ('fold', 'check', 'call', 'raise'),
        'amount': int (optional, for raise),
        'message': str (optional, for chat/bluff)
    }
    """
    try:
        if await _reject_if_read_only(sid, 'player_move'):
            return

        table_id = data.get('table_id')
        action = data.get('action')
        amount = data.get('amount', 0)
        chat_message = data.get('message')
        
        if not table_id or table_id not in poker_tables:
            await sio.emit('error', {'message': 'Invalid table_id'}, room=sid)
            return
        
        if not action:
            await sio.emit('error', {'message': 'Action required'}, room=sid)
            return
        
        table = poker_tables[table_id]
        action_kwargs = {}
        if action == 'raise':
            action_kwargs['amount'] = amount
        if chat_message:
            action_kwargs['message'] = chat_message

        result = table.process_action(sid, action, **action_kwargs)
        
        if not result['success']:
            await sio.emit('error', {'message': result.get('error', 'Action failed')}, room=sid)
            return
        
        # Notify player if their chat message was blocked due to phase restriction
        if result.get('chat_blocked'):
            await sio.emit('error', {
                'message': 'Chat is not allowed during active hand',
                'error_code': 'CHAT_PHASE_RESTRICTED'
            }, room=sid)
        
        # Only persist chat if it was actually accepted (not stripped by phase restriction)
        if chat_message and not result.get('chat_blocked'):
            player = next((p for p in table.players if p.get('sid') == sid), None)
            if player:
                message_type = 'chat' if action == 'chat' else 'action'
                metadata = {'action': action} if action != 'chat' else None
                asyncio.create_task(
                    persistence_manager.save_chat_message(
                        game_id=table_id,
                        game_type=table.game_type,
                        player_id=player.get('wallet_address', ''),
                        nickname=player.get('nickname', 'Player'),
                        message=chat_message,
                        message_type=message_type,
                        metadata=metadata
                    )
                )
        
        # Broadcast updated state
        await broadcast_game_state(table_id)
        
        # Check if hand ended (everyone else folded)
        if result.get('hand_over'):
            winner_info = result.get('winner', {})
            await _emit_poker_event(table_id, 'hand_winner', {
                'winner': winner_info,
                'reason': 'All other players folded',
                'pot': winner_info.get('amount', 0)
            })

            asyncio.create_task(table.save_checkpoint('hand_end'))
            
            if winner_info.get('amount', 0) > 0:
                winner_sid = winner_info.get('sid')
                winner_player = None
                for p in table.players:
                    if p.get('sid') == winner_sid:
                        winner_player = p
                        break
                
                if winner_player:
                    # Winnings stay in-table as chips until player leaves and settles.
                    pass
            return
        
        # Check if round complete and advance phase
        if result.get('advance_phase'):
            phase_result = table.engine.advance_phase()
            await broadcast_game_state(table_id)
            asyncio.create_task(table.save_checkpoint('phase_change'))
            
            # Check for showdown (advance_phase already computes showdown results)
            if table.engine.phase.value == 'showdown':
                showdown_result = phase_result if isinstance(phase_result, dict) else {}
                
                # Broadcast showdown reveal with all hole cards visible
                await _emit_poker_event(table_id, 'showdown_reveal', {
                    'player_hands': showdown_result.get('player_hands', table.engine.get_all_hole_cards()),
                    'community_cards': table.engine.cards_to_strings(table.engine.community_cards),
                    'winners': showdown_result.get('winners', [])
                })
                asyncio.create_task(table.save_checkpoint('showdown'))
                
                for winner in showdown_result.get('winners', []):
                    if winner.get('amount', 0) > 0:
                        winner_sid = winner.get('sid')
                        # Find player by sid from the list
                        winner_player = None
                        for p in table.players:
                            if p.get('sid') == winner_sid:
                                winner_player = p
                                break
                        
                        if winner_player:
                            # Winnings stay in-table as chips until player leaves and settles.
                            pass

        # Non-critical action checkpoint (throttled MySQL, always-hot Redis).
        asyncio.create_task(table.save_checkpoint('action'))
        
    except Exception as e:
        await sio.emit('error', {'message': f'Player move failed: {str(e)}'}, room=sid)


@sio.event
async def poker_action(sid, data):
    """
    Alternative handler for poker actions (used in SKILL.md).
    
    This is an alias for player_move that matches the protocol in SKILL.md.
    
    Expected data: {
        'game_id': str,
        'action': str ('fold', 'check', 'call', 'raise'),
        'amount': int (optional, for raise),
        'message': str (optional, for chat/bluff)
    }
    """
    if await _reject_if_read_only(sid, 'poker_action'):
        return

    # Convert game_id to table_id for compatibility
    data['table_id'] = data.get('game_id', data.get('table_id'))
    await player_move(sid, data)


@sio.event
async def get_state(sid, data):
    """
    Get current game state.
    
    Expected data: {'table_id': str}
    """
    try:
        table_id = data.get('table_id')
        
        if not table_id or table_id not in poker_tables:
            await sio.emit('error', {'message': 'Invalid table_id'}, room=sid)
            return
        
        table = poker_tables[table_id]
        state = table.get_game_state(sid)
        
        await sio.emit('game_state', state, room=sid)
        
    except Exception as e:
        await sio.emit('error', {'message': f'Get state failed: {str(e)}'}, room=sid)


@sio.event
async def join_spectate(sid, data):
    """
    Join spectator room for poker or werewolf.

    Expected data:
      - Poker: {'table_id': str, 'reveal': bool (optional)}
      - Werewolf: {'game_id': str, 'reveal': bool (optional)}
    """
    try:
        payload = data or {}
        reveal_requested = bool(payload.get('reveal', False))
        reveal_allowed = reveal_requested and _is_read_only_session(sid)
        table_id = payload.get('table_id')
        game_id = payload.get('game_id')
        joined_any = False

        if reveal_requested and not reveal_allowed:
            await sio.emit('error', {
                'message': 'Reveal mode is only available to read-only spectator sessions',
                'error_code': 'SPECTATOR_REVEAL_FORBIDDEN'
            }, room=sid)

        if table_id and table_id in poker_tables:
            poker_room = _poker_spectator_room(table_id)
            if reveal_allowed:
                # Avoid duplicate masked+reveal payloads for reveal subscribers.
                await sio.leave_room(sid, poker_room)
            else:
                await sio.enter_room(sid, poker_room)
            _set_spectator_subscription(sid, 'poker', table_id, reveal_allowed)
            table = poker_tables[table_id]
            state = table.get_game_state(for_spectator=True, reveal_all=reveal_allowed)
            await sio.emit('game_state', state, room=sid)
            joined_any = True

        if game_id and game_id in werewolf_games:
            werewolf_room = _werewolf_spectator_room(game_id)
            if reveal_allowed:
                # Avoid duplicate masked+reveal payloads for reveal subscribers.
                await sio.leave_room(sid, werewolf_room)
            else:
                await sio.enter_room(sid, werewolf_room)
            _set_spectator_subscription(sid, 'werewolf', game_id, reveal_allowed)
            game = werewolf_games[game_id]
            state = game.get_game_state(reveal_all=reveal_allowed)
            await sio.emit('werewolf_state', state, room=sid)
            joined_any = True

        if not joined_any:
            await sio.emit('error', {
                'message': 'No valid table_id/game_id to spectate'
            }, room=sid)

    except Exception as e:
        await sio.emit('error', {'message': f'Join spectate failed: {str(e)}'}, room=sid)


@sio.event
async def leave_spectate(sid, data):
    """Leave spectator room for poker or werewolf."""
    try:
        table_id = (data or {}).get('table_id')
        game_id = (data or {}).get('game_id')

        if table_id:
            await sio.leave_room(sid, _poker_spectator_room(table_id))
            _remove_spectator_subscription(sid, 'poker', table_id)
        if game_id:
            await sio.leave_room(sid, _werewolf_spectator_room(game_id))
            _remove_spectator_subscription(sid, 'werewolf', game_id)

    except Exception as e:
        await sio.emit('error', {'message': f'Leave spectate failed: {str(e)}'}, room=sid)


@sio.event
async def leave_game(sid, data):
    """
    Leave the current table.
    
    Expected data: {'table_id': str}
    """
    try:
        if await _reject_if_read_only(sid, 'leave_game'):
            return

        table_id = data.get('table_id')
        
        if not table_id or table_id not in poker_tables:
            await sio.emit('error', {'message': 'Invalid table_id'}, room=sid)
            return
        
        table = poker_tables[table_id]

        if table.engine.phase in POKER_ACTIVE_PHASES:
            await sio.emit('error', {
                'message': 'Cannot leave during active hand. Fold or wait for the hand to finish.'
            }, room=sid)
            return
        
        # Capture balances before remove to settle locked funds correctly.
        player_dict = next((p for p in table.players if p.get('sid') == sid), None)
        engine_player = table.engine.players.get(sid)
        
        # Remove from table
        table.remove_player(sid)

        if sid in table.engine.players:
            await sio.emit('error', {
                'message': 'Leave request deferred until the current hand completes.'
            }, room=sid)
            return
        
        # Leave Socket.IO room
        await sio.leave_room(sid, table_id)
        
        # Update session
        if sid in player_sessions:
            player_sessions[sid]['table_id'] = None
        
        # Settle table funds on leave so locked balance is fully released.
        # Current accounting model locks full buy-in at join; on leave we:
        # 1) unlock full principal (buy-in) to clear locked funds
        # 2) apply PnL delta separately (win => add, loss => deduct)
        if player_dict and engine_player:
            wallet_address = player_dict['wallet_address']
            buy_in_tokens = Decimal(str(player_dict.get('buy_in_tokens', 0) or 0))
            chips_tokens = Decimal(str(engine_player.chips * TEXAS_CHIP_TO_TOKEN_RATIO))

            # In normal mode this clears all lock; in local debug it's a no-op.
            if buy_in_tokens > 0:
                await unlock_balance(
                    wallet_address,
                    buy_in_tokens,
                    game_session_id=table_id,
                    description="Texas Hold'em buy-in principal unlock"
                )

            pnl_delta = chips_tokens - buy_in_tokens
            if pnl_delta > 0:
                await add_balance(
                    wallet_address,
                    pnl_delta,
                    tx_type=TransactionType.GAME_WIN,
                    description="Texas Hold'em settlement profit"
                )
            elif pnl_delta < 0:
                await deduct_balance(
                    wallet_address,
                    -pnl_delta,
                    tx_type=TransactionType.GAME_ENTRY,
                    description="Texas Hold'em settlement loss"
                )
        
        # Notify player
        await sio.emit('left_game', {'table_id': table_id}, room=sid)
        
        # Broadcast updated state
        await broadcast_game_state(table_id)
        
    except Exception as e:
        await sio.emit('error', {'message': f'Leave game failed: {str(e)}'}, room=sid)


async def broadcast_game_state(table_id: str):
    """
    Broadcast game state to all players at the table with Privacy Filter.
    
    Implements the unified room broadcast architecture:
    1. Public Payload (game_update): All players' hole_cards are MASKED as ["??", "??"]
    2. Private Payload (private_hand): Each agent receives their own hole cards separately
    
    Also saves state to Redis for persistence.
    """
    if table_id not in poker_tables:
        return
    
    table = poker_tables[table_id]
    engine = table.engine
    
    is_showdown = engine.phase.value == 'showdown'
    
    # Build public player list with MASKED hole cards (unless showdown)
    public_players = []
    for player_sid in engine.player_order:
        player = engine.players.get(player_sid)
        if not player:
            continue
        
        player_info = {
            'sid': player_sid,
            'wallet_address': player.wallet_address,
            'nickname': player.nickname,
            'chips': player.chips,
            'current_bet': player.current_bet,
            'status': player.status.value,
            'last_action': player.last_action,
            # CRITICAL: Mask hole cards unless showdown
            'hole_cards': engine.cards_to_strings(player.hole_cards) if is_showdown else ['??', '??']
        }
        public_players.append(player_info)
    
    # Get current player from source-of-truth SID to avoid legacy index drift.
    current_player = None
    if engine.current_player_sid and engine.current_player_sid in engine.players:
        if engine.players[engine.current_player_sid].can_act():
            current_player = engine.current_player_sid
    
    # Build public game state (game_update event)
    public_state = {
        'game_id': table_id,
        'phase': engine.phase.value,
        'hand_number': engine.hand_number,
        'community_cards': engine.cards_to_strings(engine.community_cards),
        'pot': engine.get_total_pot(),
        'current_bet': engine.current_bet,
        'min_raise': engine.current_bet + engine.last_raise_amount,
        'current_player': current_player,
        'players': public_players,
        'chat_history': [
            {
                'nickname': msg.player_nickname,
                'message': msg.message,
                'action': msg.action,
                'timestamp': msg.timestamp
            }
            for msg in engine.chat_history[-20:]
        ],
        'timestamp': datetime.utcnow().isoformat()
    }
    
    # STEP 1: Broadcast public state to all players in the room (game_update)
    await sio.emit('game_update', public_state, room=table_id)
    await sio.emit('game_update', public_state, room=_poker_spectator_room(table_id))

    # STEP 1b: Push reveal-mode spectator payloads directly via Socket.IO.
    reveal_sids = list(_iter_reveal_spectators('poker', table_id))
    if reveal_sids:
        reveal_state = table.get_game_state(for_spectator=True, reveal_all=True)
        await _emit_to_sids('game_update', reveal_state, reveal_sids)
    
    # STEP 2: Send private_hand to each agent (their own hole cards only)
    if not is_showdown:
        for player_dict in table.players:
            player_sid = player_dict['sid']
            player = engine.players.get(player_sid)
            if player and player.hole_cards:
                private_payload = {
                    'game_id': table_id,
                    'hole_cards': engine.cards_to_strings(player.hole_cards),
                    'your_turn': player_sid == current_player,
                    'timestamp': datetime.utcnow().isoformat()
                }
                await sio.emit('private_hand', private_payload, room=player_sid)
    
    # Save state to Redis for hot storage (non-blocking)
    asyncio.create_task(table.save_state_to_redis())


# ============================================================================
# WEREWOLF GAME SOCKET.IO HANDLERS
# ============================================================================

@sio.event
async def create_werewolf_game(sid, data):
    """
    Create a new Werewolf game.
    
    Expected data: {'game_id': str, 'entry_fee': float (optional)}
    """
    try:
        if await _reject_if_read_only(sid, 'create_werewolf_game'):
            return

        # Check authentication
        if sid not in player_sessions or not player_sessions[sid]['authenticated']:
            await sio.emit('error', {'message': 'Not authenticated'}, room=sid)
            return
        
        game_id = data.get('game_id')
        entry_fee = Decimal(str(data.get('entry_fee', 0)))
        
        if not game_id:
            await sio.emit('error', {'message': 'game_id required'}, room=sid)
            return
        
        # Use distributed lock to prevent race conditions on game creation
        async with redis_manager.lock(f"game_create:{game_id}"):
            # Create game if doesn't exist
            if game_id in werewolf_games:
                await sio.emit('error', {'message': 'Game already exists'}, room=sid)
                return
            
            werewolf_games[game_id] = WerewolfGame(game_id, entry_fee=entry_fee)
            
            # Persist to MySQL (cold storage)
            await persistence_manager.on_game_created(
                game_id=game_id,
                game_type="werewolf",
                entry_fee=entry_fee
            )
            
            # Persist core state to Redis (hot storage)
            await redis_manager.save_game_core(
                game_id,
                werewolf_games[game_id].get_core_state(),
                game_type="werewolf"
            )
        
        await sio.emit('werewolf_game_created', {'game_id': game_id}, room=sid)
        
    except Exception as e:
        await sio.emit('error', {'message': f'Create game failed: {str(e)}'}, room=sid)


@sio.event
async def join_werewolf_game(sid, data):
    """
    Join a Werewolf game.
    
    Expected data: {'game_id': str, 'nickname': str (optional)}
    """
    try:
        if await _reject_if_read_only(sid, 'join_werewolf_game'):
            return

        # Check authentication
        if sid not in player_sessions or not player_sessions[sid]['authenticated']:
            await sio.emit('error', {'message': 'Not authenticated'}, room=sid)
            return
        
        game_id = data.get('game_id')
        nickname = player_sessions[sid]['player_name'] or 'Player'
        
        if not game_id or game_id not in werewolf_games:
            await sio.emit('error', {'message': 'Invalid game_id'}, room=sid)
            return
        
        player_id = player_sessions[sid]['player_id']
        game = werewolf_games[game_id]

        # 检查余额是否足够支付入场费
        try:
            current_balance = await get_balance(player_id)
            if current_balance < game.entry_fee:
                await sio.emit('error', {
                    'message': f'Insufficient balance. Required: {float(game.entry_fee)} tokens, Available: {float(current_balance)}'
                }, room=sid)
                return
        except Exception as e:
            await sio.emit('error', {'message': f'Balance check failed: {str(e)}'}, room=sid)
            return

        # Use distributed lock to prevent race conditions on player join
        async with redis_manager.lock(f"game_join:{game_id}"):
            # Add player to game
            if not game.add_player(sid, player_id, nickname=nickname):
                await sio.emit('error', {'message': 'Could not join game'}, room=sid)
                return

            # 锁定入场费
            try:
                await lock_balance(player_id, game.entry_fee, game_session_id=game_id)
            except Exception as e:
                await sio.emit('error', {'message': f'Failed to lock entry fee: {str(e)}'}, room=sid)
                # 移除玩家
                game.remove_player(sid)
                return
            
            # Update session
            player_sessions[sid]['game_id'] = game_id
            
            # Persist to MySQL (player record)
            await persistence_manager.on_player_joined(
                game_id=game_id,
                player_id=player_id,
                socket_sid=sid,
                nickname=nickname,
                entry_paid=game.entry_fee
            )
            
            # Persist core state to Redis
            await redis_manager.save_game_core(
                game_id,
                game.get_core_state(),
                game_type="werewolf"
            )
        
        # Join Socket.IO room
        await sio.enter_room(sid, game_id)
        
        # Notify player
        await sio.emit('werewolf_joined', {
            'game_id': game_id,
            'player_id': player_id,
            'player_name': nickname,
        }, room=sid)
        
        # Broadcast updated state to all players in game
        await broadcast_werewolf_state(game_id)
        
    except Exception as e:
        await sio.emit('error', {'message': f'Join werewolf game failed: {str(e)}'}, room=sid)


@sio.event
async def start_werewolf_game(sid, data):
    """
    Start a Werewolf game.
    
    Expected data: {'game_id': str}
    """
    try:
        if await _reject_if_read_only(sid, 'start_werewolf_game'):
            return

        game_id = data.get('game_id')
        
        if not game_id or game_id not in werewolf_games:
            await sio.emit('error', {'message': 'Invalid game_id'}, room=sid)
            return
        
        game = werewolf_games[game_id]
        
        if not game.start_game():
            await sio.emit('error', {'message': 'Cannot start game (need more players)'}, room=sid)
            return
        
        # Prepare player data with roles for MySQL persistence
        players_with_roles = []
        for player in game.players:
            player_data = {
                'wallet_address': player['wallet_address'],
                'role_type': player['role'].role_type.value if player.get('role') else None,
                'team': player['role'].team.value if player.get('role') else None
            }
            players_with_roles.append(player_data)
        
        # Persist game start to MySQL and Redis
        await persistence_manager.on_game_started(
            game_id=game_id,
            players_with_roles=players_with_roles,
            initial_state=game.to_dict()
        )
        
        # Broadcast updated state
        await broadcast_werewolf_state(game_id)
        
    except Exception as e:
        await sio.emit('error', {'message': f'Start werewolf game failed: {str(e)}'}, room=sid)


@sio.event
async def werewolf_action(sid, data):
    """
    Process a Werewolf game action.
    
    Expected data: {
        'game_id': str,
        'action': str,  # Actions by phase:
            # Night Wolf Discussion: 'wolf_chat' (message required)
            # Night Wolf Voting: 'night_kill' (target_sid required)
            # Night Seer: 'seer_check' (target_sid required)
            # Night Witch: 'witch_save', 'witch_poison' (target_sid for poison), 'witch_skip'
            # Night/Day Hunter: 'hunter_shoot' (target_sid optional, None = skip)
            # Day Speaking: 'speak' (message required)
            # Day Voting: 'vote' (target_sid optional, None = abstain)
            # Any time: 'chat' (message required, public chat)
        'target_sid': str (optional, depends on action),
        'message': str (optional, for chat/speak/wolf_chat)
    }
    """
    try:
        if await _reject_if_read_only(sid, 'werewolf_action'):
            return

        game_id = data.get('game_id')
        action = data.get('action')
        target_sid = data.get('target_sid')
        message = data.get('message')
        
        if not game_id or game_id not in werewolf_games:
            await sio.emit('error', {'message': 'Invalid game_id'}, room=sid)
            return
        
        if not action:
            await sio.emit('error', {'message': 'Action required'}, room=sid)
            return
        
        game = werewolf_games[game_id]
        
        # Emit "thinking" state for non-chat actions
        if action not in ['chat', 'wolf_chat']:
            await _emit_werewolf_event(game_id, 'player_thinking', {
                'game_id': game_id,
                'player_sid': sid,
                'action_type': action
            })
        
        # Build kwargs for action
        kwargs = {}
        if target_sid is not None:  # Allow None for abstain/skip
            kwargs['target_sid'] = target_sid
        if message:
            kwargs['message'] = message
        
        result = game.process_action(sid, action, **kwargs)
        
        if not result['success']:
            error_payload = {'message': result.get('error', 'Action failed')}
            if result.get('error_code'):
                error_payload['error_code'] = result['error_code']
            await sio.emit('error', error_payload, room=sid)
            return
        
        # Send action confirmation to the player
        await sio.emit('werewolf_action_result', result, room=sid)

        # Emit spectator timeline event (masked public feed + reveal-only enrichment).
        await _emit_werewolf_action_trace(game, sid, action, result, target_sid, message)
        
        if action in ['chat', 'wolf_chat'] and message:
            player = next((p for p in game.players if p['sid'] == sid), None)
            if player:
                metadata = {'phase': game.phase.value, 'is_wolf_chat': action == 'wolf_chat'}
                asyncio.create_task(
                    persistence_manager.save_chat_message(
                        game_id=game_id,
                        game_type=game.game_type,
                        player_id=player['wallet_address'],
                        nickname=player['nickname'],
                        message=message,
                        message_type=action,
                        metadata=metadata
                    )
                )
        
        # Handle wolf_chat broadcast to other wolves only
        # (Chat stored in-memory in WerewolfGame, broadcast via Socket.IO)
        if action == 'wolf_chat' and result.get('wolf_only'):
            wolf_sids = [p['sid'] for p in game.players 
                        if p.get('role') and hasattr(p['role'], 'role_type') 
                        and p['role'].role_type.value == 'wolf']
            for wolf_sid in wolf_sids:
                if wolf_sid != sid:
                    await sio.emit('wolf_chat_message', result.get('chat'), room=wolf_sid)

            # Reveal spectators should observe wolf dialogue in realtime.
            reveal_sids = list(_iter_reveal_spectators('werewolf', game_id))
            await _emit_to_sids('wolf_chat_message', result.get('chat'), reveal_sids)
        
        # Handle public chat broadcast
        # (Chat stored in-memory in WerewolfGame, broadcast via Socket.IO)
        elif action == 'chat':
            await _emit_werewolf_event(game_id, 'chat_message', result.get('chat'))
        
        # Handle speak action (persist to MySQL for permanent history)
        elif action == 'speak':
            player = next((p for p in game.players if p['sid'] == sid), None)
            if player:
                asyncio.create_task(
                    persistence_manager.save_speech(
                        game_id=game_id,
                        player_id=player['wallet_address'],
                        nickname=player['nickname'],
                        message=message or '',
                        phase=game.phase.value,
                        game_type=game.game_type
                    )
                )
        
        # Persist core game state after non-chat actions
        if action not in ['chat', 'wolf_chat']:
            await redis_manager.save_game_core(game_id, game.get_core_state(), game_type="werewolf")
        
        # Check if all actions are complete - auto advance phase
        if result.get('all_actions_complete'):
            print(f"[AutoAdvance] All actions complete for game {game_id} phase {game.phase.value}, advancing...")
            old_phase = game.phase.value
            phase_result = game.advance_phase()
            new_phase = phase_result.get('new_phase', '')
            
            # Determine if this is a significant phase change (for MySQL sync)
            is_significant = (
                new_phase in WEREWOLF_SIGNIFICANT_PHASES
                or old_phase in WEREWOLF_SIGNIFICANT_PHASES
            )
            
            # Persist phase change
            await persistence_manager.on_phase_changed(
                game_id=game_id,
                new_phase=new_phase,
                day_count=phase_result.get('day_count', game.day_count),
                game_state=game.to_dict(),
                deaths=phase_result.get('deaths', []),
                significant=is_significant
            )
            
            # Emit phase change
            await _emit_werewolf_event(game_id, 'werewolf_phase_change', {
                'phase': new_phase,
                'day_count': phase_result.get('day_count'),
                'deaths': phase_result.get('deaths', []),
                'eliminated': phase_result.get('eliminated'),
                'game_over': phase_result.get('game_over', False),
                'winners': phase_result.get('winners', [])
            })
            
            # Handle game end
            if phase_result.get('game_over'):
                await handle_werewolf_game_end(game_id, phase_result.get('winners', []))
        
        # Broadcast updated state (masked appropriately)
        await broadcast_werewolf_state(game_id)
        
    except Exception as e:
        import traceback
        traceback.print_exc()
        await sio.emit('error', {'message': f'Werewolf action failed: {str(e)}'}, room=sid)


@sio.event
async def advance_werewolf_phase(sid, data):
    """
    Advance to the next phase in Werewolf game.
    
    Expected data: {'game_id': str}
    """
    try:
        if await _reject_if_read_only(sid, 'advance_werewolf_phase'):
            return

        game_id = data.get('game_id')
        
        if not game_id or game_id not in werewolf_games:
            await sio.emit('error', {'message': 'Invalid game_id'}, room=sid)
            return
        
        game = werewolf_games[game_id]
        old_phase = game.phase.value
        result = game.advance_phase()
        new_phase = result.get('new_phase', game.phase.value)
        
        # Determine if this is a significant phase change
        is_significant = (
            new_phase in WEREWOLF_SIGNIFICANT_PHASES
            or old_phase in WEREWOLF_SIGNIFICANT_PHASES
        )
        
        # Persist phase change
        await persistence_manager.on_phase_changed(
            game_id=game_id,
            new_phase=new_phase,
            day_count=result.get('day_count', game.day_count),
            game_state=game.to_dict(),
            deaths=result.get('deaths', []),
            significant=is_significant
        )
        
        # Emit phase change to all players
        await _emit_werewolf_event(game_id, 'werewolf_phase_change', result)
        
        # Check if game ended
        if game.is_game_over():
            winners = game.get_winners()
            await handle_werewolf_game_end(game_id, winners)
        
        # Broadcast updated state
        await broadcast_werewolf_state(game_id)
        
    except Exception as e:
        await sio.emit('error', {'message': f'Advance phase failed: {str(e)}'}, room=sid)


@sio.event
async def get_werewolf_state(sid, data):
    """
    Get current Werewolf game state.
    
    Expected data: {'game_id': str}
    """
    try:
        game_id = data.get('game_id')
        
        if not game_id or game_id not in werewolf_games:
            await sio.emit('error', {'message': 'Invalid game_id'}, room=sid)
            return
        
        game = werewolf_games[game_id]
        state = game.get_game_state(sid)
        
        await sio.emit('werewolf_state', state, room=sid)
        
    except Exception as e:
        await sio.emit('error', {'message': f'Get werewolf state failed: {str(e)}'}, room=sid)


async def broadcast_werewolf_state(game_id: str):
    """
    Broadcast Werewolf game state to all players.
    
    Each player receives a personalized view:
    - Own role is visible
    - Wolves see other wolves
    - Wolves get wolf_chat history
    - Dead players' roles may be revealed
    - Phase-specific info (witch sees who's dying, etc.)
    """
    if game_id not in werewolf_games:
        return
    
    game = werewolf_games[game_id]
    
    # Send personalized state to each player (with proper masking)
    for player in game.players:
        state = game.get_game_state(player['sid'])
        await sio.emit('werewolf_state', state, room=player['sid'])

    # Broadcast spectator-safe state to dedicated spectator room.
    spectator_state = game.get_game_state(reveal_all=False)
    await sio.emit('werewolf_state', spectator_state, room=_werewolf_spectator_room(game_id))

    # Push reveal-mode spectator state directly to subscribed sockets.
    reveal_sids = list(_iter_reveal_spectators('werewolf', game_id))
    if reveal_sids:
        reveal_state = game.get_game_state(reveal_all=True)
        await _emit_to_sids('werewolf_state', reveal_state, reveal_sids)
    
    # Refresh TTL for active game (non-blocking)
    asyncio.create_task(redis_manager.refresh_game_ttl(game_id))


# ============================================================================
# MATCHMAKING
# ============================================================================

async def on_texas_matchmaking_fallback(players, target_size: int):
    """Callback before Texas matchmaker starts a short-handed fallback table."""
    for player in players:
        await sio.emit('texas_matchmaking_fallback_warning', {
            'message': f'Starting {target_size}-player table after wait timeout',
            'player_count': target_size,
            'preferred_target': TexasMatchmaker.PREFERRED_GAME_SIZE,
            'full_ring_target': TexasMatchmaker.FULL_RING_SIZE,
        }, room=player.sid)


async def on_texas_game_matched(players, game_size: int):
    """Callback when Texas matchmaker creates and fills a poker table."""
    import uuid

    # 1) Pre-validate balances to quickly drop obviously unfundable players.
    eligible_players = []
    for queued_player in players:
        try:
            current_balance = await get_balance(queued_player.wallet_address)
            if current_balance < queued_player.buy_in_tokens:
                await sio.emit('error', {
                    'message': (
                        f'Insufficient balance for matchmaking buy-in. '
                        f'Required: {float(queued_player.buy_in_tokens)} tokens, '
                        f'Available: {float(current_balance)}'
                    )
                }, room=queued_player.sid)
                continue

            eligible_players.append(queued_player)
        except Exception as e:
            await sio.emit('error', {
                'message': f'Matchmaking buy-in lock failed: {str(e)}'
            }, room=queued_player.sid)

    # Need at least 2 potentially fundable players to start a legal table.
    if len(eligible_players) < 2:
        return

    # 2) Create table and persist creation metadata.
    table_id = f"poker_auto_{uuid.uuid4().hex[:8]}"
    table = create_texas_game(table_id)
    poker_tables[table_id] = table

    try:
        await persistence_manager.on_game_created(
            game_id=table_id,
            game_type="texas",
            entry_fee=Decimal("0")
        )
    except Exception as e:
        print(f"[TexasMatchmaking] Persist game create failed: {e}")

    # 3) Seat players and lock funds directly to table session id (single lock op).
    seated_players = []
    for p in eligible_players:
        add_ok = table.add_player(
            p.sid,
            p.wallet_address,
            nickname=p.nickname,
            buy_in_tokens=p.buy_in_tokens,
        )
        if not add_ok:
            await sio.emit('error', {
                'message': 'Could not join auto-matched poker table'
            }, room=p.sid)
            continue

        try:
            await lock_balance(
                p.wallet_address,
                p.buy_in_tokens,
                game_session_id=table_id,
            )
        except Exception as e:
            table.remove_player(p.sid)
            await sio.emit('error', {
                'message': f'Failed to finalize matchmaking seat lock: {str(e)}'
            }, room=p.sid)
            continue

        try:
            await persistence_manager.on_player_joined(
                game_id=table_id,
                player_id=p.wallet_address,
                socket_sid=p.sid,
                nickname=p.nickname,
            )
        except Exception as e:
            print(f"[TexasMatchmaking] Persist player join failed: {e}")

        if p.sid in player_sessions:
            player_sessions[p.sid]['table_id'] = table_id

        await sio.enter_room(p.sid, table_id)
        seated_players.append(p)

    # If seating dropped under minimum, refund and abort table creation.
    if len(seated_players) < 2:
        for p in seated_players:
            table.remove_player(p.sid)
            try:
                await unlock_balance(
                    p.wallet_address,
                    p.buy_in_tokens,
                    game_session_id=table_id,
                    description='Texas matchmaking cancelled after seat failures'
                )
            except Exception:
                pass
            if p.sid in player_sessions:
                player_sessions[p.sid]['table_id'] = None
        poker_tables.pop(table_id, None)
        return

    # 4) Auto-start first hand, then notify so client state does not run ahead.
    hand_started = table.start_game()
    if hand_started:
        asyncio.create_task(table.save_checkpoint('hand_start'))

    for p in seated_players:
        await sio.emit('texas_matchmaking_game_started', {
            'table_id': table_id,
            'player_count': len(seated_players),
            'requested_group_size': game_size,
            'hand_started': hand_started,
        }, room=p.sid)

    await broadcast_game_state(table_id)

async def on_matchmaking_fallback(players, target_size: int):
    """
    Callback before matchmaker downgrades from 9-player to 6-8 player game.
    
    Args:
        players: List of QueuedPlayer objects
        target_size: Target game size (6-8)
    """
    # Notify all players in queue about the fallback
    for player in players:
        await sio.emit('matchmaking_fallback_warning', {
            'message': f'Starting {target_size}-player game (waited 30+ seconds, not enough for 9-player)',
            'player_count': target_size,
            'original_target': 9
        }, room=player.sid)


async def on_game_matched(players, game_size: int):
    """
    Callback when matchmaker creates a game.
    
    Args:
        players: List of QueuedPlayer objects
        game_size: Number of players in this game
    """
    import uuid
    
    if not players:
        return

    entry_fee = getattr(players[0], 'entry_fee', Decimal("0"))

    eligible_players = []
    for player in players:
        player_entry_fee = getattr(player, 'entry_fee', entry_fee)
        if player_entry_fee != entry_fee:
            await sio.emit('error', {
                'message': f'Entry fee mismatch. Expected {float(entry_fee)} tokens.'
            }, room=player.sid)
            continue

        if entry_fee > 0:
            try:
                current_balance = await get_balance(player.wallet_address)
                if current_balance < entry_fee:
                    await sio.emit('error', {
                        'message': (
                            f'Insufficient balance for werewolf matchmaking entry fee. '
                            f'Required: {float(entry_fee)} tokens, '
                            f'Available: {float(current_balance)}'
                        )
                    }, room=player.sid)
                    continue
            except Exception as e:
                await sio.emit('error', {
                    'message': f'Failed to verify entry fee balance: {str(e)}'
                }, room=player.sid)
                continue

        eligible_players.append(player)

    if len(eligible_players) < WerewolfMatchmaker.MIN_PLAYERS:
        return

    # Generate unique game ID
    game_id = f"werewolf_auto_{uuid.uuid4().hex[:8]}"

    # Create game
    game = WerewolfGame(game_id, entry_fee=entry_fee)
    werewolf_games[game_id] = game

    # Persist game creation to MySQL
    await persistence_manager.on_game_created(
        game_id=game_id,
        game_type="werewolf",
        entry_fee=entry_fee
    )

    seated_players = []
    for player in eligible_players:
        # Add player to game
        if not game.add_player(player.sid, player.wallet_address, nickname=player.nickname):
            await sio.emit('error', {
                'message': 'Could not join auto-matched werewolf game'
            }, room=player.sid)
            continue

        if entry_fee > 0:
            try:
                await lock_balance(player.wallet_address, entry_fee, game_session_id=game_id)
            except Exception as e:
                game.remove_player(player.sid)
                await sio.emit('error', {
                    'message': f'Failed to lock werewolf entry fee: {str(e)}'
                }, room=player.sid)
                continue

        # Persist player join to MySQL
        await persistence_manager.on_player_joined(
            game_id=game_id,
            player_id=player.wallet_address,
            socket_sid=player.sid,
            nickname=player.nickname,
            entry_paid=entry_fee
        )

        # Update session
        if player.sid in player_sessions:
            player_sessions[player.sid]['game_id'] = game_id

        # Join Socket.IO room
        await sio.enter_room(player.sid, game_id)
        seated_players.append(player)

    if len(seated_players) < WerewolfMatchmaker.MIN_PLAYERS:
        for player in seated_players:
            if entry_fee > 0:
                try:
                    await unlock_balance(
                        player.wallet_address,
                        entry_fee,
                        game_session_id=game_id,
                        description='Werewolf matchmaking cancelled after seat failures'
                    )
                except Exception:
                    pass
            if player.sid in player_sessions:
                player_sessions[player.sid]['game_id'] = None
            await sio.leave_room(player.sid, game_id)
        werewolf_games.pop(game_id, None)
        return

    # Start the game
    game.start_game()
    
    # Prepare player data with roles for MySQL persistence
    players_with_roles = []
    for p in game.players:
        player_data = {
            'wallet_address': p['wallet_address'],
            'role_type': p['role'].role_type.value if p.get('role') else None,
            'team': p['role'].team.value if p.get('role') else None
        }
        players_with_roles.append(player_data)
    
    # Persist game start to MySQL and Redis
    await persistence_manager.on_game_started(
        game_id=game_id,
        players_with_roles=players_with_roles,
        initial_state=game.to_dict()
    )
    
    # Notify all players
    for player in seated_players:
        await sio.emit('matchmaking_game_started', {
            'game_id': game_id,
            'player_count': game_size
        }, room=player.sid)
    
    # Broadcast initial game state
    await broadcast_werewolf_state(game_id)


@sio.event
async def join_texas_matchmaking(sid, data):
    """Join Texas Hold'em matchmaking queue for auto-seating."""
    global texas_matchmaker

    try:
        if await _reject_if_read_only(sid, 'join_texas_matchmaking'):
            return

        if sid not in player_sessions or not player_sessions[sid]['authenticated']:
            await sio.emit('error', {'message': 'Not authenticated'}, room=sid)
            return

        data = data or {}
        requested_name = str(data.get('nickname', '')).strip()
        player_id = player_sessions[sid]['player_id']
        player_name = player_sessions[sid]['player_name'] or 'Player'
        nickname = requested_name[:32] if requested_name else player_name

        if 'tokens' in data:
            buy_in_tokens = Decimal(str(data['tokens']))
        else:
            buy_in_chips = int(data.get('chips', 1000))
            buy_in_tokens = Decimal(str(buy_in_chips)) * TEXAS_CHIP_TO_TOKEN_RATIO

        if buy_in_tokens <= 0:
            await sio.emit('error', {'message': 'Invalid buy-in amount'}, room=sid)
            return

        if texas_matchmaker is None:
            texas_matchmaker = TexasMatchmaker(
                game_start_callback=on_texas_game_matched,
                fallback_warning_callback=on_texas_matchmaking_fallback,
            )
            texas_matchmaker.start()

        if texas_matchmaker.add_player(sid, player_id, nickname, buy_in_tokens):
            queue_info = texas_matchmaker.get_queue_info()
            await sio.emit('texas_matchmaking_joined', {
                'queue_size': queue_info['size'],
                'buy_in_tokens': float(buy_in_tokens),
                'message': 'Joined Texas matchmaking queue'
            }, room=sid)
        else:
            await sio.emit('error', {'message': 'Already in Texas matchmaking queue'}, room=sid)

    except Exception as e:
        await sio.emit('error', {'message': f'Join Texas matchmaking failed: {str(e)}'}, room=sid)


@sio.event
async def leave_texas_matchmaking(sid, data):
    """Leave Texas Hold'em matchmaking queue."""
    global texas_matchmaker

    try:
        if texas_matchmaker is None:
            await sio.emit('error', {'message': 'Texas matchmaker not initialized'}, room=sid)
            return

        if texas_matchmaker.remove_player(sid):
            await sio.emit('texas_matchmaking_left', {
                'message': 'Left Texas matchmaking queue'
            }, room=sid)
        else:
            await sio.emit('error', {'message': 'Not in Texas matchmaking queue'}, room=sid)

    except Exception as e:
        await sio.emit('error', {'message': f'Leave Texas matchmaking failed: {str(e)}'}, room=sid)


@sio.event
async def get_texas_matchmaking_status(sid, data):
    """Get Texas matchmaking queue status for the requesting socket."""
    global texas_matchmaker

    try:
        if texas_matchmaker is None:
            await sio.emit('texas_matchmaking_status', {
                'queue_size': 0,
                'in_queue': False,
                'is_running': False,
            }, room=sid)
            return

        queue_info = texas_matchmaker.get_queue_info()
        in_queue = texas_matchmaker.is_player_in_queue(sid)
        await sio.emit('texas_matchmaking_status', {
            'queue_size': queue_info['size'],
            'oldest_wait_time': queue_info['oldest_wait_time'],
            'average_wait_time': queue_info['average_wait_time'],
            'in_queue': in_queue,
            'is_running': texas_matchmaker.is_running(),
        }, room=sid)

    except Exception as e:
        await sio.emit('error', {'message': f'Get Texas matchmaking status failed: {str(e)}'}, room=sid)


@sio.event
async def join_matchmaking(sid, data):
    """
    Join the Werewolf matchmaking queue.
    
    Expected data: {'nickname': str (optional)}
    """
    global werewolf_matchmaker
    
    try:
        if await _reject_if_read_only(sid, 'join_matchmaking'):
            return

        # Check authentication
        if sid not in player_sessions or not player_sessions[sid]['authenticated']:
            await sio.emit('error', {'message': 'Not authenticated'}, room=sid)
            return
        
        data = data or {}
        requested_name = str(data.get('nickname', '')).strip()
        player_id = player_sessions[sid]['player_id']
        player_name = player_sessions[sid]['player_name'] or 'Player'
        nickname = requested_name[:32] if requested_name else player_name
        
        entry_fee = Decimal(str(data.get('entry_fee', 0)))
        if entry_fee < 0:
            await sio.emit('error', {'message': 'Invalid entry fee amount'}, room=sid)
            return

        # Initialize matchmaker if needed
        if werewolf_matchmaker is None:
            werewolf_matchmaker = WerewolfMatchmaker(
                game_start_callback=on_game_matched,
                fallback_warning_callback=on_matchmaking_fallback
            )
            werewolf_matchmaker.start()

        if werewolf_matchmaker.get_queue_size() > 0:
            queued_fee = werewolf_matchmaker.queue[0].entry_fee
            if queued_fee != entry_fee:
                await sio.emit('error', {
                    'message': (
                        f'Entry fee mismatch. Current queue requires {float(queued_fee)} tokens.'
                    )
                }, room=sid)
                return

        if entry_fee > 0:
            try:
                current_balance = await get_balance(player_id)
                if current_balance < entry_fee:
                    await sio.emit('error', {
                        'message': (
                            f'Insufficient balance for werewolf matchmaking entry fee. '
                            f'Required: {float(entry_fee)} tokens, '
                            f'Available: {float(current_balance)}'
                        )
                    }, room=sid)
                    return
            except Exception as e:
                await sio.emit('error', {'message': f'Balance check failed: {str(e)}'}, room=sid)
                return
        
        # Add to queue
        if werewolf_matchmaker.add_player(sid, player_id, nickname, entry_fee):
            queue_info = werewolf_matchmaker.get_queue_info()
            await sio.emit('matchmaking_joined', {
                'queue_size': queue_info['size'],
                'entry_fee': float(entry_fee),
                'message': 'Joined matchmaking queue'
            }, room=sid)
        else:
            await sio.emit('error', {'message': 'Already in matchmaking queue'}, room=sid)
    
    except Exception as e:
        await sio.emit('error', {'message': f'Join matchmaking failed: {str(e)}'}, room=sid)


@sio.event
async def leave_matchmaking(sid, data):
    """Leave the Werewolf matchmaking queue."""
    global werewolf_matchmaker
    
    try:
        if werewolf_matchmaker is None:
            await sio.emit('error', {'message': 'Matchmaker not initialized'}, room=sid)
            return
        
        # Remove from queue
        if werewolf_matchmaker.remove_player(sid):
            await sio.emit('matchmaking_left', {
                'message': 'Left matchmaking queue'
            }, room=sid)
        else:
            await sio.emit('error', {'message': 'Not in matchmaking queue'}, room=sid)
    
    except Exception as e:
        await sio.emit('error', {'message': f'Leave matchmaking failed: {str(e)}'}, room=sid)


@sio.event
async def get_matchmaking_status(sid, data):
    """Get current matchmaking queue status."""
    global werewolf_matchmaker
    
    try:
        if werewolf_matchmaker is None:
            await sio.emit('matchmaking_status', {
                'queue_size': 0,
                'in_queue': False,
                'is_running': False
            }, room=sid)
            return
        
        queue_info = werewolf_matchmaker.get_queue_info()
        in_queue = werewolf_matchmaker.is_player_in_queue(sid)
        
        await sio.emit('matchmaking_status', {
            'queue_size': queue_info['size'],
            'oldest_wait_time': queue_info['oldest_wait_time'],
            'average_wait_time': queue_info['average_wait_time'],
            'in_queue': in_queue,
            'is_running': werewolf_matchmaker.is_running()
        }, room=sid)
    
    except Exception as e:
        await sio.emit('error', {'message': f'Get matchmaking status failed: {str(e)}'}, room=sid)


# ============================================================================
# GRACEFUL SHUTDOWN HANDLING
# ============================================================================

shutdown_event = asyncio.Event()

async def graceful_shutdown():
    """
    Handle graceful shutdown to prevent game state loss.
    
    Security improvement: Save active game states before shutdown.
    """
    global werewolf_matchmaker, texas_matchmaker, werewolf_timeout_task, poker_timeout_task
    
    print("\nGraceful shutdown initiated...")
    
    # Stop matchmaker
    if werewolf_matchmaker:
        werewolf_matchmaker.stop()
    if texas_matchmaker:
        texas_matchmaker.stop()

    # Stop background timeout task cleanly.
    if werewolf_timeout_task and not werewolf_timeout_task.done():
        werewolf_timeout_task.cancel()
        await asyncio.gather(werewolf_timeout_task, return_exceptions=True)

    if poker_timeout_task and not poker_timeout_task.done():
        poker_timeout_task.cancel()
        await asyncio.gather(poker_timeout_task, return_exceptions=True)
    
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
