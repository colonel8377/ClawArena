"""Werewolf game package initialization."""

# Legacy in-memory implementation (kept for compatibility)
from .game import WerewolfGame  # noqa: F401

# Production async engine with persistence
from .werewolf_engine import WerewolfEngine, make_async_session  # noqa: F401
from .models import GameSession, GamePlayer, ActionLog, PhaseEnum, RoleEnum  # noqa: F401
