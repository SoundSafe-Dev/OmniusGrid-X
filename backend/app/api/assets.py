"""Assets API Routes.

All endpoints scope queries to the authenticated user's organization
via :func:`app.core.tenant.get_tenant_org_id`. Cross-tenant access
returns 404 (not 403) to avoid leaking existence of resources in other
organizations.
"""

from types import SimpleNamespace
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.middleware.tenant_isolation import get_tenant_org_id, get_tenant_db
from app.db.database import get_db
from app.db.models import Asset, AssetType, Workcell, Organization, User
from app.api.auth import get_current_active_user
from app.core.pagination import MAX_OFFSET, PaginatedResponse, paginate
from app.middleware.rbac import require_admin
from app.middleware.rate_limit import rate_limit
from app.core.tenant import get_tenant_db
from app.models.schemas import (
    AssetCreate, AssetResponse, AssetUpdate,
    AssetTypeCreate, AssetTypeResponse
)

router = APIRouter(dependencies=[Depends(get_current_active_user)])


class AssetDeactivated(BaseModel):
    """A SOFT delete — the handler sets `is_active = False` and the message says
    "deactivated" rather than "deleted", which is the honest word for it."""

    message: str


class AssetStatusOut(BaseModel):
    asset_id: str
    name: str
    #: Nullable until the asset has reported a state.
    current_packml_state: Optional[str] = None
    is_active: Optional[bool] = None
    last_seen: Optional[str] = None
    #: `assets.connection_config` is a JSON column owned by whatever provisioned the
    #: asset — protocol, host, port, credentials reference. Left open.
    connection_config: Optional[Dict[str, Any]] = None


class SensorFeedConsumers(BaseModel):
    """Not data — the two call templates a downstream consumer needs to read these feeds.
    Documented because they are part of what this discovery endpoint exists to hand out."""

    correlation: str
    history: str


class SensorFeedsOut(BaseModel):
    asset_id: str
    name: str
    #: Falls back to `"generic"` when neither the asset nor its type declares one.
    sensor_class: str
    media_config: Dict[str, Any] = Field(default_factory=dict)
    #: The metric names this asset has actually emitted, from `telemetry` — not a
    #: catalogue of what it could emit.
    metrics: List[str] = Field(default_factory=list)
    consumers: SensorFeedConsumers


