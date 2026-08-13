"""Prometheus metrics for the edge agent.

Delivery instrumentation lives at the coordinator/adapter seam (see coordinator.py),
which every reading funnels through, so message counts cover all collector types
without editing individual collectors.

THAT SEAM CANNOT SEE A FAILED COLLECTION (FS-691), and this docstring used to claim
otherwise. A poll that fails produces no message, so it never reaches the seam;
`record_error` there fires only when a message *handler* raises, which is the
opposite case. For years the consequence was that `errors_total` was incremented by
nothing at all, while a device returning 500 on every poll showed `connection_state`
up — that gauge is derived from whether the poll TASK is alive, and it is.

Failures are therefore reported by the collector, through `BaseCollector.record_failure`,
which logs and counts together. See that method for the drive that exposed it.

Dependency-light and free of collector imports, so it stays cheap and independent
of the omniusgrid_agent -> opsgrid_agent rename.
"""

from typing import Optional

from prometheus_client import Counter, Gauge, Histogram

messages_total = Counter(
    "edge_collector_messages_total",
    "Readings received from collectors and handed to the buffer",
    ["asset_id", "collector_type"],
)

errors_total = Counter(
    "edge_collector_errors_total",
    "Failed collection cycles, and errors raised while handling a reading",
    ["asset_id", "collector_type"],
)

connection_state = Gauge(
    "edge_collector_connection_state",
    "Collector liveness as seen by the coordinator (1=active, 0=down)",
    ["asset_id", "collector_type"],
)

message_age_seconds = Histogram(
    "edge_collector_message_age_seconds",
    "End-to-edge age of a reading at receipt (now - timestamp_edge)",
    ["collector_type"],
)


def record_message(
    asset_id: str, collector_type: str, age_seconds: Optional[float] = None
) -> None:
    messages_total.labels(asset_id=asset_id, collector_type=collector_type).inc()
    if age_seconds is not None and age_seconds >= 0:
        message_age_seconds.labels(collector_type=collector_type).observe(age_seconds)


def record_error(asset_id: str, collector_type: str) -> None:
    errors_total.labels(asset_id=asset_id, collector_type=collector_type).inc()


def set_connection_state(asset_id: str, collector_type: str, up: bool) -> None:
    connection_state.labels(asset_id=asset_id, collector_type=collector_type).set(
        1 if up else 0
    )


# --- Store-and-forward buffer -------------------------------------------------

buffer_messages = Gauge(
    "edge_buffer_messages",
    "Messages currently pending in the store-and-forward buffer",
)

buffer_backfill_lag_seconds = Gauge(
    "edge_buffer_backfill_lag_seconds",
    "Age of the oldest pending buffered message (now - timestamp_edge)",
)

buffer_dead_lettered_total = Counter(
    "edge_buffer_dead_lettered_total",
    "Messages moved to the dead-letter table after exhausting retries",
)

buffer_dropped_total = Counter(
    "edge_buffer_dropped_total",
    "Oldest messages pruned to keep the buffer under its size limit",
)


buffer_expired_total = Counter(
    "edge_buffer_expired_total",
    "Undelivered messages deleted for passing the retention window",
)


def set_buffer_stats(pending: int, backfill_lag_seconds: float) -> None:
    buffer_messages.set(pending)
    buffer_backfill_lag_seconds.set(backfill_lag_seconds)


def record_dead_lettered(count: int) -> None:
    if count > 0:
        buffer_dead_lettered_total.inc(count)


def record_dropped(count: int) -> None:
    if count > 0:
        buffer_dropped_total.inc(count)


def record_expired(count: int) -> None:
    """Telemetry deleted for age, having never been delivered (FS-458).

    The buffer loses messages three ways — dead-lettered after retries, pruned for size,
    and expired for age. The first two increment a counter; this one only logged, at INFO,
    on a device that by definition has been unable to reach the cloud for longer than the
    retention window. The one loss whose cause is a LONG OUTAGE was the one invisible to
    the monitoring that would show the outage.
    """
    if count > 0:
        buffer_expired_total.inc(count)


# --- Local OEE (from PackML states) ------------------------------------------

