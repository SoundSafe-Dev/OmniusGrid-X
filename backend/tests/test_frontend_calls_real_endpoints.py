"""Every endpoint the frontend calls in REAL mode must exist on the backend.

THE DEFECT CLASS. `src/test/setup.ts` forces `VITE_USE_MOCK='true'` before any module
evaluates, and `src/api/mockMode.ts` reads it into a module-level `const USE_MOCK`. So
every frontend unit test has always taken the mock branch of the ~213 `if (USE_MOCK)`
forks across `src/api/`. The real branch — the code that actually runs in production —
is executed by no test at all, which means a wrong path or a wrong method sits there
indefinitely and surfaces as a 404 in front of a user.

This is the same shape as the ERP "invented endpoints" sweep, moved to our own
frontend/backend seam, and the same shape as the tenant-DB overrides: **the suite was
exercising a double instead of the thing that ships.**

WHAT IT FOUND. 183 real-mode calls across 22 modules; four that the backend does not
serve, all confirmed against the live route table and by issuing the request in-process:

    PATCH /api/v1/fleet/security/events/{id}   404   <- LIVE: wired to a UI button
    PATCH /api/v1/fleet/dtcs/{code}            404   uncalled
    GET   /api/v1/transportation/vehicles/{id} 404   uncalled
    GET   /api/v1/yard/moves                   405   uncalled (POST-only path)

The live one was the worst: `HealthSecurityPanel` awaits it with no `catch`, so axios
rejects on the 404, the optimistic state update never runs, and an operator clicking
"acknowledge" on a fleet security event sees nothing happen and no error.

WHY A ROUTE-TABLE CHECK AND NOT A MOCK SERVER. This asserts the one property a mock can
never confirm: that the path exists on the real app. It deliberately does NOT check
request bodies or response shapes — those need real-mode tests per module
(`src/test/realMode.ts`) and are a different job. Cheap, total coverage of the failure
mode that actually happened.
"""

from __future__ import annotations

import pathlib
import re
from typing import Dict, List, Set, Tuple

import pytest

from app.main import app

FRONTEND_API = pathlib.Path(__file__).resolve().parents[2] / "frontend" / "src" / "api"

#: OpenAPI puts non-method keys (`parameters`, `summary`) alongside the verbs.
HTTP_METHODS = {"get", "post", "put", "patch", "delete", "head", "options"}

#: `api.get<Foo>('/path')` / ``api.post(`/path/${id}`)`` across all five verbs.
CALL = re.compile(
    r"api\.(get|post|put|patch|delete)\s*(?:<[^;{]*?>)?\s*\(\s*([`'\"])([^`'\"]+)\2",
    re.S,
)

#: A path parameter is ALWAYS preceded by a slash: `/users/${id}`. A `${...}` glued to
#: the end of a segment is a query-string suffix — `` `/x/entities${q}` `` where
#: `q = '?entity_type=...'` — and must be dropped rather than turned into a segment.
#: Getting this wrong is not hypothetical: it made the first run of this sweep report
#: `/api/v1/erp/integrations/{id}/entities{q}` as a missing endpoint. The detector was
#: wrong, not the code, which is why `TestTheExtractor` below runs first.
PATH_PARAM = re.compile(r"/\$\{[^}]+\}")
GLUED_SUFFIX = re.compile(r"(?<!/)\$\{[^}]+\}")


def normalise(raw: str) -> str:
    """A frontend URL reduced to a comparable path shape."""
    path = raw.split("?")[0]
    path = PATH_PARAM.sub("/{param}", path)
    path = GLUED_SUFFIX.sub("", path)
    return path.rstrip("/") or "/"


