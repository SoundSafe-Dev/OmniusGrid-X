"""Every swallowed failure on the ingest path increments a counter (FS-537).

SIX SIDE EFFECTS, AND SWALLOWING IS RIGHT. `ingestion.py` catches and continues around two
WebSocket publishes, two OEE updates, an alarm publish, and **alarm rule evaluation**. The
survey that preceded this found five; the guard found the sixth, which is the argument for
writing the guard rather than fixing the list. It should:
telemetry that reached the database is what matters, and the alternative is a poison message
halting the pipeline for everything behind it.

WHAT WAS MISSING IS THAT NOTHING COUNTED THEM. A rule that raises on every message wrote one
`alarm_rule_evaluation_failed` line per message and aggregated nowhere. So "server-side alarm
rules have stopped firing" was a condition the platform could not report: telemetry keeps
flowing, dashboards keep updating, and the alerting is silently off until an operator notices
an alarm that never arrived.

This is the third time this exact argument has been made in this repository, which is why it is
a guard rather than a fix. `INGESTION_DEAD_LETTERED` (FS-464) exists because "recoverable is
not the same as noticed". FS-496 raised the edge agent's swallowed Kafka failure out of `debug`
after it had failed 100% of the time invisibly. FS-504 counted a buffer prune that silently
dropped 500 rows. **The platform was monitoring the edge's silent failures and not its own,
twice.**

WHAT THIS CHECKS. Every broad `except` in the ingest path either re-raises or increments
`INGESTION_SIDE_EFFECT_FAILED`. A sixth swallow added without a counter is the regression, and
it is the easy one to add — the handler above it is right there, three lines long, and does
exactly what a new one would want to copy.
"""

from __future__ import annotations

import ast
import inspect
import pathlib

import pytest

from app.workers import health_server, ingestion

INGESTION_SOURCE = pathlib.Path(inspect.getfile(ingestion))

#: Handlers that swallow and are exempt, with why. An entry here must show the failure is
#: counted somewhere else — not that it is acceptable for it to be invisible.
UNCOUNTED: dict[str, str] = {
    "message_processing_failed": (
        "The top-level consumer handler. It is not uncounted — it calls `_dead_letter`, "
        "which increments INGESTION_DEAD_LETTERED (and INGESTION_DEAD_LETTER_FAILED if the "
        "publish itself fails), both of which have alert rules. The detector cannot see "
        "that because the increment is inside the helper rather than the handler body. "
        "Exempted by the log event name rather than by widening the body match, so the "
        "reason is recorded instead of inferred — a body-shaped exemption would also "
        "silently excuse any future handler that happened to call something."
    ),
}


def _swallowing_handlers() -> list[tuple[int, str]]:
    """(line, body-source) for each `except` that neither re-raises nor propagates.

    Broad by design: `except Exception` and a bare `except` both hide a failure, and the
    narrow ones (`except ValueError` around a parse) are the ones deliberately handling a
    known case. Only the broad ones are the class this file is about.
    """
    tree = ast.parse(INGESTION_SOURCE.read_text())
    lines = INGESTION_SOURCE.read_text().splitlines()
    handlers = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.ExceptHandler):
            continue
        caught = ast.unparse(node.type) if node.type else "bare"
        if caught not in {"Exception", "BaseException", "bare"}:
            continue
        if any(isinstance(n, ast.Raise) for n in ast.walk(node)):
            continue  # re-raises: visible by definition
        body = "\n".join(lines[node.lineno - 1 : node.end_lineno])
        handlers.append((node.lineno, body))
    return handlers


