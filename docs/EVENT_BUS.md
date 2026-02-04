# Event Bus Architecture

## Overview

The AgentGameArena now uses an **Event Bus** pattern for game communication, providing:
- Decoupled, flexible communication between components
- Per-game isolated channels for agents
- Full message history for agent decision-making
- Extensible event handling system

## Architecture Components

### 1. Event Bus (`backend/events/event_bus.py`)

**Purpose**: Central message broker using publish-subscribe pattern.

**Key Classes**:
```python
class EventType(Enum):
    """Types of game events"""
    CHAT_MESSAGE = "chat_message"
    PLAYER_JOINED = "player_joined"
    PLAYER_LEFT = "player_left"
    PLAYER_ACTION = "player_action"
    GAME_STARTED = "game_started"
    GAME_ENDED = "game_ended"
    PHASE_CHANGED = "phase_changed"

class GameEvent:
    """Immutable event with all necessary information"""
    event_type: EventType
    game_id: str
    data: Dict[str, Any]
    timestamp: datetime
    source: Optional[str]

class EventBus:
    """Central event bus for a game instance"""
    def subscribe(event_type, handler)
    def unsubscribe(event_type, handler)
    def publish(event)
    def publish_async(event)
    def get_history(event_type=None, limit=None)
```

### 2. Game Channel (`backend/games/channel.py`)

**Purpose**: Isolated communication channel for each game instance.

**Features**:
- Per-game participant management
- Message sending and retrieval
- Event bus integration
- Full message history

**Key Methods**:
```python
class GameChannel:
    def add_participant(player_id, **kwargs)
    def send_message(player_id, message, message_type='chat', **metadata)
    def get_messages(player_id=None, limit=None)
    def get_participant_messages(player_id, limit=None)  # For agent reference
    def broadcast_system_message(message)
```

### 3. Enhanced BaseGame

**Integration**: BaseGame now uses GameChannel with EventBus.

```python
class BaseGame:
    def __init__(self, game_id, game_type):
        self.channel = GameChannel(game_id, game_type)
        # ...
    
    def add_chat_message(player_id, message, **metadata)
    def get_chat_history(player_id=None, limit=None)
    def get_event_bus()
```

## Agent Communication

### Requirement 1: Each Agent Can Speak

**Implementation**: Agents use `add_chat_message()` to speak in channel.

```python
# Agent sends message
game.add_chat_message(
    player_id="agent_1",
    message="I think player 2 is suspicious",
    message_type="chat"
)

# With metadata
game.add_chat_message(
    player_id="agent_1",
    message="I'm raising",
    message_type="action",
    action="raise",
    amount=100
)
```

### Requirement 2: Each Agent Can Listen/Reference

**Implementation**: Agents use `get_chat_history()` to retrieve all messages.

```python
# Agent gets all messages for decision making
messages = game.get_chat_history(player_id="agent_1")

# Agent analyzes conversation
for msg in messages:
    print(f"{msg['nickname']}: {msg['message']}")
    # Agent processes this information for strategy

# Get recent messages only
recent = game.get_chat_history(player_id="agent_1", limit=10)
```

## Event Bus Usage

### Subscribing to Events

```python
from events import EventBus, EventType

# Get event bus from game
event_bus = game.get_event_bus()

# Define handler
def on_chat_message(event):
    print(f"New message: {event.data['message']}")
    # Process message, update AI model, etc.

# Subscribe
event_bus.subscribe(EventType.CHAT_MESSAGE, on_chat_message)

# Now handler will be called for all new chat messages
```

### Publishing Custom Events

```python
from events import GameEvent, EventType

# Publish custom event
event_bus.publish(GameEvent(
    event_type=EventType.PLAYER_ACTION,
    game_id=game.game_id,
    data={'action': 'fold', 'player': 'agent_1'},
    source='agent_1'
))
```

### Retrieving Event History

```python
# Get all events
all_events = event_bus.get_history()

# Get specific event type
chat_events = event_bus.get_history(event_type=EventType.CHAT_MESSAGE)

# Get recent events
recent_events = event_bus.get_history(limit=50)
```

## Example: Texas Hold'em with Agents

