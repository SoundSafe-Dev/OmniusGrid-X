"""
Actionable Registries API
Endpoints for managing actionable registries (compliance and operational)
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
from typing import List, Optional
from datetime import datetime, timedelta
import uuid

from app.db.models import (
    ActionableRegistry,
    ActionableRegistryItem,
    DataCorrelation,
    User,
    Task
)
from app.models.schemas import (
    ActionableRegistryResponse,
    ActionableRegistryCreate,
    ActionableRegistryUpdate,
    ActionableRegistryItemResponse,
    ActionableRegistryItemCreate,
    ActionableRegistryItemUpdate,
    DataCorrelationResponse,
    DataCorrelationCreate
)
from app.api.auth import require_admin_user
from app.db.database import get_db

router = APIRouter(prefix="/api/v1/registries", tags=["registries"])


# ============ Actionable Registries ============

@router.get("", response_model=List[ActionableRegistryResponse])
async def get_registries(
    registry_type: Optional[str] = None,
    is_compliance: Optional[bool] = None,
    is_active: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=0, le=1000),
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all actionable registries for the organization"""
    query = select(ActionableRegistry).where(
        ActionableRegistry.organization_id == current_user.organization_id
    )
    
    if registry_type:
        query = query.where(ActionableRegistry.registry_type == registry_type)
    if is_compliance is not None:
        query = query.where(ActionableRegistry.is_compliance == is_compliance)
    if is_active is not None:
        query = query.where(ActionableRegistry.is_active == is_active)
    
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    registries = result.scalars().all()
    
    return registries


