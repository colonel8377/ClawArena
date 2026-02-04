"""Pydantic models for Arena Poker game engine."""

from enum import Enum
from typing import Optional, List
from pydantic import BaseModel, Field


class Suit(str, Enum):
    """Card suits."""
    HEARTS = "hearts"
    DIAMONDS = "diamonds"
    CLUBS = "clubs"
    SPADES = "spades"


class Rank(str, Enum):
    """Card ranks."""
    TWO = "2"
    THREE = "3"
    FOUR = "4"
    FIVE = "5"
    SIX = "6"
    SEVEN = "7"
    EIGHT = "8"
    NINE = "9"
    TEN = "10"
    JACK = "J"
    QUEEN = "Q"
    KING = "K"
    ACE = "A"


class Card(BaseModel):
    """Represents a playing card."""
    rank: Rank
    suit: Suit

    def __str__(self) -> str:
        return f"{self.rank.value}{self.suit.value[0].upper()}"


class HandRank(str, Enum):
    """Poker hand rankings."""
    HIGH_CARD = "high_card"
    PAIR = "pair"
    TWO_PAIR = "two_pair"
    THREE_OF_A_KIND = "three_of_a_kind"
    STRAIGHT = "straight"
    FLUSH = "flush"
    FULL_HOUSE = "full_house"
    FOUR_OF_A_KIND = "four_of_a_kind"
    STRAIGHT_FLUSH = "straight_flush"
    ROYAL_FLUSH = "royal_flush"


class PlayerAction(str, Enum):
    """Possible player actions."""
    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    RAISE = "raise"
    BET = "bet"
    ALL_IN = "all_in"


class GameStage(str, Enum):
    """Game stages in Texas Hold'em."""
    WAITING = "waiting"
    PRE_FLOP = "pre_flop"
    FLOP = "flop"
    TURN = "turn"
    RIVER = "river"
    SHOWDOWN = "showdown"
    ENDED = "ended"


class Player(BaseModel):
    """Represents a player in the game."""
    wallet_address: str = Field(..., description="Ethereum wallet address")
    chips: int = Field(default=1000, ge=0, description="Player's chip count")
    current_bet: int = Field(default=0, ge=0, description="Current bet in this round")
    folded: bool = Field(default=False, description="Whether player has folded")
    all_in: bool = Field(default=False, description="Whether player is all-in")
    cards: List[Card] = Field(default_factory=list, description="Player's hole cards")
    position: int = Field(..., description="Player's seat position")
    connected: bool = Field(default=True, description="Whether player is connected")

    class Config:
        use_enum_values = True


class GameState(BaseModel):
    """Represents the current state of a poker game."""
    game_id: str = Field(..., description="Unique game identifier")
    players: List[Player] = Field(default_factory=list, description="Players in the game")
    community_cards: List[Card] = Field(default_factory=list, description="Community cards")
    pot: int = Field(default=0, ge=0, description="Current pot size")
    current_bet: int = Field(default=0, ge=0, description="Current bet to match")
    stage: GameStage = Field(default=GameStage.WAITING, description="Current game stage")
    dealer_position: int = Field(default=0, description="Dealer button position")
    current_player_position: Optional[int] = Field(None, description="Position of player to act")
    small_blind: int = Field(default=10, description="Small blind amount")
    big_blind: int = Field(default=20, description="Big blind amount")
    min_players: int = Field(default=2, description="Minimum players to start")
    max_players: int = Field(default=9, description="Maximum players allowed")

    class Config:
        use_enum_values = True


class ActionRequest(BaseModel):
    """Player action request."""
    action: PlayerAction
    amount: Optional[int] = Field(None, ge=0, description="Bet/raise amount")
    wallet_address: str = Field(..., description="Player's wallet address")

    class Config:
        use_enum_values = True


class WithdrawalRequest(BaseModel):
    """Withdrawal request from player."""
    wallet_address: str = Field(..., description="Player's wallet address")
    amount: int = Field(..., gt=0, description="Amount to withdraw")


class WithdrawalPayload(BaseModel):
    """Signed withdrawal payload."""
    wallet_address: str
    amount: int
    nonce: int
    signature: str
    timestamp: int
