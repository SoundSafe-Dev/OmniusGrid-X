"""Assets API Routes"""

from typing import List, Optional
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import Asset, AssetType, Workcell, Organization
from app.models.schemas import (
    AssetCreate, AssetResponse, AssetUpdate,
    AssetTypeCreate, AssetTypeResponse
)

router = APIRouter()


@router.get("/", response_model=List[AssetResponse])
async def list_assets(
    organization_id: Optional[UUID] = None,
    workcell_id: Optional[UUID] = None,
    asset_type_id: Optional[UUID] = None,
    is_active: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=1, le=1000),
    db: AsyncSession = Depends(get_db)
):
    """List assets with optional filtering"""
    query = select(Asset)
    
    if organization_id:
        query = query.where(Asset.organization_id == organization_id)
    if workcell_id:
        query = query.where(Asset.workcell_id == workcell_id)
    if asset_type_id:
        query = query.where(Asset.asset_type_id == asset_type_id)
    if is_active is not None:
        query = query.where(Asset.is_active == is_active)
    
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    assets = result.scalars().all()
    
    return assets


@router.get("/{asset_id}", response_model=AssetResponse)
async def get_asset(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get a single asset by ID"""
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    return asset


@router.post("/", response_model=AssetResponse)
async def create_asset(
    asset_data: AssetCreate,
    db: AsyncSession = Depends(get_db)
):
    """Create a new asset"""
    # Verify asset type exists
    result = await db.execute(
        select(AssetType).where(AssetType.id == asset_data.asset_type_id)
    )
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="Asset type not found")
    
    # Create asset
    asset = Asset(**asset_data.model_dump())
    db.add(asset)
    await db.commit()
    await db.refresh(asset)
    
    return asset


@router.put("/{asset_id}", response_model=AssetResponse)
async def update_asset(
    asset_id: UUID,
    asset_data: AssetUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update an existing asset"""
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    # Update fields
    update_data = asset_data.model_dump(exclude_unset=True)
    for field, value in update_data.items():
        setattr(asset, field, value)
    
    await db.commit()
    await db.refresh(asset)
    
    return asset


@router.delete("/{asset_id}")
async def delete_asset(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Delete an asset (soft delete by deactivating)"""
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
    )
    asset = result.scalar_one_or_none()
    
    if not asset:
        raise HTTPException(status_code=404, detail="Asset not found")
    
    asset.is_active = False
    await db.commit()
    
    return {"message": "Asset deactivated successfully"}


@router.get("/types/", response_model=List[AssetTypeResponse])
async def list_asset_types(
    category: Optional[str] = None,
    db: AsyncSession = Depends(get_db)
):
    """List asset types"""
    query = select(AssetType)
    
    if category:
        query = query.where(AssetType.category == category)
    
    result = await db.execute(query)
    return result.scalars().all()


@router.get("/{asset_id}/status")
async def get_asset_status(
    asset_id: UUID,
    db: AsyncSession = Depends(get_db)
):
    """Get current asset status including PackML state"""
    result = await db.execute(
        select(Asset).where(Asset.id == asset_id)
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
        "connection_config": asset.connection_config
    }
