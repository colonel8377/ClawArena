import json

from backend.config.settings import get_settings
from backend.repositories.agent_repo import AgentRepo
from backend.repositories.game_player_repo import GamePlayerRepo
from backend.repositories.kv.kv_repo import KvRepo


class HistoryService:
    @staticmethod
    def list_history(agent_id: int, limit: int, offset: int) -> dict:
        items = GamePlayerRepo.list_history(agent_id, limit, offset)
        return {"items": items, "limit": limit, "offset": offset}

    @staticmethod
    async def summary(agent_id: int) -> dict:
        cache_key = f"history:summary:{agent_id}"
        cached = await KvRepo.get(cache_key)
        if cached:
            try:
                return json.loads(cached)
            except Exception:
                pass

        agent = AgentRepo.get_by_id(agent_id)
        agent_name = agent.agent_name if agent else f"agent_{agent_id}"
        stats = GamePlayerRepo.get_stats(agent_id)
        wins = int(stats.get("wins", 0))
        losses = int(stats.get("losses", 0))
        games_played = wins + losses
        win_rate = round((wins / games_played), 4) if games_played > 0 else 0
        recent = GamePlayerRepo.list_recent(agent_id, 5)

        payload = {
            "agent_id": agent_id,
            "agent_name": agent_name,
            "win_rate": win_rate,
            "wins": wins,
            "losses": losses,
            "games_played": games_played,
            "recent": recent,
        }
        ttl_seconds = int(get_settings().history_cache_ttl_seconds)
        if ttl_seconds > 0:
            await KvRepo.set(cache_key, json.dumps(payload, ensure_ascii=True), ttl_seconds=ttl_seconds)
        return payload
