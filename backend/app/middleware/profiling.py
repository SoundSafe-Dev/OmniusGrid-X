"""Performance profiling middleware.

Self-contained performance instrumentation for the OpsGrid backend (Task 2):
  * Request timing with millisecond precision (X-Process-Time-Ms header + log).
  * Per-request DB query count and aggregate query time (via SQLAlchemy events).
  * Slow-endpoint and slow-query detection with configurable thresholds.
  * Per-request memory delta + process RSS gauge (best-effort, see caveat below).
  * Prometheus metrics on the default registry, surfaced by the existing
    GET /metrics endpoint (app/api/health.py).

Wiring is intentionally kept out of app/main.py and app/db/database.py so that
no existing source is modified: call ``setup_profiling(app)`` once at startup
(see the wiring note handed to Hamad).

Configuration is read from environment variables here rather than from
app/core/config.py Settings, again to avoid editing existing source. These
keys ideally belong in Settings (open question for Hamad).

Memory caveat: the backend serves requests concurrently on a single process
(async). Process RSS therefore cannot be cleanly attributed to one request, so
the per-request RSS delta is reported as APPROXIMATE; the process-level gauge is
accurate.
"""

import os
import time
import contextvars
from typing import Optional

import structlog
from prometheus_client import Counter, Gauge, Histogram
from sqlalchemy import event
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response

logger = structlog.get_logger()


def _env_bool(name: str, default: bool) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


# --- Configuration (env-driven; see module docstring) -----------------------
# Disabled by default to match the other custom middlewares, which are gated
# off in app/main.py (SecurityHeaders/Audit are added-but-commented).
PROFILING_ENABLED: bool = _env_bool("PROFILING_ENABLED", False)

# Slow-query threshold grounded in app/api/query_performance.py:25, which
# defines slow queries as ">1 second execution time".
SLOW_QUERY_MS: float = _env_float("PROFILING_SLOW_QUERY_MS", 1000.0)

# Slow-request threshold is NOT grounded anywhere in the codebase (no HTTP
# latency SLA / metric exists). This 1000ms default is an UNCONFIRMED
# placeholder pending confirmation from Hamad.
SLOW_REQUEST_MS: float = _env_float("PROFILING_SLOW_REQUEST_MS", 1000.0)


# --- Memory backend (psutil preferred, graceful fallback) --------------------
try:
    import psutil

    _PROCESS = psutil.Process()
    _MEMORY_BACKEND = "psutil"

    def _rss_bytes() -> Optional[int]:
        try:
            return _PROCESS.memory_info().rss
        except Exception:
            return None

except Exception:  # psutil not installed
    _MEMORY_BACKEND = "unavailable"

    def _rss_bytes() -> Optional[int]:
        return None


# --- Prometheus metrics (default registry -> existing /metrics) --------------
HTTP_REQUEST_DURATION = Histogram(
    "opsgrid_http_request_duration_seconds",
    "HTTP request latency in seconds",
    ["method", "endpoint", "status"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0],
)

HTTP_REQUESTS_TOTAL = Counter(
    "opsgrid_http_requests_total",
    "Total HTTP requests",
    ["method", "endpoint", "status"],
)

HTTP_SLOW_REQUESTS_TOTAL = Counter(
    "opsgrid_http_slow_requests_total",
    "HTTP requests exceeding the slow-request threshold",
    ["method", "endpoint"],
)

HTTP_REQUEST_DB_QUERIES = Histogram(
    "opsgrid_http_request_db_queries",
    "Number of DB queries executed per HTTP request",
    ["method", "endpoint"],
    buckets=[0, 1, 2, 5, 10, 25, 50, 100],
)

