from backend.repositories.game_repo import GameRepo
from backend.repositories.redis_repo import RedisRepo
from backend.repositories.room_repo import RoomRepo
from backend.repositories.kset.room_repo import RoomCache


class RoomDirectoryService:
    @staticmethod
    async def list_active(limit: int = 50) -> dict:
        room_ids = await RedisRepo.get_active_rooms()
        if limit > 0:
            room_ids = room_ids[:limit]

        items: list[dict] = []
        for room_id in room_ids:
            room = RoomRepo.get_by_id(int(room_id))
            game_state = await RedisRepo.get_game_state(int(room_id)) or {}
            room_state = await RedisRepo.get_room_state(int(room_id))
            members_count = await RoomCache.count_room_members(int(room_id))
            spectators_count = await RoomCache.count_room_spectators(int(room_id))
            state_view = (game_state.get("state") or {}) if isinstance(game_state, dict) else {}
            eligible_players = state_view.get("eligible_players")
            alive_players = state_view.get("alive")
            if isinstance(eligible_players, list) and len(eligible_players) > 0:
                members_count = len(eligible_players)
            elif isinstance(alive_players, list) and len(alive_players) > 0:
                members_count = len(alive_players)
            if room and room.max_players is not None:
                try:
                    members_count = min(int(members_count), int(room.max_players))
                except (TypeError, ValueError):
                    pass

            game_id = game_state.get("game_id") or (room.game_id if room else None)
            game_type = game_state.get("game_type")
            if game_type is None and game_id:
                game = GameRepo.get_by_id(int(game_id))
                game_type = int(game.game_type) if game else None

            items.append(
                {
                    "room_id": int(room_id),
                    "game_id": int(game_id) if game_id is not None else None,
                    "game_type": int(game_type) if game_type is not None else None,
                    "phase": game_state.get("phase"),
                    "room_state": int(room_state) if room_state is not None else None,
                    "members_count": int(members_count),
                    "spectators_count": int(spectators_count),
                }
            )

        return {"items": items}
