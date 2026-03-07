from backend.config.settings import get_settings
from backend.repositories.kset.dict_key_set_backend import DictKeySetBackend
from backend.repositories.kset.key_set import KeySetBackend
from backend.repositories.kset.redis_key_set_backend import RedisKeySetBackend

_room_cache_backend: KeySetBackend | None = None
_room_members_key = "room:members:{}"
_room_spectators_key = "room:spectators:{}"

def _get_backend() -> KeySetBackend:
    global _room_cache_backend
    if _room_cache_backend is not None:
        return _room_cache_backend
    backend = get_settings().room_cache_backend
    if backend == "dict":
        _room_cache_backend = DictKeySetBackend()
    else:
        _room_cache_backend = RedisKeySetBackend()
    return _room_cache_backend


class RoomCache:
    @staticmethod
    def set_backend(backend: KeySetBackend) -> None:
        global _room_cache_backend
        _room_cache_backend = backend

    @staticmethod
    async def add_room_member(room_id: int, agent_id: int) -> None:
        await _get_backend().add(_room_members_key.format(room_id), str(agent_id))
    @staticmethod
    async def remove_room_member(room_id: int, agent_id: int) -> None:
        await _get_backend().remove(_room_members_key.format(room_id), str(agent_id))

    @staticmethod
    async def add_room_spectator(room_id: int, agent_id: int) -> None:
        await _get_backend().add(_room_spectators_key.format(room_id), str(agent_id))

    @staticmethod
    async def remove_room_spectator(room_id: int, agent_id: int) -> None:
        await _get_backend().remove(_room_spectators_key.format(room_id), str(agent_id))

    @staticmethod
    async def count_room_members(room_id: int) -> int:
        members = await _get_backend().members(_room_members_key.format(room_id))
        return len(members)

    @staticmethod
    async def count_room_spectators(room_id: int) -> int:
        spectators = await _get_backend().members(_room_spectators_key.format(room_id))
        return len(spectators)

    @staticmethod
    async def get_room_members(room_id: int) -> list[int]:
        members = await _get_backend().members(_room_members_key.format(room_id))
        return sorted(int(m) for m in members)

    @staticmethod
    async def get_room_spectators(room_id: int) -> list[int]:
        spectators = await _get_backend().members(_room_spectators_key.format(room_id))
        return sorted(int(s) for s in spectators)

    @staticmethod
    async def is_room_member(room_id: int, agent_id: int) -> bool:
        members = await _get_backend().members(_room_members_key.format(room_id))
        return str(agent_id) in members

    @staticmethod
    async def is_room_spectator(room_id: int, agent_id: int) -> bool:
        spectators = await _get_backend().members(_room_spectators_key.format(room_id))
        return str(agent_id) in spectators
