from decimal import Decimal

# Poker timeout check interval (seconds)
POKER_TIMEOUT_CHECK_INTERVAL = 1

# Texas fixed-entry matchmaking economy:
# 100 tokens entry = 1000 chips (10 chips per token).
TEXAS_FIXED_ENTRY_FEE_TOKENS = Decimal("100")
TEXAS_FIXED_BUY_IN_CHIPS = 1000
