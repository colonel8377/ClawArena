"""Poker game logic and hand evaluation."""

import random
from typing import List, Tuple, Optional
from collections import Counter
from arena_poker.models import (
    Card, Suit, Rank, HandRank, Player, GameState, 
    GameStage, PlayerAction
)


class Deck:
    """Represents a deck of cards."""

    def __init__(self):
        self.cards: List[Card] = []
        self.reset()

    def reset(self):
        """Reset and shuffle the deck."""
        self.cards = [
            Card(rank=rank, suit=suit)
            for suit in Suit
            for rank in Rank
        ]
        self.shuffle()

    def shuffle(self):
        """Shuffle the deck."""
        random.shuffle(self.cards)

    def deal(self, count: int = 1) -> List[Card]:
        """Deal cards from the deck."""
        dealt = self.cards[:count]
        self.cards = self.cards[count:]
        return dealt


class HandEvaluator:
    """Evaluates poker hands."""

    RANK_VALUES = {
        Rank.TWO: 2, Rank.THREE: 3, Rank.FOUR: 4, Rank.FIVE: 5,
        Rank.SIX: 6, Rank.SEVEN: 7, Rank.EIGHT: 8, Rank.NINE: 9,
        Rank.TEN: 10, Rank.JACK: 11, Rank.QUEEN: 12, Rank.KING: 13, Rank.ACE: 14
    }

    @classmethod
    def evaluate_hand(cls, cards: List[Card]) -> Tuple[HandRank, List[int]]:
        """
        Evaluate a poker hand (5-7 cards).
        Returns (hand_rank, high_cards) where high_cards is for tie-breaking.
        """
        if len(cards) < 5:
            return HandRank.HIGH_CARD, []

        # Find best 5-card combination
        from itertools import combinations
        best_rank = HandRank.HIGH_CARD
        best_values = []

        for combo in combinations(cards, 5):
            rank, values = cls._evaluate_five_cards(list(combo))
            if cls._compare_hands(rank, values, best_rank, best_values) > 0:
                best_rank = rank
                best_values = values

        return best_rank, best_values

    @classmethod
    def _evaluate_five_cards(cls, cards: List[Card]) -> Tuple[HandRank, List[int]]:
        """Evaluate exactly 5 cards."""
        ranks = [cls.RANK_VALUES[card.rank] for card in cards]
        suits = [card.suit for card in cards]
        rank_counts = Counter(ranks)
        
        is_flush = len(set(suits)) == 1
        is_straight = cls._is_straight(ranks)
        
        counts = sorted(rank_counts.values(), reverse=True)
        unique_ranks = sorted(rank_counts.keys(), reverse=True)

        # Royal flush
        if is_flush and is_straight and max(ranks) == 14 and min(ranks) == 10:
            return HandRank.ROYAL_FLUSH, unique_ranks

        # Straight flush
        if is_flush and is_straight:
            return HandRank.STRAIGHT_FLUSH, unique_ranks

        # Four of a kind
        if counts == [4, 1]:
            quad = [r for r, c in rank_counts.items() if c == 4][0]
            kicker = [r for r, c in rank_counts.items() if c == 1][0]
            return HandRank.FOUR_OF_A_KIND, [quad, kicker]

        # Full house
        if counts == [3, 2]:
            triple = [r for r, c in rank_counts.items() if c == 3][0]
            pair = [r for r, c in rank_counts.items() if c == 2][0]
            return HandRank.FULL_HOUSE, [triple, pair]

        # Flush
        if is_flush:
            return HandRank.FLUSH, sorted(unique_ranks, reverse=True)

        # Straight
        if is_straight:
            return HandRank.STRAIGHT, unique_ranks

        # Three of a kind
        if counts == [3, 1, 1]:
            triple = [r for r, c in rank_counts.items() if c == 3][0]
            kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)
            return HandRank.THREE_OF_A_KIND, [triple] + kickers

        # Two pair
        if counts == [2, 2, 1]:
            pairs = sorted([r for r, c in rank_counts.items() if c == 2], reverse=True)
            kicker = [r for r, c in rank_counts.items() if c == 1][0]
            return HandRank.TWO_PAIR, pairs + [kicker]

        # One pair
        if counts == [2, 1, 1, 1]:
            pair = [r for r, c in rank_counts.items() if c == 2][0]
            kickers = sorted([r for r, c in rank_counts.items() if c == 1], reverse=True)
            return HandRank.PAIR, [pair] + kickers

        # High card
        return HandRank.HIGH_CARD, sorted(unique_ranks, reverse=True)

    @staticmethod
    def _is_straight(ranks: List[int]) -> bool:
        """Check if ranks form a straight."""
        sorted_ranks = sorted(set(ranks))
        if len(sorted_ranks) != 5:
            return False
        
        # Regular straight
        if sorted_ranks[-1] - sorted_ranks[0] == 4:
            return True
        
        # Ace-low straight (A-2-3-4-5)
        if sorted_ranks == [2, 3, 4, 5, 14]:
            return True
        
        return False

    @staticmethod
    def _compare_hands(rank1: HandRank, values1: List[int], 
                       rank2: HandRank, values2: List[int]) -> int:
        """Compare two hands. Returns 1 if hand1 wins, -1 if hand2 wins, 0 if tie."""
        rank_order = [
            HandRank.HIGH_CARD, HandRank.PAIR, HandRank.TWO_PAIR,
            HandRank.THREE_OF_A_KIND, HandRank.STRAIGHT, HandRank.FLUSH,
            HandRank.FULL_HOUSE, HandRank.FOUR_OF_A_KIND,
            HandRank.STRAIGHT_FLUSH, HandRank.ROYAL_FLUSH
        ]
        
        idx1 = rank_order.index(rank1)
        idx2 = rank_order.index(rank2)
        
        if idx1 > idx2:
            return 1
        elif idx1 < idx2:
            return -1
        
        # Same rank, compare values
        for v1, v2 in zip(values1, values2):
            if v1 > v2:
                return 1
            elif v1 < v2:
                return -1
        
        return 0


