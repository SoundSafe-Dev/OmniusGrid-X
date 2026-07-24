"""Rate limiting middleware using slowapi with Redis backend.

General API limits remain gated on settings.RATE_LIMIT_ENABLED.
Authentication limits use a separate always-enabled limiter keyed by client
IP so disabling the global limiter cannot disable brute-force protection.
"""

import hashlib
import re

import jwt
from typing import Callable, get_type_hints
from uuid import UUID

import structlog
from fastapi import Request
from fastapi.responses import JSONResponse
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.core.config import settings

logger = structlog.get_logger()

_COMPLIANCE_DOWNLOAD_PATH = re.compile(
    r"^/api/v1/compliance/reports/([0-9a-fA-F-]{36})/signed-download$"
)
_EXPORT_DOWNLOAD_PATH = re.compile(
    r"^/api/v1/exports/deliveries/([0-9a-fA-F-]{36})/download$"
)


def get_user_id_from_request(request: Request) -> str:
    """Return a stable rate-limit key for ``request``.

    Prefers a user identity derived from the bearer token so the budget
    travels with the user across IPs (mobile, VPN, NAT). Falls back to
    the client IP for unauthenticated requests.
    """
    try:
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            token = auth_header[7:]
            if token == "dev-token":
                return "user:dev-user"
            # Key by the token's `sub` (the user id). The previous `token[:16]`
            # was the base64 of the JWT header, which is IDENTICAL for every
            # HS256 token — so all authenticated users shared one bucket and any
            # one of them could throttle everyone. Decode is unverified on
            # purpose: this is only for bucketing, and the real identity/signature
            # check happens in the endpoint's auth dependency. Fall back to a hash
            # of the token (still per-token, never a shared constant) if the
            # token can't be parsed.
            try:
                claims = jwt.decode(token, options={"verify_signature": False})
                sub = claims.get("sub")
                if sub:
                    return f"user:{sub}"
            except Exception:
                pass
            return f"user:{hashlib.sha256(token.encode()).hexdigest()[:32]}"
    except Exception:
        pass

    return f"ip:{get_remote_address(request)}"


def get_auth_client_key(request: Request) -> str:
    """Key authentication budgets by source IP, never by supplied tokens."""
    return f"auth-ip:{get_remote_address(request)}"


limiter = Limiter(
    key_func=get_user_id_from_request,
    storage_uri=settings.REDIS_URL,
    default_limits=[settings.RATE_LIMIT_GLOBAL],
    # headers_enabled=False: slowapi would otherwise require every decorated
    # endpoint to accept a ``response: Response`` kwarg for header injection.
    # 429 responses still carry Retry-After / X-RateLimit-Limit via the
    # exception handler below.
    headers_enabled=False,
    enabled=settings.RATE_LIMIT_ENABLED,
)

# This limiter is intentionally independent from RATE_LIMIT_ENABLED. Auth
# decorators execute their own checks, so they do not require the optional
# application-wide SlowAPI middleware.
auth_limiter = Limiter(
    key_func=get_auth_client_key,
    storage_uri=settings.REDIS_URL,
    headers_enabled=False,
    enabled=True,
)


async def rate_limit_exceeded_handler(
    request: Request, exc: RateLimitExceeded
) -> JSONResponse:
    """Return a 429 response with rate-limit headers and an audit log line."""
    logger.warning(
        "rate_limit_exceeded",
        path=request.url.path,
        method=request.method,
        client_ip=get_remote_address(request),
        limit=str(exc.detail),
    )
    await _audit_public_download_rate_limit(request)
    response = JSONResponse(
        status_code=429,
        content={
            "detail": f"Rate limit exceeded: {exc.detail}. "
            "Please slow down and try again."
        },
    )
    response.headers["Retry-After"] = "60"
    response.headers["X-RateLimit-Limit"] = str(exc.detail)
    return response


async def _audit_public_download_rate_limit(request: Request) -> None:
    """Audit signed-download 429 responses without reading the credential."""
    compliance_match = _COMPLIANCE_DOWNLOAD_PATH.match(request.url.path)
    export_match = _EXPORT_DOWNLOAD_PATH.match(request.url.path)
    try:
        if compliance_match:
            from app.services.report_download_audit import (
                audit_compliance_report_download,
            )

            await audit_compliance_report_download(
                request=request,
                succeeded=False,
                job_id=UUID(compliance_match.group(1)),
                organization_id=None,
                reason="rate_limited",
            )
        elif export_match:
            from app.services.report_download_audit import (
                audit_export_delivery_download,
            )

            await audit_export_delivery_download(
                request=request,
                succeeded=False,
                job_id=UUID(export_match.group(1)),
                organization_id=None,
                reason="rate_limited",
            )
    except ValueError:
        return


def rate_limit(limit: str = "100/minute") -> Callable:
    """Decorator for rate-limiting specific endpoints."""

    def decorator(func: Callable) -> Callable:
        _resolve_postponed_annotations(func)
        return limiter.limit(limit)(func)

    return decorator


def auth_rate_limit(limit: str) -> Callable:
    """Always enforce an IP-based limit on an authentication endpoint."""

    def decorator(func: Callable) -> Callable:
        _resolve_postponed_annotations(func)
        return auth_limiter.limit(limit)(func)

    return decorator


def _resolve_postponed_annotations(func: Callable) -> None:
    """Resolve string annotations before SlowAPI moves the wrapper globals."""
    try:
        func.__annotations__ = get_type_hints(func)
    except (NameError, TypeError):
        # FastAPI can still resolve ordinary annotations itself. This fallback
        # preserves existing behavior for callables with intentionally local
        # or incomplete typing namespaces.
        return
