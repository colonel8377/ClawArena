from backend.repositories.game_player_repo import GamePlayerRepo


class HistoryService:
    @staticmethod
    def list_history(agent_id: int, limit: int, offset: int) -> dict:
        items = GamePlayerRepo.list_history(agent_id, limit, offset)
        return {"items": items, "limit": limit, "offset": offset}
