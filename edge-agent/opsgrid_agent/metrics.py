"""Prometheus metrics for the edge agent.

Metric names align with backend/alert definitions where possible
(see ``opsgrid_edge_buffer_messages`` in ``backend/app/api/health.py`` and
``infra/prometheus/alerts.yml``).
"""

from prometheus_client import Counter, Gauge, start_http_server

_agent_id = "unknown"

COLLECTOR_MESSAGES = Counter(
    "opsgrid_edge_collector_messages_total",
    "Total telemetry messages received from collectors",
    ["agent_id", "asset_id", "collector_type"],
)

KAFKA_PUBLISH_SUCCESS = Counter(
    "opsgrid_edge_kafka_publish_total",
    "Kafka publish attempts that succeeded",
    ["agent_id"],
)

KAFKA_PUBLISH_ERRORS = Counter(
    "opsgrid_edge_kafka_publish_errors_total",
    "Kafka publish attempts that failed",
    ["agent_id"],
)

BUFFER_MESSAGES = Gauge(
    "opsgrid_edge_buffer_messages",
    "Messages waiting in the local SQLite buffer",
    ["agent_id", "asset_id"],
)

COLLECTORS_ACTIVE = Gauge(
    "opsgrid_edge_collectors_active",
    "Collector tasks currently running",
    ["agent_id"],
)

COLLECTORS_CONFIGURED = Gauge(
    "opsgrid_edge_collectors_configured",
    "Collectors registered in configuration",
    ["agent_id"],
)


def configure(agent_id: str) -> None:
    """Set the agent id used as a label on all metrics."""
    global _agent_id
    _agent_id = agent_id


def start_metrics_server(port: int) -> None:
    """Expose ``/metrics`` on ``port`` (daemon thread)."""
    start_http_server(port)


def record_collector_message(asset_id: str, collector_type: str) -> None:
    COLLECTOR_MESSAGES.labels(
        agent_id=_agent_id,
        asset_id=asset_id,
        collector_type=collector_type,
    ).inc()


def record_kafka_success() -> None:
    KAFKA_PUBLISH_SUCCESS.labels(agent_id=_agent_id).inc()


def record_kafka_error() -> None:
    KAFKA_PUBLISH_ERRORS.labels(agent_id=_agent_id).inc()


def refresh_buffer_stats(total_messages: int) -> None:
    """Update buffer depth gauge (aggregate across assets)."""
    BUFFER_MESSAGES.labels(agent_id=_agent_id, asset_id="_all").set(total_messages)


def refresh_collector_stats(active: int, configured: int) -> None:
    COLLECTORS_ACTIVE.labels(agent_id=_agent_id).set(active)
    COLLECTORS_CONFIGURED.labels(agent_id=_agent_id).set(configured)
