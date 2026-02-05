import os
import sys
from pathlib import Path

os.environ.setdefault("PYTEST_DISABLE_PLUGIN_AUTOLOAD", "1")

import pytest
from httpx import AsyncClient

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.append(str(ROOT))

from main import asgi_app  # noqa: E402


@pytest.mark.asyncio
async def test_health_ok():
    async with AsyncClient(app=asgi_app, base_url="http://test") as ac:
        resp = await ac.get("/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "healthy"
    assert "local_debug_mode" in data


@pytest.mark.asyncio
async def test_withdrawal_invalid_amount():
    async with AsyncClient(app=asgi_app, base_url="http://test") as ac:
        resp = await ac.post("/withdrawal/request", params={"address": "0xabc", "amount": 0})
    assert resp.status_code == 400
    assert "Invalid amount" in resp.json()["detail"]
