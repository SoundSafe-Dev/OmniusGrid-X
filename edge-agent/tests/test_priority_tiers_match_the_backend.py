"""The edge tier table is a copy of the backend's; this holds the copy honest (FS-754).

`opsgrid_agent/buffer/priority.py` duplicates the metric->tier mapping from
`backend/app/services/data_shedding.py` deliberately — the agent is a separate deployable
and cannot import the backend package. Duplication without a parity guard is how the role
vocabulary drifted before `test_role_vocabulary_parity.py` was written, so this file is the
same idea applied to the same failure mode.

The backend is read by AST rather than imported. Importing it would drag in SQLAlchemy,
settings and a database URL into an edge-agent test run that has none of them, and the thing
being compared is a dict literal — the source IS the fact.
"""

import ast
from pathlib import Path

import pytest

from opsgrid_agent.buffer.priority import (
    DEFAULT_PRIORITY,
    HIGHEST_PRIORITY,
    LOWEST_PRIORITY,
    PRIORITY_BY_METRIC,
    priority_for,
)

BACKEND_SOURCE = (
    Path(__file__).resolve().parents[2]
    / "backend"
    / "app"
    / "services"
    / "data_shedding.py"
)


def _backend_tiers() -> dict:
    """Extract `metric -> priority` from the backend's `PriorityConfig(...)` literals."""
    tree = ast.parse(BACKEND_SOURCE.read_text())
    found = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.Dict):
            continue
        for key, value in zip(node.keys, node.values):
            if not isinstance(key, ast.Constant) or not isinstance(key.value, str):
                continue
            if not isinstance(value, ast.Call):
                continue
            func = value.func
            name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", "")
            if name != "PriorityConfig":
                continue
            for kw in value.keywords:
                if kw.arg == "priority" and isinstance(kw.value, ast.Constant):
                    found[key.value] = kw.value.value
    return found


class TestTheTwoTablesAgree:
    def test_the_backend_table_was_actually_found(self):
        """Vacuity. An AST walk that matches nothing returns {} and every comparison
        below would pass trivially — including after somebody renames `PriorityConfig`
        or moves the file."""
        assert BACKEND_SOURCE.exists(), f"backend source moved: {BACKEND_SOURCE}"
        tiers = _backend_tiers()
        assert len(tiers) >= 15, (
            f"extracted only {len(tiers)} tiers from {BACKEND_SOURCE.name}; the parser has "
            "stopped matching and this whole file is now measuring nothing"
        )
        assert set(tiers.values()) == {1, 2, 3, 4, 5}, tiers

    def test_every_backend_metric_is_classified_on_the_edge(self):
        missing = sorted(set(_backend_tiers()) - set(PRIORITY_BY_METRIC))
        assert not missing, (
            f"the backend classifies {missing} but the edge does not, so these arrive in "
            f"the default tier {DEFAULT_PRIORITY} and are drained and shed as if nobody had "
            "an opinion. Add them to opsgrid_agent/buffer/priority.py."
        )

    def test_no_metric_is_classified_differently_on_the_two_sides(self):
        backend = _backend_tiers()
        disagreements = {
            metric: (tier, PRIORITY_BY_METRIC[metric])
            for metric, tier in backend.items()
            if metric in PRIORITY_BY_METRIC and PRIORITY_BY_METRIC[metric] != tier
        }
        assert not disagreements, (
            "backend tier != edge tier for {} (metric: backend, edge). The two sides shed "
            "in opposite directions when they disagree.".format(disagreements)
        )

    def test_the_edge_invents_no_tier_the_backend_has_never_heard_of(self):
        """The other direction. An edge-only classification is not automatically wrong,
        but it must be a deliberate addition, not a typo that quietly demotes a metric."""
        extra = sorted(set(PRIORITY_BY_METRIC) - set(_backend_tiers()))
        assert not extra, (
            f"the edge classifies {extra} and the backend does not. If this is intended, "
            "add it to backend/app/services/data_shedding.py too — otherwise it is a "
            "misspelling, and a misspelled metric silently falls back to the default tier."
        )


class TestTheClassifierItself:
    def test_safety_events_are_the_highest_tier(self):
        for metric in ("emergency_stop", "alarm", "packml_state"):
            assert PRIORITY_BY_METRIC[metric] == HIGHEST_PRIORITY, metric

    def test_bulk_telemetry_outranks_nothing_it_should_not(self):
        assert PRIORITY_BY_METRIC["vibration"] > PRIORITY_BY_METRIC["emergency_stop"]
        assert PRIORITY_BY_METRIC["debug"] == LOWEST_PRIORITY

    def test_an_unclassified_metric_lands_in_the_default_tier(self):
        assert priority_for("telemetry", {"widget_count": 3}) == DEFAULT_PRIORITY
        assert priority_for("something_nobody_named") == DEFAULT_PRIORITY

    def test_the_payload_is_read_not_only_the_topic(self):
        """The agent publishes `topic="telemetry.<asset>"` with metric names as payload
        keys. Classifying on topic alone puts every reading in tier 3 and the whole
        mechanism becomes a no-op that still looks implemented."""
        assert priority_for("telemetry.press-01", {"vibration_rms": 0.4}) == DEFAULT_PRIORITY
        assert priority_for("telemetry.press-01", {"vibration": 0.4}) == 4
        assert priority_for("telemetry.press-01", {"emergency_stop": True}) == 1

    def test_the_strongest_tier_in_a_batch_wins(self):
        mixed = {"vibration": 0.4, "debug": "x", "alarm": "HIGH"}
        assert priority_for("telemetry", mixed) == 1, (
            "a batch containing an alarm must drain as an alarm; taking the weakest or the "
            "last-seen tier would let a caller bury a safety event under padding"
        )

    @pytest.mark.parametrize("field", ["metric_name", "metric", "event_type"])
    def test_an_envelope_field_can_name_the_class_of_data(self, field):
        assert priority_for("telemetry", {field: "emergency_stop", "value": 1}) == 1
