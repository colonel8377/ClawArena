import time
from typing import Optional

from backend.repositories.kv.kv_backend import KvBackend


class DictKvBackend(KvBackend):
    def __init__(self) -> None:
        self.store: dict[str, tuple[str, Optional[float]]] = {}

    async def get(self, key: str) -> str | None:
        if key not in self.store:
            return None
        value, expiry = self.store[key]
        if expiry is None or time.time() < expiry:
            return value
        await self.delete(key)
        return None

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        expiry = time.time() + ttl_seconds if ttl_seconds is not None else None
        self.store[key] = (value, expiry)

    async def delete(self, key: str) -> None:
        self.store.pop(key, None)
