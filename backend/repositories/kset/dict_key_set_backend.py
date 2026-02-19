from backend.repositories.kset.key_set import KeySetBackend


class DictKeySetBackend(KeySetBackend):
    def __init__(self) -> None:
        self._sets: dict[str, set[str]] = {}

    async def add(self, key: str, member: str) -> None:
        self._sets.setdefault(key, set()).add(member)

    async def remove(self, key: str, member: str) -> None:
        if key in self._sets:
            self._sets[key].discard(member)

    async def members(self, key: str) -> list[str]:
        return sorted(self._sets.get(key, set()))
