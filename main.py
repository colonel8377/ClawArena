"""Main application entry point."""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import socketio

from arena_poker.api import app as api_app, get_game_manager
from arena_poker.sockets import PokerSocketServer


# Create Socket.IO server
game_manager = get_game_manager()
socket_server = PokerSocketServer(game_manager)

# Combine FastAPI and Socket.IO
app = FastAPI(
    title="Arena Poker Game Engine",
    description="Real-time poker game engine with FastAPI and Socket.IO",
    version="1.0.0"
)

# Mount the API app
app.mount("/api", api_app)

# Create combined ASGI app with Socket.IO
asgi_app = socketio.ASGIApp(
    socket_server.sio,
    other_asgi_app=app,
    socketio_path='/socket.io'
)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "main:asgi_app",
        host="0.0.0.0",
        port=8000,
        reload=True
    )
