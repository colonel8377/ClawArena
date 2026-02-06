"""
main.py - The Server

FastAPI + Socket.IO server with SIWE authentication, game management,
and withdrawal signature generation.

Security improvements:
- Rate limiting on API endpoints
- CORS whitelist configuration
- Blockchain as source of truth for nonces
- Redis persistence configuration
- Graceful shutdown handling
- Local debug mode for development
"""

import os
import asyncio
import signal
from typing import Dict, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import socketio
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from config import (
    is_local_debug_mode, 
    LOCAL_DEBUG_MODE, 
    SERVER_PRIVATE_KEY, 
    ARENA_VAULT_ADDRESS,
    WEB3_PROVIDER_URL,
    ALLOWED_ORIGINS
)
from games.texas import TexasGame, TexasEngine, create_poker_game, create_texas_game
from database.connection import init_db, get_db
from database.models import User, GameHistory, ChatMessage
from database.redis_manager import redis_manager
from database.persistence_manager import persistence_manager
from economy.account import (
    register_user, handle_login, deduct_balance, add_balance, get_balance,
    validate_account_balance, get_account_summary, transfer_balance, batch_get_balances,
    InvalidAmountError, InsufficientBalanceError, UserNotFoundError, InvalidWalletAddressError
)
from config import (
    TEXAS_CHIP_TO_TOKEN_RATIO, WEREWOLF_PRIZE_MULTIPLIER,
    MIN_WITHDRAWAL_AMOUNT, GAS_COST_ESTIMATE_HIGH, GAS_COST_ESTIMATE_MEDIUM,
    GAS_COST_ESTIMATE_LOW, WITHDRAWAL_PROFITABILITY_RATIO, DAILY_WITHDRAWAL_LIMIT
)
from games.werewolf.werewolf_game import WerewolfGame, WerewolfPhase, PHASE_TIMEOUT_SECONDS
from games.werewolf.matchmaker import WerewolfMatchmaker
from indexer.worker import deposit_worker
from decimal import Decimal
from manager.anti_bot import (
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


# ============================================================================
# ENVIRONMENT CONFIGURATION
# ============================================================================

# Validate private key is set in production (not in local debug mode)
if not LOCAL_DEBUG_MODE and SERVER_PRIVATE_KEY == '0x0000000000000000000000000000000000000000000000000000000000000001':
    import warnings
    warnings.warn(
        "WARNING: Using default private key! Set SERVER_PRIVATE_KEY environment variable in production!",
        RuntimeWarning
    )

# Initialize Web3 connection (skip in local debug mode)
if LOCAL_DEBUG_MODE:
    w3 = None
    print("⚠️  LOCAL DEBUG MODE: Web3 connection disabled")
else:
    w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER_URL)) if WEB3_PROVIDER_URL else Web3()

# Initialize server account for signing
server_account = Account.from_key(SERVER_PRIVATE_KEY)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)

# Create Socket.IO server with proper configuration
socketio_origins = '*' if '*' in ALLOWED_ORIGINS else ALLOWED_ORIGINS
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=socketio_origins,
    logger=True,
    engineio_logger=True,  # Enable Engine.IO logging to debug WebSocket messages
    ping_timeout=60,
    ping_interval=25
)

# Create FastAPI app
app = FastAPI(
    title="Arena Poker Game Engine",
    description="Real-time Texas Hold'em with SIWE authentication and blockchain settlement",
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
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["*"],
)

# Game state management
poker_tables: Dict[str, TexasGame] = {}  # Using unified TexasGame architecture
werewolf_games: Dict[str, WerewolfGame] = {}  # game_id -> WerewolfGame
player_sessions: Dict[str, Dict] = {}  # sid -> {address, table_id, game_id, authenticated}
nonces: Dict[str, str] = {}  # address -> nonce for SIWE auth only
# NOTE: withdrawal_nonces removed - now queried from blockchain

# Matchmaker for Werewolf games
werewolf_matchmaker: Optional[WerewolfMatchmaker] = None


# ============================================================================
# DATABASE INITIALIZATION
# ============================================================================

# Note: Database initialization with retry logic is performed in the async startup handler
# to properly wait for MySQL to be ready in Docker environments.
# The init_db() function now includes retry logic for container startup scenarios.


# ============================================================================
# SMART WITHDRAWAL MANAGEMENT
# ============================================================================

