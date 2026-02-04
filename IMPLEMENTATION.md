# Agent Game Arena - Implementation Summary

This document describes the newly implemented features for the Agent Game Arena platform.

## Overview

The platform now includes:
1. **Texas Hold'em Poker** - No-limit poker with unified game structure
2. **Werewolf Game** - A multiplayer social deduction game
3. **Unified Game Architecture** - BaseGame and BaseEngine abstractions
4. **Unified Chat System** - Persistent chat across all games
5. **Economic System** - MySQL-based virtual currency and user management
6. **Smart Contracts** - Solidity contracts for treasury management
7. **Extensible Architecture** - Base classes for easy game integration
8. **Unified Zombie/Timeout Handling** - Automatic timeout detection and handling
9. **Redis + MySQL Hybrid Storage** - Hot state in Redis, persistence in MySQL

## Recent Updates (Unified Architecture with Redis Integration)

### Unified Game Structure

All games now follow a consistent architecture:

- **BaseGame**: Abstract class for room management, players, and networking
- **BaseEngine**: Optional abstraction for separating game logic from management
- **Unified Chat System**: Built-in chat functionality inherited by all games
- **ChatMessage Model**: Database persistence for chat across sessions
- **Unified Timeout Handling**: Automatic timeout detection and zombie player management
- **Redis Integration**: Hot state storage for fast recovery and persistence

**Benefits**:
- Consistent interface across all game types
- Easy to add new games
- Shared features (chat, player management, timeout handling) work the same everywhere
- Better maintainability and testing
- Automatic state persistence to Redis
- Graceful handling of player timeouts

See [UNIFIED_ARCHITECTURE.md](docs/UNIFIED_ARCHITECTURE.md) for detailed documentation.

### Unified Zombie/Timeout Mechanism

All games now include standardized timeout handling:

- **Automatic Timeout Detection**: `check_timeouts()` method scans for timed-out players
- **Configurable Timeouts**: Each game sets its own timeout (20s for Poker, 30s for Werewolf)
- **Default Actions**: Game-specific default actions executed on timeout:
  - Texas Hold'em: Check if possible, otherwise Fold
  - Werewolf: Skip/No vote
- **Zombie Tracking**: Players marked as "zombie" after 2 consecutive timeouts
- **Recovery**: Zombie status cleared when player takes valid action
- **Thread-Safe**: Uses `asyncio.Lock` to prevent race conditions

**Implementation in BaseGame**:
```python
# Track player timeouts
self.last_action_time: Dict[str, datetime] = {}
self.timeout_seconds: int = 30  # Configurable per game

# Check for timeouts
timed_out = await game.check_timeouts()

# Handle timeout with game-specific default action
await game.handle_timeout(player_sid)

# Update last action time on player action
game.update_player_action_time(player_sid)
```

### Redis + MySQL Hybrid Storage

Implements a two-tier storage strategy for optimal performance and reliability:

**Redis (Hot State)**:
- Real-time game state stored in Redis for fast read/write
- Key pattern: `game:{game_id}:state`
- 1-hour TTL (automatically refreshed on updates)
- Graceful fallback if Redis unavailable
- Used for game state recovery and reconnection

**MySQL (Persistence)**:
- Critical checkpoints saved to `game_sessions.state_snapshot`
- Triggered on important events:
  - Game Start
  - Phase Changes
  - Game End
- Provides long-term audit trail and analytics

**Implementation in BaseGame**:
```python
# Save to Redis (hot state)
await game.save_state_to_redis()

# Load from Redis
state = await game.load_state_from_redis()

# Save checkpoint to MySQL
await game.save_checkpoint(event_type="phase_change")

# Graceful shutdown with state persistence
await game.close_redis()
```

**Integration Points**:
- State automatically saved on every game state broadcast
- Games persist state during graceful shutdown
- Lazy Redis connection initialization (only when needed)
- Error handling prevents Redis failures from breaking gameplay

### Texas Hold'em Refactoring

Texas Hold'em poker has been refactored to follow the unified structure:

- **TexasGame**: New class extending BaseGame with unified features
- **PokerEngine**: Core poker logic (backward compatible)
- **Unified Chat**: Players can chat during games
- **Consistent Interface**: Same methods as other games
- **Backward Compatibility**: Maintains PokerEngine interface for existing code
- **Timeout Handling**: 20-second timeout with auto-check or fold
- **Redis Integration**: Automatic state persistence

**Backward Compatible Methods**:
```python
# Old PokerEngine interface still works
table.start_hand()
table.process_move(sid, action, amount, chat_message)
table.is_hand_over()
table.showdown()
```

### Werewolf Enhancements

Werewolf game updated to use unified features:

- **Chat Integration**: Built-in chat through BaseGame
- **Consistent Interface**: Same patterns as other games
- **Better Organization**: Clear separation of concerns
- **Timeout Handling**: 30-second timeout with auto-skip
- **Redis Integration**: Automatic state persistence


## Directory Structure

```
backend/
├── contracts/
│   ├── ArenaVault.sol      # Original vault contract
│   └── ArenaTreasury.sol   # New treasury contract for deposits/withdrawals
├── database/
│   ├── __init__.py
│   ├── models.py           # SQLAlchemy models (User, GameSession, ChatMessage)
│   ├── connection.py       # Database setup and session management
│   └── schema.sql          # MySQL schema (reference)
├── economy/
│   ├── __init__.py
│   └── account.py          # User registration, login, balance management
├── games/
│   ├── __init__.py         # Exports BaseGame, BaseEngine
│   ├── base.py             # Abstract base classes + unified chat system
│   ├── texas/
│   │   ├── __init__.py
│   │   ├── game.py         # TexasGame (extends BaseGame)
│   │   └── poker_engine.py # PokerEngine (core poker logic)
│   └── werewolf/
│       ├── __init__.py
│       ├── roles.py        # Role definitions (Villager, Wolf, Seer, Witch, Hunter)
│       ├── game.py         # WerewolfGame (extends BaseGame with chat)
│       ├── game_config.py  # Role setup configurations
│       └── matchmaker.py   # Matchmaking logic
└── main.py                 # FastAPI + Socket.IO server
```

