"""Tests for the cloud ingest-gateway guards (tasks 11-15)."""

from datetime import datetime, timedelta, timezone

import pytest

from app.services.edge_ingest import (
    DedupCache,
    EdgeIngestGateway,
    RateLimited,
    SequenceTracker,
    TokenBucket,
    idempotency_key,
    validate_reading,
)

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def reading(asset="a1", seq=1, ts=None, payload=None):
    return {
        "asset_id": asset,
        "timestamp_edge": (ts or NOW).isoformat(),
        "topic": "telemetry",
        "payload": payload if payload is not None else {"v": 1},
        "sequence_num": seq,
    }


# --- task 11: validation ------------------------------------------------------

def test_validation_accepts_good_reading():
    assert validate_reading(reading()) is None


@pytest.mark.parametrize("bad", [
    {"timestamp_edge": NOW.isoformat(), "payload": {}},          # no asset
    {"asset_id": "a", "payload": {}},                            # no ts
    {"asset_id": "a", "timestamp_edge": "nope", "payload": {}},  # bad ts
    {"asset_id": "a", "timestamp_edge": NOW.isoformat(), "payload": []},  # payload not obj
    "not-a-dict",
])
def test_validation_rejects_malformed(bad):
    assert validate_reading(bad) is not None


# --- task 12: dedup -----------------------------------------------------------

def test_idempotency_key_uses_sequence():
    k = idempotency_key("agent1", reading(asset="m", seq=5))
    assert k == "agent1:m:5"


def test_dedup_cache_detects_repeat():
    c = DedupCache(ttl_seconds=100)
    assert c.seen("k1", now=0.0) is False
    assert c.seen("k1", now=1.0) is True


# --- task 13: sequence --------------------------------------------------------

def test_sequence_ok_gap_reorder():
    s = SequenceTracker()
    assert s.observe("a", "m", 1) == "ok"
    assert s.observe("a", "m", 2) == "ok"
    assert s.observe("a", "m", 5) == "gap"      # skipped 3,4
    assert s.observe("a", "m", 4) == "reorder"  # arrives late


# --- task 14: backpressure ----------------------------------------------------

def test_token_bucket_limits_then_refills():
    b = TokenBucket(rate_per_sec=10, burst=10)
    assert b.allow("a", cost=10, now=0.0) is True   # drains bucket
    assert b.allow("a", cost=1, now=0.0) is False    # empty
    assert b.allow("a", cost=5, now=1.0) is True     # +10 refilled, take 5


def test_gateway_rate_limits_oversized_burst():
    gw = EdgeIngestGateway(rate_per_sec=1, burst=3)
    with pytest.raises(RateLimited):
        gw.ingest("agent1", [reading(seq=i) for i in range(1, 11)], now=NOW)


# --- task 15 + orchestration --------------------------------------------------

def test_ingest_end_to_end_counts():
    quarantined = []
    gw = EdgeIngestGateway(
        rate_per_sec=1000, burst=1000,
        quarantine_sink=lambda aid, r, reason: quarantined.append((r, reason)),
    )
    batch = [
        reading(asset="m", seq=1),
        reading(asset="m", seq=1),          # duplicate -> deduped
        reading(asset="m", seq=2),
        {"asset_id": "m", "payload": {}},   # malformed (no ts) -> quarantined
    ]
    res = gw.ingest("agent1", batch, now=NOW)
    assert res.summary["accepted"] == 2
    assert res.summary["deduped"] == 1
    assert res.summary["quarantined"] == 1
    assert len(quarantined) == 1
