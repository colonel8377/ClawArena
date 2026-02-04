# AgentGameArena

A real-time Texas Hold'em poker game engine built with FastAPI, Socket.IO, and Web3 for Ethereum-based authentication.

## Features

- **Real-time Gameplay**: Built with `python-socketio` for instant game state updates
- **Web3 Authentication**: Sign-In with Ethereum (SIWE) for secure player authentication
- **FastAPI Backend**: High-performance async API for game management
- **Complete Poker Logic**: Full Texas Hold'em implementation with hand evaluation
- **Withdrawal System**: Cryptographically signed withdrawal payloads

## Tech Stack

- **Python 3.10+**
- **FastAPI**: Modern web framework for building APIs
- **python-socketio**: Real-time bidirectional communication
- **web3.py**: Ethereum blockchain interaction
- **eth_account**: SIWE authentication and message signing
- **pydantic**: Data validation and settings management

## Installation

### Prerequisites

- Python 3.10 or higher
- pip

### Setup

1. Clone the repository:
```bash
git clone https://github.com/colonel8377/AgentGameArena.git
cd AgentGameArena
```

2. Install dependencies:
```bash
pip install -r requirements.txt
```

3. (Optional) Create a `.env` file for configuration:
```env
HOST=0.0.0.0
PORT=8000
DEFAULT_SMALL_BLIND=10
DEFAULT_BIG_BLIND=20
DEFAULT_STARTING_CHIPS=1000
SIWE_DOMAIN=arenapoker.game
CHAIN_ID=1
```

## Running the Server

Start the server using uvicorn:

```bash
python main.py
```

Or using uvicorn directly:

```bash
uvicorn main:asgi_app --host 0.0.0.0 --port 8000 --reload
```

The server will start on `http://localhost:8000`.

## API Documentation

Once the server is running, visit:
- Interactive API docs: `http://localhost:8000/api/docs`
- Alternative API docs: `http://localhost:8000/api/redoc`

## API Endpoints

### Authentication

#### Get SIWE Nonce
```http
POST /api/auth/nonce?wallet_address=0x...
```

Returns a nonce and SIWE message for the wallet to sign.

#### Verify Signature
```http
POST /api/auth/verify?wallet_address=0x...&signature=0x...
```

Verifies the signed SIWE message.

### Game Management

#### Create Game
```http
POST /api/games?game_id=game1&small_blind=10&big_blind=20
```

Creates a new poker game.

#### Get Game State
```http
GET /api/games/{game_id}?wallet_address=0x...
```

Returns the current game state (hides other players' cards).

#### List Games
```http
GET /api/games
```

Lists all active games.

#### Delete Game
```http
DELETE /api/games/{game_id}
```

Deletes a game.

### Withdrawals

#### Create Withdrawal
```http
POST /api/withdrawal/create
Content-Type: application/json

{
  "wallet_address": "0x...",
  "amount": 1000
}
```

Creates a signed withdrawal payload.

#### Verify Withdrawal
```http
POST /api/withdrawal/verify
Content-Type: application/json

{
  "wallet_address": "0x...",
  "amount": 1000,
  "nonce": 0,
  "signature": "0x...",
  "timestamp": 1234567890
}
```

Verifies a withdrawal payload signature.

## Socket.IO Events

Connect to Socket.IO at `ws://localhost:8000/socket.io`

### Client → Server Events

#### join_game
```javascript
socket.emit('join_game', {
  game_id: 'game1',
  wallet_address: '0x...',
  chips: 1000
});
```

#### leave_game
```javascript
socket.emit('leave_game', {
  game_id: 'game1',
  wallet_address: '0x...'
});
```

#### start_hand
```javascript
socket.emit('start_hand', {
  game_id: 'game1'
});
```

#### player_action
```javascript
socket.emit('player_action', {
  game_id: 'game1',
  wallet_address: '0x...',
  action: 'bet',  // 'fold', 'check', 'call', 'raise', 'bet', 'all_in'
  amount: 50      // optional, required for bet/raise
});
```

#### get_state
```javascript
socket.emit('get_state', {
  game_id: 'game1',
  wallet_address: '0x...'
});
```

### Server → Client Events

#### connected
Emitted when client connects.

#### game_state
Emitted when game state changes. Contains full game state with players, community cards, pot, etc.

#### joined_game
Emitted when successfully joining a game.

#### left_game
Emitted when leaving a game.

#### error
Emitted when an error occurs.

## Architecture

```
arena_poker/
├── __init__.py
├── models/           # Pydantic models for data validation
├── auth/             # SIWE authentication logic
├── game/             # Poker game logic and hand evaluation
├── api/              # FastAPI REST endpoints
├── sockets/          # Socket.IO real-time communication
└── config.py         # Application configuration

main.py               # Application entry point
requirements.txt      # Python dependencies
```

### Core Components

1. **Models** (`arena_poker/models/`): Pydantic models for type-safe data structures
   - Card, Player, GameState
   - Action requests and responses
   - Withdrawal payloads

2. **Authentication** (`arena_poker/auth/`): SIWE implementation
   - Message generation
   - Signature verification using `eth_account`

3. **Game Logic** (`arena_poker/game/`): Complete poker implementation
   - Deck management
   - Hand evaluation (all poker hands)
   - Betting rounds
   - Game state management

4. **API** (`arena_poker/api/`): FastAPI endpoints
   - RESTful game management
   - Authentication endpoints
   - Withdrawal payload signing

5. **Socket.IO** (`arena_poker/sockets/`): Real-time communication
   - Room management
   - Game state broadcasting
   - Player action handling

## Game Flow

1. **Authentication**: Players authenticate using SIWE
2. **Create/Join Game**: Create a game or join an existing one via Socket.IO
3. **Start Hand**: When enough players join, start a new hand
4. **Betting Rounds**: Players take turns (pre-flop, flop, turn, river)
5. **Showdown**: Best hand wins the pot
6. **Withdrawal**: Players can request signed withdrawal payloads

## Example Client Usage

```python
import socketio

# Create client
sio = socketio.Client()

@sio.on('connected')
def on_connect(data):
    print(f"Connected: {data}")

@sio.on('game_state')
def on_game_state(data):
    print(f"Game state: {data}")

# Connect
sio.connect('http://localhost:8000', socketio_path='/socket.io')

# Join game
sio.emit('join_game', {
    'game_id': 'game1',
    'wallet_address': '0x1234...',
    'chips': 1000
})

# Start hand
sio.emit('start_hand', {'game_id': 'game1'})

# Make action
sio.emit('player_action', {
    'game_id': 'game1',
    'wallet_address': '0x1234...',
    'action': 'bet',
    'amount': 50
})
```

## Security Considerations

- SIWE authentication prevents wallet spoofing
- Withdrawal payloads are cryptographically signed
- Game state validation prevents cheating
- Server-side game logic ensures fairness

## Future Enhancements

- Persistent storage (PostgreSQL/Redis)
- Tournament support
- Side pots for all-in situations
- Spectator mode
- Chat functionality
- Advanced statistics and hand history
- Multi-table support

## License

MIT

## Contributing

Contributions are welcome! Please feel free to submit a Pull Request.