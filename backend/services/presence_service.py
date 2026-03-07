import time

from backend.config.settings import get_settings
from backend.repositories.redis_client import get_client
from backend.repositories.redis_repo import RedisRepo


class PresenceService:
    TOUCH_TTL_SECONDS = 10

    @staticmethod
    async def mark_online(agent_id: int, room_id: int | None = None) -> None:
        settings = get_settings()
        payload = {
            "status": "online",
            "ts_ms": int(time.time() * 1000),
            "room_id": room_id,
        }
        await RedisRepo.set_json(
            f"presence:agent:{agent_id}",
            payload,
            ttl_seconds=settings.presence_ttl_seconds,
        )

    @staticmethod
    async def mark_offline(agent_id: int, room_id: int | None = None) -> None:
        settings = get_settings()
        payload = {
            "status": "offline",
            "ts_ms": int(time.time() * 1000),
            "room_id": room_id,
        }
        await RedisRepo.set_json(
            f"presence:agent:{agent_id}",
            payload,
            ttl_seconds=settings.presence_ttl_seconds,
        )

    @staticmethod
    async def touch(agent_id: int, room_id: int | None = None) -> None:
        throttle_key = f"presence:touch:{agent_id}"
        client = get_client()
        ok = await client.set(throttle_key, "1", nx=True, ex=PresenceService.TOUCH_TTL_SECONDS)
        if not ok:
            return
        await PresenceService.mark_online(agent_id, room_id=room_id)

    @staticmethod
    async def mark_left(agent_id: int, room_id: int | None = None) -> None:
        settings = get_settings()
        payload = {
            "status": "left",
            "ts_ms": int(time.time() * 1000),
            "room_id": room_id,
        }
        await RedisRepo.set_json(
            f"presence:agent:{agent_id}",
            payload,
            ttl_seconds=settings.presence_ttl_seconds,
        )

    @staticmethod
    async def get(agent_id: int) -> dict | None:
        return await RedisRepo.get_json(f"presence:agent:{agent_id}")
