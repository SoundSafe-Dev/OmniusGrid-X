"""Reject oversized uploads from ``Content-Length``, before the body is read.

FastAPI resolves an ``UploadFile`` parameter by parsing the whole multipart
body first, so any size check written inside the handler necessarily runs
*after* the request has been buffered. That is too late to be a real guard: by
then the bytes have already been spooled. This middleware runs before routing,
so it can refuse the request on the declared ``Content-Length`` alone and never
touch the body.

It is scoped to specific path prefixes rather than applied globally — the cap
it enforces is the RAG document cap, which has nothing to say about the size of
a telemetry batch or a config bundle. Production ingress enforces the same
number at the edge; this keeps the limit honest on the paths ingress does not
cover (local compose, in-cluster calls straight to the Service).

``Content-Length`` measures the multipart envelope, which is slightly larger
than the file inside it. The handler still re-checks the real spooled size, so
this layer only has to be approximately right in the caller's favour — hence
the deliberate slack allowed for the envelope.
"""

from typing import Sequence

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse

logger = structlog.get_logger()

# Headroom for multipart framing (boundaries, per-part headers, filename) so a
# file that is legitimately just under the cap is not rejected for its envelope.
_MULTIPART_OVERHEAD_BYTES = 8 * 1024


class UploadLimitMiddleware(BaseHTTPMiddleware):
    """413 a request whose declared body exceeds ``max_bytes`` on a watched path."""

    def __init__(self, app, *, max_bytes: int, prefixes: Sequence[str]) -> None:
        super().__init__(app)
        self.max_bytes = max_bytes
        self.prefixes = tuple(prefixes)

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith(self.prefixes):
            return await call_next(request)

        raw_length = request.headers.get("content-length")
        if raw_length is not None:
            try:
                declared = int(raw_length)
            except ValueError:
                declared = -1
            if declared > self.max_bytes + _MULTIPART_OVERHEAD_BYTES:
                logger.warning(
                    "upload_limit.rejected",
                    path=request.url.path,
                    declared_bytes=declared,
                    limit_bytes=self.max_bytes,
                )
                return JSONResponse(
                    status_code=413,
                    content={
                        "detail": (
                            f"File too large ({declared} bytes); the limit is "
                            f"{self.max_bytes} bytes."
                        )
                    },
                )

        return await call_next(request)
