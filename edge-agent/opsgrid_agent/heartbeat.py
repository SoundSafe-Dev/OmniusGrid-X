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

from .tracing import new_traceparent, trace_id_of

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
        #: What the BACKEND said it can decode on the uplink (FS-759). Starts at raw only
        #: and is widened by an ack — never narrowed by a failed heartbeat, because a
        #: single missed heartbeat is not evidence the backend was downgraded, and
        #: oscillating the wire format on a flaky link is its own defect.
        self.wire_codecs: Tuple[str, ...] = ("raw",)

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
        # Originate W3C trace context so the backend continues one distributed
        # trace and reuses the trace-id as the request correlation id (task 15).
        traceparent = new_traceparent()
        try:
            status, resp = self._post(url, self.build_payload(), {"traceparent": traceparent})
        except Exception as e:
            logger.warning("heartbeat_failed", error=str(e))
            return False

        # Sample the server clock from ANY response carrying it — including a
        # stale-signature 401, whose detail embeds server_time precisely so a
        # drifted clock can calibrate back inside the freshness window.
        self._observe_server_time(resp)
        self._observe_wire_codecs(resp)

        if status != 200:
            logger.warning("heartbeat_rejected", status=status)
            return False
        return True

    def _observe_wire_codecs(self, resp) -> None:
        """Record what the backend advertised it can decode (FS-759).

        Only ever widens, and only from a well-formed list of strings. An older backend
        omits the field entirely, which correctly leaves this at raw — the agent must not
        compress toward something that cannot read it, since the buffer marks a message sent
        the moment the broker accepts it and the loss would be silent and permanent.
        """
        if not isinstance(resp, dict):
            return
        advertised = resp.get("wire_codecs")
        if not isinstance(advertised, (list, tuple)):
            return
        names = tuple(sorted({c for c in advertised if isinstance(c, str)}))
        if not names or "raw" not in names:
            # A backend that cannot decode `raw` cannot decode anything this agent frames.
            # Treating that as an advertisement would be worse than ignoring it.
            return
        if names != self.wire_codecs:
            logger.info("wire_codecs_negotiated", codecs=list(names))
        self.wire_codecs = names

    def _observe_server_time(self, resp) -> None:
        if self._skew is None or not isinstance(resp, dict):
            return
        server_time = resp.get("server_time")
        if not server_time:
            detail = resp.get("detail")
            if isinstance(detail, dict):
                server_time = detail.get("server_time")
        if not server_time:
            return
        try:
            st = datetime.fromisoformat(str(server_time).replace("Z", "+00:00"))
            self._skew.observe(datetime.now(timezone.utc), st)
        except (ValueError, AttributeError):  # pragma: no cover - defensive
            pass
