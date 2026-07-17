"""Unit tests for the Asset Health Index pure computation.

compute() is pure (no DB/IO), so these run without a database. The DB-backed
gatherers run in CI's backend job.
"""

from app.services.health_index import HealthIndexCalculator, HealthResult


def calc():
    return HealthIndexCalculator()


def test_healthy_asset_scores_high():
    r = calc().compute("a1", recent_oee=[85, 86, 84, 85, 87, 86], alarm_rate_per_hour=0.0)
    assert isinstance(r, HealthResult)
    assert r.health_score >= 80
    assert r.drivers == []                 # nothing hurting -> no drivers
    assert r.confidence == 1.0             # 6 samples


def test_declining_oee_penalized():
    r = calc().compute("a1", recent_oee=[90, 80, 70, 60], alarm_rate_per_hour=0.0)
    # base mean 75, minus decline penalty (trend -30 -> capped at 20)
    assert r.health_score < 75
    assert any(d["factor"] == "declining_oee" for d in r.drivers)


def test_alarms_and_low_availability_penalized():
    r = calc().compute("a1", recent_oee=[80, 80], alarm_rate_per_hour=4.0, availability=50.0)
    factors = {d["factor"] for d in r.drivers}
    assert "alarm_rate" in factors
    assert "low_availability" in factors
    assert 0.0 <= r.health_score <= 100.0
    assert r.health_score < 80


def test_no_data_is_neutral_low_confidence():
    r = calc().compute("a1", recent_oee=[])
    assert r.health_score == 50.0
    assert r.confidence < 0.5


def test_score_is_bounded():
    r = calc().compute("a1", recent_oee=[10, 5, 2], alarm_rate_per_hour=100.0, availability=0.0)
    assert r.health_score == 0.0           # clamped, never negative
