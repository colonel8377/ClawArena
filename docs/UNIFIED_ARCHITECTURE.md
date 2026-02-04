# Unified Game Architecture

This document describes the unified game architecture implemented in the Agent Game Arena.

## Overview

All games in the Arena now follow a consistent architecture pattern:
- **BaseGame**: Handles room management, players, networking, and chat
- **BaseEngine**: Handles core game rules and logic (optional abstraction)
- **ChatMessage**: Database model for persistent chat across games

## Architecture Components

### 1. BaseGame (Abstract Class)

Location: `backend/games/base.py`

**Purpose**: Provides a consistent interface for all game types.

**Responsibilities**:
- Player lifecycle management (add, remove)
- Game state management (waiting, in progress, finished)
- Chat system (unified across all games)
- Abstract methods that each game must implement

**Key Methods**:
```python
# Abstract methods (must be implemented by each game)
add_player(sid, wallet_address, **kwargs) -> bool
remove_player(sid) -> bool
can_start() -> bool
start_game() -> bool
process_action(sid, action, **kwargs) -> Dict
get_game_state(sid=None) -> Dict
is_game_over() -> bool
get_winners() -> List[str]

# Built-in chat system (inherited by all games)
add_chat_message(player_id, message, message_type='chat', **metadata) -> Dict
get_chat_history(limit=None) -> List[Dict]
```

### 2. BaseEngine (Abstract Class)

Location: `backend/games/base.py`

**Purpose**: Separates game logic from game management.

**Responsibilities**:
- Game rule enforcement
- State transitions
- Win condition checking
- Pure game logic (no networking, no database)

**Key Methods**:
```python
initialize_game(players) -> bool
process_action(player_id, action, **kwargs) -> Dict
get_state(player_id=None) -> Dict
is_finished() -> bool
get_winners() -> List[str]
```

### 3. ChatMessage (Database Model)

Location: `backend/database/models.py`

**Purpose**: Persistent storage of chat messages across game sessions.

**Fields**:
- `game_session_id`: Link to game session
- `player_wallet`: Player who sent the message
- `nickname`: Player display name
- `message`: Message content
- `message_type`: 'chat', 'action', 'system'
- `metadata`: JSON field for additional data
- `timestamp`: When message was sent

**Relationships**:
- `game_session`: Many-to-one with GameSession

## Game Implementations

### Texas Hold'em

**Structure**:
```
backend/games/texas/
├── __init__.py          # Exports TexasGame, PokerEngine
├── game.py              # TexasGame (extends BaseGame)
└── poker_engine.py      # PokerEngine (core poker logic)
```

**TexasGame Class**:
- Extends `BaseGame`
- Wraps `PokerEngine` for game logic
- Implements unified chat system
- Handles player buy-ins and chip management

**Usage**:
```python
from games.texas import TexasGame

game = TexasGame(game_id="texas_1", small_blind=25, big_blind=50)
game.add_player(sid="player1", wallet_address="0x123", buy_in=1000)
game.start_game()
game.process_action(sid="player1", action="raise", amount=100)
game.process_action(sid="player1", action="chat", message="Nice hand!")
```

### Werewolf

**Structure**:
```
backend/games/werewolf/
├── __init__.py          # Exports WerewolfGame
├── game.py              # WerewolfGame (extends BaseGame)
├── roles.py             # Role definitions
├── game_config.py       # Setup configurations
└── matchmaker.py        # Matchmaking logic
```

**WerewolfGame Class**:
- Extends `BaseGame`
- Contains game logic directly (no separate engine)
- Implements unified chat system
- Handles role assignment and phase management

**Usage**:
```python
from games.werewolf import WerewolfGame

game = WerewolfGame(game_id="wolf_1")
game.add_player(sid="player1", wallet_address="0x123", nickname="Alice")
# ... add 5 more players
game.start_game()
game.process_action(sid="player1", action="night_kill", target_sid="player2")
game.process_action(sid="player1", action="chat", message="Who's suspicious?")
```

## Chat System

### Unified Chat Feature

