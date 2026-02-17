from typing import List, Dict, Any, Optional
from pydantic import BaseModel, ConfigDict

class GameCounts(BaseModel):
    poker: int
    werewolf: int

class ActiveGamesResponse(BaseModel):
    poker_tables: List[str]
    werewolf_games: List[str]
    total: GameCounts

class ActiveWerewolfDebugResponse(BaseModel):
    game_id: str
    phase: str
    now_utc: str
    created_at_raw: Optional[str] = None
    started_at_raw: Optional[str] = None
    phase_start_raw: Optional[str] = None
    created_at_utc: Optional[str] = None
    started_at_utc: Optional[str] = None
    phase_start_utc: Optional[str] = None
    last_action_time_raw: Optional[Dict[str, Any]] = None
    last_activity_utc: Optional[str] = None
    filters: Dict[str, bool]
    would_be_hidden: bool

class TexasSpectateResponse(BaseModel):
    """Spectator view of a Texas Hold'em game."""
    model_config = ConfigDict(extra='allow')
    
    id: Optional[str] = None
    status: Optional[str] = None
    pot: Optional[float] = None
    community_cards: Optional[List[str]] = None
    players: Optional[List[Dict[str, Any]]] = None

class WerewolfSpectateResponse(BaseModel):
    """Spectator view of a Werewolf game."""
    model_config = ConfigDict(extra='allow')
    
    id: Optional[str] = None
    status: Optional[str] = None
    day: Optional[int] = None
    phase: Optional[str] = None
    players: Optional[List[Dict[str, Any]]] = None

class LeaderboardEntry(BaseModel):
    rank: int
    player_id: str
    player_name: str
    balance: str

class LeaderboardResponse(BaseModel):
    entries: List[LeaderboardEntry]
    total: int
    updated_at: str