@router.get("/{registry_id}", response_model=ActionableRegistryResponse)
async def get_registry(
    registry_id: uuid.UUID,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Get a specific actionable registry by ID"""
    result = await db.execute(
        select(ActionableRegistry).where(
            and_(
                ActionableRegistry.id == registry_id,
                ActionableRegistry.organization_id == current_user.organization_id
            )
        )
    )
    registry = result.scalar_one_or_none()
    
    if not registry:
        raise HTTPException(status_code=404, detail="Registry not found")
    
    return registry


@router.post("", response_model=ActionableRegistryResponse, status_code=201)
async def create_registry(
    registry: ActionableRegistryCreate,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new actionable registry"""
    new_registry = ActionableRegistry(
        organization_id=current_user.organization_id,
        created_by=current_user.id,
        **registry.dict()
    )
    
    db.add(new_registry)
    await db.commit()
    await db.refresh(new_registry)
    
    return new_registry


@router.put("/{registry_id}", response_model=ActionableRegistryResponse)
async def update_registry(
    registry_id: uuid.UUID,
    registry: ActionableRegistryUpdate,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Update an existing actionable registry"""
    result = await db.execute(
        select(ActionableRegistry).where(
            and_(
                ActionableRegistry.id == registry_id,
                ActionableRegistry.organization_id == current_user.organization_id
            )
        )
    )
    existing_registry = result.scalar_one_or_none()
    
    if not existing_registry:
        raise HTTPException(status_code=404, detail="Registry not found")
    
    update_data = registry.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(existing_registry, field, value)
    
    await db.commit()
    await db.refresh(existing_registry)
    
    return existing_registry


@router.delete("/{registry_id}", status_code=204)
async def delete_registry(
    registry_id: uuid.UUID,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete an actionable registry"""
    result = await db.execute(
        select(ActionableRegistry).where(
            and_(
                ActionableRegistry.id == registry_id,
                ActionableRegistry.organization_id == current_user.organization_id
            )
        )
    )
    registry = result.scalar_one_or_none()
    
    if not registry:
        raise HTTPException(status_code=404, detail="Registry not found")
    
    await db.delete(registry)
    await db.commit()


# ============ Actionable Registry Items ============

@router.get("/{registry_id}/items", response_model=List[ActionableRegistryItemResponse])
async def get_registry_items(
    registry_id: uuid.UUID,
    is_active: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=0, le=1000),
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Get all items for a specific registry"""
    # Verify registry exists and belongs to organization
    registry_result = await db.execute(
        select(ActionableRegistry).where(
            and_(
                ActionableRegistry.id == registry_id,
                ActionableRegistry.organization_id == current_user.organization_id
            )
        )
    )
    registry = registry_result.scalar_one_or_none()
    
    if not registry:
        raise HTTPException(status_code=404, detail="Registry not found")
    
    query = select(ActionableRegistryItem).where(
        ActionableRegistryItem.registry_id == registry_id
    )
    
    if is_active is not None:
        query = query.where(ActionableRegistryItem.is_active == is_active)
    
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return items


@router.post("/{registry_id}/items", response_model=ActionableRegistryItemResponse, status_code=201)
async def create_registry_item(
    registry_id: uuid.UUID,
    item: ActionableRegistryItemCreate,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new item in a registry"""
    # Verify registry exists and belongs to organization
    registry_result = await db.execute(
        select(ActionableRegistry).where(
            and_(
                ActionableRegistry.id == registry_id,
                ActionableRegistry.organization_id == current_user.organization_id
            )
        )
    )
    registry = registry_result.scalar_one_or_none()
    
    if not registry:
        raise HTTPException(status_code=404, detail="Registry not found")
    
    new_item = ActionableRegistryItem(
        registry_id=registry_id,
        **item.dict()
    )
    
    db.add(new_item)
    await db.commit()
    await db.refresh(new_item)
    
    return new_item


@router.put("/items/{item_id}", response_model=ActionableRegistryItemResponse)
async def update_registry_item(
    item_id: uuid.UUID,
    item: ActionableRegistryItemUpdate,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Update an existing registry item"""
    result = await db.execute(
        select(ActionableRegistryItem).join(ActionableRegistry).where(
            and_(
                ActionableRegistryItem.id == item_id,
                ActionableRegistry.organization_id == current_user.organization_id
            )
        )
    )
    existing_item = result.scalar_one_or_none()
    
    if not existing_item:
        raise HTTPException(status_code=404, detail="Registry item not found")
    
    update_data = item.dict(exclude_unset=True)
    for field, value in update_data.items():
        setattr(existing_item, field, value)
    
    await db.commit()
    await db.refresh(existing_item)
    
    return existing_item


@router.delete("/items/{item_id}", status_code=204)
async def delete_registry_item(
    item_id: uuid.UUID,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a registry item"""
    result = await db.execute(
        select(ActionableRegistryItem).join(ActionableRegistry).where(
            and_(
                ActionableRegistryItem.id == item_id,
                ActionableRegistry.organization_id == current_user.organization_id
            )
        )
    )
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Registry item not found")
    
    await db.delete(item)
    await db.commit()


# ============ Data Correlations ============

@router.get("/correlations", response_model=List[DataCorrelationResponse])
async def get_correlations(
    correlation_type: Optional[str] = None,
    source_type: Optional[str] = None,
    target_type: Optional[str] = None,
    is_active: Optional[bool] = None,
    skip: int = Query(0, ge=0),
    limit: int = Query(100, ge=0, le=1000),
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Get data correlations for the organization"""
    query = select(DataCorrelation).where(
        DataCorrelation.organization_id == current_user.organization_id
    )
    
    if correlation_type:
        query = query.where(DataCorrelation.correlation_type == correlation_type)
    if source_type:
        query = query.where(DataCorrelation.source_type == source_type)
    if target_type:
        query = query.where(DataCorrelation.target_type == target_type)
    if is_active is not None:
        query = query.where(DataCorrelation.is_active == is_active)
    
    query = query.offset(skip).limit(limit)
    result = await db.execute(query)
    correlations = result.scalars().all()
    
    return correlations


@router.post("/correlations", response_model=DataCorrelationResponse, status_code=201)
async def create_correlation(
    correlation: DataCorrelationCreate,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Create a new data correlation"""
    new_correlation = DataCorrelation(
        organization_id=current_user.organization_id,
        created_by=current_user.id,
        **correlation.dict()
    )
    
    db.add(new_correlation)
    await db.commit()
    await db.refresh(new_correlation)
    
    return new_correlation


@router.put("/correlations/{correlation_id}", response_model=DataCorrelationResponse)
async def update_correlation(
    correlation_id: uuid.UUID,
    correlation_strength: Optional[int] = None,
    confidence_score: Optional[int] = None,
    is_active: Optional[bool] = None,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Update an existing data correlation"""
    result = await db.execute(
        select(DataCorrelation).where(
            and_(
                DataCorrelation.id == correlation_id,
                DataCorrelation.organization_id == current_user.organization_id
            )
        )
    )
    existing_correlation = result.scalar_one_or_none()
    
    if not existing_correlation:
        raise HTTPException(status_code=404, detail="Correlation not found")
    
    if correlation_strength is not None:
        existing_correlation.correlation_strength = correlation_strength
    if confidence_score is not None:
        existing_correlation.confidence_score = confidence_score
    if is_active is not None:
        existing_correlation.is_active = is_active
    
    await db.commit()
    await db.refresh(existing_correlation)
    
    return existing_correlation


@router.delete("/correlations/{correlation_id}", status_code=204)
async def delete_correlation(
    correlation_id: uuid.UUID,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete a data correlation"""
    result = await db.execute(
        select(DataCorrelation).where(
            and_(
                DataCorrelation.id == correlation_id,
                DataCorrelation.organization_id == current_user.organization_id
            )
        )
    )
    correlation = result.scalar_one_or_none()
    
    if not correlation:
        raise HTTPException(status_code=404, detail="Correlation not found")
    
    await db.delete(correlation)
    await db.commit()


# ============ Scoring and Analytics ============

@router.get("/{registry_id}/score", response_model=dict)
async def get_registry_score(
    registry_id: uuid.UUID,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Calculate and return the compliance score for a registry"""
    # Verify registry exists and belongs to organization
    registry_result = await db.execute(
        select(ActionableRegistry).where(
            and_(
                ActionableRegistry.id == registry_id,
                ActionableRegistry.organization_id == current_user.organization_id
            )
        )
    )
    registry = registry_result.scalar_one_or_none()
    
    if not registry:
        raise HTTPException(status_code=404, detail="Registry not found")
    
    # Get all items for the registry
    items_result = await db.execute(
        select(ActionableRegistryItem).where(
            and_(
                ActionableRegistryItem.registry_id == registry_id,
                ActionableRegistryItem.is_active == True
            )
        )
    )
    items = items_result.scalars().all()
    
    if not items:
        return {
            "registry_id": str(registry_id),
            "registry_name": registry.registry_name,
            "compliance_score": 100,
            "total_items": 0,
            "completed_items": 0,
            "overdue_items": 0,
            "at_risk_items": 0
        }
    
    total_items = len(items)
    completed_items = sum(1 for item in items if item.last_completed_at)
    overdue_items = sum(1 for item in items if item.next_due_at and item.next_due_at < datetime.utcnow())
    at_risk_items = sum(1 for item in items if item.risk_score >= 70)
    
    # Calculate compliance score
    compliance_score = 0
    if total_items > 0:
        compliance_score = int((completed_items / total_items) * 100)
        # Deduct points for overdue items
        compliance_score -= int((overdue_items / total_items) * 20)
        # Deduct points for high-risk items
        compliance_score -= int((at_risk_items / total_items) * 10)
        compliance_score = max(0, min(100, compliance_score))
    
    # Update the registry with the calculated score
    registry.compliance_score = compliance_score
    await db.commit()
    
    return {
        "registry_id": str(registry_id),
        "registry_name": registry.registry_name,
        "compliance_score": compliance_score,
        "total_items": total_items,
        "completed_items": completed_items,
        "overdue_items": overdue_items,
        "at_risk_items": at_risk_items
    }


@router.post("/items/{item_id}/score", response_model=dict)
async def calculate_item_risk_score(
    item_id: uuid.UUID,
    current_user: User = Depends(require_admin_user),
    db: AsyncSession = Depends(get_db)
):
    """Calculate and update the risk score for a registry item"""
    result = await db.execute(
        select(ActionableRegistryItem).join(ActionableRegistry).where(
            and_(
                ActionableRegistryItem.id == item_id,
                ActionableRegistry.organization_id == current_user.organization_id
            )
        )
    )
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Registry item not found")
    
    # Calculate risk score based on multiple factors
    risk_score = 0
    
    # Severity contribution (0-40 points)
    severity_scores = {
        "low": 10,
        "medium": 20,
        "high": 30,
        "critical": 40
    }
    risk_score += severity_scores.get(item.severity_level, 20)
    
    # Overdue contribution (0-30 points)
    if item.next_due_at and item.next_due_at < datetime.utcnow():
        days_overdue = (datetime.utcnow() - item.next_due_at).days
        risk_score += min(30, days_overdue * 5)
    
    # Required status contribution (0-15 points)
    if item.is_required and not item.last_completed_at:
        risk_score += 15
    
    # Compliance score contribution (0-15 points, inverse)
    risk_score += max(0, 15 - (item.compliance_score / 100 * 15))
    
    risk_score = min(100, int(risk_score))
    
    # Update the item with the calculated risk score
    item.risk_score = risk_score
    await db.commit()
    
    return {
        "item_id": str(item_id),
        "item_name": item.item_name,
        "risk_score": risk_score,
        "factors": {
            "severity": severity_scores.get(item.severity_level, 20),
            "overdue": 30 if (item.next_due_at and item.next_due_at < datetime.utcnow()) else 0,
            "required": 15 if (item.is_required and not item.last_completed_at) else 0,
            "compliance": max(0, 15 - (item.compliance_score / 100 * 15))
        }
    }
