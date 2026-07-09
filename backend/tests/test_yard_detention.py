"""Tests for the yard detention-alert builder (Phase C, task 17)."""

from datetime import datetime, timedelta

from app.api.yard import build_detention_alert

NOW = datetime(2026, 7, 9, 12, 0, 0)


def checked_in(minutes_ago: float) -> datetime:
    return NOW - timedelta(minutes=minutes_ago)


def test_no_alert_inside_free_time():
    # 60 min elapsed, 120 free, warn window 30 -> 60 remaining, no alert.
    assert build_detention_alert("T1", "id1", checked_in(60), NOW) is None


def test_at_risk_within_warning_window():
    alert = build_detention_alert("T1", "id1", checked_in(100), NOW)  # 20 min free left
    assert alert is not None
    assert alert["status"] == "at_risk"
    assert alert["current_charge"] == 0.0


def test_detention_accrues_charges():
    # 4h elapsed = 120 over free -> 2h * $50 = $100.
    alert = build_detention_alert("T4", "id4", checked_in(240), NOW)
    assert alert["status"] == "detention"
    assert alert["detention_minutes"] == 120.0
    assert alert["current_charge"] == 100.0


def test_custom_rate_and_free_time():
    alert = build_detention_alert(
        "T9", "id9", checked_in(90), NOW, hourly_rate=80.0, free_minutes=30
    )
    # 60 min over a 30-min free window -> 1h * $80.
    assert alert["current_charge"] == 80.0
    assert alert["hourly_rate"] == 80.0
