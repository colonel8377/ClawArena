from decimal import Decimal

# Configuration
DAILY_LOGIN_REWARD = Decimal("1000.0")  # 1000 tokens per day
LOGIN_SECRET_BYTES = 24  # token_urlsafe -> ~32 chars
LOGIN_SECRET_ITERATIONS = 200_000