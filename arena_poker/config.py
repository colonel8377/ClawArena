"""Configuration for Arena Poker."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Application settings."""
    
    # Server settings
    HOST: str = "0.0.0.0"
    PORT: int = 8000
    
    # Game settings
    DEFAULT_SMALL_BLIND: int = 10
    DEFAULT_BIG_BLIND: int = 20
    DEFAULT_STARTING_CHIPS: int = 1000
    MIN_PLAYERS: int = 2
    MAX_PLAYERS: int = 9
    
    # SIWE settings
    SIWE_DOMAIN: str = "arenapoker.game"
    
    # Blockchain settings
    CHAIN_ID: int = 1
    
    # Server private key for signing withdrawals
    # In production, load this from secure environment variable
    SERVER_PRIVATE_KEY: str = "0x0000000000000000000000000000000000000000000000000000000000000001"
    
    # CORS settings
    CORS_ORIGINS: list = ["*"]  # In production, restrict to specific origins
    
    class Config:
        env_file = ".env"
        case_sensitive = True


settings = Settings()

