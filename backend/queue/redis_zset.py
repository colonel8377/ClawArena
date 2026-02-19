from backend.queue.base import QueueBase
from backend.repositories.redis_client import get_client


class RedisZSetQueue(QueueBase):
    async def add(self, key: str, member: str, score: int) -> None:
        client = get_client()
        await client.zadd(key, {member: score})

    async def remove(self, key: str, member: str) -> None:
        client = get_client()
        await client.zrem(key, member)

    async def size(self, key: str) -> int:
        client = get_client()
        return int(await client.zcard(key))

    async def rank(self, key: str, member: str) -> int | None:
        client = get_client()
        rank = await client.zrank(key, member)
        return int(rank) if rank is not None else None
