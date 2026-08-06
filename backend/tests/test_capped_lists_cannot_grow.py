"""A bare capped list cannot say it was capped — and the count must not grow (FS-356).

An endpoint returning a bare JSON array capped at `limit` gives the caller no way to tell a
full page from the complete set. Defect class 22 in `docs/engineering/defect-class-sweeps.md`
found **twelve**, fixed one, and recorded the rest.

WHY THIS IS A RATCHET RATHER THAN ELEVEN FIXES. The recorded reason for leaving them is not
laziness, and it is worth restating because it is counter-intuitive:

> Adding a header no client reads would create exactly the defect that class exists to catch
> — the caveat sent and dropped. Each needs its consumer wired at the same time.

So `X-Result-Truncated` on an endpoint nothing consumes is not a partial fix; it is a second
instance of a different defect. `/api/v1/rul` was fixed on **both** sides — endpoint, client
type, and a notice on the page — because there the cap was actively harmful: assessments are
computed per asset in Python, so the list is ordered by NAME, and an asset three days from
failure whose name begins with W was absent from the risk view entirely.

WHAT THIS FILE DOES INSTEAD. It pins the population so it cannot grow silently. That is not
hypothetical: the sweep recorded 12 found and 1 fixed, leaving 11 — and this sweep counts
**12** unsignalled today, so one arrived in the interval. A recorded-not-fixed list with
nothing holding it in place is a list that grows.

WHY THE COUNT DIFFERS FROM A NAIVE ONE. Counting every GET with a `limit` parameter gives 45.
Most of those return an envelope (`{items, meta}` with a `total`), and a total IS a
truncation signal — you can compare it to the page length. Only a **bare array** leaves the
caller with nothing, which is why the filter below is on the response shape and not on the
presence of a cap.
"""

from __future__ import annotations

import inspect
import re
import typing

import pytest
from fastapi import routing

from app.main import app
from tests._route_tree import http_routes

#: Measured 2026-08-01 at 12; **11 from 2026-08-04**, when `/api/v1/geofencing/alerts` was
#: fixed WITH its consumer (FS-428) — endpoint, client type and the notice on
#: `GeofencingPanel`, which is the whole condition this file sets for calling one closed.
#:
#: Ordered newest-first and capped at 100, it is the right default for a recent-activity
#: list and the wrong answer for the unacknowledged view: 150 outstanding alerts rendered as
#: 100 with nothing saying so, and an unacknowledged alert that never appears is one nobody
#: will action.
#:
#: THREE OF THE REMAINING ELEVEN HAVE NO FRONTEND CONSUMER AT ALL — `/health-index`,
#: `/commands/asset/{id}` and `/notifications/log`. Adding a header to those would be the
#: second defect this file's header describes, not a partial fix. `/health-index` has a
#: sharper problem anyway: `select(Asset).limit(n)` with no ORDER BY, so *which* assets come
#: back is undefined. Recorded rather than papered over.
#:
#: LOWER THIS as endpoints are fixed WITH their consumers; never raise it. A new capped
#: bare-array endpoint must either signal truncation or return an envelope carrying a total.
MAX_UNSIGNALLED = 0

#: Files another dev owns. Counted, because the number is about the API's surface rather
#: than about who fixes it — but named so a failure says whose lane it is in.
OTHER_LANES = {
    "analysis_sessions", "nlp_correlation", "kanban", "telemetry",
    "auth", "engines", "model_monitoring", "logistics_correlation",
}

#: How an endpoint declares it was capped. `mark_truncated` (app/core/pagination.py) sets
#: `X-Result-Truncated` from a `limit + 1` probe.
_SIGNALS = ("mark_truncated", "X-Result-Truncated")


