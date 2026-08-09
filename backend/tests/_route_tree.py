"""Walking the mounted route tree — one implementation, shared.

NOT a test module. Imported by the guards that need to enumerate what the app
actually serves.

WHY THIS IS EXTRACTED RATHER THAN COPIED. FastAPI >= 0.130 keeps
``include_router()`` results as lazy ``_IncludedRouter`` entries, so ``app.routes``
holds ~74 objects of which only 2 are real ``APIRoute``s — the other 451 live
inside containers whose children carry RELATIVE paths, with the prefix on the
container's ``include_context``.

A walk that does not recurse therefore sees a handful of routes, finds nothing
wrong with them, and passes. That is the failure mode this repository has a rule
for: a guard that cannot see its subject is worse than no guard, because it
reports the absence of evidence as evidence of absence. `test_route_auth_walk`
carries the scar in a comment; a second copy of the traversal would be free to
regress independently of the first, which is defect class 7 — a test double that
reimplements what it stands in for.
"""

from __future__ import annotations

from typing import Iterator, Tuple

from starlette.routing import Route

#: Paths FastAPI mounts for its own docs. Not part of the API surface.
DOC_PATHS = frozenset(
    {"/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
)

#: Methods every route answers implicitly; their presence says nothing.
IMPLICIT_METHODS = frozenset({"HEAD", "OPTIONS"})


def flatten(routes, prefix: str = "") -> Iterator[Tuple[object, str]]:
    """Recursively expand router containers, carrying include prefixes.

    Yields ``(route, prefix)``. The caller joins them — the child's ``path`` is
    relative to everything above it.
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


def http_routes(app) -> Iterator[Tuple[Route, str, set]]:
    """Every HTTP route the app serves, as ``(route, full_path, methods)``.

    Excludes websockets, mounts, the docs endpoints, and the implicit
    HEAD/OPTIONS that every route answers.
    """
    for route, prefix in flatten(app.routes):
        if not isinstance(route, Route):  # skips WebSocketRoute (/ws) + mounts
            continue
        path = prefix + route.path
        if path in DOC_PATHS:
            continue
        methods = (route.methods or set()) - IMPLICIT_METHODS
        if not methods:
            continue
        yield route, path, methods
