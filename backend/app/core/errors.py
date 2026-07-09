"""Centralized API error envelope + exception handlers (task 7).

Gives every 4xx/5xx a consistent JSON shape so clients (and the generated SDK,
task 11) can handle errors uniformly:

    {
      "error": {"code": "not_found", "message": "...", "details": {...},
                "trace_id": "..."},
      "detail": "..."          # mirror of message, for backward compatibility
    }

The ``detail`` mirror is deliberate: FastAPI's default error body is
``{"detail": ...}`` and existing callers/tests read it, so keeping it makes this
additive rather than breaking. ``trace_id`` is pulled from the request-context
middleware (task 9) when present, tying an error response to its trace.

This is response *shape* only — distinct from the error-capture/triage subsystem
owned on the integration branch.
"""

from typing import Any, Dict, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import structlog

logger = structlog.get_logger()


class AppError(Exception):
    """Application error carrying a machine code + HTTP status + details.

    Raise this from services/routers when you want a stable ``code`` in the
    envelope; plain ``HTTPException`` still works and is wrapped too.
    """

    def __init__(
        self,
        message: str,
        code: str = "error",
        status_code: int = status.HTTP_400_BAD_REQUEST,
        details: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.message = message
        self.code = code
        self.status_code = status_code
        self.details = details or {}


# Map common HTTP statuses to stable machine codes for the envelope.
_STATUS_CODE = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "unavailable",
}


def _trace_id(request: Request) -> Optional[str]:
    return getattr(request.state, "request_id", None)


def _envelope(
    message: str, code: str, status_code: int, details: Any, trace_id: Optional[str]
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "trace_id": trace_id,
            },
            "detail": message,  # backward-compatible mirror
        },
    )


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the envelope handlers onto a FastAPI app."""

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return _envelope(exc.message, exc.code, exc.status_code, exc.details, _trace_id(request))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODE.get(exc.status_code, "error")
        # exc.detail may be a str or a structured payload; normalize to message.
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        details = {} if isinstance(exc.detail, str) else {"detail": exc.detail}
        return _envelope(message, code, exc.status_code, details, _trace_id(request))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(
            "request validation failed",
            "validation_error",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"errors": exc.errors()},
            _trace_id(request),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Never leak internals; log with the trace id for correlation.
        tid = _trace_id(request)
        logger.error("unhandled_exception", error=str(exc), trace_id=tid, path=request.url.path)
        return _envelope("internal server error", "internal_error", 500, {}, tid)
