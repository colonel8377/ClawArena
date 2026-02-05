import os
import asyncio
import threading
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Dict, List, Optional, Tuple

import socketio
import uvicorn
import requests
import sys
import importlib

CURRENT_DIR = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.abspath(os.path.join(CURRENT_DIR, os.pardir, os.pardir))
if REPO_ROOT not in sys.path:
    sys.path.append(REPO_ROOT)
BACKEND_DIR = os.path.join(REPO_ROOT, "backend")
if BACKEND_DIR not in sys.path:
    sys.path.append(BACKEND_DIR)

# Ensure local debug mode so external services are skipped
os.environ.setdefault("LOCAL_DEBUG_MODE", "true")

# Load backend packages and alias to top-level names expected by main.py
backend_pkg = importlib.import_module("backend")
sys.modules["backend"] = backend_pkg

config_mod = importlib.import_module("backend.config")
sys.modules["config"] = config_mod

database_mod = importlib.import_module("backend.database")
sys.modules["database"] = database_mod
sys.modules["database.connection"] = importlib.import_module("backend.database.connection")
sys.modules["database.redis_manager"] = importlib.import_module("backend.database.redis_manager")
sys.modules["database.models"] = importlib.import_module("backend.database.models")

games_mod = importlib.import_module("backend.games")
sys.modules["games"] = games_mod
sys.modules["games.texas"] = importlib.import_module("backend.games.texas")
sys.modules["games.werewolf"] = importlib.import_module("backend.games.werewolf")
sys.modules["games.werewolf.werewolf_game"] = importlib.import_module("backend.games.werewolf.werewolf_game")

indexer_mod = importlib.import_module("backend.indexer")
sys.modules["indexer"] = indexer_mod
sys.modules["indexer.worker"] = importlib.import_module("backend.indexer.worker")

events_mod = importlib.import_module("backend.events")
sys.modules["events"] = events_mod

economy_mod = importlib.import_module("backend.economy")
sys.modules["economy"] = economy_mod
sys.modules["economy.account"] = importlib.import_module("backend.economy.account")

from backend import main  # noqa: E402  # Import after setting env


@dataclass
class InMemoryUser:
    wallet: str
    balance: Decimal = Decimal("1000")
    locked: Decimal = Decimal("0")
    last_login: Optional[str] = None


class InMemoryAccountStore:
    def __init__(self):
        self.users: Dict[str, InMemoryUser] = {}

    @staticmethod
    def _validate_wallet(wallet: str):
        if not wallet or len(wallet) != 42 or not wallet.startswith("0x"):
            raise ValueError("Invalid wallet address format")

    def register_user(self, wallet: str) -> Dict:
        self._validate_wallet(wallet)
        if wallet in self.users:
            user = self.users[wallet]
            return {
                "status": "already_registered",
                "user": {
                    "wallet_address": user.wallet,
                    "balance": float(user.balance),
                    "locked_balance": float(user.locked),
                    "created_at": user.last_login,
                },
            }

        user = InMemoryUser(wallet=wallet, balance=Decimal("1000000"))
        self.users[wallet] = user
        return {
            "status": "registered",
            "user": {
                "wallet_address": user.wallet,
                "balance": float(user.balance),
                "locked_balance": float(user.locked),
                "created_at": None,
            },
            "local_debug_mode": True,
        }

    def handle_login(self, wallet: str) -> Dict:
        self._validate_wallet(wallet)
        if wallet not in self.users:
            raise ValueError(f"User not found: {wallet}")
        user = self.users[wallet]
        user.balance = Decimal("1000000")
        return {
            "status": "success",
            "reward_granted": True,
            "reward_amount": float(user.balance),
            "local_debug_mode": True,
            "user": {
                "wallet_address": user.wallet,
                "balance": float(user.balance),
                "locked_balance": float(user.locked),
                "last_login_date": user.last_login,
            },
        }

    def add_balance(self, wallet: str, amount: Decimal) -> Dict:
        self._validate_wallet(wallet)
        if wallet not in self.users:
            raise ValueError(f"User not found: {wallet}")
        self.users[wallet].balance += amount
        return {
            "status": "success",
            "balance": float(self.users[wallet].balance),
        }

    def deduct_balance(self, wallet: str, amount: Decimal) -> Dict:
        self._validate_wallet(wallet)
        if wallet not in self.users:
            raise ValueError(f"User not found: {wallet}")
        if self.users[wallet].balance < amount:
            raise ValueError("Insufficient balance")
        self.users[wallet].balance -= amount
        return {
            "status": "success",
            "balance": float(self.users[wallet].balance),
        }

    def get_balance(self, wallet: str) -> Decimal:
        self._validate_wallet(wallet)
        if wallet not in self.users:
            raise ValueError(f"User not found: {wallet}")
        return self.users[wallet].balance


