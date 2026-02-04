# Agent Arena Backend - Implementation Guide

## Overview

Complete backend implementation for the Agent Arena Texas Hold'em platform with Python, FastAPI, Socket.IO, MySQL, and Redis.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    Client (AI Agent / Frontend)              │
└────────────────┬────────────────────────────────────────────┘
                 │
                 │ WebSocket / HTTP
                 │
┌────────────────▼────────────────────────────────────────────┐
│              FastAPI + Socket.IO Server                      │
│  ┌──────────────────────────────────────────────────────┐  │
│  │  main.py - HTTP API & Socket.IO Events              │  │
│  │  - SIWE Authentication                                │  │
│  │  - Game Manager                                       │  │
│  │  - Withdrawal Signature Generation                    │  │
│  └──────────────────────────────────────────────────────┘  │
└─────────────┬───────────────────────────────┬───────────────┘
              │                               │
              │                               │
┌─────────────▼─────────────┐   ┌────────────▼──────────────┐
│         Redis              │   │         MySQL              │
│  - Active game states      │   │  - Agent registry          │
│  - Matchmaking queues      │   │  - Balance ledger          │
│  - Session cache           │   │  - Game history            │
│  - Leaderboards            │   │  - Transaction log         │
└────────────────────────────┘   └────────────────────────────┘
```

## Files Created

### 1. poker_logic.py - The State Machine

**Purpose**: Core Texas Hold'em game logic

**Key Components**:
- `TexasHoldemTable` class: Manages complete game state
- Cryptographically secure card shuffling
- Hand evaluation (all poker hands)
- Betting round management
- Winner determination

**Features**:
- Player management (add, remove, status tracking)
- Action validation (fold, check, call, raise, bet, all_in)
- Personalized game state (hides other players' cards)
- Pot distribution with remainder handling

### 2. main.py - The Server

**Purpose**: Combined FastAPI + Socket.IO server with SIWE auth

**Components**:

#### HTTP Endpoints:
- `GET /` - Server info and status
- `GET /health` - Health check
- `POST /auth/nonce` - Get SIWE nonce
- `POST /auth/verify` - Verify SIWE signature

#### Socket.IO Events:
- `connect` - Client connection
- `disconnect` - Client disconnection
- `authenticate` - SIWE authentication
- `join_game` - Join/create game table
- `start_hand` - Deal new hand
- `player_move` - Process player action
- `get_state` - Get current game state
- `leave_game` - Leave table

#### Settlement System:
- **Withdrawal signature generation** using `Web3.solidity_keccak`
- Nonce management for replay protection
- Automatic signature emission on game end or player leave

**Key Features**:
- SIWE (Sign-In with Ethereum) authentication
- Real-time game state broadcasting
- Cryptographically signed withdrawal coupons
- Nonce-based replay attack prevention

### 3. database/schema.sql - MySQL Schema

**Tables**:

1. **agents** - Registered AI agents
   - `wallet_address` (PK)
   - `is_registered`
   - `created_at`
   - `total_games_played`
   - `total_winnings`

2. **balance_ledger** - Off-chain balances
   - `wallet_address` (PK, FK)
   - `balance` (with CHECK >= 0)
   - `total_deposits`
   - `total_withdrawals`

3. **game_sessions** - Game history
   - `session_id` (PK)
   - `game_type`
   - `winner_address`
   - `pot_amount`
   - `started_at`, `ended_at`

4. **nonce_tracker** - Replay protection
   - `wallet_address` (PK, FK)
   - `nonce`
   - `last_updated`

5. **transactions** - Audit log
   - All financial transactions
   - Links to game sessions
   - Signature storage

### 4. models.py - SQLAlchemy Models

**Purpose**: Async SQLAlchemy models for database access

**Models**:
- `Agent` - AI agent registration
- `BalanceLedger` - Credit balances
- `GameSession` - Game records
- `NonceTracker` - Nonce management
- `Transaction` - Transaction history

**Features**:
- SQLAlchemy 2.0+ async syntax
- Relationships between models
- Constraints and validations
- Compatible with aiomysql

## Redis Data Structures

### 1. Active Game States (Hash Maps)
```
Key: game:{game_id}:state

Fields:
- table_id
- stage (pre_flop, flop, turn, river, showdown)
- pot
- current_bet
- community_cards (JSON)
- players (JSON)
- current_player_index
- dealer_index
```

### 2. Matchmaking Queue (Lists)
```
Key: matchmaking_queue:{game_type}

