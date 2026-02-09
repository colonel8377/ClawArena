"""Texas Hold'em configuration and helper accessors.

This module centralizes gameplay and matchmaking knobs so rule constants are
not duplicated across engine, table wrapper, and socket orchestration.
"""

from typing import Dict


# Table gameplay defaults
TEXAS_MIN_PLAYERS = 2
TEXAS_MAX_PLAYERS = 9
TEXAS_DEFAULT_SMALL_BLIND = 25
TEXAS_DEFAULT_BIG_BLIND = 50
TEXAS_TURN_TIMEOUT_SECONDS = 20


# Matchmaking defaults
TEXAS_MATCHMAKING_MIN_PLAYERS = TEXAS_MIN_PLAYERS
TEXAS_MATCHMAKING_PREFERRED_GAME_SIZE = 6
TEXAS_MATCHMAKING_FULL_RING_SIZE = TEXAS_MAX_PLAYERS
TEXAS_MATCHMAKING_ADAPTIVE_WAIT_TIME = 20.0
TEXAS_MATCHMAKING_CHECK_INTERVAL = 2.0


def get_default_blinds() -> Dict[str, int]:
    """Return the default blind structure."""
    return {
        'small_blind': TEXAS_DEFAULT_SMALL_BLIND,
        'big_blind': TEXAS_DEFAULT_BIG_BLIND,
    }


def get_table_limits() -> Dict[str, int]:
    """Return hard table limits for player count and turn timer."""
    return {
        'min_players': TEXAS_MIN_PLAYERS,
        'max_players': TEXAS_MAX_PLAYERS,
        'turn_timeout_seconds': TEXAS_TURN_TIMEOUT_SECONDS,
    }


def get_matchmaking_limits() -> Dict[str, float]:
    """Return Texas matchmaking thresholds."""
    return {
        'min_players': TEXAS_MATCHMAKING_MIN_PLAYERS,
        'preferred_game_size': TEXAS_MATCHMAKING_PREFERRED_GAME_SIZE,
        'full_ring_size': TEXAS_MATCHMAKING_FULL_RING_SIZE,
        'adaptive_wait_time': TEXAS_MATCHMAKING_ADAPTIVE_WAIT_TIME,
        'check_interval': TEXAS_MATCHMAKING_CHECK_INTERVAL,
    }