class DummyRedisLock:
    def __init__(self):
        self._lock = asyncio.Lock()

    async def __aenter__(self):
        await self._lock.acquire()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._lock.release()


class DummyRedisManager:
    def __init__(self):
        self.nonces: Dict[str, int] = {}

    async def connect(self):
        return True

    async def list_persisted_games(self):
        return []

    async def restore_game_state(self, game_id: str):
        return None

    async def delete_game_state(self, game_id: str):
        return None

    async def get_nonce(self, address: str) -> int:
        self.nonces[address] = self.nonces.get(address, 0) + 1
        return self.nonces[address]

    def lock(self, key: str):
        return DummyRedisLock()

    async def save_game_state(self, game_id: str, state, game_type: str = "texas"):
        return True


class DummyDepositWorker:
    async def run(self):
        return None

    def stop(self):
        return None


def patch_main_dependencies():
    account_store = InMemoryAccountStore()
    main.register_user = account_store.register_user
    main.handle_login = account_store.handle_login
    main.add_balance = account_store.add_balance
    main.deduct_balance = account_store.deduct_balance
    main.get_balance = account_store.get_balance
    main.redis_manager = DummyRedisManager()
    main.init_db = lambda retry=True: True
    main.deposit_worker = DummyDepositWorker()
    main.is_local_debug_mode = lambda: True
    main.LOCAL_DEBUG_MODE = True
    # Reset in-memory game state
    main.poker_tables.clear()
    main.werewolf_games.clear()
    main.player_sessions.clear()


async def wait_for_server(port: int, timeout: float = 5.0):
    deadline = asyncio.get_event_loop().time() + timeout
    while asyncio.get_event_loop().time() < deadline:
        try:
            resp = requests.get(f"http://127.0.0.1:{port}/health")
            if resp.status_code == 200:
                return
        except Exception:
            await asyncio.sleep(0.1)
            continue
        await asyncio.sleep(0.05)
    raise RuntimeError("Server did not start in time")


async def start_server(port: int = 8001) -> Tuple[uvicorn.Server, asyncio.Task]:
    config = uvicorn.Config(
        main.asgi_app,
        host="127.0.0.1",
        port=port,
        log_level="error",
        access_log=False,
    )
    server = uvicorn.Server(config)
    server_task = asyncio.create_task(server.serve())
    await wait_for_server(port)
    return server, server_task


class EventCatcher:
    def __init__(self):
        self.events: List[Tuple[str, Dict]] = []

    def handler(self, event: str):
        def _inner(data):
            self.events.append((event, data))

        return _inner

    def expect_event(self, name: str) -> Dict:
        for evt, payload in self.events:
            if evt == name:
                return payload
        raise AssertionError(f"Event {name} not received. Got: {self.events}")


async def run_http_edge_cases(base_url: str):
    with requests.Session() as session:
        bad_resp = await asyncio.to_thread(
            session.post,
            f"{base_url}/api/register",
            params={"wallet_address": "bad"},
        )
        assert bad_resp.status_code == 400

        missing_user = await asyncio.to_thread(
            session.post,
            f"{base_url}/api/login",
            params={"wallet_address": "0x" + "1" * 40},
        )
        assert missing_user.status_code == 404


