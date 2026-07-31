"""Fleet-wide aggregates for the operations dashboard (FS-192).

The dashboard previously had four stat tiles and no trends, because the data
didn't exist: `health-index` and `rul` expose only ``/{asset_id}``, and nothing
returned a time-bucketed series. These endpoints fill that gap.

Two rules held throughout:

1. **Aggregate in SQL, not in Python loops.** ``/oee/dashboard/summary`` calls
   ``calculate_oee`` once per asset — an N+1 behind a dashboard tile. The trend
   endpoints here are single ``GROUP BY`` queries regardless of fleet size. The
   two health endpoints can't be pure SQL (the scoring function is Python), so
   they batch every input in a fixed number of queries and then call the
   already-tested pure ``HealthIndexCalculator.compute`` per asset — O(1)
   queries, not O(assets).

2. **Say what the number is.** Availability-only OEE is reported as such via
   ``availability_only`` rather than being passed off as full OEE, which is what
   ``dashboard.py`` did by hardcoding ``performance = quality = 1.0``.

Every endpoint is tenant-scoped through ``get_tenant_db`` (sets the
``app.current_org_id`` GUC that RLS reads) plus an explicit org filter.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import UUID

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.core.tenant import get_tenant_db, get_tenant_org_id
from app.core.time_buckets import (
    BUCKET_SECONDS,
    bucket_start,
    fill_series,
    is_postgres,
    pg_bucket,
    resolve_bucket,
)
from app.db.models import Alarm, Asset, PackMLState, Telemetry
from app.services.health_index import health_index_calculator

logger = structlog.get_logger()

router = APIRouter(dependencies=[Depends(get_current_active_user)])


# ---- Response schemas (pool #43). These document what the handlers already
# return; no shape changed. snake_case on the wire — `/api/v1/dashboard` is
# registered with the frontend casing seam, so `asset_count` arrives as
# `assetCount`.


class AlarmTrendResponse(BaseModel):
    bucket: str
    hours: int
    severities: List[str]
    #: Each point is `{timestamp, total, <severity>: count, ...}` — the severity
    #: names are KEYS, discovered per query, so this cannot be a fixed model. The
    #: frontend types it as an index signature for the same reason.
    series: List[Dict[str, Any]]
    #: Returned but absent from the frontend's `AlarmTrend`. Declared because the
    #: handler sends it: the model must match the payload, not the consumer.
    asset_count: int


class ThroughputTotals(BaseModel):
    total_parts: int
    good_parts: int
    #: None when no part counters were reported — NOT 0% quality. The handler is
    #: explicit about this and the frontend comment repeats it.
    quality_pct: Optional[float] = None


class ThroughputResponse(BaseModel):
    bucket: str
    hours: int
    series: List[Dict[str, Any]]
    asset_count: int
    totals: ThroughputTotals


class AvailabilityTrendResponse(BaseModel):
    bucket: str
    hours: int
    availability_only: bool
    asset_count: int
    series: List[Dict[str, Any]]
    #: Optional because the no-assets early return omits it entirely. Declaring it
    #: required would turn that branch into a 500; declaring it optional makes the
    #: branch emit `null`, which `fmtNum` on the dashboard already renders as "—",
    #: identical to the absent key it sends today.
    average_availability_pct: Optional[float] = None


class HealthBandItem(BaseModel):
    band: str
    min: int
    max: int
    count: int


class HealthDistributionResponse(BaseModel):
    hours: int
    asset_count: int
    bands: List[HealthBandItem]
    average_health: Optional[float] = None


class AtRiskResponse(BaseModel):
    hours: int
    asset_count: int
    #: Rows built by the health scorer; passed through as scored.
    items: List[Dict[str, Any]]

# Part-counter metric names, mirroring oee_calculator._extract_part_counters so
# throughput and OEE agree on what "a part" is.
TOTAL_PART_METRICS = ("parts_produced", "parts_count", "total_parts", "cycle_count")
GOOD_PART_METRICS = ("good_parts", "parts_ok")

# PackML states that count as productive run time.
RUNNING_STATES = ("Execute",)


def _window(hours: int) -> tuple[datetime, datetime]:
    end = datetime.now(timezone.utc)
    return end - timedelta(hours=hours), end


def _resolve_bucket_or_400(bucket: Optional[str]) -> tuple[str, int]:
    try:
        return resolve_bucket(bucket)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


async def _org_asset_ids(db: AsyncSession, org_id: UUID) -> list[UUID]:
    result = await db.execute(
        select(Asset.id).where(Asset.organization_id == org_id, Asset.is_active == True)
    )
    return [row[0] for row in result.all()]


@router.get("/alarms/trend", response_model=AlarmTrendResponse, summary="Alarm counts over time, by severity")
async def alarms_trend(
    hours: int = Query(24, ge=1, le=720),
    bucket: Optional[str] = Query(None, description=f"one of {sorted(BUCKET_SECONDS)}"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Alarms bucketed by time and severity — one GROUP BY, any fleet size."""
    bucket_name, seconds = _resolve_bucket_or_400(bucket)
    start, end = _window(hours)

    base = (
        select(Alarm.occurred_at, Alarm.severity)
        .join(Asset, Alarm.asset_id == Asset.id)
        .where(
            Asset.organization_id == org_id,
            Alarm.occurred_at >= start,
            Alarm.occurred_at <= end,
        )
    )

    counts: dict[datetime, dict[str, int]] = {}
    severities: set[str] = set()

    if is_postgres(db):
        b = pg_bucket(Alarm.occurred_at, seconds)
        result = await db.execute(
            select(b.label("bucket"), Alarm.severity, func.count().label("n"))
            .select_from(Alarm)
            .join(Asset, Alarm.asset_id == Asset.id)
            .where(
                Asset.organization_id == org_id,
                Alarm.occurred_at >= start,
                Alarm.occurred_at <= end,
            )
            .group_by("bucket", Alarm.severity)
        )
        rows = [(ts, sev, n) for ts, sev, n in result.all()]
    else:
        raw = await db.execute(base)
        rows = [(ts, sev, 1) for ts, sev in raw.all()]

    for ts, severity, n in rows:
        key = bucket_start(ts, seconds)
        sev = severity or "unknown"
        severities.add(sev)
        counts.setdefault(key, {})
        counts[key][sev] = counts[key].get(sev, 0) + int(n)

    ordered = sorted(severities)
    series = fill_series(
        {ts: {**{s: 0 for s in ordered}, **vals, "total": sum(vals.values())}
         for ts, vals in counts.items()},
        start, end, seconds,
        default={**{s: 0 for s in ordered}, "total": 0},
    )

    # HOW MANY ASSETS THIS WAS COMPUTED OVER. `oee/trend`, `health/distribution` and
    # `assets/at-risk` all report it and these two did not — so an all-zero alarm trend was
    # indistinguishable between a fleet of fifty with nothing wrong (good news) and an
    # organisation with no assets at all (nothing was examined). Three of five reporting it is
    # the state in which the other two look fine.
    asset_count = (
        await db.execute(
            select(func.count(Asset.id)).where(Asset.organization_id == org_id)
        )
    ).scalar() or 0

    return {
        "bucket": bucket_name,
        "hours": hours,
        "severities": ordered,
        "series": series,
        "asset_count": asset_count,
    }


