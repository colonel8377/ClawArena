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
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum
from typing import Dict, List, Optional, Any, Callable, Awaitable

try:
    from treys import Card, Evaluator, Deck
except ImportError:
    # Fallback for environments without treys
    Card = None
    Evaluator = None
    Deck = None


# ============================================================================
# CONSTANTS
# ============================================================================

# Timeout configuration
TURN_TIMEOUT_SECONDS = 20  # Fast poker - 20 second turn timer
DEFAULT_SMALL_BLIND = 25
DEFAULT_BIG_BLIND = 50
MIN_PLAYERS = 2
MAX_PLAYERS = 9


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


class PlayerAction(Enum):
    """Available player actions."""
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    RAISE = "raise"
    ALL_IN = "all_in"


class PlayerStatus(Enum):
    """Player status in game."""
    ACTIVE = "active"
    FOLDED = "folded"
    ALL_IN = "all_in"
    SITTING_OUT = "sitting_out"


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
    current_bet: int = 0
    total_bet_this_round: int = 0
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

class PokerEngine:
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
        
        # Dealer/blind positions
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
        
        # Reset players
        for player in self.players.values():
            player.reset_for_new_hand()
        
        # Reset game state
        self.phase = PokerPhase.PRE_FLOP
        self.community_cards = []
        self.pots = [Pot()]
        self.current_bet = 0
        self.last_raise_amount = self.big_blind
        
        # Move dealer button
        self._rotate_dealer()
        
        # Create and shuffle deck
        self._create_deck()
        
        # Deal hole cards
        self._deal_hole_cards()
        
        # Post blinds
        self._post_blinds()
        
        # Set first player to act (after big blind)
        self._set_first_to_act()
        
        # Generate hole cards info for each player
        hole_cards_info = {}
        for sid, player in self.players.items():
            hole_cards_info[sid] = self._cards_to_strings(player.hole_cards)
        
        return {
            'success': True,
            'hand_number': self.hand_number,
            'dealer': self.player_order[self.dealer_index],
            'small_blind': self.player_order[self.small_blind_index],
            'big_blind': self.player_order[self.big_blind_index],
            'current_player': self.player_order[self.current_player_index],
            'hole_cards': hole_cards_info,
            'pot': self.get_total_pot()
        }
    
    def _create_deck(self):
        """Create and shuffle a new deck."""
        if Deck:
            deck = Deck()
            self._deck = deck.draw(52)
        else:
            # Fallback: create simple deck representation
            self._deck = list(range(52))
            random.shuffle(self._deck)
    
    def _deal_hole_cards(self):
        """Deal two hole cards to each active player."""
        active_sids = [sid for sid in self.player_order 
                       if self.players[sid].status == PlayerStatus.ACTIVE]
        
        for _ in range(2):
            for sid in active_sids:
                if self._deck:
                    card = self._deck.pop()
                    self.players[sid].hole_cards.append(card)
    
    def _post_blinds(self):
        """Post small and big blinds."""
        active_sids = [sid for sid in self.player_order 
                       if self.players[sid].status == PlayerStatus.ACTIVE]
        
        if len(active_sids) < MIN_PLAYERS:
            return
        
        # Calculate blind positions relative to active_sids
        dealer_pos = self.dealer_index % len(active_sids)
        
        if len(active_sids) == 2:
            # Heads-up: dealer is small blind
            sb_pos = dealer_pos
            bb_pos = (dealer_pos + 1) % len(active_sids)
        else:
            sb_pos = (dealer_pos + 1) % len(active_sids)
            bb_pos = (dealer_pos + 2) % len(active_sids)
        
        # Store positions for this hand
        self.small_blind_index = sb_pos
        self.big_blind_index = bb_pos
        
        # Post small blind
        sb_sid = active_sids[sb_pos]
        sb_amount = min(self.small_blind, self.players[sb_sid].chips)
        self._place_bet(sb_sid, sb_amount)
        
        # Post big blind
        bb_sid = active_sids[bb_pos]
        bb_amount = min(self.big_blind, self.players[bb_sid].chips)
        self._place_bet(bb_sid, bb_amount)
        
        self.current_bet = bb_amount
    
    def _rotate_dealer(self):
        """Move dealer button to next active player."""
        if not self.player_order:
            return
        
        # Find next active player
        active_sids = [sid for sid in self.player_order 
                       if self.players[sid].status == PlayerStatus.ACTIVE]
        
        if len(active_sids) < MIN_PLAYERS:
            return
        
        # Rotate dealer position
        self.dealer_index = (self.dealer_index + 1) % len(active_sids)
    
    def _set_first_to_act(self):
        """Set the first player to act after dealing."""
        active_sids = [sid for sid in self.player_order 
                       if self.players[sid].can_act()]
        
        if not active_sids:
            return
        
        if len(active_sids) <= 2:
            # Heads-up: small blind acts first pre-flop
            self.current_player_index = self.small_blind_index % len(active_sids)
        else:
            # UTG acts first (player after big blind)
            self.current_player_index = (self.big_blind_index + 1) % len(active_sids)
    
    # ========================================================================
    # BETTING ACTIONS
    # ========================================================================
    
    def process_move(
        self,
        sid: str,
        action: str,
        amount: int = 0,
        chat_message: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Process a player's move with optional chat/bluff message.
        
        This is the main action handler that validates and executes player moves.
        The chat_message field allows agents to bluff, taunt, or communicate
        while making their move.
        
        Args:
            sid: Player's socket ID
            action: One of 'fold', 'check', 'call', 'raise'
            amount: Required if action is 'raise', the total bet amount
            chat_message: Optional trash talk/bluff message
            
        Returns:
            Dict with success status and move details
        """
        # Validate it's this player's turn
        if not self._is_player_turn(sid):
            return {'success': False, 'error': 'Not your turn'}
        
        player = self.players.get(sid)
        if not player or not player.can_act():
            return {'success': False, 'error': 'Player cannot act'}
        
        # Process chat message first (always broadcast, even if action fails)
        if chat_message:
            chat_entry = ChatMessage(
                player_sid=sid,
                player_nickname=player.nickname,
                message=chat_message,
                action=action
            )
            self.chat_history.append(chat_entry)
        
        # Validate and execute action
        result = self._execute_action(sid, action, amount)
        
        if result['success']:
            player.has_acted = True
            player.last_action = action
            player.last_action_time = datetime.utcnow()
            player.consecutive_timeouts = 0
            
            # Add chat to result for broadcasting
            result['chat'] = chat_message
            result['player_nickname'] = player.nickname
            
            # Check if betting round is complete
            if self._is_betting_round_complete():
                result['round_complete'] = True
                result['advance_phase'] = True
            else:
                # Move to next player
                self._advance_to_next_player()
                result['next_player'] = self.player_order[self.current_player_index]
        
        return result
    
    def _execute_action(self, sid: str, action: str, amount: int) -> Dict[str, Any]:
        """Execute the player's action."""
        player = self.players[sid]
        
        if action == 'fold':
            return self._handle_fold(sid)
        elif action == 'check':
            return self._handle_check(sid)
        elif action == 'call':
            return self._handle_call(sid)
        elif action == 'raise':
            return self._handle_raise(sid, amount)
        else:
            return {'success': False, 'error': f'Unknown action: {action}'}
    
    def _handle_fold(self, sid: str) -> Dict[str, Any]:
        """Handle fold action."""
        player = self.players[sid]
        player.status = PlayerStatus.FOLDED
        
        return {
            'success': True,
            'action': 'fold',
            'player_sid': sid
        }
    
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
        
        # Add to main pot (side pots handled at showdown)
        self.pots[0].add(amount, sid)
    
    # ========================================================================
    # PHASE MANAGEMENT
    # ========================================================================
    
    def advance_phase(self) -> Dict[str, Any]:
        """
        Advance to the next phase and deal community cards.
        
        Returns:
            Dict with phase change information
        """
        # Reset betting state for new round
        for player in self.players.values():
            player.current_bet = 0
            player.has_acted = False
        
        self.current_bet = 0
        self.last_raise_amount = self.big_blind
        
        if self.phase == PokerPhase.PRE_FLOP:
            return self._deal_flop()
        elif self.phase == PokerPhase.FLOP:
            return self._deal_turn()
        elif self.phase == PokerPhase.TURN:
            return self._deal_river()
        elif self.phase == PokerPhase.RIVER:
            return self._start_showdown()
        else:
            return {'success': False, 'error': 'Cannot advance from current phase'}
    
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
            'current_player': self.player_order[self.current_player_index]
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
            'current_player': self.player_order[self.current_player_index]
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
            'current_player': self.player_order[self.current_player_index]
        }
    
    def _set_post_flop_first_to_act(self):
        """Set first player to act post-flop (first active after dealer)."""
        active_sids = [sid for sid in self.player_order 
                       if self.players[sid].can_act()]
        
        if not active_sids:
            return
        
        # First active player after dealer
        self.current_player_index = (self.dealer_index + 1) % len(active_sids)
    
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
                'player_hands': self._get_all_hole_cards()
            }
        
        # Evaluate hands and determine winners for each pot
        results = self._evaluate_and_distribute_pots(showdown_players)
        
        return {
            'success': True,
            'phase': 'showdown',
            'winners': results['winners'],
            'player_hands': self._get_all_hole_cards(),
            'community_cards': self._cards_to_strings(self.community_cards)
        }
    
    def _calculate_side_pots(self):
        """Calculate side pots for all-in scenarios."""
        # Get all players' total investments
        investments = []
        for sid in self.player_order:
            player = self.players[sid]
            if player.is_active() and player.total_bet_this_round > 0:
                investments.append((sid, player.total_bet_this_round))
        
        if not investments:
            return
        
        # Sort by investment amount
        investments.sort(key=lambda x: x[1])
        
        # Calculate pots
        self.pots = []
        prev_investment = 0
        eligible_players = [sid for sid, _ in investments]
        
        for i, (sid, investment) in enumerate(investments):
            if investment > prev_investment:
                pot_contribution = investment - prev_investment
                pot_amount = pot_contribution * (len(investments) - i)
                
                self.pots.append(Pot(
                    amount=pot_amount,
                    eligible_players=list(eligible_players)
                ))
            
            # Remove player from eligibility for next pots
            eligible_players.remove(sid)
            prev_investment = investment
    
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
    
    def _get_all_hole_cards(self) -> Dict[str, List[str]]:
        """Get all players' hole cards for showdown reveal."""
        return self.get_all_hole_cards()
    
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
        
        active_sids = [s for s in self.player_order if self.players[s].can_act()]
        if not active_sids or self.current_player_index >= len(active_sids):
            return False
        
        return active_sids[self.current_player_index] == sid
    
    def _is_betting_round_complete(self) -> bool:
        """Check if the current betting round is complete."""
        active_players = [p for p in self.players.values() if p.can_act()]
        
        if len(active_players) <= 1:
            return True
        
        # All active players must have acted and matched the current bet
        for player in active_players:
            if not player.has_acted:
                return False
            if player.current_bet < self.current_bet and player.chips > 0:
                return False
        
        return True
    
    def _advance_to_next_player(self):
        """Move to the next active player."""
        active_sids = [s for s in self.player_order if self.players[s].can_act()]
        
        if not active_sids:
            return
        
        start_index = self.current_player_index
        self.current_player_index = (self.current_player_index + 1) % len(active_sids)
        
        # Skip players who can't act
        while self.current_player_index != start_index:
            if self.players[active_sids[self.current_player_index]].can_act():
                break
            self.current_player_index = (self.current_player_index + 1) % len(active_sids)
    
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
    
    def get_game_state(self, sid: Optional[str] = None, for_spectator: bool = False) -> Dict[str, Any]:
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
        active_sids = [s for s in self.player_order if self.players[s].can_act()]
        if active_sids and self.current_player_index < len(active_sids):
            state['current_player'] = active_sids[self.current_player_index]
        
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
            
            # Only show hole cards to the player themselves (unless showdown or spectator mode)
            if self.phase == PokerPhase.SHOWDOWN:
                # Reveal at showdown
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
        
        # Return summary
        return {
            'success': True,
            'hand_ended': True,
            'hand_number': self.hand_number
        }


# ============================================================================
# FACTORY FUNCTION
# ============================================================================

def create_poker_game(
    game_id: Optional[str] = None,
    small_blind: int = DEFAULT_SMALL_BLIND,
    big_blind: int = DEFAULT_BIG_BLIND
) -> PokerEngine:
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
    
    return PokerEngine(
        game_id=game_id,
        small_blind=small_blind,
        big_blind=big_blind
    )
