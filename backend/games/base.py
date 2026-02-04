"""
Abstract base class for all games.

This module defines the interface that all game implementations must follow.
It separates game management (BaseGame) from game logic (BaseEngine).
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from enum import Enum
from datetime import datetime


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
    Delegates game logic to a BaseEngine instance.
    """
    
    def __init__(self, game_id: str):
        """
        Initialize a game instance.
        
        Args:
            game_id: Unique identifier for this game instance
        """
        self.game_id = game_id
        self.phase = GamePhase.WAITING
        self.players: List[Dict] = []
        self.chat_messages: List[Dict] = []  # Unified chat system
        self.engine: Optional[BaseEngine] = None  # Game logic engine
    
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
        Add a chat message to the game.
        
        This method provides a unified chat system for all games.
        
        Args:
            player_id: Player identifier (sid or wallet_address)
            message: Message content
            message_type: Type of message ('chat', 'action', 'system')
            **metadata: Additional message metadata
            
        Returns:
            Dict with message data including timestamp
        """
        timestamp = datetime.utcnow().isoformat()
        
        # Find player nickname
        player_nickname = "Unknown"
        for p in self.players:
            if p.get('sid') == player_id or p.get('wallet_address') == player_id:
                player_nickname = p.get('nickname', 'Player')
                break
        
        chat_msg = {
            'player_id': player_id,
            'nickname': player_nickname,
            'message': message,
            'type': message_type,
            'timestamp': timestamp,
            **metadata
        }
        
        self.chat_messages.append(chat_msg)
        return chat_msg
    
    def get_chat_history(self, limit: Optional[int] = None) -> List[Dict]:
        """
        Get chat message history.
        
        Args:
            limit: Optional limit on number of recent messages
            
        Returns:
            List of chat messages (most recent first if limit is set)
        """
        if limit:
            return self.chat_messages[-limit:]
        return self.chat_messages
