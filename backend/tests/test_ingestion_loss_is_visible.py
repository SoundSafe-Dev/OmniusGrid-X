"""Telemetry the ingestion worker cannot process is counted and alerted on (FS-464).

Found by the reverse carry-across pass — the edge agent's classes re-asked of the backend.
FS-458 established that every way the agent's buffer loses a message must increment a counter
and have a Prometheus alert, because a loss visible only in a log is invisible on a device
that cannot reach the network. Asked of the cloud, the same question had a worse answer.

**The ingestion worker's dead-letter path had neither.** A message it cannot process is
published to a DLQ and logged, and that was all: no counter, no alert, nothing on a dashboard.
Meanwhile the agent's dead-lettering has had `edge_buffer_dead_lettered_total` and an
`EdgeDeadLettering` rule since FS-458 — **the platform was monitoring the edge's data loss and
not its own.**

WHY THE CLOUD CASE IS SHARPER. A dead-lettered message was ACCEPTED. The device sent it, the
broker acknowledged it, and the agent's store-and-forward buffer dropped its copy on that
acknowledgement. So the data exists in exactly one place — a DLQ topic nobody is watching —
and the device has been told everything is fine.

AND ONE PATH LOST IT COMPLETELY. `_dead_letter` opened with:

    if self._producer is None:
        return

A bare return: no DLQ record, no counter, no log. Defensive (the producer starts before the
consumer), but it is the only branch in the worker where an accepted message vanishes leaving
no trace of any kind, and "unreachable" is a property of today's start-up order rather than of
the code.

TWO COUNTERS, NOT ONE, because they need different responses. Dead-lettering is a bug to fix
at leisure — the data is preserved and replayable. A failed DLQ publish is data leaving the
system, and its alert is critical.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
INGESTION = Path(__file__).resolve().parent.parent / "app" / "workers" / "ingestion.py"
HEALTH = Path(__file__).resolve().parent.parent / "app" / "workers" / "health_server.py"
ALERTS = ROOT / "infra" / "prometheus" / "alerts.yml"

COUNTERS = (
    "opsgrid_ingestion_dead_lettered_total",
    "opsgrid_ingestion_dead_letter_failed_total",
)


def _dead_letter_source() -> str:
    source = INGESTION.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "_dead_letter":
            return ast.get_source_segment(source, node) or ""
    return ""


class TestTheSweepCanSeeItsSubject:
    def test_the_dead_letter_handler_exists(self):
        body = _dead_letter_source()
        assert body, "_dead_letter not found; every assertion below would pass over nothing"
        assert "dlq" in body.lower(), "the handler no longer mentions a DLQ"

    def test_the_alerts_file_is_readable(self):
        assert ALERTS.exists()
        assert "opsgrid_workers" in ALERTS.read_text()


class TestEveryLossPathIsCounted:
    def test_the_counters_are_declared(self):
        health = HEALTH.read_text()
        for name in COUNTERS:
            assert name in health, f"{name} is not declared"

    @pytest.mark.parametrize("counter", ["INGESTION_DEAD_LETTERED", "INGESTION_DEAD_LETTER_FAILED"])
    def test_each_counter_is_incremented_in_the_handler(self, counter: str):
        body = _dead_letter_source()
        assert f"{counter}.labels(" in body, (
            f"{counter} is declared and never incremented — a metric nobody touches is the "
            f"same silence it was meant to replace"
        )

    def test_no_branch_returns_without_recording_the_loss(self):
        """The `if self._producer is None: return` case.

        A bare `return` inside this handler discards an accepted message with no DLQ
        record, no counter and no log. Every early exit has to say something first.
        """
        source = INGESTION.read_text()
        tree = ast.parse(source)
        handler = next(
            n for n in ast.walk(tree)
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "_dead_letter"
        )
        silent = []
        for node in ast.walk(handler):
            if not isinstance(node, ast.If):
                continue
            for stmt in node.body:
                if isinstance(stmt, ast.Return):
                    seg = ast.get_source_segment(source, node) or ""
                    if "logger." not in seg and ".inc()" not in seg:
                        silent.append(node.lineno)
        assert not silent, (
            f"these branches of _dead_letter return without logging or counting, at lines "
            f"{silent}. An accepted message leaves the system there and nothing anywhere "
            f"records that it did."
        )


class TestEveryCounterIsAlertedOn:
    """A counter with no alert is a time series nobody looks at — invisible for a
    different reason than the log line it replaced, while looking on a dashboard like it
    was handled. The same pairing FS-458 asserts for the agent."""

    def test_each_counter_has_a_rule(self):
        alerts = ALERTS.read_text()
        unalerted = sorted(c for c in COUNTERS if c not in alerts)
        assert not unalerted, f"these loss counters have no Prometheus rule: {unalerted}"

    def test_total_loss_is_more_severe_than_dead_lettering(self):
        """The two are not the same event. A dead-lettered message is replayable; one
        whose DLQ publish also failed is gone, from a device that has been acknowledged
        and has already dropped its copy. Ranking them the same wastes the distinction."""
        import yaml

        rules = [
            r
            for group in yaml.safe_load(ALERTS.read_text())["groups"]
            for r in group["rules"]
        ]
        by_expr = {r.get("expr", ""): r for r in rules}
        dead = next(r for e, r in by_expr.items() if COUNTERS[0] in e)
        lost = next(r for e, r in by_expr.items() if COUNTERS[1] in e)
        order = {"info": 0, "low": 1, "medium": 2, "high": 3, "critical": 4}
        self_sev = order[lost["labels"]["severity"]]
        other_sev = order[dead["labels"]["severity"]]
        assert self_sev > other_sev, (
            f"losing telemetry entirely ({lost['labels']['severity']}) is not ranked above "
            f"dead-lettering it ({dead['labels']['severity']}), so the alert that means "
            f"'data left the system' reads no louder than the one that means 'data is "
            f"parked somewhere replayable'"
        )

    def test_the_alerts_say_what_to_do(self):
        import yaml

        rules = [
            r
            for group in yaml.safe_load(ALERTS.read_text())["groups"]
            for r in group["rules"]
            if any(c in r.get("expr", "") for c in COUNTERS)
        ]
        assert len(rules) == 2
        for rule in rules:
            description = rule["annotations"]["description"]
            assert len(description) > 80, (
                f"{rule['alert']} has a description too short to act on; an operator woken "
                f"by it needs to know where the data is and what to check"
            )
