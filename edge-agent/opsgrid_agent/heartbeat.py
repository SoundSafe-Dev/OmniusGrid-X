"""Agent heartbeat protocol (task 16, edge side).

Periodically reports agent health to the backend so the fleet view knows the
agent is alive and how its buffer/collectors are doing. The heartbeat response
carries the server clock, which is fed to the clock-skew estimator (task 21) —
so heartbeats double as the time-sync channel.

The HTTP call and the health snapshot are both injected, keeping this unit-
testable and decoupled from the concrete buffer/coordinator implementations.
``post_fn(url, json_body, headers) -> (status, response_dict)``.
"""

from datetime import datetime, timezone
from typing import Callable, Dict, Optional, Tuple

import structlog

logger = structlog.get_logger()

PostFn = Callable[[str, Dict, Dict], Tuple[int, Dict]]
HealthFn = Callable[[], Dict]


class HeartbeatReporter:
    """Builds and sends periodic health heartbeats to the backend."""

    def __init__(
        self,
        server_url: str,
        agent_version: str,
        health_fn: HealthFn,
        post_fn: PostFn,
        skew_estimator=None,
    ):
        self.server_url = server_url.rstrip("/")
        self.agent_version = agent_version
        self._health_fn = health_fn
        self._post = post_fn
        self._skew = skew_estimator

    def build_payload(self) -> Dict:
        """Snapshot current health into a heartbeat payload."""
        health = self._health_fn() or {}
        return {
            "agent_version": self.agent_version,
            "buffer_pending": int(health.get("buffer_pending", 0) or 0),
            "dead_lettered": int(health.get("dead_lettered", 0) or 0),
            "dropped": int(health.get("dropped", 0) or 0),
            "active_collectors": int(health.get("active_collectors", 0) or 0),
            "total_collectors": int(health.get("total_collectors", 0) or 0),
            "cert_expires_in_seconds": health.get("cert_expires_in_seconds"),
        }

    def send_once(self) -> bool:
        """Send a single heartbeat. Returns True on a 200 ack.

        On success, samples the server clock from the ack to update the
        clock-skew estimator (if one was provided).
        """
        url = f"{self.server_url}/api/v1/edge/heartbeat"
        try:
            status, resp = self._post(url, self.build_payload(), {})
        except Exception as e:
            logger.warning("heartbeat_failed", error=str(e))
            return False
        if status != 200:
            logger.warning("heartbeat_rejected", status=status)
            return False

        server_time = resp.get("server_time")
        if server_time and self._skew is not None:
            try:
                st = datetime.fromisoformat(server_time.replace("Z", "+00:00"))
                self._skew.observe(datetime.now(timezone.utc), st)
            except (ValueError, AttributeError):  # pragma: no cover - defensive
                pass
        return True
