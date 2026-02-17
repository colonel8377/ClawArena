"""
Event Bus for Game Communication.

This implements a publish-subscribe pattern for game events,
allowing loose coupling between game components.
"""

from typing import Dict, List, Callable, Any, Optional
from enum import Enum
from dataclasses import dataclass, field
from datetime import datetime, timezone
import asyncio
from collections import defaultdict


from backend.utils import log

class EventType(Enum):
    """Types of game events."""
    # Chat events
    CHAT_MESSAGE = "chat_message"
    CHAT_BROADCAST = "chat_broadcast"
    
    # Player events
    PLAYER_JOINED = "player_joined"
    PLAYER_LEFT = "player_left"
    PLAYER_ACTION = "player_action"
    
    # Game state events
    GAME_STARTED = "game_started"
    GAME_ENDED = "game_ended"
    PHASE_CHANGED = "phase_changed"
    
    # System events
    ERROR = "error"
    WARNING = "warning"


@dataclass
class GameEvent:
    """
    Represents a game event.
    
    Events are immutable and carry all necessary information.
    """
    event_type: EventType
    game_id: str
    data: Dict[str, Any]
    timestamp: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source: Optional[str] = None  # Source player/component
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary."""
        return {
            'event_type': self.event_type.value,
            'game_id': self.game_id,
            'data': self.data,
            'timestamp': self.timestamp.isoformat(),
            'source': self.source
        }


class EventBus:
    """
    Central event bus for game communication.
    
    Uses publish-subscribe pattern to decouple game components.
    Each game instance has its own event bus for isolation.
    """
    
    def __init__(self, game_id: str):
        """
        Initialize event bus for a game.
        
        Args:
            game_id: Unique identifier for the game
        """
        self.game_id = game_id
        self._subscribers: Dict[EventType, List[Callable]] = defaultdict(list)
        self._event_history: List[GameEvent] = []
        self._max_history = 1000  # Prevent memory bloat
    
    def subscribe(self, event_type: EventType, handler: Callable[[GameEvent], Any]):
        """
        Subscribe to an event type.
        
        Args:
            event_type: Type of event to subscribe to
            handler: Callback function to handle the event
        """
        if handler not in self._subscribers[event_type]:
            self._subscribers[event_type].append(handler)
    
    def unsubscribe(self, event_type: EventType, handler: Callable[[GameEvent], Any]):
        """
        Unsubscribe from an event type.
        
        Args:
            event_type: Type of event to unsubscribe from
            handler: Callback function to remove
        """
        if handler in self._subscribers[event_type]:
            self._subscribers[event_type].remove(handler)
    
    def publish(self, event: GameEvent):
        """
        Publish an event to all subscribers.
        
        Args:
            event: Event to publish
        """
        # Store in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)
        
        # Notify subscribers
        for handler in self._subscribers[event.event_type]:
            try:
                handler(event)
            except Exception as e:
                log.error(f"Error in event handler: {e}")
    
    async def publish_async(self, event: GameEvent):
        """
        Publish an event asynchronously.
        
        Args:
            event: Event to publish
        """
        # Store in history
        self._event_history.append(event)
        if len(self._event_history) > self._max_history:
            self._event_history.pop(0)
        
        # Notify subscribers asynchronously
        tasks = []
        for handler in self._subscribers[event.event_type]:
            if asyncio.iscoroutinefunction(handler):
                tasks.append(handler(event))
            else:
                try:
                    handler(event)
                except Exception as e:
                    log.error(f"Error in event handler: {e}")
        
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
    
    def get_history(
        self, 
        event_type: Optional[EventType] = None,
        limit: Optional[int] = None
    ) -> List[GameEvent]:
        """
        Get event history.
        
        Args:
            event_type: Optional filter by event type
            limit: Optional limit on number of events
            
        Returns:
            List of events (most recent first if limit is set)
        """
        events = self._event_history
        
        # Filter by type
        if event_type:
            events = [e for e in events if e.event_type == event_type]
        
        # Apply limit
        if limit:
            events = events[-limit:]
        
        return events
    
    def clear_history(self):
        """Clear event history."""
        self._event_history.clear()
