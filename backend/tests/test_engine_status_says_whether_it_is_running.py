"""Four engines expose a status route and none of them is started (FS-530).

`main.py` starts eight background services. `tactical_engine`, `mlops_pipeline`,
`strategic_engine` and `cloud_gateway` are not among them. Each defines `start()`, each spawns
its loops there, and **nothing calls it** — `tactical_engine.py:442-446` records its own
unreachability in a docstring, which is how long this has been known.

So every figure those routes report is the value the object was CONSTRUCTED with:

    /engines/tactical/status  ->  model_loaded: false      nothing loaded a model
    /engines/mlops/status     ->  cached_models: []        the poll loop never ran
    /engines/cloud/status     ->  connected: false         the manager never started
    /engines/strategic/recommendations -> []               the listener never ran

Each reads as an observation about the world and is a fact about an object nobody switched on.
`connected: false` on a cloud gateway reads as "the cloud is unreachable". `cached_models: []`
reads as "no models have been published". They are not the same statements, and an operator
cannot act on the difference because the payload does not carry it.

THIS DOES NOT START THEM, and that is deliberate. Whether these engines should run — and what
happens to the telemetry path when they do — is a product decision in the correlation-AI lane,
not a defect fix. What *is* a defect is a status endpoint that cannot distinguish **not
running** from **running and idle**: FS-349's shape exactly, where a report carried a
`model_version` for a model that was never loaded, and the fix was to say so in the payload.

THE LIST ROUTE IS SIGNALLED BY HEADER. `/strategic/recommendations` returns a bare array, and
an empty one means both "ran, found nothing" and "never started" — the failure that renders as
emptiness (FS-487). `X-Engine-Not-Running` follows `X-Result-Truncated`'s reasoning: clients
already consume the bare list, and reshaping it into an envelope would break every caller to
fix something they could then no longer see.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

from app.api import engines
from app.core.pagination import ENGINE_NOT_RUNNING_HEADER
from app.services.cloud_gateway import cloud_gateway
from app.services.mlops_pipeline import mlops_pipeline
from app.services.strategic_engine import strategic_engine
from app.services.tactical_engine import tactical_engine
from tests.test_service_lifecycle_is_declared import EXPECTED_DORMANT

MAIN = pathlib.Path(__file__).resolve().parents[1] / "app" / "main.py"

#: The four, keyed by the SHARED dormant declaration (FS-590).
#:
#: THIS FILE KEPT A PRIVATE COPY, AND IT WAS MINE, WRITTEN HOURS EARLIER.
#: `test_service_lifecycle_is_declared.py` already recorded exactly which background
#: services are dormant and why — with better reasons than a bare list, including the one
#: that matters most: `cloud_gateway` holds a 10,000-entry in-memory queue drained only by
#: the `_flush_loop` that `start()` launches, so starting any producer without it means
#: events accumulate and are silently dropped.
#:
#: Two lists of the same fact is FS-492's shape, and the carry-across sweep that found it
#: was looking for exactly this — in other people's guards. It found mine first.
#:
#: Reading `EXPECTED_DORMANT` means the day one of these is started, BOTH guards fail
#: together and the reasoning lives in one place.
_INSTANCES = {
    "tactical_engine": tactical_engine,
    "mlops_pipeline": mlops_pipeline,
    "strategic_engine": strategic_engine,
    "cloud_gateway": cloud_gateway,
}
ENGINES = {name: _INSTANCES[name] for name in EXPECTED_DORMANT if name in _INSTANCES}


def _started_in_main() -> set[str]:
    """Names `main.py` calls `.start()` on."""
    started = set()
    for node in ast.walk(ast.parse(MAIN.read_text())):
        if (
            isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "start"
            and isinstance(node.func.value, ast.Name)
        ):
            started.add(node.func.value.id)
    return started


class TestThePremiseIsStillTrue:
    def test_the_derived_set_did_not_shrink(self):
        """DERIVING A LIST TRADES ONE FAILURE FOR ANOTHER, and this is the second one.

        Sharing `EXPECTED_DORMANT` removed the divergence two private copies had already
        accumulated (FS-590). It also means this file's population is now controlled by
        another file — and when a mutation test removed `cloud_gateway` from that
        declaration, every assertion here still passed. **The suite went from 16 tests to
        14 and reported success**: the sweep had silently stopped checking the one engine
        whose dormancy actually costs something, because it holds a 10,000-entry queue that
        only its own `_flush_loop` drains.

        A count is the cheapest thing that notices. Sharing a list is right; sharing it
        without asserting what you got is how a guard narrows to nothing one entry at a
        time.
        """
        assert set(ENGINES) == set(_INSTANCES), (
            f"this file checks {sorted(ENGINES)} and expects {sorted(_INSTANCES)}. An "
            f"engine dropped out of EXPECTED_DORMANT, so it is no longer checked here — "
            f"either it was started (update both) or the declaration lost an entry."
        )

    def test_main_starts_something(self):
        """If this read empty the whole file would pass by asserting that engines nobody
        starts report they are not started — true and useless."""
        assert len(_started_in_main()) >= 5, (
            f"only {_started_in_main()} start calls found in main.py; the AST walk is broken"
        )

    @pytest.mark.parametrize("name", sorted(ENGINES))
    def test_the_engine_is_still_unstarted(self, name: str):
        """The day one of these is started, this fails — and the `note` on its status route
        should come out with it. A stale "not running" note on a running engine is the same
        defect pointing the other way."""
        assert name not in _started_in_main(), (
            f"{name} is started in main.py now. Its status route still carries a "
            f"not-running note; remove it, and check the routes that read its state now "
            f"report measurements rather than construction defaults."
        )

    @pytest.mark.parametrize("name,engine", sorted(ENGINES.items()))
    def test_each_carries_a_running_flag(self, name: str, engine: object):
        """`cloud_gateway` had none until FS-530 — three siblings had one and it did not,
        so `get_stats()` had no way to say whether its loops were up."""
        assert hasattr(engine, "_running"), (
            f"{name} has no `_running` flag, so nothing can distinguish an idle engine from "
            f"an absent one"
        )


class TestEachStatusRouteSaysWhetherItIsRunning:
    async def test_tactical_status(self):
        payload = await engines.get_tactical_status()
        assert payload["running"] is False
        assert "NOT running" in payload["note"], (
            "`model_loaded: false` is reported with nothing saying the engine that would "
            "load it was never started"
        )

    async def test_mlops_status(self):
        payload = await engines.get_mlops_status()
        assert payload["running"] is False
        assert "NOT running" in payload["note"], (
            "`cached_models: []` reads as 'no models have been published' when it means "
            "'the poll loop never ran'"
        )

    async def test_cloud_status(self):
        payload = await engines.get_cloud_gateway_status()
        assert payload["running"] is False
        assert payload["note"] and "never been asked to connect" in payload["note"], (
            "`connected: false` on a gateway nobody started reads as 'the cloud is "
            "unreachable', which is a different and alarming statement"
        )

    async def test_the_note_disappears_when_the_engine_runs(self, monkeypatch):
        """The other direction. A permanent 'not running' banner on a running engine is the
        same defect, and the one that would survive longest — nobody investigates a warning
        that has always been there."""
        monkeypatch.setattr(cloud_gateway, "_running", True)
        payload = await engines.get_cloud_gateway_status()
        assert payload["running"] is True
        assert payload["note"] is None


class TestTheListRouteSignalsWithoutReshaping:
    async def test_an_empty_list_carries_the_header(self):
        from fastapi import Response

        response = Response()
        await engines.get_strategic_recommendations(response=response)
        assert response.headers.get(ENGINE_NOT_RUNNING_HEADER) == "strategic", (
            "an empty recommendation list is served with nothing saying the listener that "
            "fills it was never started — the page renders 'No recommendations' either way"
        )

    async def test_the_header_is_absent_when_running(self, monkeypatch):
        from fastapi import Response

        monkeypatch.setattr(strategic_engine, "_running", True)
        response = Response()
        await engines.get_strategic_recommendations(response=response)
        assert ENGINE_NOT_RUNNING_HEADER not in response.headers, (
            "the header is set for a running engine, so it says nothing"
        )

    def test_the_body_is_still_a_bare_array(self):
        """The whole reason for a header. Reshaping into an envelope would break every
        caller in order to fix something they could then no longer see."""
        import inspect

        signature = inspect.signature(engines.get_strategic_recommendations)
        assert "response" in signature.parameters, (
            "the route no longer takes a Response, so it cannot set the header"
        )
        # Parsed, not grepped: `return [` also matches a comment or a docstring, and this
        # file's docstrings are long enough that it would.
        returns = [
            node
            for node in ast.walk(ast.parse(
                __import__("textwrap").dedent(
                    inspect.getsource(engines.get_strategic_recommendations)
                )
            ))
            if isinstance(node, ast.Return) and node.value is not None
        ]
        assert returns and any(isinstance(r.value, ast.ListComp) for r in returns), (
            "the route no longer returns a bare array. If it now sends an envelope the "
            "header is redundant and the docstring's argument for using one no longer "
            "applies — say so there rather than leaving both."
        )
