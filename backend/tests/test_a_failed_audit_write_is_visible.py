"""A failed audit write is counted and alerted on (FS-536).

THIS HAS ALREADY HAPPENED HERE, AND THE SCHEMA CARRIES THE POST-MORTEM.
`db/models.py:1561-1567`, above `audit_logs.ip_address`:

> Migrations 001/009 create this as INET. Declared as VARCHAR here, every insert bound
> `$n::VARCHAR` and Postgres rejected it … and audit_trail swallows the failure as
> `audit_log_failed`, so **the audit trail has been silently empty on real deployments while
> every write appeared to succeed.**

The type mismatch was fixed. **The condition that made it invisible was not.** The handler
still logs and continues, and nothing counted, so the next thing to break an audit write — a
constraint, a migration, a full disk, an RLS policy — reproduces the identical outcome, and an
auditor discovers it by finding a period with no rows.

CONTINUING IS RIGHT. An audit write must not fail a user's request. But *"do not fail the
request"* and *"do not tell anyone"* are separate decisions, and only the first had been made.
That is the same argument as FS-537 on the ingest path and FS-504 on the edge buffer — three
places where the swallow was correct and the silence was not.

WHY CRITICAL RATHER THAN HIGH. An audit gap is a compliance finding, it cannot be
reconstructed after the fact, and every minute it continues is unrecoverable. `for: 0m`
follows from that: unlike a dropped WebSocket frame there is no acceptable transient here.

ALSO IN THIS FILE: `_get_request_body` and `_get_response_body` returned `None` inside a
`try`/`except Exception`. The body cannot raise, so the handler could never fire — the
try/except was theatre that implied an attempt not being made, and a reader looking for why
audit rows carry no payload found a function that appeared to try and fail. They now say
plainly that bodies are not captured and why.
"""

from __future__ import annotations

import ast
import inspect
import pathlib
import textwrap

import pytest

from app.core import http_metrics
from app.middleware import audit

AUDIT_SOURCE = pathlib.Path(inspect.getfile(audit))
ALERTS = pathlib.Path(__file__).resolve().parents[2] / "infra" / "prometheus" / "alerts.yml"


class TestTheFailureIsCounted:
    def test_the_counter_exists(self):
        assert hasattr(http_metrics, "AUDIT_WRITE_FAILURES"), (
            "there is no counter for a failed audit write, so the condition that has "
            "already produced a silently empty audit trail in this product is once again "
            "invisible"
        )

    def test_the_handler_increments_it(self):
        source = AUDIT_SOURCE.read_text()
        assert "AUDIT_WRITE_FAILURES.labels" in source, (
            "`audit_log_failed` is logged and nothing is counted. A log line per failure "
            "aggregates nowhere — which is exactly how the INET/VARCHAR mismatch emptied "
            "the trail without anyone noticing."
        )

    def test_the_request_still_succeeds(self):
        """The swallow must stay. A fix that made audit failures fail the request would
        take the platform down on a schema change, which is a much larger fault than the
        one being fixed."""
        handler = next(
            node
            for node in ast.walk(ast.parse(AUDIT_SOURCE.read_text()))
            if isinstance(node, ast.ExceptHandler)
            and "audit_log_failed" in ast.unparse(node)
        )
        assert not any(isinstance(n, ast.Raise) for n in ast.walk(handler)), (
            "the audit handler now re-raises, so a failed audit write fails the user's "
            "request. Continuing is deliberate; only the silence was the defect."
        )

    def test_it_is_labelled_by_action_not_by_error(self):
        """An unbounded label — error text, user id, resource id — is a cardinality
        explosion that takes Prometheus down instead of reporting to it."""
        assert http_metrics.AUDIT_WRITE_FAILURES._labelnames == ("action",)


class TestSomethingWatchesTheCounter:
    def test_an_alert_rule_reads_it(self):
        alerts = ALERTS.read_text()
        assert "opsgrid_audit_write_failed_total" in alerts, (
            "nothing alerts on the counter, so a persistent audit gap still reaches nobody "
            "— a counter without a rule is a metric, not a signal"
        )
        assert "AuditWriteFailing" in alerts

    def test_it_is_critical_and_has_no_grace_window(self):
        alerts = ALERTS.read_text()
        block = alerts[alerts.index("AuditWriteFailing") :][:900]
        assert "severity: critical" in block, (
            "the audit alert is not critical. An audit gap cannot be reconstructed after "
            "the fact, which is what separates it from a dropped metric."
        )
        assert "for: 0m" in block, (
            "the audit alert has a grace window. One lost audit row is a permanent gap in "
            "a compliance record; there is no transient to wait out."
        )

    def test_the_alert_has_a_promtool_unit_test(self):
        """The condition this rule guards has already occurred and produced no signal.
        `promtool check rules` proves the expression parses, never that a series exists to
        make it true (rule 121)."""
        test_file = ALERTS.parent / "tests" / "audit_alerts_test.yml"
        assert test_file.exists(), "the audit alert has no unit test proving it can fire"
        body = test_file.read_text()
        assert body.count("exp_alerts: []") >= 2, (
            "no must-stay-quiet cases. An alert that fires on a healthy system gets muted, "
            "which is the same as not having one."
        )


class TestTheBodyCapturersDoNotPretend:
    @pytest.mark.parametrize("name", ["_get_request_body", "_get_response_body"])
    def test_no_unreachable_exception_handler(self, name: str):
        """`return None` inside `try`/`except Exception` cannot raise, so the handler could
        never fire. It implied an attempt that was not being made — a reader looking for why
        audit rows carry no payload found a function that appeared to try and fail."""
        source = inspect.getsource(getattr(audit.AuditLoggingMiddleware, name))
        # AST, NOT A SUBSTRING. The first version searched the source text for
        # "except Exception" and failed against the fix, because the DOCSTRING explaining
        # the removal contains that phrase. Rule 37: a substring search matches the comment
        # describing the defect as readily as the defect, and in this repository the
        # comments are long and say exactly what was removed.
        handlers = [
            node
            for node in ast.walk(ast.parse(textwrap.dedent(source)))
            if isinstance(node, ast.ExceptHandler)
        ]
        assert not handlers, (
            f"{name} has an exception handler around code that cannot raise. Say plainly "
            f"that bodies are not captured, or capture them."
        )

    @pytest.mark.parametrize("name", ["_get_request_body", "_get_response_body"])
    def test_it_says_why(self, name: str):
        doc = inspect.getdoc(getattr(audit.AuditLoggingMiddleware, name)) or ""
        assert "None" in doc and len(doc) > 60, (
            f"{name} does not explain that it always returns None. A capturer that silently "
            f"captures nothing is indistinguishable from a request that had no body."
        )
