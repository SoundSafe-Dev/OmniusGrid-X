"""Shared route-walking helpers for the guard suites.

fastapi >=0.130 keeps include_router() results as lazy ``_IncludedRouter``
entries in ``app.routes``: the child ``Route.path`` is RELATIVE and the prefix
lives on the container's ``include_context``. Iterating ``app.routes`` directly
therefore visits only a handful of routes.

That is not a theoretical concern — test_route_auth_walk.py grew this recursion
after the fastapi upgrade, but test_realdb_endpoint_smoke.py kept walking
``app.routes`` and so probed 2 GET routes instead of ~200. It only failed loudly
because of its `tested > 150` sanity assertion; without that it would have
passed vacuously while testing nothing. Keep one definition so the next guard
inherits the fix.
"""
from __future__ import annotations

from starlette.routing import Route

DOC_PATHS = {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}


def flatten(routes, prefix: str = ""):
    """Recursively expand router containers, carrying include prefixes.

    Yields ``(route, prefix)`` pairs; the caller joins them.
    """
    for route in routes:
        ctx = getattr(route, "include_context", None)
        if ctx is not None:
            child_prefix = prefix + (getattr(ctx, "prefix", "") or "")
            yield from flatten(ctx.included_router.routes, child_prefix)
        elif getattr(route, "routes", None) is not None and not isinstance(route, Route):
            # Mount containers carry their own path prefix; plain routers don't.
            yield from flatten(route.routes, prefix + (getattr(route, "path", "") or ""))
        else:
            yield route, prefix


def http_paths(app, method: str = "GET", skip: set[str] | None = None):
    """Absolute paths of every HTTP route on ``app`` serving ``method``."""
    skip = (skip or set()) | DOC_PATHS
    seen: set[str] = set()
    for route, prefix in flatten(app.routes):
        if not isinstance(route, Route):  # skips WebSocketRoute (/ws) + mounts
            continue
        if method not in (getattr(route, "methods", None) or set()):
            continue
        path = prefix + route.path
        if path in skip or path in seen:
            continue
        seen.add(path)
        yield path
