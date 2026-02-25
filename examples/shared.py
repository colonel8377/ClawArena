import asyncio
import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Callable, Dict, Optional

import httpx
import socketio

BASE_URL = os.getenv("CLAW_BASE_URL", "http://localhost:8080")
SOCKET_URL = os.getenv("CLAW_SOCKET_URL", BASE_URL)
USER_AGENT = os.getenv("CLAW_AGENT_UA", "ClawArenaAgent/Examples")
UA_PREFIX = os.getenv("CLAW_AGENT_UA_PREFIX", "ClawArenaAgent/")
if not USER_AGENT.startswith(UA_PREFIX):
    raise RuntimeError(
        f"Invalid User-Agent: must start with '{UA_PREFIX}'. "
        "Set CLAW_AGENT_UA or CLAW_AGENT_UA_PREFIX."
    )
TIMEOUT = float(os.getenv("CLAW_TIMEOUT", "10"))
ALLOW_GUEST_SPECTATOR = os.getenv("CLAW_ALLOW_GUEST_SPECTATOR", "true").lower() in ("1", "true", "yes")

PLAYERS_FILE = os.path.join(os.path.dirname(__file__), "players.json")


class ApiError(RuntimeError):
    pass


def _load_players() -> Dict[str, Dict[str, Any]]:
    if not os.path.exists(PLAYERS_FILE):
        return {}
    with open(PLAYERS_FILE, "r", encoding="utf-8") as f:
        return json.load(f)


def _save_players(data: Dict[str, Dict[str, Any]]) -> None:
    with open(PLAYERS_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, sort_keys=True)


def _unwrap(payload: Dict[str, Any]) -> Dict[str, Any]:
    if isinstance(payload, dict) and "ok" in payload:
        return payload
    raise ApiError(f"Unexpected payload: {payload}")


def _ok_data(payload: Dict[str, Any]) -> Dict[str, Any]:
    envelope = _unwrap(payload)
    if not envelope.get("ok"):
        raise ApiError(f"API error {envelope.get('code')}: {envelope.get('message')}")
    return envelope.get("data") or {}


def _err(payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if isinstance(payload, dict) and payload.get("ok") is False:
        return payload
    return None


@dataclass
class Player:
    name: str
    agent_id: Optional[int] = None
    secret: Optional[str] = None
    token: Optional[str] = None
    socket: Optional[socketio.AsyncClient] = None
    room_id: Optional[int] = None
    role: int = 1

    def label(self) -> str:
        if self.agent_id:
            return f"{self.name}#{self.agent_id}"
        return self.name

    async def register_or_login(self) -> None:
        players = _load_players()
        if self.name in players:
            self.agent_id = int(players[self.name]["agent_id"])
            self.secret = players[self.name]["secret"]
            await self.login()
            return

        data = await http_post("/api/register", {"agent_name": self.name})
        if data.get("ok"):
            body = data.get("data") or {}
            self.agent_id = int(body["agent_id"])
            self.secret = body["secret"]
            players[self.name] = {"agent_id": self.agent_id, "secret": self.secret}
            _save_players(players)
            self.token = body.get("token")
            _log(self, f"register reward_granted={body.get('reward_granted')} amount={body.get('reward_amount')}")
            return

        if data.get("code") == 40002 and self.name in players:
            self.agent_id = int(players[self.name]["agent_id"])
            self.secret = players[self.name]["secret"]
            await self.login()
            return

        raise ApiError(f"register failed: {data}")

    async def login(self) -> None:
        if not self.agent_id or not self.secret:
            raise ApiError("missing agent_id/secret for login")
        data = await http_post("/api/login", {"agent_id": self.agent_id, "secret": self.secret})
        if not data.get("ok"):
            raise ApiError(f"login failed: {data}")
        body = data.get("data") or {}
        self.token = body.get("token")
        _log(self, f"login reward_granted={body.get('reward_granted')} amount={body.get('reward_amount')}")

    async def wallet(self) -> Dict[str, Any]:
        if not self.token:
            raise ApiError("missing token")
        data = await http_get("/api/wallet", self.token)
        if not data.get("ok"):
            raise ApiError(f"wallet failed: {data}")
        return data.get("data") or {}

    async def connect(self) -> None:
        if not self.token and not (self.role == 2 and ALLOW_GUEST_SPECTATOR):
            raise ApiError("missing token")
        if self.socket and self.socket.connected:
            return
        self.init_socket()
        auth: Dict[str, Any] = {"role": self.role, "agent_name": self.name}
        if self.token:
            auth["token"] = self.token
        await self.socket.connect(
            SOCKET_URL,
            auth=auth,
            headers={"User-Agent": USER_AGENT},
            socketio_path="/socket.io",
        )

    def init_socket(self) -> None:
        if self.socket is None:
            self.socket = socketio.AsyncClient(reconnection=False)

    async def disconnect(self) -> None:
        if self.socket and self.socket.connected:
            await self.socket.disconnect()

    async def reconnect(self) -> None:
        await self.disconnect()
        await asyncio.sleep(0.2)
        await self.connect()

    async def call(self, event: str, payload: Dict[str, Any], timeout: float = TIMEOUT) -> Dict[str, Any]:
        if not self.socket:
            raise ApiError("socket not connected")
        return await self.socket.call(event, payload, timeout=timeout)


async def http_post(path: str, payload: Dict[str, Any], token: Optional[str] = None) -> Dict[str, Any]:
    headers = {"Content-Type": "application/json", "User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=TIMEOUT) as client:
        resp = await client.post(path, json=payload)
        print(resp.text)
        return resp.json()


async def http_get(path: str, token: Optional[str] = None) -> Dict[str, Any]:
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    async with httpx.AsyncClient(base_url=BASE_URL, headers=headers, timeout=TIMEOUT) as client:
        resp = await client.get(path)
        return resp.json()


def new_action_id() -> str:
    return str(uuid.uuid4())


def _log(player: Player, msg: str) -> None:
    print(f"[{player.label()}] {msg}")


def log_system(msg: str) -> None:
    print(f"[system] {msg}")


EventHandler = Callable[[Player, Dict[str, Any]], Any]


def attach_basic_handlers(player: Player) -> None:
    if not player.socket:
        return

    @player.socket.on("system:connected")
    async def _on_connected(payload):
        data = _ok_data(payload)
        _log(player, f"socket connected reward_granted={data.get('reward_granted')} amount={data.get('reward_amount')}")

    @player.socket.on("system:error")
    async def _on_error(payload):
        _log(player, f"system:error {payload}")
