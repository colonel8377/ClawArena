import json
from typing import Any

from backend.repositories.redis_client import get_client
from backend.config.constants import RoomState
from backend.config.settings import get_settings


class RedisRepo:
    @staticmethod
    async def set_json(key: str, payload: Any, ttl_seconds: int | None = None) -> None:
        client = get_client()
        if ttl_seconds is not None:
            await client.setex(key, ttl_seconds, json.dumps(payload))
        else:
            await client.set(key, json.dumps(payload))

    @staticmethod
    async def get_json(key: str) -> Any | None:
        client = get_client()
        raw = await client.get(key)
        return json.loads(raw) if raw else None

    @staticmethod
    async def add_system_event(event_id: str, payload: dict) -> None:
        client = get_client()
        await client.xadd("system:events", {"event_id": event_id, "payload": json.dumps(payload)})

    @staticmethod
    async def add_game_event(room_id: int, event_id: str, event_type: str, payload: dict, ts_ms: int) -> None:
        client = get_client()
        await client.xadd(
            f"game:events:{room_id}",
            {
                "event_id": event_id,
                "event_type": event_type,
                "ts": ts_ms,
                "payload": json.dumps(payload),
            },
        )

    @staticmethod
    async def set_game_state(room_id: int, state: dict) -> None:
        await RedisRepo.set_json(f"game:state:{room_id}", state)

    @staticmethod
    async def get_game_state(room_id: int) -> dict | None:
        return await RedisRepo.get_json(f"game:state:{room_id}")

    @staticmethod
    async def set_game_public_state(room_id: int, state: dict) -> None:
        await RedisRepo.set_json(f"game:state:public:{room_id}", state)

    @staticmethod
    async def get_game_public_state(room_id: int) -> dict | None:
        return await RedisRepo.get_json(f"game:state:public:{room_id}")

    @staticmethod
    async def set_room_state(room_id: int, room_state: int) -> None:
        key = f"room:state:{room_id}"
        payload = {"room_state": room_state}
        if int(room_state) == int(RoomState.FINISHED):
            ttl_seconds = get_settings().room_state_ttl_seconds
            if ttl_seconds and ttl_seconds > 0:
                await RedisRepo.set_json(key, payload, ttl_seconds=ttl_seconds)
                return
        await RedisRepo.set_json(key, payload)

    @staticmethod
    async def get_room_state(room_id: int) -> int | None:
        data = await RedisRepo.get_json(f"room:state:{room_id}")
        if not data:
            return None
        value = data.get("room_state")
        return int(value) if value is not None else None

    @staticmethod
    async def add_active_room(room_id: int) -> None:
        client = get_client()
        await client.sadd("rooms:active", str(room_id))

    @staticmethod
    async def remove_active_room(room_id: int) -> None:
        client = get_client()
        await client.srem("rooms:active", str(room_id))

    @staticmethod
    async def get_active_rooms() -> list[int]:
        client = get_client()
        rooms = await client.smembers("rooms:active")
        return sorted(int(room_id) for room_id in rooms)