DB_QUERY_DURATION = Histogram(
    "opsgrid_db_query_duration_seconds",
    "Individual DB query execution time in seconds",
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

DB_SLOW_QUERIES_TOTAL = Counter(
    "opsgrid_db_slow_queries_total",
    "DB queries exceeding the slow-query threshold",
)

PROCESS_MEMORY_RSS = Gauge(
    "opsgrid_process_memory_rss_bytes",
    "Resident set size of the backend process in bytes",
)


# --- Per-request query aggregation -------------------------------------------
# contextvars propagate into the greenlet that runs SQLAlchemy Core events
# under async, so queries get attributed to the active request.
_query_stats: contextvars.ContextVar[Optional[dict]] = contextvars.ContextVar(
    "profiling_query_stats", default=None
)

_listeners_registered = False


def _before_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    context._profiling_start = time.perf_counter()


def _after_cursor_execute(conn, cursor, statement, parameters, context, executemany):
    start = getattr(context, "_profiling_start", None)
    if start is None:
        return
    elapsed = time.perf_counter() - start
    elapsed_ms = elapsed * 1000.0

    DB_QUERY_DURATION.observe(elapsed)

    stats = _query_stats.get()
    if stats is not None:
        stats["count"] += 1
        stats["total_ms"] += elapsed_ms

    if elapsed_ms >= SLOW_QUERY_MS:
        DB_SLOW_QUERIES_TOTAL.inc()
        logger.warning(
            "slow_query",
            duration_ms=round(elapsed_ms, 2),
            threshold_ms=SLOW_QUERY_MS,
            statement=statement[:500],
        )


def _register_query_listeners() -> None:
    """Attach DB query timing events to the existing async engine."""
    global _listeners_registered
    if _listeners_registered:
        return
    # Imported lazily so this module has no import-time dependency on the engine.
    from app.db.database import engine

    sync_engine = engine.sync_engine
    event.listen(sync_engine, "before_cursor_execute", _before_cursor_execute)
    event.listen(sync_engine, "after_cursor_execute", _after_cursor_execute)
    _listeners_registered = True


def _endpoint_label(request: Request) -> str:
    """Use the matched route template to keep label cardinality bounded."""
    route = request.scope.get("route")
    path = getattr(route, "path", None)
    return path or request.url.path


class ProfilingMiddleware(BaseHTTPMiddleware):
    """Time each request, attribute DB queries, and emit metrics/logs."""

    async def dispatch(self, request: Request, call_next):
        if not PROFILING_ENABLED:
            return await call_next(request)

        token = _query_stats.set({"count": 0, "total_ms": 0.0})
        rss_before = _rss_bytes()
        start = time.perf_counter()

        response: Optional[Response] = None
        # Default for the case where call_next raises before producing a response:
        # the exception still propagates, but the request is recorded (status 500)
        # instead of being dropped from the metrics entirely.
        status_code = 500

        try:
            response = await call_next(request)
            status_code = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000.0
            stats = _query_stats.get() or {"count": 0, "total_ms": 0.0}
            _query_stats.reset(token)

            rss_after = _rss_bytes()
            if rss_after is not None:
                PROCESS_MEMORY_RSS.set(rss_after)
            rss_delta = (
                rss_after - rss_before
                if (rss_after is not None and rss_before is not None)
                else None
            )

            method = request.method
            endpoint = _endpoint_label(request)
            status = str(status_code)

            HTTP_REQUEST_DURATION.labels(method, endpoint, status).observe(duration_ms / 1000.0)
            HTTP_REQUESTS_TOTAL.labels(method, endpoint, status).inc()
            HTTP_REQUEST_DB_QUERIES.labels(method, endpoint).observe(stats["count"])

            # Response headers can only be attached when a response was produced.
            if response is not None:
                response.headers["X-Process-Time-Ms"] = f"{duration_ms:.2f}"
                response.headers["X-DB-Query-Count"] = str(stats["count"])
                response.headers["X-DB-Query-Time-Ms"] = f"{stats['total_ms']:.2f}"

            log_fields = {
                "method": method,
                "endpoint": endpoint,
                "status": status_code,
                "duration_ms": round(duration_ms, 2),
                "db_query_count": stats["count"],
                "db_query_time_ms": round(stats["total_ms"], 2),
                "rss_delta_bytes_approx": rss_delta,
            }

            if duration_ms >= SLOW_REQUEST_MS:
                HTTP_SLOW_REQUESTS_TOTAL.labels(method, endpoint).inc()
                logger.warning("slow_request", threshold_ms=SLOW_REQUEST_MS, **log_fields)
            else:
                logger.info("request_profile", **log_fields)


def setup_profiling(app) -> None:
    """Add the profiling middleware and, when enabled, the DB query listeners.

    Call once during app setup. When PROFILING_ENABLED is False the DB query
    listeners are NOT attached, so disabled profiling adds no per-query cost; the
    middleware is still added but short-circuits on every request.
    """
    if PROFILING_ENABLED:
        _register_query_listeners()
    app.add_middleware(ProfilingMiddleware)
    logger.info(
        "profiling_setup",
        enabled=PROFILING_ENABLED,
        slow_request_ms=SLOW_REQUEST_MS,
        slow_query_ms=SLOW_QUERY_MS,
        memory_backend=_MEMORY_BACKEND,
    )
