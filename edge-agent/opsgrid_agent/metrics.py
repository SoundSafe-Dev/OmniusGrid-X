"""Prometheus metrics for the edge agent.

Instrumentation lives at the coordinator/adapter seam (see coordinator.py), which
every collector — mature and BaseCollector-style — funnels through, so a single
set of metrics covers all collector types without editing individual collectors.

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
    "Errors raised while handling a collector reading",
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


def set_buffer_stats(pending: int, backfill_lag_seconds: float) -> None:
    buffer_messages.set(pending)
    buffer_backfill_lag_seconds.set(backfill_lag_seconds)


def record_dead_lettered(count: int) -> None:
    if count > 0:
        buffer_dead_lettered_total.inc(count)


def record_dropped(count: int) -> None:
    if count > 0:
        buffer_dropped_total.inc(count)
