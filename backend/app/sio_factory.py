"""Socket.IO server factory."""

import socketio
from ..config.server_config import ALLOWED_ORIGINS
from ..config.arena_config import SOCKET_IO_LOGGER, SOCKET_ENGINEIO_LOGGER

def create_sio() -> socketio.AsyncServer:
    """Create and configure the Socket.IO server."""
    socketio_origins = '*' if '*' in ALLOWED_ORIGINS else ALLOWED_ORIGINS
    sio = socketio.AsyncServer(
        async_mode='asgi',
        cors_allowed_origins=socketio_origins,
        logger=SOCKET_IO_LOGGER,
        engineio_logger=SOCKET_ENGINEIO_LOGGER,
        ping_timeout=60,
        ping_interval=25
    )
    return sio
