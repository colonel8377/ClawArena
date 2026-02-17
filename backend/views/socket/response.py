"""Socket.IO response helpers."""

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class SocketResponse:
    event: str
    payload: Dict[str, Any]


async def emit_response(sio, response: SocketResponse, room: str) -> None:
    """Emit a standardized Socket.IO response."""
    await sio.emit(response.event, response.payload, room=room)
