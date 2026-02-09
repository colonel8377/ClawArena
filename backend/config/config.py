"""
Centralized configuration for the Arena Poker Server.

This module provides:
- Environment variable loading
- Local debug mode detection
- Configuration validation
"""

import os
import warnings
from decimal import Decimal


def _env_bool(name: str, default: bool) -> bool:
    """Parse common boolean env values with a safe fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}

# Load from environment
LOCAL_DEBUG_MODE = _env_bool('LOCAL_DEBUG_MODE', False)
DEV_MODE = _env_bool('DEV_MODE', False)

# Local debug mode balance (unlimited funds for testing)
LOCAL_DEBUG_BALANCE = Decimal(os.getenv('LOCAL_DEBUG_BALANCE', '999999999'))

# Database configuration
DB_USER = os.getenv('DB_USER', 'root')
DB_PASSWORD = os.getenv('DB_PASSWORD', '')
DB_HOST = os.getenv('DB_HOST', 'localhost')
DB_PORT = os.getenv('DB_PORT', '3306')
DB_NAME = os.getenv('DB_NAME', 'agent_arena')

# Redis configuration
REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')

# Web3 configuration (not used in local debug mode)
WEB3_PROVIDER_URL = os.getenv('WEB3_PROVIDER_URL', 'https://mainnet.base.org')
ARENA_VAULT_ADDRESS = os.getenv('ARENA_VAULT_ADDRESS', '')
SERVER_PRIVATE_KEY = os.getenv(
    'SERVER_PRIVATE_KEY',
    '0x0000000000000000000000000000000000000000000000000000000000000001'
)

# CORS configuration
def _parse_allowed_origins(raw_value: str):
    """Parse/trim ALLOWED_ORIGINS into a clean list for CORS matching."""
    origins = [item.strip() for item in raw_value.split(',') if item.strip()]
    return origins or ['*']


ALLOWED_ORIGINS = _parse_allowed_origins(os.getenv('ALLOWED_ORIGINS', '*'))


def _parse_allowed_hosts(raw_value: str):
    """Parse and sanitize host patterns for Starlette TrustedHostMiddleware."""
    valid_hosts = []
    invalid_hosts = []

    for item in raw_value.split(','):
        host = item.strip().lower()
        if not host:
            continue

        # Starlette accepts:
        # 1) "*"
        # 2) exact hosts without wildcard
        # 3) wildcard subdomain patterns like "*.example.com"
        if host == '*':
            valid_hosts.append(host)
            continue

        if '*' not in host:
            valid_hosts.append(host)
            continue

        if host.startswith('*.') and host.count('*') == 1 and len(host) > 2:
            valid_hosts.append(host)
            continue

        invalid_hosts.append(host)

    if invalid_hosts:
        warnings.warn(
            f"Ignored invalid ALLOWED_HOSTS patterns: {', '.join(invalid_hosts)}. "
            "Wildcard entries must be '*' or '*.example.com'.",
            RuntimeWarning,
        )

    # Keep service bootable even if env is misconfigured.
    if not valid_hosts:
        warnings.warn(
            "No valid ALLOWED_HOSTS found. Falling back to '*' to avoid startup failure.",
            RuntimeWarning,
        )
        return ['*']

    return valid_hosts


# Trusted host configuration (for TrustedHostMiddleware)
ALLOWED_HOSTS = _parse_allowed_hosts(
    os.getenv('ALLOWED_HOSTS', '*.railway.app, *.*.railway.app,*.clawarena.io,localhost,127.0.0.1')
)

# Anti-bot configuration (simplified - no PoW)
BOT_TOKEN_SECRET = os.getenv('BOT_TOKEN_SECRET', 'dev-unsafe-secret')
BOT_TOKEN_TTL = int(os.getenv('BOT_TOKEN_TTL', '3600'))  # 1 hour

# Game economy configuration
# 德州扑克筹码/Token比例：1 Token = 10 Chips，让用户感觉更值钱
TEXAS_CHIP_TO_TOKEN_RATIO = Decimal("0.1")  # 1 Token 换 10 Chips
TEXAS_DEFAULT_BUY_IN_CHIPS = 1000  # 默认买入1000筹码
TEXAS_DEFAULT_BUY_IN_TOKENS = TEXAS_DEFAULT_BUY_IN_CHIPS * TEXAS_CHIP_TO_TOKEN_RATIO  # = 100 Tokens

# 狼人杀奖金倍数：奖金池 = 入场费总和 × 奖金倍数
# 平台不抽成/不抽水：默认按 1.0 全额返还给胜利阵营
WEREWOLF_PRIZE_MULTIPLIER = Decimal("1.0")

# 提现配置
MIN_WITHDRAWAL_AMOUNT = Decimal("1.0")  # 最小提现金额：1 Token
GAS_COST_ESTIMATE_HIGH = Decimal("0.01")   # 高拥堵Gas费估算
GAS_COST_ESTIMATE_MEDIUM = Decimal("0.005") # 中等拥堵Gas费估算
GAS_COST_ESTIMATE_LOW = Decimal("0.001")    # 低拥堵Gas费估算

# 智能提现阈值：提现金额必须超过Gas费的倍数
WITHDRAWAL_PROFITABILITY_RATIO = Decimal("3.0")  # 提现收益至少是Gas费的3倍

# 每日提现额度（单服务器无上限）
DAILY_WITHDRAWAL_LIMIT = None  # None = 无上限

BOT_ALLOW_BYPASS_LOCAL = os.getenv('BOT_ALLOW_BYPASS_LOCAL', 'true').lower() == 'true'

# Socket.IO logging (chatty in production if enabled, especially Engine.IO frame logs)
SOCKET_IO_LOGGER = _env_bool('SOCKET_IO_LOGGER', LOCAL_DEBUG_MODE or DEV_MODE)
SOCKET_ENGINEIO_LOGGER = _env_bool('SOCKET_ENGINEIO_LOGGER', LOCAL_DEBUG_MODE)

# ============================================================================
# AGENT-ONLY POLICY (Simplified)
# ============================================================================
# This arena is designed for AI Agents ONLY. Humans can only spectate.
#
# How it works:
# 1. User-Agent detection: Block browsers, allow programmatic clients
# 2. Simple token-based sessions: Track agents
# 3. Rate limiting: Prevent abuse
#
# No challenge/PoW needed - we just want to filter out casual web scrapers.


def is_local_debug_mode() -> bool:
    """
    Check if local debug mode is enabled.
    
    Returns:
        True if LOCAL_DEBUG_MODE environment variable is set to 'true'
    """
    return LOCAL_DEBUG_MODE


def get_debug_balance() -> Decimal:
    """
    Get the balance for accounts in local debug mode.
    
    Returns:
        The debug balance (default: 999999999)
    """
    return LOCAL_DEBUG_BALANCE


# Print warning if local debug mode is enabled
if LOCAL_DEBUG_MODE:
    warnings.warn(
        "LOCAL DEBUG MODE ENABLED - Security features DISABLED. DO NOT USE IN PRODUCTION!",
        RuntimeWarning
    )
    print("=" * 70)
    print("⚠️  LOCAL DEBUG MODE ENABLED ⚠️")
    print("=" * 70)
    print("- Blockchain connections are DISABLED")
    print("- Authentication is SIMPLIFIED (no signature verification)")
    print("- All accounts have UNLIMITED funds")
    print("- DO NOT USE IN PRODUCTION!")
    print("=" * 70)
elif BOT_TOKEN_SECRET == 'dev-unsafe-secret':
    warnings.warn(
        "BOT_TOKEN_SECRET is using a default value. Set BOT_TOKEN_SECRET in production!",
        RuntimeWarning
    )