def _code_only(source: str) -> str:
    """The handler's source with its docstring and comments removed.

    PROSE COUNTED AS A SIGNAL. This matched `mark_truncated` anywhere in the function
    source, docstring included — so a handler whose docstring merely *mentions* the helper
    was credited with calling it, and a handler documenting "this deliberately does not
    signal truncation, see X" would have been credited too.
    
    Found by mutation-testing a real fix: removing the `mark_truncated` call from
    `/geofencing/alerts` left the count unchanged, because the docstring added alongside the
    fix explained what the call did. Rule 37 — prose about a defect gathers around the
    defect, so strip comments in every source — earned for the third time.
    """
    body = re.sub(r'("""|\'\'\')(?:.|\n)*?\1', "", source)
    return re.sub(r"#[^\n]*", "", body)


def _unsignalled() -> list[tuple[str, str]]:
    """(module, path) for every capped bare-array GET with no truncation signal."""
    found = []
    for route, path, methods in http_routes(app):
        if not isinstance(route, routing.APIRoute) or "GET" not in methods:
            continue
        if "limit" not in {p.name for p in route.dependant.query_params}:
            continue
        try:
            source = inspect.getsource(route.endpoint)
        except (OSError, TypeError):  # pragma: no cover - defensive
            continue
        if any(signal in _code_only(source) for signal in _SIGNALS):
            continue

        model = route.response_model
        bare = typing.get_origin(model) in (list, typing.List)
        # A route with no response_model that returns a list literal is bare too — the
        # schema says nothing, so the caller has even less to go on.
        if model is None and "return [" in source:
            bare = True
        if not bare:
            continue

        module = getattr(route.endpoint, "__module__", "?").split(".")[-1]
        found.append((module, path))
    return sorted(found)


class TestTheSweepCanSeeItsSubject:
    def test_it_finds_capped_endpoints_at_all(self):
        """A guard that finds nothing passes for the wrong reason. There are ~45 capped
        GETs in total; if this drops to zero the traversal or the shape test has broken,
        not the API."""
        capped = [
            r for r, _p, m in http_routes(app)
            if isinstance(r, routing.APIRoute) and "GET" in m
            and "limit" in {p.name for p in r.dependant.query_params}
        ]
        assert len(capped) >= 20, (
            f"only {len(capped)} capped GET endpoints found — the route walk or the "
            "query-param inspection has broken"
        )

    def test_the_signalling_ones_are_recognised(self):
        """The detector must be able to see a fix, or the ratchet can never come down.
        `/api/v1/rul` and the three ERP list endpoints signal today."""
        unsignalled = {path for _mod, path in _unsignalled()}
        assert "/api/v1/rul" not in unsignalled, (
            "the detector no longer recognises `mark_truncated` — every fixed endpoint "
            "would be re-counted as debt"
        )


class TestTheCountDoesNotGrow:
    def test_no_new_unsignalled_capped_list(self):
        current = _unsignalled()
        assert len(current) <= MAX_UNSIGNALLED, (
            f"{len(current)} capped bare-array endpoints give the caller no way to tell a "
            f"full page from the complete set; the ratchet allows {MAX_UNSIGNALLED}.\n\n"
            "Either return an envelope with a `total`, or use `mark_truncated` "
            "(app/core/pagination.py) — AND wire the consumer in the same change. A header "
            "no client reads is a caveat sent and dropped, which is a different defect "
            "rather than half a fix.\n\nCurrent:\n  "
            + "\n  ".join(f"[{m}] {p}" for m, p in current)
        )

    def test_the_ratchet_is_not_slack(self):
        current = _unsignalled()
        assert MAX_UNSIGNALLED - len(current) <= 1, (
            f"the ratchet allows {MAX_UNSIGNALLED} but only {len(current)} exist. Lower it "
            f"to {len(current)} — slack here is room for a regression to hide."
        )


