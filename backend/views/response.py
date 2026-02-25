from decimal import Decimal, ROUND_HALF_UP
from typing import Any, Dict, Optional

from fastapi.encoders import jsonable_encoder
from pydantic import BaseModel, Field

from backend.config.constants import RoomRole
from backend.services.announcement_service import AnnouncementService
from backend.views.context import get_trace_id


class Announcement(BaseModel):
    id: str = ""
    level: str = "info"
    message: str = ""


class ApiResponse(BaseModel):
    ok: bool = True
    code: int = 0
    message: str = "ok"
    data: Dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""
    announcement: Optional[Announcement] = None


class ErrorResponse(BaseModel):
    ok: bool = False
    code: int
    message: str
    data: Dict[str, Any] = Field(default_factory=dict)
    trace_id: str = ""
    announcement: Optional[Announcement] = None


class QueueJoinResponse(BaseModel):
    status: str = Field(pattern="^(joined)$")
    game_type: int = Field(ge=1, le=2)
    queue_size: int = Field(ge=0)
    queue_rank: int | None = Field(default=None, ge=1)


class QueueLeaveResponse(BaseModel):
    status: str = Field(pattern="^(left)$")
    game_type: int | None = Field(default=None, ge=1, le=2)


class RoomJoinResponse(BaseModel):
    status: str = Field(pattern="^(joined)$")
    room_id: int = Field(ge=1)
    role: RoomRole
    role_label: str


class RoomLeaveResponse(BaseModel):
    status: str = Field(pattern="^(left)$")
    room_id: int | None = Field(default=None, ge=1)


class ConnectResponse(BaseModel):
    status: str = Field(pattern="^(connected)$")
    agent_id: int = Field(ge=1)
    reward_granted: bool
    reward_amount: int = Field(ge=0)


class RoomStatePayload(BaseModel):
    room_id: int = Field(ge=1)
    room_state: int | None = None
    game_state: Dict[str, Any] | None = None


class TexasSettlementPayload(BaseModel):
    game_id: int = Field(ge=1)
    room_id: int = Field(ge=1)
    prize_pool: Decimal = Field(ge=0)
    payouts: Dict[int, Decimal]
    stacks: Dict[int, int]
    busted_ids: list[int] | None = None


class RoomUpdatePayload(BaseModel):
    type: str = Field(pattern="^(room_join|room_leave|game_start|game_finish)$")
    room_id: int = Field(ge=1)
    agent_id: int | None = None
    role: int | None = None
    room_state: int | None = None
    members_count: int | None = None
    spectators_count: int | None = None
    ts_ms: int


_DISPLAY_SCALE = Decimal("0.01")


def _encode_payload(data: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    return jsonable_encoder(
        data or {},
        custom_encoder={Decimal: lambda v: float(v.quantize(_DISPLAY_SCALE, rounding=ROUND_HALF_UP))},
    )


def ok(
    data: Optional[Dict[str, Any]] = None,
    message: str = "ok",
    code: int = 0,
    trace_id: str = "",
    announcement: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    if not trace_id:
        trace_id = get_trace_id()
    data = _encode_payload(data)
    payload: Dict[str, Any] = {
        "ok": True,
        "code": code,
        "message": message,
        "data": data,
        "trace_id": trace_id,
    }
    current_announcement = announcement or AnnouncementService.get_current()
    if current_announcement:
        payload["announcement"] = current_announcement
    return payload


def fail(message: str, code: int, trace_id: str = "") -> Dict[str, Any]:
    if not trace_id:
        trace_id = get_trace_id()
    payload: Dict[str, Any] = {
        "ok": False,
        "code": code,
        "message": message,
        "data": {},
        "trace_id": trace_id,
    }
    current_announcement = AnnouncementService.get_current()
    if current_announcement:
        payload["announcement"] = current_announcement
    return payload
