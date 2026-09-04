"""Telemetry API Routes.

Telemetry rows are scoped indirectly through their parent ``Asset``.
Every endpoint first verifies that the requested ``asset_id`` belongs
to the authenticated user's organization (via
:func:`app.core.tenant.get_tenant_org_id`). Cross-tenant access
returns 404 to avoid leaking the existence of assets in other
organizations.
"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import MAX_OFFSET
from app.middleware.tenant_isolation import get_tenant_org_id, get_tenant_db
from app.db.models import Telemetry, Asset, PackMLState
from app.middleware.rate_limit import rate_limit

router = APIRouter()

# Aggregation window sizes for the history endpoint (task B9).
AGGREGATION_SECONDS = {"1min": 60, "5min": 300, "1hour": 3600}


def bucket_records(records: list, seconds: int, aggregation: str) -> list:
    """Pure time-bucket rollup (avg/min/max/count) for non-Postgres dialects.

    ``records``: dicts with time (datetime), metric_name, value, unit. Buckets are
    aligned to the epoch (floor(ts/seconds)*seconds), newest bucket first —
    mirroring the TimescaleDB time_bucket path so both dialects return one shape.
    """
    buckets: dict = {}
    for r in records:
        epoch = int(r["time"].timestamp())
        start = epoch - (epoch % seconds)
        key = (start, r["metric_name"])
        b = buckets.setdefault(key, {"values": [], "unit": r.get("unit")})
        b["values"].append(r["value"])
    out = []
    for (start, metric_name), b in sorted(buckets.items(), reverse=True):
        vals = b["values"]
        out.append({
            "timestamp": datetime.utcfromtimestamp(start).isoformat(),
            "metric_name": metric_name,
            "value": sum(vals) / len(vals),
            "min": min(vals),
            "max": max(vals),
            "count": len(vals),
            "unit": b["unit"],
            "aggregation": aggregation,
        })
    return out


def _history_page(items: list, start_time, end_time, skip: int, limit: int) -> dict:
    """Time-series pagination envelope (FS-89).

    A row COUNT over a telemetry window is expensive and rarely useful, so this
    deliberately does NOT carry a `total`. Instead it signals whether the window
    was truncated (`has_more` = a full page came back) and returns the newest /
    oldest timestamps as cursors: fetch the next (older) page with
    `end_time = meta.oldest`. Rows are ordered newest-first, so items[0] is the
    newest and items[-1] the oldest.
    """
    return {
        "items": items,
        "meta": {
            "count": len(items),
            "skip": skip,
            "limit": limit,
            "has_more": len(items) == limit,
            "start_time": start_time.isoformat(),
            "end_time": end_time.isoformat(),
            "newest": items[0]["timestamp"] if items else None,
            "oldest": items[-1]["timestamp"] if items else None,
        },
    }


async def _verify_asset_in_org(
    db: AsyncSession,
    asset_id: UUID,
    org_id: UUID,
) -> None:
    """Verify ``asset_id`` exists and belongs to ``org_id``.

    Raises HTTP 404 if the asset does not exist OR belongs to a
    different organization. Using 404 (not 403) prevents an attacker
    from probing for the existence of assets in other tenants.
    """
    result = await db.execute(
        select(Asset.id).where(
            Asset.id == asset_id,
            Asset.organization_id == org_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Asset not found")


class LatestTelemetryResponse(BaseModel):
    """Either a data point, or `message` alone when the asset has none yet.

    Both shapes are legitimate -- an asset with no telemetry recorded is not an
    error -- so every data field is Optional and callers branch on their presence,
    the same way the handler's own two `return` statements already do.
    """

    message: Optional[str] = None
    asset_id: Optional[str] = None
    timestamp: Optional[str] = None
    metric_name: Optional[str] = None
    value: Optional[float] = None
    unit: Optional[str] = None
    packml_state: Optional[str] = None
    metadata: Optional[dict] = None


class TelemetryMetricsResponse(BaseModel):
    asset_id: str
    metrics: List[str]


class TelemetryHistoryItem(BaseModel):
    """Raw rows carry `packml_state`/`metadata`; aggregated buckets carry
    `min`/`max`/`count`/`aggregation` instead -- the two query paths in
    `get_telemetry_history` never populate both sets, so every field past the
    three every row has is Optional."""

    timestamp: str
    metric_name: str
    value: float
    unit: Optional[str] = None
    packml_state: Optional[str] = None
    metadata: Optional[dict] = None
    min: Optional[float] = None
    max: Optional[float] = None
    count: Optional[int] = None
    aggregation: Optional[str] = None


class TelemetryHistoryMeta(BaseModel):
    count: int
    skip: int
    limit: int
    has_more: bool
    start_time: str
    end_time: str
    newest: Optional[str] = None
    oldest: Optional[str] = None


class TelemetryHistoryResponse(BaseModel):
    items: List[TelemetryHistoryItem]
    meta: TelemetryHistoryMeta


@router.get("/{asset_id}/latest", summary="Get latest telemetry", description="Retrieve the most recent telemetry data point for a specific asset, optionally filtered by metric name. Returns 404 if the asset belongs to a different organization.", response_model=LatestTelemetryResponse, response_model_exclude_none=True)
@rate_limit("100/minute")
async def get_latest_telemetry(
    request: Request,
    asset_id: UUID,
    metric_name: Optional[str] = None,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get latest telemetry for an asset in the user's organization."""
    await _verify_asset_in_org(db, asset_id, org_id)

    query = select(Telemetry).where(Telemetry.asset_id == asset_id)

    if metric_name:
        query = query.where(Telemetry.metric_name == metric_name)

    query = query.order_by(Telemetry.time.desc()).limit(1)
    result = await db.execute(query)
    latest = result.scalar_one_or_none()

    if not latest:
        return {"message": "No telemetry data found"}

    return {
        "asset_id": str(asset_id),
        "timestamp": latest.time.isoformat(),
        "metric_name": latest.metric_name,
        "value": float(latest.value),
        "unit": latest.unit,
        "packml_state": latest.packml_state,
        "metadata": latest.meta_data,
    }