class SmartWithdrawalManager:
    """智能提现管理器 - 单服务器优化"""

    def __init__(self):
        self.pending_withdrawals = {}  # wallet_address -> list of pending amounts

    async def should_withdraw(self, wallet_address: str, amount: Decimal) -> Dict[str, Any]:
        """
        智能判断是否应该提现

        Args:
            wallet_address: 用户钱包地址
            amount: 提现金额

        Returns:
            Dict with decision and reasoning
        """
        # 检查最小提现金额
        if amount < MIN_WITHDRAWAL_AMOUNT:
            return {
                'should_withdraw': False,
                'reason': f'Amount {amount} below minimum {MIN_WITHDRAWAL_AMOUNT}',
                'accumulate': True
            }

        # 获取当前Gas费估算（这里简化，实际可以调用Gas估算API）
        gas_cost = await self._estimate_gas_cost()

        # 计算净收益
        net_profit = amount - gas_cost

        # 检查是否值得提现
        if net_profit < gas_cost * WITHDRAWAL_PROFITABILITY_RATIO:
            return {
                'should_withdraw': False,
                'reason': f'Net profit {net_profit} too low vs gas cost {gas_cost}',
                'accumulate': True,
                'suggested_wait': True
            }

        # 检查每日限额（单服务器无限制）
        if DAILY_WITHDRAWAL_LIMIT is not None:
            daily_total = await self._get_daily_withdrawal_total(wallet_address)
            if daily_total + amount > DAILY_WITHDRAWAL_LIMIT:
                return {
                    'should_withdraw': False,
                    'reason': f'Would exceed daily limit {DAILY_WITHDRAWAL_LIMIT}',
                    'accumulate': False
                }

        return {
            'should_withdraw': True,
            'net_profit': float(net_profit),
            'gas_cost': float(gas_cost),
            'reason': 'Optimal withdrawal conditions'
        }

    async def _estimate_gas_cost(self) -> Decimal:
        """估算Gas费用（简化版本）"""
        # 这里可以集成实际的Gas估算API
        # 目前使用静态估算
        try:
            # 可以根据网络状况动态调整
            # 例如：调用 etherscan API 或 web3.eth.gas_price
            return GAS_COST_ESTIMATE_MEDIUM
        except:
            return GAS_COST_ESTIMATE_HIGH  # 保守估算

    async def _get_daily_withdrawal_total(self, wallet_address: str) -> Decimal:
        """获取今日提现总额（单服务器简化实现）"""
        # 在Redis中存储每日提现记录
        try:
            today_key = f"daily_withdrawals:{wallet_address}:{datetime.utcnow().date()}"
            daily_total = await redis_manager.get_cached_balance(wallet_address)  # 简化实现
            return daily_total or Decimal("0")
        except:
            return Decimal("0")

    def add_pending_withdrawal(self, wallet_address: str, amount: Decimal):
        """添加待提现金额"""
        if wallet_address not in self.pending_withdrawals:
            self.pending_withdrawals[wallet_address] = []
        self.pending_withdrawals[wallet_address].append(amount)

    def get_pending_total(self, wallet_address: str) -> Decimal:
        """获取用户待提现总额"""
        amounts = self.pending_withdrawals.get(wallet_address, [])
        return sum(amounts)

    def clear_pending_withdrawals(self, wallet_address: str):
        """清除用户的待提现记录"""
        self.pending_withdrawals.pop(wallet_address, None)

    async def process_auto_withdrawal(self, wallet_address: str, amount: Decimal) -> bool:
        """
        处理自动提现

        Args:
            wallet_address: 用户钱包地址
            amount: 提现金额

        Returns:
            True if withdrawal was processed
        """
        decision = await self.should_withdraw(wallet_address, amount)

        if decision['should_withdraw']:
            try:
                # 生成提现签名
                signature_data = await generate_withdrawal_signature(wallet_address, int(amount))

                # 可以通过多种方式通知用户：
                # 1. Socket.IO推送（如果用户在线）
                # 2. 存储到数据库供用户查询
                # 3. 发送到消息队列

                # 这里暂时记录到日志
                print(f"Auto-withdrawal processed for {wallet_address}: {amount} tokens")

                return True
            except Exception as e:
                print(f"Auto-withdrawal failed for {wallet_address}: {e}")
                return False
        else:
            # 累积待提现金额
            if decision.get('accumulate', False):
                self.add_pending_withdrawal(wallet_address, amount)
            return False

# 全局智能提现管理器实例
smart_withdrawal_manager = SmartWithdrawalManager()


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
    - Deposit event worker (if not in local debug mode)
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
    
    # Start deposit event worker (unless in local debug mode)
    if not is_local_debug_mode():
        asyncio.create_task(deposit_worker.run())
        print("✓ Deposit event worker started")
    else:
        print("⚠ Deposit event worker disabled (local debug mode)")
    
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
                        
                        # Only restore active games
                        phase = state.get('phase', 'unknown')
                        if phase in ['waiting', 'finished', 'aborted']:
                            print(f"  ⚠ Skipping inactive game: {game_id} (phase: {phase})")
                            await redis_manager.delete_game_data(game_id)
                            continue
                        
                        if game_type == 'werewolf':
                            # Restore werewolf game using from_dict
                            game = WerewolfGame.from_dict(state)
                            werewolf_games[game_id] = game
                            restored_count += 1
                            print(f"  ✓ Restored werewolf game: {game_id} (phase: {phase}, day: {game.day_count})")
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
    asyncio.create_task(werewolf_timeout_checker())
    print("✓ Werewolf game timeout checker started")


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
                        significant_phases = ['day_announcement', 'day_voting', 'finished', 'aborted']
                        is_significant = new_phase in significant_phases or old_phase in significant_phases
                        
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
                                await sio.emit('PLAYER_TIMEOUT', {
                                    'message': f'Player {nickname} Timed Out',
                                    'player': nickname,
                                    'timestamp': datetime.utcnow().isoformat()
                                }, room=game_id)
                        
                        # Check if game was aborted
                        if result.get('aborted'):
                            await sio.emit('GAME_ABORTED', {
                                'message': result.get('reason', 'Game aborted'),
                                'refund_players': result.get('refund_players', []),
                                'timestamp': datetime.utcnow().isoformat()
                            }, room=game_id)
                            continue
                        
                        # Emit phase change
                        await sio.emit('werewolf_phase_change', {
                            'phase': result.get('new_phase'),
                            'day_count': result.get('day_count'),
                            'deaths': result.get('deaths', []),
                            'eliminated': result.get('eliminated'),
                            'game_over': result.get('game_over', False),
                            'winners': result.get('winners', [])
                        }, room=game_id)
                        
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
    
    # Determine winner team
    winner_team = None
    if game and winners:
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
            final_state=game.to_dict() if game else None
        )
    except Exception as e:
        print(f"Failed to persist game end: {e}")
        import traceback
        traceback.print_exc()
    
    # Handle prize distribution and refunds
    try:
        if game and winners:
            # 计算奖金池：所有入场费的总和 × 奖金倍数
            total_entry_fees = sum(player['entry_fee_paid'] for player in game.players)
            prize_pool = total_entry_fees * WEREWOLF_PRIZE_MULTIPLIER
            prize_per_winner = prize_pool / len(winners)

            print(f"Werewolf game prize pool: {float(prize_pool)} tokens from {len(winners)} winners")

            for winner_address in winners:
                add_balance(winner_address, prize_per_winner,
                           tx_type=TransactionType.GAME_WIN,
                           description="Werewolf game prize")
                print(f"Awarded {float(prize_per_winner)} tokens to winner: {winner_address[:8]}...")
        elif game and not winners:
            # 平局或游戏异常结束，退还所有入场费
            print("Werewolf game ended without winners, refunding entry fees")
            for player in game.players:
                unlock_balance(player['wallet_address'], player['entry_fee_paid'],
                              game_session_id=game_id,
                              description="Werewolf game refund - no winners")
                print(f"Refunded {float(player['entry_fee_paid'])} tokens to: {player['wallet_address'][:8]}...")
        else:
            print("No game data found for prize distribution")
    except Exception as e:
        print(f"Failed to handle prize distribution: {e}")
        import traceback
        traceback.print_exc()


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def generate_nonce() -> str:
    """Generate a random nonce for SIWE."""
    import secrets
    return secrets.token_hex(16)


