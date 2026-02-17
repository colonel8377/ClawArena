"""Socket.IO view models for common events."""

from typing import Optional

from pydantic import BaseModel


class JoinSpectateRequest(BaseModel):
    table_id: Optional[str] = None
    game_id: Optional[str] = None
    reveal: bool = False


class LeaveSpectateRequest(BaseModel):
    table_id: Optional[str] = None
    game_id: Optional[str] = None