def _route_table() -> Dict[str, Set[str]]:
    """{normalised path: {methods}} derived from the app itself, live.

    Built from `app.openapi()` rather than a checked-in `openapi.json`, because a guard
    validating against a stale artifact reports on a backend that no longer exists.

    NOT from `app.routes`: this app includes routers lazily behind an `_IncludedRouter`
    wrapper, so at import time `app.routes` holds 74 entries covering none of the API —
    reading it produced 185 "missing endpoint" failures against a backend that serves
    every one of them. `app.openapi()` resolves the wrappers (373 paths), and is the
    same source that feeds the SDK codegen.
    """
    table: Dict[str, Set[str]] = {}
    for path, operations in app.openapi()["paths"].items():
        key = re.sub(r"\{[^}]+\}", "{param}", path.rstrip("/")) or "/"
        table.setdefault(key, set()).update(
            method.lower() for method in operations if method.lower() in HTTP_METHODS
        )
    return table


def _frontend_calls() -> List[Tuple[str, int, str, str, str]]:
    """(module, line, method, raw url, normalised path) for every api.* call."""
    calls = []
    for path in sorted(FRONTEND_API.glob("*.ts")):
        if ".test." in path.name:
            continue
        source = path.read_text()
        for match in CALL.finditer(source):
            method, raw = match.group(1), match.group(3)
            if not raw.startswith("/"):
                continue  # relative or composed elsewhere; out of scope
            line = source[: match.start()].count("\n") + 1
            calls.append((path.name, line, method, raw, normalise(raw)))
    return calls


ROUTES = _route_table()
CALLS = _frontend_calls()


class TestTheExtractor:
    """Runs first because every assertion below depends on it, and its first version
    was wrong."""

    def test_a_path_parameter_becomes_a_segment(self):
        assert normalise("/api/v1/nlp/sessions/${sessionId}") == "/api/v1/nlp/sessions/{param}"
        assert normalise("/a/${x}/b/${y}") == "/a/{param}/b/{param}"

    def test_a_glued_template_is_a_query_suffix_not_a_segment(self):
        """`` `/x/entities${q}` `` with `q = '?entity_type=erp'` is ONE path plus a
        query, not a two-segment path. Reading it as a segment manufactures a missing
        endpoint that is not missing."""
        assert normalise("/api/v1/erp/integrations/${id}/entities${q}") == (
            "/api/v1/erp/integrations/{param}/entities"
        )

    def test_a_literal_query_string_is_dropped(self):
        assert normalise("/api/v1/alarms/active?limit=10") == "/api/v1/alarms/active"

    def test_a_trailing_slash_does_not_change_the_path(self):
        assert normalise("/api/v1/alarm-rules/") == normalise("/api/v1/alarm-rules")


class TestTheSweepIsNotVacuous:
    def test_it_found_calls_to_check(self):
        """A moved directory or a changed client idiom would otherwise make every
        assertion below pass while checking nothing."""
        assert len(CALLS) >= 150, (
            f"only {len(CALLS)} frontend api calls extracted from {FRONTEND_API}; "
            f"the sweep is not reaching them"
        )

    def test_it_covers_many_modules(self):
        assert len({c[0] for c in CALLS}) >= 15

    def test_it_found_the_backend_routes(self):
        assert len(ROUTES) >= 200, f"only {len(ROUTES)} routes read off the app"

    def test_a_known_good_call_resolves(self):
        """If the matcher could not confirm a route that definitely exists, a green
        run would mean nothing."""
        assert "/api/v1/alarms/active" in ROUTES
        assert "get" in ROUTES["/api/v1/alarms/active"]

    def test_a_route_the_backend_does_not_have_is_detected(self):
        """Proves the check can fail, using a path no router defines."""
        assert normalise("/api/v1/definitely/not/a/route") not in ROUTES


@pytest.mark.parametrize(
    "module,line,method,raw,path",
    CALLS,
    ids=[f"{m}:{ln}:{meth}" for m, ln, meth, _raw, _p in CALLS],
)
def test_the_backend_serves_this_call(module, line, method, raw, path):
    methods = ROUTES.get(path)
    assert methods is not None, (
        f"frontend/src/api/{module}:{line} calls {method.upper()} {raw}, which resolves "
        f"to {path} — no such route on the backend. In mock mode this is invisible; in "
        f"production it is a 404 in front of a user."
    )
    assert method in methods, (
        f"frontend/src/api/{module}:{line} calls {method.upper()} {raw}, but the backend "
        f"serves {sorted(m.upper() for m in methods)} on {path}."
    )
