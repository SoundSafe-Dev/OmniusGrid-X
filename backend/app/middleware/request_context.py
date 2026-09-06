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

from app.core.http_metrics import record_http

logger = structlog.get_logger()

REQUEST_ID_HEADER = "X-Request-ID"


def correlation_id_from_headers(headers) -> str:
    """Derive a correlation id from request/handshake headers.

    Prefer an explicit ``X-Request-ID``, then the W3C ``traceparent`` trace-id,
    else mint a fresh one. Accepts anything with ``.get(name)`` (Starlette's
    ``Headers`` for both HTTP requests and WebSocket handshakes), so the HTTP
    middleware and the WebSocket endpoint (FS-108) share one derivation and
    ids line up across both transports and with distributed traces.
    """
    rid = headers.get(REQUEST_ID_HEADER)
    if rid:
        return rid[:128]
    traceparent = headers.get("traceparent")
    if traceparent:
        # W3C format: version-traceid-spanid-flags; reuse the 32-hex trace id.
        parts = traceparent.split("-")
        if len(parts) >= 2 and len(parts[1]) == 32:
            return parts[1]
    return uuid.uuid4().hex


def _incoming_id(request: Request) -> str:
    """Prefer an explicit request id, then the traceparent trace-id, else new."""
    return correlation_id_from_headers(request.headers)


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

        elapsed = time.perf_counter() - start
        response.headers[REQUEST_ID_HEADER] = request_id
        # The matched TEMPLATE, not the concrete path (FS-1015): `/assets/{asset_id}`
        # rather than `/assets/9f2c...`, or every id becomes its own metric series. Only
        # read on the response path, where `scope["route"]` is still present.
        route = getattr(request.scope.get("route"), "path", None)
        record_http(request.method, response.status_code, elapsed, route=route)
        logger.info(
            "request_completed",
            method=request.method,
            path=request.url.path,
            status_code=response.status_code,
            duration_ms=round(elapsed * 1000, 2),
        )
        structlog.contextvars.unbind_contextvars("request_id")
        return response


def outbound_correlation_headers() -> dict:
    """Headers carrying this request's correlation id to an OUTBOUND call (FS-1014).

    THE ID STOPPED AT THE PROCESS BOUNDARY. `RequestContextMiddleware` binds
    `request_id` into structlog's contextvars, so every log line this process writes
    carries it — and then every ERP connector, every middleware integration and the MLOps
    registry client opened an `aiohttp` session with no correlation header at all.
    `grep -n "correlation_id" services/erp_connectors/ services/erp_middleware/` returned
    nothing across both directories.

    So a failing ERP webhook and the request that triggered it could not be joined: our
    side of the call is traceable, the vendor's side records an unattributed request, and
    the operator correlating them has a timestamp and hope. The counters and the retry
    classifier all work; what is missing is the thread between two systems.

    Read from structlog's contextvars rather than passed down through every call
    signature, because the alternative is threading a `request_id` parameter through the
    connector base class, five middleware services and their forty-odd call sites — which
    is the change nobody makes, which is why the header was never added.

    Returns an EMPTY dict outside a request (a scheduled worker, a startup task), rather
    than minting an id: a fresh id on an outbound call would look like correlation and
    correlate nothing, which is worse than its absence because it invites the reader to
    trust it.
    """
    bound = structlog.contextvars.get_contextvars()
    request_id = bound.get("request_id")
    return {REQUEST_ID_HEADER: str(request_id)} if request_id else {}
