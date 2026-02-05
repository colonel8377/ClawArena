"""
Anti-bot protection: fingerprinting, captcha, and risk scoring.
"""

import base64
import hashlib
import hmac
import json
import secrets
import time
from dataclasses import dataclass
from typing import Any, Dict, Optional, Tuple

from fastapi import HTTPException, Request
from pydantic import BaseModel, Field

from config import (
    BOT_TOKEN_SECRET,
    BOT_TOKEN_TTL,
    BOT_CHALLENGE_TTL,
    BOT_POW_DIFFICULTY,
    BOT_RISK_BLOCK_THRESHOLD,
    BOT_RISK_CHALLENGE_THRESHOLD,
    BOT_ALLOW_BYPASS_LOCAL,
    LOCAL_DEBUG_MODE,
)
from database.redis_manager import redis_manager

_MEM_CHALLENGES: Dict[str, Tuple[Dict[str, Any], int]] = {}


SUSPICIOUS_UA_KEYWORDS = (
    "curl",
    "wget",
    "python",
    "httpclient",
    "aiohttp",
    "scrapy",
    "spider",
    "bot",
    "headless",
    "phantomjs",
    "selenium",
    "playwright",
    "puppeteer",
)


class BotChallengeRequest(BaseModel):
    fingerprint: str = Field(..., min_length=8, max_length=256)


class BotVerifyRequest(BaseModel):
    challenge_id: str = Field(..., min_length=8, max_length=128)
    answer: str = Field(..., min_length=1, max_length=64)
    pow_nonce: str = Field(..., min_length=1, max_length=64)
    fingerprint: str = Field(..., min_length=8, max_length=256)


@dataclass
class BotChallenge:
    challenge_id: str
    question: str
    answer: int
    pow_salt: str
    pow_difficulty: int
    fingerprint: str
    ip: str
    issued_at: int


def _base64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _unbase64url(data: str) -> bytes:
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _pow_valid(salt: str, nonce: str, difficulty_bits: int) -> bool:
    digest = hashlib.sha256(f"{salt}:{nonce}".encode("utf-8")).digest()
    bits_remaining = difficulty_bits
    for byte in digest:
        if bits_remaining <= 0:
            return True
        if bits_remaining >= 8:
            if byte != 0:
                return False
            bits_remaining -= 8
            continue
        mask = 0xFF << (8 - bits_remaining) & 0xFF
        return (byte & mask) == 0
    return bits_remaining <= 0


def _get_client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _is_suspicious_ua(user_agent: str) -> bool:
    ua = (user_agent or "").lower()
    if not ua:
        return True
    return any(token in ua for token in SUSPICIOUS_UA_KEYWORDS)


async def _redis_set_json(key: str, value: Dict[str, Any], ttl: int) -> bool:
    if not await redis_manager.ping():
        _MEM_CHALLENGES[key] = (value, int(time.time()) + ttl)
        return True
    client = redis_manager.client
    if not client:
        _MEM_CHALLENGES[key] = (value, int(time.time()) + ttl)
        return True
    await client.setex(key, ttl, json.dumps(value))
    return True


async def _redis_get_json(key: str) -> Optional[Dict[str, Any]]:
    if not await redis_manager.ping():
        payload = _MEM_CHALLENGES.get(key)
        if not payload:
            return None
        data, exp = payload
        if exp < int(time.time()):
            _MEM_CHALLENGES.pop(key, None)
            return None
        return data
    client = redis_manager.client
    if not client:
        payload = _MEM_CHALLENGES.get(key)
        if not payload:
            return None
        data, exp = payload
        if exp < int(time.time()):
            _MEM_CHALLENGES.pop(key, None)
            return None
        return data
    data = await client.get(key)
    return json.loads(data) if data else None


async def _redis_incr(key: str, ttl: int) -> int:
    if not await redis_manager.ping():
        return 0
    client = redis_manager.client
    if not client:
        return 0
    value = await client.incr(key)
    if value == 1:
        await client.expire(key, ttl)
    return value


def _token_sign(payload: Dict[str, Any]) -> str:
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(BOT_TOKEN_SECRET.encode("utf-8"), raw, hashlib.sha256).digest()
    return _base64url(raw) + "." + _base64url(signature)


