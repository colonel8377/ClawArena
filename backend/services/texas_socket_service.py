"""Socket.IO Texas adapter that delegates to StateCoordinator."""


class TexasSocketService:
    def __init__(self, coordinator) -> None:
        self._coordinator = coordinator

    async def start_hand(self, sid: str, payload) -> None:
        await self._coordinator.start_texas_hand(sid, payload)

    async def player_move(self, sid: str, payload) -> None:
        await self._coordinator.texas_player_move(sid, payload)

    async def get_state(self, sid: str, payload) -> None:
        await self._coordinator.get_texas_state(sid, payload)

    async def leave_game(self, sid: str, payload) -> None:
        await self._coordinator.leave_texas_game(sid, payload)
