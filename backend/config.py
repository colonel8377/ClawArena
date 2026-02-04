"""
Centralized configuration for the Arena Poker Server.

This module provides:
- Environment variable loading
- Local debug mode detection
- Configuration validation
"""

import os
from decimal import Decimal

# Load from environment
LOCAL_DEBUG_MODE = os.getenv('LOCAL_DEBUG_MODE', 'false').lower() == 'true'
DEV_MODE = os.getenv('DEV_MODE', 'false').lower() == 'true'

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
ALLOWED_ORIGINS = os.getenv('ALLOWED_ORIGINS', '*').split(',')


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
    import warnings
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
