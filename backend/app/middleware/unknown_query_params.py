"""Make an undeclared query parameter VISIBLE, without refusing it (FS-739).

THE DEFECT IS A WRONG ANSWER THAT LOOKS RIGHT. An unknown query parameter is silently
ignored, which is FastAPI's default:

    GET /api/v1/alarms?severty=critical      ->  200, EVERY alarm
    GET /api/v1/assets/?is_activ=true        ->  200, every asset, active or not

A caller who mistypes a filter gets a complete, well-formed, plausible answer to a question
they did not ask. The API contract gate reports it as `AcceptedNegativeData` on 14
operations — "in query - object with unexpected properties".

WHY THIS WARNS RATHER THAN REFUSES, which is the whole design decision.

The first version raised a 422. It worked, the frontend sends no undeclared parameter
(measured: 12 distinct keys, all declared), and it broke 15 tests — because those tests
encode a DELIBERATE compatibility guarantee, written down in
`test_yard_tenant_scoping_realdb.py`:

    An unknown query parameter must not error either — a client that has not been
    redeployed keeps working.

That is a decision, made with its reason, and this codebase's rule is that a recorded
decision is not overturned by whoever next has an opinion. A browser holding an old SPA is
exactly the stale client that sentence protects, and a 422 would break it on a request that
has always worked.

So the parameter is still ignored — behaviour is unchanged, every existing client keeps
working — and the fact is no longer silent. It is logged at WARNING with the route and the
offending names, and returned as `X-Unknown-Query-Parameters` so a developer sees it in the
network tab at the moment they make the typo. Refusing outright remains available and is
recorded in `docs/engineering/api-contract-gate.md` as the change it would be: a breaking
one, needing a deprecation window rather than a defect sweep.
"""

from __future__ import annotations

import structlog
from fastapi.routing import APIRoute
from starlette.requests import HTTPConnection

logger = structlog.get_logger()

#: Parameters accepted on any route because something other than the handler owns them.
#: Each earns its place; this is not somewhere to silence a noisy log line.
ALWAYS_ALLOWED = frozenset(
    {
        # Cache-busting, added by browsers and proxies rather than by our clients.
        "_",
        "_t",
        # Swagger UI's OAuth2 redirect round-trip.
        "code",
        "state",
    }
)

#: The response header carrying the names, so the typo is visible in a network tab.
HEADER = "X-Unknown-Query-Parameters"


def _declared(route: APIRoute) -> set[str]:
    """Every query parameter name this route can consume.

    `dependant.query_params` is flattened by FastAPI across nested `Depends`, so a filter
    model bound with `Depends()` contributes its fields here too.
    """
    names = {param.name for param in route.dependant.query_params}
    for sub in route.dependant.dependencies:
        names |= {param.name for param in sub.query_params}
    return names


def unknown_query_params(connection: HTTPConnection) -> list[str]:
    """Names the caller sent that this route cannot read. Empty when there is nothing to
    say, including on any route that declares no query parameters at all — those may be
    reading `query_params` directly, and this cannot see that."""
    route = connection.scope.get("route")
    if not isinstance(route, APIRoute):
        return []
    declared = _declared(route)
    if not declared:
        return []
    return sorted(
        name
        for name in connection.query_params.keys()
        if name not in declared and name not in ALWAYS_ALLOWED
    )


async def note_unknown_query_params(connection: HTTPConnection) -> None:
    """Global dependency: record undeclared parameters without changing the response.

    `HTTPConnection`, NOT `Request`. A global dependency is applied to WEBSOCKET routes
    too, and asking for a `Request` there cannot be satisfied — every `/ws` connection was
    refused when this took one, which the websocket binding tests caught at once.
    """
    unknown = unknown_query_params(connection)
    if not unknown:
        return
    route = connection.scope.get("route")
    logger.warning(
        "unknown_query_parameters",
        path=getattr(route, "path", connection.url.path),
        unknown=unknown,
        hint="ignored by the handler; check for a typo in a filter name",
    )
    # Read by the middleware that owns the response, since a dependency cannot set a
    # header on a response that does not exist yet.
    connection.scope.setdefault("state", {})
    connection.scope["state"]["unknown_query_params"] = unknown
