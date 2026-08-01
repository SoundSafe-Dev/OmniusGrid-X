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
import typing

import pytest
from fastapi import routing

from app.main import app
from tests._route_tree import http_routes

#: Measured 2026-08-01. LOWER THIS as endpoints are fixed WITH their consumers; never raise
#: it. A new capped bare-array endpoint must either signal truncation or return an envelope
#: carrying a total.
MAX_UNSIGNALLED = 12

#: Files another dev owns. Counted, because the number is about the API's surface rather
#: than about who fixes it — but named so a failure says whose lane it is in.
OTHER_LANES = {
    "analysis_sessions", "nlp_correlation", "kanban", "telemetry",
    "auth", "engines", "model_monitoring", "logistics_correlation",
}

#: How an endpoint declares it was capped. `mark_truncated` (app/core/pagination.py) sets
#: `X-Result-Truncated` from a `limit + 1` probe.
_SIGNALS = ("mark_truncated", "X-Result-Truncated")


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
        if any(signal in source for signal in _SIGNALS):
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


class TestTheDebtIsAttributed:
    def test_every_unsignalled_endpoint_is_named_with_its_lane(self):
        """Not an assertion so much as a readable inventory: a failure elsewhere in this
        file is far more useful when the reader can see whose lane each one is in."""
        current = _unsignalled()
        mine = [(m, p) for m, p in current if m not in OTHER_LANES]
        theirs = [(m, p) for m, p in current if m in OTHER_LANES]
        assert len(mine) + len(theirs) == len(current)
        # Recorded here so the split is visible in the source without running anything:
        #   mine   — commands, fleet_logistics (geofencing/alerts), health_index,
        #            notifications, registries x3
        #   theirs — analysis_sessions x3, kanban x2
        assert theirs, (
            "no cross-lane entries found; if they were fixed, lower MAX_UNSIGNALLED and "
            "update this note rather than leaving a stale claim about other people's work"
        )
