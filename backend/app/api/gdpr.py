"""GDPR Compliance API Endpoints"""

from datetime import datetime
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select, and_, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import get_db
from app.db.models import User, ConsentRecord, DataProcessingRecord
from app.api.auth import get_current_active_user
from app.middleware.rbac import require_admin
from app.middleware.rate_limit import rate_limit
import structlog

logger = structlog.get_logger()

router = APIRouter()


@router.post("/consent", summary="Record consent", description="Record user consent for data processing activities.")
@rate_limit("100/minute")
async def record_consent(
    request: Request,
    consent_type: str,
    consent_given: bool,
    consent_method: str = "checkbox",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Record user consent"""
    # Validate consent type
    valid_types = ["data_processing", "marketing", "analytics"]
    if consent_type not in valid_types:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid consent type. Valid types: {valid_types}"
        )
    
    # Create consent record
    consent_record = ConsentRecord(
        user_id=current_user.id,
        consent_type=consent_type,
        consent_given=consent_given,
        consent_method=consent_method,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("user-agent")
    )
    
    db.add(consent_record)
    await db.commit()
    
    logger.info(
        "consent_recorded",
        user_id=str(current_user.id),
        consent_type=consent_type,
        consent_given=consent_given
    )
    
    return {"message": "Consent recorded successfully"}


@router.get("/consent", summary="Get user consents", description="Get all consent records for the current user.")
@rate_limit("100/minute")
async def get_user_consents(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get user's consent records"""
    result = await db.execute(
        select(ConsentRecord).where(ConsentRecord.user_id == current_user.id)
    )
    consents = result.scalars().all()
    
    consent_list = [
        {
            "id": str(consent.id),
            "consent_type": consent.consent_type,
            "consent_given": consent.consent_given,
            "consent_date": consent.consent_date.isoformat() if consent.consent_date else None,
            "consent_method": consent.consent_method,
            "withdrawn_at": consent.withdrawn_at.isoformat() if consent.withdrawn_at else None
        }
        for consent in consents
    ]
    
    return {"items": consent_list, "total": len(consent_list)}


@router.put("/consent/{consent_id}/withdraw", summary="Withdraw consent", description="Withdraw previously given consent.")
@rate_limit("100/minute")
async def withdraw_consent(
    request: Request,
    consent_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Withdraw consent"""
    result = await db.execute(
        select(ConsentRecord).where(
            and_(
                ConsentRecord.id == consent_id,
                ConsentRecord.user_id == current_user.id
            )
        )
    )
    consent = result.scalar_one_or_none()
    
    if not consent:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Consent record not found"
        )
    
    consent.consent_given = False
    consent.withdrawn_at = datetime.utcnow()
    
    await db.commit()
    
    logger.info(
        "consent_withdrawn",
        consent_id=consent_id,
        user_id=str(current_user.id)
    )
    
    return {"message": "Consent withdrawn successfully"}


@router.get("/data-export", summary="Export user data", description="Export all user data in machine-readable format (GDPR data portability).")
@rate_limit("10/hour")
async def export_user_data(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Export all user data for GDPR data portability"""
    user_data = {
        "user": {
            "id": str(current_user.id),
            "email": current_user.email,
            "full_name": current_user.full_name,
            "role": current_user.role,
            "organization_id": str(current_user.organization_id) if current_user.organization_id else None,
            "is_active": current_user.is_active,
            "created_at": current_user.created_at.isoformat() if current_user.created_at else None,
            "last_login": current_user.last_login.isoformat() if current_user.last_login else None
        },
        "consents": [],
        "export_timestamp": datetime.utcnow().isoformat()
    }
    
    # Get consent records
    result = await db.execute(
        select(ConsentRecord).where(ConsentRecord.user_id == current_user.id)
    )
    consents = result.scalars().all()
    
    for consent in consents:
        user_data["consents"].append({
            "id": str(consent.id),
            "consent_type": consent.consent_type,
            "consent_given": consent.consent_given,
            "consent_date": consent.consent_date.isoformat() if consent.consent_date else None,
            "withdrawn_at": consent.withdrawn_at.isoformat() if consent.withdrawn_at else None
        })
    
    logger.info(
        "user_data_exported",
        user_id=str(current_user.id)
    )
    
    return user_data


@router.delete("/data-delete", summary="Delete user data", description="Delete all user data (GDPR right to be forgotten). This action is irreversible.")
@rate_limit("10/hour")
async def delete_user_data(
    request: Request,
    confirmation: str,  # Must be "DELETE" to confirm
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Delete all user data (right to be forgotten)"""
    if confirmation != "DELETE":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Confirmation must be 'DELETE' to proceed"
        )
    
    user_id = str(current_user.id)
    
    # Delete consent records
    await db.execute(
        delete(ConsentRecord).where(ConsentRecord.user_id == current_user.id)
    )
    
    # Mark user as deleted (soft delete)
    current_user.email = f"deleted_{user_id}@deleted.local"
    current_user.full_name = "Deleted User"
    current_user.is_active = False
    current_user.hashed_password = ""  # Remove password
    
    await db.commit()
    
    logger.warning(
        "user_data_deleted",
        user_id=user_id
    )
    
    return {"message": "User data deleted successfully. This action is irreversible."}


@router.get("/processing-records", summary="Get data processing records", description="Get data processing records for the organization.")
@rate_limit("100/minute")
async def get_processing_records(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Get data processing records"""
    if not current_user.organization_id:
        return {"items": [], "total": 0}
    
    result = await db.execute(
        select(DataProcessingRecord).where(
            DataProcessingRecord.organization_id == current_user.organization_id
        )
    )
    records = result.scalars().all()
    
    record_list = [
        {
            "id": str(record.id),
            "processing_activity": record.processing_activity,
            "data_categories": record.data_categories,
            "purposes": record.purposes,
            "recipients": record.recipients,
            "retention_period": record.retention_period,
            "security_measures": record.security_measures,
            "legal_basis": record.legal_basis,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None
        }
        for record in records
    ]
    
    return {"items": record_list, "total": len(record_list)}


@router.post("/processing-records", summary="Create data processing record", description="Create a new data processing record.")
@rate_limit("10/minute")
@require_admin()
async def create_processing_record(
    request: Request,
    processing_activity: str,
    data_categories: List[str],
    purposes: List[str],
    recipients: Optional[List[str]] = None,
    retention_period: Optional[str] = None,
    security_measures: Optional[List[str]] = None,
    legal_basis: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Create data processing record"""
    if not current_user.organization_id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Organization required"
        )
    
    record = DataProcessingRecord(
        organization_id=current_user.organization_id,
        processing_activity=processing_activity,
        data_categories=data_categories,
        purposes=purposes,
        recipients=recipients,
        retention_period=retention_period,
        security_measures=security_measures,
        legal_basis=legal_basis
    )
    
    db.add(record)
    await db.commit()
    await db.refresh(record)
    
    logger.info(
        "processing_record_created",
        record_id=str(record.id),
        organization_id=str(current_user.organization_id)
    )
    
    return {
        "id": str(record.id),
        "processing_activity": processing_activity,
        "message": "Data processing record created successfully"
    }
