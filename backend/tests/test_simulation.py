"""Unit tests for the digital-twin / simulation engine (pure, seeded)."""

from app.services.simulation import SimulationEngine


def eng():
    return SimulationEngine()


def test_monte_carlo_is_deterministic_with_seed():
    a = eng().monte_carlo_throughput(runs=500, seed=42)
    b = eng().monte_carlo_throughput(runs=500, seed=42)
    assert a["throughput"] == b["throughput"]      # same seed -> identical
    assert a["downtime_hours"] == b["downtime_hours"]


def test_monte_carlo_stats_are_sane():
    r = eng().monte_carlo_throughput(
        horizon_hours=168, cycle_time_seconds=60, mtbf_hours=50, mttr_hours=2,
        performance=0.9, quality=0.98, runs=1000, seed=7,
    )
    t = r["throughput"]
    assert t["p10"] <= t["p50"] <= t["p90"]        # ordered percentiles
    assert t["mean"] > 0
    assert 0 <= r["availability_mean"] <= 100
    assert r["downtime_hours"]["mean"] >= 0


def test_more_downtime_lowers_throughput():
    reliable = eng().monte_carlo_throughput(mtbf_hours=200, mttr_hours=1, runs=800, seed=1)
    faulty = eng().monte_carlo_throughput(mtbf_hours=10, mttr_hours=8, runs=800, seed=1)
    assert faulty["throughput"]["mean"] < reliable["throughput"]["mean"]
    assert faulty["availability_mean"] < reliable["availability_mean"]


def test_invalid_inputs_raise():
    try:
        eng().monte_carlo_throughput(cycle_time_seconds=0)
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_fleet_rollup_identifies_bottleneck():
    rollup = eng().fleet_oee_rollup([
        {"asset_id": "a1", "oee": 88.0},
        {"asset_id": "a2", "oee": 45.0},
        {"asset_id": "a3", "oee": 72.0},
    ])
    assert rollup["asset_count"] == 3
    assert rollup["bottleneck_asset_id"] == "a2"
    assert rollup["bottleneck_oee"] == 45.0
    assert rollup["distribution"] == {"world_class": 1, "acceptable": 1, "low": 1}


def test_fleet_rollup_empty():
    assert eng().fleet_oee_rollup([])["asset_count"] == 0
