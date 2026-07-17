"""Edge-side trace-context propagation (task 15).

The edge agent isn't a full OpenTelemetry app, but it can still originate W3C
trace context so an uplink request (heartbeat, telemetry ingest) shows up as the
root of a distributed trace once it reaches the backend. The backend's FastAPI
instrumentation (task 13) extracts the ``traceparent`` header and continues the
trace; the request-context middleware (task 9) also reuses the trace-id as its
correlation id — so one id ties the edge log line, the HTTP request, and the
backend spans together.

Format: W3C ``traceparent`` = ``00-<32hex trace>-<16hex span>-01``.
"""

import os


def _hex(n_bytes: int) -> str:
    return os.urandom(n_bytes).hex()


def new_trace_id() -> str:
    """A random 16-byte (32 hex) trace id."""
    return _hex(16)


def new_span_id() -> str:
    """A random 8-byte (16 hex) span id."""
    return _hex(8)


def new_traceparent(trace_id: str = None) -> str:
    """Build a sampled W3C traceparent, optionally continuing an existing trace."""
    tid = trace_id or new_trace_id()
    return f"00-{tid}-{new_span_id()}-01"


def trace_id_of(traceparent: str) -> str:
    """Extract the 32-hex trace id from a traceparent, or '' if malformed."""
    parts = traceparent.split("-")
    return parts[1] if len(parts) >= 2 and len(parts[1]) == 32 else ""
