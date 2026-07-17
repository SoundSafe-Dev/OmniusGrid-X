"""Predictive-maintenance remaining useful life estimates.

The first production version uses the real asset health index as its signal and
maps it onto a Weibull time-to-failure curve.  The explicit ``model_source``
keeps the response contract stable when a trained failure model is published in
the model registry later.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, replace
from datetime import datetime, timedelta, timezone
from math import exp, isfinite, log
from typing import Any
from uuid import UUID

import structlog
from prometheus_client import Counter, Histogram

from app.services.health_index import HealthResult, health_index_calculator
from app.services.notifications import notification_service

logger = structlog.get_logger()

# Prometheus metrics (scraped via /metrics in app/api/health.py). Labels are
# deliberately low-cardinality (risk level only — never asset ids).
RUL_ASSESSMENTS_TOTAL = Counter(
    "opsgrid_rul_assessments_total",
    "RUL assessments computed",
    ["risk_level"],
)

RUL_ASSESSMENT_DURATION = Histogram(
    "opsgrid_rul_assessment_duration_seconds",
    "End-to-end RUL assessment latency (health fetch + estimate)",
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

RUL_LOW_RUL_ALERTS_TOTAL = Counter(
    "opsgrid_rul_low_rul_alerts_total",
    "Low-RUL alert notifications raised for high/critical risk assessments",
    ["risk_level"],
)


@dataclass(frozen=True)
class MaintenanceWindow:
    start: datetime
    end: datetime
    urgency: str
    reason: str

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "urgency": self.urgency,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class RULAssessment:
    asset_id: str
    health_score: float
    failure_probability: float
    probability_horizon_hours: int
    remaining_useful_life_hours: float
    risk_level: str
    confidence: float
    recommended_maintenance_window: MaintenanceWindow
    drivers: list[dict[str, Any]]
    model_source: str
    computed_at: datetime
    notification_dispatched: bool = False
    notification_delivery_count: int = 0

    def as_dict(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "health_score": self.health_score,
            "failure_probability": self.failure_probability,
            "probability_horizon_hours": self.probability_horizon_hours,
            "remaining_useful_life_hours": self.remaining_useful_life_hours,
            "risk_level": self.risk_level,
            "confidence": self.confidence,
            "recommended_maintenance_window": (
                self.recommended_maintenance_window.as_dict()
            ),
            "drivers": self.drivers,
            "model_source": self.model_source,
            "computed_at": self.computed_at,
            "notification_dispatched": self.notification_dispatched,
            "notification_delivery_count": self.notification_delivery_count,
        }


class RULService:
    """Estimate failure risk and schedule a maintenance window for an asset."""

    PROBABILITY_HORIZON_HOURS = 30 * 24
    WEIBULL_SHAPE = 2.0
    MIN_CHARACTERISTIC_LIFE_HOURS = 24.0
    MAX_CHARACTERISTIC_LIFE_HOURS = 5 * 365 * 24.0
    UNKNOWN_HEALTH_BASELINE = 60.0
    MODEL_SOURCE = "health_index_weibull_v1"

    _DRIVER_MAX_IMPACT = {
        "alarm_rate": 30.0,
        "declining_oee": 20.0,
        "low_availability": 21.0,
    }
    _SEVERITY_BY_RISK = {
        "low": "info",
        "medium": "warning",
        "high": "error",
        "critical": "critical",
    }

    def __init__(
        self,
        health_calculator=health_index_calculator,
        notifier=notification_service,
    ) -> None:
        self.health_calculator = health_calculator
        self.notifier = notifier

    @staticmethod
    def _bounded(value: float, lower: float, upper: float, fallback: float) -> float:
        value = float(value)
        if not isfinite(value):
            return fallback
        return min(max(value, lower), upper)

    @classmethod
    def _driver_pressure(cls, drivers: list[dict[str, Any]]) -> float:
        pressure = 0.0
        for driver in drivers:
            maximum = cls._DRIVER_MAX_IMPACT.get(str(driver.get("factor")))
            if maximum is None:
                continue
            try:
                impact = abs(float(driver.get("impact", 0.0)))
            except (TypeError, ValueError):
                continue
            pressure = max(pressure, min(impact / maximum, 1.0))
        return pressure

    @staticmethod
    def _risk_level(failure_probability: float, rul_hours: float) -> str:
        if failure_probability >= 0.75 or rul_hours <= 7 * 24:
            return "critical"
        if failure_probability >= 0.35 or rul_hours <= 30 * 24:
            return "high"
        if failure_probability >= 0.10 or rul_hours <= 90 * 24:
            return "medium"
        return "low"

    @staticmethod
    def _maintenance_window(
        now: datetime,
        risk_level: str,
        rul_hours: float,
    ) -> MaintenanceWindow:
        # Fractions keep the recommendation ahead of the estimated failure;
        # caps keep healthy assets from receiving impractically distant windows.
        rules = {
            "critical": (0.0, 0.25, 0.0, 24.0),
            "high": (0.10, 0.35, 24.0, 72.0),
            "medium": (0.25, 0.55, 168.0, 336.0),
            "low": (0.40, 0.65, 720.0, 1080.0),
        }
        start_fraction, end_fraction, start_cap, end_cap = rules[risk_level]
        start_hours = min(rul_hours * start_fraction, start_cap)
        end_hours = min(rul_hours * end_fraction, end_cap)
        end_hours = max(end_hours, start_hours + 1.0)

        reasons = {
            "critical": "Service immediately; predicted failure risk is critical.",
            "high": "Schedule service in the next maintenance opportunity.",
            "medium": "Plan service within the upcoming maintenance cycle.",
            "low": "Include the asset in routine preventive maintenance.",
        }
        return MaintenanceWindow(
            start=now + timedelta(hours=start_hours),
            end=now + timedelta(hours=end_hours),
            urgency=risk_level,
            reason=reasons[risk_level],
        )

    @classmethod
    def calculate(
        cls,
        health: HealthResult,
        *,
        now: datetime | None = None,
        probability_horizon_hours: int = PROBABILITY_HORIZON_HOURS,
    ) -> RULAssessment:
        """Convert a health-index result into a bounded Weibull estimate."""
        if probability_horizon_hours <= 0:
            raise ValueError("probability_horizon_hours must be positive")

        computed_at = now or datetime.now(timezone.utc)
        if computed_at.tzinfo is None:
            computed_at = computed_at.replace(tzinfo=timezone.utc)
        else:
            computed_at = computed_at.astimezone(timezone.utc)

        health_score = cls._bounded(health.health_score, 0.0, 100.0, 50.0)
        confidence = cls._bounded(health.confidence, 0.0, 1.0, 0.0)
        pressure = cls._driver_pressure(health.drivers)

        # Low-confidence health is pulled toward a neutral baseline. Known
        # harmful drivers can then reduce the effective score by up to 10 pts.
        confidence_adjusted = (
            confidence * health_score
            + (1.0 - confidence) * cls.UNKNOWN_HEALTH_BASELINE
        )
        effective_score = cls._bounded(
            confidence_adjusted - 10.0 * pressure,
            0.0,
            100.0,
            cls.UNKNOWN_HEALTH_BASELINE,
        )

        life_ratio = (
            cls.MAX_CHARACTERISTIC_LIFE_HOURS
            / cls.MIN_CHARACTERISTIC_LIFE_HOURS
        )
        characteristic_life = cls.MIN_CHARACTERISTIC_LIFE_HOURS * exp(
            log(life_ratio) * effective_score / 100.0
        )
        failure_probability = 1.0 - exp(
            -(
                probability_horizon_hours / characteristic_life
            ) ** cls.WEIBULL_SHAPE
        )
        rul_hours = characteristic_life * (
            log(2.0) ** (1.0 / cls.WEIBULL_SHAPE)
        )
        risk_level = cls._risk_level(failure_probability, rul_hours)

        return RULAssessment(
            asset_id=str(health.asset_id),
            health_score=round(health_score, 1),
            failure_probability=round(failure_probability, 4),
            probability_horizon_hours=probability_horizon_hours,
            remaining_useful_life_hours=round(rul_hours, 1),
            risk_level=risk_level,
            confidence=round(confidence, 2),
            recommended_maintenance_window=cls._maintenance_window(
                computed_at, risk_level, rul_hours
            ),
            drivers=list(health.drivers),
            model_source=cls.MODEL_SOURCE,
            computed_at=computed_at,
        )

    @classmethod
    def _notification_event(
        cls,
        assessment: RULAssessment,
        organization_id: UUID,
    ) -> dict[str, Any]:
        window = assessment.recommended_maintenance_window
        return {
            "event_type": "rul_recommendation",
            "severity": cls._SEVERITY_BY_RISK[assessment.risk_level],
            "domain": "maintenance",
            "organization_id": str(organization_id),
            "asset_id": assessment.asset_id,
            "title": f"Predictive maintenance: {assessment.risk_level} risk",
            "message": (
                f"Asset {assessment.asset_id} has a "
                f"{assessment.failure_probability:.1%} probability of failure "
                f"within {assessment.probability_horizon_hours} hours and an "
                f"estimated RUL of {assessment.remaining_useful_life_hours:.1f} "
                f"hours. Schedule maintenance between {window.start.isoformat()} "
                f"and {window.end.isoformat()}."
            ),
            "failure_probability": assessment.failure_probability,
            "probability_horizon_hours": assessment.probability_horizon_hours,
            "remaining_useful_life_hours": assessment.remaining_useful_life_hours,
            "maintenance_window": {
                "start": window.start.isoformat(),
                "end": window.end.isoformat(),
                "urgency": window.urgency,
                "reason": window.reason,
            },
            "model_source": assessment.model_source,
        }

    async def assess_asset(
        self,
        asset_id: str,
        organization_id: UUID,
        *,
        health_window_hours: int = 24,
        dispatch_notification: bool = False,
        now: datetime | None = None,
    ) -> RULAssessment:
        started = time.perf_counter()
        health = await self.health_calculator.get_asset_health(
            asset_id, hours=health_window_hours
        )
        assessment = self.calculate(health, now=now)
        try:  # metrics must never break the assessment path
            RUL_ASSESSMENTS_TOTAL.labels(risk_level=assessment.risk_level).inc()
            RUL_ASSESSMENT_DURATION.observe(time.perf_counter() - started)
        except Exception:  # pragma: no cover - defensive
            pass
        if not dispatch_notification:
            return assessment

        event = self._notification_event(assessment, organization_id)
        try:
            deliveries = await self.notifier.dispatch(
                event, organization_id=str(organization_id)
            )
        except Exception as exc:  # assessment remains available if delivery fails
            logger.warning(
                "rul_notification_failed",
                asset_id=asset_id,
                organization_id=str(organization_id),
                error=str(exc),
            )
            # FS-110: surface the swallowed failure in error-triage — a warning
            # log alone doesn't show up on the error dashboard.
            from app.services.error_tracker import error_tracker

            await error_tracker.report_subsystem_error(
                exc,
                subsystem="rul",
                operation="notify",
                organization_id=str(organization_id),
            )
            return assessment

        if assessment.risk_level in ("high", "critical"):
            try:  # metrics must never break the assessment path
                RUL_LOW_RUL_ALERTS_TOTAL.labels(
                    risk_level=assessment.risk_level
                ).inc()
            except Exception:  # pragma: no cover - defensive
                pass

        return replace(
            assessment,
            notification_dispatched=True,
            notification_delivery_count=sum(
                1 for delivery in deliveries if delivery.get("delivered")
            ),
        )


rul_service = RULService()
