"""Service layer entrypoint exports."""

from backend.services.base import BaseService
from backend.services.game_service import GameService

__all__ = [
    "BaseService",
    "GameService",
]