All games now have a built-in chat system through `BaseGame`:

**Adding Messages**:
```python
# From within a game class
chat_msg = self.add_chat_message(
    player_id="sid123",
    message="Hello everyone!",
    message_type="chat"  # or "action", "system"
)
```

**Retrieving History**:
```python
# Get all messages
all_messages = game.get_chat_history()

# Get recent messages
recent = game.get_chat_history(limit=50)
```

**Message Format**:
```python
{
    'player_id': 'sid123',
    'nickname': 'Alice',
    'message': 'Hello everyone!',
    'type': 'chat',
    'timestamp': '2026-02-04T13:07:55.123456'
}
```

### Database Persistence

Chat messages can be persisted to the database for reconnection:

```python
from database.models import ChatMessage
from database.connection import get_db

# Save chat message
db = get_db()
db_message = ChatMessage(
    game_session_id=game.game_id,
    player_wallet=player['wallet_address'],
    nickname=player['nickname'],
    message=chat_msg['message'],
    message_type='chat',
    timestamp=datetime.utcnow()
)
db.add(db_message)
db.commit()

# Retrieve chat history
messages = db.query(ChatMessage)\
    .filter(ChatMessage.game_session_id == game_id)\
    .order_by(ChatMessage.timestamp.desc())\
    .limit(50)\
    .all()
```

## Benefits of Unified Architecture

1. **Consistency**: All games follow the same pattern
2. **Maintainability**: Changes to base features benefit all games
3. **Extensibility**: Easy to add new games following the pattern
4. **Testing**: Common interface makes testing easier
5. **Documentation**: Developers know what to expect

## Adding a New Game

To add a new game to the Arena:

1. **Create game directory**: `backend/games/mygame/`

2. **Implement BaseGame**:
```python
from backend.games.base import BaseGame

class MyGame(BaseGame):
    def __init__(self, game_id: str):
        super().__init__(game_id)
        # ... game-specific initialization
    
    def add_player(self, sid, wallet_address, **kwargs):
        # Implement player addition
        pass
    
    # ... implement all abstract methods
```

3. **Use unified chat**:
```python
def process_action(self, sid, action, **kwargs):
    if action == 'chat':
        message = kwargs.get('message', '')
        return {'success': True, 'chat': self.add_chat_message(sid, message)}
    # ... handle other actions
```

4. **Export in __init__.py**:
```python
from .game import MyGame
__all__ = ['MyGame']
```

5. **Register in main.py**:
```python
from games.mygame import MyGame

my_games: Dict[str, MyGame] = {}
```

## Migration Notes

### For Existing Texas Hold'em Code

The old `PokerEngine` still works and is backward compatible. New code should use `TexasGame`:

**Before**:
```python
from poker_engine import create_poker_game
table = create_poker_game(table_id)
```

**After**:
```python
from games.texas import TexasGame
game = TexasGame(game_id=table_id)
```

### For Existing Werewolf Code

`WerewolfGame` now includes chat support. Update action handling:

**Before**:
```python
# Chat was handled separately
```

**After**:
```python
result = game.process_action(sid, 'chat', message='Hello!')
```

## Testing

Example test for a new game:

```python
def test_my_game():
    from backend.games.mygame import MyGame
    from backend.games.base import BaseGame
    
    # Create game
    game = MyGame(game_id="test_1")
    
    # Verify it extends BaseGame
    assert isinstance(game, BaseGame)
    
    # Test chat system
    game.add_player("sid1", "0x123", nickname="Alice")
    chat = game.add_chat_message("sid1", "Test message")
    assert chat['message'] == "Test message"
    
    # Test game state includes chat
    state = game.get_game_state()
    assert 'chat_messages' in state
```

## Future Enhancements

Potential improvements to the unified architecture:

1. **Persistent Chat**: Automatic sync to database
2. **Chat Channels**: Public, team, private channels
3. **Message Filtering**: Profanity filter, rate limiting
4. **Rich Messages**: Support for emojis, formatting
5. **Voice Chat**: Integration with voice channels
6. **Replay System**: Replay games from chat history
