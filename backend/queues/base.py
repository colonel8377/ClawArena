from abc import ABC, abstractmethod


class QueueBase(ABC):
    @abstractmethod
    async def add(self, key: str, member: str, score: int) -> None:
        raise NotImplementedError

    @abstractmethod
    async def remove(self, key: str, member: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def size(self, key: str) -> int:
        raise NotImplementedError

    @abstractmethod
    async def rank(self, key: str, member: str) -> int | None:
        raise NotImplementedError
