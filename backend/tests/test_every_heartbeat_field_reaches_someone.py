"""Every field the edge agent sends reaches a human or a gauge (FS-591).

THE CARRY-ACROSS. FS-485 swept "a signal the server sends and nothing consumes". This asks the
same question of the **edge→backend heartbeat**, which is the one wire in this product where a
field crosses a network, a schema, an ORM and a response model — four places it can be dropped,
each of which fails silently.

WHAT IT FOUND: `dropped`.

The agent counts telemetry its store-and-forward buffer discarded — FS-504 built that counter,
because up to 500 undelivered readings vanished per disk-full event with nothing recording it.
The count is then sent in every heartbeat, accepted by `HeartbeatPayload`, and written to
`edge_agent_status.dropped`.

And then: **`AgentStatusOut` omitted it, `update_fleet_metrics` set no gauge for it, and no
alert rule named it.** FastAPI deletes an undeclared field rather than erroring, so the number
travelled the entire wire, landed in a column, and reached nobody.

**It is the only one of the three buffer figures that is unrecoverable.** `buffer_pending` is
data waiting to send. `dead_lettered` is data preserved for replay. `dropped` is data that no
longer exists anywhere — gone from the device, never arrived in the cloud. Both recoverable
figures had a gauge and one had an alert; the permanent one had neither, plus no response
field. The instrumentation was inversely proportional to the severity.

WHY A GUARD RATHER THAN THREE EDITS. Four boundaries, each silent. A field can be added to the
agent and stop at any one of them, and the symptom is always the same — a number nobody sees —
which is indistinguishable from a healthy fleet.
"""

from __future__ import annotations

import ast
import pathlib

import pytest

BACKEND = pathlib.Path(__file__).resolve().parents[1]
REPO = BACKEND.parent
AGENT_HEARTBEAT = REPO / "edge-agent" / "opsgrid_agent" / "heartbeat.py"
API = BACKEND / "app" / "api" / "edge_fleet.py"
SERVICE = BACKEND / "app" / "services" / "edge_fleet.py"
ALERTS = REPO / "infra" / "prometheus" / "alerts.yml"

#: Heartbeat fields deliberately not surfaced, with why. Empty — a field the agent bothers to
#: compute and send, and nothing shows, is either a gap or dead weight, and both need saying.
NOT_SURFACED: dict[str, str] = {
    "agent_version": (
        "SERVED, but by a different route from a different column, and that is worth "
        "someone checking. `GET /fleet/agents/versions` builds the version distribution "
        "from `Asset.agent_version`, which the KAFKA heartbeat path writes "
        "(`workers/ingestion.py:415`). The HTTP heartbeat here writes "
        "`EdgeAgentStatus.agent_version` instead. Two writers, two tables, one fact — so "
        "an agent reporting over one path and not the other appears at a different version "
        "depending on which screen you open.\n\n"
        "NOT RESOLVED HERE. Reconciling them means deciding which table owns the fleet's "
        "version, which is the OTA lane's call; recorded so the next person to touch either "
        "writer sees the other. Rule 122 — two components each correct about themselves."
    ),
}

#: Fields whose meaning is metadata rather than a measurement, so a gauge would be nonsense.
NOT_A_METRIC = {
    "agent_version": (
        "a string rather than a measurement — and see NOT_SURFACED above for the two-writer "
        "problem it actually has"
    ),
    "cert_expires_in_seconds": (
        "already has its own gauge and two alert rules under a different name "
        "(edge_agent_cert_expiry_seconds)"
    ),
    "total_collectors": (
        "the denominator for active_collectors, which is gauged; a gauge for the "
        "denominator alone says nothing an operator can act on"
    ),
}


def _sent_fields() -> set[str]:
    """Keys the agent puts in its heartbeat payload."""
    tree = ast.parse(AGENT_HEARTBEAT.read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "build_payload":
            for child in ast.walk(node):
                if isinstance(child, ast.Dict):
                    return {
                        k.value
                        for k in child.keys
                        if isinstance(k, ast.Constant) and isinstance(k.value, str)
                    }
    return set()


def _model_fields(source: str, class_name: str) -> set[str]:
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == class_name:
            return {
                stmt.target.id
                for stmt in node.body
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name)
            }
    return set()


class TestTheSweepHasBothSides:
    def test_it_reads_the_agent_payload(self):
        """Vacuity. If the agent's builder were renamed this file would compare an empty set
        against everything and pass — while the wire it exists to check went unexamined."""
        sent = _sent_fields()
        assert len(sent) >= 5, f"only {sent} parsed out of the agent's build_payload"
        assert "buffer_pending" in sent

    def test_it_reads_the_backend_models(self):
        accepted = _model_fields(API.read_text(), "HeartbeatPayload")
        served = _model_fields(API.read_text(), "AgentStatusOut")
        assert len(accepted) >= 5 and len(served) >= 5


