"""
Poker Engine for OpenClaw Poker Arena.

This module implements the No-Limit Texas Hold'em game engine:
- State Machine: Pre-flop -> Flop -> Turn -> River -> Showdown
- Side Pots: Handles all-in scenarios with main pot + side pots
- Betting Logic: Validates min-raise, check, call, fold
- Hand Evaluation: Uses treys library for efficient hand ranking
- Turn Timer: 20 seconds with auto-check/fold on timeout

The engine is designed for AI Agent gameplay with integrated chat/bluff messaging.
"""

import asyncio
import random
import secrets
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Awaitable

from treys import Card, Evaluator, Deck

from ..base import check_chat_phase
from .utils import censor_card_info
from ...config.texas_config import (
    TEXAS_DEFAULT_BIG_BLIND,
    TEXAS_DEFAULT_SMALL_BLIND,
    TEXAS_MAX_PLAYERS,
    TEXAS_MIN_PLAYERS,
    TEXAS_TURN_TIMEOUT_SECONDS,
)
from .roles import PlayerAction, PlayerStatus


# ============================================================================
# CONSTANTS
# ============================================================================

# Timeout configuration
TURN_TIMEOUT_SECONDS = TEXAS_TURN_TIMEOUT_SECONDS
DEFAULT_SMALL_BLIND = TEXAS_DEFAULT_SMALL_BLIND
DEFAULT_BIG_BLIND = TEXAS_DEFAULT_BIG_BLIND
MIN_PLAYERS = TEXAS_MIN_PLAYERS
MAX_PLAYERS = TEXAS_MAX_PLAYERS

# Game Rules Configuration
# Strategy for handling dead pots (excess bets from folded players with no eligible callers).
# 'MAIN_POT': Merge dead money into the Main Pot (standard rule, benefits the hand winner).
# 'BURN': Remove dead money from the game (deflationary).
# 'REFUND': Refund to the bettor (non-standard).
DEAD_POT_MERGE_STRATEGY = 'MAIN_POT'


# ============================================================================
# ENUMS
# ============================================================================

class PokerPhase(Enum):
    """Texas Hold'em game phases."""
    WAITING = "waiting"
    PRE_FLOP = "pre_flop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"
    FINISHED = "finished"


# ============================================================================
# DATA CLASSES
# ============================================================================

@dataclass
class PokerPlayer:
    """
    Represents a player in the poker game.
    
    Tracks chip stack, hole cards, and betting state.
    """
    sid: str
    wallet_address: str
    nickname: str
    chips: int = 1000
    hole_cards: List[int] = field(default_factory=list)
    status: PlayerStatus = PlayerStatus.ACTIVE
    current_bet: int = 0  # Current bet in this betting round
    total_bet_this_round: int = 0  # Total bet in this betting round (for round tracking)
    total_bet_this_hand: int = 0  # Total bet across entire hand (for side pot calculation)
    has_acted: bool = False
    last_action: Optional[str] = None
    last_action_time: Optional[datetime] = None
    consecutive_timeouts: int = 0
    
    def is_active(self) -> bool:
        """Check if player is still active in the hand."""
        return self.status in (PlayerStatus.ACTIVE, PlayerStatus.ALL_IN)
    
    def can_act(self) -> bool:
        """Check if player can take an action."""
        return self.status == PlayerStatus.ACTIVE and self.chips > 0
    
    def reset_for_new_hand(self):
        """Reset player state for a new hand."""
        self.hole_cards = []
        self.status = PlayerStatus.ACTIVE if self.chips > 0 else PlayerStatus.SITTING_OUT
        self.current_bet = 0
        self.total_bet_this_round = 0
        self.total_bet_this_hand = 0  # Reset for new hand
        self.has_acted = False
        self.last_action = None


@dataclass
class Pot:
    """
    Represents a pot (main pot or side pot).
    
    For side pot calculations in all-in scenarios.
    """
    amount: int = 0
    eligible_players: List[str] = field(default_factory=list)  # List of player sids
    
    def add(self, amount: int, player_sid: str):
        """Add chips to the pot."""
        self.amount += amount
        if player_sid not in self.eligible_players:
            self.eligible_players.append(player_sid)


@dataclass
class ChatMessage:
    """Represents a chat/bluff message from a player."""
    player_sid: str
    player_nickname: str
    message: str
    timestamp: str = field(default_factory=lambda: datetime.utcnow().isoformat())
    action: Optional[str] = None  # The action that accompanied this message


# ============================================================================
# POKER ENGINE CLASS
# ============================================================================

