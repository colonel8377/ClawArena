from abc import ABC, abstractmethod
from typing import Any


class GameEngine(ABC):
    def __init__(self, game_id: int, room_id: int, players: list[dict[str, Any]], seed: int | None = None) -> None:
        self.game_id = game_id
        self.room_id = room_id
        self.players = players
        self.seed = seed

    @property
    @abstractmethod
    def phase(self) -> str:
        raise NotImplementedError

    @abstractmethod
    def get_state(self) -> dict[str, Any]:
        raise NotImplementedError

    @abstractmethod
    def validate_action(self, actor_id: int, action: str, payload: dict[str, Any]) -> None:
        raise NotImplementedError

    @abstractmethod
    def apply_action(self, actor_id: int, action: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def apply_leave(self, actor_id: int) -> list[dict[str, Any]]:
        raise NotImplementedError

    @abstractmethod
    def next_phase(self) -> str:
        raise NotImplementedError

    def snapshot(self) -> dict[str, Any]:
        return {
            "game_id": self.game_id,
            "room_id": self.room_id,
            "phase": self.phase,
            "state": self.get_state(),
        }
