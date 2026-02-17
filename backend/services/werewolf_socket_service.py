"""Socket.IO Werewolf adapter that delegates to StateCoordinator."""


class WerewolfSocketService:
    def __init__(self, coordinator) -> None:
        self._coordinator = coordinator

    async def create_game(self, sid: str, payload) -> None:
        await self._coordinator.create_werewolf_game(sid, payload)

    async def join_game(self, sid: str, payload) -> None:
        await self._coordinator.join_werewolf_game(sid, payload)

    async def start_game(self, sid: str, payload) -> None:
        await self._coordinator.start_werewolf_game(sid, payload)

    async def process_action(self, sid: str, payload) -> None:
        await self._coordinator.werewolf_action(sid, payload)

    async def advance_phase(self, sid: str, payload) -> None:
        await self._coordinator.advance_werewolf_phase(sid, payload)

    async def get_state(self, sid: str, payload) -> None:
        await self._coordinator.get_werewolf_state(sid, payload)
