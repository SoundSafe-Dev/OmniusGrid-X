# Subsystem alerts runbook

Response guidance for the `opsgrid_subsystems` Prometheus alert group
(`infra/prometheus/alerts.yml`, added in FS-107). These cover the subsystems
FS-105 instrumented — notifications, predictive maintenance (RUL), the
digital-twin optimizer, the historian, the error tracker, and ingestion lag.

Each alert carries a `runbook_url` anchor into this file. All thresholds are
tuned so an idle subsystem produces no series and therefore never pages.

## Notifications

**NotificationDeliveryFailing** — >20% of `opsgrid_notification_dispatches_total`
came back `status="failure"` over 10m.
1. Check which `channel` label dominates the failures (webhook/email/sms).
2. For webhooks: verify the subscriber target is reachable and not returning
   4xx/5xx (`/api/v1/notifications/subscriptions`). For email/SMS: check the
   provider credentials and quota.
3. Failures do not drop the alert — the underlying event still exists — but
   operators are not being told. Treat as time-sensitive if a critical-severity
   subscription is affected.

**NotificationDeliverySlow** — p95 `opsgrid_notification_delivery_duration_seconds`
above 10s for the labelled channel. A slow channel serialises behind the
dispatcher and delays every following notification. Usually an upstream provider
latency spike; consider disabling the offending channel until it recovers.

## Predictive maintenance

**PredictiveMaintenanceLowRULSurge** — more than 5 high/critical low-RUL alerts
raised in the trailing hour.
1. Open the Predictive Maintenance board and confirm whether this is a real
   cluster of aging assets (expected: correlated wear on a line) or noise.
2. If the assets are unrelated, suspect the input feed — a bad health-index or
   telemetry-degradation slope will skew the RUL estimator. Cross-check
   `opsgrid_rul_assessment_duration_seconds` and the health-index service.

## Digital twin

**DigitalTwinOptimizeSlow** — p95 `opsgrid_twin_optimize_run_duration_seconds`
above 10s for 15m. The candidate sweep is likely too wide or the baseline pull
is slow. Recommendations lag while runs queue. Check the optimizer's candidate
count and the baseline query against TimescaleDB.

## Historian

**HistorianQueriesSlow** — p95 `opsgrid_historian_query_duration_seconds` above
2.5s for the labelled `granularity`. Dashboards and exports read from the
historian and will feel it. Check continuous-aggregate freshness, chunk pruning,
and whether a wide time-range query is scanning raw hypertable chunks.

## Error tracker

**ErrorTrackerDropping** (critical) — `opsgrid_error_tracker_dropped_total`
increased: the aggregator hit capacity and is discarding occurrences. This is an
observability blind spot — Error Triage is now under-counting. Investigate the
flush pipeline (see below) before trusting any error dashboard.

**ErrorTrackerFlushFailing** — flush cycles are failing and re-queuing batches.
Almost always the errors sink (DB) is unreachable or slow. Fix before the
pending buffer fills and escalates to `ErrorTrackerDropping`.

**ErrorTrackerBacklog** — `opsgrid_error_tracker_pending_fingerprints` above 500
for 10m: intake is outrunning flush. Correlate with `ErrorTrackerFlushFailing`
and the sink health.

## Ingestion

**IngestionLagHighApp** — `opsgrid_ingestion_lag_seconds` above 120s on a topic
for 10m. This is the wall-clock event-to-write lag the ingestion worker observes
(complements the broker-side consumer-group lag alert `IngestionLagHigh`).
Telemetry is landing late; check ingestion-worker throughput, the Redpanda
consumer, and the TimescaleDB write path.