def _token_verify(token: str) -> Optional[Dict[str, Any]]:
    try:
        encoded_payload, encoded_sig = token.split(".", 1)
        raw = _unbase64url(encoded_payload)
        expected = hmac.new(BOT_TOKEN_SECRET.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(_unbase64url(encoded_sig), expected):
            return None
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


async def evaluate_risk(
    ip: str, fingerprint: str, user_agent: str, path: str, method: str
) -> int:
    risk = 0
    if _is_suspicious_ua(user_agent):
        risk += 25
    if not fingerprint:
        risk += 20
    if method not in {"GET", "POST"}:
        risk += 5
    if path.startswith("/api/spectate"):
        risk += 5
    ip_rate = await _redis_incr(f"arena:bot:req:ip:{ip}", 60)
    fp_rate = await _redis_incr(f"arena:bot:req:fp:{fingerprint}", 60) if fingerprint else 0
    if ip_rate > 90:
        risk += 30
    elif ip_rate > 60:
        risk += 15
    if fp_rate > 150:
        risk += 25
    elif fp_rate > 100:
        risk += 10
    return risk


async def record_failed_check(ip: str, fingerprint: str) -> int:
    fail_count = await _redis_incr(f"arena:bot:fail:ip:{ip}", 3600)
    if fingerprint:
        await _redis_incr(f"arena:bot:fail:fp:{fingerprint}", 3600)
    return fail_count


def should_skip_bot_check(path: str, method: str) -> bool:
    if method == "OPTIONS":
        return True
    if path in {"/", "/health", "/openapi.json"}:
        return True
    if path.startswith("/docs") or path.startswith("/redoc"):
        return True
    if path.startswith("/bot/"):
        return True
    return False


async def issue_challenge(request: Request, fingerprint: str) -> Dict[str, Any]:
    ip = _get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    risk = await evaluate_risk(ip, fingerprint, user_agent, request.url.path, request.method)

    # Simple arithmetic captcha + proof-of-work
    a = secrets.randbelow(8) + 2
    b = secrets.randbelow(8) + 2
    answer = a + b
    challenge_id = secrets.token_urlsafe(16)
    pow_salt = secrets.token_hex(16)
    pow_difficulty = max(14, min(BOT_POW_DIFFICULTY, 20))

    challenge = BotChallenge(
        challenge_id=challenge_id,
        question=f"{a} + {b} = ?",
        answer=answer,
        pow_salt=pow_salt,
        pow_difficulty=pow_difficulty,
        fingerprint=fingerprint,
        ip=ip,
        issued_at=int(time.time()),
    )
    await _redis_set_json(
        f"arena:bot:challenge:{challenge_id}",
        {
            "answer": answer,
            "pow_salt": pow_salt,
            "pow_difficulty": pow_difficulty,
            "fingerprint": fingerprint,
            "ip": ip,
            "issued_at": challenge.issued_at,
        },
        BOT_CHALLENGE_TTL,
    )
    return {
        "challenge_id": challenge_id,
        "question": challenge.question,
        "pow_salt": pow_salt,
        "pow_difficulty": pow_difficulty,
        "expires_in": BOT_CHALLENGE_TTL,
        "risk": risk,
    }


async def verify_challenge(request: Request, payload: BotVerifyRequest) -> Dict[str, Any]:
    ip = _get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    challenge_key = f"arena:bot:challenge:{payload.challenge_id}"
    stored = await _redis_get_json(challenge_key)
    if not stored:
        raise HTTPException(status_code=400, detail="Challenge expired or invalid")
    if stored.get("ip") != ip or stored.get("fingerprint") != payload.fingerprint:
        await record_failed_check(ip, payload.fingerprint)
        raise HTTPException(status_code=403, detail="Challenge mismatch")

    try:
        answer = int(payload.answer)
    except ValueError:
        await record_failed_check(ip, payload.fingerprint)
        raise HTTPException(status_code=400, detail="Invalid answer")

    if answer != int(stored.get("answer", -1)):
        await record_failed_check(ip, payload.fingerprint)
        raise HTTPException(status_code=403, detail="Incorrect answer")

    if not _pow_valid(stored.get("pow_salt", ""), payload.pow_nonce, int(stored.get("pow_difficulty", 0))):
        await record_failed_check(ip, payload.fingerprint)
        raise HTTPException(status_code=403, detail="Invalid proof of work")

    risk = await evaluate_risk(ip, payload.fingerprint, user_agent, request.url.path, request.method)
    now = int(time.time())
    token_payload = {
        "fp": payload.fingerprint,
        "ip": ip,
        "iat": now,
        "exp": now + BOT_TOKEN_TTL,
        "risk": risk,
    }
    token = _token_sign(token_payload)
    return {
        "bot_token": token,
        "expires_in": BOT_TOKEN_TTL,
        "risk": risk,
    }


async def verify_request_bot_token(request: Request) -> Tuple[bool, Optional[str], int]:
    if BOT_ALLOW_BYPASS_LOCAL and LOCAL_DEBUG_MODE:
        return True, None, 0
    path = request.url.path
    if should_skip_bot_check(path, request.method):
        return True, None, 0

    ip = _get_client_ip(request)
    token = request.headers.get("x-bot-token", "")
    fingerprint = request.headers.get("x-fingerprint", "")
    user_agent = request.headers.get("user-agent", "")

    risk = await evaluate_risk(ip, fingerprint, user_agent, path, request.method)
    if risk >= BOT_RISK_BLOCK_THRESHOLD:
        await record_failed_check(ip, fingerprint)
        return False, "risk_blocked", risk

    if not token:
        await record_failed_check(ip, fingerprint)
        return False, "challenge_required", risk

    payload = _token_verify(token)
    if not payload:
        await record_failed_check(ip, fingerprint)
        return False, "invalid_token", risk

    if payload.get("fp") != fingerprint or payload.get("ip") != ip:
        await record_failed_check(ip, fingerprint)
        return False, "token_mismatch", risk

    if risk >= BOT_RISK_CHALLENGE_THRESHOLD and payload.get("risk", 0) < BOT_RISK_CHALLENGE_THRESHOLD:
        return False, "challenge_required", risk

    return True, None, risk


async def verify_socket_auth(
    environ: Dict[str, Any], auth: Optional[Dict[str, Any]]
) -> Tuple[bool, str]:
    if BOT_ALLOW_BYPASS_LOCAL and LOCAL_DEBUG_MODE:
        return True, ""
    auth = auth or {}
    token = auth.get("botToken") or auth.get("bot_token") or ""
    fingerprint = auth.get("fingerprint") or auth.get("fp") or ""
    ip = (
        environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or environ.get("REMOTE_ADDR")
        or "unknown"
    )
    user_agent = environ.get("HTTP_USER_AGENT", "")
    if not token:
        return False, "challenge_required"

    payload = _token_verify(token)
    if not payload:
        return False, "invalid_token"
    if payload.get("fp") != fingerprint or payload.get("ip") != ip:
        return False, "token_mismatch"
    risk = await evaluate_risk(ip, fingerprint, user_agent, "/socket.io", "GET")
    if risk >= BOT_RISK_BLOCK_THRESHOLD:
        return False, "risk_blocked"
    return True, ""
