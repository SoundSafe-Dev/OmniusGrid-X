"""Tests for edge data-plane robustness utilities (tasks 21-23)."""

import gzip
import json
from datetime import datetime, timedelta, timezone

from opsgrid_agent.aggregation import WindowAggregator
from opsgrid_agent.compression import compress, decompress
from opsgrid_agent.timesync import ClockSkewEstimator, parse_http_date

UTC = timezone.utc


# --- task 21: clock skew ------------------------------------------------------

def test_offset_zero_until_calibrated():
    est = ClockSkewEstimator()
    assert est.calibrated is False
    dt = datetime(2026, 7, 8, tzinfo=UTC)
    assert est.correct(dt) == dt  # no correction before any sample


def test_offset_tracks_server_ahead():
    est = ClockSkewEstimator(alpha=1.0)  # take newest sample fully
    edge = datetime(2026, 7, 8, 12, 0, 0, tzinfo=UTC)
    server = edge + timedelta(seconds=30)  # edge is 30s behind
    est.observe(edge, server)
    assert est.offset_seconds == 30.0
    assert est.correct(edge) == server


def test_ewma_smooths_samples():
    est = ClockSkewEstimator(alpha=0.5)
    base = datetime(2026, 7, 8, tzinfo=UTC)
    est.observe(base, base + timedelta(seconds=10))  # -> 10
    est.observe(base, base + timedelta(seconds=20))  # -> 0.5*20 + 0.5*10 = 15
    assert est.offset_seconds == 15.0


def test_parse_http_date():
    dt = parse_http_date("Wed, 08 Jul 2026 12:00:00 GMT")
    assert dt is not None and dt.year == 2026
    assert parse_http_date("garbage") is None


# --- task 22: compression -----------------------------------------------------

def test_small_payload_left_raw():
    data = b"tiny"
    framed, compressed = compress(data, min_size=512)
    assert compressed is False
    assert decompress(framed) == data


def test_large_repetitive_payload_compresses_and_roundtrips():
    # `allowed` is what the BACKEND advertised it can decode (FS-759). Omitting it now means
    # raw only, deliberately: an agent must not compress toward a backend that never said it
    # could decompress, because the buffer marks a row sent the moment the broker accepts it
    # and the loss would be silent and permanent rather than retried.
    data = json.dumps([{"asset_id": "a", "v": 1} for _ in range(500)]).encode()
    framed, compressed = compress(data, min_size=512, allowed=["raw", "gzip"])
    assert compressed is True
    assert len(framed) < len(data)
    assert decompress(framed) == data


def test_it_will_not_compress_until_the_backend_says_it_can_decode():
    """The fail-closed default (FS-759). This is the whole reason the negotiation exists."""
    data = json.dumps([{"asset_id": "a", "v": 1} for _ in range(500)]).encode()
    framed, compressed = compress(data, min_size=512)
    assert compressed is False
    assert decompress(framed) == data
    framed_explicit, compressed_explicit = compress(data, min_size=512, allowed=["raw"])
    assert compressed_explicit is False
    assert decompress(framed_explicit) == data


def test_decompress_rejects_unknown_codec():
    try:
        decompress(b"\x09garbage")
        assert False, "expected ValueError"
    except ValueError:
        pass


# --- task 23: aggregation -----------------------------------------------------

def test_window_aggregates_min_max_mean():
    agg = WindowAggregator(window_seconds=10)
    agg.add("m1", {"temp": 10.0}, now=0.0)
    agg.add("m1", {"temp": 20.0}, now=1.0)
    agg.add("m1", {"temp": 30.0}, now=2.0)
    assert agg.collect_due(now=5.0) == []          # window not elapsed yet
    due = agg.collect_due(now=11.0)
    assert len(due) == 1
    asset, payload = due[0]
    assert asset == "m1"
    s = payload["temp"]
    assert (s["min"], s["max"], s["mean"], s["count"], s["last"]) == (10.0, 30.0, 20.0, 3, 30.0)


def test_non_numeric_fields_ignored():
    agg = WindowAggregator(window_seconds=1)
    agg.add("m1", {"state": "running", "rpm": 100}, now=0.0)
    due = agg.collect_due(now=2.0)
    _, payload = due[0]
    assert "state" not in payload and "rpm" in payload
