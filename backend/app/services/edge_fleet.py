"""Edge-fleet service: liveness logic + Prometheus metrics (tasks 17, 18).

Pure, side-effect-light helpers so the fleet logic is unit-testable without a
database or HTTP: :func:`agent_liveness` classifies an agent from its last-seen
time, and :func:`update_fleet_metrics` publishes per-agent gauges. The API layer
(:mod:`app.api.edge_fleet`) owns persistence and calls these.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from prometheus_client import Gauge

# An agent that misses this many seconds of heartbeats is considered stale;
# double that, offline. Heartbeats are expected ~every 30s.
STALE_AFTER_SECONDS = 90
OFFLINE_AFTER_SECONDS = 300


def agent_liveness(
    last_seen: Optional[datetime], now: Optional[datetime] = None
) -> str:
    """Classify an agent as 'online' | 'stale' | 'offline'."""
    if last_seen is None:
        return "offline"
    now = now or datetime.now(timezone.utc)
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=timezone.utc)
    age = (now - last_seen).total_seconds()
    if age <= STALE_AFTER_SECONDS:
        return "online"
    if age <= OFFLINE_AFTER_SECONDS:
        return "stale"
    return "offline"


# --- Prometheus fleet metrics (task 18) --------------------------------------

edge_agent_up = Gauge(
    "edge_agent_up",
    "Edge agent liveness (1=online, 0=stale/offline) as seen by the backend",
    ["agent_id"],
)
edge_agent_buffer_pending = Gauge(
    "edge_agent_buffer_pending",
    "Store-and-forward buffer depth reported by the agent",
    ["agent_id"],
)
edge_agent_dead_lettered = Gauge(
    "edge_agent_dead_lettered",
    "Dead-lettered message count reported by the agent",
    ["agent_id"],
)
#: Telemetry the agent DISCARDED — the only one of the three buffer figures that is
#: unrecoverable, and the only one that had no gauge (FS-591).
#:
#: `buffer_pending` is data waiting to send. `dead_lettered` is data preserved for replay.
#: **`dropped` is data that no longer exists anywhere**: the store-and-forward buffer sheds
#: its oldest rows on a full disk (FS-504 made it count them) and those readings are gone
#: from the edge and never reached the cloud.
#:
#: It was counted by the agent, sent in every heartbeat, accepted by `HeartbeatPayload`, and
#: written to `edge_agent_status.dropped` — then omitted from `AgentStatusOut`, given no
#: gauge here, and no alert. The one number measuring permanent loss travelled the entire
#: wire and reached nobody, while the two recoverable ones were both instrumented.
edge_agent_dropped = Gauge(
    "edge_agent_dropped",
    "Telemetry permanently discarded by the agent's buffer (unrecoverable)",
    ["agent_id"],
)
edge_agent_active_collectors = Gauge(
    "edge_agent_active_collectors",
    "Active collector count reported by the agent",
    ["agent_id"],
)
edge_agent_cert_expiry_seconds = Gauge(
    "edge_agent_cert_expiry_seconds",
    "Seconds until the agent certificate expires",
    ["agent_id"],
)


def update_fleet_metrics(agent_id: str, health: Dict[str, Any], live: str) -> None:
    """Publish per-agent gauges from a heartbeat payload."""
    edge_agent_up.labels(agent_id=agent_id).set(1 if live == "online" else 0)
    edge_agent_buffer_pending.labels(agent_id=agent_id).set(health.get("buffer_pending", 0) or 0)
    edge_agent_dead_lettered.labels(agent_id=agent_id).set(health.get("dead_lettered", 0) or 0)
    edge_agent_dropped.labels(agent_id=agent_id).set(health.get("dropped", 0) or 0)
    edge_agent_active_collectors.labels(agent_id=agent_id).set(health.get("active_collectors", 0) or 0)
    cert = health.get("cert_expires_in_seconds")
    if cert is not None:
        edge_agent_cert_expiry_seconds.labels(agent_id=agent_id).set(cert)
