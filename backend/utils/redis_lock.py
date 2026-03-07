import secrets
from typing import Optional

from backend.utils.log import get_logger
from backend.repositories.redis_client import get_client


_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
else
  return 0
end
"""


class RedisLock:
    def __init__(self, key: str, ttl_ms: int = 5000) -> None:
        self.key = key
        self.ttl_ms = ttl_ms
        self.token: Optional[str] = None
        self.acquired: bool = False

    async def acquire(self) -> bool:
        logger.info("try RedisLock key=%s ttl_ms=%s", self.key, self.ttl_ms)
        if self.acquired:
            return True
        self.token = secrets.token_urlsafe(16)
        client = get_client()
        self.acquired = bool(await client.set(self.key, self.token, nx=True, px=self.ttl_ms))
        if not self.acquired:
            self.token = None
        return self.acquired

    async def release(self) -> None:
        if not self.token or not self.acquired:
            return
        client = get_client()
        await client.eval(_RELEASE_SCRIPT, 1, self.key, self.token)
        self.acquired = False

    async def __aenter__(self) -> "RedisLock":
        await self.acquire()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.release()
logger = get_logger(__name__)
