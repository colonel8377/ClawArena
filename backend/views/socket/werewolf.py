"""Socket.IO view models for Werewolf events."""

from decimal import Decimal
from typing import Optional

from pydantic import BaseModel


class CreateWerewolfGameRequest(BaseModel):
    game_id: Optional[str] = None
    entry_fee: Decimal = Decimal("0")


class JoinWerewolfGameRequest(BaseModel):
    game_id: Optional[str] = None


class StartWerewolfGameRequest(BaseModel):
    game_id: Optional[str] = None


class WerewolfActionRequest(BaseModel):
    game_id: Optional[str] = None
    action: Optional[str] = None
    target_sid: Optional[str] = None
    message: Optional[str] = None


class AdvanceWerewolfPhaseRequest(BaseModel):
    game_id: Optional[str] = None


class GetWerewolfStateRequest(BaseModel):
    game_id: Optional[str] = None
    reveal: bool = False