class TestTheDetectorHasSubjects:
    def test_it_finds_the_swallowing_handlers(self):
        """A walk that finds nothing passes this file trivially while the defect it exists
        for goes unchecked — FS-484, FS-492 and FS-504 each cost that once."""
        handlers = _swallowing_handlers()
        assert len(handlers) >= 5, (
            f"only {len(handlers)} broad swallowing handlers found in ingestion.py. Either "
            f"they were all removed — worth noticing on its own — or the AST walk broke."
        )

    def test_the_counter_exists_and_is_labelled(self):
        assert hasattr(health_server, "INGESTION_SIDE_EFFECT_FAILED")
        assert hasattr(health_server, "INGESTION_SIDE_EFFECTS")
        # SIX, not the five the plan listed. The sixth — `websocket_alarm_publish` — was
        # found by this guard after the survey that produced the list had finished, which is
        # the argument for writing the guard rather than fixing the five.
        assert len(health_server.INGESTION_SIDE_EFFECTS) == 6

    @pytest.mark.parametrize("name,reason", sorted(UNCOUNTED.items()))
    def test_each_exemption_still_describes_a_real_handler(self, name: str, reason: str):
        assert name in INGESTION_SOURCE.read_text(), (
            f"{name!r} is exempted from the counter requirement and appears nowhere in "
            f"ingestion.py — the entry describes nothing"
        )


class TestNothingFailsUncounted:
    def test_every_swallowing_handler_increments_the_counter(self):
        uncounted = [
            f"ingestion.py:{line}\n      {body.strip()[:160]}"
            for line, body in _swallowing_handlers()
            if "INGESTION_SIDE_EFFECT_FAILED" not in body
            and "INGESTION_DEAD_LETTER" not in body
            and not any(name in body for name in UNCOUNTED)
        ]
        assert not uncounted, (
            "these handlers on the ingest path swallow a failure and increment nothing, so "
            "the condition is invisible to Prometheus and to the operator:\n\n  "
            + "\n\n  ".join(uncounted)
            + "\n\nAdd `INGESTION_SIDE_EFFECT_FAILED.labels(side_effect=...).inc()` and a "
            "name in `INGESTION_SIDE_EFFECTS`. Swallowing is usually right here; not "
            "counting never is."
        )

    @pytest.mark.parametrize("side_effect", health_server.INGESTION_SIDE_EFFECTS)
    def test_each_named_side_effect_is_actually_used(self, side_effect: str):
        """The other direction. A name in the tuple that no handler passes describes a
        counter that can never move, and would make the set look more complete than it is."""
        source = INGESTION_SOURCE.read_text()
        assert f'side_effect="{side_effect}"' in source, (
            f"{side_effect!r} is declared in INGESTION_SIDE_EFFECTS and no handler in "
            f"ingestion.py increments it"
        )


class TestTheAlarmPathIsTheOneThatMatters:
    def test_alarm_rule_evaluation_is_counted(self):
        """Named separately because its failure is qualitatively different from the others.
        A dropped WebSocket frame is a stale panel; alarm rules not firing is the alerting
        being off while everything looks healthy."""
        source = INGESTION_SOURCE.read_text()
        assert 'side_effect="alarm_rule_evaluation"' in source, (
            "the alarm-rule handler does not increment the counter. Telemetry keeps "
            "flowing and dashboards keep updating while no rule fires — the operator finds "
            "out by noticing an alarm that never arrived."
        )

    def test_an_alert_rule_watches_the_counter(self):
        """A counter nothing alerts on is a metric, not a signal. FS-498 found
        `EdgeAgentBufferHigh` unfirable for the whole time it existed; the same shape here
        would be a counter that increments into a dashboard nobody opens."""
        alerts = (
            pathlib.Path(__file__).resolve().parents[2]
            / "infra" / "prometheus" / "alerts.yml"
        ).read_text()
        assert "opsgrid_ingestion_side_effect_failed_total" in alerts, (
            "no alert rule reads the counter, so a persistently failing side effect still "
            "reaches nobody"
        )
        assert "IngestionSideEffectFailing" in alerts

    def test_the_alert_has_a_promtool_unit_test(self):
        """`promtool check rules` proves an expression parses, not that a series exists to
        make it true — rule 121, and exactly how EdgeAgentBufferHigh stayed useless."""
        test_file = (
            pathlib.Path(__file__).resolve().parents[2]
            / "infra" / "prometheus" / "tests" / "ingestion_side_effects_test.yml"
        )
        assert test_file.exists(), (
            "the alert has no promtool unit test, so nothing proves it can fire"
        )
        body = test_file.read_text()
        assert "IngestionSideEffectFailing" in body
        assert body.count("exp_alerts: []") >= 2, (
            "the unit test drives no must-stay-quiet cases. An alert that fires on a "
            "healthy system is as bad as one that never fires."
        )
