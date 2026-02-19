from functools import lru_cache
from typing import Any

from saq import Queue

from backend.config.settings import get_settings


@lru_cache
def get_queue() -> Queue:
    settings = get_settings()
    url = settings.saq_redis_url or settings.redis_url
    return Queue.from_url(url)


async def enqueue_task(name: str, **kwargs: Any) -> None:
    queue = get_queue()
    await queue.enqueue(name, **kwargs)