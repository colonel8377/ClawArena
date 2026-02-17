"""Socket.IO view models for matchmaking events."""

from typing import Optional

from pydantic import BaseModel


class JoinTexasMatchmakingRequest(BaseModel):
    pass


class LeaveTexasMatchmakingRequest(BaseModel):
    pass


class GetTexasMatchmakingStatusRequest(BaseModel):
    pass


class JoinWerewolfMatchmakingRequest(BaseModel):
    nickname: Optional[str] = None

class LeaveWerewolfMatchmakingRequest(BaseModel):
    pass


class GetMatchmakingStatusRequest(BaseModel):
    pass
