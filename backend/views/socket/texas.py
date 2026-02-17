"""Socket.IO view models for Texas events."""

from typing import Optional

from pydantic import BaseModel


class StartHandRequest(BaseModel):
    table_id: Optional[str] = None


class PlayerMoveRequest(BaseModel):
    table_id: Optional[str] = None
    action: Optional[str] = None
    amount: Optional[int] = 0
    message: Optional[str] = None


class GetStateRequest(BaseModel):
    table_id: Optional[str] = None


class LeaveGameRequest(BaseModel):
    table_id: Optional[str] = None
