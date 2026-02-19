from backend.repositories.kset.key_set import KeySetBackend
from backend.repositories.redis_client import get_client



class RedisKeySetBackend(KeySetBackend):
    async def add(self, key: str, member: str) -> None:
        client = get_client()
        await client.sadd(key, member)

    async def remove(self, key: str, member: str) -> None:
        client = get_client()
        await client.srem(key, member)

    async def members(self, key: str) -> list[str]:
        client = get_client()
        members = await client.smembers(key)
        return [str(m) for m in members]