@router.get("/{asset_id}/history", summary="Get telemetry history", description="Retrieve historical telemetry data for an asset with optional time range, metric filtering, and aggregation. Defaults to last 24 hours if no time range specified. Returns 404 if the asset belongs to a different organization.", response_model=TelemetryHistoryResponse)
@rate_limit("60/minute")
async def get_telemetry_history(
    request: Request,
    asset_id: UUID,
    metric_name: Optional[str] = None,
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    aggregation: Optional[str] = Query(None, enum=["1min", "5min", "1hour"]),
    # FS-899. `skip` had no ceiling -- a value above Postgres's bigint OFFSET limit
    # reaches asyncpg and 500s where the schema promises a 4xx (the same gap
    # test_generated_input_cannot_five_hundred.py closes for in-lane routes; this file
    # is on the shared other-lanes allowlist for unrelated reasons and the check does
    # not reach it). `limit`'s ceiling is lowered from 10000 to 5000, matching
    # historian.py's raw-query ceiling: this endpoint's rows carry a JSON metadata
    # column and default to EVERY metric on the asset (no metric_name filter is
    # required), so a row here is heavier than historian's single-metric series point.
    skip: int = Query(0, ge=0, le=MAX_OFFSET),
    limit: int = Query(1000, ge=1, le=5000),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get telemetry history for an asset in the user's organization."""
    if not end_time:
        end_time = datetime.now(timezone.utc)
    if not start_time:
        start_time = end_time - timedelta(hours=24)

    await _verify_asset_in_org(db, asset_id, org_id)

    if aggregation:
        seconds = AGGREGATION_SECONDS[aggregation]
        if db.bind.dialect.name == "postgresql":
            # TimescaleDB time_bucket rollup: avg/min/max/count per bucket.
            bucket = func.time_bucket(text(f"INTERVAL '{seconds} seconds'"), Telemetry.time)
            query = (
                select(
                    bucket.label("bucket"),
                    Telemetry.metric_name,
                    func.avg(Telemetry.value).label("avg"),
                    func.min(Telemetry.value).label("min"),
                    func.max(Telemetry.value).label("max"),
                    func.count().label("count"),
                    func.max(Telemetry.unit).label("unit"),
                )
                .where(
                    Telemetry.asset_id == asset_id,
                    Telemetry.time >= start_time,
                    Telemetry.time <= end_time,
                )
                .group_by("bucket", Telemetry.metric_name)
                .order_by(text("bucket DESC"))
                .offset(skip)
                .limit(limit)
            )
            if metric_name:
                query = query.where(Telemetry.metric_name == metric_name)
            rows = (await db.execute(query)).all()
            return _history_page(
                [
                    {
                        "timestamp": r.bucket.isoformat(),
                        "metric_name": r.metric_name,
                        "value": float(r.avg),
                        "min": float(r.min),
                        "max": float(r.max),
                        "count": int(r.count),
                        "unit": r.unit,
                        "aggregation": aggregation,
                    }
                    for r in rows
                ],
                start_time, end_time, skip, limit,
            )
        # Non-Postgres dialects (tests/dev SQLite): bucket in Python.
        query = select(Telemetry).where(
            Telemetry.asset_id == asset_id,
            Telemetry.time >= start_time,
            Telemetry.time <= end_time,
        )
        if metric_name:
            query = query.where(Telemetry.metric_name == metric_name)
        raw = (await db.execute(query.order_by(Telemetry.time.desc()).limit(10000))).scalars().all()
        records = [
            {"time": t.time, "metric_name": t.metric_name,
             "value": float(t.value), "unit": t.unit}
            for t in raw
        ]
        return _history_page(
            bucket_records(records, seconds, aggregation)[skip:skip + limit],
            start_time, end_time, skip, limit,
        )

    # Raw data query
    query = select(Telemetry).where(
        Telemetry.asset_id == asset_id,
        Telemetry.time >= start_time,
        Telemetry.time <= end_time
    )

    if metric_name:
        query = query.where(Telemetry.metric_name == metric_name)

    query = query.order_by(Telemetry.time.desc()).offset(skip).limit(limit)
    result = await db.execute(query)
    telemetry_data = result.scalars().all()

    return _history_page(
        [
            {
                "timestamp": t.time.isoformat(),
                "metric_name": t.metric_name,
                "value": float(t.value),
                "unit": t.unit,
                "packml_state": t.packml_state,
                # ORM maps this as meta_data = Column("metadata", ...); `t.metadata`
                # is the SQLAlchemy MetaData object, not the row value (latent 500).
                "metadata": t.meta_data,
            }
            for t in telemetry_data
        ],
        start_time, end_time, skip, limit,
    )


@router.get("/{asset_id}/metrics", summary="List available metrics", description="Retrieve a list of all metric names that have been recorded for a specific asset. Returns 404 if the asset belongs to a different organization.", response_model=TelemetryMetricsResponse)
@rate_limit("100/minute")
async def get_available_metrics(
    request: Request,
    asset_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """List metric names for an asset in the user's organization."""
    await _verify_asset_in_org(db, asset_id, org_id)

    result = await db.execute(
        select(Telemetry.metric_name)
        .where(Telemetry.asset_id == asset_id)
        .distinct()
    )
    metrics = result.scalars().all()

    return {
        "asset_id": str(asset_id),
        "metrics": list(metrics),
    }
