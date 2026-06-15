"""Error-tracking middleware.

Catches unhandled exceptions as they propagate out of the route, records them
to the in-process aggregator (app/services/error_tracker.py), and re-raises
unchanged so the existing 500 behaviour, response shape, and the profiling
middleware's own exception accounting are all preserved.

Handled responses (2xx/3xx/4xx, including HTTPException, which FastAPI converts
to a response before it reaches here) pass straight through untouched. Only
genuinely unhandled exceptions are tracked.

Wiring lives in app/main.py via ``setup_error_tracking(app)``, called just
before ``setup_profiling(app)`` so this middleware sits *inside* profiling and
both observe the failure. The flush task lifecycle is owned by the
``error_tracker`` singleton, started/stopped in the app lifespan.
"""

from __future__ import annotations

import structlog
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from app.services.error_tracker import error_tracker

logger = structlog.get_logger()


def _endpoint_label(request: Request) -> str:
    """Matched route template, to keep fingerprint/label cardinality bounded.

    ``scope["route"]`` is not visible from a BaseHTTPMiddleware once an exception
    has propagated, but ``scope["path_params"]`` is — so when the route object is
    missing we rebuild the template by substituting each matched path-param value
    back into the concrete path (e.g. ``/items/42`` -> ``/items/{item_id}``).
    Without this, every distinct id would become its own fingerprint/label.
    """
    scope = request.scope
    route = scope.get("route")
    path = getattr(route, "path", None)
    if path:
        return path

    raw_path = scope.get("path") or request.url.path
    params = scope.get("path_params") or {}
    if not params:
        return raw_path

    value_to_name = {str(value): name for name, value in params.items()}
    segments = [
        "{" + value_to_name[seg] + "}" if seg in value_to_name else seg
        for seg in raw_path.split("/")
    ]
    return "/".join(segments)


def _organization_id(request: Request) -> str | None:
    """Best-effort org id if a prior layer stashed it on request.state.

    Auth is dependency-based (runs inside the route, not as middleware), so this
    is usually None at middleware level — recorded only when resolvable.
    """
    for attr in ("org_id", "organization_id"):
        value = getattr(request.state, attr, None)
        if value:
            return str(value)
    user = getattr(request.state, "user", None)
    org = getattr(user, "organization_id", None)
    return str(org) if org else None


class ErrorTrackingMiddleware(BaseHTTPMiddleware):
    """Record unhandled exceptions, then re-raise them unchanged."""

    async def dispatch(self, request: Request, call_next):
        if not error_tracker.enabled:
            return await call_next(request)
        try:
            return await call_next(request)
        except Exception as exc:
            # A bug in the tracker must never change what the client receives.
            try:
                await error_tracker.record(
                    exc,
                    method=request.method,
                    route=_endpoint_label(request),
                    organization_id=_organization_id(request),
                )
            except Exception:  # noqa: BLE001
                logger.exception("error_tracker_record_failed")
            raise


def setup_error_tracking(app) -> None:
    """Add the error-tracking middleware. Call once during app setup.

    When ERROR_TRACKING_ENABLED is False the middleware short-circuits on every
    request, so a disabled feature adds effectively no overhead. The background
    flush task is started separately by ``error_tracker.start()`` in the
    application lifespan.
    """
    app.add_middleware(ErrorTrackingMiddleware)
    logger.info("error_tracking_setup", enabled=error_tracker.enabled)