class TexasEngine:
    """
    No-Limit Texas Hold'em game engine.
    
    Features:
    - State machine for game phases
    - Side pot calculation for all-in scenarios
    - Min-raise validation
    - Hand evaluation using treys
    - 20-second turn timer with auto-check/fold
    - Chat/bluff message handling
    """
    
    def __init__(
        self,
        game_id: str,
        small_blind: int = DEFAULT_SMALL_BLIND,
        big_blind: int = DEFAULT_BIG_BLIND
    ):
        """
        Initialize the poker engine.
        
        Args:
            game_id: Unique identifier for this game
            small_blind: Small blind amount
            big_blind: Big blind amount
        """
        self.game_id = game_id
        self.small_blind = small_blind
        self.big_blind = big_blind
        self.min_raise = big_blind  # Minimum raise amount
        
        # Game state
        self.phase = PokerPhase.WAITING
        self.players: Dict[str, PokerPlayer] = {}
        self.player_order: List[str] = []  # Sids in seat order
        
        # Dealer/blind positions - stored as SIDs for consistency
        self.dealer_sid: Optional[str] = None
        self.small_blind_sid: Optional[str] = None
        self.big_blind_sid: Optional[str] = None
        self.current_player_sid: Optional[str] = None
        
        # Legacy index support (for backward compatibility)
        self.dealer_index = 0
        self.small_blind_index = 0
        self.big_blind_index = 0
        self.current_player_index = 0
        
        # Betting state
        self.current_bet = 0  # Current bet to match
        self.last_raise_amount = big_blind  # Track last raise for min-raise calculation
        self.pots: List[Pot] = [Pot()]  # Main pot + side pots
        
        # Community cards
        self.community_cards: List[int] = []
        
        # Deck
        self._deck: List[int] = []
        
        # Hand evaluator
        self._evaluator = Evaluator() if Evaluator else None
        
        # Chat history
        self.chat_history: List[ChatMessage] = []
        
        # Timeout handling
        self._timeout_task: Optional[asyncio.Task] = None
        self._on_timeout: Optional[Callable[[str], Awaitable[None]]] = None
        
        # Broadcast callback
        self._broadcast_callback: Optional[Callable[[str, Any, Optional[str]], Awaitable[None]]] = None
        
        # Hand number
        self.hand_number = 0
        self.turn_started_at: Optional[datetime] = None

        # Winners of the most recently completed hand (SIDs)
        self.last_hand_winners: List[str] = []
    
    # ========================================================================
    # PLAYER MANAGEMENT
    # ========================================================================
    
    def add_player(
        self,
        sid: str,
        wallet_address: str,
        nickname: str,
        buy_in: int = 1000
    ) -> bool:
        """
        Add a player to the table.
        
        Args:
            sid: Socket.IO session ID
            wallet_address: Player's wallet address
            nickname: Player's display name
            buy_in: Initial chip stack
            
        Returns:
            True if player was added successfully
        """
        if len(self.players) >= MAX_PLAYERS:
            return False
        
        if sid in self.players:
            return False
        
        player = PokerPlayer(
            sid=sid,
            wallet_address=wallet_address,
            nickname=nickname,
            chips=buy_in
        )
        
        # If hand is in progress, set player as SITTING_OUT
        # They will become ACTIVE at the start of the next hand
        if self.phase not in (PokerPhase.WAITING, PokerPhase.FINISHED):
            player.status = PlayerStatus.SITTING_OUT
        
        self.players[sid] = player
        self.player_order.append(sid)
        
        return True
    
    def remove_player(self, sid: str) -> bool:
        """
        Remove a player from the table.
        
        Args:
            sid: Socket.IO session ID
            
        Returns:
            True if player was removed successfully
        """
        if sid not in self.players:
            return False
        
        # If game is in progress, mark as folded instead of removing
        if self.phase not in (PokerPhase.WAITING, PokerPhase.FINISHED):
            self.players[sid].status = PlayerStatus.FOLDED
            return True
        
        del self.players[sid]
        self.player_order.remove(sid)
        return True

    def update_player_sid(self, old_sid: str, new_sid: str) -> bool:
        """Update player SID for reconnection without losing table seat/state."""
        if old_sid not in self.players:
            return False
        if old_sid == new_sid:
            return True
        if new_sid in self.players:
            return False

        player = self.players.pop(old_sid)
        player.sid = new_sid
        self.players[new_sid] = player

        self.player_order = [new_sid if sid == old_sid else sid for sid in self.player_order]
        self.last_hand_winners = [new_sid if sid == old_sid else sid for sid in self.last_hand_winners]

        if self.dealer_sid == old_sid:
            self.dealer_sid = new_sid
        if self.small_blind_sid == old_sid:
            self.small_blind_sid = new_sid
        if self.big_blind_sid == old_sid:
            self.big_blind_sid = new_sid
        if self.current_player_sid == old_sid:
            self.current_player_sid = new_sid

        for pot in self.pots:
            pot.eligible_players = [new_sid if sid == old_sid else sid for sid in pot.eligible_players]

        return True
    
    def can_start(self) -> bool:
        """Check if the game can start."""
        active_players = [p for p in self.players.values() if p.chips > 0]
        return len(active_players) >= MIN_PLAYERS
    
    # ========================================================================
    # HAND MANAGEMENT
    # ========================================================================
    
    def start_hand(self) -> Dict[str, Any]:
        """
        Start a new hand.
        
        Returns:
            Dict with hand start information including player hole cards
        """
        if not self.can_start():
            return {'success': False, 'error': 'Not enough players'}
        
        self.hand_number += 1
        self.last_hand_winners = []
        
        # Reset players
        for player in self.players.values():
            player.reset_for_new_hand()
        
        # Reset game state
        self.phase = PokerPhase.PRE_FLOP
        self.community_cards = []
        self.pots = [Pot()]
        self.current_bet = 0
        self.last_raise_amount = self.big_blind
        self.turn_started_at = None
        
        # Move dealer button
        self._rotate_dealer()
        
        # Create and shuffle deck
        self._create_deck()
        # Post blinds
        self._post_blinds()

        # Deal hole cards after blind positions are established so the
        # pre-flop deal order starts correctly from small blind.
        self._deal_hole_cards()
        
        # Set first player to act (after big blind)
        self._set_first_to_act()
        
        # Generate hole cards info for each player
        hole_cards_info = {}
        for sid, player in self.players.items():
            hole_cards_info[sid] = self._cards_to_strings(player.hole_cards)
        
        return {
            'success': True,
            'hand_number': self.hand_number,
            'dealer': self.dealer_sid,
            'small_blind': self.small_blind_sid,
            'big_blind': self.big_blind_sid,
            'current_player': self.current_player_sid,
            'hole_cards': hole_cards_info,
            'pot': self.get_total_pot()
        }
    
    def _create_deck(self):
        """Create and shuffle a new deck."""
        if Deck:
            deck = Deck()
            # Use SystemRandom for secure shuffling
            self._deck = deck.draw(52)
            secrets.SystemRandom().shuffle(self._deck)
        else:
            # Fallback: create simple deck representation
            self._deck = list(range(52))
            secrets.SystemRandom().shuffle(self._deck)
    
    def _deal_hole_cards(self):
        """
        Deal two hole cards to each active player.
        
        Deals in proper order: starting from small blind position,
        one card to each player, then second card to each player.
        """
        active_sids = [sid for sid in self.player_order 
                       if self.players[sid].status == PlayerStatus.ACTIVE]
        
        if not active_sids:
            return
        
        # Reorder to start dealing from small blind position
        sb_pos = self.small_blind_index % len(active_sids)
        deal_order = active_sids[sb_pos:] + active_sids[:sb_pos]
        
        # Deal first card to each player, then second card
        for _ in range(2):
            for sid in deal_order:
                if self._deck:
                    card = self._deck.pop()
                    self.players[sid].hole_cards.append(card)
    
    def _post_blinds(self):
        """Post small and big blinds."""
        active_sids = [sid for sid in self.player_order 
                       if self.players[sid].status == PlayerStatus.ACTIVE]
        
        if len(active_sids) < MIN_PLAYERS:
            return
        
        # Find dealer position in player_order
        if self.dealer_sid not in self.player_order:
            return
        dealer_order_pos = self.player_order.index(self.dealer_sid)
        
        # Find next active players after dealer
        def find_next_active(start_pos, skip=1):
            """Find the nth active player after start position."""
            count = 0
            for i in range(1, len(self.player_order) + 1):
                pos = (start_pos + i) % len(self.player_order)
                sid = self.player_order[pos]
                if sid in active_sids:
                    count += 1
                    if count == skip:
                        return sid
            return None
        
        if len(active_sids) == 2:
            # Heads-up: dealer is small blind, other player is big blind
            self.small_blind_sid = self.dealer_sid
            self.big_blind_sid = find_next_active(dealer_order_pos, 1)
        else:
            # Normal: SB is after dealer, BB is after SB
            self.small_blind_sid = find_next_active(dealer_order_pos, 1)
            self.big_blind_sid = find_next_active(dealer_order_pos, 2)
        
        # Update legacy indices
        if self.small_blind_sid in active_sids:
            self.small_blind_index = active_sids.index(self.small_blind_sid)
        if self.big_blind_sid in active_sids:
            self.big_blind_index = active_sids.index(self.big_blind_sid)
        
        # Post small blind
        if self.small_blind_sid:
            sb_amount = min(self.small_blind, self.players[self.small_blind_sid].chips)
            self._place_bet(self.small_blind_sid, sb_amount)
            
            # Mark as all-in if posting blind uses all chips
            if self.players[self.small_blind_sid].chips == 0:
                self.players[self.small_blind_sid].status = PlayerStatus.ALL_IN
        
        # Post big blind
        if self.big_blind_sid:
            bb_amount = min(self.big_blind, self.players[self.big_blind_sid].chips)
            self._place_bet(self.big_blind_sid, bb_amount)
            
            # Mark as all-in if posting blind uses all chips
            if self.players[self.big_blind_sid].chips == 0:
                self.players[self.big_blind_sid].status = PlayerStatus.ALL_IN
            
            self.current_bet = bb_amount
    
    def _rotate_dealer(self):
        """Move dealer button to next active player."""
        if not self.player_order:
            return
        
        # Find active players (those with chips who can play)
        active_sids = [sid for sid in self.player_order 
                       if self.players[sid].chips > 0]
        
        if len(active_sids) < MIN_PLAYERS:
            return
        
        # Find current dealer position in player_order
        if self.dealer_sid and self.dealer_sid in self.player_order:
            current_pos = self.player_order.index(self.dealer_sid)
        else:
            current_pos = -1
        
        # Find next active player after current dealer
        for i in range(1, len(self.player_order) + 1):
            next_pos = (current_pos + i) % len(self.player_order)
            next_sid = self.player_order[next_pos]
            if next_sid in active_sids:
                self.dealer_sid = next_sid
                self.dealer_index = active_sids.index(next_sid)
                return
    
    def _set_first_to_act(self):
        """Set the first player to act after dealing (pre-flop)."""
        active_sids = [sid for sid in self.player_order 
                       if self.players[sid].can_act()]
        
        if not active_sids:
            return
        
        # Find big blind position in player_order
        if self.big_blind_sid not in self.player_order:
            return
        bb_order_pos = self.player_order.index(self.big_blind_sid)
        
        if len(active_sids) == 2:
            # Heads-up: small blind (dealer) acts first pre-flop
            self.current_player_sid = self.small_blind_sid
        else:
            # UTG acts first (player after big blind who can act)
            for i in range(1, len(self.player_order) + 1):
                pos = (bb_order_pos + i) % len(self.player_order)
                sid = self.player_order[pos]
                if self.players[sid].can_act():
                    self.current_player_sid = sid
                    break
        
        # Update legacy index
        if self.current_player_sid in active_sids:
            self.current_player_index = active_sids.index(self.current_player_sid)
        if self.current_player_sid:
            self.turn_started_at = datetime.utcnow()
    
    # ========================================================================
    # BETTING ACTIONS
    # ========================================================================
    
    # Phases where public chat is allowed (between hands, showdown, finished).
    # During active hand phases (PRE_FLOP through RIVER), chat is blocked to
    # prevent agents from leaking hole cards in public chat.
    CHAT_ALLOWED_PHASES = {PokerPhase.WAITING, PokerPhase.SHOWDOWN, PokerPhase.FINISHED}

    def process_move(
        self,
        sid: str,
        action: str,
        amount: int = 0,
        chat_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a player's move with optional chat/bluff message.
        
        Chat is permitted during all phases, but card information is censored
        during active hand phases (PRE_FLOP through RIVER) to prevent cheating.
        """
        player = self.players.get(sid)
        if not player:
            return {'success': False, 'error': 'Player not found'}

        chat_blocked = False
        chat_payload: Optional[ChatMessage] = None

        # Enforce chat limits (length and spam control could be added here)
        if chat_message and len(chat_message) > 200:
            chat_message = chat_message[:200]  # Truncate overly long messages

        # Block chat during restricted phases to prevent info leakage.
        if chat_message and check_chat_phase(self.phase, self.CHAT_ALLOWED_PHASES):
            chat_blocked = True
            chat_message = None

        # Process chat message (only if allowed by phase)
        if chat_message:
            chat_payload = ChatMessage(
                player_sid=sid,
                player_nickname=player.nickname,
                message=chat_message,
                action=action
            )
            self.chat_history.append(chat_payload)

        # Validate it's this player's turn for gameplay actions.
        if not self._is_player_turn(sid):
            result = {'success': False, 'error': 'Not your turn'}
            if chat_payload:
                result['chat'] = chat_payload.message
                result['player_nickname'] = player.nickname
            if chat_blocked:
                result['chat_blocked'] = True
            return result

        if not player.can_act():
            result = {'success': False, 'error': 'Player cannot act'}
            if chat_payload:
                result['chat'] = chat_payload.message
                result['player_nickname'] = player.nickname
            if chat_blocked:
                result['chat_blocked'] = True
            return result
        
        # Validate and execute action
        result = self._execute_action(sid, action, amount)
        
        if result['success']:
            player.has_acted = True
            player.last_action = action
            player.last_action_time = datetime.utcnow()
            player.consecutive_timeouts = 0
            
            # Add chat to result for broadcasting
            if chat_payload:
                result['chat'] = chat_payload.message
            result['player_nickname'] = player.nickname
            
            # Notify caller that chat was stripped due to phase restriction
            if chat_blocked:
                result['chat_blocked'] = True
            
            # Check if hand is over (everyone else folded)
            if result.get('hand_over'):
                # Hand ended due to fold - no need to advance phase
                return result
            
            # Check if betting round is complete
            if self._is_betting_round_complete():
                result['round_complete'] = True
                result['advance_phase'] = True
            else:
                # Move to next player
                self._advance_to_next_player()
                result['next_player'] = self.current_player_sid
        
        return result
    
    def _execute_action(self, sid: str, action: str, amount: int) -> Dict[str, Any]:
        """Execute the player's action."""
        player = self.players[sid]
        
        if action == PlayerAction.FOLD.value:
            return self._handle_fold(sid)
        elif action == PlayerAction.CHECK.value:
            return self._handle_check(sid)
        elif action == PlayerAction.CALL.value:
            return self._handle_call(sid)
        elif action == PlayerAction.RAISE.value:
            return self._handle_raise(sid, amount)
        elif action == PlayerAction.ALL_IN.value:
            return self._handle_all_in(sid)
        else:
            return {'success': False, 'error': f'Unknown action: {action}'}

    def _handle_all_in(self, sid: str) -> Dict[str, Any]:
        """
        Handle explicit all-in action.

        Behaves like:
        - all-in call when stack is not enough to fully call
        - all-in raise otherwise
        """
        player = self.players[sid]

        if player.chips <= 0:
            return {'success': False, 'error': 'No chips left'}

        to_call = max(0, self.current_bet - player.current_bet)

        # All-in call (short call allowed).
        if player.chips <= to_call:
            amount = player.chips
            self._place_bet(sid, amount)
            player.status = PlayerStatus.ALL_IN
            return {
                'success': True,
                'action': 'all_in',
                'amount': amount,
                'player_sid': sid
            }

        # All-in raise to total invested amount.
        raise_to = player.current_bet + player.chips
        return self._handle_raise(sid, raise_to)
    
    def _handle_fold(self, sid: str) -> Dict[str, Any]:
        """Handle fold action."""
        player = self.players[sid]
        player.status = PlayerStatus.FOLDED
        
        result = {
            'success': True,
            'action': 'fold',
            'player_sid': sid
        }
        
        # Check if only one player remains - hand ends immediately
        active_players = [p for p in self.players.values() if p.is_active()]
        if len(active_players) == 1:
            winner = active_players[0]
            total_pot = self.get_total_pot()
            winner.chips += total_pot
            self.phase = PokerPhase.FINISHED
            self.last_hand_winners = [winner.sid]
            
            result['hand_over'] = True
            result['winner'] = {
                'sid': winner.sid,
                'nickname': winner.nickname,
                'amount': total_pot
            }
        
        return result
    
    def _handle_check(self, sid: str) -> Dict[str, Any]:
        """Handle check action."""
        player = self.players[sid]
        
        # Can only check if no bet to match
        if player.current_bet < self.current_bet:
            return {
                'success': False,
                'error': 'Cannot check, must call or raise'
            }
        
        return {
            'success': True,
            'action': 'check',
            'player_sid': sid
        }
    
    def _handle_call(self, sid: str) -> Dict[str, Any]:
        """Handle call action."""
        player = self.players[sid]
        
        call_amount = self.current_bet - player.current_bet
        
        if call_amount <= 0:
            return {
                'success': False,
                'error': 'Nothing to call, use check'
            }
        
        # Check if this puts player all-in
        if call_amount >= player.chips:
            call_amount = player.chips
            player.status = PlayerStatus.ALL_IN
        
        self._place_bet(sid, call_amount)
        
        return {
            'success': True,
            'action': 'call' if player.status != PlayerStatus.ALL_IN else 'all_in',
            'amount': call_amount,
            'player_sid': sid
        }
    
    def _handle_raise(self, sid: str, amount: int) -> Dict[str, Any]:
        """
        Handle raise action.
        
        Args:
            amount: The TOTAL bet amount (not the raise amount)
        """
        player = self.players[sid]
        
        # Calculate raise amount
        raise_to = amount
        current_investment = player.current_bet
        additional_chips = raise_to - current_investment
        
        # Validate minimum raise
        min_raise_to = self.current_bet + self.last_raise_amount
        
        if raise_to < min_raise_to and additional_chips < player.chips:
            # Allow smaller raise if all-in
            return {
                'success': False,
                'error': f'Minimum raise is to {min_raise_to}'
            }
        
        if additional_chips > player.chips:
            return {
                'success': False,
                'error': 'Not enough chips'
            }
        
        # Check if this puts player all-in
        if additional_chips == player.chips:
            player.status = PlayerStatus.ALL_IN
        
        # Calculate if this is a full raise (meets minimum raise requirement)
        raise_amount = raise_to - self.current_bet
        is_full_raise = raise_amount >= self.last_raise_amount
        
        # Update last raise amount only for full raises
        if is_full_raise and raise_amount > 0:
            self.last_raise_amount = raise_amount
        
        # Place the bet
        self._place_bet(sid, additional_chips)
        self.current_bet = raise_to
        
        # Reset has_acted for other players only if this is a full raise
        # Incomplete raises (all-in < min raise) don't reopen betting
        if is_full_raise:
            for other_sid, other_player in self.players.items():
                if other_sid != sid and other_player.can_act():
                    other_player.has_acted = False
        
        return {
            'success': True,
            'action': 'raise' if player.status != PlayerStatus.ALL_IN else 'all_in',
            'amount': raise_to,
            'raise_amount': raise_amount,
            'player_sid': sid
        }
    
    def _place_bet(self, sid: str, amount: int):
        """Place a bet and add chips to the pot."""
        player = self.players[sid]
        player.chips -= amount
        player.current_bet += amount
        player.total_bet_this_round += amount
        player.total_bet_this_hand += amount  # Track total for side pot calculation
        
        # Add to main pot (side pots handled at showdown)
        self.pots[0].add(amount, sid)
    
    # ========================================================================
    # PHASE MANAGEMENT
    # ========================================================================
    
    def advance_phase(self) -> Dict[str, Any]:
        """
        Advance to the next phase and deal community cards.
        
        If all players are all-in, automatically runs out the board
        (deals all remaining community cards without betting rounds).
        
        Returns:
            Dict with phase change information
        """
        # Reset betting state for new round
        for player in self.players.values():
            player.current_bet = 0
            player.has_acted = False
        
        self.current_bet = 0
        self.last_raise_amount = self.big_blind
        
        # Check if we should run out the board (all players all-in or only one left)
        run_out = self._should_run_out_board()
        
        if self.phase == PokerPhase.PRE_FLOP:
            result = self._deal_flop()
            if run_out and result.get('success'):
                # Continue dealing without betting
                result['run_out'] = True
                result['turn'] = self._deal_turn_card_only()
                result['river'] = self._deal_river_card_only()
                result['community_cards'] = self._cards_to_strings(self.community_cards)
                showdown_result = self._start_showdown()
                # Merge results so we don't lose the run_out info
                showdown_result.update({
                    'run_out': True,
                    'flop': self._cards_to_strings(self.community_cards[:3]),
                    'turn': result['turn'],
                    'river': result['river']
                })
                return showdown_result
            return result
        elif self.phase == PokerPhase.FLOP:
            result = self._deal_turn()
            if run_out and result.get('success'):
                result['run_out'] = True
                result['river'] = self._deal_river_card_only()
                result['community_cards'] = self._cards_to_strings(self.community_cards)
                showdown_result = self._start_showdown()
                showdown_result.update({
                    'run_out': True,
                    'turn': self._cards_to_strings(self.community_cards[3:4])[0] if len(self.community_cards) > 3 else None,
                    'river': result['river']
                })
                return showdown_result
            return result
        elif self.phase == PokerPhase.TURN:
            result = self._deal_river()
            if run_out and result.get('success'):
                result['run_out'] = True
                showdown_result = self._start_showdown()
                showdown_result.update({'run_out': True})
                return showdown_result
            return result
        elif self.phase == PokerPhase.RIVER:
            return self._start_showdown()
        else:
            return {'success': False, 'error': 'Cannot advance from current phase'}
    
    def _deal_turn_card_only(self) -> str:
        """Deal turn card without changing phase (for run-out)."""
        if self._deck:
            self._deck.pop()  # Burn
            if self._deck:
                card = self._deck.pop()
                self.community_cards.append(card)
                return self._cards_to_strings([card])[0]
        return ""
    
    def _deal_river_card_only(self) -> str:
        """Deal river card without changing phase (for run-out)."""
        if self._deck:
            self._deck.pop()  # Burn
            if self._deck:
                card = self._deck.pop()
                self.community_cards.append(card)
                return self._cards_to_strings([card])[0]
        return ""
    
    def _deal_flop(self) -> Dict[str, Any]:
        """Deal the flop (3 community cards)."""
        self.phase = PokerPhase.FLOP
        
        # Burn and deal 3
        if self._deck:
            self._deck.pop()  # Burn card
            for _ in range(3):
                if self._deck:
                    self.community_cards.append(self._deck.pop())
        
        self._set_post_flop_first_to_act()
        
        return {
            'success': True,
            'phase': 'flop',
            'community_cards': self._cards_to_strings(self.community_cards),
            'current_player': self.current_player_sid
        }
    
    def _deal_turn(self) -> Dict[str, Any]:
        """Deal the turn (4th community card)."""
        self.phase = PokerPhase.TURN
        
        # Burn and deal 1
        if self._deck:
            self._deck.pop()  # Burn card
            if self._deck:
                self.community_cards.append(self._deck.pop())
        
        self._set_post_flop_first_to_act()
        
        return {
            'success': True,
            'phase': 'turn',
            'community_cards': self._cards_to_strings(self.community_cards),
            'current_player': self.current_player_sid
        }
    
    def _deal_river(self) -> Dict[str, Any]:
        """Deal the river (5th community card)."""
        self.phase = PokerPhase.RIVER
        
        # Burn and deal 1
        if self._deck:
            self._deck.pop()  # Burn card
            if self._deck:
                self.community_cards.append(self._deck.pop())
        
        self._set_post_flop_first_to_act()
        
        return {
            'success': True,
            'phase': 'river',
            'community_cards': self._cards_to_strings(self.community_cards),
            'current_player': self.current_player_sid
        }
    
    def _set_post_flop_first_to_act(self):
        """Set first player to act post-flop (first active player after dealer)."""
        active_sids = [sid for sid in self.player_order 
                       if self.players[sid].can_act()]
        
        if not active_sids:
            return
        
        # Find dealer position in player_order
        if self.dealer_sid not in self.player_order:
            # Fallback to first active
            self.current_player_sid = active_sids[0]
            self.current_player_index = 0
            return
        
        dealer_order_pos = self.player_order.index(self.dealer_sid)
        
        # Find first player who can act after dealer
        for i in range(1, len(self.player_order) + 1):
            pos = (dealer_order_pos + i) % len(self.player_order)
            sid = self.player_order[pos]
            if self.players[sid].can_act():
                self.current_player_sid = sid
                self.current_player_index = active_sids.index(sid)
                self.turn_started_at = datetime.utcnow()
                return
    
    # ========================================================================
    # SHOWDOWN
    # ========================================================================
    
    def _start_showdown(self) -> Dict[str, Any]:
        """
        Start the showdown phase.
        
        Evaluates hands and determines winners.
        
        Returns:
            Dict with showdown results including all hole cards revealed
        """
        self.phase = PokerPhase.SHOWDOWN
        
        # Calculate side pots first
        self._calculate_side_pots()
        
        # Get all players who haven't folded
        showdown_players = [
            sid for sid in self.player_order
            if self.players[sid].is_active()
        ]
        
        if len(showdown_players) == 0:
            return {'success': False, 'error': 'No players at showdown'}
        
        if len(showdown_players) == 1:
            # Everyone else folded
            winner_sid = showdown_players[0]
            total_pot = self.get_total_pot()
            self.players[winner_sid].chips += total_pot
            
            return {
                'success': True,
                'phase': 'showdown',
                'winners': [{
                    'sid': winner_sid,
                    'nickname': self.players[winner_sid].nickname,
                    'amount': total_pot,
                    'hand': None
                }],
                'player_hands': self.get_all_hole_cards()
            }
        
        # Evaluate hands and determine winners for each pot
        results = self._evaluate_and_distribute_pots(showdown_players)
        self.last_hand_winners = list(dict.fromkeys(w['sid'] for w in results['winners']))
        
        return {
            'success': True,
            'phase': 'showdown',
            'winners': results['winners'],
            'player_hands': self.get_all_hole_cards(),
            'community_cards': self._cards_to_strings(self.community_cards)
        }
    
    def _calculate_side_pots(self):
        """
        Calculate side pots for all-in scenarios.
        
        Handles contributions from both active and folded players correctly.
        """
        # Get ALL players' investments (including folded players)
        # Format: (sid, investment, is_active)
        all_investments = []
        for sid in self.player_order:
            player = self.players[sid]
            if player.total_bet_this_hand > 0:
                all_investments.append((sid, player.total_bet_this_hand, player.is_active()))
        
        if not all_investments:
            return
            
        # Find all unique investment levels to create pot "slices"
        # We must consider folded players' levels too, as they cap their contribution
        levels = sorted(list(set(inv for _, inv, _ in all_investments)))
        
        self.pots = []
        prev_level = 0
        
        for level in levels:
            contribution_per_player = level - prev_level
            if contribution_per_player <= 0:
                continue
                
            # Who contributed to this slice? (Anyone who bet at least this level)
            contributors = [p for p in all_investments if p[1] >= level]
            
            # Who is eligible to win this slice? (Active contributors)
            eligible_winners = [p[0] for p in contributors if p[2]]
            
            # Calculate pot amount for this slice
            pot_amount = contribution_per_player * len(contributors)
            
            if not eligible_winners:
                # Dead money slice (only folded players contributed to this excess)
                # Create a temporary dead pot; will be merged into Main Pot during cleanup.
                self.pots.append(Pot(amount=pot_amount, eligible_players=[]))
            else:
                # Check if we can merge with previous pot
                # We can merge if the eligible winners are IDENTICAL
                can_merge = False
                if self.pots:
                    prev_pot = self.pots[-1]
                    # Compare sets of eligible players AND ensure prev_pot is not a dead pot
                    if prev_pot.eligible_players and set(prev_pot.eligible_players) == set(eligible_winners):
                        prev_pot.amount += pot_amount
                        can_merge = True
                
                if not can_merge:
                    self.pots.append(Pot(
                        amount=pot_amount,
                        eligible_players=eligible_winners
                    ))
            
            prev_level = level

        # Cleanup: Merge any "dead" pots (no eligible winners) based on configured strategy.
        valid_pots = [p for p in self.pots if p.eligible_players]
        dead_money = sum(p.amount for p in self.pots if not p.eligible_players)

        if not valid_pots:
            return

        if dead_money <= 0:
            self.pots = valid_pots
            return

        if DEAD_POT_MERGE_STRATEGY == 'MAIN_POT':
            valid_pots[0].amount += dead_money
        elif DEAD_POT_MERGE_STRATEGY == 'BURN':
            pass
        elif DEAD_POT_MERGE_STRATEGY == 'REFUND':
            pass
        else:
            valid_pots[0].amount += dead_money

        self.pots = valid_pots
    
    def _evaluate_and_distribute_pots(self, showdown_players: List[str]) -> Dict[str, Any]:
        """Evaluate hands and distribute pots to winners."""
        winners = []
        
        # Evaluate each player's hand
        player_hands = {}
        for sid in showdown_players:
            player = self.players[sid]
            if player.hole_cards and self.community_cards and self._evaluator:
                try:
                    hand_rank = self._evaluator.evaluate(
                        player.hole_cards,
                        self.community_cards
                    )
                    player_hands[sid] = hand_rank
                except Exception:
                    player_hands[sid] = 9999  # Worst possible
            else:
                player_hands[sid] = 9999
        
        # Distribute each pot
        for pot in self.pots:
            # Find eligible players with best hand (lowest rank number)
            eligible = [sid for sid in showdown_players if sid in pot.eligible_players]
            
            if not eligible:
                continue
            
            best_rank = min(player_hands.get(sid, 9999) for sid in eligible)
            pot_winners = [sid for sid in eligible if player_hands.get(sid, 9999) == best_rank]
            
            # Split pot among winners
            share = pot.amount // len(pot_winners)
            remainder = pot.amount % len(pot_winners)
            
            for i, winner_sid in enumerate(pot_winners):
                amount = share + (1 if i < remainder else 0)
                self.players[winner_sid].chips += amount
                
                winners.append({
                    'sid': winner_sid,
                    'nickname': self.players[winner_sid].nickname,
                    'amount': amount,
                    'hand_rank': player_hands.get(winner_sid)
                })
        
        return {'winners': winners}
    
    def get_all_hole_cards(self) -> Dict[str, List[str]]:
        """
        Get all players' hole cards for showdown reveal.
        
        Public method for accessing hole cards at showdown.
        
        Returns:
            Dict mapping player SID to their hole cards as strings
        """
        return {
            sid: self._cards_to_strings(player.hole_cards)
            for sid, player in self.players.items()
            if player.hole_cards
        }
    
    def cards_to_strings(self, cards: List[int]) -> List[str]:
        """
        Convert card integers to human-readable strings.
        
        Public wrapper for _cards_to_strings.
        
        Args:
            cards: List of treys card integers
            
        Returns:
            List of card strings (e.g., ["Ah", "Ks"])
        """
        return self._cards_to_strings(cards)
    
    # ========================================================================
    # TIMEOUT HANDLING
    # ========================================================================
    
    def handle_timeout(self, sid: str) -> Dict[str, Any]:
        """
        Handle player timeout - auto-check if free, auto-fold if facing bet.
        
        Args:
            sid: Socket ID of the player who timed out
            
        Returns:
            Dict with the auto-action taken
        """
        player = self.players.get(sid)
        if not player:
            return {'success': False, 'error': 'Player not found'}
        
        player.consecutive_timeouts += 1
        
        # Determine automatic action
        if player.current_bet >= self.current_bet:
            # Free to check
            action = 'check'
            result = self.process_move(sid, 'check')
        else:
            # Must fold
            action = 'fold'
            result = self.process_move(sid, 'fold')
        
        result['auto_action'] = True
        result['timeout'] = True
        
        return result
    
    # ========================================================================
    # UTILITY METHODS
    # ========================================================================
    
    def _is_player_turn(self, sid: str) -> bool:
        """Check if it's the given player's turn."""
        if not self.player_order:
            return False
        
        # Use SID-based check for consistency
        return self.current_player_sid == sid and self.players[sid].can_act()
    
    def _is_betting_round_complete(self) -> bool:
        """Check if the current betting round is complete."""
        active_players = [p for p in self.players.values() if p.can_act()]
        
        # If only one or zero players can act, round is complete
        if len(active_players) <= 1:
            return True
        
        # All active players must have acted and matched the current bet
        for player in active_players:
            if not player.has_acted:
                return False
            if player.current_bet < self.current_bet and player.chips > 0:
                return False
        
        return True
    
    def _should_run_out_board(self) -> bool:
        """
        Check if we should run out the board (deal remaining cards without betting).
        
        This happens when:
        - All players but one have folded, OR
        - All remaining players are all-in
        
        Returns:
            True if board should be run out without further betting
        """
        active_players = [p for p in self.players.values() if p.is_active()]
        
        # Only one player left (others folded)
        if len(active_players) <= 1:
            return True
        
        # Check if all active players are all-in (no one can bet)
        players_who_can_act = [p for p in active_players if p.can_act()]
        return len(players_who_can_act) == 0
    
    def _advance_to_next_player(self):
        """Move to next active player who can act."""
        if not self.player_order or not self.current_player_sid:
            return
        
        # Find current position in player_order
        if self.current_player_sid not in self.player_order:
            return
        
        current_order_pos = self.player_order.index(self.current_player_sid)
        
        # Find next player who can act
        for i in range(1, len(self.player_order) + 1):
            pos = (current_order_pos + i) % len(self.player_order)
            sid = self.player_order[pos]
            if self.players[sid].can_act():
                self.current_player_sid = sid
                
                # Update legacy index
                active_sids = [s for s in self.player_order if self.players[s].can_act()]
                if sid in active_sids:
                    self.current_player_index = active_sids.index(sid)
                self.turn_started_at = datetime.utcnow()
                return

    def get_turn_time_remaining(self) -> float:
        """Get remaining seconds for the current player's turn."""
        if self.phase in (PokerPhase.WAITING, PokerPhase.SHOWDOWN, PokerPhase.FINISHED):
            return 0.0
        if not self.current_player_sid:
            return 0.0
        if self.turn_started_at is None:
            self.turn_started_at = datetime.utcnow()
            return float(TURN_TIMEOUT_SECONDS)

        elapsed = (datetime.utcnow() - self.turn_started_at).total_seconds()
        return max(0.0, float(TURN_TIMEOUT_SECONDS) - elapsed)
    
    def get_total_pot(self) -> int:
        """Get the total pot size."""
        return sum(pot.amount for pot in self.pots)
    
    def _cards_to_strings(self, cards: List[int]) -> List[str]:
        """Convert treys card integers to readable strings."""
        if not cards:
            return []
        
        if Card:
            return [Card.int_to_str(c) for c in cards]
        else:
            # Fallback representation
            suits = ['h', 'd', 'c', 's']
            ranks = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
            result = []
            for c in cards:
                rank = ranks[c % 13]
                suit = suits[c // 13]
                result.append(f"{rank}{suit}")
            return result
    
    def get_game_state(
        self,
        sid: Optional[str] = None,
        for_spectator: bool = False,
        reveal_all: bool = False
    ) -> Dict[str, Any]:
        """
        Get the current game state.
        
        Args:
            sid: Optional player SID for player-specific state
            for_spectator: If True, return sanitized state (no hole cards)
            
        Returns:
            Dict representing current game state
        """
        state = {
            'game_id': self.game_id,
            'phase': self.phase.value,
            'hand_number': self.hand_number,
            'community_cards': self._cards_to_strings(self.community_cards),
            'pot': self.get_total_pot(),
            'current_bet': self.current_bet,
            'min_raise': self.current_bet + self.last_raise_amount,
            'small_blind': self.small_blind,
            'big_blind': self.big_blind,
            'dealer_position': self.dealer_index,
            'players': [],
            'chat_history': [
                {
                    'nickname': msg.player_nickname,
                    'message': msg.message,
                    'action': msg.action,
                    'timestamp': msg.timestamp
                }
                for msg in self.chat_history[-20:]  # Last 20 messages
            ]
        }
        
        # Get current player
        if self.current_player_sid:
            state['current_player'] = self.current_player_sid
        
        # Add player information
        for player_sid in self.player_order:
            player = self.players[player_sid]
            
            player_info = {
                'sid': player_sid,
                'nickname': player.nickname,
                'chips': player.chips,
                'current_bet': player.current_bet,
                'status': player.status.value,
                'last_action': player.last_action
            }
            
            # Only show hole cards to the player themselves (unless showdown or reveal_all)
            if self.phase == PokerPhase.SHOWDOWN or reveal_all:
                # Reveal at showdown or for authorized spectators
                player_info['hole_cards'] = self._cards_to_strings(player.hole_cards)
            elif sid and player_sid == sid and not for_spectator:
                # Player can see their own cards
                player_info['hole_cards'] = self._cards_to_strings(player.hole_cards)
            
            state['players'].append(player_info)
        
        return state
    
    def get_private_state(self, sid: str) -> Dict[str, Any]:
        """
        Get player-specific private state.
        
        This includes hole cards and any other private information.
        
        Args:
            sid: Player's socket ID
            
        Returns:
            Dict with private player information
        """
        player = self.players.get(sid)
        if not player:
            return {}
        
        return {
            'hole_cards': self._cards_to_strings(player.hole_cards),
            'chips': player.chips,
            'current_bet': player.current_bet,
            'status': player.status.value
        }
    
    def is_hand_over(self) -> bool:
        """Check if the current hand is over."""
        # Check if only one player remains
        active_players = [p for p in self.players.values() if p.is_active()]
        if len(active_players) <= 1:
            return True
        
        return self.phase in (PokerPhase.SHOWDOWN, PokerPhase.FINISHED)
    
    def end_hand(self) -> Dict[str, Any]:
        """
        End the current hand and prepare for the next.
        
        Returns:
            Dict with hand summary
        """
        self.phase = PokerPhase.WAITING
        
        # Clear temporary state
        self.community_cards = []
        self.chat_history = []
        self.pots = [Pot()]
        self.turn_started_at = None
        
        # Return summary
        return {
            'success': True,
            'hand_ended': True,
            'hand_number': self.hand_number
        }

    def to_dict(self) -> Dict[str, Any]:
        """Serialize full engine state for restart recovery."""
        return {
            'game_id': self.game_id,
            'small_blind': self.small_blind,
            'big_blind': self.big_blind,
            'min_raise': self.min_raise,
            'phase': self.phase.value,
            'player_order': list(self.player_order),
            'dealer_sid': self.dealer_sid,
            'small_blind_sid': self.small_blind_sid,
            'big_blind_sid': self.big_blind_sid,
            'current_player_sid': self.current_player_sid,
            'dealer_index': self.dealer_index,
            'small_blind_index': self.small_blind_index,
            'big_blind_index': self.big_blind_index,
            'current_player_index': self.current_player_index,
            'current_bet': self.current_bet,
            'last_raise_amount': self.last_raise_amount,
            'pots': [
                {
                    'amount': pot.amount,
                    'eligible_players': list(pot.eligible_players),
                }
                for pot in self.pots
            ],
            'community_cards': list(self.community_cards),
            'chat_history': [
                {
                    'player_sid': msg.player_sid,
                    'player_nickname': msg.player_nickname,
                    'message': msg.message,
                    'timestamp': msg.timestamp,
                    'action': msg.action,
                }
                for msg in self.chat_history[-100:]
            ],
            'hand_number': self.hand_number,
            'last_hand_winners': list(self.last_hand_winners),
            'turn_started_at': self.turn_started_at.isoformat() if self.turn_started_at else None,
            'players': {
                sid: {
                    'sid': player.sid,
                    # 'wallet_address': player.wallet_address, # Removed for privacy
                    'nickname': player.nickname,
                    'chips': player.chips,
                    'hole_cards': list(player.hole_cards),
                    'status': player.status.value,
                    'current_bet': player.current_bet,
                    'total_bet_this_round': player.total_bet_this_round,
                    'total_bet_this_hand': player.total_bet_this_hand,
                    'has_acted': player.has_acted,
                    'last_action': player.last_action,
                    'last_action_time': player.last_action_time.isoformat() if player.last_action_time else None,
                    'consecutive_timeouts': player.consecutive_timeouts,
                }
                for sid, player in self.players.items()
            }
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> 'TexasEngine':
        """Restore engine state from serialized snapshot."""
        game_id = data.get('game_id', 'restored_table')
        engine = cls(
            game_id=game_id,
            small_blind=int(data.get('small_blind', DEFAULT_SMALL_BLIND)),
            big_blind=int(data.get('big_blind', DEFAULT_BIG_BLIND))
        )

        try:
            engine.phase = PokerPhase(data.get('phase', PokerPhase.WAITING.value))
        except ValueError:
            engine.phase = PokerPhase.WAITING

        engine.min_raise = int(data.get('min_raise', engine.big_blind))
        engine.player_order = list(data.get('player_order', []))
        engine.dealer_sid = data.get('dealer_sid')
        engine.small_blind_sid = data.get('small_blind_sid')
        engine.big_blind_sid = data.get('big_blind_sid')
        engine.current_player_sid = data.get('current_player_sid')
        engine.dealer_index = int(data.get('dealer_index', 0))
        engine.small_blind_index = int(data.get('small_blind_index', 0))
        engine.big_blind_index = int(data.get('big_blind_index', 0))
        engine.current_player_index = int(data.get('current_player_index', 0))
        engine.current_bet = int(data.get('current_bet', 0))
        engine.last_raise_amount = int(data.get('last_raise_amount', engine.big_blind))
        engine.community_cards = [int(c) for c in data.get('community_cards', [])]
        engine.hand_number = int(data.get('hand_number', 0))
        engine.last_hand_winners = list(data.get('last_hand_winners', []))

        ts = data.get('turn_started_at')
        if ts:
            try:
                engine.turn_started_at = datetime.fromisoformat(ts)
            except (TypeError, ValueError):
                engine.turn_started_at = datetime.utcnow()

        players_data = data.get('players', {})
        engine.players = {}
        for sid, p in players_data.items():
            try:
                status = PlayerStatus(p.get('status', PlayerStatus.ACTIVE.value))
            except ValueError:
                status = PlayerStatus.ACTIVE

            player = PokerPlayer(
                sid=p.get('sid', sid),
                wallet_address=p.get('wallet_address', ''),
                nickname=p.get('nickname', 'Player'),
                chips=int(p.get('chips', 0)),
                hole_cards=[int(c) for c in p.get('hole_cards', [])],
                status=status,
                current_bet=int(p.get('current_bet', 0)),
                total_bet_this_round=int(p.get('total_bet_this_round', 0)),
                total_bet_this_hand=int(p.get('total_bet_this_hand', 0)),
                has_acted=bool(p.get('has_acted', False)),
                last_action=p.get('last_action'),
                consecutive_timeouts=int(p.get('consecutive_timeouts', 0)),
            )

            last_action_time = p.get('last_action_time')
            if last_action_time:
                try:
                    player.last_action_time = datetime.fromisoformat(last_action_time)
                except (TypeError, ValueError):
                    player.last_action_time = None

            engine.players[sid] = player

        if not engine.player_order:
            engine.player_order = list(engine.players.keys())

        engine.pots = []
        for pot_data in data.get('pots', []):
            engine.pots.append(
                Pot(
                    amount=int(pot_data.get('amount', 0)),
                    eligible_players=list(pot_data.get('eligible_players', []))
                )
            )
        if not engine.pots:
            engine.pots = [Pot()]

        engine.chat_history = []
        for msg in data.get('chat_history', []):
            engine.chat_history.append(
                ChatMessage(
                    player_sid=msg.get('player_sid', ''),
                    player_nickname=msg.get('player_nickname', 'Player'),
                    message=msg.get('message', ''),
                    timestamp=msg.get('timestamp', datetime.utcnow().isoformat()),
                    action=msg.get('action')
                )
            )

        return engine


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_poker_game(
    game_id: Optional[str] = None,
    small_blind: int = DEFAULT_SMALL_BLIND,
    big_blind: int = DEFAULT_BIG_BLIND
) -> TexasEngine:
    """
    Create a new poker game instance.
    
    Args:
        game_id: Optional custom game ID (auto-generated if not provided)
        small_blind: Small blind amount
        big_blind: Big blind amount
        
    Returns:
        New PokerEngine instance
    """
    if game_id is None:
        game_id = f"poker_{uuid.uuid4().hex[:12]}"
    
    return TexasEngine(
        game_id=game_id,
        small_blind=small_blind,
        big_blind=big_blind
    )
