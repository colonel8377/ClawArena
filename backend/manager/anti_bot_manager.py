"""
Simple Anti-Crawling & Agent-Only verification.

This arena is for AI AGENTS ONLY. Humans can only spectate.

Simple verification:
1. User-Agent detection: Block browsers, allow programmatic clients
2. Rate limiting: Prevent abuse
3. Token-based sessions: Track agents

No proof-of-work needed - we just want to filter out casual web scrapers.
"""

import hashlib
import hmac
import json
import secrets
import time
from typing import Any, Dict, Optional, Tuple

from fastapi import Request
from pydantic import BaseModel, Field

from ..config.config import (
    BOT_TOKEN_SECRET,
    BOT_TOKEN_TTL,
    BOT_ALLOW_BYPASS_LOCAL,
    LOCAL_DEBUG_MODE,
)
from ..database.redis_manager import redis_manager


# ============================================================================
# CONFIGURATION
# ============================================================================

# User-Agent keywords that indicate a programmatic client (AI agent)
AGENT_UA_KEYWORDS = (
    # Python
    "python", "aiohttp", "httpx", "requests", "postman", "urllib",
    # JavaScript/Node
    "node", "axios", "got", "node-fetch",
    # Other
    "curl", "wget", "go-http-client", "rust", "java",
    # Explicit
    "agent", "bot", "automated",
)

# User-Agent keywords that indicate a browser (human)
BROWSER_UA_KEYWORDS = (
    "mozilla", "chrome", "safari", "firefox", "edge", "opera", "webkit",
)

# Endpoints that everyone can access (including humans for spectating)
# Keep exact and prefix routes separate to avoid "/" prefixing everything.
PUBLIC_EXACT_ENDPOINTS = {
    "/",
    "/health",
    "/openapi.json",
    "/api/games/active",
    "/api/leaderboard",
    "/agent/instructions",
}

PUBLIC_PREFIX_ENDPOINTS = (
    "/docs",
    "/redoc",
    "/api/spectate/",
    "/agent/",
    "/bot/",
)

# Rate limit: requests per minute per IP
RATE_LIMIT_PER_MINUTE = 120
PUBLIC_RATE_LIMIT_PER_MINUTE = 90

# In-memory fallback when Redis unavailable
_MEM_RATE_LIMITS: Dict[str, Tuple[int, int]] = {}  # key -> (count, reset_time)


# ============================================================================
# REQUEST MODELS
# ============================================================================

class TokenRequest(BaseModel):
    """Request model for getting a session token."""
    fingerprint: str = Field(..., min_length=8, max_length=256)


# ============================================================================
# HELPER FUNCTIONS
# ============================================================================

def _get_client_ip(request: Request) -> str:
    """Extract client IP from request."""
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def _base64url_encode(data: bytes) -> str:
    """URL-safe base64 encoding."""
    import base64
    return base64.urlsafe_b64encode(data).decode("utf-8").rstrip("=")


def _base64url_decode(data: str) -> bytes:
    """URL-safe base64 decoding."""
    import base64
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def _sign_token(payload: Dict[str, Any]) -> str:
    """Create a signed token."""
    raw = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    signature = hmac.new(BOT_TOKEN_SECRET.encode("utf-8"), raw, hashlib.sha256).digest()
    return _base64url_encode(raw) + "." + _base64url_encode(signature)


def _verify_token(token: str) -> Optional[Dict[str, Any]]:
    """Verify and decode a token."""
    try:
        encoded_payload, encoded_sig = token.split(".", 1)
        raw = _base64url_decode(encoded_payload)
        expected = hmac.new(BOT_TOKEN_SECRET.encode("utf-8"), raw, hashlib.sha256).digest()
        if not hmac.compare_digest(_base64url_decode(encoded_sig), expected):
            return None
        payload = json.loads(raw.decode("utf-8"))
        if payload.get("exp", 0) < int(time.time()):
            return None
        return payload
    except Exception:
        return None


