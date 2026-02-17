"""Shared HTTP rate limiter instance."""

from slowapi import Limiter
from slowapi.util import get_remote_address
from fastapi import Request

from backend.constant.api_error import InvalidPlayerIDError


# ============================================================================
# CUSTOM RATE LIMIT DECORATOR (Service Level)
# ============================================================================

def rate_limit(limit: str, key_func=None):
    """
    Decorator for service-level rate limiting (not just HTTP routes).
    
    Uses Redis to track request counts.
    
    Args:
        limit: Rate limit string (e.g., "10/minute", "1/second")
        key_func: Function to extract key from arguments (default: first arg as key)
        
    Usage:
        @rate_limit("10/minute", key_func=lambda wallet, *args: f"transfer:{wallet}")
        async def transfer(wallet, ...):
            ...
    """
    def decorator(func):
        from functools import wraps
        import time
        from backend.database.redis_manager import redis_manager

        # Parse limit string "10/minute" -> count=10, seconds=60
        count, period = limit.split('/')
        count = int(count)
        seconds = {
            'second': 1,
            'minute': 60,
            'hour': 3600,
            'day': 86400
        }.get(period, 60)

        @wraps(func)
        async def wrapper(*args, **kwargs):
            if not redis_manager.client:
                # If Redis unavailable, fail open or closed? 
                # Fail open (allow request) to prevent downtime
                return await func(*args, **kwargs)

            # Determine key
            if key_func:
                key_suffix = key_func(*args, **kwargs)
            else:
                # Default: use first argument if available, else function name
                key_suffix = str(args[0]) if args else "global"
            
            key = f"rate_limit:{func.__name__}:{key_suffix}"
            
            # Simple sliding window or fixed window using Redis INCR + EXPIRE
            current = await redis_manager.client.incr(key)
            if current == 1:
                await redis_manager.client.expire(key, seconds)
            
            if current > count:
                raise ValueError(f"Rate limit exceeded: {limit}")
            
            return await func(*args, **kwargs)
        
        return wrapper
    return decorator

def get_player_id(request: Request)->str:
    player_id = getattr(request.state, "player_id", None)
    if not player_id:
        raise InvalidPlayerIDError("Missing token player_id")
    return request.state.player_id

ip_limiter = Limiter(key_func=get_remote_address)
player_id_limiter = Limiter(key_func=get_player_id)