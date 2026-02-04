"""
Matchmaker module for Werewolf game.

This module implements dynamic player count matchmaking (6-9 players).
It manages a queue of players and starts games when conditions are met.
"""

import asyncio
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Callable


@dataclass
class QueuedPlayer:
    """Represents a player in the matchmaking queue."""
    sid: str
    wallet_address: str
    nickname: str
    join_time: float = field(default_factory=time.time)


class WerewolfMatchmaker:
    """
    Matchmaker for Werewolf games with dynamic player counts.
    
    Logic:
    - If queue_size >= 9: Pop 9 players -> Start Standard Game
    - If queue_size >= 6 AND wait_time > 30s: Pop queue_size (6-8) -> Start Adaptive Game
    - If queue_size < 6: Keep waiting
    """
    
    # Constants
    MIN_PLAYERS = 6
    STANDARD_GAME_SIZE = 9
    ADAPTIVE_WAIT_TIME = 30.0  # seconds
    CHECK_INTERVAL = 2.0  # seconds
    
    def __init__(self, game_start_callback: Optional[Callable] = None):
        """
        Initialize the matchmaker.
        
        Args:
            game_start_callback: Async function to call when starting a game.
                                 Should accept (players: List[QueuedPlayer], game_size: int)
        """
        self.queue: List[QueuedPlayer] = []
        self.queue_sids: set = set()  # For O(1) lookup
        self.game_start_callback = game_start_callback
        self._task: Optional[asyncio.Task] = None
        self._running = False
    
    def add_player(self, sid: str, wallet_address: str, nickname: str = "Player") -> bool:
        """
        Add a player to the matchmaking queue.
        
        Args:
            sid: Socket.IO session ID
            wallet_address: Player's wallet address
            nickname: Player's display name
            
        Returns:
            True if added successfully, False if already in queue
        """
        # Check if player already in queue (O(1) lookup)
        if sid in self.queue_sids:
            return False
        
        player = QueuedPlayer(
            sid=sid,
            wallet_address=wallet_address,
            nickname=nickname
        )
        self.queue.append(player)
        self.queue_sids.add(sid)
        return True
    
    def remove_player(self, sid: str) -> bool:
        """
        Remove a player from the matchmaking queue.
        
        Args:
            sid: Socket.IO session ID
            
        Returns:
            True if removed successfully, False if not in queue
        """
        if sid not in self.queue_sids:
            return False
        
        self.queue = [p for p in self.queue if p.sid != sid]
        self.queue_sids.discard(sid)
        return True
    
    def get_queue_size(self) -> int:
        """Get current queue size."""
        return len(self.queue)
    
    def get_queue_info(self) -> Dict:
        """
        Get information about the current queue state.
        
        Returns:
            Dictionary with queue statistics
        """
        if not self.queue:
            return {
                'size': 0,
                'oldest_wait_time': 0,
                'average_wait_time': 0
            }
        
        current_time = time.time()
        wait_times = [current_time - p.join_time for p in self.queue]
        
        return {
            'size': len(self.queue),
            'oldest_wait_time': max(wait_times),
            'average_wait_time': sum(wait_times) / len(wait_times)
        }
    
    async def _check_queue(self):
        """
        Periodic task to check queue and start games.
        
        This runs every CHECK_INTERVAL seconds and applies the matchmaking logic.
        """
        while self._running:
            try:
                await self._process_queue()
            except Exception as e:
                # Log error but continue running
                print(f"Error in matchmaker check_queue: {e}")
            
            # Wait before next check
            await asyncio.sleep(self.CHECK_INTERVAL)
    
    async def _process_queue(self):
        """Process the queue and start games if conditions are met."""
        queue_size = len(self.queue)
        
        # Not enough players
        if queue_size < self.MIN_PLAYERS:
            return
        
        # Standard game: 9+ players
        if queue_size >= self.STANDARD_GAME_SIZE:
            players = self.queue[:self.STANDARD_GAME_SIZE]
            self.queue = self.queue[self.STANDARD_GAME_SIZE:]
            # Update set
            for p in players:
                self.queue_sids.discard(p.sid)
            await self._start_game(players, self.STANDARD_GAME_SIZE)
            return
        
        # Adaptive game: 6-8 players with sufficient wait time
        if self.MIN_PLAYERS <= queue_size < self.STANDARD_GAME_SIZE:
            # Check oldest player's wait time
            current_time = time.time()
            oldest_wait = current_time - self.queue[0].join_time
            
            if oldest_wait >= self.ADAPTIVE_WAIT_TIME:
                # Start game with current queue size
                players = self.queue[:queue_size]
                self.queue = []
                # Clear set
                self.queue_sids.clear()
                await self._start_game(players, queue_size)
    
    async def _start_game(self, players: List[QueuedPlayer], game_size: int):
        """
        Start a game with the given players.
        
        Args:
            players: List of QueuedPlayer objects
            game_size: Number of players in this game
        """
        if self.game_start_callback:
            try:
                await self.game_start_callback(players, game_size)
            except Exception as e:
                # If game start fails, add players back to end of queue to avoid infinite retry
                print(f"Error starting game: {e}")
                self.queue.extend(players)
                # Update set
                for p in players:
                    self.queue_sids.add(p.sid)
    
    def start(self):
        """Start the matchmaker background task."""
        if self._running:
            return
        
        self._running = True
        self._task = asyncio.create_task(self._check_queue())
    
    def stop(self):
        """Stop the matchmaker background task."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
    
    def is_running(self) -> bool:
        """Check if matchmaker is running."""
        return self._running
    
    def is_player_in_queue(self, sid: str) -> bool:
        """
        Check if a player is in the queue (O(1) lookup).
        
        Args:
            sid: Socket.IO session ID
            
        Returns:
            True if player is in queue, False otherwise
        """
        return sid in self.queue_sids
    
    def clear_queue(self):
        """Clear all players from the queue."""
        self.queue.clear()
        self.queue_sids.clear()