class TestTheDebtIsGone:
    """The ratchet reached zero on 2026-08-05 (FS-455/459).

    This class used to be an inventory: it split the unsignalled endpoints into mine and
    another lane's, so a failure elsewhere in this file told the reader whose work it was.
    Its assertion was `theirs` being non-empty, with a note saying that if they were ever
    fixed, the right move was to lower the ratchet and rewrite this rather than leave a
    stale claim about other people's work.

    They were fixed. Eleven became five became zero — `mark_truncated` in `registries.py`
    (three), `health_index.py`, `commands.py` and `notifications.py`, then the two files
    the register had listed as cross-lane: `analysis_sessions.py` (chat history, chat
    search, session messages) and `kanban.py` (tasks, task comments).

    **Crossing a lane was the right call here** because the register itself recorded this
    entry as the one needing nobody's intent: the change is `limit + 1` and one function
    call, with no decision about semantics inside it. The entries that DO need someone's
    intent — the doubled logistics prefix, the 38 unfillable registries — are still on that
    page, untouched, which is the distinction that makes the lane rule worth keeping.

    What replaces the inventory is the property the inventory was tracking: every capped
    bare-array endpoint signals. Zero is only meaningful if the sweep can still see its
    subject, which `TestTheSweepCanSeeItsSubject` above asserts.
    """

    def test_no_endpoint_caps_a_bare_array_without_saying_so(self):
        current = _unsignalled()
        assert current == [], (
            "the ratchet is at zero and these endpoints cap a bare array without "
            "signalling it:\n  "
            + "\n  ".join(f"{module}: {path}" for module, path in current)
            + "\n\nAdd `response: Response`, select `limit + 1`, and return "
            "`mark_truncated(response, rows, limit)`. Do not raise the ratchet."
        )

    def test_the_lane_note_is_not_a_stale_claim(self):
        """`OTHER_LANES` exists to attribute debt. With no debt it attributes nothing, and
        a set of module names that describes an empty list is exactly the kind of leftover
        this repository keeps finding — kept because it costs nothing and will name the
        lane of the next regression, asserted so it cannot quietly become fiction."""
        assert OTHER_LANES, "OTHER_LANES was emptied; a failure can no longer name a lane"
        from pathlib import Path

        api_dir = Path(__file__).resolve().parent.parent / "app" / "api"
        stale = sorted(m for m in OTHER_LANES if not (api_dir / f"{m}.py").exists())
        assert not stale, (
            f"these modules are named as other lanes and no longer exist: {stale}"
        )


class TestTheSignalCanActuallyBeSent:
    """`mark_truncated(response, ...)` needs a `response` parameter, and nothing said so.

    Three handlers were edited to signal truncation and shipped a bare `NameError` — a 500
    on every call, on `/notifications/log`, `/health-index` and `/assets/{id}/commands`
    (FS-456). It was mine: a rewrite added the call to nine handlers and the parameter to
    six.

    Nothing caught it at edit time. `import app.main` succeeds, because the name is resolved
    when the line RUNS, not when the module loads; the type checker is not run on this
    package; and the unit tests for these routers use mocked sessions that never reach the
    line. Only a real request against a real database found it, which is the slowest and
    most expensive place to learn about a typo.

    So: an AST check, in the file that owns the truncation-signal rule. It costs milliseconds
    and it fires on the edit rather than three test suites later.
    """

    def test_every_handler_that_signals_truncation_can_reach_a_response(self):
        import ast
        from pathlib import Path

        api_dir = Path(__file__).resolve().parent.parent / "app" / "api"
        broken = []
        paths = sorted(api_dir.glob("*.py"))
        assert len(paths) > 20, f"only {len(paths)} api modules found; the glob is wrong"
        for path in paths:
            for node in ast.walk(ast.parse(path.read_text())):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                calls = [
                    n for n in ast.walk(node)
                    if isinstance(n, ast.Call)
                    and isinstance(n.func, ast.Name)
                    and n.func.id == "mark_truncated"
                ]
                if not calls:
                    continue
                names = {a.arg for a in node.args.args + node.args.kwonlyargs}
                if "response" not in names:
                    broken.append(f"{path.name}:{node.lineno} {node.name}")

        assert not broken, (
            "these handlers call mark_truncated(response, ...) and take no `response` "
            "parameter, so every request raises NameError and answers 500:\n  "
            + "\n  ".join(broken)
            + "\nAdd `response: Response` to the signature (FastAPI injects it)."
        )

