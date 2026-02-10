"""
Werewolf role configuration helpers.

This module provides role configuration for different player counts (6-9 players).
It implements balanced role distributions to support adaptive matchmaking.
"""

import random
from typing import List

# Avoid direct import here to prevent circular dependency
# from backend.games.werewolf.roles import RoleType (MOVED TO FUNCTION SCOPE)

# Static configuration dictionary defining roles for each player count
# We use strings initially or late import to avoid circular dependency loop:
# werewolf_game -> werewolf_config -> werewolf.roles -> (potentially) werewolf_game
#
# Actually, the cycle is:
# config/werewolf_config.py imports games/werewolf/roles.py
# games/werewolf/roles.py imports NOTHING critical
# BUT games/werewolf/werewolf_game.py imports config/werewolf_config.py
# AND games/werewolf/__init__.py imports werewolf_game
# AND config/__init__.py imports werewolf_config
#
# The error "partially initialized module" suggests roles.py might be importing something that loops back.
# Let's check roles.py. If roles.py is clean, then the loop might be elsewhere.
#
# However, to fix this immediately without deep diving into roles.py's imports (which we can't see right now),
# we can move the import inside the functions or use a TYPE_CHECKING block if it's just for typing.
# But here we need RoleType values for the dict.
#
# Wait, let's check the error again:
# ImportError: cannot import name 'allow_witch_double_action_same_night' from partially initialized module 'backend.config.werewolf_config'
# This means `werewolf_game.py` is trying to import `werewolf_config` BEFORE `werewolf_config` has finished initializing.
# This happens if `werewolf_config` imports something that eventually imports `werewolf_game`.
#
# `werewolf_config` imports `backend.games.werewolf.roles`.
# If `roles.py` imports `werewolf_game`, that's the cycle.
#
# Let's assume `roles.py` is fine.
# The issue might be that we are importing `RoleType` at the top level.
#
# SOLUTION: Move RoleType import inside the functions where it's used,
# OR define the config using strings/integers and map them later.
#
# But wait, ROLE_CONFIGURATIONS uses RoleType enum members directly.
#
# Let's try to break the cycle by NOT importing RoleType at top level if possible,
# or checking what roles.py imports.
#
# Since I cannot see roles.py in this turn, I will assume the cycle is:
# config -> roles -> ... -> config
#
# Actually, the error says `werewolf_game.py` line 19 imports `werewolf_config`.
# And `werewolf_config` line 11 imports `roles`.
# If `roles` imports `werewolf_game` (e.g. for type hinting), we have a cycle.
#
# FIX: Use local import in `werewolf_config.py` is hard because of the global dict.
# BETTER FIX: Ensure `roles.py` does NOT import `werewolf_game` or `config`.
#
# Since I can't edit `roles.py` blindly, I will modify `werewolf_config.py` to lazy import RoleType
# inside the functions, and change ROLE_CONFIGURATIONS to use raw values or strings if needed,
# OR better:
# The user wants to fix the import error.
#
# Let's look at `werewolf_config.py` again.
# It defines `ROLE_CONFIGURATIONS` constant. This needs `RoleType` at module level.
#
# If `roles.py` is indeed importing something causing a loop, we must break it.
#
# Strategy:
# 1. Modify `werewolf_config.py` to NOT import `RoleType` at top level.
# 2. Define `ROLE_CONFIGURATIONS` using string keys or integer values matching RoleType.
# 3. Convert them to RoleType inside `get_setup`.

from enum import Enum

class RoleTypeStub(str, Enum):
    WOLF = "wolf"
    VILLAGER = "villager"
    SEER = "seer"
    WITCH = "witch"
    HUNTER = "hunter"
    GUARD = "guard"
    IDIOT = "idiot"

# Static configuration using Stub/Strings to avoid import cycle
ROLE_CONFIGURATIONS = {
    6: [
        RoleTypeStub.WOLF,
        RoleTypeStub.WOLF,
        RoleTypeStub.SEER,
        RoleTypeStub.HUNTER,
        RoleTypeStub.VILLAGER,
        RoleTypeStub.VILLAGER,
    ],
    7: [
        RoleTypeStub.WOLF,
        RoleTypeStub.WOLF,
        RoleTypeStub.SEER,
        RoleTypeStub.HUNTER,
        RoleTypeStub.VILLAGER,
        RoleTypeStub.VILLAGER,
        RoleTypeStub.VILLAGER,
    ],
    8: [
        RoleTypeStub.WOLF,
        RoleTypeStub.WOLF,
        RoleTypeStub.SEER,
        RoleTypeStub.WITCH,
        RoleTypeStub.HUNTER,
        RoleTypeStub.VILLAGER,
        RoleTypeStub.VILLAGER,
        RoleTypeStub.VILLAGER,
    ],
    9: [
        RoleTypeStub.WOLF,
        RoleTypeStub.WOLF,
        RoleTypeStub.WOLF,
        RoleTypeStub.SEER,
        RoleTypeStub.WITCH,
        RoleTypeStub.HUNTER,
        RoleTypeStub.VILLAGER,
        RoleTypeStub.VILLAGER,
        RoleTypeStub.VILLAGER,
    ],
}


# Rule toggles (kept default-compatible with current behavior)
ALLOW_WITCH_DOUBLE_ACTION_SAME_NIGHT = False
MAX_CHAT_MESSAGE_LENGTH = 300


def get_setup(player_count: int) -> List:
    """
    Get the shuffled role list for a given player count.

    Args:
        player_count: Number of players in the game (6-9)

    Returns:
        List of RoleType enums, shuffled randomly

    Raises:
        ValueError: If player_count is not in the valid range (6-9)
    """
    # Lazy import to break circular dependency
    from backend.games.werewolf.roles import RoleType
    
    if player_count not in ROLE_CONFIGURATIONS:
        raise ValueError(
            f"Invalid player count: {player_count}. "
            f"Must be between 6 and 9 (inclusive)."
        )

    # Get the role configuration for this player count
    # Convert stubs/strings to actual RoleType enum
    stub_roles = ROLE_CONFIGURATIONS[player_count].copy()
    roles = [RoleType(r.value) for r in stub_roles]

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