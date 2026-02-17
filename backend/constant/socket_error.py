"""Socket.IO error definitions and helpers."""

from dataclasses import dataclass
from typing import Any, Dict, Optional

from backend.views.socket.response import SocketResponse


@dataclass(frozen=True)
class SocketErrorPayload:
    message: str
    error_code: Optional[str] = None


class SocketError(Exception):
    """Structured Socket.IO error with optional error code."""

    def __init__(self, message: str, error_code: Optional[str] = None) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code

    def to_response(self) -> SocketResponse:
        return SocketResponse("error", error_payload(self.message, self.error_code))


def error_payload(message: str, error_code: Optional[str] = None) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"message": message}
    if error_code:
        payload["error_code"] = error_code
    return payload


def error_response(message: str, error_code: Optional[str] = None) -> SocketResponse:
    return SocketResponse("error", error_payload(message, error_code))


async def emit_error(sio, message: str, room: str, error_code: Optional[str] = None) -> None:
    """Emit a standardized Socket.IO error event."""
    await sio.emit("error", error_payload(message, error_code), room=room)