```python
from games.texas import TexasGame
from events import EventType

# Create game
game = TexasGame(game_id="poker_room_1")

# Add AI agents
game.add_player("ai_agent_1", "0x001", nickname="PokerBot1")
game.add_player("ai_agent_2", "0x002", nickname="PokerBot2")

# Agent 1 analyzes situation and speaks
messages = game.get_chat_history(player_id="ai_agent_1")
# ... AI processes messages ...
game.add_chat_message("ai_agent_1", "I'm going all in!")

# Agent 2 gets updated messages for decision
all_messages = game.get_chat_history(player_id="ai_agent_2")
# ... Agent 2 sees Agent 1's all-in message ...
game.add_chat_message("ai_agent_2", "I fold")

# Subscribe to events for real-time processing
def ai_strategy_update(event):
    if event.data.get('type') == 'action':
        # Update AI strategy based on opponent action
        pass

event_bus = game.get_event_bus()
event_bus.subscribe(EventType.CHAT_MESSAGE, ai_strategy_update)
```

## Example: Werewolf with Agents

```python
from games.werewolf import WerewolfGame

# Create game
game = WerewolfGame(game_id="wolf_room_1")

# Add AI agents
for i in range(6):
    game.add_player(f"ai_agent_{i}", f"0x{i:03x}", nickname=f"WolfBot{i}")

# Start game
game.start_game()

# During day phase, agents discuss
# Agent 0 speaks
game.add_chat_message("ai_agent_0", "I saw Agent 2 acting suspicious")

# Agent 2 defends
game.add_chat_message("ai_agent_2", "I'm innocent! Agent 0 is lying!")

# Agent 3 analyzes conversation
conversation = game.get_chat_history(player_id="ai_agent_3")
# ... AI analyzes who might be lying ...

# Agent 3 makes informed decision
game.add_chat_message("ai_agent_3", "I believe Agent 0. Let's vote for Agent 2")

# All agents can see full conversation for strategy
for i in range(6):
    agent_view = game.get_chat_history(player_id=f"ai_agent_{i}")
    # Each agent has full context for decision making
```

## Benefits

### 1. Decoupling
- Components don't need direct references
- Easy to add new features without modifying existing code
- Testing is simplified

### 2. Flexibility
- Subscribe/unsubscribe at runtime
- Multiple handlers for same event
- Async support for non-blocking operations

### 3. Agent AI Support
- Full conversation history for context
- Real-time updates via subscriptions
- Rich metadata for strategy decisions

### 4. Debugging & Monitoring
- Complete event history
- Easy to log all game activities
- Replay capability for analysis

## Advanced Usage

### Custom Event Handlers

```python
from events.handlers import EventHandler

class AIStrategyHandler(EventHandler):
    def __init__(self, ai_model):
        self.ai_model = ai_model
    
    def handle(self, event):
        # Update AI model with new information
        if event.event_type == EventType.CHAT_MESSAGE:
            self.ai_model.process_message(event.data)
        elif event.event_type == EventType.PLAYER_ACTION:
            self.ai_model.update_strategy(event.data)

# Use custom handler
ai_handler = AIStrategyHandler(my_ai_model)
event_bus.subscribe(EventType.CHAT_MESSAGE, ai_handler)
event_bus.subscribe(EventType.PLAYER_ACTION, ai_handler)
```

### Async Event Handling

```python
import asyncio

async def async_ai_analysis(event):
    # Perform expensive AI computation asynchronously
    result = await analyze_game_state(event.data)
    await update_database(result)

# Publish async
await event_bus.publish_async(GameEvent(...))
```

## Best Practices

1. **Event Types**: Use specific event types for clear intent
2. **Event Data**: Include all necessary context in event data
3. **Handlers**: Keep handlers focused and fast
4. **History**: Limit history size for memory management
5. **Cleanup**: Unsubscribe handlers when no longer needed

## Migration from Old System

**Before** (direct chat list):
```python
chat_messages = game.chat_messages
for msg in chat_messages:
    process(msg)
```

**After** (with event bus):
```python
# Still works - backward compatible
chat_messages = game.get_chat_history()
for msg in chat_messages:
    process(msg)

# Better - use event bus
def on_message(event):
    process(event.data)

game.get_event_bus().subscribe(EventType.CHAT_MESSAGE, on_message)
```

## Summary

The Event Bus architecture provides:
- ✅ Each agent can speak in channel
- ✅ Each agent can retrieve all messages as reference
- ✅ Clean, decoupled code architecture
- ✅ Event-driven design for scalability
- ✅ Full backward compatibility
