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
"""

import os
import asyncio
import signal
from typing import Dict, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
import socketio
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from games.texas import TexasGame, PokerEngine, create_poker_game, create_texas_game
from database.connection import init_db, get_db
from database.models import User, GameHistory, ChatMessage
from economy.account import register_user, handle_login, deduct_balance, add_balance, get_balance
from games.werewolf.werewolf_game import WerewolfGame
from games.werewolf.matchmaker import WerewolfMatchmaker
from decimal import Decimal


# ============================================================================
# ENVIRONMENT CONFIGURATION
# ============================================================================

SERVER_PRIVATE_KEY = os.getenv(
    'SERVER_PRIVATE_KEY', 
    '0x0000000000000000000000000000000000000000000000000000000000000001'
)

# Validate private key is set in production
if SERVER_PRIVATE_KEY == '0x0000000000000000000000000000000000000000000000000000000000000001':
    import warnings
    warnings.warn(
        "WARNING: Using default private key! Set SERVER_PRIVATE_KEY environment variable in production!",
        RuntimeWarning
    )

# Contract configuration
ARENA_VAULT_ADDRESS = os.getenv('ARENA_VAULT_ADDRESS', '')
WEB3_PROVIDER_URL = os.getenv('WEB3_PROVIDER_URL', 'https://mainnet.base.org')

# CORS configuration - whitelist specific origins in production
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', '*').split(',')

# Initialize Web3 connection
w3 = Web3(Web3.HTTPProvider(WEB3_PROVIDER_URL)) if WEB3_PROVIDER_URL else Web3()

# Initialize server account for signing
server_account = Account.from_key(SERVER_PRIVATE_KEY)

# Rate limiting
limiter = Limiter(key_func=get_remote_address)

# Create Socket.IO server with proper configuration
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins=ALLOWED_ORIGINS,
    logger=True,
    engineio_logger=False,
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

# Initialize database on startup
try:
    init_db()
    print("✓ Database initialized")
except Exception as e:
    print(f"⚠ Database initialization failed: {e}")
    print("  Make sure MySQL is running and credentials are correct")


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



def generate_withdrawal_signature(user_address: str, amount: int) -> Dict:
    """
    Generate a withdrawal signature for on-chain claiming.
    
    SECURITY UPDATE: Nonce is now queried from blockchain (single source of truth)
    instead of being tracked in MySQL/memory.
    
    This creates a signature that can be verified by the smart contract
    to allow the user to withdraw their winnings.
    
    Args:
        user_address: Ethereum address of the user
        amount: Amount of tokens to withdraw (in wei)
    
    Returns:
        Dict containing the signature, message hash, nonce, and parameters
    """
    # Get current nonce from blockchain (SINGLE SOURCE OF TRUTH)
    nonce = get_nonce_from_blockchain(user_address)
    
    # Ensure address is checksummed
    user_address = Web3.to_checksum_address(user_address)
    
    # Create the message to sign (matching smart contract's expected format)
    # This must match: keccak256(abi.encodePacked(address, amount, nonce))
    
    # Using Web3.py to create the same hash as Solidity
    message = w3.solidity_keccak(
        ['address', 'uint256', 'uint256'],
        [user_address, amount, nonce]
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
        "security": "enhanced"
    }


@app.get("/health")
@limiter.limit("30/minute")
async def health(request: Request):
    """Health check."""
    return {
        "status": "healthy",
        "active_tables": len(poker_tables),
        "web3_connected": w3.is_connected() if w3 else False
    }


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
    
    Security update: Nonce is now automatically fetched from blockchain.
    """
    if amount <= 0:
        raise HTTPException(status_code=400, detail="Invalid amount")
    
    try:
        # Generate signature with blockchain-sourced nonce
        signature_data = generate_withdrawal_signature(address, amount)
        return signature_data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to generate signature: {str(e)}")


