"""
Abstract base class for all games.

This module defines the interface that all game implementations must follow.
"""

from abc import ABC, abstractmethod
from typing import Dict, List, Any, Optional
from enum import Enum


class GamePhase(Enum):
    """Base game phases that games can extend."""
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


class BaseGame(ABC):
    """
    Abstract base class for games in the Arena.
    
    All games must implement these methods to ensure consistent
    behavior across different game types.
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
