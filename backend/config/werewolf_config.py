"""
Werewolf role configuration helpers.

This module provides role configuration for different player counts (6-9 players).
It implements balanced role distributions to support adaptive matchmaking.
"""

import random
from typing import List

from ..games.werewolf.roles import RoleType


# Static configuration dictionary defining roles for each player count
ROLE_CONFIGURATIONS = {
    6: [
        RoleType.WOLF,
        RoleType.WOLF,
        RoleType.SEER,
        RoleType.HUNTER,
        RoleType.VILLAGER,
        RoleType.VILLAGER,
    ],
    7: [
        RoleType.WOLF,
        RoleType.WOLF,
        RoleType.SEER,
        RoleType.HUNTER,
        RoleType.VILLAGER,
        RoleType.VILLAGER,
        RoleType.VILLAGER,
    ],
    8: [
        RoleType.WOLF,
        RoleType.WOLF,
        RoleType.SEER,
        RoleType.WITCH,
        RoleType.HUNTER,
        RoleType.VILLAGER,
        RoleType.VILLAGER,
        RoleType.VILLAGER,
    ],
    9: [
        RoleType.WOLF,
        RoleType.WOLF,
        RoleType.WOLF,
        RoleType.SEER,
        RoleType.WITCH,
        RoleType.HUNTER,
        RoleType.VILLAGER,
        RoleType.VILLAGER,
        RoleType.VILLAGER,
    ],
}


# Rule toggles (kept default-compatible with current behavior)
ALLOW_WITCH_DOUBLE_ACTION_SAME_NIGHT = False
MAX_CHAT_MESSAGE_LENGTH = 300


def get_setup(player_count: int) -> List[RoleType]:
    """
    Get the shuffled role list for a given player count.

    Args:
        player_count: Number of players in the game (6-9)

    Returns:
        List of RoleType enums, shuffled randomly

    Raises:
        ValueError: If player_count is not in the valid range (6-9)
    """
    if player_count not in ROLE_CONFIGURATIONS:
        raise ValueError(
            f"Invalid player count: {player_count}. "
            f"Must be between 6 and 9 (inclusive)."
        )

    # Get the role configuration for this player count
    roles = ROLE_CONFIGURATIONS[player_count].copy()

    # Shuffle the roles randomly
    random.shuffle(roles)

    return roles


def get_role_counts(player_count: int) -> dict:
    """
    Get the count of each role type for a given player count.

    Args:
        player_count: Number of players in the game (6-9)

    Returns:
        Dictionary mapping RoleType to count
    """
    if player_count not in ROLE_CONFIGURATIONS:
        raise ValueError(
            f"Invalid player count: {player_count}. "
            f"Must be between 6 and 9 (inclusive)."
        )

    roles = ROLE_CONFIGURATIONS[player_count]
    role_counts = {}

    for role in roles:
        role_counts[role] = role_counts.get(role, 0) + 1

    return role_counts


def allow_witch_double_action_same_night() -> bool:
    """Whether witch can use antidote and poison in the same night."""
    return ALLOW_WITCH_DOUBLE_ACTION_SAME_NIGHT


def get_max_chat_message_length() -> int:
    """Maximum accepted chat message length for werewolf text channels."""
    return MAX_CHAT_MESSAGE_LENGTH