def create_siwe_message(address: str, nonce: str) -> str:
    """Create a Sign-In with Ethereum message."""
    domain = "arenapoker.game"
    issued_at = datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%SZ")
    
    message = (
        f"{domain} wants you to sign in with your Ethereum account:\n"
        f"{address}\n\n"
        f"Sign in to Arena Poker\n\n"
        f"URI: https://{domain}\n"
        f"Version: 1\n"
        f"Chain ID: 1\n"
        f"Nonce: {nonce}\n"
        f"Issued At: {issued_at}"
    )
    return message


def verify_siwe_signature(message: str, signature: str, expected_address: str) -> bool:
    """Verify a SIWE signature."""
    try:
        message_hash = encode_defunct(text=message)
        recovered_address = Account.recover_message(message_hash, signature=signature)
        return recovered_address.lower() == expected_address.lower()
    except Exception:
        return False


def get_nonce_from_blockchain(user_address: str) -> int:
    """
    Get the current nonce for a user from the blockchain.
    
    This is the ONLY source of truth for withdrawal nonces.
    Prevents nonce desynchronization issues.
    
    Args:
        user_address: Ethereum address of the user
    
    Returns:
        Current nonce value from smart contract
    """
    if not ARENA_VAULT_ADDRESS or not w3.is_connected():
        # Fallback for testing - use in-memory counter
        import warnings
        warnings.warn("Web3 not configured - using in-memory nonce (testing only)", RuntimeWarning)
        return 0
    
    try:
        # Load contract ABI (simplified - just the nonce getter)
        contract_abi = [
            {
                "inputs": [{"internalType": "address", "name": "agent", "type": "address"}],
                "name": "getNonce",
                "outputs": [{"internalType": "uint256", "name": "", "type": "uint256"}],
                "stateMutability": "view",
                "type": "function"
            }
        ]
        
        contract = w3.eth.contract(
            address=Web3.to_checksum_address(ARENA_VAULT_ADDRESS),
            abi=contract_abi
        )
        
        # Get nonce from blockchain
        nonce = contract.functions.getNonce(Web3.to_checksum_address(user_address)).call()
        return nonce
    except Exception as e:
        print(f"Error getting nonce from blockchain: {e}")
        return 0



async def generate_withdrawal_signature(user_address: str, amount: int) -> Dict:
    """
    Generate a withdrawal signature for on-chain claiming.
    
    In local debug mode, returns a mock signature that won't work on-chain
    but allows testing the flow.
    
    SECURITY UPDATE: Nonce is now synchronized via RedisManager to prevent
    race conditions during concurrent withdrawal requests. Periodically syncs
    with blockchain to ensure consistency.
    
    This creates a signature that can be verified by the smart contract
    to allow the user to withdraw their winnings.
    
    Args:
        user_address: Ethereum address of the user
        amount: Amount of tokens to withdraw (in wei)
    
    Returns:
        Dict containing the signature, message hash, nonce, and parameters
    """
    # Local debug mode: return mock signature
    if LOCAL_DEBUG_MODE:
        return {
            'user_address': user_address,
            'amount': amount,
            'nonce': 0,
            # Mock signature: 65 bytes in hex (r: 32 + s: 32 + v: 1 = 65 bytes)
            'signature': '0x' + '00' * 65,
            # Mock hash: 32 bytes in hex (Keccak-256 hash)
            'message_hash': '0x' + '00' * 32,
            'signer': server_account.address,
            'local_debug_mode': True,
            'note': 'Mock signature for local debug mode - not valid on-chain'
        }
    
    # Periodic blockchain sync: verify Redis nonce matches blockchain
    # This prevents using stale nonces if user withdrew on-chain directly
    try:
        blockchain_nonce = get_nonce_from_blockchain(user_address)
        await redis_manager.sync_nonce_from_blockchain(user_address, blockchain_nonce)
    except Exception as e:
        # Log but don't fail - Redis nonce is still usable
        print(f"Warning: Could not sync nonce with blockchain: {e}")
    
    # Get and increment nonce atomically via RedisManager (prevents race conditions)
    nonce = await redis_manager.get_and_increment_nonce(user_address)
    
    # Ensure address is checksummed
    user_address = Web3.to_checksum_address(user_address)
    
    # Create the message to sign (matching smart contract's expected format)
    # This must match: keccak256(abi.encodePacked(address, amount, nonce, chainId, contract))
    
    # Using Web3.py to create the same hash as Solidity
    if not ARENA_VAULT_ADDRESS:
        raise ValueError("ARENA_VAULT_ADDRESS not set - cannot generate withdrawal signature")
    
    if not w3:
        raise RuntimeError("Web3 provider not initialized - cannot generate withdrawal signature")
    
    vault_address = Web3.to_checksum_address(ARENA_VAULT_ADDRESS)
    chain_id = w3.eth.chain_id
    message = w3.solidity_keccak(
        ['address', 'uint256', 'uint256', 'uint256', 'address'],
        [user_address, amount, nonce, chain_id, vault_address]
    )
    
    # Sign the message hash
    signed_message = server_account.sign_message(encode_defunct(hexstr=message.hex()))
    
    return {
        'user_address': user_address,
        'amount': amount,
        'nonce': nonce,
        'signature': signed_message.signature.hex(),
        'message_hash': message.hex(),
        'signer': server_account.address
    }


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
        "server_address": server_account.address,
        "security": "enhanced",
        "local_debug_mode": LOCAL_DEBUG_MODE
    }