async def run_texas_flow(base_url: str):
    wallet_a = "0x" + "a" * 40
    wallet_b = "0x" + "b" * 40
    with requests.Session() as session:
        await asyncio.to_thread(
            session.post, f"{base_url}/api/register", params={"wallet_address": wallet_a}
        )
        await asyncio.to_thread(
            session.post, f"{base_url}/api/register", params={"wallet_address": wallet_b}
        )
        await asyncio.to_thread(
            session.post, f"{base_url}/api/login", params={"wallet_address": wallet_a}
        )
        await asyncio.to_thread(
            session.post, f"{base_url}/api/login", params={"wallet_address": wallet_b}
        )

    anon_client = socketio.AsyncClient()
    anon_errors: List[Dict] = []
    anon_client.on("error", lambda data: anon_errors.append(data))
    await anon_client.connect(base_url, socketio_path="/socket.io")
    await anon_client.emit("join_game", {"table_id": "edge-table"})
    await asyncio.sleep(0.1)
    assert any("Not authenticated" in err.get("message", "") for err in anon_errors)
    await anon_client.disconnect()

    sio_a, sio_b = socketio.AsyncClient(), socketio.AsyncClient()
    catch_a, catch_b = EventCatcher(), EventCatcher()
    for evt in ["authenticated", "joined_game", "game_state", "error"]:
        sio_a.on(evt, catch_a.handler(evt))
        sio_b.on(evt, catch_b.handler(evt))

    await sio_a.connect(base_url, socketio_path="/socket.io", transports=["websocket"])
    await sio_b.connect(base_url, socketio_path="/socket.io", transports=["websocket"])

    await sio_a.emit("authenticate", {"address": wallet_a, "signature": "debug"})
    await sio_b.emit("authenticate", {"address": wallet_b, "signature": "debug"})
    await asyncio.sleep(0.1)
    catch_a.expect_event("authenticated")
    catch_b.expect_event("authenticated")

    await sio_a.emit("join_game", {"table_id": "table-1", "chips": 500})
    await sio_b.emit("join_game", {"table_id": "table-1", "chips": 500})
    await asyncio.sleep(0.2)
    catch_a.expect_event("joined_game")
    catch_b.expect_event("joined_game")

    await sio_a.emit("start_hand", {"table_id": "table-1"})
    await asyncio.sleep(0.2)
    await sio_a.emit("player_move", {"table_id": "table-1", "action": "chat", "message": "gl hf"})
    await asyncio.sleep(0.2)
    await sio_b.emit("player_move", {"table_id": "table-1", "action": "invalid"})
    await asyncio.sleep(0.2)
    assert any(evt == "error" for evt, _ in catch_b.events)

    await sio_a.disconnect()
    await sio_b.disconnect()


async def run_werewolf_flow(base_url: str):
    wallets = [f"0x{idx:040d}" for idx in range(6)]
    with requests.Session() as session:
        for wallet in wallets:
            await asyncio.to_thread(
                session.post, f"{base_url}/api/register", params={"wallet_address": wallet}
            )
            await asyncio.to_thread(
                session.post, f"{base_url}/api/login", params={"wallet_address": wallet}
            )

    clients: List[socketio.AsyncClient] = []
    catchers: List[EventCatcher] = []
    for _ in wallets:
        cli = socketio.AsyncClient()
        catcher = EventCatcher()
        for evt in ["authenticated", "werewolf_joined", "werewolf_state", "werewolf_game_created", "error"]:
            cli.on(evt, catcher.handler(evt))
        clients.append(cli)
        catchers.append(catcher)

    for cli in clients:
        await cli.connect(base_url, socketio_path="/socket.io", transports=["websocket"])
    for cli, wallet in zip(clients, wallets):
        await cli.emit("authenticate", {"address": wallet, "signature": "debug"})
    await asyncio.sleep(0.2)
    for catcher in catchers:
        catcher.expect_event("authenticated")

    await clients[0].emit("create_werewolf_game", {"game_id": "ww-1"})
    await asyncio.sleep(0.1)
    catchers[0].expect_event("werewolf_game_created")

    for cli in clients:
        await cli.emit("join_werewolf_game", {"game_id": "ww-1", "nickname": "p"})
    await asyncio.sleep(0.3)
    for catcher in catchers:
        catcher.expect_event("werewolf_joined")

    await clients[0].emit("start_werewolf_game", {"game_id": "ww-1"})
    await asyncio.sleep(0.2)
    await clients[1].emit("werewolf_action", {"game_id": "ww-1", "action": "chat", "message": "hello"})
    await asyncio.sleep(0.2)
    await clients[2].emit("werewolf_action", {"game_id": "ww-1", "action": "invalid_action"})
    await asyncio.sleep(0.2)
    assert any(evt == "error" for evt, _ in catchers[2].events)

    for cli in clients:
        await cli.disconnect()


async def main_runner():
    patch_main_dependencies()
    server, server_task = await start_server()
    try:
        base_url = "http://127.0.0.1:8001"
        await run_http_edge_cases(base_url)
        await run_texas_flow(base_url)
        await run_werewolf_flow(base_url)
        print("All example flows passed")
    finally:
        server.should_exit = True
        await asyncio.wait_for(server_task, timeout=5)
        if not server_task.done():
            server_task.cancel()


if __name__ == "__main__":
    asyncio.run(main_runner())
