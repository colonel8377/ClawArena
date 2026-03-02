import json
from decimal import Decimal
from typing import Any

from backend.repositories.redis_client import get_client
from backend.config.constants import RoomState
from backend.config.settings import get_settings


class RedisRepo:
    TEXAS_TURN_DEADLINE_KEY = "texas:turn_deadline"

    @staticmethod
    def _json_default(value: Any):
        if isinstance(value, Decimal):
            return float(value)
        if isinstance(value, set):
            return list(value)
        raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")

    @staticmethod
    async def set_json(key: str, payload: Any, ttl_seconds: int | None = None) -> None:
        client = get_client()
        encoded = json.dumps(payload, default=RedisRepo._json_default)
        if ttl_seconds is not None:
            await client.setex(key, ttl_seconds, encoded)
        else:
            await client.set(key, encoded)

    @staticmethod
    async def get_json(key: str) -> Any | None:
        client = get_client()
        raw = await client.get(key)
        return json.loads(raw) if raw else None

    @staticmethod
    async def add_system_event(event_id: str, payload: dict) -> None:
        client = get_client()
        await client.xadd("system:events", {"event_id": event_id, "payload": json.dumps(payload, default=RedisRepo._json_default)})

    @staticmethod
    async def add_game_event(room_id: int, event_id: str, event_type: str, payload: dict, ts_ms: int) -> str:
        client = get_client()
        message_id = await client.xadd(
            f"game:events:{room_id}",
            {
                "event_id": event_id,
                "event_type": event_type,
                "ts": ts_ms,
                "payload": json.dumps(payload, default=RedisRepo._json_default),
            },
        )
        return str(message_id)

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

    @staticmethod
    async def set_texas_turn_deadline(room_id: int, deadline_ms: int) -> None:
        client = get_client()
        await client.zadd(RedisRepo.TEXAS_TURN_DEADLINE_KEY, {str(room_id): int(deadline_ms)})

    @staticmethod
    async def remove_texas_turn_deadline(room_id: int) -> None:
        client = get_client()
        await client.zrem(RedisRepo.TEXAS_TURN_DEADLINE_KEY, str(room_id))

    @staticmethod
    async def get_due_texas_rooms(now_ms: int, limit: int = 200) -> list[int]:
        client = get_client()
        raw = await client.zrangebyscore(
            RedisRepo.TEXAS_TURN_DEADLINE_KEY,
            min="-inf",
            max=int(now_ms),
            start=0,
            num=int(limit),
        )
        return [int(room_id) for room_id in raw]

    @staticmethod
    async def add_online_player(sid: str) -> None:
        client = get_client()
        await client.sadd("online:players", sid)

    @staticmethod
    async def add_online_spectator(sid: str) -> None:
        client = get_client()
        await client.sadd("online:spectators", sid)

    @staticmethod
    async def remove_online_sid(sid: str) -> None:
        client = get_client()
        await client.srem("online:players", sid)
        await client.srem("online:spectators", sid)

    @staticmethod
    async def get_online_counts() -> dict:
        client = get_client()
        players = await client.scard("online:players")
        spectators = await client.scard("online:spectators")
        return {
            "players": int(players or 0),
            "spectators": int(spectators or 0),
            "total": int((players or 0) + (spectators or 0)),
        }

    @staticmethod
    async def get_last_stream_id(stream: str) -> str | None:
        client = get_client()
        items = await client.xrevrange(stream, max="+", min="-", count=1)
        if not items:
            return None
        return str(items[0][0])

    @staticmethod
    async def set_hand_result_emitted(room_id: int, hand_index: int, ttl_seconds: int = 86400) -> bool:
        client = get_client()
        key = f"dedupe:tx:hand_result:{room_id}:{hand_index}"
        ok = await client.set(key, "1", ex=ttl_seconds, nx=True)
        return bool(ok)
