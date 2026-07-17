"""Digital-twin scenario optimization over the real simulation engine.

The simulation service deliberately returns numbers only.  This module adds the
recommendation layer: evaluate a shared baseline and candidate parameter changes,
rank beneficial actions by expected throughput impact, and send approval-gated
recommendations to the existing strategic engine.
"""

from __future__ import annotations

import asyncio
import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import sqrt
from typing import Any, Mapping, Sequence
from uuid import uuid4

import structlog
from prometheus_client import Counter, Histogram

from app.services.simulation import simulation_engine
from app.services.strategic_engine import strategic_engine

logger = structlog.get_logger()

# Prometheus metrics (scraped via /metrics in app/api/health.py). No labels —
# runs are org-scoped and org ids would be unbounded cardinality.
TWIN_OPTIMIZE_RUNS_TOTAL = Counter(
    "opsgrid_twin_optimize_runs_total",
    "Digital-twin optimization runs evaluated",
)

TWIN_OPTIMIZE_RUN_DURATION = Histogram(
    "opsgrid_twin_optimize_run_duration_seconds",
    "Digital-twin optimization run latency (baseline + candidate sweeps)",
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0],
)

TWIN_RECOMMENDATIONS_TOTAL = Counter(
    "opsgrid_twin_recommendations_total",
    "Digital-twin recommendations emitted by optimization runs",
)

_OVERRIDABLE_FIELDS = frozenset(
    {
        "cycle_time_seconds",
        "mtbf_hours",
        "mttr_hours",
        "performance",
        "quality",
    }
)


@dataclass(frozen=True)
class SimulationPlan:
    horizon_hours: float = 168.0
    cycle_time_seconds: float = 60.0
    mtbf_hours: float = 50.0
    mttr_hours: float = 2.0
    performance: float = 0.9
    quality: float = 0.98
    runs: int = 1000
    seed: int = 0

    def __post_init__(self) -> None:
        if self.horizon_hours <= 0 or self.cycle_time_seconds <= 0:
            raise ValueError("horizon_hours and cycle_time_seconds must be positive")
        if self.mtbf_hours < 0 or self.mttr_hours < 0:
            raise ValueError("mtbf_hours and mttr_hours cannot be negative")
        if not 0 < self.performance <= 1 or not 0 < self.quality <= 1:
            raise ValueError("performance and quality must be in (0, 1]")
        if self.runs < 1:
            raise ValueError("runs must be positive")

    def with_overrides(self, overrides: Mapping[str, float]) -> "SimulationPlan":
        unknown = set(overrides) - _OVERRIDABLE_FIELDS
        if unknown:
            raise ValueError(
                f"Unsupported simulation overrides: {sorted(unknown)}"
            )
        if not overrides:
            raise ValueError("A candidate action must change at least one parameter")
        return replace(
            self,
            **{name: float(value) for name, value in overrides.items()},
        )

    def simulation_kwargs(self) -> dict[str, Any]:
        return {
            "horizon_hours": self.horizon_hours,
            "cycle_time_seconds": self.cycle_time_seconds,
            "mtbf_hours": self.mtbf_hours,
            "mttr_hours": self.mttr_hours,
            "performance": self.performance,
            "quality": self.quality,
            "runs": self.runs,
            "seed": self.seed,
        }

    def as_dict(self) -> dict[str, Any]:
        return self.simulation_kwargs()


@dataclass(frozen=True)
class CandidateAction:
    action_id: str
    name: str
    description: str
    parameter_overrides: dict[str, float]
    asset_id: str | None = None
    recommendation_type: str = "parameter_tuning"
    requires_approval: bool = True

    def __post_init__(self) -> None:
        if not self.action_id.strip() or not self.name.strip():
            raise ValueError("action_id and name are required")
        unknown = set(self.parameter_overrides) - _OVERRIDABLE_FIELDS
        if unknown:
            raise ValueError(
                f"Unsupported simulation overrides: {sorted(unknown)}"
            )
        if not self.parameter_overrides:
            raise ValueError("A candidate action must change at least one parameter")
        if not self.requires_approval:
            raise ValueError("Strategic recommendations must require approval")


