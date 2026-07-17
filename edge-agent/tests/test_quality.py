"""Tests for the edge data-quality layer (tasks 6-10)."""

from datetime import datetime, timedelta, timezone

import pytest

from opsgrid_agent.quality import QualityPipeline
from opsgrid_agent.quality.config import MetricQualityRule, QualityConfig
from opsgrid_agent.quality.deadband import DeadbandFilter
from opsgrid_agent.quality.flags import QualityAction, QualityFlag
from opsgrid_agent.quality.transforms import apply_linear
from opsgrid_agent.quality.units import to_canonical
from opsgrid_agent.quality.validation import (
    check_numeric,
    parse_edge_timestamp,
    validate_envelope,
)

NOW = datetime(2026, 7, 8, 12, 0, 0, tzinfo=timezone.utc)


def reading(payload, asset_id="asset-1", ts=None):
    return {
        "asset_id": asset_id,
        "timestamp_edge": (ts or NOW).isoformat(),
        "topic": "telemetry",
        "payload": dict(payload),
        "sequence_num": 1,
    }


# --- task 7: scaling ---------------------------------------------------------

def test_linear_transform_scales_and_offsets():
    assert apply_linear(100, gain=0.01, offset=0.0) == pytest.approx(1.0)
    assert apply_linear(10, gain=2.0, offset=5.0) == pytest.approx(25.0)


def test_linear_transform_clamps():
    assert apply_linear(10_000, gain=1.0, clamp_max=100) == 100
    assert apply_linear(-5, gain=1.0, clamp_min=0) == 0


# --- task 9: unit normalization ----------------------------------------------

def test_fahrenheit_to_celsius():
    val, unit = to_canonical(32.0, "degF")
    assert unit == "degC"
    assert val == pytest.approx(0.0)
    assert to_canonical(212.0, "F")[0] == pytest.approx(100.0)


def test_psi_to_kpa_and_fraction_to_percent():
    assert to_canonical(1.0, "psi")[0] == pytest.approx(6.894757)
    assert to_canonical(0.5, "fraction") == (pytest.approx(50.0), "percent")


def test_unknown_unit_returns_none():
    assert to_canonical(1.0, "furlongs") is None


# --- task 6: validation ------------------------------------------------------

def test_parse_timestamp_accepts_z_suffix():
    assert parse_edge_timestamp("2026-07-08T12:00:00Z") is not None
    assert parse_edge_timestamp("not-a-time") is None


def test_missing_field_flagged():
    r = reading({"t": 1})
    r["asset_id"] = ""
    assert QualityFlag.MISSING_FIELD in validate_envelope(r, NOW, None)


def test_stale_reading_flagged():
    old = NOW - timedelta(seconds=600)
    flags = validate_envelope(reading({"t": 1}, ts=old), NOW, staleness_seconds=300)
    assert QualityFlag.STALE in flags


def test_future_timestamp_flagged_bad():
    future = NOW + timedelta(seconds=3600)
    flags = validate_envelope(reading({"t": 1}, ts=future), NOW, None)
    assert QualityFlag.BAD_TIMESTAMP in flags


def test_check_numeric_range_and_nonfinite():
    assert check_numeric(5.0, 0, 10) == (5.0, [])
    _, flags = check_numeric(50.0, 0, 10)
    assert QualityFlag.OUT_OF_RANGE in flags
    _, flags = check_numeric(float("nan"), None, None)
    assert QualityFlag.NON_FINITE in flags
    # strings/bools are passed through, not range-checked
    assert check_numeric("running", 0, 10) == (None, [])
    assert check_numeric(True, 0, 10) == (None, [])


# --- task 8: deadband --------------------------------------------------------

def test_deadband_suppresses_small_changes():
    f = DeadbandFilter()
    assert f.should_forward("a", "m", 10.0, now=0.0, deadband=1.0) is True   # first
    assert f.should_forward("a", "m", 10.5, now=1.0, deadband=1.0) is False  # < 1.0
    assert f.should_forward("a", "m", 11.5, now=2.0, deadband=1.0) is True   # >= 1.0


def test_deadband_heartbeat_forces_forward():
    f = DeadbandFilter()
    f.should_forward("a", "m", 10.0, now=0.0, deadband=1.0, max_interval_seconds=60)
    # flat value, but heartbeat window elapsed
    assert f.should_forward("a", "m", 10.0, now=61.0, deadband=1.0, max_interval_seconds=60)


def test_min_interval_blocks_rapid_forwards():
    f = DeadbandFilter()
    f.should_forward("a", "m", 10.0, now=0.0, deadband=0.1, min_interval_seconds=5)
    assert f.should_forward("a", "m", 99.0, now=1.0, deadband=0.1, min_interval_seconds=5) is False


# --- task 10: full pipeline --------------------------------------------------

def test_pipeline_scales_normalizes_and_forwards():
    cfg = QualityConfig(
        metrics={
            "temp_raw": MetricQualityRule(
                gain=0.1, rename_to="temperature", unit="degF", min=-50, max=150
            )
        }
    )
    pipe = QualityPipeline(cfg)
    # raw 320 * 0.1 = 32 degF -> 0 degC
    res = pipe.process(reading({"temp_raw": 320}), now=NOW)
    assert res.action == QualityAction.FORWARD
    assert res.reading["payload"]["temperature"] == pytest.approx(0.0)
    assert "temp_raw" not in res.reading["payload"]


def test_pipeline_quarantines_out_of_range():
    cfg = QualityConfig(metrics={"t": MetricQualityRule(min=0, max=100)})
    res = QualityPipeline(cfg).process(reading({"t": 999}), now=NOW)
    assert res.action == QualityAction.QUARANTINE
    assert QualityFlag.OUT_OF_RANGE.value in res.reading["quality"]["flags"]


def test_pipeline_drops_when_deadband_suppresses_all():
    cfg = QualityConfig(metrics={"t": MetricQualityRule(deadband=1.0)})
    pipe = QualityPipeline(cfg)
    assert pipe.process(reading({"t": 10.0}), now=NOW).action == QualityAction.FORWARD
    second = pipe.process(reading({"t": 10.1}), now=NOW).action
    assert second == QualityAction.DROP


def test_pipeline_disabled_is_passthrough():
    cfg = QualityConfig(enabled=False, metrics={"t": MetricQualityRule(min=0, max=1)})
    res = QualityPipeline(cfg).process(reading({"t": 999}), now=NOW)
    assert res.action == QualityAction.FORWARD


def test_unknown_unit_flagged_but_forwarded():
    cfg = QualityConfig(
        quarantine_on_invalid=True,
        metrics={"t": MetricQualityRule(unit="furlongs")},
    )
    res = QualityPipeline(cfg).process(reading({"t": 5}), now=NOW)
    assert res.action == QualityAction.FORWARD  # unknown unit is not "invalid"
    assert QualityFlag.UNKNOWN_UNIT.value in res.reading["quality"]["flags"]