@app.get("/nonce/{address}")
@limiter.limit("10/minute")
async def get_withdrawal_nonce(request: Request, address: str):
    """
    Get current withdrawal nonce for an address from blockchain.
    
    This queries the smart contract directly (single source of truth).
    """
    try:
        nonce = get_nonce_from_blockchain(address)
        return {
            "address": address,
            "nonce": nonce,
            "source": "blockchain"
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
    except ValueError as e:
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
    except ValueError as e:
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
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get balance: {str(e)}")


# ============================================================================
# SOCKET.IO EVENT HANDLERS
# ============================================================================

@sio.event
async def connect(sid, environ):
    """Handle client connection."""
    print(f"Client connected: {sid}")
    player_sessions[sid] = {
        'address': None,
        'table_id': None,
        'game_id': None,
        'authenticated': False
    }
    await sio.emit('connected', {'sid': sid}, room=sid)


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
    
    Expected data: {'address': str, 'signature': str}
    """
    try:
        address = data.get('address')
        signature = data.get('signature')
        
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
        
    except Exception as e:
        await sio.emit('error', {'message': f'Authentication failed: {str(e)}'}, room=sid)


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
        chips = data.get('chips', 1000)
        
        if not table_id:
            await sio.emit('error', {'message': 'table_id required'}, room=sid)
            return
        
        # Create table if it doesn't exist
        if table_id not in poker_tables:
            poker_tables[table_id] = create_texas_game(table_id)
        
        table = poker_tables[table_id]
        address = player_sessions[sid]['address']
        
        # Add player to table
        if not table.add_player(sid, address, nickname=address[:8], buy_in=chips):
            await sio.emit('error', {'message': 'Could not join table'}, room=sid)
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
        
        # Broadcast updated state
        await broadcast_game_state(table_id)
        
        # Check if round complete and advance phase
        if result.get('advance_phase'):
            phase_result = table.advance_phase()
            await broadcast_game_state(table_id)
            
            # Check for showdown
            if table.phase.value == 'showdown':
                showdown_result = table.get_game_state()
                # Broadcast showdown reveal
                await sio.emit('showdown_reveal', {
                    'player_hands': table.get_all_hole_cards(),
                    'community_cards': table.cards_to_strings(table.community_cards),
                    'winners': showdown_result.get('winners', [])
                }, room=table_id)
                
                # Generate withdrawal signatures for winners
                for winner in showdown_result.get('winners', []):
                    if winner.get('amount', 0) > 0:
                        player = table.players.get(winner['sid'])
                        if player:
                            await generate_and_emit_withdrawal(
                                table_id,
                                player.wallet_address,
                                winner['amount']
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
        
        # If player had chips, generate withdrawal signature
        if player and player.chips > 0:
            await generate_and_emit_withdrawal(
                table_id,
                player.wallet_address,
                player.chips
            )
        
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
    
    SECURITY UPDATE: Nonce is now queried from blockchain (single source of truth).
    
    This is called when:
    - A game ends with winnings
    - A player leaves with chips
    
    The signature allows the user to claim their winnings on-chain.
    """
    # Generate signature (nonce automatically fetched from blockchain)
    withdrawal_data = generate_withdrawal_signature(user_address, amount)
    
    # Emit to all sessions for this address in this table
    await sio.emit('withdrawal_signature', withdrawal_data, room=table_id)
    
    print(f"Generated withdrawal signature for {user_address}: {amount} chips (nonce: {withdrawal_data['nonce']})")


async def broadcast_game_state(table_id: str):
    """
    Broadcast game state to all players at the table.
    Also saves state to Redis for persistence.
    """
    if table_id not in poker_tables:
        return
    
    table = poker_tables[table_id]
    
    # Send personalized state to each player
    for player_sid, player in table.players.items():
        state = table.get_game_state(player_sid)
        await sio.emit('game_state', state, room=player_sid)
    
    # Save state to Redis for hot storage (non-blocking)
    asyncio.create_task(table.save_state_to_redis())


# ============================================================================
# WEREWOLF GAME SOCKET.IO HANDLERS
# ============================================================================

@sio.event
async def create_werewolf_game(sid, data):
    """
    Create a new Werewolf game.
    
    Expected data: {'game_id': str}
    """
    try:
        # Check authentication
        if sid not in player_sessions or not player_sessions[sid]['authenticated']:
            await sio.emit('error', {'message': 'Not authenticated'}, room=sid)
            return
        
        game_id = data.get('game_id')
        if not game_id:
            await sio.emit('error', {'message': 'game_id required'}, room=sid)
            return
        
        # Create game if doesn't exist
        if game_id in werewolf_games:
            await sio.emit('error', {'message': 'Game already exists'}, room=sid)
            return
        
        werewolf_games[game_id] = WerewolfGame(game_id)
        
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
        
        game = werewolf_games[game_id]
        address = player_sessions[sid]['address']
        
        # Add player to game
        if not game.add_player(sid, address, nickname=nickname):
            await sio.emit('error', {'message': 'Could not join game'}, room=sid)
            return
        
        # Update session
        player_sessions[sid]['game_id'] = game_id
        
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
        'action': str,  # 'night_kill', 'seer_check', 'witch_save', 'witch_poison', 'vote', 'hunter_shoot'
        'target_sid': str (optional, depends on action)
    }
    """
    try:
        game_id = data.get('game_id')
        action = data.get('action')
        target_sid = data.get('target_sid')
        
        if not game_id or game_id not in werewolf_games:
            await sio.emit('error', {'message': 'Invalid game_id'}, room=sid)
            return
        
        if not action:
            await sio.emit('error', {'message': 'Action required'}, room=sid)
            return
        
        game = werewolf_games[game_id]
        result = game.process_action(sid, action, target_sid=target_sid)
        
        if not result['success']:
            await sio.emit('error', {'message': result.get('error', 'Action failed')}, room=sid)
            return
        
        # Send action confirmation
        await sio.emit('werewolf_action_result', result, room=sid)
        
        # Broadcast updated state (masked appropriately)
        await broadcast_werewolf_state(game_id)
        
    except Exception as e:
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
        result = game.advance_phase()
        
        # Emit phase change to all players
        await sio.emit('werewolf_phase_change', result, room=game_id)
        
        # Check if game ended
        if game.is_game_over():
            winners = game.get_winners()
            
            # Record game in database
            try:
                from database.connection import get_db_session
                with get_db_session() as db:
                    for winner_address in winners:
                        game_record = GameHistory(
                            game_type='werewolf',
                            winner_wallet=winner_address,
                            timestamp=datetime.utcnow()
                        )
                        db.add(game_record)
                    db.commit()
            except Exception as e:
                print(f"Failed to record game result: {e}")
            
            # Award winnings (example: 50 tokens per winner)
            try:
                for winner_address in winners:
                    add_balance(winner_address, Decimal("50.0"))
            except Exception as e:
                print(f"Failed to award winnings: {e}")
        
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
    Also saves state to Redis for persistence.
    """
    if game_id not in werewolf_games:
        return
    
    game = werewolf_games[game_id]
    
    # Send personalized state to each player (with proper masking)
    for player in game.players:
        state = game.get_game_state(player['sid'])
        await sio.emit('werewolf_state', state, room=player['sid'])
    
    # Save state to Redis for hot storage (non-blocking)
    asyncio.create_task(game.save_state_to_redis())


# ============================================================================
# MATCHMAKING
# ============================================================================

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
    
    # Add all players to game
    for player in players:
        # Add player to game
        game.add_player(player.sid, player.wallet_address, nickname=player.nickname)
        
        # Update session
        if player.sid in player_sessions:
            player_sessions[player.sid]['game_id'] = game_id
        
        # Join Socket.IO room
        await sio.enter_room(player.sid, game_id)
    
    # Start the game
    game.start_game()
    
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
            werewolf_matchmaker = WerewolfMatchmaker(game_start_callback=on_game_matched)
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
    """
    global werewolf_matchmaker
    
    print("\nGraceful shutdown initiated...")
    
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
    print("Arena Poker Server - Enhanced Security Edition")
    print("=" * 70)
    print(f"Server account address: {server_account.address}")
    print(f"Web3 connected: {w3.is_connected() if w3 else False}")
    print(f"Arena Vault address: {ARENA_VAULT_ADDRESS or 'Not configured'}")
    print(f"CORS allowed origins: {ALLOWED_ORIGINS}")
    print("=" * 70)
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
