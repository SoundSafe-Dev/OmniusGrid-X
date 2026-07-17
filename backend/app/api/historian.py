"""Tenant-scoped time-series historian queries."""

import time
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from prometheus_client import Counter, Histogram
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id


router = APIRouter()

# Prometheus metrics (scraped via /metrics in app/api/health.py). Granularity
# is a closed 4-value enum, so it is safe as a label; ids/metric names are not.
HISTORIAN_QUERIES_TOTAL = Counter(
    "opsgrid_historian_queries_total",
    "Historian queries served",
    ["granularity"],
)

HISTORIAN_QUERY_DURATION = Histogram(
    "opsgrid_historian_query_duration_seconds",
    "Historian query latency",
    ["granularity"],
    buckets=[0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0],
)

HISTORIAN_ROWS_RETURNED = Histogram(
    "opsgrid_historian_rows_returned",
    "Rows returned per historian query",
    buckets=[0, 1, 10, 50, 100, 500, 1000, 2500, 5000],
)


class HistorianGranularity(str, Enum):
    raw = "raw"
    minute = "1m"
    hour = "1h"
    day = "1d"


class HistorianPoint(BaseModel):
    timestamp: datetime
    average: float
    minimum: float
    maximum: float
    sample_count: int


class HistorianQueryResponse(BaseModel):
    asset_id: UUID
    metric: str
    granularity: HistorianGranularity
    start: datetime
    end: datetime
    effective_start: datetime
    offset: int
    limit: int
    count: int
    has_more: bool
    points: list[HistorianPoint]


_DEFAULT_RETENTION_DAYS = {
    HistorianGranularity.raw: 30,
    HistorianGranularity.minute: 365,
    HistorianGranularity.hour: 1825,
    HistorianGranularity.day: 1825,
}

_RETENTION_COLUMN = {
    HistorianGranularity.raw: "hot_retention_days",
    HistorianGranularity.minute: "warm_retention_days",
    HistorianGranularity.hour: "cold_retention_days",
    HistorianGranularity.day: "cold_retention_days",
}

_RAW_QUERY = text(
    """
    SELECT
        telemetry.time AS timestamp,
        telemetry.value AS average,
        telemetry.value AS minimum,
        telemetry.value AS maximum,
        CAST(1 AS BIGINT) AS sample_count
    FROM telemetry
    JOIN assets ON assets.id = telemetry.asset_id
    WHERE assets.organization_id = :organization_id
      AND telemetry.asset_id = :asset_id
      AND telemetry.metric_name = :metric
      AND telemetry.time >= :start_time
      AND telemetry.time < :end_time
    ORDER BY telemetry.time ASC
    LIMIT :fetch_limit
    OFFSET :offset_rows
    """
)


def _rollup_query(view_name: str):
    return text(
        f"""
        SELECT
            rollup.time AS timestamp,
            rollup.avg_value AS average,
            rollup.min_value AS minimum,
            rollup.max_value AS maximum,
            rollup.sample_count AS sample_count
        FROM {view_name} AS rollup
        JOIN assets ON assets.id = rollup.asset_id
        WHERE assets.organization_id = :organization_id
          AND rollup.asset_id = :asset_id
          AND rollup.metric_name = :metric
          AND rollup.time >= :start_time
          AND rollup.time < :end_time
        ORDER BY rollup.time ASC
        LIMIT :fetch_limit
        OFFSET :offset_rows
        """
    )


_POINT_QUERIES = {
    HistorianGranularity.raw: _RAW_QUERY,
    HistorianGranularity.minute: _rollup_query("telemetry_1min"),
    HistorianGranularity.hour: _rollup_query("telemetry_1hour"),
    HistorianGranularity.day: _rollup_query("telemetry_1day"),
}


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


async def _verify_asset(
    db: AsyncSession,
    asset_id: UUID,
    organization_id: UUID,
) -> None:
    result = await db.execute(
        select(Asset.id).where(
            Asset.id == asset_id,
            Asset.organization_id == organization_id,
        )
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Asset not found")


async def _retention_days(
    db: AsyncSession,
    organization_id: UUID,
    metric: str,
    granularity: HistorianGranularity,
) -> int:
    column_name = _RETENTION_COLUMN[granularity]
    result = await db.execute(
        text(
            f"""
            SELECT {column_name} AS retention_days
            FROM historian_retention_policies
            WHERE organization_id = :organization_id
              AND metric_name IN ('*', :metric)
            ORDER BY CASE WHEN metric_name = :metric THEN 0 ELSE 1 END
            LIMIT 1
            """
        ),
        {"organization_id": str(organization_id), "metric": metric},
    )
    value = result.scalar_one_or_none()
    return int(value) if value is not None else _DEFAULT_RETENTION_DAYS[granularity]


def _point(row: dict[str, Any]) -> HistorianPoint:
    return HistorianPoint(
        timestamp=row["timestamp"],
        average=float(row["average"]),
        minimum=float(row["minimum"]),
        maximum=float(row["maximum"]),
        sample_count=int(row["sample_count"]),
    )


@router.get("/query", response_model=HistorianQueryResponse)
async def query_historian(
    asset_id: UUID,
    metric: str = Query(min_length=1, max_length=100),
    start: datetime = Query(),
    end: datetime = Query(),
    granularity: HistorianGranularity = Query(HistorianGranularity.raw),
    offset: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=5000),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
) -> HistorianQueryResponse:
    """Return a tenant-owned metric series at the requested resolution."""
    started = time.perf_counter()
    start_utc = _utc(start)
    end_utc = _utc(end)
    if start_utc >= end_utc:
        raise HTTPException(status_code=422, detail="start must be before end")

    await _verify_asset(db, asset_id, organization_id)

    retention_days = await _retention_days(
        db, organization_id, metric, granularity
    )
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    effective_start = max(start_utc, cutoff)

    rows: list[dict[str, Any]] = []
    if effective_start < end_utc:
        result = await db.execute(
            _POINT_QUERIES[granularity],
            {
                "organization_id": str(organization_id),
                "asset_id": str(asset_id),
                "metric": metric,
                "start_time": effective_start,
                "end_time": end_utc,
                "offset_rows": offset,
                "fetch_limit": limit + 1,
            },
        )
        rows = [dict(row) for row in result.mappings().all()]

    has_more = len(rows) > limit
    points = [_point(row) for row in rows[:limit]]
    try:  # metrics must never break the query path
        HISTORIAN_QUERIES_TOTAL.labels(granularity=granularity.value).inc()
        HISTORIAN_QUERY_DURATION.labels(granularity=granularity.value).observe(
            time.perf_counter() - started
        )
        HISTORIAN_ROWS_RETURNED.observe(len(points))
    except Exception:  # pragma: no cover - defensive
        pass
    return HistorianQueryResponse(
        asset_id=asset_id,
        metric=metric,
        granularity=granularity,
        start=start_utc,
        end=end_utc,
        effective_start=effective_start,
        offset=offset,
        limit=limit,
        count=len(points),
        has_more=has_more,
        points=points,
    )