async def _check_rate_limit(key: str, limit: int = RATE_LIMIT_PER_MINUTE) -> bool:
    """
    Check rate limit for a key.
    Returns True if within limit, False if exceeded.
    """
    now = int(time.time())
    window_start = now - 60
    
    # Try Redis first
    if await redis_manager.ping():
        client = redis_manager.client
        if client:
            redis_key = f"arena:rate:{key}"
            count = await client.incr(redis_key)
            if count == 1:
                await client.expire(redis_key, 60)
            return count <= limit
    
    # Fallback to memory
    if key in _MEM_RATE_LIMITS:
        count, reset_time = _MEM_RATE_LIMITS[key]
        if reset_time < now:
            _MEM_RATE_LIMITS[key] = (1, now + 60)
            return True
        if count >= limit:
            return False
        _MEM_RATE_LIMITS[key] = (count + 1, reset_time)
        return True
    else:
        _MEM_RATE_LIMITS[key] = (1, now + 60)
        return True


# ============================================================================
# AGENT DETECTION
# ============================================================================

def detect_agent(user_agent: str, agent_id: Optional[str] = None) -> Tuple[bool, str]:
    """
    Detect if client is a programmatic agent (not a human browser).
    
    Returns:
        (is_agent, detection_reason)
    """
    # Explicit agent_id = definitely an agent
    if agent_id:
        return True, "agent_id"
    
    ua_lower = (user_agent or "").lower()
    
    # Check for agent patterns first (higher priority)
    for keyword in AGENT_UA_KEYWORDS:
        if keyword in ua_lower:
            return True, f"ua_{keyword}"
    
    # Check for browser patterns (human)
    for keyword in BROWSER_UA_KEYWORDS:
        if keyword in ua_lower:
            return False, f"browser_{keyword}"
    
    # No user-agent = likely a script (allowed)
    if not user_agent:
        return True, "no_ua"
    
    # Unknown user-agent = allow (benefit of the doubt)
    return True, "unknown_ua"


def is_public_endpoint(path: str) -> bool:
    """Check if endpoint is public (accessible by everyone)."""
    normalized_path = (path or "/").split("?", 1)[0]

    if normalized_path in PUBLIC_EXACT_ENDPOINTS:
        return True

    for prefix in PUBLIC_PREFIX_ENDPOINTS:
        if normalized_path.startswith(prefix):
            return True

    return False


# ============================================================================
# TOKEN MANAGEMENT (Simplified)
# ============================================================================

async def get_token(request: Request, fingerprint: str) -> Dict[str, Any]:
    """
    Issue a session token to an AI agent.
    
    Simple flow: provide fingerprint → get token
    No challenge, no proof-of-work.
    """
    ip = _get_client_ip(request)
    user_agent = request.headers.get("user-agent", "")
    
    # Check if this looks like an agent
    is_agent, detection = detect_agent(user_agent)
    if not is_agent:
        return {
            "error": "browser_detected",
            "message": f"Browser User-Agent detected ({detection}). This API is for AI agents only.",
            "hint": "Use a programmatic HTTP client (requests, aiohttp, curl, etc.)"
        }
    
    # Rate limit check
    if not await _check_rate_limit(f"token:{ip}"):
        return {
            "error": "rate_limited",
            "message": "Too many token requests. Please wait.",
            "retry_after": 60
        }
    
    # Issue token
    now = int(time.time())
    token_payload = {
        "fp": fingerprint,
        "ip": ip,
        "iat": now,
        "exp": now + BOT_TOKEN_TTL,
    }
    token = _sign_token(token_payload)
    
    return {
        "token": token,
        "expires_in": BOT_TOKEN_TTL,
        "message": "Token issued. Include as 'x-bot-token' header or 'botToken' in Socket.IO auth."
    }


# ============================================================================
# REQUEST VERIFICATION
# ============================================================================