@router.get("/throughput", response_model=ThroughputResponse, summary="Produced-part throughput over time")
async def throughput_trend(
    hours: int = Query(24, ge=1, le=720),
    bucket: Optional[str] = Query(None, description=f"one of {sorted(BUCKET_SECONDS)}"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Total and good parts per bucket, summed across the fleet.

    Part counters are cumulative per asset in some deployments and per-interval
    in others; we sum the values reported in each window, which matches how
    ``oee_calculator`` reads them.
    """
    bucket_name, seconds = _resolve_bucket_or_400(bucket)
    start, end = _window(hours)
    wanted = TOTAL_PART_METRICS + GOOD_PART_METRICS

    if is_postgres(db):
        b = pg_bucket(Telemetry.time, seconds)
        result = await db.execute(
            select(b.label("bucket"), Telemetry.metric_name, func.sum(Telemetry.value))
            .select_from(Telemetry)
            .join(Asset, Telemetry.asset_id == Asset.id)
            .where(
                Asset.organization_id == org_id,
                Telemetry.metric_name.in_(wanted),
                Telemetry.time >= start,
                Telemetry.time <= end,
            )
            .group_by("bucket", Telemetry.metric_name)
        )
        rows = [(ts, name, float(v or 0)) for ts, name, v in result.all()]
    else:
        raw = await db.execute(
            select(Telemetry.time, Telemetry.metric_name, Telemetry.value)
            .join(Asset, Telemetry.asset_id == Asset.id)
            .where(
                Asset.organization_id == org_id,
                Telemetry.metric_name.in_(wanted),
                Telemetry.time >= start,
                Telemetry.time <= end,
            )
        )
        rows = [(ts, name, float(v or 0)) for ts, name, v in raw.all()]

    agg: dict[datetime, dict[str, float]] = {}
    for ts, name, value in rows:
        key = bucket_start(ts, seconds)
        entry = agg.setdefault(key, {"total_parts": 0.0, "good_parts": 0.0})
        if name in TOTAL_PART_METRICS:
            entry["total_parts"] += value
        if name in GOOD_PART_METRICS:
            entry["good_parts"] += value

    series = fill_series(
        agg, start, end, seconds, default={"total_parts": 0.0, "good_parts": 0.0}
    )
    total = sum(p["total_parts"] for p in series)
    good = sum(p["good_parts"] for p in series)

    # See the note in `alarms_trend`: a throughput series of zeroes says nothing about
    # whether anything was there to produce parts.
    asset_count = (
        await db.execute(
            select(func.count(Asset.id)).where(Asset.organization_id == org_id)
        )
    ).scalar() or 0

    return {
        "bucket": bucket_name,
        "hours": hours,
        "series": series,
        "asset_count": asset_count,
        "totals": {
            "total_parts": total,
            "good_parts": good,
            # Quality is only meaningful when both counters are actually reported.
            "quality_pct": round(good / total * 100, 2) if total > 0 else None,
        },
    }


@router.get("/oee/trend", response_model=AvailabilityTrendResponse, summary="Fleet availability over time")
async def oee_trend(
    hours: int = Query(24, ge=1, le=720),
    bucket: Optional[str] = Query(None, description=f"one of {sorted(BUCKET_SECONDS)}"),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Run time / elapsed time per bucket, across the fleet.

    This is **availability only**, and says so: performance needs a per-asset
    ideal cycle time and quality needs part counters, neither of which can be
    resolved inside one GROUP BY. ``oee_calculator.calculate_oee`` computes the
    full three-factor OEE for a single asset — use that for point-in-time
    figures. Reporting this as "OEE" is precisely the overstatement this field
    exists to prevent.
    """
    bucket_name, seconds = _resolve_bucket_or_400(bucket)
    start, end = _window(hours)

    asset_ids = await _org_asset_ids(db, org_id)
    if not asset_ids:
        return {
            "bucket": bucket_name, "hours": hours, "availability_only": True,
            "asset_count": 0, "series": fill_series({}, start, end, seconds,
                                                    default={"availability_pct": None}),
        }

    if is_postgres(db):
        b = pg_bucket(PackMLState.state_entered_at, seconds)
        result = await db.execute(
            select(b.label("bucket"), func.sum(PackMLState.duration_seconds))
            .where(
                PackMLState.asset_id.in_(asset_ids),
                PackMLState.state.in_(RUNNING_STATES),
                PackMLState.state_entered_at >= start,
                PackMLState.state_entered_at <= end,
            )
            .group_by("bucket")
        )
        rows = [(ts, float(v or 0)) for ts, v in result.all()]
    else:
        raw = await db.execute(
            select(PackMLState.state_entered_at, PackMLState.duration_seconds).where(
                PackMLState.asset_id.in_(asset_ids),
                PackMLState.state.in_(RUNNING_STATES),
                PackMLState.state_entered_at >= start,
                PackMLState.state_entered_at <= end,
            )
        )
        rows = [(ts, float(v or 0)) for ts, v in raw.all()]

    run_seconds: dict[datetime, float] = {}
    for ts, secs in rows:
        key = bucket_start(ts, seconds)
        run_seconds[key] = run_seconds.get(key, 0.0) + secs

    # Capacity per bucket = bucket length × number of assets.
    capacity = seconds * len(asset_ids)
    agg = {
        ts: {"availability_pct": round(min(100.0, total / capacity * 100), 2)}
        for ts, total in run_seconds.items()
    }
    series = fill_series(
        agg, start, end, seconds, default={"availability_pct": 0.0}
    )

    measured = [p["availability_pct"] for p in series if p["availability_pct"] is not None]
    return {
        "bucket": bucket_name,
        "hours": hours,
        "availability_only": True,
        "asset_count": len(asset_ids),
        "series": series,
        "average_availability_pct": round(sum(measured) / len(measured), 2) if measured else 0.0,
    }


async def _fleet_health(db: AsyncSession, org_id: UUID, hours: int) -> list[dict]:
    """Health score for every asset in the org, in a fixed number of queries.

    Deliberately not ``health_index_calculator.get_asset_health`` per asset: that
    issues several queries each (and opens its own non-tenant session, so its
    alarm-rate lookup is silently zeroed by RLS). Inputs are gathered in bulk
    here and fed to the same pure ``compute``.
    """
    start, end = _window(hours)

    result = await db.execute(
        select(Asset.id, Asset.name).where(
            Asset.organization_id == org_id, Asset.is_active == True
        )
    )
    assets = [(row[0], row[1]) for row in result.all()]
    if not assets:
        return []
    asset_ids = [a[0] for a in assets]

    # One query: alarms per asset over the window.
    alarm_rows = await db.execute(
        select(Alarm.asset_id, func.count())
        .where(Alarm.asset_id.in_(asset_ids), Alarm.occurred_at >= start)
        .group_by(Alarm.asset_id)
    )
    alarm_counts = {row[0]: int(row[1]) for row in alarm_rows.all()}

    # One query: run seconds per asset (availability proxy).
    run_rows = await db.execute(
        select(PackMLState.asset_id, func.sum(PackMLState.duration_seconds))
        .where(
            PackMLState.asset_id.in_(asset_ids),
            PackMLState.state.in_(RUNNING_STATES),
            PackMLState.state_entered_at >= start,
        )
        .group_by(PackMLState.asset_id)
    )
    run_seconds = {row[0]: float(row[1] or 0) for row in run_rows.all()}

    window_seconds = max(1.0, (end - start).total_seconds())
    out = []
    for asset_id, name in assets:
        availability = min(100.0, run_seconds.get(asset_id, 0.0) / window_seconds * 100)
        alarm_rate = alarm_counts.get(asset_id, 0) / max(1, hours)
        # recent_oee is unavailable in bulk (it needs per-asset part counters);
        # compute() treats an empty list as "unknown" and lowers its confidence,
        # which is the honest signal here.
        health = health_index_calculator.compute(
            str(asset_id),
            recent_oee=[],
            alarm_rate_per_hour=alarm_rate,
            availability=availability,
        )
        out.append({
            "asset_id": str(asset_id),
            "asset_name": name,
            "health_score": health.health_score,
            "confidence": health.confidence,
            "availability_pct": round(availability, 2),
            "alarm_rate_per_hour": round(alarm_rate, 2),
            "drivers": health.drivers,
        })
    return out


# Bands are inclusive-low / exclusive-high except the top one.
HEALTH_BANDS = (
    ("critical", 0, 40),
    ("at_risk", 40, 60),
    ("fair", 60, 80),
    ("healthy", 80, 100.01),
)


@router.get("/health/distribution", response_model=HealthDistributionResponse, summary="Asset-health histogram for the fleet")
async def health_distribution(
    hours: int = Query(24, ge=1, le=720),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    scored = await _fleet_health(db, org_id, hours)
    bands = {name: 0 for name, _, _ in HEALTH_BANDS}
    for entry in scored:
        for name, low, high in HEALTH_BANDS:
            if low <= entry["health_score"] < high:
                bands[name] += 1
                break

    scores = [e["health_score"] for e in scored]
    return {
        "hours": hours,
        "asset_count": len(scored),
        "bands": [
            {"band": name, "min": low, "max": high, "count": bands[name]}
            for name, low, high in HEALTH_BANDS
        ],
        "average_health": round(sum(scores) / len(scores), 1) if scores else None,
    }


@router.get("/assets/at-risk", response_model=AtRiskResponse, summary="Lowest-health assets, worst first")
async def assets_at_risk(
    hours: int = Query(24, ge=1, le=720),
    limit: int = Query(10, ge=1, le=100),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    scored = await _fleet_health(db, org_id, hours)
    scored.sort(key=lambda e: e["health_score"])
    return {
        "hours": hours,
        "asset_count": len(scored),
        "items": scored[:limit],
    }
