"""
main.py - The Server

FastAPI + Socket.IO server with SIWE authentication, game management,
and withdrawal signature generation.
"""

import os
import asyncio
from typing import Dict, Optional
from datetime import datetime

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
import socketio
from eth_account import Account
from eth_account.messages import encode_defunct
from web3 import Web3

from poker_logic import TexasHoldemTable


# Environment configuration
SERVER_PRIVATE_KEY = os.getenv(
    'SERVER_PRIVATE_KEY', 
    '0x0000000000000000000000000000000000000000000000000000000000000001'
)

# Initialize server account for signing
server_account = Account.from_key(SERVER_PRIVATE_KEY)

# Create Socket.IO server
sio = socketio.AsyncServer(
    async_mode='asgi',
    cors_allowed_origins='*',
    logger=True,
    engineio_logger=False
)

# Create FastAPI app
app = FastAPI(
    title="Arena Poker Game Engine",
    description="Real-time Texas Hold'em with SIWE authentication",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Game state management
tables: Dict[str, TexasHoldemTable] = {}
player_sessions: Dict[str, Dict] = {}  # sid -> {address, table_id, authenticated}
nonces: Dict[str, str] = {}  # address -> nonce
withdrawal_nonces: Dict[str, int] = {}  # address -> nonce counter


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


def generate_withdrawal_signature(user_address: str, amount: int, nonce: int) -> Dict:
    """
    Generate a withdrawal signature for on-chain claiming.
    
    This creates a signature that can be verified by the smart contract
    to allow the user to withdraw their winnings.
    
    Args:
        user_address: Ethereum address of the user
        amount: Amount of tokens to withdraw
        nonce: Unique nonce to prevent replay attacks
    
    Returns:
        Dict containing the signature, message hash, and parameters
    """
    # Create the message to sign (matching smart contract's expected format)
    # This should match: keccak256(abi.encodePacked(address, amount, nonce))
    
    # Using Web3.py to create the same hash as Solidity
    w3 = Web3()
    
    # Encode the message components
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
async def root():
    """Root endpoint."""
    return {
        "name": "Arena Poker Game Engine",
        "version": "2.0.0",
        "status": "running",
        "server_address": server_account.address
    }


@app.get("/health")
async def health():
    """Health check."""
    return {"status": "healthy", "active_tables": len(tables)}


@app.post("/auth/nonce")
async def get_nonce(address: str):
    """Get a nonce for SIWE authentication."""
    nonce = generate_nonce()
    nonces[address.lower()] = nonce
    message = create_siwe_message(address, nonce)
    
    return {
        "nonce": nonce,
        "message": message
    }


@app.post("/auth/verify")
async def verify_auth(address: str, signature: str):
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
        'authenticated': False
    }
    await sio.emit('connected', {'sid': sid}, room=sid)


@sio.event
async def disconnect(sid):
    """Handle client disconnection."""
    print(f"Client disconnected: {sid}")
    
    if sid in player_sessions:
        session = player_sessions[sid]
        
        # Remove from table if in one
        if session['table_id'] and session['table_id'] in tables:
            table = tables[session['table_id']]
            table.remove_player(sid)
            
            # Broadcast updated state
            await broadcast_game_state(session['table_id'])
        
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
        if table_id not in tables:
            tables[table_id] = TexasHoldemTable(table_id)
        
        table = tables[table_id]
        address = player_sessions[sid]['address']
        
        # Add player to table
        if not table.add_player(sid, address, chips):
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
        
        if not table_id or table_id not in tables:
            await sio.emit('error', {'message': 'Invalid table_id'}, room=sid)
            return
        
        table = tables[table_id]
        
        if not table.deal_hands():
            await sio.emit('error', {'message': 'Not enough players to start'}, room=sid)
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
        'action': str ('fold', 'check', 'call', 'raise', 'bet', 'all_in'),
        'amount': int (optional, for raise/bet)
    }
    """
    try:
        table_id = data.get('table_id')
        action = data.get('action')
        amount = data.get('amount', 0)
        
        if not table_id or table_id not in tables:
            await sio.emit('error', {'message': 'Invalid table_id'}, room=sid)
            return
        
        if not action:
            await sio.emit('error', {'message': 'Action required'}, room=sid)
            return
        
        table = tables[table_id]
        result = table.apply_action(sid, action, amount)
        
        if not result['success']:
            await sio.emit('error', {'message': result.get('error', 'Action failed')}, room=sid)
            return
        
        # Broadcast updated state
        await broadcast_game_state(table_id)
        
        # Check if game ended (showdown complete)
        if table.stage == 'showdown':
            # Determine winners
            winners = table.determine_winner()
            
            # Generate withdrawal signatures for winners
            for winner in winners:
                if winner['chips_won'] > 0:
                    await generate_and_emit_withdrawal(
                        table_id,
                        winner['address'],
                        winner['chips_won']
                    )
        
    except Exception as e:
        await sio.emit('error', {'message': f'Player move failed: {str(e)}'}, room=sid)


@sio.event
async def get_state(sid, data):
    """
    Get current game state.
    
    Expected data: {'table_id': str}
    """
    try:
        table_id = data.get('table_id')
        
        if not table_id or table_id not in tables:
            await sio.emit('error', {'message': 'Invalid table_id'}, room=sid)
            return
        
        table = tables[table_id]
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
        
        if not table_id or table_id not in tables:
            await sio.emit('error', {'message': 'Invalid table_id'}, room=sid)
            return
        
        table = tables[table_id]
        
        # Get player's remaining chips before leaving
        player = None
        for p in table.players:
            if p['sid'] == sid:
                player = p
                break
        
        # Remove from table
        table.remove_player(sid)
        
        # Leave Socket.IO room
        await sio.leave_room(sid, table_id)
        
        # Update session
        if sid in player_sessions:
            player_sessions[sid]['table_id'] = None
        
        # If player had chips, generate withdrawal signature
        if player and player['chips'] > 0:
            await generate_and_emit_withdrawal(
                table_id,
                player['address'],
                player['chips']
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
    
    This is called when:
    - A game ends with winnings
    - A player leaves with chips
    
    The signature allows the user to claim their winnings on-chain.
    """
    addr_lower = user_address.lower()
    
    # Get or initialize nonce for this address
    if addr_lower not in withdrawal_nonces:
        withdrawal_nonces[addr_lower] = 0
    
    nonce = withdrawal_nonces[addr_lower]
    withdrawal_nonces[addr_lower] += 1
    
    # Generate signature
    withdrawal_data = generate_withdrawal_signature(user_address, amount, nonce)
    
    # Emit to all sessions for this address in this table
    await sio.emit('withdrawal_signature', withdrawal_data, room=table_id)
    
    print(f"Generated withdrawal signature for {user_address}: {amount} chips")


async def broadcast_game_state(table_id: str):
    """Broadcast game state to all players at the table."""
    if table_id not in tables:
        return
    
    table = tables[table_id]
    
    # Send personalized state to each player
    for player in table.players:
        state = table.get_game_state(player['sid'])
        await sio.emit('game_state', state, room=player['sid'])


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
    
    print(f"Server account address: {server_account.address}")
    print(f"Starting Arena Poker Server...")
    
    uvicorn.run(
        "main:asgi_app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
