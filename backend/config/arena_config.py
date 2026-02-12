"""
Arena runtime configuration.

This module centralizes environment-driven settings for debug mode, web3,
economy values, and Socket.IO logging.
"""

import os
import sys
import warnings
from decimal import Decimal


def _env_bool(name: str, default: bool) -> bool:
    """Parse common boolean env values with a safe fallback."""
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {'1', 'true', 'yes', 'on'}


def _detect_production_environment() -> bool:
    """Detect if we are running in a production-like environment."""
    production_indicators = (
        'RAILWAY_ENVIRONMENT',
        'RAILWAY_SERVICE_NAME',
        'FLY_APP_NAME',
        'RENDER_SERVICE_ID',
        'HEROKU_APP_NAME',
        'AWS_EXECUTION_ENV',
        'K_SERVICE',           # Google Cloud Run
        'ECS_CONTAINER_METADATA_URI',
    )
    return any(os.getenv(var) for var in production_indicators)


# Load from environment
LOCAL_DEBUG_MODE = _env_bool('LOCAL_DEBUG_MODE', False)

# Hard override: never allow debug mode in detected production environments
if LOCAL_DEBUG_MODE and _detect_production_environment():
    print("CRITICAL: LOCAL_DEBUG_MODE=true in a production environment. Forcing OFF.")
    LOCAL_DEBUG_MODE = False
DEV_MODE = _env_bool('DEV_MODE', False)

# Local debug mode balance (unlimited funds for testing)
LOCAL_DEBUG_BALANCE = Decimal(os.getenv('LOCAL_DEBUG_BALANCE', '999999999'))

# Web3 configuration (not used in local debug mode)
WEB3_PROVIDER_URL = os.getenv('WEB3_PROVIDER_URL', 'https://mainnet.base.org')
ARENA_VAULT_ADDRESS = os.getenv('ARENA_VAULT_ADDRESS', '')
SERVER_PRIVATE_KEY = os.getenv(
    'SERVER_PRIVATE_KEY',
    '0x0000000000000000000000000000000000000000000000000000000000000001'
)


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