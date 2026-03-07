from slowapi import Limiter
from slowapi.util import get_remote_address
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from backend.views.response import fail
from backend.config.settings import get_settings

limiter = Limiter(key_func=get_remote_address)


def attach_rate_limiter(app: FastAPI) -> None:
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_handler)
    app.add_middleware(SlowAPIMiddleware)


def _rate_limit_handler(_: Request, __: RateLimitExceeded) -> JSONResponse:
    return JSONResponse(status_code=429, content=fail("Rate limited", 42901))


def rate_limit(limit: str):
    settings = get_settings()
    if settings.debug:
        def decorator(func):
            return func
        return decorator
    return limiter.limit(limit)
