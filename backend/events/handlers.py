"""
Event handlers for common game events.
"""

from abc import ABC, abstractmethod
from typing import Optional
from .event_bus import GameEvent


from backend.utils import log

class EventHandler(ABC):
    """
    Abstract base class for event handlers.
    
    Provides structured way to handle events.
    """
    
    @abstractmethod
    def handle(self, event: GameEvent):
        """
        Handle an event.
        
        Args:
            event: The event to handle
        """
        pass
    
    def __call__(self, event: GameEvent):
        """Make handler callable."""
        return self.handle(event)


class ChatEventHandler(EventHandler):
    """
    Handler for chat events.
    
    Stores messages and provides retrieval.
    """
    
    def __init__(self):
        self.messages = []
    
    def handle(self, event: GameEvent):
        """Store chat message."""
        self.messages.append(event.data)
    
    def get_messages(self, limit: Optional[int] = None):
        """Get chat messages."""
        if limit:
            return self.messages[-limit:]
        return self.messages


class LoggingEventHandler(EventHandler):
    """
    Handler that logs all events.
    """
    
    def handle(self, event: GameEvent):
        """Log the event."""
        log.info(f"[{event.timestamp}] {event.event_type.value}: {event.data}")
