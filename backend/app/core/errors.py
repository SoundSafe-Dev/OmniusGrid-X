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

from typing import Any, Dict, Mapping, Optional

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
import re

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


# RFC-9457 (problem+json) additive layer (FS-102).
#
# We keep the existing ``error``/``detail`` members untouched for backward
# compatibility and ADD the four standard problem members alongside them, so a
# single body satisfies both existing callers and RFC-9457 consumers.
#
# Content-Type choice: error responses now advertise
# ``application/problem+json`` (the RFC-9457 media type). This is safe because
# the body is still valid JSON — httpx/TestClient ``.json()`` and existing tests
# read the parsed body regardless of media type, and the only content-type
# assertion in the suite is on a 2xx download response, which these handlers do
# not touch. Kept as a module constant so it is easy to flip back to
# ``application/json`` if a downstream consumer ever requires the narrower type.
PROBLEM_JSON = "application/problem+json"
_PROBLEM_TYPE_BASE = "https://omniusgrid.dev/problems/"


def _problem_type(code: str) -> str:
    """Stable, dereferenceable-looking problem type URI per machine code."""
    if not code or code == "error":
        return "about:blank"
    return _PROBLEM_TYPE_BASE + code


def _problem_title(code: str) -> str:
    """Short human-readable summary derived from the machine code."""
    if not code:
        return "Error"
    return code.replace("_", " ").title()


def _envelope(
    message: str,
    code: str,
    status_code: int,
    details: Any,
    trace_id: Optional[str],
    instance: Optional[str] = None,
    headers: Optional[Mapping[str, str]] = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        media_type=PROBLEM_JSON,
        # Headers the raiser attached are part of the response's MEANING, not
        # decoration: RFC 9110 makes `Allow` on a 405 and `WWW-Authenticate` on a
        # 401 mandatory, and a client that follows the spec cannot act on either
        # response without them. Starlette's router raises 405 with `Allow`
        # already set and FastAPI's auth dependencies raise 401 with the
        # challenge; this envelope rebuilt the response and dropped both.
        headers=dict(headers) if headers else None,
        content={
            # RFC-9457 standard members (additive).
            "type": _problem_type(code),
            "title": _problem_title(code),
            "status": status_code,
            "instance": instance or trace_id,
            # Existing OmniusGrid envelope (unchanged, backward-compatible).
            "error": {
                "code": code,
                "message": message,
                "details": details or {},
                "trace_id": trace_id,
            },
            "detail": message,  # backward-compatible mirror
        },
    )


def _is_nul_byte_error(exc: BaseException) -> bool:
    """True when this exception is Postgres rejecting a NUL byte in the input.

    Walks ``__cause__``/``__context__`` because SQLAlchemy wraps the driver error
    twice — asyncpg's CharacterNotInRepertoireError arrives inside an
    AsyncAdapt_asyncpg_dbapi.Error inside a sqlalchemy.exc.DBAPIError — so matching on
    the outermost type would never fire.

    Matches on the class NAME rather than importing asyncpg, so the check costs nothing
    when the driver changes and cannot break the error handler by failing to import. The
    message test is the belt to that braces: 0x00 is the only byte that produces this
    error for UTF-8 input.
    """
    seen = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ == "CharacterNotInRepertoireError":
            return True
        text = str(current)
        if "invalid byte sequence for encoding" in text and "0x00" in text:
            return True
        current = current.__cause__ or current.__context__
    return False


_FK_DETAIL = re.compile(
    r'Key \((?P<column>[\w, ]+)\)=\([^)]*\) is not present in table "(?P<table>\w+)"'
)


def _foreign_key_target(exc: BaseException) -> Optional[Dict[str, str]]:
    """Return {column, table} when this is Postgres rejecting an unknown reference.

    A foreign-key violation says the row you pointed at does not exist. In a request
    context that pointer came from the payload — `trailer_id`, `shipment_id`,
    `dock_door_id` — so it is the caller's mistake, and 500 both misleads them and
    buries a real 4xx in the error budget.

    THE RESPONSE NAMES THE COLUMN AND TABLE, and nothing else. Postgres's DETAIL line
    also contains the offending VALUE, which may be another tenant's identifier; echoing
    it back would turn an error message into a probe for what exists. The constraint name
    is likewise withheld — it is schema shape the caller has no use for.
    """
    seen = set()
    current: Optional[BaseException] = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if type(current).__name__ == "ForeignKeyViolationError" or "violates foreign key constraint" in str(current):
            match = _FK_DETAIL.search(str(current))
            if match:
                return {"column": match.group("column"), "table": match.group("table")}
            return {"column": "", "table": ""}
        current = current.__cause__ or current.__context__
    return None


