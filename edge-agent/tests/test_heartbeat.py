"""Tests for the agent heartbeat protocol (task 16, edge side)."""

from datetime import datetime, timezone

from opsgrid_agent.heartbeat import HeartbeatReporter
from opsgrid_agent.timesync import ClockSkewEstimator


def health():
    return {
        "buffer_pending": 12,
        "dead_lettered": 1,
        "active_collectors": 3,
        "total_collectors": 4,
        "cert_expires_in_seconds": 100000,
    }


def test_build_payload_snapshots_health():
    r = HeartbeatReporter("https://cloud", "1.2.3", health, post_fn=lambda *a: (200, {}))
    p = r.build_payload()
    assert p["agent_version"] == "1.2.3"
    assert p["buffer_pending"] == 12
    assert p["active_collectors"] == 3


def test_send_once_success_and_clock_sample():
    server_time = datetime(2026, 7, 8, 12, 0, 30, tzinfo=timezone.utc)
    captured = {}

    def post(url, body, headers):
        captured["url"] = url
        captured["body"] = body
        return 200, {"ok": True, "server_time": server_time.isoformat()}

    skew = ClockSkewEstimator(alpha=1.0)
    r = HeartbeatReporter("https://cloud/", "1.0", health, post_fn=post, skew_estimator=skew)
    assert r.send_once() is True
    assert captured["url"] == "https://cloud/api/v1/edge/heartbeat"
    assert captured["body"]["dead_lettered"] == 1
    assert skew.calibrated  # server clock was sampled from the ack


def test_send_once_handles_rejection_and_transport_error():
    r_reject = HeartbeatReporter("https://c", "1", health, post_fn=lambda *a: (503, {}))
    assert r_reject.send_once() is False

    def boom(*a):
        raise ConnectionError("down")

    r_err = HeartbeatReporter("https://c", "1", health, post_fn=boom)
    assert r_err.send_once() is False
