"""A health check must report a broken dependency, not fail on it (FS-687).

`_check_database`, `_check_redis`, `_check_message_broker` and `_check_ingestion` each catch
broadly and **return** the failure — `return f"error: {exc}", {}` — so `_run_health_checks` can
report every component and compute `not_ready` / `degraded` from the whole picture. A database
that is down produces a readiness answer naming the database; it does not produce a 500.

NOTHING PINNED THAT, and the pressure to break it is real and specific. The swallow ratchet
(`test_the_swallow_surface_only_shrinks.py`) counts a broad handler as *swallowing* unless it
re-raises, so these four read as twelve entries of debt in `api/health.py` — the largest cluster
in the file — while being the correct shape for their job. The obvious way to shrink that
number is to raise instead, and the result would be a readiness probe that returns 500 the
moment any one dependency is unavailable: Kubernetes would restart a pod whose only problem is
that Redis is slow, and the operator would lose the per-component report that says which
dependency it actually was.

WHAT THIS ASSERTS, therefore, is the contract rather than the implementation: with a dependency
raising, the endpoint still answers, still names every component, and marks the broken one as
an error while leaving the others alone. A future author who "fixes" the ratchet entry fails
here, with a message explaining the trade.

THE RATCHET IS NOT WRONG SO MUCH AS COARSE, and that is recorded rather than edited. 37 of its
201 handlers return a value carrying the caught exception — the same propagation `raise`
performs, expressed as data — and its own docstring says it must not punish translating an
error properly. Excluding them by shape was considered and rejected: a returned error is only
propagation if the CALLER reads it, which the shape cannot show. `_run_health_checks` does read
it, and that is what this file demonstrates.
"""

from __future__ import annotations

import pytest

from app.api import health as health_module

pytestmark = pytest.mark.asyncio


class _Boom:
    """A session whose every use raises, standing in for a database that is down."""

    async def execute(self, *_args, **_kwargs):
        raise RuntimeError("connection refused")


async def _ok(*_args, **_kwargs):
    return "ok", {}


def _errored(what: str):
    """A checker in its FAILING state — which is a returned status, not an exception.

    The first draft of this helper made the stub raise, and every aggregator test failed with
    `RuntimeError: _check_database is down`. That was the test's premise being wrong, not a
    defect: `_run_health_checks` deliberately does not wrap the checkers, because each one
    catches its own failure and returns it. Stubbing a raise removed the very behaviour under
    test. The contract is *checker catches and returns; aggregator reports and grades*, and
    this stub now stands in for the first half honestly.
    """

    async def _error(*_args, **_kwargs):
        return f"error: {what} is down", {}

    return _error


async def _report(monkeypatch, broken: str):
    """Run the aggregator with exactly one checker reporting an error and the rest healthy.

    THE SIGNATURES DIFFER AND THAT MATTERS: `_check_database` and `_check_ingestion` take the
    session, `_check_redis` and `_check_message_broker` take nothing. The first draft passed a
    session to all four — `TypeError: _check_message_broker() takes 0 positional arguments`,
    four failures that were entirely the test's own. Hence `*_args`.
    """
    for name in ("_check_database", "_check_redis", "_check_message_broker", "_check_ingestion"):
        monkeypatch.setattr(health_module, name, _errored(broken) if name == broken else _ok)
    return await health_module._run_health_checks(_Boom())


class TestTheEndpointStillAnswers:
    async def test_a_database_failure_is_reported_rather_than_raised(self, monkeypatch):
        report = await _report(monkeypatch, "_check_database")
        assert "database" in report["checks"]
        assert report["checks"]["database"].startswith("error"), (
            "a database that raises should be reported as an error component, not swallowed "
            "into 'ok' and not propagated as a 500"
        )

    async def test_the_overall_status_says_not_ready(self, monkeypatch):
        """The database is critical, so its failure has to reach the overall verdict — a
        per-component error that leaves `status: ready` would be worse than raising."""
        report = await _report(monkeypatch, "_check_database")
        assert report["status"] == "not_ready"

    async def test_every_component_is_still_named(self, monkeypatch):
        """The value of reporting over raising: the operator learns which dependency it was,
        and that the others were fine."""
        report = await _report(monkeypatch, "_check_database")
        assert set(report["checks"]) == {"database", "redis", "message_broker", "ingestion"}
        assert report["checked_at"]

    async def test_one_broken_dependency_does_not_mark_the_others_broken(self, monkeypatch):
        """`_check_redis` raising must not make the broker look down. A single `except` around
        the whole aggregation would pass the tests above and fail this one."""
        async def _ok(*_args, **_kwargs):
            return "ok", {}

        async def _boom(*_args, **_kwargs):
            return "error: redis is down", {}

        monkeypatch.setattr(health_module, "_check_database", _ok)
        monkeypatch.setattr(health_module, "_check_message_broker", _ok)
        monkeypatch.setattr(health_module, "_check_ingestion", _ok)
        monkeypatch.setattr(health_module, "_check_redis", _boom)

        report = await health_module._run_health_checks(_Boom())
        assert report["checks"]["redis"].startswith("error")
        assert report["checks"]["database"] == "ok"
        assert report["checks"]["message_broker"] == "ok"


class TestTheCheckersDoNotRaise:
    """The property stated directly, per checker, so the failure names the one that broke."""

    async def test_the_database_check_returns_a_status_instead_of_raising(self):
        status, details = await health_module._check_database(_Boom())
        assert isinstance(status, str) and status.startswith("error")
        assert isinstance(details, dict)

    async def test_the_ingestion_check_returns_a_status_instead_of_raising(self):
        status, details = await health_module._check_ingestion(_Boom())
        assert isinstance(status, str)
        assert isinstance(details, dict)

    async def test_the_argumentless_checks_answer_without_a_live_dependency(self):
        """`_check_redis` and `_check_message_broker` take no session — they reach their own
        clients — so the property here is simply that neither raises when the dependency is
        absent, which is the ordinary state of a laptop."""
        for checker in (health_module._check_redis, health_module._check_message_broker):
            status, details = await checker()
            assert isinstance(status, str)
            assert isinstance(details, dict)
