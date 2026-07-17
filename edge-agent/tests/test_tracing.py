"""Tests for edge trace-context propagation (task 15)."""

import re

from opsgrid_agent.heartbeat import HeartbeatReporter
from opsgrid_agent.tracing import new_traceparent, trace_id_of

_TRACEPARENT = re.compile(r"^00-[0-9a-f]{32}-[0-9a-f]{16}-01$")


def test_traceparent_format():
    tp = new_traceparent()
    assert _TRACEPARENT.match(tp)


def test_traceparent_continues_existing_trace():
    tid = "a" * 32
    tp = new_traceparent(tid)
    assert trace_id_of(tp) == tid


def test_trace_id_of_rejects_malformed():
    assert trace_id_of("garbage") == ""


def test_heartbeat_sends_traceparent_header():
    captured = {}

    def post(url, body, headers):
        captured["headers"] = headers
        return 200, {"ok": True}

    r = HeartbeatReporter("https://cloud", "1.0", lambda: {}, post_fn=post)
    assert r.send_once() is True
    assert _TRACEPARENT.match(captured["headers"]["traceparent"])
