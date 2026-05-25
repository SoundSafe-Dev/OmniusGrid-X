"""Data Residency Controls (USA) API Endpoints"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User, DataResidencyTag
from app.api.auth import get_current_active_user
from app.middleware.rbac import require_admin
from app.middleware.rate_limit import rate_limit
import structlog

logger = structlog.get_logger()

router = APIRouter()

# Default region for USA compliance
DEFAULT_REGION = "USA"


@router.post("/tag", summary="Tag record with residency", description="Tag a database record with its data residency region.")
@rate_limit("100/minute")
async def tag_record_residency(
    request: Request,
    table_name: str,
    record_id: str,
    region: str = DEFAULT_REGION,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Tag a record with data residency information"""
    # Validate region (only USA allowed for now)
    if region != "USA":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Region '{region}' not supported. Only 'USA' is currently supported."
        )
    
    # Check if tag already exists
    result = await db.execute(
        select(DataResidencyTag).where(
            and_(
                DataResidencyTag.table_name == table_name,
                DataResidencyTag.record_id == record_id
            )
        )
    )
    existing_tag = result.scalar_one_or_none()
    
    if existing_tag:
        # Update existing tag
        existing_tag.region = region
        existing_tag.tagged_by = current_user.id
        existing_tag.tagged_at = datetime.utcnow()
        await db.commit()
        
        logger.info(
            "data_residency_tag_updated",
            table_name=table_name,
            record_id=record_id,
            region=region
        )
        
        return {"message": "Data residency tag updated successfully"}
    
    # Create new tag
    tag = DataResidencyTag(
        table_name=table_name,
        record_id=record_id,
        region=region,
        tagged_by=current_user.id
    )
    
    db.add(tag)
    await db.commit()
    
    logger.info(
        "data_residency_tag_created",
        table_name=table_name,
        record_id=record_id,
        region=region
    )
    
    return {"message": "Data residency tag created successfully"}


@router.get("/tag/{table_name}/{record_id}", summary="Get record residency", description="Get the data residency tag for a specific record.")
@rate_limit("100/minute")
async def get_record_residency(
    request: Request,
    table_name: str,
    record_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get data residency tag for a record"""
    result = await db.execute(
        select(DataResidencyTag).where(
            and_(
                DataResidencyTag.table_name == table_name,
                DataResidencyTag.record_id == record_id
            )
        )
    )
    tag = result.scalar_one_or_none()
    
    if not tag:
        return {
            "table_name": table_name,
            "record_id": record_id,
            "tagged": False,
            "region": None
        }
    
    return {
        "table_name": table_name,
        "record_id": record_id,
        "tagged": True,
        "region": tag.region,
        "tagged_at": tag.tagged_at.isoformat() if tag.tagged_at else None,
        "tagged_by": str(tag.tagged_by) if tag.tagged_by else None
    }


@router.get("/tags", summary="List residency tags", description="List all data residency tags, optionally filtered by table or region.")
@rate_limit("100/minute")
async def list_residency_tags(
    request: Request,
    table_name: Optional[str] = None,
    region: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """List data residency tags"""
    query = select(DataResidencyTag)
    
    if table_name:
        query = query.where(DataResidencyTag.table_name == table_name)
    
    if region:
        query = query.where(DataResidencyTag.region == region)
    
    result = await db.execute(query.order_by(DataResidencyTag.tagged_at.desc()))
    tags = result.scalars().all()
    
    tag_list = [
        {
            "id": str(tag.id),
            "table_name": tag.table_name,
            "record_id": tag.record_id,
            "region": tag.region,
            "tagged_at": tag.tagged_at.isoformat() if tag.tagged_at else None,
            "tagged_by": str(tag.tagged_by) if tag.tagged_by else None
        }
        for tag in tags
    ]
    
    return {"items": tag_list, "total": len(tag_list)}


@router.delete("/tag/{table_name}/{record_id}", summary="Remove residency tag", description="Remove a data residency tag from a record.")
@rate_limit("10/minute")
@require_admin()
async def remove_residency_tag(
    request: Request,
    table_name: str,
    record_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Remove data residency tag"""
    result = await db.execute(
        select(DataResidencyTag).where(
            and_(
                DataResidencyTag.table_name == table_name,
                DataResidencyTag.record_id == record_id
            )
        )
    )
    tag = result.scalar_one_or_none()
    
    if not tag:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Data residency tag not found"
        )
    
    await db.delete(tag)
    await db.commit()
    
    logger.info(
        "data_residency_tag_removed",
        table_name=table_name,
        record_id=record_id
    )
    
    return {"message": "Data residency tag removed successfully"}


@router.get("/summary", summary="Get residency summary", description="Get a summary of data residency across all tables.")
@rate_limit("100/minute")
async def get_residency_summary(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get data residency summary"""
    result = await db.execute(select(DataResidencyTag))
    tags = result.scalars().all()
    
    summary = {
        "total_tags": len(tags),
        "by_region": {},
        "by_table": {}
    }
    
    for tag in tags:
        # Count by region
        summary["by_region"][tag.region] = summary["by_region"].get(tag.region, 0) + 1
        
        # Count by table
        summary["by_table"][tag.table_name] = summary["by_table"].get(tag.table_name, 0) + 1
    
    return summary


@router.post("/validate", summary="Validate data residency", description="Validate that all data in specified tables is tagged with correct residency.")
@rate_limit("10/minute")
@require_admin()
async def validate_data_residency(
    request: Request,
    table_names: List[str],
    expected_region: str = DEFAULT_REGION,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Validate data residency for specified tables"""
    validation_results = {
        "expected_region": expected_region,
        "tables": {},
        "total_records": 0,
        "tagged_records": 0,
        "untagged_records": 0,
        "compliance_percentage": 0.0
    }
    
    for table_name in table_names:
        # Get all tags for this table
        result = await db.execute(
            select(DataResidencyTag).where(DataResidencyTag.table_name == table_name)
        )
        tags = result.scalars().all()
        
        # Count tagged records with correct region
        correct_tags = [t for t in tags if t.region == expected_region]
        
        # Note: This is a simplified validation. In production, you would need to
        # query the actual table to get the total record count and compare.
        # For now, we just report what we have tagged.
        
        validation_results["tables"][table_name] = {
            "tagged_count": len(tags),
            "correct_region_count": len(correct_tags),
            "incorrect_region_count": len(tags) - len(correct_tags)
        }
        
        validation_results["tagged_records"] += len(tags)
    
    validation_results["total_records"] = validation_results["tagged_records"]
    
    # Calculate compliance percentage
    if validation_results["total_records"] > 0:
        correct_region_total = sum(
            t["correct_region_count"] for t in validation_results["tables"].values()
        )
        validation_results["compliance_percentage"] = (
            correct_region_total / validation_results["total_records"]
        ) * 100
    
    logger.info(
        "data_residency_validation",
        table_names=table_names,
        expected_region=expected_region,
        compliance_percentage=validation_results["compliance_percentage"]
    )
    
    return validation_results
