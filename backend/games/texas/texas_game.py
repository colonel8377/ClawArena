"""
Texas Hold'em Game Implementation.

This module implements TexasGame which extends BaseGame and uses
the poker_engine.PokerEngine for core game logic.
"""

from datetime import datetime
from typing import Dict, List, Optional, Any

from .texas_engine import TexasEngine
from ..base import BaseGame, GamePhase, check_chat_phase
from ...config import TEXAS_CHIP_TO_TOKEN_RATIO, TEXAS_DEFAULT_BUY_IN_CHIPS
from ...database.persistence_manager import persistence_manager
from ...database.redis_manager import redis_manager


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

        # 处理买入金额：可以传入chips或tokens，默认使用chips
        if 'buy_in_chips' in kwargs:
            buy_in_chips = kwargs['buy_in_chips']
            buy_in_tokens = buy_in_chips * TEXAS_CHIP_TO_TOKEN_RATIO
        elif 'buy_in_tokens' in kwargs:
            buy_in_tokens = kwargs['buy_in_tokens']
            buy_in_chips = buy_in_tokens / TEXAS_CHIP_TO_TOKEN_RATIO
        else:
            # 默认买入
            buy_in_chips = TEXAS_DEFAULT_BUY_IN_CHIPS
            buy_in_tokens = buy_in_chips * TEXAS_CHIP_TO_TOKEN_RATIO
        
        # Add to poker engine
        success = self.engine.add_player(
            sid=sid,
            wallet_address=wallet_address,
            nickname=nickname,
            buy_in=int(buy_in_chips)
        )
        if not success:
            return False

        # Keep wrapper state in sync only after engine accepts the player.
        player = {
            'sid': sid,
            'wallet_address': wallet_address,
            'nickname': nickname,
            'buy_in_chips': int(buy_in_chips),
            'buy_in_tokens': float(buy_in_tokens)
        }
        self.players.append(player)

        self.channel.add_participant(
            player_id=sid,
            wallet_address=wallet_address,
            nickname=nickname
        )
        
        return True
    
    def remove_player(self, sid: str) -> bool:
        """Remove a player from the game."""
        removed = self.engine.remove_player(sid)
        if not removed:
            return False

        # Engine keeps players during active hands (marks as folded), so only
        # remove from wrapper state if engine fully removed the seat.
        if sid not in self.engine.players:
            self.players = [p for p in self.players if p['sid'] != sid]
            self.channel.remove_participant(sid)

        return True
    
    def can_start(self) -> bool:
        """Check if game can start."""
        return len(self.players) >= self.MIN_PLAYERS and self.engine.can_start()
    
    def start_game(self) -> bool:
        """Start the game or deal the next hand when a hand already finished."""
        if not self.can_start():
            return False

        # Table-level lifecycle: GamePhase.IN_PROGRESS means the table is alive,
        # not that a hand is currently actionable. Allow explicit next-hand starts
        # after a hand reaches SHOWDOWN/FINISHED/WAITING.
        if self.phase == GamePhase.WAITING:
            pass
        elif self.phase == GamePhase.IN_PROGRESS:
            if self.engine.phase not in {
                self.engine.phase.SHOWDOWN,
                self.engine.phase.FINISHED,
                self.engine.phase.WAITING,
            }:
                return False
        else:
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
        if action == 'chat':
            # Reuse shared phase gate to keep wrapper and engine chat rules consistent.
            gate = check_chat_phase(self.engine.phase, self.engine.CHAT_ALLOWED_PHASES)
            if gate:
                return gate

            # Handle chat through BaseGame
            message = kwargs.get('message', '')
            result = {'success': True, 'chat': self.add_chat_message(sid, message)}
            self.update_player_action_time(sid)
            self._reset_timeout_tracking(sid)
            return result
        
        # Delegate to poker engine, including optional action-attached chat.
        chat_message = kwargs.get('message')
        if action == 'raise':
            amount = kwargs.get('amount', self.big_blind)
            result = self.engine.process_move(
                sid,
                action,
                amount=amount,
                chat_message=chat_message
            )
        else:
            result = self.engine.process_move(sid, action, chat_message=chat_message)

        if result.get('success'):
            self.update_player_action_time(sid)
            self._reset_timeout_tracking(sid)

        return result
    
    def get_game_state(
        self,
        sid: Optional[str] = None,
        for_spectator: bool = False,
        reveal_all: bool = False
    ) -> Dict:
        """
        Get the current game state.
        
        For poker, this includes player-specific hole cards when sid is provided.
        """
        # Get base state from engine
        engine_state = self.engine.get_game_state(
            sid,
            for_spectator=for_spectator,
            reveal_all=reveal_all
        )
        
        # Add chat history from BaseGame
        state = {
            **engine_state,
            'chat_messages': self.get_chat_history(limit=50)
        }
        
        return state
    
    def is_game_over(self) -> bool:
        """Check if the game is over."""
        # A finished hand is not a finished table. The table only ends when it
        # can no longer start a hand (fewer than 2 chip-positive players).
        return not self.engine.can_start()
    
    def get_winners(self) -> List[str]:
        """
        Get the list of winning player wallet addresses.
        
        For poker, this returns the winners of the current hand.
        """
        if not self.engine.is_hand_over():
            return []
        
        winners = self.engine.last_hand_winners
        
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
        # Always write hot state first so reconnect/recovery remains instant.
        state = self.get_core_state()
        await self.save_state_to_redis(state)

        # Cold storage is throttled in PersistenceManager for non-critical events.
        force_mysql = event_type in {
            'hand_start',
            'phase_change',
            'hand_end',
            'showdown',
            'shutdown',
        }
        await persistence_manager.save_poker_checkpoint(
            game_id=self.game_id,
            game_state=state,
            event_type=event_type,
            force_mysql=force_mysql,
        )

    async def save_state_to_redis(self, state: Optional[Dict] = None):
        """Persist poker core state through the unified RedisManager namespace."""
        payload = state if state is not None else self.get_core_state()
        await redis_manager.save_game_core(self.game_id, payload, game_type=self.game_type)

    def get_core_state(self) -> Dict[str, Any]:
        """Return restart-safe table state for hot storage snapshots."""
        return self.to_dict()

    def get_game_snapshot(self, sid: Optional[str] = None) -> Dict[str, Any]:
        """Build reconnect snapshot payload for poker clients."""
        state = self.get_game_state(sid)
        return {
            'game_id': self.game_id,
            'game_type': self.game_type,
            **state,
            'turn_time_remaining': self.engine.get_turn_time_remaining(),
            'timestamp': datetime.utcnow().isoformat(),
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize full table + engine state for recovery."""
        return {
            'game_id': self.game_id,
            'game_type': self.game_type,
            'phase': self.phase.value,
            'small_blind': self.small_blind,
            'big_blind': self.big_blind,
            'players': list(self.players),
            'last_action_time': {
                sid: ts.isoformat() for sid, ts in self.last_action_time.items()
            },
            'engine': self.engine.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TexasGame':
        """Restore table and engine state from Redis snapshot."""
        game = cls(
            game_id=data.get('game_id', 'restored_table'),
            small_blind=int(data.get('small_blind', 25)),
            big_blind=int(data.get('big_blind', 50)),
        )

        phase_value = data.get('phase', GamePhase.WAITING.value)
        try:
            game.phase = GamePhase(phase_value)
        except ValueError:
            game.phase = GamePhase.WAITING

        engine_data = data.get('engine')
        if isinstance(engine_data, dict):
            game.engine = TexasEngine.from_dict(engine_data)

        wrapper_players = data.get('players', [])
        game.players = []
        if isinstance(wrapper_players, list) and wrapper_players:
            for player in wrapper_players:
                if not isinstance(player, dict):
                    continue
                game.players.append({
                    'sid': player.get('sid'),
                    'wallet_address': player.get('wallet_address', ''),
                    'nickname': player.get('nickname', 'Player'),
                    'buy_in_chips': int(player.get('buy_in_chips', 0) or 0),
                    'buy_in_tokens': float(player.get('buy_in_tokens', 0) or 0),
                })
        else:
            for sid in game.engine.player_order:
                player = game.engine.players.get(sid)
                if not player:
                    continue
                game.players.append({
                    'sid': sid,
                    'wallet_address': player.wallet_address,
                    'nickname': player.nickname,
                    'buy_in_chips': int(player.chips),
                    'buy_in_tokens': float(player.chips * TEXAS_CHIP_TO_TOKEN_RATIO),
                })

        for player in game.players:
            sid = player.get('sid')
            if sid:
                game.channel.add_participant(
                    player_id=sid,
                    wallet_address=player.get('wallet_address', ''),
                    nickname=player.get('nickname', 'Player'),
                )

        game.last_action_time = {}
        for sid, ts in (data.get('last_action_time') or {}).items():
            try:
                game.last_action_time[sid] = datetime.fromisoformat(ts)
            except (TypeError, ValueError):
                continue

        # Keep table lifecycle aligned with restored hand lifecycle.
        if game.engine.phase.value in {'pre_flop', 'flop', 'turn', 'river', 'showdown'}:
            game.phase = GamePhase.IN_PROGRESS

        return game
    
