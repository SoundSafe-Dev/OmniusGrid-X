"""Digital-twin / what-if simulation — numeric only.

Monte-Carlo simulation of line throughput/downtime under MTBF/MTTR distributions,
and fleet OEE rollups. This is a quantitative *what-if* tool: it returns numbers
and scenarios (expected throughput, downtime percentiles, the bottleneck asset).
It deliberately produces NO recommendations or actions — analysis/recommendations
remain the Correlation AI engine's job — so it complements, not duplicates it.

Deterministic given a seed (uses a local random.Random), so results are testable.
"""

import random
import statistics
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()


def _percentile(sorted_vals: List[float], pct: float) -> float:
    if not sorted_vals:
        return 0.0
    k = (len(sorted_vals) - 1) * pct
    lo = int(k)
    hi = min(lo + 1, len(sorted_vals) - 1)
    frac = k - lo
    return sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * frac


class SimulationEngine:
    """Numeric what-if simulation + fleet analytics (no recommendations)."""

    def monte_carlo_throughput(
        self,
        horizon_hours: float = 168.0,
        cycle_time_seconds: float = 60.0,
        mtbf_hours: float = 50.0,
        mttr_hours: float = 2.0,
        performance: float = 0.9,
        quality: float = 0.98,
        runs: int = 1000,
        seed: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Simulate ``runs`` production runs; return throughput/downtime stats.

        Each run alternates uptime (exponential MTBF) and repair (exponential
        MTTR) across the horizon; parts = uptime/cycle_time * performance * quality.
        """
        if cycle_time_seconds <= 0 or horizon_hours <= 0:
            raise ValueError("cycle_time_seconds and horizon_hours must be > 0")

        rng = random.Random(seed)
        parts_per_run: List[float] = []
        downtime_per_run: List[float] = []
        availability_per_run: List[float] = []

        for _ in range(max(1, runs)):
            t = 0.0
            downtime = 0.0
            while t < horizon_hours:
                ttf = rng.expovariate(1.0 / mtbf_hours) if mtbf_hours > 0 else float("inf")
                run_time = min(ttf, horizon_hours - t)
                t += run_time
                if t >= horizon_hours:
                    break
                ttr = rng.expovariate(1.0 / mttr_hours) if mttr_hours > 0 else 0.0
                repair = min(ttr, horizon_hours - t)
                downtime += repair
                t += repair

            uptime = max(0.0, horizon_hours - downtime)
            parts = (uptime * 3600.0 / cycle_time_seconds) * performance * quality
            parts_per_run.append(parts)
            downtime_per_run.append(downtime)
            availability_per_run.append(uptime / horizon_hours if horizon_hours else 0.0)

        parts_sorted = sorted(parts_per_run)
        return {
            "runs": len(parts_per_run),
            "seed": seed,
            "throughput": {
                "mean": round(statistics.mean(parts_per_run), 1),
                "p10": round(_percentile(parts_sorted, 0.10), 1),
                "p50": round(_percentile(parts_sorted, 0.50), 1),
                "p90": round(_percentile(parts_sorted, 0.90), 1),
            },
            "downtime_hours": {
                "mean": round(statistics.mean(downtime_per_run), 2),
                "p90": round(_percentile(sorted(downtime_per_run), 0.90), 2),
            },
            "availability_mean": round(statistics.mean(availability_per_run) * 100, 1),
            "inputs": {
                "horizon_hours": horizon_hours,
                "cycle_time_seconds": cycle_time_seconds,
                "mtbf_hours": mtbf_hours,
                "mttr_hours": mttr_hours,
                "performance": performance,
                "quality": quality,
            },
        }

    def fleet_oee_rollup(self, assets: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Aggregate per-asset OEE into fleet metrics + the bottleneck (lowest OEE)."""
        entries = [a for a in assets if a.get("oee") is not None]
        if not entries:
            return {"asset_count": 0, "mean_oee": 0.0, "bottleneck_asset_id": None}

        oees = [float(a["oee"]) for a in entries]
        bottleneck = min(entries, key=lambda a: float(a["oee"]))
        return {
            "asset_count": len(entries),
            "mean_oee": round(statistics.mean(oees), 1),
            "min_oee": round(min(oees), 1),
            "max_oee": round(max(oees), 1),
            "bottleneck_asset_id": bottleneck.get("asset_id"),
            "bottleneck_oee": round(float(bottleneck["oee"]), 1),
            "distribution": {
                "world_class": sum(1 for o in oees if o >= 85),
                "acceptable": sum(1 for o in oees if 60 <= o < 85),
                "low": sum(1 for o in oees if o < 60),
            },
        }


simulation_engine = SimulationEngine()
