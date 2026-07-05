"""HTTP server for the edge agent: Prometheus /metrics + /healthz.

prometheus_client.start_http_server only serves /metrics, so we run a small
threaded stdlib HTTP server that also exposes /healthz (collector/agent health)
for Kubernetes probes. Started from EdgeAgent.start() when METRICS_PORT is set.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Optional

import structlog
from prometheus_client import CONTENT_TYPE_LATEST, generate_latest

logger = structlog.get_logger()

_started = False


def _make_handler(health_provider: Optional[Callable[[], dict]]):
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
                try:
                    health = health_provider() if health_provider else {"status": "ok"}
                except Exception as e:  # pragma: no cover - defensive
                    health = {"status": "error", "error": str(e)}
                code = 200 if health.get("status") != "error" else 503
                self._write(code, "application/json", json.dumps(health).encode())
            else:
                self._write(404, "text/plain", b"not found")

        def log_message(self, *args):  # silence default stderr access logging
            return

    return Handler


def create_server(port: int, health_provider: Optional[Callable[[], dict]] = None) -> ThreadingHTTPServer:
    """Build (but do not start) the metrics/health HTTP server."""
    return ThreadingHTTPServer(("0.0.0.0", port), _make_handler(health_provider))


def start_metrics_server(port: int, health_provider: Optional[Callable[[], dict]] = None) -> bool:
    """Serve /metrics and /healthz on ``0.0.0.0:<port>`` in a daemon thread. Idempotent."""
    global _started
    if _started:
        return True
    try:
        server = create_server(port, health_provider)
    except OSError as e:
        logger.error("metrics_server_failed", port=port, error=str(e))
        return False
    threading.Thread(target=server.serve_forever, daemon=True).start()
    _started = True
    logger.info("metrics_server_started", port=port)
    return True