class PokerGame:
    """Manages poker game logic."""

    def __init__(self, game_id: str, small_blind: int = 10, big_blind: int = 20):
        self.game_state = GameState(
            game_id=game_id,
            small_blind=small_blind,
            big_blind=big_blind
        )
        self.deck = Deck()

    def add_player(self, wallet_address: str, chips: int = 1000) -> bool:
        """Add a player to the game."""
        if len(self.game_state.players) >= self.game_state.max_players:
            return False
        
        # Check if player already exists
        if any(p.wallet_address == wallet_address for p in self.game_state.players):
            return False

        position = len(self.game_state.players)
        player = Player(
            wallet_address=wallet_address,
            chips=chips,
            position=position
        )
        self.game_state.players.append(player)
        return True

    def remove_player(self, wallet_address: str) -> bool:
        """Remove a player from the game."""
        player = self._get_player(wallet_address)
        if not player:
            return False
        
        self.game_state.players = [
            p for p in self.game_state.players 
            if p.wallet_address != wallet_address
        ]
        return True

    def start_hand(self) -> bool:
        """Start a new hand."""
        if len(self.game_state.players) < self.game_state.min_players:
            return False

        # Reset for new hand
        self.deck.reset()
        self.game_state.community_cards = []
        self.game_state.pot = 0
        self.game_state.current_bet = 0
        self.game_state.stage = GameStage.PRE_FLOP

        # Reset players
        for player in self.game_state.players:
            player.cards = []
            player.current_bet = 0
            player.folded = False
            player.all_in = False

        # Deal hole cards
        for player in self.game_state.players:
            player.cards = self.deck.deal(2)

        # Post blinds
        self._post_blinds()
        
        # Set first player to act (after big blind)
        bb_position = (self.game_state.dealer_position + 2) % len(self.game_state.players)
        self.game_state.current_player_position = (bb_position + 1) % len(self.game_state.players)

        return True

    def _post_blinds(self):
        """Post small and big blinds."""
        players = self.game_state.players
        num_players = len(players)
        
        sb_position = (self.game_state.dealer_position + 1) % num_players
        bb_position = (self.game_state.dealer_position + 2) % num_players
        
        # Small blind
        sb_player = players[sb_position]
        sb_amount = min(self.game_state.small_blind, sb_player.chips)
        sb_player.chips -= sb_amount
        sb_player.current_bet = sb_amount
        self.game_state.pot += sb_amount
        
        # Big blind
        bb_player = players[bb_position]
        bb_amount = min(self.game_state.big_blind, bb_player.chips)
        bb_player.chips -= bb_amount
        bb_player.current_bet = bb_amount
        self.game_state.pot += bb_amount
        self.game_state.current_bet = bb_amount

    def process_action(self, wallet_address: str, action: PlayerAction, 
                      amount: Optional[int] = None) -> bool:
        """Process a player action."""
        player = self._get_player(wallet_address)
        if not player or player.folded or player.all_in:
            return False

        if player.position != self.game_state.current_player_position:
            return False

        if action == PlayerAction.FOLD:
            player.folded = True
        
        elif action == PlayerAction.CHECK:
            if player.current_bet < self.game_state.current_bet:
                return False
        
        elif action == PlayerAction.CALL:
            call_amount = self.game_state.current_bet - player.current_bet
            call_amount = min(call_amount, player.chips)
            player.chips -= call_amount
            player.current_bet += call_amount
            self.game_state.pot += call_amount
            if player.chips == 0:
                player.all_in = True
        
        elif action in [PlayerAction.BET, PlayerAction.RAISE]:
            if amount is None or amount <= 0:
                return False
            
            total_bet = player.current_bet + amount
            if total_bet <= self.game_state.current_bet:
                return False
            
            bet_amount = min(amount, player.chips)
            player.chips -= bet_amount
            player.current_bet += bet_amount
            self.game_state.pot += bet_amount
            self.game_state.current_bet = player.current_bet
            
            if player.chips == 0:
                player.all_in = True
        
        elif action == PlayerAction.ALL_IN:
            all_in_amount = player.chips
            player.chips = 0
            player.current_bet += all_in_amount
            self.game_state.pot += all_in_amount
            self.game_state.current_bet = max(
                self.game_state.current_bet, 
                player.current_bet
            )
            player.all_in = True

        # Move to next player
        self._advance_to_next_player()
        
        # Check if betting round is complete
        if self._is_betting_round_complete():
            self._advance_stage()

        return True

    def _advance_to_next_player(self):
        """Move to the next active player."""
        current = self.game_state.current_player_position
        if current is None:
            return
        
        num_players = len(self.game_state.players)
        next_position = (current + 1) % num_players
        
        # Find next active player
        checked = 0
        while checked < num_players:
            player = self.game_state.players[next_position]
            if not player.folded and not player.all_in:
                self.game_state.current_player_position = next_position
                return
            next_position = (next_position + 1) % num_players
            checked += 1
        
        # No active players to act
        self.game_state.current_player_position = None

    def _is_betting_round_complete(self) -> bool:
        """Check if the current betting round is complete."""
        active_players = [
            p for p in self.game_state.players 
            if not p.folded and not p.all_in
        ]
        
        if len(active_players) <= 1:
            return True
        
        # All active players have matched the current bet
        return all(
            p.current_bet == self.game_state.current_bet 
            for p in active_players
        )

    def _advance_stage(self):
        """Advance to the next game stage."""
        # Reset bets for next round
        for player in self.game_state.players:
            player.current_bet = 0
        self.game_state.current_bet = 0
        
        if self.game_state.stage == GameStage.PRE_FLOP:
            # Deal flop
            self.game_state.community_cards = self.deck.deal(3)
            self.game_state.stage = GameStage.FLOP
            self._set_first_player_for_round()
        
        elif self.game_state.stage == GameStage.FLOP:
            # Deal turn
            self.game_state.community_cards.extend(self.deck.deal(1))
            self.game_state.stage = GameStage.TURN
            self._set_first_player_for_round()
        
        elif self.game_state.stage == GameStage.TURN:
            # Deal river
            self.game_state.community_cards.extend(self.deck.deal(1))
            self.game_state.stage = GameStage.RIVER
            self._set_first_player_for_round()
        
        elif self.game_state.stage == GameStage.RIVER:
            # Showdown
            self.game_state.stage = GameStage.SHOWDOWN
            self._determine_winners()

    def _set_first_player_for_round(self):
        """Set the first player to act in a betting round."""
        # First player after dealer
        first_position = (self.game_state.dealer_position + 1) % len(self.game_state.players)
        
        # Find first active player
        for i in range(len(self.game_state.players)):
            position = (first_position + i) % len(self.game_state.players)
            player = self.game_state.players[position]
            if not player.folded and not player.all_in:
                self.game_state.current_player_position = position
                return
        
        self.game_state.current_player_position = None

    def _determine_winners(self):
        """Determine the winner(s) and distribute pot."""
        active_players = [p for p in self.game_state.players if not p.folded]
        
        if len(active_players) == 1:
            # Only one player left
            active_players[0].chips += self.game_state.pot
            self.game_state.pot = 0
            return

        # Evaluate hands
        player_hands = []
        for player in active_players:
            all_cards = player.cards + self.game_state.community_cards
            hand_rank, hand_values = HandEvaluator.evaluate_hand(all_cards)
            player_hands.append((player, hand_rank, hand_values))

        # Find best hand
        best_rank = HandRank.HIGH_CARD
        best_values = []
        
        for _, rank, values in player_hands:
            if HandEvaluator._compare_hands(rank, values, best_rank, best_values) > 0:
                best_rank = rank
                best_values = values

        # Find all winners (ties)
        winners = [
            player for player, rank, values in player_hands
            if rank == best_rank and values == best_values
        ]

        # Distribute pot
        share = self.game_state.pot // len(winners)
        for winner in winners:
            winner.chips += share
        
        self.game_state.pot = 0

    def _get_player(self, wallet_address: str) -> Optional[Player]:
        """Get player by wallet address."""
        for player in self.game_state.players:
            if player.wallet_address == wallet_address:
                return player
        return None

    def get_public_state(self, wallet_address: Optional[str] = None) -> dict:
        """Get public game state (hides other players' cards)."""
        state = self.game_state.model_dump()
        
        # Hide other players' cards
        for player in state['players']:
            if wallet_address and player['wallet_address'] == wallet_address:
                continue
            if self.game_state.stage != GameStage.SHOWDOWN:
                player['cards'] = []
        
        return state
