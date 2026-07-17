"""Unit tests for the error-tracker core (no Docker/DB).

Covers the pure logic: fingerprinting, app-frame selection, PII scrubbing,
traceback truncation, and the bounded in-memory aggregator (concurrency +
overflow). These are the GDPR-facing and correctness-critical surfaces.
"""

import asyncio

import pytest

from app.services import error_tracker as et
from app.services.error_tracker import (
    ErrorTracker,
    compute_fingerprint,
    scrub,
    _app_frame,
    _format_traceback,
)


def _caught(exc: Exception) -> Exception:
    try:
        raise exc
    except Exception as e:  # noqa: BLE001
        return e


def _caught_via_alpha() -> Exception:
    def alpha():
        raise ValueError("boom")
    try:
        alpha()
    except Exception as e:  # noqa: BLE001
        return e


def _caught_via_beta() -> Exception:
    def beta():
        raise ValueError("boom")
    try:
        beta()
    except Exception as e:  # noqa: BLE001
        return e


# --- fingerprinting ----------------------------------------------------------

def test_fingerprint_is_deterministic_and_16_chars():
    exc = _caught(ValueError("x"))
    fp1 = compute_fingerprint("ValueError", "GET", "/api/v1/x", exc)
    fp2 = compute_fingerprint("ValueError", "GET", "/api/v1/x", exc)
    assert fp1 == fp2
    assert len(fp1) == 16


def test_fingerprint_differs_by_route():
    exc = _caught(ValueError("x"))
    a = compute_fingerprint("ValueError", "GET", "/api/v1/a", exc)
    b = compute_fingerprint("ValueError", "GET", "/api/v1/b", exc)
    assert a != b


def test_fingerprint_differs_by_exception_type():
    exc = _caught(ValueError("x"))
    a = compute_fingerprint("ValueError", "GET", "/api/v1/x", exc)
    b = compute_fingerprint("KeyError", "GET", "/api/v1/x", exc)
    assert a != b


def test_fingerprint_differs_by_crash_site():
    a = compute_fingerprint("ValueError", "GET", "/x", _caught_via_alpha())
    b = compute_fingerprint("ValueError", "GET", "/x", _caught_via_beta())
    assert a != b


def test_same_route_template_same_fingerprint():
    # The middleware passes the route TEMPLATE, so two concrete ids collapse.
    exc = _caught_via_alpha()
    a = compute_fingerprint("ValueError", "GET", "/api/v1/assets/{id}", exc)
    b = compute_fingerprint("ValueError", "GET", "/api/v1/assets/{id}", exc)
    assert a == b


# --- app-frame selection -----------------------------------------------------

def test_app_frame_falls_back_to_deepest_when_no_app_frame():
    exc = _caught_via_alpha()
    frame = _app_frame(exc)
    assert frame is not None
    # Deepest frame is the inner alpha() that raised.
    assert frame.name == "alpha"


# --- scrubbing ---------------------------------------------------------------

def test_scrub_email():
    assert scrub("contact jane.doe@example.com now") == "contact <email> now"


def test_scrub_bearer_token():
    out = scrub("Authorization: Bearer abc123.DEF456.ghi789")
    assert "abc123" not in out
    assert "<token>" in out


def test_scrub_long_hex_run():
    secret = "a" * 40
    assert scrub(f"key={secret}") == "key=<token>"


def test_scrub_none_and_empty():
    assert scrub(None) is None
    assert scrub("") == ""


def test_scrub_unicode_safe():
    assert scrub("café déjà 🚀 ok") == "café déjà 🚀 ok"


def test_format_traceback_truncates(monkeypatch):
    monkeypatch.setattr(et, "TRACEBACK_MAX_BYTES", 64)
    exc = _caught_via_alpha()
    out = _format_traceback(exc)
    assert len(out.encode("utf-8")) <= 64


def test_format_traceback_scrubs(monkeypatch):
    monkeypatch.setattr(et, "TRACEBACK_MAX_BYTES", 8192)
    exc = _caught(ValueError("user bob@corp.com failed"))
    out = _format_traceback(exc)
    assert "bob@corp.com" not in out
    assert "<email>" in out


# --- aggregator --------------------------------------------------------------

@pytest.mark.asyncio
async def test_concurrent_records_sum_correctly():
    tracker = ErrorTracker()
    exc = _caught(ValueError("x"))
    await asyncio.gather(*[
        tracker.record(exc, method="GET", route="/api/v1/x") for _ in range(50)
    ])
    assert len(tracker._pending) == 1
    pending = next(iter(tracker._pending.values()))
    assert pending.count == 50
    # All in one hourly bucket.
    assert sum(pending.bucket_counts.values()) == 50


@pytest.mark.asyncio
async def test_overflow_drops_new_fingerprints_but_counts_known(monkeypatch):
    monkeypatch.setattr(et, "MAX_PENDING_FINGERPRINTS", 2)
    tracker = ErrorTracker()

    # Two distinct routes fill capacity.
    await tracker.record(_caught(ValueError("a")), method="GET", route="/a")
    await tracker.record(_caught(ValueError("b")), method="GET", route="/b")
    assert len(tracker._pending) == 2

    before = et.ERROR_TRACKER_DROPPED_TOTAL._value.get()

    # A third NEW fingerprint is dropped...
    await tracker.record(_caught(ValueError("c")), method="GET", route="/c")
    assert len(tracker._pending) == 2
    assert et.ERROR_TRACKER_DROPPED_TOTAL._value.get() == before + 1

    # ...but a KNOWN fingerprint still increments.
    await tracker.record(_caught(ValueError("a")), method="GET", route="/a")
    counts = {p.route: p.count for p in tracker._pending.values()}
    assert counts["/a"] == 2
