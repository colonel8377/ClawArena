"""Texas Hold'em role and action definitions.

This module mirrors Werewolf's role-style organization by centralizing
Texas seat semantics and action/status enums used across the engine stack.
"""

from enum import Enum
from typing import Dict


class SeatRole(Enum):
    """Per-hand table roles in Texas Hold'em."""

    DEALER = "dealer"
    SMALL_BLIND = "small_blind"
    BIG_BLIND = "big_blind"


class PlayerAction(Enum):
    """Supported betting actions for a player turn."""

    FOLD = "fold"
    CHECK = "check"
    CALL = "call"
    RAISE = "raise"
    ALL_IN = "all_in"


class PlayerStatus(Enum):
    """Lifecycle status of a player within a hand."""

    ACTIVE = "active"
    FOLDED = "folded"
    ALL_IN = "all_in"
    SITTING_OUT = "sitting_out"


def get_seat_roles(dealer_sid: str, small_blind_sid: str, big_blind_sid: str) -> Dict[str, str]:
    """Build a reverse lookup map from seat sid to role label."""

    role_map: Dict[str, str] = {}
    if dealer_sid:
        role_map[dealer_sid] = SeatRole.DEALER.value
    if small_blind_sid:
        role_map[small_blind_sid] = SeatRole.SMALL_BLIND.value
    if big_blind_sid:
        role_map[big_blind_sid] = SeatRole.BIG_BLIND.value
    return role_map