@dataclass(frozen=True)
class ExpectedImpact:
    throughput_delta_parts: float
    throughput_improvement_percent: float
    downtime_reduction_hours: float
    availability_improvement_points: float
    objective_score: float

    def as_dict(self) -> dict[str, float]:
        return {
            "throughput_delta_parts": self.throughput_delta_parts,
            "throughput_improvement_percent": (
                self.throughput_improvement_percent
            ),
            "downtime_reduction_hours": self.downtime_reduction_hours,
            "availability_improvement_points": (
                self.availability_improvement_points
            ),
            "objective_score": self.objective_score,
        }


@dataclass(frozen=True)
class TwinRecommendation:
    rank: int
    recommendation_id: str
    action_id: str
    name: str
    description: str
    asset_id: str | None
    recommendation_type: str
    priority: int
    confidence: float
    expected_impact: ExpectedImpact
    scenario_inputs: dict[str, Any]
    scenario_metrics: dict[str, Any]
    simulation_basis: str
    requires_approval: bool
    strategic_engine_emitted: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "rank": self.rank,
            "recommendation_id": self.recommendation_id,
            "action_id": self.action_id,
            "name": self.name,
            "description": self.description,
            "asset_id": self.asset_id,
            "recommendation_type": self.recommendation_type,
            "priority": self.priority,
            "confidence": self.confidence,
            "expected_impact": self.expected_impact.as_dict(),
            "scenario_inputs": self.scenario_inputs,
            "scenario_metrics": self.scenario_metrics,
            "simulation_basis": self.simulation_basis,
            "requires_approval": self.requires_approval,
            "strategic_engine_emitted": self.strategic_engine_emitted,
        }


@dataclass(frozen=True)
class OptimizationResult:
    organization_id: str
    objective: str
    evaluated_candidates: int
    baseline_simulation: dict[str, Any]
    fleet_summary: dict[str, Any]
    recommendations: list[TwinRecommendation]
    generated_at: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "organization_id": self.organization_id,
            "objective": self.objective,
            "evaluated_candidates": self.evaluated_candidates,
            "baseline_simulation": self.baseline_simulation,
            "fleet_summary": self.fleet_summary,
            "recommendations": [r.as_dict() for r in self.recommendations],
            "generated_at": self.generated_at,
        }


