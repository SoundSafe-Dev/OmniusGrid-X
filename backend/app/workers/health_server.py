"""Health + Prometheus endpoint for the background workers (FS-213/214).

The four workers (ingestion, export delivery, compliance reports, OTA rollouts)
exposed NOTHING: no HTTP server, no metrics port, no health signal. Two
consequences, both real:

* **Kubernetes could not tell a wedged worker from a healthy one.** Their
  Deployments carry no probes, because there was nothing to probe. If a consumer
  loop dies while the process stays alive — an unhandled task exception, a broker
  connection that never recovers — the pod keeps running forever and the queue
  silently backs up. A liveness probe is the only thing that restarts that.
* **They were invisible to Prometheus.** The scrape config has no worker job, and
  adding one would have scraped nothing. The `opsgrid_*` metrics the app already
  defines are only reachable through the API's `/metrics`, so anything a worker
  recorded never left the pod.

This is deliberately the same shape as `edge-agent/opsgrid_agent/metrics_server.py`
— a small threaded stdlib server, because `prometheus_client.start_http_server`
serves only `/metrics` and probes need a separate health path.

Liveness is HEARTBEAT-BASED rather than "the process is up": a worker calls
``beat()`` each time it completes a unit of work, and `/healthz` fails once the
last beat is older than the configured staleness window. That is what makes the
probe meaningful — a process that is running but no longer consuming reports
unhealthy and gets restarted, which is the case a plain TCP or "process exists"
check cannot detect.
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

import structlog
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Gauge, generate_latest

logger = structlog.get_logger()

# Exported so Prometheus can see per-worker liveness and throughput once the
# scrape job exists. Labelled by worker so one job covers all four.
WORKER_HEARTBEAT_AGE = Gauge(
    "opsgrid_worker_heartbeat_age_seconds",
    "Seconds since this worker last completed a unit of work",
    ["worker"],
)
WORKER_UNITS = Counter(
    "opsgrid_worker_units_total",
    "Units of work completed by this worker",
    ["worker"],
)

#: Telemetry this worker ACCEPTED from a device and then could not process (FS-464).
#:
#: The message is published to a dead-letter topic so it can be replayed, which makes it
#: recoverable — but recoverable is not the same as noticed. Until this counter existed the
#: only record was a log line, on the one path where the data has already been acknowledged
#: to the device that sent it: the agent's buffer drops it after the ack, so a poison
#: message is gone from the edge and invisible in the cloud.
#:
#: The agent side of exactly this has had a counter and a Prometheus alert since FS-458.
#: **The platform was monitoring the edge's data loss and not its own.**
#:
#: Labelled by SOURCE TOPIC, which is bounded (a handful of topics), never by error text.
INGESTION_DEAD_LETTERED = Counter(
    "opsgrid_ingestion_dead_lettered_total",
    "Messages the ingestion worker could not process and published to the DLQ",
    ["source_topic"],
)

#: The DLQ publish itself failing, which is the TOTAL loss: the message is neither
#: processed nor preserved, and its offset advances regardless. Separate from the counter
#: above because they need different responses — one is a bug to fix at leisure, the other
#: is data leaving the system.
INGESTION_DEAD_LETTER_FAILED = Counter(
    "opsgrid_ingestion_dead_letter_failed_total",
    "Messages lost entirely because the dead-letter publish also failed",
    ["source_topic"],
)

#: Side effects on the hot ingest path that failed and were swallowed (FS-537).
#:
#: FIVE OF THEM, AND SWALLOWING IS RIGHT. Ingestion must not stop because a WebSocket
#: publish failed or an OEE counter could not be updated — telemetry that reached the
#: database is the thing that matters, and the alternative is a poison message halting the
#: pipeline. What was missing is that **nothing counted them.**
#:
#: One of the five is `alarm_rule_evaluation` (`ingestion.py:475`). A rule that raises on
#: every message writes one `alarm_rule_evaluation_failed` line per message and nothing
#: aggregates it, so "server-side alarm rules stopped firing" is a condition the platform
#: cannot report and an operator discovers by noticing an alarm that never arrived. The
#: telemetry keeps flowing, the dashboards keep updating, and the alerting is off.
#:
#: This is the same argument as `INGESTION_DEAD_LETTERED` above — recoverable is not the
#: same as noticed — and the same as FS-496 and FS-504 on the edge agent, where a 100%
#: failing path produced a debug line and a counter was the whole fix. The platform was
#: monitoring the edge's silent failures and not its own, twice.
#:
#: Labelled by SIDE EFFECT, which is a fixed set of five, never by error text.
INGESTION_SIDE_EFFECT_FAILED = Counter(
    "opsgrid_ingestion_side_effect_failed_total",
    "Non-fatal side effects on the ingest path that raised and were swallowed",
    ["side_effect"],
)

#: The five, named. A sixth swallow added without a name here counts under nothing, so the
#: guard asserts this set against the handlers in `ingestion.py`.
INGESTION_SIDE_EFFECTS = (
    "websocket_telemetry_publish",
    "oee_telemetry_tracking",
    "alarm_rule_evaluation",
    "websocket_state_publish",
    "oee_state_tracking",
    # THE SIXTH, found by the guard and not by the survey that preceded it. The plan
    # counted five swallows on the ingest path; `_process_alarm`'s WebSocket publish is a
    # seventh handler in the file and the sixth of this class. Its failure means an alarm
    # was written to the database and never reached the live feed — so the alarm exists,
    # the page does not update, and nothing says why.
    "websocket_alarm_publish",
)


_started = False


class WorkerHealth:
    """Heartbeat state for one worker process."""

    def __init__(self, worker: str, stale_after_seconds: float = 300.0):
        self.worker = worker
        self.stale_after = stale_after_seconds
        self._last_beat = time.monotonic()
        self._ready = False
        self._lock = threading.Lock()

    def ready(self) -> None:
        """Mark startup complete (broker connected, consumer subscribed)."""
        with self._lock:
            self._ready = True
            self._last_beat = time.monotonic()

    def beat(self) -> None:
        """Record a completed unit of work."""
        with self._lock:
            self._last_beat = time.monotonic()
        WORKER_UNITS.labels(self.worker).inc()

    def snapshot(self) -> dict:
        with self._lock:
            age = time.monotonic() - self._last_beat
            ready = self._ready
        WORKER_HEARTBEAT_AGE.labels(self.worker).set(age)
        # An idle worker is healthy — a queue with nothing in it produces no
        # beats. Staleness only condemns a worker that was working and stopped,
        # which is why `stale_after` must exceed the expected idle gap. Workers
        # with genuinely unbounded idle periods should pass stale_after=0 to
        # opt out of staleness and keep readiness-only semantics.
        stale = self.stale_after > 0 and age > self.stale_after
        return {
            "status": "error" if (ready and stale) else "ok",
            "worker": self.worker,
            "ready": ready,
            "heartbeat_age_seconds": round(age, 1),
            "stale_after_seconds": self.stale_after,
        }


def _make_handler(health: WorkerHealth):
    class Handler(BaseHTTPRequestHandler):
        def _write(self, code: int, content_type: str, body: bytes) -> None:
            self.send_response(code)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):  # noqa: N802 (stdlib API)
            if self.path.startswith("/metrics"):
                self._write(200, CONTENT_TYPE_LATEST, generate_latest())
            elif self.path.startswith("/healthz"):
                snap = health.snapshot()
                self._write(
                    503 if snap["status"] == "error" else 200,
                    "application/json",
                    json.dumps(snap).encode(),
                )
            elif self.path.startswith("/readyz"):
                snap = health.snapshot()
                self._write(
                    200 if snap["ready"] else 503,
                    "application/json",
                    json.dumps(snap).encode(),
                )
            else:
                self._write(404, "text/plain", b"not found")

        def log_message(self, *args):  # silence per-request stderr logging
            return

    return Handler


def create_server(port: int, health: WorkerHealth) -> ThreadingHTTPServer:
    """Build (but do not start) the worker health/metrics server."""
    return ThreadingHTTPServer(("0.0.0.0", port), _make_handler(health))


def start_health_server(
    worker: str,
    port: Optional[int] = None,
    stale_after_seconds: float = 300.0,
) -> Optional[WorkerHealth]:
    """Serve /metrics, /healthz and /readyz in a daemon thread. Idempotent.

    Returns the :class:`WorkerHealth` the caller should ``beat()``, or None when
    no port is configured — so a worker running outside Kubernetes (tests, local
    runs) needs no special casing.
    """
    global _started
    if port is None:
        return None
    health = WorkerHealth(worker, stale_after_seconds)
    if _started:
        return health
    try:
        server = create_server(port, health)
    except OSError as exc:
        # Never let an unavailable port stop the worker from doing its job.
        logger.error("worker_health_server_failed", worker=worker, port=port, error=str(exc))
        return health
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _started = True
    logger.info("worker_health_server_started", worker=worker, port=port)
    return health
