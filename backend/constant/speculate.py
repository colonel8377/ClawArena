from datetime import timedelta

# Constants for stale checks
STALE_THRESHOLD = timedelta(minutes=30)
# Constants below are kept for debug/legacy memory checks if needed
WAITING_STALE_THRESHOLD = timedelta(hours=1)
POKER_INACTIVE_THRESHOLD = timedelta(minutes=15)
WEREWOLF_INACTIVE_THRESHOLD = timedelta(hours=1)

LEADERBOARD_LIMIT = 10
