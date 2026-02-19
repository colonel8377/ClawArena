from abc import ABC, abstractmethod


class KeySetBackend(ABC):
    @abstractmethod
    async def add(self, key: str, member: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def remove(self, key: str, member: str) -> None:
        raise NotImplementedError

    @abstractmethod
    async def members(self, key: str) -> list[str]:
        raise NotImplementedError
