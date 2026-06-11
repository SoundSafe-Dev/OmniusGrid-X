"""Rate limiting middleware using slowapi with Redis backend.

Gated on ``settings.RATE_LIMIT_ENABLED`` so it can be toggled per
environment. Keys per authenticated user when a bearer token is present,
otherwise per remote IP.
"""

import re
from typing import Callable
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
            # Token prefix is sufficient for keying without decoding the
            # JWT on every request. The full identity check still happens
            # in the auth dependency on the endpoint itself.
            return f"user:{token[:16]}"
    except Exception:
        pass

    return f"ip:{get_remote_address(request)}"


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
        return limiter.limit(limit)(func)

    return decorator
