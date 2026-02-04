"""
Texas Hold'em Game Implementation.

This module implements TexasGame which extends BaseGame and uses
the poker_engine.PokerEngine for core game logic.
"""

from typing import Dict, List, Optional, Any
from ..base import BaseGame, GamePhase
from .texas_engine import TexasEngine, PokerPhase


class TexasGame(BaseGame):
    """
    Texas Hold'em game implementation extending BaseGame.
    
    This class wraps the PokerEngine and provides the BaseGame interface
    for consistent game management across the Arena.
    """
    
    MIN_PLAYERS = 2
    MAX_PLAYERS = 9
    
    def __init__(self, game_id: str, small_blind: int = 25, big_blind: int = 50):
        """
        Initialize a Texas Hold'em game.
        
        Args:
            game_id: Unique identifier for this game
            small_blind: Small blind amount
            big_blind: Big blind amount
        """
        # Initialize with 20 second timeout for poker actions
        super().__init__(game_id, game_type="texas", timeout_seconds=20)
        
        # Use PokerEngine as the game logic engine
        self.engine = TexasEngine(
            game_id=game_id,
            small_blind=small_blind,
            big_blind=big_blind
        )
        
        # Track poker-specific state
        self.small_blind = small_blind
        self.big_blind = big_blind
    
    def add_player(self, sid: str, wallet_address: str, **kwargs) -> bool:
        """Add a player to the game."""
        if len(self.players) >= self.MAX_PLAYERS:
            return False
        
        if self.phase != GamePhase.WAITING:
            # In poker, players can join mid-game but sit out until next hand
            pass
        
        # Check if player already in game
        if any(p['sid'] == sid for p in self.players):
            return False
        
        nickname = kwargs.get('nickname', f'Player{len(self.players) + 1}')
        buy_in = kwargs.get('buy_in', 1000)
        
        # Add to BaseGame player list
        player = {
            'sid': sid,
            'wallet_address': wallet_address,
            'nickname': nickname,
            'buy_in': buy_in
        }
        self.players.append(player)
        
        # Register with game channel
        self.channel.add_participant(
            player_id=sid,
            wallet_address=wallet_address,
            nickname=nickname
        )
        
        # Add to poker engine
        success = self.engine.add_player(
            sid=sid,
            wallet_address=wallet_address,
            nickname=nickname,
            buy_in=buy_in
        )
        
        return success
    
    def remove_player(self, sid: str) -> bool:
        """Remove a player from the game."""
        self.players = [p for p in self.players if p['sid'] != sid]
        return self.engine.remove_player(sid)
    
    def can_start(self) -> bool:
        """Check if game can start."""
        return len(self.players) >= self.MIN_PLAYERS and self.engine.can_start()
    
    def start_game(self) -> bool:
        """Start the game."""
        if not self.can_start():
            return False
        
        if self.phase != GamePhase.WAITING:
            return False
        
        # Start first hand
        result = self.engine.start_hand()
        
        if result.get('success'):
            self.phase = GamePhase.IN_PROGRESS
            return True
        
        return False
    
    def _reset_timeout_tracking(self, sid: str):
        """
        Reset timeout tracking for a player.
        
        Clears consecutive timeout count and zombie status on successful action.
        
        Args:
            sid: Socket.IO session ID
        """
        player = self._get_player_by_sid(sid)
        if player:
            player['consecutive_timeouts'] = 0
            if player.get('status') == 'zombie':
                player['status'] = 'active'
    
    def process_action(self, sid: str, action: str, **kwargs) -> Dict:
        """
        Process a player action.
        
        Actions:
        - fold: Fold the hand
        - check: Check (no bet)
        - call: Call the current bet
        - raise: Raise the bet (amount in kwargs)
        - all_in: Go all-in
        - chat: Send a chat message (message in kwargs)
        """
        # Update last action time for zombie tracking
        self.update_player_action_time(sid)
        
        # Reset consecutive timeouts on successful action
        self._reset_timeout_tracking(sid)
        
        if action == 'chat':
            # Handle chat through BaseGame
            message = kwargs.get('message', '')
            return {'success': True, 'chat': self.add_chat_message(sid, message)}
        
        # Delegate to poker engine
        if action == 'raise':
            amount = kwargs.get('amount', self.big_blind)
            return self.engine.process_move(sid, action, amount=amount)
        else:
            return self.engine.process_move(sid, action)
    
    def get_game_state(self, sid: Optional[str] = None) -> Dict:
        """
        Get the current game state.
        
        For poker, this includes player-specific hole cards when sid is provided.
        """
        # Get base state from engine
        engine_state = self.engine.get_game_state(sid)
        
        # Add chat history from BaseGame
        state = {
            **engine_state,
            'chat_messages': self.get_chat_history(limit=50)
        }
        
        return state
    
    def is_game_over(self) -> bool:
        """Check if the game is over."""
        # Poker games continue until explicitly ended or all but one player leaves
        if len(self.players) < 2:
            return True
        
        # Check if hand is finished
        return self.engine.is_hand_over()
    
    def get_winners(self) -> List[str]:
        """
        Get the list of winning player wallet addresses.
        
        For poker, this returns the winners of the current hand.
        """
        if not self.engine.is_hand_over():
            return []
        
        # Get winners from showdown results
        showdown = self.engine.showdown()
        winners = showdown.get('winners', [])
        
        # Convert sids to wallet addresses
        winner_wallets = []
        for winner_sid in winners:
            for player in self.players:
                if player['sid'] == winner_sid:
                    winner_wallets.append(player['wallet_address'])
                    break
        
        return winner_wallets
    
    async def execute_default_action(self, sid: str) -> Dict:
        """
        Execute default action for timed-out poker player.
        
        In poker, the default action is:
        - Check if possible (no bet to call)
        - Fold otherwise
        
        Args:
            sid: Socket.IO session ID
            
        Returns:
            Dict with action result
        """
        # Try to check first (auto-check if no bet to call)
        result = self.engine.process_move(sid, 'check')
        
        if result.get('success'):
            return result
        
        # If check failed, fold
        return self.engine.process_move(sid, 'fold')
    
    async def save_checkpoint(self, event_type: str = "manual"):
        """
        Save game state checkpoint to MySQL.
        
        Called on:
        - Game start (hand start)
        - Phase change (flop, turn, river)
        - Hand end
        
        Args:
            event_type: Type of checkpoint event
        """
        # Save to Redis for hot state
        await self.save_state_to_redis()
        
        # TODO: Implement MySQL persistence via database module
        # This would save to GameSession.state_snapshot
        pass
    
    # ========================================================================
    # BACKWARD COMPATIBILITY METHODS (PokerEngine interface)
    # ========================================================================
    
    def start_hand(self) -> Dict:
        """
        Start a new hand (backward compatible with PokerEngine).
        
        Returns:
            Dict with success status
        """
        return self.engine.start_hand()
    
    def process_move(self, sid: str, action: str, amount: int = 0, 
                    chat_message: Optional[str] = None) -> Dict:
        """
        Process a player move (backward compatible with PokerEngine).
        
        Args:
            sid: Socket.IO session ID
            action: Action type (fold, check, call, raise)
            amount: Bet amount for raise
            chat_message: Optional chat/bluff message
            
        Returns:
            Dict with action result
        """
        # Update last action time for zombie tracking
        self.update_player_action_time(sid)
        
        # Reset consecutive timeouts on successful action
        self._reset_timeout_tracking(sid)
        
        # Delegate to engine
        return self.engine.process_move(sid, action, amount, chat_message)
    
    def can_start(self) -> bool:
        """Check if game can start (backward compatible)."""
        return len(self.players) >= self.MIN_PLAYERS and self.engine.can_start()
    
    def is_hand_over(self) -> bool:
        """Check if current hand is over (backward compatible)."""
        return self.engine.is_hand_over()
    
    def showdown(self) -> Dict:
        """Get showdown results (backward compatible)."""
        return self.engine.showdown()