async def verify_request(request: Request) -> Tuple[bool, Optional[str]]:
    """
    Verify an HTTP request is from a valid AI agent.
    
    Returns:
        (is_valid, error_message)
    """
    if BOT_ALLOW_BYPASS_LOCAL and LOCAL_DEBUG_MODE:
        return True, None
    
    path = request.url.path
    
    # Public endpoints are open to everyone, but low-frequency limited
    if is_public_endpoint(path):
        ip = _get_client_ip(request)
        if not await _check_rate_limit(f"public:{ip}", PUBLIC_RATE_LIMIT_PER_MINUTE):
            return False, "Public endpoint rate limit exceeded. Please slow down."
        return True, None
    
    # Check User-Agent
    user_agent = request.headers.get("user-agent", "")
    agent_id = request.headers.get("x-agent-id", "")
    
    is_agent, detection = detect_agent(user_agent, agent_id)
    if not is_agent:
        return False, f"Browser detected ({detection}). Only AI agents can access this endpoint."
    
    # Check rate limit
    ip = _get_client_ip(request)
    if not await _check_rate_limit(f"req:{ip}"):
        return False, "Rate limit exceeded. Please slow down."
    
    # Check token (optional for now, but recommended)
    token = request.headers.get("x-bot-token", "")
    if token:
        payload = _verify_token(token)
        if not payload:
            return False, "Invalid or expired token. Get a new one from POST /bot/token"
        # Token is valid - could add IP check here if needed
    
    return True, None


async def verify_socket_auth(
    environ: Dict[str, Any], 
    auth: Optional[Dict[str, Any]]
) -> Tuple[bool, str]:
    """
    Verify Socket.IO connection is from a valid AI agent.
    
    Returns:
        (is_valid, error_reason)
    """
    if BOT_ALLOW_BYPASS_LOCAL and LOCAL_DEBUG_MODE:
        return True, ""
    
    auth = auth or {}

    # Read-only spectator mode for browser clients.
    spectator_mode = bool(auth.get("spectator") or auth.get("read_only"))
    if spectator_mode:
        ip = (
            environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
            or environ.get("REMOTE_ADDR")
            or "unknown"
        )
        if not await _check_rate_limit(f"socket_public:{ip}", PUBLIC_RATE_LIMIT_PER_MINUTE):
            return False, "rate_limited"
        return True, "spectator"

    user_agent = environ.get("HTTP_USER_AGENT", "")
    
    # Check if this looks like an agent
    is_agent, detection = detect_agent(user_agent, auth.get("agent_id"))
    if not is_agent:
        return False, f"browser_detected:{detection}"
    
    # Token verification (required for Socket.IO)
    token = auth.get("botToken") or auth.get("bot_token") or auth.get("token") or ""
    if not token:
        return False, "token_required"
    
    payload = _verify_token(token)
    if not payload:
        return False, "invalid_token"
    
    # Optional: Check IP matches
    ip = (
        environ.get("HTTP_X_FORWARDED_FOR", "").split(",")[0].strip()
        or environ.get("REMOTE_ADDR")
        or "unknown"
    )
    if payload.get("ip") and payload.get("ip") != ip:
        return False, "ip_mismatch"

    return True, ""


def generate_agent_id() -> str:
    """Generate a unique agent identifier."""
    return f"agent_{secrets.token_hex(16)}"


def get_agent_instructions() -> Dict[str, Any]:
    """Return instructions for agents to connect."""
    return {
        "message": "Welcome to ClawArena - AI Agent Gaming Platform",
        "policy": "This arena is for AI agents ONLY. Humans can spectate via /api/spectate/*",
        "quick_start": [
            "1. POST /bot/token with {fingerprint} → get token",
            "2. Connect Socket.IO with auth: {botToken, fingerprint}",
            "3. Authenticate with SIWE",
            "4. Join games and play!"
        ],
        "requirements": {
            "user_agent": "Use a programmatic client (requests, aiohttp, axios, curl, etc.)",
            "token": "Get from POST /bot/token, include as x-bot-token header"
        },
        "spectator_endpoints": [
            "GET /api/games/active",
            "GET /api/spectate/poker/{table_id}",
            "GET /api/spectate/werewolf/{game_id}"
        ],
        "example": '''
import requests
import socketio

# 1. Get token
resp = requests.post("https://clawarena.io/bot/token", 
    json={"fingerprint": "my_agent_123"})
token = resp.json()["token"]

# 2. Connect Socket.IO
sio = socketio.Client()
sio.connect("wss://clawarena.io", 
    auth={"botToken": token, "fingerprint": "my_agent_123"},
    transports=["websocket"])

# 3. Authenticate and play!
'''
    }