class TwinOptimizer:
    """Run fair, seeded scenario comparisons and emit strategic advice."""

    OBJECTIVE = "mean_throughput"

    def __init__(
        self,
        simulator=simulation_engine,
        recommendation_engine=strategic_engine,
    ) -> None:
        self.simulator = simulator
        self.recommendation_engine = recommendation_engine

    @staticmethod
    def _expected_impact(
        baseline: Mapping[str, Any],
        scenario: Mapping[str, Any],
    ) -> ExpectedImpact:
        baseline_throughput = float(baseline["throughput"]["mean"])
        scenario_throughput = float(scenario["throughput"]["mean"])
        throughput_delta = scenario_throughput - baseline_throughput
        if baseline_throughput > 0:
            improvement_percent = 100.0 * throughput_delta / baseline_throughput
        else:
            improvement_percent = 100.0 if throughput_delta > 0 else 0.0

        downtime_reduction = (
            float(baseline["downtime_hours"]["mean"])
            - float(scenario["downtime_hours"]["mean"])
        )
        availability_improvement = (
            float(scenario["availability_mean"])
            - float(baseline["availability_mean"])
        )
        score = round(improvement_percent, 4)
        return ExpectedImpact(
            throughput_delta_parts=round(throughput_delta, 2),
            throughput_improvement_percent=round(improvement_percent, 4),
            downtime_reduction_hours=round(downtime_reduction, 2),
            availability_improvement_points=round(availability_improvement, 2),
            objective_score=score,
        )

    @staticmethod
    def _confidence(
        baseline: Mapping[str, Any],
        scenario: Mapping[str, Any],
        throughput_delta: float,
        runs: int,
    ) -> float:
        baseline_width = max(
            0.0,
            float(baseline["throughput"]["p90"])
            - float(baseline["throughput"]["p10"]),
        )
        scenario_width = max(
            0.0,
            float(scenario["throughput"]["p90"])
            - float(scenario["throughput"]["p10"]),
        )
        noise = max((baseline_width + scenario_width) / 2.0, 1.0)
        signal = max(throughput_delta, 0.0)
        signal_confidence = signal / (signal + noise)
        sample_confidence = min(1.0, sqrt(runs / 1000.0))
        return round(
            min(0.99, 0.35 + 0.35 * sample_confidence + 0.30 * signal_confidence),
            2,
        )

    @staticmethod
    def _priority(improvement_percent: float) -> int:
        if improvement_percent >= 20.0:
            return 1
        if improvement_percent >= 10.0:
            return 2
        if improvement_percent >= 5.0:
            return 3
        return 4

    @staticmethod
    def _simulation_basis(
        plan: SimulationPlan,
        fleet_summary: Mapping[str, Any],
    ) -> str:
        basis = (
            f"{plan.runs} seeded Monte Carlo runs over "
            f"{plan.horizon_hours:g} hours, ranked by mean throughput improvement"
        )
        if fleet_summary.get("asset_count"):
            basis += (
                f"; fleet mean OEE {fleet_summary.get('mean_oee')}%, "
                f"bottleneck {fleet_summary.get('bottleneck_asset_id')}"
            )
        return basis

    def evaluate(
        self,
        organization_id: str,
        baseline_plan: SimulationPlan,
        candidates: Sequence[CandidateAction],
        fleet_assets: Sequence[Mapping[str, Any]],
        *,
        min_improvement_percent: float = 0.0,
        max_recommendations: int = 5,
        now: datetime | None = None,
    ) -> OptimizationResult:
        """Pure scenario sweep; every candidate uses the baseline's same seed."""
        if min_improvement_percent < 0:
            raise ValueError("min_improvement_percent cannot be negative")
        if max_recommendations < 1:
            raise ValueError("max_recommendations must be positive")
        action_ids = [candidate.action_id for candidate in candidates]
        if len(action_ids) != len(set(action_ids)):
            raise ValueError("Candidate action_id values must be unique")

        started = time.perf_counter()
        generated_at = now or datetime.now(timezone.utc)
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        else:
            generated_at = generated_at.astimezone(timezone.utc)

        baseline = self.simulator.monte_carlo_throughput(
            **baseline_plan.simulation_kwargs()
        )
        fleet_summary = self.simulator.fleet_oee_rollup(
            [dict(asset) for asset in fleet_assets]
        )
        basis = self._simulation_basis(baseline_plan, fleet_summary)

        recommendations: list[TwinRecommendation] = []
        for candidate in candidates:
            scenario_plan = baseline_plan.with_overrides(
                candidate.parameter_overrides
            )
            scenario = self.simulator.monte_carlo_throughput(
                **scenario_plan.simulation_kwargs()
            )
            impact = self._expected_impact(baseline, scenario)
            if (
                impact.throughput_improvement_percent <= 0
                or impact.throughput_improvement_percent
                < min_improvement_percent
            ):
                continue

            recommendations.append(
                TwinRecommendation(
                    rank=0,
                    recommendation_id=str(uuid4()),
                    action_id=candidate.action_id,
                    name=candidate.name,
                    description=candidate.description,
                    asset_id=candidate.asset_id,
                    recommendation_type=candidate.recommendation_type,
                    priority=self._priority(
                        impact.throughput_improvement_percent
                    ),
                    confidence=self._confidence(
                        baseline,
                        scenario,
                        impact.throughput_delta_parts,
                        baseline_plan.runs,
                    ),
                    expected_impact=impact,
                    scenario_inputs=scenario_plan.as_dict(),
                    scenario_metrics=scenario,
                    simulation_basis=basis,
                    requires_approval=candidate.requires_approval,
                )
            )

        recommendations.sort(
            key=lambda recommendation: (
                -recommendation.expected_impact.objective_score,
                -recommendation.expected_impact.downtime_reduction_hours,
                recommendation.action_id,
            )
        )
        ranked = [
            replace(recommendation, rank=index)
            for index, recommendation in enumerate(
                recommendations[:max_recommendations], start=1
            )
        ]
        try:  # metrics must never break the optimization path
            TWIN_OPTIMIZE_RUNS_TOTAL.inc()
            TWIN_OPTIMIZE_RUN_DURATION.observe(time.perf_counter() - started)
            if ranked:
                TWIN_RECOMMENDATIONS_TOTAL.inc(len(ranked))
        except Exception:  # pragma: no cover - defensive
            pass
        return OptimizationResult(
            organization_id=str(organization_id),
            objective=self.OBJECTIVE,
            evaluated_candidates=len(candidates),
            baseline_simulation=baseline,
            fleet_summary=fleet_summary,
            recommendations=ranked,
            generated_at=generated_at,
        )

    @staticmethod
    def _strategic_payload(
        result: OptimizationResult,
        recommendation: TwinRecommendation,
        valid_for_hours: int,
    ) -> dict[str, Any]:
        expected_impact: dict[str, Any] = recommendation.expected_impact.as_dict()
        expected_impact.update(
            {
                "organization_id": result.organization_id,
                "action_id": recommendation.action_id,
            }
        )
        valid_until = (
            result.generated_at + timedelta(hours=valid_for_hours)
        ).astimezone(timezone.utc).replace(tzinfo=None)
        return {
            "id": recommendation.recommendation_id,
            "asset_id": recommendation.asset_id,
            "type": recommendation.recommendation_type,
            "priority": recommendation.priority,
            "description": recommendation.description,
            "expected_impact": expected_impact,
            "confidence": recommendation.confidence,
            "simulation_basis": recommendation.simulation_basis,
            "valid_until": valid_until.isoformat(),
            "requires_approval": recommendation.requires_approval,
        }

    async def optimize(
        self,
        organization_id: str,
        baseline_plan: SimulationPlan,
        candidates: Sequence[CandidateAction],
        fleet_assets: Sequence[Mapping[str, Any]],
        *,
        min_improvement_percent: float = 0.0,
        max_recommendations: int = 5,
        emit_recommendations: bool = True,
        valid_for_hours: int = 24,
        now: datetime | None = None,
    ) -> OptimizationResult:
        if valid_for_hours < 1:
            raise ValueError("valid_for_hours must be positive")

        result = await asyncio.to_thread(
            self.evaluate,
            organization_id,
            baseline_plan,
            candidates,
            fleet_assets,
            min_improvement_percent=min_improvement_percent,
            max_recommendations=max_recommendations,
            now=now,
        )
        if not emit_recommendations:
            return result

        emitted: list[TwinRecommendation] = []
        for recommendation in result.recommendations:
            payload = self._strategic_payload(
                result, recommendation, valid_for_hours
            )
            try:
                await self.recommendation_engine.receive_recommendation(payload)
            except Exception as exc:  # optimization remains useful if queueing fails
                logger.warning(
                    "twin_recommendation_emission_failed",
                    recommendation_id=recommendation.recommendation_id,
                    organization_id=result.organization_id,
                    error=str(exc),
                )
                # FS-110: report into error-triage, not just the log stream.
                from app.services.error_tracker import error_tracker

                await error_tracker.report_subsystem_error(
                    exc,
                    subsystem="twin",
                    operation="emit_recommendation",
                    organization_id=(
                        str(result.organization_id)
                        if result.organization_id is not None
                        else None
                    ),
                )
                emitted.append(recommendation)
            else:
                emitted.append(
                    replace(recommendation, strategic_engine_emitted=True)
                )
        return replace(result, recommendations=emitted)


twin_optimizer = TwinOptimizer()
