from backend.config.constants import GameType
from backend.domain.texas.engine import TexasEngine
from backend.domain.werewolf.engine import WerewolfEngine
from backend.repositories.kset.room_repo import RoomCache
from backend.repositories.redis_repo import RedisRepo
from backend.repositories.room_repo import RoomRepo
from backend.services.timer_service import TimerService


class RoomStateService:
    @staticmethod
    async def get_state(room_id: int) -> dict:
        room_state = await RedisRepo.get_room_state(room_id)
        if room_state is None:
            room = RoomRepo.get_by_id(room_id)
            room_state = int(room.room_state) if room else None
        game_state = await RedisRepo.get_game_state(room_id)
        if game_state is not None:
            timers = TimerService.build(game_state)
            if timers:
                game_state["timers"] = timers
        return {"room_id": room_id, "room_state": room_state, "game_state": game_state}

    @staticmethod
    async def get_state_for_spectator(room_id: int) -> dict:
        payload = await RoomStateService.get_state(room_id)
        game_state = payload.get("game_state")
        if not game_state:
            return payload
        game_type = int(game_state.get("game_type") or 0)
        if game_type == int(GameType.TEXAS):
            engine = TexasEngine.from_state(game_state)
            reveal_state = engine.build_view_state(None, reveal_all=True)
            merged = dict(game_state)
            merged["state"] = reveal_state
            payload["game_state"] = merged
        return payload

    @staticmethod
    async def get_state_for_agent(room_id: int, agent_id: int | None) -> dict:
        payload = await RoomStateService.get_state(room_id)
        game_state = payload.get("game_state")
        if not game_state:
            return payload
        game_type = int(game_state.get("game_type") or 0)
        if agent_id is None:
            return payload
        is_member = await RoomCache.is_room_member(room_id, agent_id)
        if not is_member:
            return payload

        public_state = await RedisRepo.get_game_public_state(room_id)
        if not public_state:
            if game_type == int(GameType.TEXAS):
                public_state = TexasEngine.from_state(game_state).build_public_state()
            elif game_type == int(GameType.WEREWOLF):
                public_state = WerewolfEngine.from_state(game_state).build_public_state()

        timers = game_state.get("timers")
        if game_type == int(GameType.TEXAS):
            engine = TexasEngine.from_state(game_state)
            view_state = engine.build_view_state(agent_id, reveal_all=False)
            public_state = dict(public_state or {})
            public_state["state"] = view_state
        elif game_type == int(GameType.WEREWOLF):
            engine = WerewolfEngine.from_state(game_state)
            public_state = engine.build_view_state(agent_id, reveal_all=False)
        else:
            return payload

        if timers:
            public_state = dict(public_state or {})
            public_state["timers"] = timers
        payload["game_state"] = public_state
        return payload