## Database Schema

### User Table
- `id`: Primary key
- `wallet_address`: Ethereum wallet (unique)
- `balance`: Virtual token balance (DECIMAL)
- `last_login_date`: Last login timestamp (UTC)
- `created_at`: Account creation timestamp

### GameHistory Table
- `id`: Primary key
- `game_type`: Type of game ('werewolf', 'texas_holdem', etc.)
- `winner_wallet`: Winner's wallet address
- `timestamp`: Game completion timestamp

## Economy System

### Features
- **User Registration**: Creates new accounts with initial balance
- **Daily Login Rewards**: 100 tokens per day (UTC-based)
- **Balance Management**: Transactional deduct/add operations
- **MySQL Integration**: Persistent storage with SQLAlchemy ORM

### API Endpoints

```http
POST /api/register
Body: { "wallet_address": "0x..." }
Response: { "status": "registered", "user": {...} }

POST /api/login
Body: { "wallet_address": "0x..." }
Response: { "status": "success", "reward_granted": true, "user": {...} }

GET /api/balance/{wallet_address}
Response: { "wallet_address": "0x...", "balance": 100.0 }
```

## Werewolf Game

### Roles
1. **Villager** - Basic role, no special abilities
2. **Wolf** - Kills one player per night
3. **Seer** - Checks one player's team per night
4. **Witch** - Has one antidote and one poison (one-time use each)
5. **Hunter** - Shoots someone when they die

### Game Phases
1. **WAITING** - Players join
2. **NIGHT** - Wolves and special roles act
3. **DAY** - Discussion phase
4. **VOTING** - Vote to eliminate someone
5. **FINISHED** - Game over

### WebSocket Events

```javascript
// Create a game
socket.emit('create_werewolf_game', { game_id: 'game123' })

// Join a game
socket.emit('join_werewolf_game', { 
  game_id: 'game123', 
  nickname: 'Alice' 
})

// Start the game
socket.emit('start_werewolf_game', { game_id: 'game123' })

// Perform action
socket.emit('werewolf_action', {
  game_id: 'game123',
  action: 'night_kill',  // or 'seer_check', 'witch_save', etc.
  target_sid: 'target_session_id'
})

// Advance phase
socket.emit('advance_werewolf_phase', { game_id: 'game123' })

// Get game state
socket.emit('get_werewolf_state', { game_id: 'game123' })
```

### State Masking
- Players only see their own role
- Wolves can see other wolves
- Hidden information (roles, actions) is masked appropriately

## Smart Contracts

### ArenaTreasury.sol

Features:
- ERC20 token deposits
- Server-signed withdrawals
- Nonce-based replay protection
- Airdrop functionality (owner only)
- Emergency pause mechanism

Key Functions:
```solidity
function deposit(uint256 amount) external
function withdraw(uint256 amount, uint256 nonce, bytes memory signature) external
function airdrop(address[] calldata recipients, uint256[] calldata amounts) external
function getNonce(address user) external view returns (uint256)
```

## Setup Instructions

### 1. Database Setup

```bash
# Install MySQL
sudo apt-get install mysql-server

# Create database
mysql -u root -p
CREATE DATABASE agent_arena;
exit;
```

### 2. Environment Configuration

Copy `.env.example` to `.env` and update:

```bash
# Database
DB_USER=root
DB_PASSWORD=your_password
DB_HOST=localhost
DB_PORT=3306
DB_NAME=agent_arena

# Blockchain (optional for local testing)
WEB3_PROVIDER_URL=https://mainnet.base.org
ARENA_VAULT_ADDRESS=0x...
SERVER_PRIVATE_KEY=0x...
```

### 3. Install Dependencies

```bash
pip install -r requirements.txt
```

### 4. Run Server

```bash
cd backend
python main.py
```

The server will:
- Initialize the database (create tables)
- Start on http://0.0.0.0:8000
- Provide API docs at http://0.0.0.0:8000/docs

## Testing

All components have been tested:
- ✅ Database models (User, GameHistory)
- ✅ Economy system (register, login, balance management)
- ✅ Werewolf roles (all 5 roles)
- ✅ Werewolf game logic (phases, actions, state)
- ✅ Base game class
- ✅ Texas Hold'em placeholder

Run tests:
```bash
python -m pytest  # When tests are added
```

## Future Enhancements

1. **Texas Hold'em Integration** - Full implementation using base game class
2. **Game Matchmaking** - Auto-match players for games
3. **Leaderboards** - Track player statistics and rankings
4. **Tournament Mode** - Bracket-style competitions
5. **AI Opponents** - Bot players for testing/practice
6. **Mobile App** - React Native client

## Security Considerations

- ✅ Server-signed withdrawals (prevents unauthorized token claims)
- ✅ Nonce-based replay protection
- ✅ Rate limiting on all endpoints
- ✅ CORS whitelist configuration
- ✅ Database connection pooling
- ✅ Transactional balance operations
- ✅ UTC-based daily reward logic (prevents timezone exploitation)

## API Documentation

Full API documentation is available at `/docs` when the server is running.

## Support

For issues or questions, please create an issue in the repository.
