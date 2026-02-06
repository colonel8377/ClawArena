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
import asyncio
import json
import os
from .channel import GameChannel


class GamePhase(Enum):
    """Base game phases that games can extend."""
    WAITING = "waiting"
    IN_PROGRESS = "in_progress"
    FINISHED = "finished"


# ============================================================================
# CHAT PHASE RESTRICTION HELPERS
# ============================================================================

def chat_restricted_error(phase_value: str, reason: str = None) -> Dict:
    """
    Generate a standard error response for phase-restricted public chat.
    
    Used by all games to enforce the rule: public chat is only allowed
    during designated phases, preventing information leakage (e.g. revealing
    hole cards in poker, or speaking out of turn in werewolf).
    
    Args:
        phase_value: Current phase name (for the error message)
        reason: Optional custom reason string
        
    Returns:
        Dict with success=False, error message, and error_code='CHAT_PHASE_RESTRICTED'
    """
    return {
        'success': False,
        'error': reason or f'Public chat is not allowed during {phase_value}',
        'error_code': 'CHAT_PHASE_RESTRICTED'
    }


def check_chat_phase(current_phase, allowed_phases: set) -> Optional[Dict]:
    """
    Check if public chat is allowed in the current phase.
    
    Args:
        current_phase: Current game phase (Enum with .value)
        allowed_phases: Set of phases where public chat is freely allowed
        
    Returns:
        None if chat is allowed, or a CHAT_PHASE_RESTRICTED error dict if blocked
    """
    if current_phase in allowed_phases:
        return None
    phase_value = current_phase.value if hasattr(current_phase, 'value') else str(current_phase)
    return chat_restricted_error(phase_value)


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
    Enhanced with unified zombie/timeout handling and Redis integration.
    """
    
    def __init__(self, game_id: str, game_type: str = "unknown", timeout_seconds: int = 30):
        """
        Initialize a game instance.
        
        Args:
            game_id: Unique identifier for this game instance
            game_type: Type of game (texas, werewolf, etc.)
            timeout_seconds: Default timeout for player actions (in seconds)
        """
        self.game_id = game_id
        self.game_type = game_type
        self.phase = GamePhase.WAITING
        self.players: List[Dict] = []
        
        # Enhanced communication channel with event bus
        self.channel = GameChannel(channel_id=game_id, game_type=game_type)
        self.engine: Optional[BaseEngine] = None  # Game logic engine
        
        # Unified timeout and zombie handling
        self.timeout_seconds = timeout_seconds
        self.last_action_time: Dict[str, datetime] = {}  # sid -> last action timestamp
        self._action_lock = asyncio.Lock()  # Prevent race conditions
        
        # Redis connection (lazy-initialized)
        self._redis_client = None
        self._redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379')
    
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
    
    # ========================================================================
    # UNIFIED TIMEOUT & ZOMBIE HANDLING
    # ========================================================================
    
    def update_player_action_time(self, sid: str):
        """
        Update the last action time for a player.
        
        Args:
            sid: Socket.IO session ID
        """
        self.last_action_time[sid] = datetime.now(timezone.utc)
    
    async def check_timeouts(self) -> List[str]:
        """
        Check for players who have timed out.
        
        Returns:
            List of socket IDs (sids) of players who timed out
        """
        timed_out_players = []
        current_time = datetime.now(timezone.utc)
        
        for player in self.players:
            sid = player.get('sid')
            if not sid:
                continue
            
            last_action = self.last_action_time.get(sid)
            if last_action:
                time_since_action = (current_time - last_action).total_seconds()
                if time_since_action > self.timeout_seconds:
                    timed_out_players.append(sid)
        
        return timed_out_players
    
    async def handle_timeout(self, sid: str) -> Dict:
        """
        Handle a player timeout by executing default action.
        
        Args:
            sid: Socket.IO session ID of the timed-out player
            
        Returns:
            Dict with result of default action execution
        """
        async with self._action_lock:
            # Execute game-specific default action
            result = await self.execute_default_action(sid)
            
            # Update zombie tracking if needed
            player = self._get_player_by_sid(sid)
            if player:
                player.setdefault('consecutive_timeouts', 0)
                player['consecutive_timeouts'] += 1
                
                # Mark as zombie after 2 consecutive timeouts
                if player['consecutive_timeouts'] >= 2:
                    player['status'] = 'zombie'
            
            return result
    
    @abstractmethod
    async def execute_default_action(self, sid: str) -> Dict:
        """
        Execute the default action for a timed-out player.
        
        Game-specific implementation:
        - Texas Hold'em: Fold
        - Werewolf: Skip/No vote
        
        Args:
            sid: Socket.IO session ID
            
        Returns:
            Dict with 'success' bool and optional 'error' message
        """
        pass
    
    def _get_player_by_sid(self, sid: str) -> Optional[Dict]:
        """
        Get player dict by socket ID.
        
        Args:
            sid: Socket.IO session ID
            
        Returns:
            Player dict or None if not found
        """
        for player in self.players:
            if player.get('sid') == sid:
                return player
        return None
    
    # ========================================================================
    # REDIS + MYSQL HYBRID STORAGE
    # ========================================================================
    
    async def _init_redis(self):
        """Initialize Redis connection if not already connected."""
        if self._redis_client is None:
            try:
                import redis.asyncio as redis
                self._redis_client = redis.from_url(
                    self._redis_url,
                    encoding='utf-8',
                    decode_responses=True
                )
                await self._redis_client.ping()
            except Exception as e:
                print(f"⚠ Redis init failed for game {self.game_id}: {e}")
                self._redis_client = None
    
    async def save_state_to_redis(self, state: Optional[Dict] = None):
        """
        Save current game state to Redis for hot storage.
        
        Args:
            state: Optional state dict. If not provided, calls get_game_state()
        """
        await self._init_redis()
        
        if self._redis_client is None:
            return  # Redis not available, skip
        
        try:
            if state is None:
                state = self.get_game_state()
            
            # Add metadata
            state_with_meta = {
                'game_id': self.game_id,
                'game_type': self.game_type,
                'phase': self.phase.value if isinstance(self.phase, Enum) else str(self.phase),
                'updated_at': datetime.now(timezone.utc).isoformat(),
                'state': state
            }
            
            redis_key = f"game:{self.game_id}:state"
            await self._redis_client.set(
                redis_key,
                json.dumps(state_with_meta),
                ex=3600  # 1 hour expiry
            )
        except Exception as e:
            print(f"⚠ Failed to save state to Redis for game {self.game_id}: {e}")
    
    async def load_state_from_redis(self) -> Optional[Dict]:
        """
        Load game state from Redis.
        
        Returns:
            State dict or None if not found or Redis unavailable
        """
        await self._init_redis()
        
        if self._redis_client is None:
            return None
        
        try:
            redis_key = f"game:{self.game_id}:state"
            data = await self._redis_client.get(redis_key)
            
            if data:
                return json.loads(data)
            return None
        except Exception as e:
            print(f"⚠ Failed to load state from Redis for game {self.game_id}: {e}")
            return None
    
    async def save_checkpoint(self, event_type: str = "manual"):
        """
        Save a checkpoint to MySQL for persistence.
        
        Called on critical events:
        - Game Start
        - Phase Change
        - Game End
        
        Args:
            event_type: Type of checkpoint event
        """
        # This is a hook for subclasses to implement MySQL persistence
        # Default implementation does nothing
        pass
    
    async def close_redis(self):
        """Close Redis connection."""
        if self._redis_client:
            try:
                await self._redis_client.close()
            except Exception:
                pass
            self._redis_client = None
