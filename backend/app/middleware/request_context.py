"""Request-ID / correlation middleware + structured access logging (task 9).

Assigns every request a stable id (honouring an inbound ``X-Request-ID`` or the
W3C ``traceparent`` trace-id when present, so ids line up with distributed
traces — task 15), exposes it on ``request.state.request_id`` and the response
``X-Request-ID`` header, binds it into structlog's contextvars so every log line
in the request carries it, and emits one structured access log per request.

Pure-stdlib + structlog, so it adds no dependency and stays independent of the
tracing stack (which is optional and gated separately).
"""

import time
import uuid

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()

REQUEST_ID_HEADER = "X-Request-ID"


def _incoming_id(request: Request) -> str:
    """Prefer an explicit request id, then the traceparent trace-id, else new."""
    rid = request.headers.get(REQUEST_ID_HEADER)
    if rid:
        return rid[:128]
    traceparent = request.headers.get("traceparent")
    if traceparent:
        # W3C format: version-traceid-spanid-flags; reuse the 32-hex trace id.
        parts = traceparent.split("-")
        if len(parts) >= 2 and len(parts[1]) == 32:
            return parts[1]
    return uuid.uuid4().hex


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        request_id = _incoming_id(request)
        request.state.request_id = request_id

        structlog.contextvars.bind_contextvars(request_id=request_id)
        start = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            # Duration is still useful on the error path; the exception handlers
            # (task 7) own the response, so re-raise after logging.
            elapsed_ms = (time.perf_counter() - start) * 1000
            logger.error(
                "request_failed",
                method=request.method,
                path=request.url.path,
                duration_ms=round(elapsed_ms, 2),
            )
            structlog.contextvars.unbind_contextvars("request_id")
            raise

        elapsed_ms = (time.perf_counter() - start) * 1000
        response.headers[REQUEST_ID_HEADER] = request_id
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(elapsed_ms, 2),
        )
        structlog.contextvars.unbind_contextvars("request_id")
        return response
