# User-Agent keywords that indicate a programmatic client (AI agent)
from typing import Optional, Tuple

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


PUBLIC_EXACT_ENDPOINTS = {
    "/",
    "/health",
    "/api/games/active",
    "/api/register",
    "/api/leaderboard",
    "/agent/instructions",
}

def detect_agent(user_agent: str) -> Tuple[bool, str]:
    """
    Detect if client is a programmatic agent (not a human browser).

    Returns:
        (is_agent, detection_reason)
    """
    # Explicit agent_id = definitely an agent

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
        return False, "no_ua"

    # Unknown user-agent = allow (benefit of the doubt)
    return False, "unknown_ua"