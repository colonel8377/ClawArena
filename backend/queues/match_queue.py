from backend.queues.redis_zset import RedisZSetQueue
from backend.repositories.redis_client import get_client


class MatchQueue(RedisZSetQueue):
    async def pop_min(self, key: str, count: int) -> list[tuple[int, int]]:
        client = get_client()
        items = await client.zpopmin(key, count)
        return [(int(member), int(score)) for member, score in items]

    async def peek_min_score(self, key: str) -> int | None:
        client = get_client()
        items = await client.zrange(key, 0, 0, withscores=True)
        if not items:
            return None
        return int(items[0][1])