@router.get("/", response_model=PaginatedResponse[AssetResponse], summary="List all assets", description="Retrieve a paginated list of manufacturing assets in the authenticated user's organization, with optional filtering by workcell, asset type, and active status. Returns a {items, meta} envelope with the true total count.")
@rate_limit("100/minute")
async def list_assets(
    request: Request,
    workcell_id: Optional[UUID] = None,
    asset_type_id: Optional[UUID] = None,
    is_active: Optional[bool] = None,
    skip: int = Query(0, ge=0, le=MAX_OFFSET),
    limit: int = Query(100, ge=1, le=1000),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """List assets within the authenticated user's organization."""
    # ORDERED so the cap and the offset mean something (FS-429). Without an ORDER BY,
    # Postgres may return any rows it likes and different ones next time, so a paged
    # list can repeat rows on page 2 and skip others entirely.
    query = select(Asset).order_by(Asset.name).where(Asset.organization_id == org_id)

    if workcell_id:
        query = query.where(Asset.workcell_id == workcell_id)
    if asset_type_id:
        query = query.where(Asset.asset_type_id == asset_type_id)
    if is_active is not None:
        query = query.where(Asset.is_active == is_active)

    total = (
        await db.execute(select(func.count()).select_from(query.subquery()))
    ).scalar_one()
    result = await db.execute(query.offset(skip).limit(limit))
    return paginate(result.scalars().all(), total, SimpleNamespace(skip=skip, limit=limit))


@router.get("/{asset_id}", response_model=AssetResponse, summary="Get asset details", description="Retrieve detailed information about a specific asset including its configuration, PackML state, and connection settings. Returns 404 if the asset belongs to a different organization.")
@rate_limit("100/minute")
async def get_asset(
    request: Request,
    asset_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get a single asset by ID, scoped to the user's organization."""
    result = await db.execute(
        select(Asset).where(
            Asset.id == asset_id,
            Asset.organization_id == org_id,
        )
    )
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    return asset


@router.post("/", response_model=AssetResponse, summary="Create a new asset", description="Register a new manufacturing asset in the authenticated user's organization. The organization is derived from the JWT — any client-supplied organization_id in the request body is ignored.", dependencies=[Depends(require_admin)])
@rate_limit("30/minute")
async def create_asset(
    request: Request,
    asset_data: AssetCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Create a new asset in the authenticated user's organization."""
    result = await db.execute(
        select(AssetType).where(AssetType.id == asset_data.asset_type_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Asset type not found")
    workcell = (
        await db.execute(
            select(Workcell).where(
                Workcell.id == asset_data.workcell_id,
                Workcell.organization_id == org_id,
            )
        )
    ).scalar_one_or_none()
    if workcell is None:
        raise HTTPException(status_code=404, detail="Workcell not found")

    # Server-side override: ignore any client-supplied organization_id and
    # bind the new asset to the authenticated user's organization.
    payload = asset_data.model_dump()
    payload["organization_id"] = org_id
    asset = Asset(**payload)

    db.add(asset)
    await db.commit()

    return asset


@router.put("/{asset_id}", response_model=AssetResponse, summary="Update asset", description="Modify an existing asset's configuration. Only provided fields will be updated (partial update). Returns 404 if the asset belongs to a different organization.", dependencies=[Depends(require_admin)])
@rate_limit("30/minute")
async def update_asset(
    request: Request,
    asset_id: UUID,
    asset_data: AssetUpdate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Update an asset within the authenticated user's organization."""
    result = await db.execute(
        select(Asset).where(
            Asset.id == asset_id,
            Asset.organization_id == org_id,
        )
    )
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    update_data = asset_data.model_dump(exclude_unset=True)
    if "workcell_id" in update_data:
        workcell = (
            await db.execute(
                select(Workcell).where(
                    Workcell.id == update_data["workcell_id"],
                    Workcell.organization_id == org_id,
                )
            )
        ).scalar_one_or_none()
        if workcell is None:
            raise HTTPException(status_code=404, detail="Workcell not found")
    for field, value in update_data.items():
        setattr(asset, field, value)

    await db.commit()

    return asset


@router.delete("/{asset_id}", response_model=AssetDeactivated, summary="Deactivate asset", description="Soft delete an asset by setting its active status to false. Returns 404 if the asset belongs to a different organization.", dependencies=[Depends(require_admin)])
@rate_limit("30/minute")
async def delete_asset(
    request: Request,
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Deactivate an asset within the authenticated user's organization."""
    result = await db.execute(
        select(Asset).where(
            Asset.id == asset_id,
            Asset.organization_id == org_id,
        )
    )
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    asset.is_active = False
    await db.commit()

    return {"message": "Asset deactivated successfully"}


@router.get("/types/", response_model=List[AssetTypeResponse], summary="List asset types", description="Retrieve all available asset types with optional filtering by category (e.g., 3d_printer, cnc, robot). Asset types are a global catalog and are not tenant-scoped.")
@rate_limit("100/minute")
async def list_asset_types(
    request: Request,
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """List asset types (global catalog, not tenant-scoped)."""
    query = select(AssetType)

    if category:
        query = query.where(AssetType.category == category)

    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{asset_id}/status", response_model=AssetStatusOut, summary="Get asset status", description="Retrieve the current operational status of an asset including PackML state, active status, last seen timestamp, and connection configuration. Returns 404 if the asset belongs to a different organization.")
@rate_limit("100/minute")
async def get_asset_status(
    request: Request,
    asset_id: UUID,
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get asset status, scoped to the user's organization."""
    result = await db.execute(
        select(Asset).where(
            Asset.id == asset_id,
            Asset.organization_id == org_id,
        )
    )
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    return {
        "asset_id": str(asset.id),
        "name": asset.name,
        "current_packml_state": asset.current_packml_state,
        "is_active": asset.is_active,
        "last_seen": asset.last_seen.isoformat() if asset.last_seen else None,
        "connection_config": asset.connection_config,
    }


@router.get(
    "/{asset_id}/sensor-feeds",
    response_model=SensorFeedsOut,
    summary="Get sensor feed summary",
    description="Discovery surface for downstream consumers (correlation, predictive "
                "maintenance, simulation/growth planning): the asset's sensor class, "
                "media config, and the metric names it actually emits.",
)
async def get_sensor_feeds(
    asset_id: UUID,
    db: AsyncSession = Depends(get_tenant_db),
    current_user: User = Depends(get_current_active_user),
):
    """Summarize what this asset's sensors feed into the platform (task B16)."""
    from app.db.models import Telemetry

    result = await db.execute(select(Asset).where(Asset.id == asset_id))
    asset = result.scalar_one_or_none()
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")

    sensor_class = asset.sensor_class
    if not sensor_class and asset.asset_type_id:
        atype = (await db.execute(
            select(AssetType).where(AssetType.id == asset.asset_type_id)
        )).scalar_one_or_none()
        sensor_class = getattr(atype, "sensor_class", None)

    metrics = (await db.execute(
        select(Telemetry.metric_name).where(Telemetry.asset_id == str(asset_id)).distinct()
    )).scalars().all()

    return {
        "asset_id": str(asset.id),
        "name": asset.name,
        "sensor_class": sensor_class or "generic",
        "media_config": asset.media_config or {},
        "metrics": sorted(metrics),
        # How to consume these feeds elsewhere in the platform.
        "consumers": {
            "correlation": "POST /api/v1/nlp/sessions/{session_id}/platform-data "
                           "{source_type: 'asset_telemetry', params: {asset_id}}",
            "history": f"GET /api/v1/telemetry/{asset_id}/history?aggregation=5min",
        },
    }
