"""Digital-twin ranking and strategic recommendation tests."""

from datetime import datetime, timezone

import pytest

from app.services.simulation import SimulationEngine
from app.services.strategic_engine import CloudStrategicEngine
from app.services.twin_optimizer import (
    CandidateAction,
    SimulationPlan,
    TwinOptimizer,
)


def _baseline() -> SimulationPlan:
    return SimulationPlan(
        horizon_hours=168.0,
        cycle_time_seconds=60.0,
        mtbf_hours=12.0,
        mttr_hours=4.0,
        performance=0.8,
        quality=0.95,
        runs=800,
        seed=42,
    )


def _candidates() -> list[CandidateAction]:
    return [
        CandidateAction(
            action_id="double-line-speed",
            name="Reduce cycle time",
            description="Reduce the line cycle time from 60 to 30 seconds.",
            parameter_overrides={"cycle_time_seconds": 30.0},
            asset_id="asset-2",
        ),
        CandidateAction(
            action_id="faster-repair",
            name="Reduce repair time",
            description="Pre-stage spares to reduce mean repair time.",
            parameter_overrides={"mttr_hours": 1.0},
            asset_id="asset-2",
            recommendation_type="maintenance_window",
        ),
        CandidateAction(
            action_id="slower-line",
            name="Increase cycle time",
            description="Increase the line cycle time to 120 seconds.",
            parameter_overrides={"cycle_time_seconds": 120.0},
            asset_id="asset-2",
        ),
    ]


def test_scenario_sweep_ranks_expected_impact_and_filters_harmful_actions():
    optimizer = TwinOptimizer(
        simulator=SimulationEngine(),
        recommendation_engine=CloudStrategicEngine(),
    )
    result = optimizer.evaluate(
        "org-1",
        _baseline(),
        _candidates(),
        [
            {"asset_id": "asset-1", "oee": 82.0},
            {"asset_id": "asset-2", "oee": 47.0},
        ],
        now=datetime(2026, 7, 14, 8, 0, tzinfo=timezone.utc),
    )

    assert result.evaluated_candidates == 3
    assert [r.rank for r in result.recommendations] == [1, 2]
    assert [r.action_id for r in result.recommendations] == [
        "double-line-speed",
        "faster-repair",
    ]
    assert "slower-line" not in {r.action_id for r in result.recommendations}
    assert result.fleet_summary["bottleneck_asset_id"] == "asset-2"

    best = result.recommendations[0]
    baseline_mean = result.baseline_simulation["throughput"]["mean"]
    scenario_mean = best.scenario_metrics["throughput"]["mean"]
    assert best.expected_impact.throughput_delta_parts == pytest.approx(
        scenario_mean - baseline_mean
    )
    assert best.expected_impact.throughput_improvement_percent > 0
    assert best.expected_impact.objective_score == (
        best.expected_impact.throughput_improvement_percent
    )
    assert best.scenario_inputs["seed"] == _baseline().seed


@pytest.mark.asyncio
async def test_optimizer_emits_real_approval_gated_strategic_recommendation():
    recommendation_engine = CloudStrategicEngine()
    optimizer = TwinOptimizer(
        simulator=SimulationEngine(),
        recommendation_engine=recommendation_engine,
    )
    now = datetime.now(timezone.utc)
    result = await optimizer.optimize(
        "org-1",
        _baseline(),
        [_candidates()[0]],
        [{"asset_id": "asset-2", "oee": 47.0}],
        emit_recommendations=True,
        valid_for_hours=24,
        now=now,
    )

    assert len(result.recommendations) == 1
    recommendation = result.recommendations[0]
    assert recommendation.strategic_engine_emitted is True
    assert len(recommendation_engine.pending_recommendations) == 1

    queued = recommendation_engine.pending_recommendations[0]
    assert queued.recommendation_id == recommendation.recommendation_id
    assert queued.asset_id == "asset-2"
    assert queued.requires_approval is True
    assert queued.expected_impact["organization_id"] == "org-1"
    assert queued.expected_impact["action_id"] == "double-line-speed"
    # Since the FS-96 aware-datetime sweep, the strategic engine stores
    # valid_until timezone-AWARE (naive ISO inputs are coerced to UTC) — compare
    # aware-to-aware instead of stripping tzinfo.
    assert queued.valid_until > now


def test_plan_rejects_non_scenario_overrides():
    with pytest.raises(ValueError, match="Unsupported simulation overrides"):
        _baseline().with_overrides({"horizon_hours": 24.0})

    with pytest.raises(ValueError, match="must require approval"):
        CandidateAction(
            action_id="unsafe-action",
            name="Unsafe action",
            description="Attempt to bypass operator approval.",
            parameter_overrides={"mttr_hours": 1.0},
            requires_approval=False,
        )
