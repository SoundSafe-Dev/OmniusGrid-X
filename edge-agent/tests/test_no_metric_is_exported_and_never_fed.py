"""A metric that is always zero is a lie an operator can query (FS-692).

`prometheus_client` publishes every metric on the default registry, so a counter that is
defined and never incremented does not simply *not exist* — it appears at `/metrics` with a
value of 0 and a helpful description. Someone building a dashboard finds
`opsgrid_edge_collector_messages_total`, graphs it, and gets a flat line that reads as
"this agent received no telemetry" rather than "nobody wired this up".

WHAT WAS FOUND. `COLLECTOR_MESSAGES` and its helper `record_collector_message` arrived in
the hridyansh/integration merge, which brought a second, agent-level metric family (the
UPPERCASE block from line ~232). The lowercase `messages_total` already counted the same
readings and *was* fed from `coordinator.py`. The merge kept both and wired one. Both were
exported.

WHAT THIS DOES NOT CATCH, and the distinction matters — this is the weaker sibling of
FS-691. `errors_total` had exactly one call site and so passes here, while being fed by one
path out of fifteen. A metric with a caller can still be near-silent. See rule 194: the
zero-call-site sweep and the disproportion check are different questions, and only the
second one finds the interesting defects.
"""

from __future__ import annotations

import ast
import pathlib
import re

METRICS_PY = pathlib.Path(__file__).resolve().parent.parent / "opsgrid_agent" / "metrics.py"
PACKAGE = METRICS_PY.parent

#: Metrics deliberately exported without an emitter, with the reason. Empty, and the bar for
#: adding an entry is high: an exported metric nobody feeds is a zero an operator will read
#: as a measurement.
DELIBERATELY_UNFED: dict[str, str] = {}


def _definitions() -> dict[str, str]:
    """Module-level names bound to a prometheus_client collector, by kind."""
    found = {}
    for node in ast.parse(METRICS_PY.read_text()).body:
        if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Call):
            continue
        func = node.value.func
        kind = getattr(func, "id", getattr(func, "attr", ""))
        if kind in {"Counter", "Gauge", "Histogram", "Summary"}:
            for target in node.targets:
                if isinstance(target, ast.Name):
                    found[target.id] = kind
    return found


def _helpers() -> dict[str, set[str]]:
    """Each module-level function in metrics.py, and the names its body mentions."""
    return {
        node.name: {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        for node in ast.parse(METRICS_PY.read_text()).body
        if isinstance(node, ast.FunctionDef)
    }


def _elsewhere() -> tuple[str, int]:
    files = [p for p in PACKAGE.rglob("*.py") if p.name != "metrics.py"]
    return "\n".join(p.read_text() for p in files), len(files)


def _unfed() -> list[str]:
    """Metrics reachable from no code outside metrics.py, directly or via a called helper."""
    body, _ = _elsewhere()
    helpers = _helpers()
    called = {name for name in helpers if re.search(rf"\b{name}\s*\(", body)}

    dead = []
    for metric in _definitions():
        if re.search(rf"\b{metric}\b", body):
            continue  # emitted directly
        if any(metric in helpers[h] for h in called):
            continue  # emitted through a helper somebody calls
        dead.append(metric)
    return sorted(dead)


class TestTheMeasurementIsReal:
    """Rule 165 — assert the denominator before believing an empty result."""

    def test_it_found_the_metrics(self):
        defs = _definitions()
        assert len(defs) >= 20, f"only found {sorted(defs)} — the parse is not working"
        assert "errors_total" in defs and "COLLECTOR_MESSAGES" in defs, (
            "both metric families must be visible; this file exists because one of them "
            "was invisible to everybody who read the module"
        )

    def test_it_read_the_rest_of_the_package(self):
        body, count = _elsewhere()
        assert count >= 50, f"only read {count} modules"
        assert "metrics.record_message(" in body, (
            "the emission sites are what makes a metric fed — if this substring stops "
            "appearing, every metric will look unfed and the failure will be the test's"
        )

    def test_a_helper_that_nobody_calls_does_not_count_as_feeding(self):
        """POSITIVE CONTROL, and precisely the case that hid: `record_collector_message`
        mentions `COLLECTOR_MESSAGES`, so a check that only asked 'is this metric named
        anywhere in metrics.py' would call it fed. It is fed only if the helper is CALLED."""
        helpers = _helpers()
        assert "COLLECTOR_MESSAGES" in helpers["record_collector_message"], (
            "the helper no longer touches the metric — this control has expired"
        )

    def test_a_metric_emitted_only_through_a_helper_is_seen_as_fed(self):
        """NEGATIVE CONTROL. Most metrics here are never named outside metrics.py; they are
        emitted through helpers. A detector that missed that would report twenty defects."""
        assert "quality_flag_total" not in _unfed(), (
            "quality_flag_total is emitted by record_quality, which the pipeline calls"
        )


def test_every_metric_is_fed_by_something():
    unfed = [m for m in _unfed() if m not in DELIBERATELY_UNFED]
    assert not unfed, (
        f"{unfed} are exported at /metrics and incremented by nothing.\n\n"
        f"prometheus_client publishes the whole default registry, so these appear with a "
        f"value of 0 and a description that says what they would have meant. A dashboard "
        f"built on one shows a flat line that reads as 'no traffic'. Wire it at the site "
        f"its twin is already wired, or delete it."
    )
