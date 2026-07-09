"""Platform data as correlation sources (correlation foundation).

Makes live platform data — asset/sensor telemetry, yard, transportation — usable
as inputs to the AI correlation engine and analysis sessions, *without* touching
the correlation engine itself (owned on the gemma-correlation-ai branch).

The mechanism: the engine derives domains + shared keys from each source's
``processed_data`` shaped like a one-tab spreadsheet (``tabs[].column_names`` +
``sample_data`` + explicit ``shared_keys``). Each provider here queries a domain
and returns records + columns in that shape; the router (app/api/platform_correlation.py)
stores them as a ``SessionDataSource`` row, which then appears in DataSourcesPanel
and flows through ``correlate_session`` unchanged.

Providers are async ``(db, organization_id, params) -> ProviderResult``.
"""

from dataclasses import dataclass
from typing import Any, Awaitable, Callable, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Asset, Shipment, Telemetry, YardTrailer


@dataclass
class ProviderResult:
    file_name: str
    records: List[Dict[str, Any]]
    columns: List[str]
    shared_keys: List[str]

    def to_processed_data(self) -> Dict[str, Any]:
        """Shape as the engine's one-tab 'spreadsheet' so domains + keys resolve."""
        return {
            "shared_keys": self.shared_keys,
            "tabs": [{
                "name": self.file_name,
                "column_names": self.columns,
                "sample_data": self.records[:200],  # cap the descriptor sample
                "row_count": len(self.records),
            }],
            "row_count": len(self.records),
        }


def _columns(records: List[Dict[str, Any]]) -> List[str]:
    cols: List[str] = []
    for r in records:
        for k in r:
            if k not in cols:
                cols.append(k)
    return cols


def telemetry_rows_to_records(rows: List[Any], asset: Optional[Any] = None) -> List[Dict[str, Any]]:
    """Shape Telemetry ORM rows (+ optional Asset context) into correlatable records.

    Including asset name + sensor_class means audio/video/machinery modality is a
    first-class correlation dimension (e.g. "does high audio_band_high coincide
    with late shipments from dock 3?").
    """
    asset_name = getattr(asset, "name", None)
    sensor_class = getattr(asset, "sensor_class", None)
    if asset is not None and not sensor_class:
        atype = getattr(asset, "asset_type", None)
        sensor_class = getattr(atype, "sensor_class", None)
    return [{
        "asset_id": r.asset_id,
        "asset_name": asset_name,
        "sensor_class": sensor_class,
        "metric_name": r.metric_name,
        "value": float(r.value) if r.value is not None else None,
        "unit": r.unit,
        "packml_state": r.packml_state,
        "time": r.time.isoformat() if r.time else None,
    } for r in rows]


async def asset_telemetry_provider(db: AsyncSession, organization_id: str, params: Dict[str, Any]) -> ProviderResult:
    """Recent telemetry rows for one asset (audio/video/machinery sensors included)."""
    asset_id = params.get("asset_id")
    if not asset_id:
        raise ValueError("asset_telemetry requires params.asset_id")
    limit = int(params.get("limit", 500))
    asset = (await db.execute(
        select(Asset).where(Asset.id == str(asset_id))
    )).scalar_one_or_none()
    rows = (await db.execute(
        select(Telemetry).where(Telemetry.asset_id == str(asset_id))
        .order_by(Telemetry.time.desc()).limit(limit)
    )).scalars().all()
    records = telemetry_rows_to_records(rows, asset)
    name = params.get("name") or f"telemetry-{getattr(asset, 'name', None) or asset_id}"
    return ProviderResult(name, records, _columns(records),
                          ["asset_id", "asset_name", "metric_name", "time"])


async def yard_provider(db: AsyncSession, organization_id: str, params: Dict[str, Any]) -> ProviderResult:
    """Current yard trailer inventory as correlatable records."""
    rows = (await db.execute(
        select(YardTrailer).where(YardTrailer.organization_id == organization_id).limit(500)
    )).scalars().all()
    records = [{
        "trailer_number": t.trailer_number,
        "carrier_id": str(t.carrier_id) if t.carrier_id else None,
        "status": t.status,
        "dock_door_id": str(t.dock_door_id) if t.dock_door_id else None,
        "shipment_id": str(t.shipment_id) if t.shipment_id else None,
        "check_in_at": t.check_in_at.isoformat() if t.check_in_at else None,
    } for t in rows]
    return ProviderResult("yard-inventory", records, _columns(records),
                          ["trailer_number", "shipment_id", "carrier_id"])


async def transportation_provider(db: AsyncSession, organization_id: str, params: Dict[str, Any]) -> ProviderResult:
    """Shipments as correlatable records."""
    rows = (await db.execute(
        select(Shipment).where(Shipment.organization_id == organization_id).limit(500)
    )).scalars().all()
    records = [{
        "shipment_number": s.shipment_number,
        "carrier_id": str(s.carrier_id) if s.carrier_id else None,
        "driver_id": str(s.driver_id) if s.driver_id else None,
        "origin": s.origin,
        "destination": s.destination,
        "status": s.status,
        "scheduled_delivery": s.scheduled_delivery.isoformat() if s.scheduled_delivery else None,
    } for s in rows]
    return ProviderResult("shipments", records, _columns(records),
                          ["shipment_number", "carrier_id", "driver_id"])


ProviderFn = Callable[[AsyncSession, str, Dict[str, Any]], Awaitable[ProviderResult]]

# source_type -> (provider, human label). New domains register here.
_PROVIDERS: Dict[str, tuple] = {
    "asset_telemetry": (asset_telemetry_provider, "Asset / sensor telemetry"),
    "yard": (yard_provider, "Yard inventory"),
    "transportation": (transportation_provider, "Shipments"),
}


def available_source_types() -> List[Dict[str, str]]:
    return [{"source_type": k, "label": label} for k, (_, label) in _PROVIDERS.items()]


def get_provider(source_type: str) -> Optional[ProviderFn]:
    entry = _PROVIDERS.get(source_type)
    return entry[0] if entry else None
