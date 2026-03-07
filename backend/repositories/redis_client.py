from functools import lru_cache

from redis.asyncio import Redis

from backend.config.settings import get_settings


@lru_cache
def get_client() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.redis_url, decode_responses=True)
