import os
from urllib.parse import quote_plus


def _build_database_url() -> str:
    """Build DB URL from DB_URL or DB_* vars (docker-compose friendly)."""
    direct_url = os.getenv('DB_URL', '').strip()
    if direct_url:
        return direct_url.replace('mysql://', '')

    user = os.getenv('DB_USER', 'root')
    password = os.getenv('DB_PASSWORD', '')
    host = os.getenv('DB_HOST', 'localhost')
    port = os.getenv('DB_PORT', '3306')
    name = os.getenv('DB_NAME', 'agent_arena')
    return f"{quote_plus(user)}:{quote_plus(password)}@{host}:{port}/{name}"


# Database configuration from environment
DB_URL = _build_database_url()

# Retry configuration for database connection
DB_CONNECT_RETRIES = int(os.getenv('DB_CONNECT_RETRIES', '10'))
DB_CONNECT_RETRY_DELAY = int(os.getenv('DB_CONNECT_RETRY_DELAY', '3'))

# Create sync database URL (for backwards compatibility)
SYNC_DATABASE_URL = f"mysql+pymysql://{DB_URL}"

# Create async database URL
ASYNC_DATABASE_URL = f"mysql+aiomysql://{DB_URL}"