@app.get("/health")
@limiter.limit("30/minute")
async def health(request: Request):
    """Health check."""
    return {
        "status": "healthy",
        "active_tables": len(poker_tables),
        "web3_connected": w3.is_connected() if w3 else False,
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
            "3. Authenticate with SIWE and start playing!"
        ]
    }


@app.get("/agent/instructions")
async def agent_instructions_endpoint():
    """
    Get instructions for AI agents to connect and play.
    
    This endpoint is public.
    """
    return get_agent_instructions()


@app.post("/auth/nonce")
@limiter.limit("5/minute")
async def get_nonce(request: Request, address: str):
    """Get a nonce for SIWE authentication."""
    nonce = generate_nonce()
    nonces[address.lower()] = nonce
    message = create_siwe_message(address, nonce)
    
    return {
        "nonce": nonce,
        "message": message
    }


@app.post("/auth/verify")
@limiter.limit("5/minute")
async def verify_auth(request: Request, address: str, signature: str):
    """Verify SIWE signature."""
    addr_lower = address.lower()
    
    if addr_lower not in nonces:
        raise HTTPException(status_code=400, detail="No nonce found")
    
    nonce = nonces[addr_lower]
    message = create_siwe_message(address, nonce)
    
    if not verify_siwe_signature(message, signature, address):
        raise HTTPException(status_code=401, detail="Invalid signature")
    
    # Clear used nonce
    del nonces[addr_lower]
    
    return {"verified": True, "address": address}


@app.post("/withdrawal/request")
@limiter.limit("3/minute")
async def request_withdrawal(request: Request, address: str, amount: int):
    """
    Request a withdrawal signature.
    
    Security update: Nonce is now synchronized via RedisManager.
    """
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount")
    
    try:
        # Generate signature with synchronized nonce from RedisManager
        signature_data = await generate_withdrawal_signature(address, amount)
        return signature_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate signature: {str(e)}")


