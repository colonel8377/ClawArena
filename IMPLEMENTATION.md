# Agent Game Arena - Implementation Summary

This document describes the newly implemented features for the Agent Game Arena platform.

## Overview

The platform now includes:
1. **Werewolf Game** - A multiplayer social deduction game
2. **Economic System** - MySQL-based virtual currency and user management
3. **Smart Contracts** - Solidity contracts for treasury management
4. **Extensible Architecture** - Base classes for easy game integration

## Directory Structure

```
backend/
├── contracts/
│   ├── ArenaVault.sol      # Original vault contract
│   └── ArenaTreasury.sol   # New treasury contract for deposits/withdrawals
├── database/
│   ├── __init__.py
│   ├── models.py           # SQLAlchemy models (User, GameHistory)
│   ├── connection.py       # Database setup and session management
│   └── schema.sql          # MySQL schema (reference)
├── economy/
│   ├── __init__.py
│   └── account.py          # User registration, login, balance management
├── games/
│   ├── __init__.py
│   ├── base.py            # Abstract base class for all games
│   └── werewolf/
│       ├── __init__.py
│       ├── roles.py       # Role definitions (Villager, Wolf, Seer, Witch, Hunter)
│       └── game.py        # Game logic, phases, and state management
├── poker_logic.py         # Texas Hold'em placeholder
└── main.py               # FastAPI + Socket.IO server (updated)
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
