"""Tests for telemetry history aggregation (task B9).

The Postgres path uses TimescaleDB time_bucket (validated via make up); the pure
bucket_records fallback shares the response shape and is unit-tested here.
"""

from datetime import datetime, timezone

from app.api.telemetry import AGGREGATION_SECONDS, bucket_records


def rec(minute: int, second: int, value: float, metric="temp"):
    return {
        "time": datetime(2026, 7, 9, 12, minute, second, tzinfo=timezone.utc),
        "metric_name": metric,
        "value": value,
        "unit": "C",
    }


def test_aggregation_windows():
    assert AGGREGATION_SECONDS == {"1min": 60, "5min": 300, "1hour": 3600}


def test_bucket_rolls_up_avg_min_max_count():
    records = [rec(0, 10, 10.0), rec(0, 40, 20.0), rec(1, 5, 30.0)]
    out = bucket_records(records, 60, "1min")
    assert len(out) == 2  # two 1-minute buckets
    newest = out[0]  # newest first
    assert newest["value"] == 30.0 and newest["count"] == 1
    older = out[1]
    assert older["value"] == 15.0
    assert older["min"] == 10.0 and older["max"] == 20.0 and older["count"] == 2
    assert older["aggregation"] == "1min"


def test_buckets_are_per_metric():
    records = [rec(0, 10, 10.0, "temp"), rec(0, 20, 100.0, "rpm")]
    out = bucket_records(records, 60, "1min")
    metrics = {o["metric_name"] for o in out}
    assert metrics == {"temp", "rpm"}
    assert all(o["count"] == 1 for o in out)


def test_five_minute_alignment():
    # 12:03 and 12:04 share the 12:00 5-minute bucket; 12:06 starts a new one.
    records = [rec(3, 0, 1.0), rec(4, 0, 3.0), rec(6, 0, 5.0)]
    out = bucket_records(records, 300, "5min")
    assert len(out) == 2
    assert out[1]["value"] == 2.0  # avg of the 12:00 bucket
