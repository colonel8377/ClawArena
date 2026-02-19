from backend.repositories.kv_backend import KvBackend
from backend.repositories.redis_client import get_client


class RedisKvBackend(KvBackend):
    async def get(self, key: str) -> str | None:
        client = get_client()
        return await client.get(key)

    async def set(self, key: str, value: str, ttl_seconds: int | None = None) -> None:
        client = get_client()
        if ttl_seconds is not None:
            await client.setex(key, ttl_seconds, value)
        else:
            await client.set(key, value)

    async def delete(self, key: str) -> None:
        client = get_client()
        await client.delete(key)
