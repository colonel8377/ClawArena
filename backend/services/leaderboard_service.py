from backend.config.settings import get_settings
from backend.repositories.leaderboard_repo import LeaderboardRepo
from backend.repositories.redis_repo import RedisRepo


class LeaderboardService:
    @staticmethod
    async def get_top_agents(limit: int) -> list[dict]:
        settings = get_settings()
        limit = max(1, min(limit, 100))
        cache_key = f"leaderboard:token:top:{limit}"

        cached = await RedisRepo.get_json(cache_key)
        if cached:
            return cached

        rows = LeaderboardRepo.top_by_token(limit)
        await RedisRepo.set_json(cache_key, rows, ttl_seconds=settings.leaderboard_cache_ttl_seconds)
        return rows
