import json
from typing import Any

from backend.queue.base import QueueBase
from backend.repositories.redis_client import get_client


class RedisStreamQueue(QueueBase):
    async def add(self, key: str, member: str, score: int) -> None:
        client = get_client()
        await client.xadd(key, {"payload": member, "score": score})

    async def remove(self, key: str, member: str) -> None:
        client = get_client()
        await client.xdel(key, member)

    async def size(self, key: str) -> int:
        client = get_client()
        return int(await client.xlen(key))

    async def rank(self, key: str, member: str) -> int | None:
        return None

    async def publish(self, stream: str, payload: dict[str, Any]) -> str:
        client = get_client()
        message_id = await client.xadd(stream, {"payload": json.dumps(payload)})
        return str(message_id)

    async def read(self, stream: str, last_id: str, count: int = 10, block_ms: int = 0) -> list[tuple[str, dict[str, Any]]]:
        client = get_client()
        items = await client.xread({stream: last_id}, count=count, block=block_ms)
        if not items:
            return []
        result: list[tuple[str, dict[str, Any]]] = []
        for _, messages in items:
            for message_id, data in messages:
                parsed = dict(data)
                payload = parsed.get("payload")
                if payload is not None:
                    try:
                        parsed["payload"] = json.loads(payload)
                    except Exception:
                        parsed["payload"] = payload
                result.append((str(message_id), parsed))
        return result

    async def create_group(self, stream: str, group: str, start_id: str = "0-0") -> None:
        client = get_client()
        try:
            await client.xgroup_create(stream, group, id=start_id, mkstream=True)
        except Exception:
            return

    async def read_group(
        self,
        stream: str,
        group: str,
        consumer: str,
        count: int = 10,
        block_ms: int = 0,
    ) -> list[tuple[str, dict[str, Any]]]:
        client = get_client()
        items = await client.xreadgroup(group, consumer, {stream: ">"}, count=count, block=block_ms)
        if not items:
            return []
        result: list[tuple[str, dict[str, Any]]] = []
        for _, messages in items:
            for message_id, data in messages:
                parsed = dict(data)
                payload = parsed.get("payload")
                if payload is not None:
                    try:
                        parsed["payload"] = json.loads(payload)
                    except Exception:
                        parsed["payload"] = payload
                result.append((str(message_id), parsed))
        return result

    async def ack(self, stream: str, group: str, message_id: str) -> None:
        client = get_client()
        await client.xack(stream, group, message_id)
