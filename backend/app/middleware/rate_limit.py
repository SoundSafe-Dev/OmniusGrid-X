"""Rate limiting middleware using slowapi with Redis backend.

General API limits remain gated on settings.RATE_LIMIT_ENABLED. Authentication
and remote agent-operation limits use separate always-enabled limiters, so
disabling the global limiter cannot disable brute-force or remote-action
protection.
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
from slowapi.middleware import (
    SlowAPIMiddleware,
    _find_route_handler,
    _should_exempt,
    async_check_limits,
)
from slowapi.util import get_remote_address

from app.core.errors import problem_response
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
            # FS-910. `jwt.decode` is the only thing this try can fail on, and its
            # failures are all `jwt.PyJWTError` subclasses -- the same narrowing
            # `get_tenant_key_from_request`'s sibling catch already carries. `except
            # Exception` here was one broad catch too many for the same fallback.
            except jwt.PyJWTError:
                pass
            return f"user:{hashlib.sha256(token.encode()).hexdigest()[:32]}"
    # FS-970, finishing what FS-910 started one nesting level in. The outer catch here was
    # `except Exception: pass`, left alone by FS-910 as defence in depth.
    #
    # WHAT CAN ACTUALLY RAISE, checked rather than assumed -- and the first answer was
    # wrong. The draft of this narrowing also caught `UnicodeError`, reasoning that a
    # client could put a raw 0xE9 in the Authorization header, that Starlette decodes
    # header bytes as latin-1, and that `token.encode()` in the hash fallback below would
    # then fail on a lone surrogate. The test written for it failed: latin-1 maps every
    # byte 0x00-0xFF to codepoint U+0000-U+00FF, all of which encode to UTF-8 perfectly
    # well, so `b"Bearer abc\xe9def"` arrives as `'Bearer abcédef'` and hashes fine.
    # Lone surrogates come from `errors="surrogateescape"`, which is not what Starlette
    # does. **UnicodeEncodeError is not reachable here through a real request**, and
    # claiming it in a catch tuple would have been a guess dressed as a precaution.
    #
    # What remains is AttributeError: this being handed something that is not a Request
    # (a test double, a middleware ordering mistake). Everything else -- a TypeError from
    # a rename, a KeyError from a refactor -- is a bug, and now propagates.
    #
    # AND IT IS LOGGED, because the fallback is not free. Every request landing here is
    # bucketed by IP rather than by user, so a whole NAT or VPN egress shares one budget;
    # if extraction broke for ALL requests, the per-user rate limit would silently become
    # a per-IP one with nothing anywhere saying so.
    except AttributeError as exc:
        logger.warning(
            "rate_limit_key_fell_back_to_ip",
            error=str(exc),
            error_type=type(exc).__name__,
        )

    return f"ip:{get_remote_address(request)}"


def get_tenant_key_from_request(request: Request) -> str:
    """Return the rate-limit key for the ORGANISATION a request belongs to (FS-843).

    THE DEFECT THIS EXISTS FOR. `get_user_id_from_request` keys on the token's `sub`, so
    the budget is per person and a tenant's share of the platform scaled with its
    headcount — 500 users meant 500x the budget of a single-user tenant. Nothing bounded
    an organisation as a whole, so the noisiest neighbour was structurally the largest
    customer and the only lever was throttling one user at a time while the other 499
    carried on.

    Read from the `org` claim, decoded WITHOUT signature verification. That is correct
    here and would not be for authorisation: this only chooses a counter, and the real
    identity check happens in the endpoint's auth dependency. A forged claim can only move
    the forger into another tenant's bucket, which throttles the forger.

    THE FALLBACK IS DELIBERATELY PER-USER, NOT A SHARED BUCKET. A token minted before this
    claim existed has no `org`, and so does a user who has not been attached to one. Both
    fall back to the per-user key, which means such a request is bounded by the per-user
    limit and escapes the tenant cap. The alternative — a shared `tenant:unknown` bucket —
    would throttle every unattached user against every other one, which is a worse failure
    than a 30-minute gap while old access tokens expire.
    """
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == "dev-token":
            return "tenant:dev-org"
        try:
            claims = jwt.decode(token, options={"verify_signature": False})
            org = claims.get("org")
            if org:
                return f"tenant:{org}"
        except jwt.PyJWTError:
            pass
    # No org to bill this to. Fall back to the caller's own key so the request is still
    # counted somewhere rather than sharing a bucket with unrelated callers.
    return get_user_id_from_request(request)


def get_auth_client_key(request: Request) -> str:
    """Key authentication budgets by source IP, never by supplied tokens."""
    return f"auth-ip:{get_remote_address(request)}"


def get_remote_operation_key(request: Request) -> str:
    """Key remote-operation budgets by authenticated subject and target asset."""

    asset_id = str(request.path_params.get("asset_id") or "unknown")
    auth_header = request.headers.get("Authorization", "")
    if auth_header.startswith("Bearer "):
        token = auth_header[7:]
        if token == "dev-token":
            subject = "dev-user"
        else:
            try:
                claims = jwt.decode(token, options={"verify_signature": False})
                subject = str(UUID(str(claims.get("sub"))))
            except (jwt.PyJWTError, ValueError, TypeError):
                # NARROWED to what the two calls raise (FS-693's ratchet payment):
                # jwt.decode raises PyJWTError subclasses on a malformed token, and
                # UUID() raises ValueError/TypeError on a sub claim that is not one.
                # Authentication still validates the bearer token. This fallback
                # avoids putting the credential itself in a key.
                subject = hashlib.sha256(token.encode("utf-8")).hexdigest()[:24]
        return f"remote-user:{subject}:asset:{asset_id}"
    return f"remote-ip:{get_remote_address(request)}:asset:{asset_id}"


# in_memory_fallback_enabled: if Redis is unreachable, fall back to per-process
# counters instead of raising. Fleet-wide limits become per-worker limits, which
# is weaker — but a rate limiter must never convert a cache outage into an API
# outage. swallow_errors covers transient storage errors mid-request the same way.
limiter = Limiter(
    key_func=get_user_id_from_request,
    storage_uri=settings.REDIS_URL,
    in_memory_fallback_enabled=True,
    swallow_errors=True,
    default_limits=[settings.RATE_LIMIT_GLOBAL],
    # headers_enabled=False: slowapi would otherwise require every decorated
    # endpoint to accept a ``response: Response`` kwarg for header injection.
    # 429 responses still carry Retry-After / X-RateLimit-Limit via the
    # exception handler below.
    headers_enabled=False,
    enabled=settings.RATE_LIMIT_ENABLED,
)

# THE TENANT BUDGET (FS-843), a second dimension rather than a replacement. The per-user
# limiter above still protects one user from a runaway client; this one protects every
# other tenant from one organisation as a whole. Both apply, and a request must pass both.
#
# Shares slowapi's fallback semantics on purpose — `in_memory_fallback_enabled` and
# `swallow_errors` for the reason written above the first limiter: a rate limiter must
# never convert a Redis outage into an API outage. Under fallback a fleet-wide tenant cap
# degrades to a per-process one, which is weaker and still bounded.
tenant_limiter = Limiter(
    key_func=get_tenant_key_from_request,
    storage_uri=settings.REDIS_URL,
    in_memory_fallback_enabled=True,
    swallow_errors=True,
    default_limits=[settings.RATE_LIMIT_PER_TENANT],
    headers_enabled=False,
    enabled=settings.RATE_LIMIT_ENABLED,
)


# This limiter is intentionally independent from RATE_LIMIT_ENABLED. Auth
# decorators execute their own checks, so they do not require the optional
# application-wide SlowAPI middleware.
# This one matters most: it is deliberately enabled=True always, so before the
# fallback below an unreachable Redis raised on EVERY /auth request — turning a
# Redis outage into a total authentication outage (login and register 500). Redis
# also has no Deployment in the k8s stack yet (FS-196), so that was the default
# state, not an edge case. Brute-force protection now degrades to per-process
# counters rather than locking everyone out.
auth_limiter = Limiter(
    key_func=get_auth_client_key,
    storage_uri=settings.REDIS_URL,
    in_memory_fallback_enabled=True,
    swallow_errors=True,
    headers_enabled=False,
    enabled=True,
)

# Remote agent actions remain protected even when the optional global API
# limiter is disabled. The route-specific decorators set separate read and
# collector-restart budgets.
remote_operation_limiter = Limiter(
    key_func=get_remote_operation_key,
    storage_uri=settings.REDIS_URL,
    in_memory_fallback_enabled=True,
    swallow_errors=True,
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
    # THE SHARED ENVELOPE, not a bare `{"detail": ...}`. Every other error in this API is
    # `application/problem+json` with a type, title, status and trace id — that is what the
    # OpenAPI document declares for 429 on every route and what the generated SDK parses.
    # This handler answered plain JSON, making 429 the one error shape a client could not
    # handle generically, and 429 is the error most likely to be handled programmatically:
    # the correct response to it is to back off and retry. Found by the contract gate as
    # the single "Response violates schema" failure across 546 operations.
    #
    # `Retry-After` and `X-RateLimit-Limit` are passed THROUGH the envelope rather than set
    # on the response afterwards: `_envelope` rebuilds the response object, and a header
    # attached to the old one would be dropped — the same mistake that once lost `Allow` on
    # a 405 and `WWW-Authenticate` on a 401, recorded in `app/core/errors.py`.
    return problem_response(
        request,
        message=f"Rate limit exceeded: {exc.detail}. Please slow down and try again.",
        code="rate_limit_exceeded",
        status_code=429,
        headers={"Retry-After": "60", "X-RateLimit-Limit": str(exc.detail)},
    )


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


def remote_operation_rate_limit(limit: str) -> Callable:
    """Always enforce a per-user, per-target remote-operation budget."""

    def decorator(func: Callable) -> Callable:
        _resolve_postponed_annotations(func)
        return remote_operation_limiter.limit(limit)(func)

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


class TenantRateLimitMiddleware(SlowAPIMiddleware):
    """Apply the tenant budget alongside the per-user one (FS-843).

    `SlowAPIMiddleware` reads `app.state.limiter`, so one instance can enforce exactly one
    dimension. This subclass changes only which limiter it reads, inheriting slowapi's
    route-exemption handling, storage fallback and 429 translation rather than
    reimplementing them — a second copy of that logic is a second thing to keep correct.

    SAFE TO RUN BESIDE THE FIRST because neither middleware sets
    `request.state._rate_limiting_complete`; that flag belongs to the `@limit` DECORATOR
    path, and it is what stops a decorated endpoint being counted twice. Both middlewares
    therefore evaluate, and a request has to satisfy both budgets.
    """

    async def dispatch(self, request: Request, call_next):
        app = request.app
        limiter = app.state.tenant_limiter

        if not limiter.enabled:
            return await call_next(request)

        handler = _find_route_handler(app.routes, request.scope)
        if _should_exempt(limiter, handler):
            return await call_next(request)

        error_response, _ = await async_check_limits(limiter, request, handler, app)
        if error_response is not None:
            return error_response
        return await call_next(request)