oee_availability = Gauge("edge_oee_availability", "Local OEE availability ratio", ["asset_id"])
oee_performance = Gauge("edge_oee_performance", "Local OEE performance ratio", ["asset_id"])
oee_quality = Gauge("edge_oee_quality", "Local OEE quality ratio", ["asset_id"])
oee_ratio = Gauge("edge_oee", "Local OEE (availability x performance x quality)", ["asset_id"])


def set_oee(asset_id: str, result: dict) -> None:
    """Publish a LocalOEECalculator result dict (percentages 0-100).

    A factor that could not be computed is **not published** (FS-461). Prometheus has no
    null, and `.set(0.0)` on an unmeasurable factor is not a neutral default: 0% OEE is
    the single worst number this system can report about a machine, and it was being
    reported for every asset whose telemetry carries no part counts.

    The series simply does not advance. A gauge that stops updating is what "no data"
    looks like in Prometheus, and `absent()` / staleness are the tools written for it —
    both of which a hardcoded zero defeats.
    """
    for gauge, key in (
        (oee_availability, "availability"),
        (oee_performance, "performance"),
        (oee_quality, "quality"),
        (oee_ratio, "oee"),
    ):
        value = result.get(key)
        if value is not None:
            gauge.labels(asset_id=asset_id).set(value)


packml_unmapped_total = Counter(
    "edge_packml_unmapped_total",
    "Vendor states the PackML mapper does not understand",
    ["asset_type"],
)


def record_packml_unmapped(asset_type: str) -> None:
    """A vendor state the mapper could not translate (FS-462).

    These used to become `Idle`, which is an AVAILABILITY LOSS state — a machine running
    at full rate recorded as down, with one log line on a device that may not be able to
    ship logs. This counter is what makes a missing mapping visible from the cloud, and it
    is labelled by ASSET TYPE rather than by the vendor string: the string is arbitrary
    text off a PLC, and using it as a label would hand unbounded cardinality to Prometheus.
    """
    packml_unmapped_total.labels(asset_type=asset_type or "generic").inc()


# --- Local analytics: anomalies + alerts -------------------------------------

anomaly_z_score = Gauge(
    "edge_anomaly_z_score",
    "Z-score of the most recent anomaly per metric",
    ["asset_id", "metric"],
)
anomaly_total = Counter(
    "edge_anomaly_total",
    "Anomalies detected by the edge anomaly detector",
    ["asset_id", "metric", "severity"],
)
alert_triggered_total = Counter(
    "edge_alert_triggered_total",
    "Local alert rules fired",
    ["asset_id", "rule_id", "severity"],
)


def record_anomaly(asset_id: str, anomaly: dict) -> None:
    metric = str(anomaly.get("metric_name", ""))
    anomaly_z_score.labels(asset_id=asset_id, metric=metric).set(anomaly.get("z_score", 0.0))
    anomaly_total.labels(
        asset_id=asset_id, metric=metric, severity=str(anomaly.get("severity", ""))
    ).inc()


def record_alert(asset_id: str, alert: dict) -> None:
    alert_triggered_total.labels(
        asset_id=asset_id,
        rule_id=str(alert.get("rule_id", "")),
        severity=str(alert.get("severity", "")),
    ).inc()


# --- Data-quality pipeline ----------------------------------------------------

quality_readings_total = Counter(
    "edge_quality_readings_total",
    "Readings processed by the data-quality pipeline, by decided action",
    ["asset_id", "action"],
)

quality_flag_total = Counter(
    "edge_quality_flag_total",
    "Quality flags raised on readings (a reading may raise several)",
    ["asset_id", "flag"],
)


def record_quality(asset_id: str, action: str, flags: list) -> None:
    """Publish the outcome of one quality-pipeline decision."""
    quality_readings_total.labels(asset_id=asset_id, action=action).inc()
    for flag in flags:
        quality_flag_total.labels(asset_id=asset_id, flag=str(flag)).inc()


# ---- Converged from hridyansh/integration: agent-level metrics API ----
# Metric names align with backend/alert definitions where possible
# (see ``opsgrid_edge_buffer_messages`` in ``backend/app/api/health.py`` and
# ``infra/prometheus/alerts.yml``).

from prometheus_client import Counter, Gauge, start_http_server  # noqa: F811

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
