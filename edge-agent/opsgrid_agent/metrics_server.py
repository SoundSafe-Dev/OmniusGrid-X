"""Prometheus /metrics HTTP endpoint for the edge agent.

Started from EdgeAgent.start() when the METRICS_PORT env var is set. Uses
prometheus_client's built-in WSGI server (no extra dependency).
"""

import structlog
from prometheus_client import start_http_server

logger = structlog.get_logger()

_started = False


def start_metrics_server(port: int) -> bool:
    """Expose Prometheus metrics on ``0.0.0.0:<port>/metrics``. Idempotent."""
    global _started
    if _started:
        return True
    try:
        start_http_server(port)
        _started = True
        logger.info("metrics_server_started", port=port)
        return True
    except OSError as e:
        logger.error("metrics_server_failed", port=port, error=str(e))
        return False
