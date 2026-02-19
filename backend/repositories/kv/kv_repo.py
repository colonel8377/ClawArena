from backend.config.settings import get_settings
from backend.repositories.kv_backend import KvBackend
from backend.repositories.kv.redis_kv import RedisKvBackend
from backend.repositories.kv.dict_kv import DictKvBackend

_kv_backend: KvBackend | None = None


def _get_backend() -> KvBackend:
    global _kv_backend
    if _kv_backend is not None:
        return _kv_backend
    backend = get_settings().kv_backend
    if backend == "dict":
        _kv_backend = DictKvBackend()
    else:
        _kv_backend = RedisKvBackend()
    return _kv_backend


class KvRepo:
    @staticmethod
    def set_backend(backend: KvBackend) -> None:
        global _kv_backend
        _kv_backend = backend

    @staticmethod
    async def get(key: str) -> str | None:
        return await _get_backend().get(key)

    @staticmethod
    async def set(key: str, value: str, ttl_seconds: int | None = None) -> None:
        await _get_backend().set(key, value, ttl_seconds=ttl_seconds)

    @staticmethod
    async def delete(key: str) -> None:
        await _get_backend().delete(key)

    @staticmethod
    async def get_session_agent_id(token: str) -> str | None:
        if not token:
            return None
        return await KvRepo.get(f"session:{token}")

    @staticmethod
    async def set_session(token: str, agent_id: str, ttl_seconds: int) -> None:
        await KvRepo.set(f"session:{token}", agent_id, ttl_seconds=ttl_seconds)

    @staticmethod
    async def set_agent_room(agent_id: int, room_id: int) -> None:
        await KvRepo.set(f"agent:room:{agent_id}", str(room_id))

    @staticmethod
    async def get_agent_room(agent_id: int) -> int | None:
        value = await KvRepo.get(f"agent:room:{agent_id}")
        return int(value) if value else None

    @staticmethod
    async def clear_agent_room(agent_id: int) -> None:
        await KvRepo.delete(f"agent:room:{agent_id}")

    @staticmethod
    async def get_agent_queue(agent_id: int) -> int | None:
        value = await KvRepo.get(f"agent:queue:{agent_id}")
        return int(value) if value else None

    @staticmethod
    async def set_agent_queue(agent_id: int, game_type: int) -> None:
        await KvRepo.set(f"agent:queue:{agent_id}", str(game_type))

    @staticmethod
    async def clear_agent_queue(agent_id: int) -> None:
        await KvRepo.delete(f"agent:queue:{agent_id}")
