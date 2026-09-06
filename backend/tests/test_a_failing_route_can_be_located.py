"""A 5xx was counted but not located (FS-1015).

`http_requests_total` is labelled by method and status class only. A 500 on
`POST /yard/trailers/checkin` and a 500 on anything else in the API are therefore the same
series, and an operator watching the error rate rise has no way to narrow it without
reading logs.

That mattered most exactly where there was nothing else: `api/yard.py`,
`api/transportation.py`, `api/shop_floor.py` and `api/fleet_targeting.py` carry **zero**
counters of their own — measured, no `Counter(`, no `_total`, no `.inc()` in any of the
four — so the whole logistics and shop-floor write surface was visible only as an anonymous
contribution to a global number.

WHY A SEPARATE ERROR COUNTER RATHER THAN A `route` LABEL ON THE EXISTING ONE. Both answer
the question. Labelling every request multiplies the series count by roughly 550 routes for
traffic that is overwhelmingly successful; labelling only failures keeps the cardinality
proportional to how often things actually break, which is the property that makes it safe
to leave on.

THE TEMPLATE, NOT THE PATH. `/assets/{asset_id}`, never `/assets/9f2c…` — otherwise every
id becomes its own series and the metric that was added to help becomes the cardinality
incident.
"""
from __future__ import annotations

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient

from app.core.http_metrics import HTTP_ROUTE_ERRORS
from app.middleware.request_context import RequestContextMiddleware


def _app() -> TestClient:
    app = FastAPI()
    app.add_middleware(RequestContextMiddleware)

    @app.get("/widgets/{widget_id}")
    def get_widget(widget_id: str):
        if widget_id.startswith("bad"):
            raise HTTPException(status_code=422, detail="nope")
        return {"ok": True}

    return TestClient(app)


def _series() -> dict:
    return {
        (s.labels["route"], s.labels["method"], s.labels["status_class"]): s.value
        for metric in HTTP_ROUTE_ERRORS.collect()
        for s in metric.samples
        if s.name.endswith("_total")
    }


class TestAFailureIsAttributedToItsRoute:
    def test_a_failing_request_names_the_route(self):
        before = _series()
        _app().get("/widgets/bad-1")
        after = _series()
        key = ("/widgets/{widget_id}", "GET", "4xx")
        assert after.get(key, 0) > before.get(key, 0), (
            "a 4xx did not increment the route-labelled counter. The failure is still "
            "counted globally, but nothing says WHICH route produced it."
        )

    def test_a_successful_request_adds_nothing(self):
        """The cardinality guarantee. If successes were counted here the series count
        would scale with traffic and route count rather than with failures."""
        before = _series()
        _app().get("/widgets/fine")
        assert _series() == before

    def test_two_different_ids_share_one_series(self):
        """The template, not the path. Concrete ids would make this metric the incident."""
        _app().get("/widgets/bad-2")
        _app().get("/widgets/bad-3")
        routes = {route for route, _, _ in _series()}
        assert not any(
            "bad-2" in route or "bad-3" in route for route in routes
        ), f"a concrete id leaked into a metric label: {routes}"


class TestTheRoutersThatHadNothing:
    """The four files the finding named. This asserts the premise still holds — if one of
    them grows its own counters later, this test should be revisited rather than silently
    continuing to claim they have none."""

    @pytest.mark.parametrize(
        "module", ["yard", "transportation", "shop_floor", "fleet_targeting"]
    )
    def test_they_are_covered_by_the_middleware_rather_than_by_hand(self, module):
        from tests._source_trees import REPO_ROOT

        source = (REPO_ROOT / "backend" / "app" / "api" / f"{module}.py").read_text()
        assert "Counter(" not in source, (
            f"api/{module}.py now defines its own Counter. That is fine, but this file "
            "asserts the middleware-level route labelling is what covers it — update the "
            "reasoning rather than leaving two stories about the same routes."
        )
