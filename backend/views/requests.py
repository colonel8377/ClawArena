from pydantic import BaseModel, Field

from backend.config.constants import RoomRole
from backend.config.constants import ChatChannel, WerewolfAction, TexasAction


class RegisterRequest(BaseModel):
    agent_name: str = Field(min_length=2, max_length=32)


class LoginRequest(BaseModel):
    agent_id: int = Field(ge=1)
    secret: str = Field(min_length=16, max_length=128)


class QueueJoinRequest(BaseModel):
    game_type: int = Field(ge=1, le=2)


class QueueLeaveRequest(BaseModel):
    game_type: int | None = Field(default=None, ge=1, le=2)


class RoomJoinRequest(BaseModel):
    room_id: int = Field(ge=1)
    role: RoomRole


class WerewolfActionRequest(BaseModel):
    room_id: int = Field(ge=1)
    action_id: str = Field(min_length=8, max_length=64)
    action: WerewolfAction
    payload: dict = Field(default_factory=dict)


class TexasActionRequest(BaseModel):
    room_id: int = Field(ge=1)
    action_id: str = Field(min_length=8, max_length=64)
    action: TexasAction
    payload: dict = Field(default_factory=dict)


class RoomChatRequest(BaseModel):
    room_id: int = Field(ge=1)
    channel: ChatChannel
    content: str = Field(min_length=1, max_length=200)
