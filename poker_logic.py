"""
poker_logic.py - The State Machine for Texas Hold'em Poker

This module implements the core game logic for Texas Hold'em poker,
managing game state, players, and game flow.
"""

import random
import secrets
from typing import List, Dict, Optional, Tuple
from enum import Enum


class HandRank(Enum):
    """Poker hand rankings for simplified evaluation."""
    HIGH_CARD = 1
    PAIR = 2
    TWO_PAIR = 3
    THREE_OF_A_KIND = 4
    STRAIGHT = 5
    FLUSH = 6
    FULL_HOUSE = 7
    FOUR_OF_A_KIND = 8
    STRAIGHT_FLUSH = 9
    ROYAL_FLUSH = 10


class TexasHoldemTable:
    """
    Texas Hold'em poker table state machine.
    
    Manages the complete game state including deck, pot, community cards,
    players, and game flow.
    """
    
    def __init__(self, table_id: str, small_blind: int = 10, big_blind: int = 20):
        self.table_id = table_id
        self.small_blind = small_blind
        self.big_blind = big_blind
        
        # Game state
        self.deck: List[str] = []
        self.pot: int = 0
        self.community_cards: List[str] = []
        self.current_player_index: int = 0
        self.dealer_index: int = 0
        self.current_bet: int = 0
        self.stage: str = "waiting"  # waiting, pre_flop, flop, turn, river, showdown
        
        # Players list: [{'sid': str, 'address': str, 'chips': int, 'hand': [], 'status': str, 'bet': int}]
        self.players: List[Dict] = []
        
        # Betting round tracking
        self.last_raiser_index: Optional[int] = None
        self.players_acted: set = set()
        
    def add_player(self, sid: str, address: str, chips: int = 1000) -> bool:
        """Add a player to the table."""
        if len(self.players) >= 9:  # Max 9 players
            return False
        
        # Check if player already at table
        if any(p['sid'] == sid or p['address'] == address for p in self.players):
            return False
        
        player = {
            'sid': sid,
            'address': address,
            'chips': chips,
            'hand': [],
            'status': 'active',
            'bet': 0,
            'position': len(self.players)
        }
        self.players.append(player)
        return True
    
    def remove_player(self, sid: str) -> bool:
        """Remove a player from the table."""
        self.players = [p for p in self.players if p['sid'] != sid]
        return True
    
    def _create_deck(self) -> List[str]:
        """Create and shuffle a standard 52-card deck."""
        suits = ['h', 'd', 'c', 's']  # hearts, diamonds, clubs, spades
        ranks = ['2', '3', '4', '5', '6', '7', '8', '9', 'T', 'J', 'Q', 'K', 'A']
        deck = [f"{rank}{suit}" for suit in suits for rank in ranks]
        
        # Cryptographically secure shuffle
        for i in range(len(deck) - 1, 0, -1):
            j = secrets.randbelow(i + 1)
            deck[i], deck[j] = deck[j], deck[i]
        
        return deck
    
    def deal_hands(self) -> bool:
        """
        Start a new hand by dealing cards to all active players.
        Returns True if successful, False if not enough players.
        """
        active_players = [p for p in self.players if p['status'] != 'folded' and p['chips'] > 0]
        if len(active_players) < 2:
            return False
        
        # Reset game state
        self.deck = self._create_deck()
        self.pot = 0
        self.community_cards = []
        self.current_bet = 0
        self.stage = "pre_flop"
        self.players_acted = set()
        
        # Reset player states
        for player in self.players:
            player['hand'] = []
            player['status'] = 'active' if player['chips'] > 0 else 'folded'
            player['bet'] = 0
        
        # Deal 2 cards to each active player
        active_players = [p for p in self.players if p['status'] == 'active']
        for _ in range(2):
            for player in active_players:
                if self.deck:
                    player['hand'].append(self.deck.pop())
        
        # Post blinds
        self._post_blinds()
        
        # Set first player to act (after big blind)
        self.current_player_index = (self.dealer_index + 3) % len(self.players)
        self._find_next_active_player()
        
        return True
    
    def _post_blinds(self):
        """Post small and big blinds."""
        if len(self.players) < 2:
            return
        
        # Small blind
        sb_index = (self.dealer_index + 1) % len(self.players)
        sb_player = self.players[sb_index]
        sb_amount = min(self.small_blind, sb_player['chips'])
        sb_player['chips'] -= sb_amount
        sb_player['bet'] = sb_amount
        self.pot += sb_amount
        
        # Big blind
        bb_index = (self.dealer_index + 2) % len(self.players)
        bb_player = self.players[bb_index]
        bb_amount = min(self.big_blind, bb_player['chips'])
        bb_player['chips'] -= bb_amount
        bb_player['bet'] = bb_amount
        self.pot += bb_amount
        self.current_bet = bb_amount
    
    def apply_action(self, sid: str, action: str, amount: int = 0) -> Dict:
        """
        Apply a player action (fold, check, call, raise, bet, all_in).
        
        Returns a dict with 'success' bool and optional 'error' message.
        """
        # Find player
        player_index = None
        for i, p in enumerate(self.players):
            if p['sid'] == sid:
                player_index = i
                break
        
        if player_index is None:
            return {'success': False, 'error': 'Player not found'}
        
        # Check if it's player's turn
        if player_index != self.current_player_index:
            return {'success': False, 'error': 'Not your turn'}
        
        player = self.players[player_index]
        
        # Check if player can act
        if player['status'] != 'active':
            return {'success': False, 'error': 'Player is not active'}
        
        # Process action
        if action == 'fold':
            player['status'] = 'folded'
        
        elif action == 'check':
            if player['bet'] < self.current_bet:
                return {'success': False, 'error': 'Cannot check, must call or raise'}
        
        elif action == 'call':
            call_amount = self.current_bet - player['bet']
            actual_amount = min(call_amount, player['chips'])
            player['chips'] -= actual_amount
            player['bet'] += actual_amount
            self.pot += actual_amount
            
            if player['chips'] == 0:
                player['status'] = 'all_in'
        
        elif action in ['raise', 'bet']:
            total_bet = player['bet'] + amount
            if total_bet <= self.current_bet:
                return {'success': False, 'error': 'Raise amount too small'}
            
            actual_amount = min(amount, player['chips'])
            player['chips'] -= actual_amount
            player['bet'] += actual_amount
            self.pot += actual_amount
            self.current_bet = player['bet']
            self.last_raiser_index = player_index
            
            if player['chips'] == 0:
                player['status'] = 'all_in'
        
        elif action == 'all_in':
            all_in_amount = player['chips']
            player['chips'] = 0
            player['bet'] += all_in_amount
            self.pot += all_in_amount
            
            if player['bet'] > self.current_bet:
                self.current_bet = player['bet']
                self.last_raiser_index = player_index
            
            player['status'] = 'all_in'
        
        else:
            return {'success': False, 'error': 'Invalid action'}
        
        # Mark player as acted
        self.players_acted.add(player_index)
        
        # Move to next player
        self._advance_to_next_player()
        
        # Check if betting round is complete
        if self._is_betting_round_complete():
            self._advance_stage()
        
        return {'success': True}
    
    def _find_next_active_player(self):
        """Find the next active player who can act."""
        checked = 0
        while checked < len(self.players):
            player = self.players[self.current_player_index]
            if player['status'] == 'active' and player['chips'] > 0:
                return
            self.current_player_index = (self.current_player_index + 1) % len(self.players)
            checked += 1
        
        # No active players left
        self.current_player_index = -1
    
    def _advance_to_next_player(self):
        """Move to the next player's turn."""
        self.current_player_index = (self.current_player_index + 1) % len(self.players)
        self._find_next_active_player()
    
    def _is_betting_round_complete(self) -> bool:
        """Check if the current betting round is complete."""
        active_players = [p for p in self.players if p['status'] == 'active']
        
        # Only one player left
        if len(active_players) <= 1:
            return True
        
        # All active players have matched the current bet and acted
        for i, player in enumerate(self.players):
            if player['status'] == 'active':
                if player['bet'] != self.current_bet or i not in self.players_acted:
                    return False
        
        return True
    
    def _advance_stage(self):
        """Advance to the next stage of the game."""
        # Reset bets for next round
        for player in self.players:
            player['bet'] = 0
        self.current_bet = 0
        self.players_acted = set()
        
        if self.stage == "pre_flop":
            # Deal flop (3 cards)
            self.community_cards = [self.deck.pop() for _ in range(3)]
            self.stage = "flop"
            self.current_player_index = (self.dealer_index + 1) % len(self.players)
            self._find_next_active_player()
        
        elif self.stage == "flop":
            # Deal turn (1 card)
            self.community_cards.append(self.deck.pop())
            self.stage = "turn"
            self.current_player_index = (self.dealer_index + 1) % len(self.players)
            self._find_next_active_player()
        
        elif self.stage == "turn":
            # Deal river (1 card)
            self.community_cards.append(self.deck.pop())
            self.stage = "river"
            self.current_player_index = (self.dealer_index + 1) % len(self.players)
            self._find_next_active_player()
        
        elif self.stage == "river":
            # Showdown
            self.stage = "showdown"
            self._determine_winner()
    
    def determine_winner(self) -> List[Dict]:
        """
        Determine the winner(s) of the hand.
        Returns list of winner dicts with player info and winnings.
        """
        return self._determine_winner()
    
    def _determine_winner(self) -> List[Dict]:
        """
        Internal method to determine winner(s) and distribute pot.
        Simple heuristic for MVP: evaluates hand strength.
        """
        active_players = [p for p in self.players if p['status'] != 'folded']
        
        if len(active_players) == 1:
            # Only one player left - they win
            winner = active_players[0]
            winner['chips'] += self.pot
            return [{
                'address': winner['address'],
                'chips_won': self.pot,
                'hand': winner['hand']
            }]
        
        # Evaluate all hands
        player_hands = []
        for player in active_players:
            all_cards = player['hand'] + self.community_cards
            rank, high_cards = self._evaluate_hand(all_cards)
            player_hands.append({
                'player': player,
                'rank': rank,
                'high_cards': high_cards
            })
        
        # Find best hand(s)
        best_rank = max(ph['rank'] for ph in player_hands)
        winners = [ph for ph in player_hands if ph['rank'] == best_rank]
        
        # If multiple winners with same rank, compare high cards
        if len(winners) > 1:
            best_high_cards = max(w['high_cards'] for w in winners)
            winners = [w for w in winners if w['high_cards'] == best_high_cards]
        
        # Distribute pot
        share = self.pot // len(winners)
        remainder = self.pot % len(winners)
        
        results = []
        for i, winner_data in enumerate(winners):
            winner = winner_data['player']
            winnings = share + (1 if i < remainder else 0)
            winner['chips'] += winnings
            results.append({
                'address': winner['address'],
                'chips_won': winnings,
                'hand': winner['hand']
            })
        
        self.pot = 0
        return results
    
    def _evaluate_hand(self, cards: List[str]) -> Tuple[int, List[int]]:
        """
        Evaluate a poker hand (simplified for MVP).
        Returns (rank, high_cards) for comparison.
        """
        if len(cards) < 5:
            return (HandRank.HIGH_CARD.value, [0])
        
        # Parse cards
        ranks = []
        suits = []
        rank_values = {'2': 2, '3': 3, '4': 4, '5': 5, '6': 6, '7': 7, 
                      '8': 8, '9': 9, 'T': 10, 'J': 11, 'Q': 12, 'K': 13, 'A': 14}
        
        for card in cards:
            ranks.append(rank_values[card[0]])
            suits.append(card[1])
        
        # Count ranks
        rank_counts = {}
        for rank in ranks:
            rank_counts[rank] = rank_counts.get(rank, 0) + 1
        
        counts = sorted(rank_counts.values(), reverse=True)
        unique_ranks = sorted(rank_counts.keys(), reverse=True)
        
        # Check for flush
        is_flush = len(set(suits)) == 1 if len(suits) >= 5 else False
        
        # Check for straight
        is_straight = False
        for i in range(len(unique_ranks) - 4):
            if unique_ranks[i] - unique_ranks[i+4] == 4:
                is_straight = True
                break
        
        # Determine hand rank
        if is_flush and is_straight:
            return (HandRank.STRAIGHT_FLUSH.value, unique_ranks[:5])
        elif counts[0] == 4:
            return (HandRank.FOUR_OF_A_KIND.value, unique_ranks[:2])
        elif counts[0] == 3 and counts[1] == 2:
            return (HandRank.FULL_HOUSE.value, unique_ranks[:2])
        elif is_flush:
            return (HandRank.FLUSH.value, unique_ranks[:5])
        elif is_straight:
            return (HandRank.STRAIGHT.value, unique_ranks[:5])
        elif counts[0] == 3:
            return (HandRank.THREE_OF_A_KIND.value, unique_ranks[:3])
        elif counts[0] == 2 and counts[1] == 2:
            return (HandRank.TWO_PAIR.value, unique_ranks[:3])
        elif counts[0] == 2:
            return (HandRank.PAIR.value, unique_ranks[:4])
        else:
            return (HandRank.HIGH_CARD.value, unique_ranks[:5])
    
    def get_game_state(self, sid: Optional[str] = None) -> Dict:
        """
        Get the current game state.
        If sid is provided, includes that player's hole cards.
        """
        # Hide other players' cards
        players_state = []
        for player in self.players:
            player_data = {
                'address': player['address'],
                'chips': player['chips'],
                'status': player['status'],
                'bet': player['bet'],
                'position': player['position']
            }
            
            # Only show cards to the player or during showdown
            if sid == player['sid'] or self.stage == 'showdown':
                player_data['hand'] = player['hand']
            else:
                player_data['hand'] = []
            
            players_state.append(player_data)
        
        return {
            'table_id': self.table_id,
            'stage': self.stage,
            'pot': self.pot,
            'current_bet': self.current_bet,
            'community_cards': self.community_cards,
            'players': players_state,
            'current_player_index': self.current_player_index,
            'dealer_index': self.dealer_index
        }