@app.get("/nonce/{address}")
@limiter.limit("10/minute")
async def get_withdrawal_nonce(request: Request, address: str):
    """
    Get current withdrawal nonce for an address from RedisManager.
    
    This queries the synchronized nonce counter.
    """
    try:
        nonce = await redis_manager.get_nonce(address)
        return {
            "address": address,
            "nonce": nonce,
            "source": "redis_synchronized"
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get nonce: {str(e)}")


# ============================================================================
# ECONOMY SYSTEM ENDPOINTS
# ============================================================================

@app.post("/api/register")
@limiter.limit("5/minute")
async def api_register(request: Request, wallet_address: str):
    """
    Register a new user account.
    
    Creates a user account in the database with initial balance.
    """
    try:
        result = register_user(wallet_address)
        return result
    except (InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Registration failed: {str(e)}")


@app.post("/api/login")
@limiter.limit("10/minute")
async def api_login(request: Request, wallet_address: str):
    """
    Handle user login with daily reward check.
    
    Checks if it's a new UTC day and grants daily login reward if applicable.
    """
    try:
        result = handle_login(wallet_address)
        return result
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Login failed: {str(e)}")


@app.get("/api/balance/{wallet_address}")
@limiter.limit("20/minute")
async def api_get_balance(request: Request, wallet_address: str):
    """Get user's current balance."""
    try:
        balance = get_balance(wallet_address)
        return {
            "wallet_address": wallet_address,
            "balance": float(balance)
        }
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get balance: {str(e)}")


@app.get("/api/account/{wallet_address}")
@limiter.limit("10/minute")
async def api_get_account_summary(request: Request, wallet_address: str):
    """Get comprehensive account summary including validation and recent transactions."""
    try:
        summary = get_account_summary(wallet_address)
        return summary
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get account summary: {str(e)}")


@app.post("/api/transfer")
@limiter.limit("5/minute")
async def api_transfer_balance(request: Request, from_wallet: str, to_wallet: str, amount: float):
    """Transfer balance between two accounts."""
    try:
        result = transfer_balance(from_wallet, to_wallet, Decimal(str(amount)))
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
async def api_batch_get_balances(request: Request, wallet_addresses: List[str]):
    """Get balances for multiple wallet addresses efficiently."""
    try:
        if len(wallet_addresses) > 50:
            raise HTTPException(status_code=400, detail="Too many addresses (max 50)")
        balances = batch_get_balances(wallet_addresses)
        return {
            "balances": {addr: float(bal) for addr, bal in balances.items()}
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Batch balance query failed: {str(e)}")


@app.get("/api/withdrawal/smart/{wallet_address}")
@limiter.limit("20/minute")
async def api_get_smart_withdrawal_status(request: Request, wallet_address: str):
    """Get smart withdrawal status and pending withdrawals."""
    try:
        # 检查余额
        balance = get_balance(wallet_address)

        # 获取待提现总额
        pending_total = smart_withdrawal_manager.get_pending_total(wallet_address)

        # 计算建议的提现决策
        available_for_withdrawal = balance - pending_total
        decision = await smart_withdrawal_manager.should_withdraw(wallet_address, available_for_withdrawal)

        return {
            "wallet_address": wallet_address,
            "current_balance": float(balance),
            "pending_withdrawals": float(pending_total),
            "available_for_withdrawal": float(available_for_withdrawal),
            "smart_decision": decision,
            "min_withdrawal": float(MIN_WITHDRAWAL_AMOUNT),
            "gas_estimate": float(await smart_withdrawal_manager._estimate_gas_cost())
        }
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Smart withdrawal status failed: {str(e)}")


@app.post("/api/withdrawal/smart/{wallet_address}")
@limiter.limit("10/minute")
async def api_request_smart_withdrawal(request: Request, wallet_address: str, amount: Optional[float] = None):
    """Request smart withdrawal with optimal timing."""
    try:
        # 如果没有指定金额，使用可用余额
        if amount is None:
            balance = get_balance(wallet_address)
            pending_total = smart_withdrawal_manager.get_pending_total(wallet_address)
            amount = float(balance - pending_total)
        else:
            amount = float(amount)

        token_amount = Decimal(str(amount))

        # 使用智能提现管理器
        success = await smart_withdrawal_manager.process_auto_withdrawal(wallet_address, token_amount)

        if success:
            return {
                "status": "processed",
                "message": f"Withdrawal of {amount} tokens processed immediately",
                "wallet_address": wallet_address
            }
        else:
            # 检查是否累积了待提现金额
            pending_total = smart_withdrawal_manager.get_pending_total(wallet_address)
            return {
                "status": "accumulated",
                "message": f"Amount {amount} tokens accumulated for later withdrawal",
                "pending_total": float(pending_total),
                "wallet_address": wallet_address
            }

    except InvalidAmountError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (UserNotFoundError, InvalidWalletAddressError, ValueError) as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Smart withdrawal failed: {str(e)}")


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


@app.get("/api/spectate/poker/{table_id}")
@limiter.limit("30/minute")
async def api_spectate_poker(request: Request, table_id: str, reveal: bool = False):
    """Return poker state for spectators (optionally reveal hole cards)."""
    if table_id not in poker_tables:
        raise HTTPException(status_code=404, detail="Table not found")
    table = poker_tables[table_id]
    return table.get_game_state(for_spectator=True, reveal_all=reveal)


@app.get("/api/spectate/werewolf/{game_id}")
@limiter.limit("30/minute")
async def api_spectate_werewolf(request: Request, game_id: str, reveal: bool = False):
    """Return werewolf state for spectators (optionally reveal roles)."""
    if game_id not in werewolf_games:
        raise HTTPException(status_code=404, detail="Game not found")
    game = werewolf_games[game_id]
    return game.get_game_state(reveal_all=reveal)


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
    
    print(f"AI Agent connected: {sid} (agent_id: {agent_id})")
    
    player_sessions[sid] = {
        'address': None,
        'table_id': None,
        'game_id': None,
        'authenticated': False,
        'agent_id': agent_id
    }
    await sio.emit('connected', {
        'sid': sid,
        'agent_id': agent_id,
        'message': 'Welcome, AI Agent! You are connected to the arena.'
    }, room=sid)


@sio.event
async def disconnect(sid):
    """Handle client disconnection."""
    global werewolf_matchmaker
    
    print(f"Client disconnected: {sid}")
    
    if sid in player_sessions:
        session = player_sessions[sid]
        
        # Remove from table if in one
        if session['table_id'] and session['table_id'] in poker_tables:
            table = poker_tables[session['table_id']]
            table.remove_player(sid)
            
            # Broadcast updated state
            await broadcast_game_state(session['table_id'])
        
        # Remove from matchmaking queue if in one
        if werewolf_matchmaker:
            werewolf_matchmaker.remove_player(sid)
        
        del player_sessions[sid]


@sio.event
async def authenticate(sid, data):
    """
    Authenticate a client with SIWE.
    
    In local debug mode, skips signature verification and accepts any valid address.
    
    On successful authentication, checks if player was in an active game and sends
    GAME_SNAPSHOT for reconnection recovery.
    
    Expected data: {'address': str, 'signature': str}
    """
    try:
        address = data.get('address')
        signature = data.get('signature')
        
        # Local debug mode: simplified authentication (no signature verification)
        if LOCAL_DEBUG_MODE:
            if not address:
                await sio.emit('error', {'message': 'Missing address'}, room=sid)
                return
            
            # Validate address format
            if len(address) != 42 or not address.startswith('0x'):
                await sio.emit('error', {'message': 'Invalid address format'}, room=sid)
                return
            
            # Mark as authenticated (no signature verification needed)
            player_sessions[sid]['address'] = address
            player_sessions[sid]['authenticated'] = True
            
            # Auto-register/update user with debug balance
            try:
                register_user(address)
            except Exception:
                pass  # User may already exist
            
            await sio.emit('authenticated', {
                'address': address,
                'local_debug_mode': True
            }, room=sid)
            
            # Check for reconnection to active game
            await handle_reconnection(sid, address)
            return
        
        # Normal mode: full SIWE authentication
        if not address or not signature:
            await sio.emit('error', {'message': 'Missing address or signature'}, room=sid)
            return
        
        addr_lower = address.lower()
        
        # Check if nonce exists
        if addr_lower not in nonces:
            await sio.emit('error', {'message': 'No nonce found. Call /auth/nonce first'}, room=sid)
            return
        
        # Verify signature
        nonce = nonces[addr_lower]
        message = create_siwe_message(address, nonce)
        
        if not verify_siwe_signature(message, signature, address):
            await sio.emit('error', {'message': 'Invalid signature'}, room=sid)
            return
        
        # Mark as authenticated
        player_sessions[sid]['address'] = address
        player_sessions[sid]['authenticated'] = True
        
        # Clear used nonce
        del nonces[addr_lower]
        
        await sio.emit('authenticated', {'address': address}, room=sid)
        
        # Check for reconnection to active game
        await handle_reconnection(sid, address)
        
    except Exception as e:
        await sio.emit('error', {'message': f'Authentication failed: {str(e)}'}, room=sid)


async def handle_reconnection(sid: str, wallet_address: str):
    """
    Handle reconnection by checking if player was in an active game.
    
    If found, updates the player's sid and sends GAME_SNAPSHOT.
    
    Args:
        sid: New socket ID
        wallet_address: Player's wallet address
    """
    wallet_lower = wallet_address.lower()
    
    # Inactive werewolf phases (no need to reconnect)
    INACTIVE_PHASES = {WerewolfPhase.WAITING, WerewolfPhase.FINISHED, WerewolfPhase.ABORTED}
    
    # Check werewolf games for this wallet
    for game_id, game in werewolf_games.items():
        # Skip finished/aborted/waiting games
        if game.phase in INACTIVE_PHASES:
            continue
        
        # Find player by wallet address
        for player in game.players:
            if player['wallet_address'].lower() == wallet_lower:
                old_sid = player['sid']
                
                # Update player's socket ID
                if old_sid != sid:
                    game.update_player_sid(old_sid, sid)
                    print(f"[Reconnect] Player {wallet_address} reconnected to game {game_id}")
                
                # Update session
                player_sessions[sid]['game_id'] = game_id
                
                # Join Socket.IO room
                await sio.enter_room(sid, game_id)
                
                # Send GAME_SNAPSHOT for recovery
                snapshot = game.get_game_snapshot(sid)
                await sio.emit('GAME_SNAPSHOT', snapshot, room=sid)
                
                print(f"[Reconnect] Sent GAME_SNAPSHOT to {wallet_address} for game {game_id}")
                return
    
    # Check poker tables for this wallet
    for table_id, table in poker_tables.items():
        for player in table.players:
            if player.get('wallet_address', '').lower() == wallet_lower:
                # Update session
                player_sessions[sid]['table_id'] = table_id
                
                # Join Socket.IO room
                await sio.enter_room(sid, table_id)
                
                # Send game state
                state = table.get_game_state(sid)
                await sio.emit('GAME_SNAPSHOT', {
                    'game_id': table_id,
                    'game_type': 'texas',
                    **state,
                    'timestamp': datetime.utcnow().isoformat()
                }, room=sid)
                
                print(f"[Reconnect] Sent GAME_SNAPSHOT to {wallet_address} for poker table {table_id}")
                return


@sio.event
async def join_game(sid, data):
    """
    Join or create a game table.
    
    Expected data: {'table_id': str, 'chips': int (optional)}
    """
    try:
        # Check authentication
        if sid not in player_sessions or not player_sessions[sid]['authenticated']:
            await sio.emit('error', {'message': 'Not authenticated'}, room=sid)
            return
        
        table_id = data.get('table_id')

        # 支持chips或tokens买入，默认使用chips
        if 'tokens' in data:
            buy_in_tokens = Decimal(str(data['tokens']))
            buy_in_chips = buy_in_tokens / TEXAS_CHIP_TO_TOKEN_RATIO
        else:
            buy_in_chips = data.get('chips', 1000)
            buy_in_tokens = buy_in_chips * TEXAS_CHIP_TO_TOKEN_RATIO

        if not table_id:
            await sio.emit('error', {'message': 'table_id required'}, room=sid)
            return

        # 检查余额是否足够
        try:
            current_balance = get_balance(address)
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
        address = player_sessions[sid]['address']

        # Add player to table with token amount
        if not table.add_player(sid, address, nickname=address[:8], buy_in_tokens=buy_in_tokens):
            await sio.emit('error', {'message': 'Could not join table'}, room=sid)
            return

        # 锁定资金
        try:
            lock_balance(address, buy_in_tokens, game_session_id=table_id)
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
            'address': address
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
        table_id = data.get('table_id')
        
        if not table_id or table_id not in poker_tables:
            await sio.emit('error', {'message': 'Invalid table_id'}, room=sid)
            return
        
        table = poker_tables[table_id]
        
        result = table.start_hand()
        if not result['success']:
            await sio.emit('error', {'message': result.get('error', 'Not enough players to start')}, room=sid)
            return
        
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
        result = table.process_move(sid, action, amount, chat_message)
        
        if not result['success']:
            await sio.emit('error', {'message': result.get('error', 'Action failed')}, room=sid)
            return
        
        if chat_message:
            player = next((p for p in table.players if p.get('sid') == sid), None)
            if player:
                message_type = 'chat' if action == 'chat' else 'action'
                metadata = {'action': action} if action != 'chat' else None
                asyncio.create_task(
                    persistence_manager.save_chat_message(
                        game_id=table_id,
                        game_type=table.game_type,
                        wallet_address=player.get('wallet_address', ''),
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
            await sio.emit('hand_winner', {
                'winner': winner_info,
                'reason': 'All other players folded',
                'pot': winner_info.get('amount', 0)
            }, room=table_id)
            
            # Generate withdrawal signature for winner
            if winner_info.get('amount', 0) > 0:
                winner_sid = winner_info.get('sid')
                winner_player = None
                for p in table.players:
                    if p.get('sid') == winner_sid:
                        winner_player = p
                        break
                
                if winner_player:
                    # 转换chips为tokens发放奖金
                    token_amount = int(winner_info['amount'] * TEXAS_CHIP_TO_TOKEN_RATIO)
                    await generate_and_emit_withdrawal(
                        table_id,
                        winner_player['wallet_address'],
                        token_amount
                    )
            return
        
        # Check if round complete and advance phase
        if result.get('advance_phase'):
            phase_result = table.engine.advance_phase()
            await broadcast_game_state(table_id)
            
            # Check for showdown (use engine.phase, not table.phase)
            if table.engine.phase.value == 'showdown':
                showdown_result = table.engine.showdown()
                
                # Broadcast showdown reveal with all hole cards visible
                await sio.emit('showdown_reveal', {
                    'player_hands': table.engine.get_all_hole_cards(),
                    'community_cards': table.engine.cards_to_strings(table.engine.community_cards),
                    'winners': showdown_result.get('winners', [])
                }, room=table_id)
                
                # Generate withdrawal signatures for winners
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
                            # 转换chips为tokens发放奖金
                            token_amount = int(winner['amount'] * TEXAS_CHIP_TO_TOKEN_RATIO)
                            await generate_and_emit_withdrawal(
                                table_id,
                                winner_player['wallet_address'],
                                token_amount
                            )
        
    except Exception as e:
        await sio.emit('error', {'message': f'Player move failed: {str(e)}'}, room=sid)


@sio.event
async def poker_action(sid, data):
    """
    Alternative handler for poker actions (used in agent_rules.md).
    
    This is an alias for player_move that matches the protocol in agent_rules.md.
    
    Expected data: {
        'game_id': str,
        'action': str ('fold', 'check', 'call', 'raise'),
        'amount': int (optional, for raise),
        'message': str (optional, for chat/bluff)
    }
    """
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
async def leave_game(sid, data):
    """
    Leave the current table.
    
    Expected data: {'table_id': str}
    """
    try:
        table_id = data.get('table_id')
        
        if not table_id or table_id not in poker_tables:
            await sio.emit('error', {'message': 'Invalid table_id'}, room=sid)
            return
        
        table = poker_tables[table_id]
        
        # Get player's remaining chips before leaving
        player = table.players.get(sid)
        
        # Remove from table
        table.remove_player(sid)
        
        # Leave Socket.IO room
        await sio.leave_room(sid, table_id)
        
        # Update session
        if sid in player_sessions:
            player_sessions[sid]['table_id'] = None
        
        # If player had chips, convert to tokens and unlock funds
        if player and player.chips > 0:
            token_amount = int(player.chips * TEXAS_CHIP_TO_TOKEN_RATIO)
            # 解锁剩余资金
            unlock_balance(player.wallet_address, token_amount,
                          game_session_id=table_id,
                          description="Texas Hold'em game exit refund")
        
        # Notify player
        await sio.emit('left_game', {'table_id': table_id}, room=sid)
        
        # Broadcast updated state
        await broadcast_game_state(table_id)
        
    except Exception as e:
        await sio.emit('error', {'message': f'Leave game failed: {str(e)}'}, room=sid)


# ============================================================================
# SETTLEMENT SYSTEM (CRUCIAL)
# ============================================================================

async def generate_and_emit_withdrawal(table_id: str, user_address: str, amount: int):
    """
    Generate withdrawal signature and emit to the user.

    Includes smart withdrawal management for optimal timing.

    SECURITY UPDATE: Nonce is now synchronized via RedisManager.

    This is called when:
    - A game ends with winnings
    - A player leaves with chips

    The signature allows the user to claim their winnings on-chain.
    """
    token_amount = Decimal(str(amount))

    # 使用智能提现管理器判断是否立即提现
    decision = await smart_withdrawal_manager.should_withdraw(user_address, token_amount)

    if decision['should_withdraw']:
        # 立即生成提现签名
        withdrawal_data = await generate_withdrawal_signature(user_address, amount)
        withdrawal_data['smart_decision'] = decision

        # Emit to all sessions for this address in this table
        await sio.emit('withdrawal_signature', withdrawal_data, room=table_id)

        print(f"✅ Immediate withdrawal for {user_address}: {amount} tokens (net profit: {decision.get('net_profit', 'N/A')})")
    else:
        # 累积待提现或推迟提现
        if decision.get('accumulate', False):
            smart_withdrawal_manager.add_pending_withdrawal(user_address, token_amount)
            print(f"⏳ Accumulated pending withdrawal for {user_address}: {token_amount} tokens")

        # 仍然发送通知，但标记为延迟提现
        delayed_data = {
            'user_address': user_address,
            'amount': amount,
            'delayed': True,
            'reason': decision['reason'],
            'pending_total': float(smart_withdrawal_manager.get_pending_total(user_address))
        }
        await sio.emit('withdrawal_delayed', delayed_data, room=table_id)


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
    
    # Get current player
    active_sids = [s for s in engine.player_order if engine.players[s].can_act()]
    current_player = None
    if active_sids and engine.current_player_index < len(active_sids):
        current_player = active_sids[engine.current_player_index]
    
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
            
            werewolf_games[game_id] = WerewolfGame(game_id)
            
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
        # Check authentication
        if sid not in player_sessions or not player_sessions[sid]['authenticated']:
            await sio.emit('error', {'message': 'Not authenticated'}, room=sid)
            return
        
        game_id = data.get('game_id')
        nickname = data.get('nickname', 'Player')
        
        if not game_id or game_id not in werewolf_games:
            await sio.emit('error', {'message': 'Invalid game_id'}, room=sid)
            return
        
        address = player_sessions[sid]['address']
        game = werewolf_games[game_id]

        # 检查余额是否足够支付入场费
        try:
            current_balance = get_balance(address)
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
            if not game.add_player(sid, address, nickname=nickname):
                await sio.emit('error', {'message': 'Could not join game'}, room=sid)
                return

            # 锁定入场费
            try:
                lock_balance(address, game.entry_fee, game_session_id=game_id)
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
                wallet_address=address,
                socket_sid=sid,
                nickname=nickname
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
            'address': address
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
            await sio.emit('player_thinking', {
                'game_id': game_id,
                'player_sid': sid,
                'action_type': action
            }, room=game_id)
        
        # Build kwargs for action
        kwargs = {}
        if target_sid is not None:  # Allow None for abstain/skip
            kwargs['target_sid'] = target_sid
        if message:
            kwargs['message'] = message
        
        result = game.process_action(sid, action, **kwargs)
        
        if not result['success']:
            await sio.emit('error', {'message': result.get('error', 'Action failed')}, room=sid)
            return
        
        # Send action confirmation to the player
        await sio.emit('werewolf_action_result', result, room=sid)
        
        if action in ['chat', 'wolf_chat'] and message:
            player = next((p for p in game.players if p['sid'] == sid), None)
            if player:
                metadata = {'phase': game.phase.value, 'is_wolf_chat': action == 'wolf_chat'}
                asyncio.create_task(
                    persistence_manager.save_chat_message(
                        game_id=game_id,
                        game_type=game.game_type,
                        wallet_address=player['wallet_address'],
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
        
        # Handle public chat broadcast
        # (Chat stored in-memory in WerewolfGame, broadcast via Socket.IO)
        elif action == 'chat':
            await sio.emit('chat_message', result.get('chat'), room=game_id)
        
        # Handle speak action (persist to MySQL for permanent history)
        elif action == 'speak':
            player = next((p for p in game.players if p['sid'] == sid), None)
            if player:
                asyncio.create_task(
                    persistence_manager.save_speech(
                        game_id=game_id,
                        wallet_address=player['wallet_address'],
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
            significant_phases = ['day_announcement', 'day_voting', 'finished', 'aborted']
            is_significant = new_phase in significant_phases or old_phase in significant_phases
            
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
            await sio.emit('werewolf_phase_change', {
                'phase': new_phase,
                'day_count': phase_result.get('day_count'),
                'deaths': phase_result.get('deaths', []),
                'eliminated': phase_result.get('eliminated'),
                'game_over': phase_result.get('game_over', False),
                'winners': phase_result.get('winners', [])
            }, room=game_id)
            
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
        game_id = data.get('game_id')
        
        if not game_id or game_id not in werewolf_games:
            await sio.emit('error', {'message': 'Invalid game_id'}, room=sid)
            return
        
        game = werewolf_games[game_id]
        old_phase = game.phase.value
        result = game.advance_phase()
        new_phase = result.get('new_phase', game.phase.value)
        
        # Determine if this is a significant phase change
        significant_phases = ['day_announcement', 'day_voting', 'finished', 'aborted']
        is_significant = new_phase in significant_phases or old_phase in significant_phases
        
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
        await sio.emit('werewolf_phase_change', result, room=game_id)
        
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
    
    # Refresh TTL for active game (non-blocking)
    asyncio.create_task(redis_manager.refresh_game_ttl(game_id))


# ============================================================================
# MATCHMAKING
# ============================================================================

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
    
    # Generate unique game ID
    game_id = f"werewolf_auto_{uuid.uuid4().hex[:8]}"
    
    # Create game
    game = WerewolfGame(game_id)
    werewolf_games[game_id] = game
    
    # Persist game creation to MySQL
    await persistence_manager.on_game_created(
        game_id=game_id,
        game_type="werewolf",
        entry_fee=Decimal("0")
    )
    
    # Add all players to game
    for player in players:
        # Add player to game
        game.add_player(player.sid, player.wallet_address, nickname=player.nickname)
        
        # Persist player join to MySQL
        await persistence_manager.on_player_joined(
            game_id=game_id,
            wallet_address=player.wallet_address,
            socket_sid=player.sid,
            nickname=player.nickname
        )
        
        # Update session
        if player.sid in player_sessions:
            player_sessions[player.sid]['game_id'] = game_id
        
        # Join Socket.IO room
        await sio.enter_room(player.sid, game_id)
    
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
    for player in players:
        await sio.emit('matchmaking_game_started', {
            'game_id': game_id,
            'player_count': game_size
        }, room=player.sid)
    
    # Broadcast initial game state
    await broadcast_werewolf_state(game_id)


@sio.event
async def join_matchmaking(sid, data):
    """
    Join the Werewolf matchmaking queue.
    
    Expected data: {'nickname': str (optional)}
    """
    global werewolf_matchmaker
    
    try:
        # Check authentication
        if sid not in player_sessions or not player_sessions[sid]['authenticated']:
            await sio.emit('error', {'message': 'Not authenticated'}, room=sid)
            return
        
        nickname = data.get('nickname', 'Player')
        address = player_sessions[sid]['address']
        
        # Initialize matchmaker if needed
        if werewolf_matchmaker is None:
            werewolf_matchmaker = WerewolfMatchmaker(
                game_start_callback=on_game_matched,
                fallback_warning_callback=on_matchmaking_fallback
            )
            werewolf_matchmaker.start()
        
        # Add to queue
        if werewolf_matchmaker.add_player(sid, address, nickname):
            queue_info = werewolf_matchmaker.get_queue_info()
            await sio.emit('matchmaking_joined', {
                'queue_size': queue_info['size'],
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
    Also stops the deposit event worker gracefully.
    """
    global werewolf_matchmaker
    
    print("\nGraceful shutdown initiated...")
    
    # Stop deposit worker
    if not is_local_debug_mode():
        deposit_worker.stop()
        print("✓ Deposit worker stopped")
    
    # Stop matchmaker
    if werewolf_matchmaker:
        werewolf_matchmaker.stop()
    
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
        save_tasks.append(game.save_state_to_redis())
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
    print(f"Server account address: {server_account.address}")
    print(f"Web3 connected: {w3.is_connected() if w3 else False}")
    print(f"Arena Vault address: {ARENA_VAULT_ADDRESS or 'Not configured'}")
    print(f"CORS allowed origins: {ALLOWED_ORIGINS}")
    print(f"Local Debug Mode: {LOCAL_DEBUG_MODE}")
    print("=" * 70)
    
    if LOCAL_DEBUG_MODE:
        print("\n⚠️  LOCAL DEBUG MODE FEATURES:")
        print("  ✓ Simplified authentication (no SIWE signature required)")
        print("  ✓ Unlimited funds for all accounts")
        print("  ✓ Mock withdrawal signatures")
        print("  ✓ Web3/Blockchain connections disabled")
        print("\n  ⚠️  DO NOT USE IN PRODUCTION!")
    else:
        print("\nSecurity features enabled:")
        print("  ✓ Rate limiting on all endpoints")
        print("  ✓ Blockchain nonce synchronization")
        print("  ✓ Configurable CORS whitelist")
        print("  ✓ Graceful shutdown handling")
        print("  ✓ Daily withdrawal limits (contract)")
        print("  ✓ Emergency pause mechanism (contract)")
    
    print("=" * 70)
    print("\nStarting server on http://0.0.0.0:8000")
    print("API docs available at: http://0.0.0.0:8000/docs")
    print("=" * 70)
    
    uvicorn.run(
        "main:asgi_app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