class TestNothingIsDroppedAtABoundary:
    def test_every_sent_field_is_accepted(self):
        """Boundary one. Pydantic ignores an unknown key, so a field the agent adds and the
        model does not declare is discarded on arrival with no error."""
        missing = sorted(_sent_fields() - _model_fields(API.read_text(), "HeartbeatPayload"))
        assert not missing, (
            f"the agent sends {missing} and HeartbeatPayload does not declare them, so "
            f"pydantic drops them silently at the door"
        )

    def test_every_accepted_field_is_served_or_recorded(self):
        """Boundary three, and the one `dropped` fell through. FastAPI OMITS an undeclared
        response field rather than erroring — the value is set on the server and absent from
        the payload, with nothing anywhere reporting a problem."""
        accepted = _model_fields(API.read_text(), "HeartbeatPayload")
        served = _model_fields(API.read_text(), "AgentStatusOut")
        unsurfaced = sorted(accepted - served - set(NOT_SURFACED))
        assert not unsurfaced, (
            f"{unsurfaced} are accepted from the agent and never served. The agent computes "
            f"and transmits them every heartbeat and no fleet view shows them — which is "
            f"exactly what happened to `dropped`, the count of permanently lost telemetry. "
            f"Serve it, or record it in NOT_SURFACED with why."
        )

    def test_every_numeric_field_has_a_gauge_or_a_reason(self):
        """Boundary four. A field served in JSON but absent from Prometheus is visible only
        to somebody already looking at the right page."""
        service = SERVICE.read_text()
        accepted = _model_fields(API.read_text(), "HeartbeatPayload")
        ungauged = sorted(
            field
            for field in accepted - set(NOT_A_METRIC) - set(NOT_SURFACED)
            if f'health.get("{field}"' not in service
        )
        assert not ungauged, (
            f"{ungauged} are accepted from every agent and no gauge publishes them, so the "
            f"fleet's behaviour is invisible to alerting. Add a gauge in "
            f"`update_fleet_metrics`, or a NOT_A_METRIC entry saying why a gauge would be "
            f"nonsense."
        )


class TestTheUnrecoverableFigureIsTheBestInstrumented:
    """`dropped` had the least instrumentation of the three and the worst consequence.
    These pin the inversion closed."""

    def test_dropped_is_served(self):
        assert "dropped" in _model_fields(API.read_text(), "AgentStatusOut"), (
            "AgentStatusOut omits `dropped` again. buffer_pending is data waiting to send "
            "and dead_lettered is replayable; this one is gone from the device and never "
            "arrived — and it is the one no fleet view shows."
        )

    def test_dropped_has_a_gauge(self):
        assert "edge_agent_dropped" in SERVICE.read_text()

    def test_dropped_has_an_alert(self):
        alerts = ALERTS.read_text()
        assert "edge_agent_dropped" in alerts, (
            "no alert reads the dropped counter, so permanent telemetry loss reaches nobody "
            "— while the two RECOVERABLE figures both have one"
        )
        assert "EdgeAgentDroppingTelemetry" in alerts

    def test_the_alert_reads_an_increase_not_a_total(self):
        """The counter is cumulative. A threshold on the raw gauge pages forever about an
        outage last quarter, and an alert that always fires is muted within a day."""
        alerts = ALERTS.read_text()
        block = alerts[alerts.index("EdgeAgentDroppingTelemetry") :][:400]
        assert "increase(edge_agent_dropped" in block, (
            "the rule thresholds the cumulative total rather than its increase, so it fires "
            "permanently once any agent has ever dropped a reading"
        )

    def test_the_alert_has_a_promtool_test(self):
        body = (ALERTS.parent / "tests" / "edge_alerts_test.yml").read_text()
        assert "EdgeAgentDroppingTelemetry" in body, (
            "`promtool check rules` proves the expression parses, never that a series exists "
            "to make it true — which is how EdgeAgentBufferHigh stayed unfirable (FS-498)"
        )

    @pytest.mark.parametrize("field", ["buffer_pending", "dead_lettered", "dropped"])
    def test_all_three_buffer_figures_are_gauged(self, field: str):
        """Together, because the finding was the *inversion*: the two recoverable figures
        were instrumented and the unrecoverable one was not. Checking them as a set is what
        makes that visible rather than three unrelated passes."""
        assert f'health.get("{field}"' in SERVICE.read_text()