def _instance(request: Request) -> Optional[str]:
    try:
        return request.url.path
    except Exception:  # pragma: no cover - defensive
        return None


def _jsonable_validation_errors(exc: RequestValidationError) -> Any:
    """`exc.errors()`, made encodable — WITHOUT throwing the message away.

    A `@model_validator` that raises a bare `ValueError` (the documented way to express a
    cross-field rule) makes pydantic v2 put the LIVE EXCEPTION OBJECT in the error's
    `ctx`:

        {'type': 'value_error', 'msg': 'Value error, ...',
         'ctx': {'error': ValueError('retention days must satisfy hot <= warm <= cold')}}

    `JSONResponse` then calls `json.dumps` on it, raises
    `TypeError: Object of type ValueError is not JSON serializable`, and the generic
    handler below turns that into a **500**. So every request that violated a cross-field
    rule got a server error where the schema promises 422 — the validator worked
    perfectly and the envelope reporting it was what failed.

    Found by the contract gate (FS-259) on `PUT /data-retention/policies/{metric_name}`;
    it affects every model with such a validator, which today is that one plus the three
    in `twin_optimizer`.

    `jsonable_encoder` alone would fix the crash and encode the exception as `{}`, which
    silently drops the only text saying WHICH rule was broken. Stringifying it first keeps
    that, and `msg` and `ctx` then agree.
    """
    from fastapi.encoders import jsonable_encoder

    cleaned = []
    for error in exc.errors():
        error = dict(error)
        ctx = error.get("ctx")
        if isinstance(ctx, Mapping):
            error["ctx"] = {
                key: str(value) if isinstance(value, BaseException) else value
                for key, value in ctx.items()
            }
        cleaned.append(error)
    return jsonable_encoder(cleaned)


def register_exception_handlers(app: FastAPI) -> None:
    """Wire the envelope handlers onto a FastAPI app."""

    @app.exception_handler(AppError)
    async def _app_error(request: Request, exc: AppError) -> JSONResponse:
        return _envelope(
            exc.message, exc.code, exc.status_code, exc.details,
            _trace_id(request), _instance(request),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODE.get(exc.status_code, "error")
        # exc.detail may be a str or a structured payload; normalize to message.
        message = exc.detail if isinstance(exc.detail, str) else "request failed"
        details = {} if isinstance(exc.detail, str) else {"detail": exc.detail}
        return _envelope(
            message, code, exc.status_code, details,
            _trace_id(request), _instance(request),
            headers=getattr(exc, "headers", None),
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return _envelope(
            "request validation failed",
            "validation_error",
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            {"errors": _jsonable_validation_errors(exc)},
            _trace_id(request),
            _instance(request),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        tid = _trace_id(request)

        # A NUL byte in the request is a CLIENT error, and the only one of Postgres's
        # data errors that can be attributed to the request with certainty.
        #
        # Postgres text columns cannot store 0x00 at all, so a string containing one can
        # never be written however the endpoint is fixed — and nothing in this codebase
        # generates a NUL, so it arrived in the payload. Returning 500 told the caller
        # the server had broken and a retry might work, when the request was simply
        # unstorable.
        #
        # DELIBERATELY NARROW. The tempting version of this maps every asyncpg DataError
        # to 400, which would also relabel our own bad values — a wrong cast, a
        # miscomputed id — as the caller's fault and hide real defects behind a 4xx.
        # This matches one exception type whose cause is unambiguous. Everything else
        # stays a 500.
        if _is_nul_byte_error(exc):
            logger.warning(
                "request_contained_nul_byte", trace_id=tid, path=request.url.path
            )
            return _envelope(
                "Request contains a NUL byte (0x00), which cannot be stored.",
                "bad_request", 400, {}, tid, _instance(request),
            )

        # A reference to a row that does not exist is the caller's mistake.
        fk = _foreign_key_target(exc)
        if fk is not None:
            # STILL LOGGED AT ERROR. The status is now the caller's, but the cause might
            # not be: our own code can insert a bad reference too, and a 4xx that goes
            # unlogged would hide that class of bug completely. The status code answers
            # the client; the log entry keeps the server honest.
            logger.error(
                "foreign_key_violation",
                error=str(exc),
                trace_id=tid,
                path=request.url.path,
                referenced_table=fk["table"] or None,
                column=fk["column"] or None,
            )
            detail = (
                f"Reference in '{fk['column']}' does not exist in '{fk['table']}'."
                if fk["table"]
                else "The request references a record that does not exist."
            )
            return _envelope(detail, "bad_request", 400, {}, tid, _instance(request))

        # Never leak internals; log with the trace id for correlation.
        logger.error("unhandled_exception", error=str(exc), trace_id=tid, path=request.url.path)
        return _envelope("internal server error", "internal_error", 500, {}, tid, _instance(request))
