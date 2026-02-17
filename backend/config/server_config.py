import os
import warnings


# CORS configuration
def _parse_allowed_origins(raw_value: str):
    """Parse/trim ALLOWED_ORIGINS into a clean list for CORS matching."""
    origins = [item.strip() for item in raw_value.split(',') if item.strip()]
    return origins or ['*']


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


ALLOWED_ORIGINS = _parse_allowed_origins(os.getenv('ALLOWED_ORIGINS', '*'))


# Trusted host configuration (for TrustedHostMiddleware)
ALLOWED_HOSTS = _parse_allowed_hosts(
    os.getenv('ALLOWED_HOSTS', '*.railway.app,*.clawarena.io,localhost,127.0.0.1')
)

# Anti-bot configuration (simplified - no PoW)
BOT_TOKEN_SECRET = os.getenv('BOT_TOKEN_SECRET', 'dev-unsafe-secret')
BOT_TOKEN_TTL = int(os.getenv('BOT_TOKEN_TTL', '86400'))  # 1 day

if BOT_TOKEN_SECRET == 'dev-unsafe-secret':
    warnings.warn(
        "BOT_TOKEN_SECRET is using a default value. Set BOT_TOKEN_SECRET in production!",
        RuntimeWarning,
    )