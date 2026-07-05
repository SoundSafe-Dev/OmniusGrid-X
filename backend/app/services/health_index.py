"""Asset Health Index — a computed 0–100 health metric per asset.

Combines recent OEE level + trend, alarm rate, and (optional) availability into a
single health score with diagnostic *drivers* (which factors are hurting health).

This is a **metric only**: it produces a number + drivers for dashboards and as a
signal for other systems. It does NOT generate recommendations or create tasks —
that remains the Correlation AI engine's responsibility.
"""

from datetime import datetime, timedelta
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional
import statistics

import structlog

logger = structlog.get_logger()


@dataclass
class HealthResult:
    asset_id: str
    health_score: float          # 0–100
    drivers: List[Dict[str, Any]] = field(default_factory=list)
    confidence: float = 1.0      # 0–1 (lower when little data)
    computed_at: str = ""

    def as_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "health_score": self.health_score,
            "drivers": self.drivers,
            "confidence": self.confidence,
            "computed_at": self.computed_at,
        }


class HealthIndexCalculator:
    """Computes the asset health index. The core math is pure and testable."""

    # Weights / thresholds (tuned to keep the score interpretable).
    DECLINE_THRESHOLD = 5.0      # OEE-point drop (first->last) before penalizing
    DECLINE_MAX_PENALTY = 20.0
    ALARM_PENALTY_PER_HR = 5.0
    ALARM_MAX_PENALTY = 30.0
    AVAILABILITY_FLOOR = 70.0
    AVAILABILITY_WEIGHT = 0.3

    def compute(
        self,
        asset_id: str,
        recent_oee: List[float],
        alarm_rate_per_hour: float = 0.0,
        availability: Optional[float] = None,
        now: Optional[datetime] = None,
    ) -> HealthResult:
        """Pure health computation. ``recent_oee`` oldest→newest (percentages)."""
        drivers: List[Dict[str, Any]] = []

        if recent_oee:
            base = statistics.mean(recent_oee)
            confidence = min(1.0, len(recent_oee) / 6.0)
        else:
            base = 50.0  # unknown -> neutral
            confidence = 0.2

        health = base

        # Declining OEE trend (first -> last).
        if len(recent_oee) >= 2:
            trend = recent_oee[-1] - recent_oee[0]
            if trend < -self.DECLINE_THRESHOLD:
                penalty = min(self.DECLINE_MAX_PENALTY, -trend)
                health -= penalty
                drivers.append({"factor": "declining_oee", "impact": round(-penalty, 1),
                                "detail": f"OEE fell {round(-trend, 1)} pts"})

        # Alarm rate.
        alarm_penalty = min(self.ALARM_MAX_PENALTY, alarm_rate_per_hour * self.ALARM_PENALTY_PER_HR)
        if alarm_penalty > 0:
            health -= alarm_penalty
            drivers.append({"factor": "alarm_rate", "impact": round(-alarm_penalty, 1),
                            "detail": f"{round(alarm_rate_per_hour, 2)} alarms/hr"})

        # Low availability.
        if availability is not None and availability < self.AVAILABILITY_FLOOR:
            penalty = (self.AVAILABILITY_FLOOR - availability) * self.AVAILABILITY_WEIGHT
            health -= penalty
            drivers.append({"factor": "low_availability", "impact": round(-penalty, 1),
                            "detail": f"availability {round(availability, 1)}%"})

        health = max(0.0, min(100.0, health))
        return HealthResult(
            asset_id=asset_id,
            health_score=round(health, 1),
            drivers=drivers,
            confidence=round(confidence, 2),
            computed_at=(now or datetime.utcnow()).isoformat(),
        )

    # ------------------------------------------------------------------ #
    # DB-backed gathering (exercised in CI's backend job)
    # ------------------------------------------------------------------ #
    async def get_asset_health(self, asset_id: str, hours: int = 24) -> HealthResult:
        """Gather recent OEE + alarm rate for an asset and compute its health."""
        now = datetime.utcnow()
        recent_oee: List[float] = []
        availability: Optional[float] = None
        try:
            from app.services.oee_calculator import oee_calculator
            history = await oee_calculator.get_historical_oee(
                asset_id, now - timedelta(hours=hours), now, aggregation="hourly"
            )
            recent_oee = [float(h.get("oee", 0.0)) for h in history if h.get("oee") is not None]
            avails = [float(h["availability"]) for h in history if h.get("availability") is not None]
            availability = avails[-1] if avails else None
        except Exception as e:  # pragma: no cover - defensive DB path
            logger.warning("health_index_oee_unavailable", asset_id=asset_id, error=str(e))

        alarm_rate = await self._recent_alarm_rate(asset_id, hours)
        return self.compute(asset_id, recent_oee, alarm_rate, availability, now)

    async def _recent_alarm_rate(self, asset_id: str, hours: int) -> float:
        """Alarms per hour for the asset over the window (0.0 if unavailable)."""
        try:
            from sqlalchemy import select, func
            from app.db.database import AsyncSessionLocal
            from app.db.models import Alarm
            since = datetime.utcnow() - timedelta(hours=hours)
            async with AsyncSessionLocal() as session:
                result = await session.execute(
                    select(func.count()).select_from(Alarm).where(
                        Alarm.asset_id == asset_id, Alarm.occurred_at >= since
                    )
                )
                count = result.scalar() or 0
            return count / max(1, hours)
        except Exception as e:  # pragma: no cover - defensive DB path
            logger.warning("health_index_alarm_rate_unavailable", asset_id=asset_id, error=str(e))
            return 0.0


health_index_calculator = HealthIndexCalculator()
