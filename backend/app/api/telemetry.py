"""Telemetry API Routes"""

from typing import List, Optional
from uuid import UUID
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select, func, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Telemetry, Asset, PackMLState

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


@router.get("/{asset_id}/latest", summary="Get latest telemetry", description="Retrieve the most recent telemetry data point for a specific asset, optionally filtered by metric name.")
async def get_latest_telemetry(
    asset_id: UUID,
    metric_name: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """Get latest telemetry for an asset"""
    # Verify asset exists
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Build query
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
        "metadata": latest.metadata
    }


@router.get("/{asset_id}/history", summary="Get telemetry history", description="Retrieve historical telemetry data for an asset with optional time range, metric filtering, and aggregation. Defaults to last 24 hours if no time range specified.")
async def get_telemetry_history(
    asset_id: UUID,
    metric_name: Optional[str] = None,
    start_time: Optional[datetime] = Query(None),
    end_time: Optional[datetime] = Query(None),
    aggregation: Optional[str] = Query(None, enum=["1min", "5min", "1hour"]),
    skip: int = Query(0, ge=0),
    limit: int = Query(1000, ge=1, le=10000),
    db: AsyncSession = Depends(get_db)
):
    """Get telemetry history for an asset"""
    # Set default time range if not provided
    if not end_time:
        end_time = datetime.utcnow()
    if not start_time:
        start_time = end_time - timedelta(hours=24)
    
    # Verify asset exists
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Asset not found")
    
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
            return [
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
            ]
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
        return bucket_records(records, seconds, aggregation)[skip:skip + limit]

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

    return [
        {
            "timestamp": t.time.isoformat(),
            "metric_name": t.metric_name,
            "value": float(t.value),
            "unit": t.unit,
            "packml_state": t.packml_state,
            "metadata": t.metadata
        }
        for t in telemetry_data
    ]


@router.get("/{asset_id}/metrics", summary="List available metrics", description="Retrieve a list of all metric names that have been recorded for a specific asset.")
async def get_available_metrics(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get list of available metrics for an asset"""
    result = await db.execute(
        select(Telemetry.metric_name)
        .where(Telemetry.asset_id == asset_id)
        .distinct()
    )
    metrics = result.scalars().all()
    
    return {
        "asset_id": str(asset_id),
        "metrics": list(metrics)
    }
