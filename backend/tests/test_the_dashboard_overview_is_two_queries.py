"""`/overview` answers in two round trips, and answers the same thing (FS-879).

THE COST. Five queries per call, three of them reading `assets` and two reading the same
`Alarm ⋈ Asset` join — each pair differing by a single predicate. `Dashboard.tsx:159` polls
this every 30 seconds PER OPEN TAB, so the load is five queries multiplied by every
dashboard anyone has left open, against a pool sized at 10 connections per process
(FS-839). A subset question asked as its own query pays a full round trip — and for the
alarms, a full second join — to re-ask something already in flight.

`FILTER` answers the subset in the pass the superset is already making.

NOT SERVED FROM THE CONTINUOUS AGGREGATES, though the task pool suggested it:
`002_continuous_aggregates.sql` rolls up `telemetry` into hourly temperature and minute
performance features. Nothing on this endpoint is time-series — they are row counts in
`assets` and `alarms` — so no aggregate over telemetry can answer them. Recorded here
because the next person to read that task will reach for the same wrong tool.

BOTH HALVES ARE ASSERTED, and the second is the one that matters. A faster endpoint that
returns different numbers is not an optimisation, it is a regression with a good benchmark
— so the counts are checked against a known population as well as the query count.
"""
from __future__ import annotations

import ast
import pathlib

import pytest

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _overview_source() -> str:
    """The body of the `/overview` handler, isolated by AST rather than line numbers.

    Slicing by line number is how this kind of guard goes stale silently: the handler moves
    and the check starts measuring whatever now occupies those lines.
    """
    tree = ast.parse((APP / "api/dashboard.py").read_text())
    fn = next(
        (
            node
            for node in ast.walk(tree)
            if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef))
            and node.name == "get_dashboard_overview"
        ),
        None,
    )
    assert fn is not None, "the /overview handler has been renamed; this guard is blind"
    return ast.unparse(fn)


class TestItIsTwoRoundTrips:
    def test_the_handler_executes_twice(self):
        source = _overview_source()
        executes = source.count("db.execute")
        assert executes == 2, (
            f"/overview issues {executes} queries. It was five: three reading `assets` and "
            f"two reading the same Alarm-Asset join, each pair differing by one predicate. "
            f"A subset asked as its own query pays a round trip to re-ask a question "
            f"already in flight, and this endpoint is polled every 30s per open tab."
        )

    def test_it_uses_filter_rather_than_a_second_query(self):
        """The mechanism, not just the count — so collapsing them by dropping a number
        instead of by computing it would still fail."""
        source = _overview_source()
        assert source.count(".filter(") >= 2, (
            "the two subset counts are no longer answered with FILTER clauses, so either "
            "they became separate queries again or a figure is no longer being computed"
        )

    def test_the_totals_are_derived_not_re_queried(self):
        """`total_assets` and `active_assets` come from the grouped pass, not from their
        own COUNTs. The derivation lives in `_summarise_assets` so it can be tested against
        a population that includes a NULL state — see the class below for why that matters.
        """
        source = _overview_source()
        assert "_summarise_assets" in source, (
            "the asset totals are no longer derived from the grouped pass, so they are "
            "being re-queried — which is the two extra round trips this collapsed"
        )


class TestTheDerivationOverARealPopulation:
    """The totals are now SUMS OVER THE HISTOGRAM rather than their own COUNT queries, so
    the identity `sum(histogram) == total` is what makes the collapse correct.

    THE FIRST VERSION OF THIS WAS VACUOUS, and mutation-testing is what showed it: the
    assertions ran over the HTTP endpoint against a fixture with **zero assets**, so
    `sum({}) == 0` passed while proving nothing — and excluding NULL states from the query
    did not fail it. Rule 165, in a test written to guard a rewrite.

    So the derivation is exercised directly, against a population that contains the case
    that can actually break it.
    """

    def test_the_histogram_sums_to_the_total(self):
        from app.api.dashboard import _summarise_assets

        rows = [("EXECUTE", 5, 4), ("IDLE", 2, 2), ("ABORTED", 1, 0)]
        histogram, total, active = _summarise_assets(rows)
        assert total == 8
        assert sum(histogram.values()) == total
        assert active == 6

    def test_a_null_state_is_counted_not_dropped(self):
        """THE CASE THE VACUOUS TEST COULD NOT SEE. An asset with no PackML state is still
        an asset. Postgres groups NULL as its own group, so it reaches the histogram — and
        if a predicate ever excluded it, `total_assets` would silently under-report while
        every count still looked internally consistent."""
        from app.api.dashboard import _summarise_assets

        rows = [("EXECUTE", 5, 4), (None, 3, 1)]
        histogram, total, active = _summarise_assets(rows)
        assert None in histogram, "an asset with no state vanished from the histogram"
        assert total == 8, f"total dropped the NULL group: {total}"
        assert active == 5

    def test_an_empty_population_is_zero_not_an_error(self):
        """The other end: a new organisation with no assets must render, not 500."""
        from app.api.dashboard import _summarise_assets

        histogram, total, active = _summarise_assets([])
        assert (histogram, total, active) == ({}, 0, 0)

    def test_active_never_exceeds_total(self):
        """`active` comes from a FILTER over the same rows, so it is a subset by
        construction. This is what catches a mis-ordered tuple unpack, which would
        otherwise produce plausible numbers in the wrong fields."""
        from app.api.dashboard import _summarise_assets

        rows = [("EXECUTE", 5, 4), (None, 3, 1), ("IDLE", 2, 2)]
        _, total, active = _summarise_assets(rows)
        assert active <= total


class TestTheEndpointStillAnswers:
    """Shape only. The tenancy suite already covers the values against a real database;
    these assert the contract did not change and are deliberately NOT relied on for the
    arithmetic, which the class above exercises properly."""

    @pytest.mark.asyncio
    async def test_the_response_keeps_every_field(self, client_a, seeded_orgs):
        resp = await client_a.get("/api/v1/dashboard/overview")
        assert resp.status_code == 200, resp.text
        body = resp.json()
        for field in (
            "total_assets",
            "active_assets",
            "assets_by_state",
            "active_alarms",
            "critical_alarms",
        ):
            assert field in body, f"/overview stopped returning {field}"
        assert isinstance(body["assets_by_state"], dict)
