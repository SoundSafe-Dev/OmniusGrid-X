"""Tests for the edge metrics/health HTTP server (metrics_server.py)."""

import json
import os
import sys
import threading
import unittest
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opsgrid_agent.metrics_server import create_server
from opsgrid_agent import metrics as _metrics  # noqa: F401  (registers edge_* metrics)


class _RunningServer:
    """Context manager: serve on an ephemeral port in a daemon thread."""

    def __init__(self, health_provider=None):
        self.server = create_server(0, health_provider=health_provider)
        self.port = self.server.server_address[1]

    def __enter__(self):
        self._thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self._thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()

    def get(self, path):
        return urllib.request.urlopen(f"http://127.0.0.1:{self.port}{path}", timeout=5)


class MetricsServerTest(unittest.TestCase):
    def test_metrics_endpoint(self):
        with _RunningServer() as srv:
            resp = srv.get("/metrics")
            self.assertEqual(resp.status, 200)
            body = resp.read().decode()
            # A known edge metric's HELP/TYPE line is always present.
            self.assertIn("edge_collector_messages_total", body)

    def test_healthz_ok(self):
        with _RunningServer(health_provider=lambda: {"status": "ok", "running": True,
                                                     "collectors_active": 2}) as srv:
            resp = srv.get("/healthz")
            self.assertEqual(resp.status, 200)
            body = json.loads(resp.read())
            self.assertEqual(body["status"], "ok")
            self.assertEqual(body["collectors_active"], 2)

    def test_healthz_error_returns_503(self):
        with _RunningServer(health_provider=lambda: {"status": "error"}) as srv:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                srv.get("/healthz")
            self.assertEqual(ctx.exception.code, 503)

    def test_unknown_path_404(self):
        with _RunningServer() as srv:
            with self.assertRaises(urllib.error.HTTPError) as ctx:
                srv.get("/nope")
            self.assertEqual(ctx.exception.code, 404)


if __name__ == "__main__":
    unittest.main(verbosity=2)