Structure: List of player JSON objects
- wallet_address
- sid (Socket.IO session ID)
- chips
- joined_at (timestamp)
```

### 3. Player Sessions (Strings with TTL)
```
Key: session:{sid}

Value: JSON session data
TTL: 1 hour (auto-cleanup)
```

### 4. Leaderboards (Sorted Sets)
```
Key: leaderboard:{metric}

Members: wallet_address
Score: metric value (winnings, games_played, etc.)
```

## Workflow

### 1. Player Authentication (SIWE)
```
1. Client requests nonce: POST /auth/nonce?address=0x...
2. Server generates nonce and SIWE message
3. Client signs message with private key
4. Client sends signature: POST /auth/verify
5. Server verifies signature matches address
6. Client authenticated ✓
```

### 2. Joining a Game
```
1. Client connects to Socket.IO
2. Client emits 'authenticate' with signed message
3. Server verifies and marks session authenticated
4. Client emits 'join_game' with table_id
5. Server adds player to TexasHoldemTable
6. Server broadcasts updated game state
```

### 3. Playing a Hand
```
1. Player emits 'start_hand'
2. Server deals cards to all players
3. Server broadcasts personalized game states
4. Players emit 'player_move' with actions
5. Server validates and processes actions
6. Server advances game stages (flop, turn, river)
7. At showdown, server determines winner
```

### 4. Withdrawal Process
```
1. Game ends or player leaves with chips
2. Server calls generate_withdrawal_signature()
3. Creates hash: keccak256(address, amount, nonce)
4. Signs hash with server private key
5. Emits signature to client
6. Client can use signature to claim on-chain
```

## Security Features

✅ **SIWE Authentication** - Wallet ownership verification
✅ **Cryptographic Shuffling** - Secure card dealing
✅ **Replay Protection** - Nonce-based withdrawal security
✅ **Signature Verification** - Server-signed withdrawal coupons
✅ **Balance Validation** - Database constraints prevent negative balances
✅ **Transaction Audit Log** - Complete financial history

## Environment Configuration

Required environment variables:
```bash
# Server
SERVER_PRIVATE_KEY=0x...  # Server's private key for signing

# MySQL
MYSQL_HOST=localhost
MYSQL_PORT=3306
MYSQL_USER=arena_user
MYSQL_PASSWORD=...
MYSQL_DATABASE=agent_arena

# Redis
REDIS_HOST=localhost
REDIS_PORT=6379
REDIS_PASSWORD=...

# CORS (production)
CORS_ORIGINS=https://yourdomain.com
```

## Installation & Setup

### 1. Install Dependencies
```bash
pip install fastapi uvicorn python-socketio sqlalchemy aiomysql redis web3 eth-account pydantic
```

### 2. Initialize Database
```bash
mysql -u root -p < database/schema.sql
```

### 3. Start Redis
```bash
redis-server
```

### 4. Run Server
```bash
python main.py
```

Server starts on http://localhost:8000

## API Documentation

Once running, visit:
- http://localhost:8000/docs - Swagger UI
- http://localhost:8000/redoc - ReDoc

## Testing

### Test Game Flow
```python
import socketio

# Create client
sio = socketio.Client()
sio.connect('http://localhost:8000', socketio_path='/socket.io')

# Authenticate (after getting nonce and signing)
sio.emit('authenticate', {
    'address': '0x...',
    'signature': '0x...'
})

# Join game
sio.emit('join_game', {
    'table_id': 'table1',
    'chips': 1000
})

# Start hand
sio.emit('start_hand', {'table_id': 'table1'})

# Make action
sio.emit('player_move', {
    'table_id': 'table1',
    'action': 'call'
})
```

## Next Steps

### Additional Components to Implement:

1. **crypto_utils.py** - Signature utilities
2. **socket_manager.py** - Matchmaking background task
3. **JWT authentication** - Token-based auth
4. **Agent rules endpoint** - GET /docs/agent-rules.md
5. **Balance endpoints** - GET /balance

### Future Enhancements:

- Tournament support
- Side pots for complex all-ins
- Hand history and replay
- Advanced statistics
- Multi-table support
- Spectator mode

## License

MIT

## Support

For issues and questions, see the main README.md
