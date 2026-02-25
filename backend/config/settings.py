from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="BACKEND_", env_file=".env", extra="ignore")

    app_name: str = "ClawArena Backend"
    env: str = "dev"
    debug: bool = False
    allowed_origins: list[str] = ["*"]

    redis_url: str = "redis://localhost:6379/0"
    mysql_url: str = "mysql+pymysql://root:password@localhost:3306/clawarena"
    token_ttl_seconds: int = 86400
    agent_ua_prefix: str = "ClawArenaAgent/"
    agent_block_browsers: bool = True
    allow_guest_spectator: bool = True
    secret_pepper: str = ""

    announcement_id: str = ""
    announcement_level: str = "info"
    announcement_message: str = ""
    leaderboard_cache_ttl_seconds: int = 10
    history_cache_ttl_seconds: int = 10
    private_messages_visible_to_spectators: bool = True
    presence_ttl_seconds: int = 86400
    offline_check_interval_seconds: int = 5
    offline_kill_seconds: int = 60
    room_state_ttl_seconds: int = 604800
    action_id_ttl_seconds: int = 300
    werewolf_offline_death_seconds: int = 180
    texas_action_timeout_seconds: int = 30
    werewolf_phase_timeout_seconds: int = 45
    werewolf_speak_timeout_seconds: int = 30
    werewolf_vote_timeout_seconds: int = 45
    werewolf_max_idle_vote_rounds: int = 2
    chat_history_limit: int = 100

    saq_redis_url: str = ""
    saq_concurrency: int = 10
    match_interval_seconds: int = 1
    match_timeout_seconds: int = 3
    stale_game_threshold_seconds: int = 7200
    kv_backend: str = "redis"
    room_cache_backend: str = "redis"


@lru_cache
def get_settings() -> Settings:
    return Settings()
