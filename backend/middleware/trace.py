import time
import uuid
from fastapi import Request

from backend.views.context import set_trace_id
from backend.utils.log import get_logger

logger = get_logger(__name__)


async def trace_middleware(request: Request, call_next):
    trace_id = request.headers.get("x-trace-id") or uuid.uuid4().hex
    set_trace_id(trace_id)
    start = time.time()
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    duration_ms = int((time.time() - start) * 1000)
    logger.info(
        "http_request method=%s path=%s status=%s duration_ms=%s",
        request.method,
        request.url.path,
        response.status_code,
        duration_ms,
    )
    return response
