"""
Abstract base class for all games.

This module defines the interface that all game implementations must follow.
It separates game management (BaseGame) from game logic (BaseEngine).

Each game instance has its own isolated communication channel (identified by game_id).
All messages within a game are scoped to that specific game session.
Uses event bus pattern for flexible, decoupled communication.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from enum import Enum
from datetime import datetime, timezone
from .channel import GameChannel


class GamePhase(Enum):
    """Base game phases that games can extend."""
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class BaseEngine(ABC):
    """
    Abstract base class for game logic engines.
    
    Engines handle the core game rules and state transitions,
    separate from room management and networking.
    """
    
    @abstractmethod
    def initialize_game(self, players: List[Dict]) -> bool:
        """
        Initialize the game with assigned players.
        
        Args:
            players: List of player dictionaries with sid, wallet_address, etc.
            
        Returns:
            True if initialization successful, False otherwise
        """
        pass
    
    @abstractmethod
    def process_action(self, player_id: str, action: str, **kwargs) -> Dict:
        """
        Process a game action from a player.
        
        Args:
            player_id: Player identifier (usually sid)
            action: Action type
            **kwargs: Additional action parameters
            
        Returns:
            Dict with 'success' bool and optional 'error' or 'data'
        """
        pass
    
    @abstractmethod
    def get_state(self, player_id: Optional[str] = None) -> Dict:
        """
        Get current game state.
        
        Args:
            player_id: Optional player ID for player-specific view
            
        Returns:
            Dict representing current game state
        """
        pass
    
    @abstractmethod
    def is_finished(self) -> bool:
        """
        Check if game has ended.
        
        Returns:
            True if game is over, False otherwise
        """
        pass
    
    @abstractmethod
    def get_winners(self) -> List[str]:
        """
        Get list of winner identifiers.
        
        Returns:
            List of winner wallet addresses or player IDs
        """
        pass


class BaseGame(ABC):
    """
    Abstract base class for games in the Arena.
    
    Handles room management, player lifecycle, and networking.
    Uses GameChannel for communication and event bus for events.
    """
    
    def __init__(self, game_id: str, game_type: str = "unknown"):
        """
        Initialize a game instance.
        
        Args:
            game_id: Unique identifier for this game instance
            game_type: Type of game (texas, werewolf, etc.)
        """
        self.game_id = game_id
        self.game_type = game_type
        self.phase = GamePhase.WAITING
        self.players: List[Dict] = []
        
        # Enhanced communication channel with event bus
        self.channel = GameChannel(channel_id=game_id, game_type=game_type)
        self.engine: Optional[BaseEngine] = None  # Game logic engine
    
    def get_channel_id(self) -> str:
        """
        Get the unique channel ID for this game instance.
        
        Each game instance has its own isolated communication channel.
        
        Returns:
            The game_id which serves as the channel identifier
        """
        return self.channel.channel_id
    
    @abstractmethod
    def add_player(self, sid: str, wallet_address: str, **kwargs) -> bool:
        """
        Add a player to the game.
        
        Args:
            sid: Socket.IO session ID
            wallet_address: Player's wallet address
            **kwargs: Additional player-specific parameters
            
        Returns:
            True if player was added successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def remove_player(self, sid: str) -> bool:
        """
        Remove a player from the game.
        
        Args:
            sid: Socket.IO session ID
            
        Returns:
            True if player was removed successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def can_start(self) -> bool:
        """
        Check if the game can start.
        
        Returns:
            True if game has minimum required players, False otherwise
        """
        pass
    
    @abstractmethod
    def start_game(self) -> bool:
        """
        Start the game.
        
        Returns:
            True if game started successfully, False otherwise
        """
        pass
    
    @abstractmethod
    def process_action(self, sid: str, action: str, **kwargs) -> Dict:
        """
        Process a player action.
        
        Args:
            sid: Socket.IO session ID
            action: Action type
            **kwargs: Additional action parameters
            
        Returns:
            Dict with 'success' bool and optional 'error' message
        """
        pass
    
    @abstractmethod
    def get_game_state(self, sid: Optional[str] = None) -> Dict:
        """
        Get the current game state.
        
        For games with hidden information, this should return a
        player-specific view when sid is provided.
        
        Args:
            sid: Socket.IO session ID (optional, for player-specific state)
            
        Returns:
            Dict representing the current game state
        """
        pass
    
    @abstractmethod
    def is_game_over(self) -> bool:
        """
        Check if the game is over.
        
        Returns:
            True if game has ended, False otherwise
        """
        pass
    
    @abstractmethod
    def get_winners(self) -> List[str]:
        """
        Get the list of winning player wallet addresses.
        
        Returns:
            List of winner wallet addresses (empty if no winners yet)
        """
        pass
    
    def add_chat_message(self, player_id: str, message: str, 
                        message_type: str = "chat", **metadata) -> Dict:
        """
        Add a chat message to the game channel.
        
        Each agent can speak in the channel. Messages are published via event bus.
        
        Args:
            player_id: Player identifier (sid or wallet_address)
            message: Message content
            message_type: Type of message ('chat', 'action', 'system')
            **metadata: Additional message metadata
            
        Returns:
            Dict with message data including timestamp
        """
        return self.channel.send_message(
            player_id=player_id,
            message=message,
            message_type=message_type,
            **metadata
        )
    
    def get_chat_history(self, player_id: Optional[str] = None, limit: Optional[int] = None) -> List[Dict]:
        """
        Get chat message history.
        
        Each agent can retrieve messages as reference for decision making.
        
        Args:
            player_id: Optional player ID requesting messages (for future filtering)
            limit: Optional limit on number of recent messages
            
        Returns:
            List of chat messages (most recent first if limit is set)
        """
        if player_id:
            # Get messages for specific agent (includes all messages for reference)
            return self.channel.get_participant_messages(player_id, limit=limit)
        return self.channel.get_messages(limit=limit)
    
    def get_event_bus(self):
        """
        Get the event bus for this game.
        
        Returns:
            EventBus instance for subscribing to game events
        """
        return self.channel.event_bus
