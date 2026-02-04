"""
Game Channel - Enhanced communication channel with event bus.

Provides structured, isolated communication for each game instance.
"""

from datetime import datetime, timezone
from typing import List, Dict, Any, Optional

from backend.events.event_bus import EventBus, GameEvent, EventType


class GameChannel:
    """
    Communication channel for a game instance.
    
    Each game has its own channel for isolated communication.
    Uses event bus pattern for flexible message handling.
    """
    
    def __init__(self, channel_id: str, game_type: str):
        """
        Initialize a game channel.
        
        Args:
            channel_id: Unique identifier for this channel (usually game_id)
            game_type: Type of game (texas, werewolf, etc.)
        """
        self.channel_id = channel_id
        self.game_type = game_type
        self.event_bus = EventBus(channel_id)
        self.participants: Dict[str, Dict] = {}  # player_id -> player info
    
    def add_participant(self, player_id: str, **kwargs):
        """
        Add a participant to the channel.
        
        Args:
            player_id: Unique player identifier
            **kwargs: Additional player info (wallet_address, nickname, etc.)
        """
        self.participants[player_id] = {
            'player_id': player_id,
            'joined_at': datetime.now(timezone.utc),
            **kwargs
        }
        
        # Publish join event
        self.event_bus.publish(GameEvent(
            event_type=EventType.PLAYER_JOINED,
            game_id=self.channel_id,
            data={
                'player_id': player_id,
                'nickname': kwargs.get('nickname', 'Unknown')
            },
            source=player_id
        ))
    
    def remove_participant(self, player_id: str):
        """
        Remove a participant from the channel.
        
        Args:
            player_id: Player identifier to remove
        """
        if player_id in self.participants:
            del self.participants[player_id]
            
            # Publish leave event
            self.event_bus.publish(GameEvent(
                event_type=EventType.PLAYER_LEFT,
                game_id=self.channel_id,
                data={'player_id': player_id},
                source=player_id
            ))
    
    def send_message(
        self, 
        player_id: str, 
        message: str,
        message_type: str = 'chat',
        **metadata
    ) -> Dict[str, Any]:
        """
        Send a message in the channel.
        
        Args:
            player_id: ID of player sending message
            message: Message content
            message_type: Type of message ('chat', 'action', 'system')
            **metadata: Additional message metadata
            
        Returns:
            Message data with timestamp
        """
        participant = self.participants.get(player_id, {})
        nickname = participant.get('nickname', 'Unknown')
        
        message_data = {
            'player_id': player_id,
            'nickname': nickname,
            'message': message,
            'type': message_type,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            **metadata
        }
        
        # Publish chat event
        self.event_bus.publish(GameEvent(
            event_type=EventType.CHAT_MESSAGE,
            game_id=self.channel_id,
            data=message_data,
            source=player_id
        ))
        
        return message_data
    
    def get_messages(
        self, 
        player_id: Optional[str] = None,
        limit: Optional[int] = None
    ) -> List[Dict[str, Any]]:
        """
        Get messages from the channel.
        
        Args:
            player_id: Optional player ID (for future filtering)
            limit: Optional limit on number of messages
            
        Returns:
            List of message data dictionaries
        """
        chat_events = self.event_bus.get_history(
            event_type=EventType.CHAT_MESSAGE,
            limit=limit
        )
        
        return [event.data for event in chat_events]
    
    def get_participant_messages(self, player_id: str, limit: Optional[int] = None) -> List[Dict]:
        """
        Get all messages for a specific participant to reference.
        
        This allows agents to get other players' messages as reference.
        
        Args:
            player_id: ID of player requesting messages
            limit: Optional limit on number of messages
            
        Returns:
            List of all channel messages (for agent reference)
        """
        return self.get_messages(limit=limit)
    
    def get_participants(self) -> List[Dict]:
        """Get list of all participants in the channel."""
        return list(self.participants.values())
    
    def broadcast_system_message(self, message: str):
        """
        Broadcast a system message to all participants.
        
        Args:
            message: System message content
        """
        return self.send_message(
            player_id='system',
            message=message,
            message_type='system'
        )
    
    def clear_history(self):
        """Clear channel message history."""
        self.event_bus.clear_history()
