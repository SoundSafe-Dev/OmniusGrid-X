"""Data Residency Controls (USA) API Endpoints"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, status, Request
from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

# `get_tenant_db`, not `get_db` (FS-433). Migration 062 puts data_residency_tags under
# FORCE ROW LEVEL SECURITY; the unscoped session binds no tenant GUC, so every read here
# would return zero rows and every write would be refused.
from app.core.tenant import get_tenant_db
from app.db.models import User, DataResidencyTag
from app.api.auth import get_current_active_user
from app.middleware.rbac import require_admin
from app.middleware.rate_limit import rate_limit
import structlog

logger = structlog.get_logger()

from pydantic import BaseModel  # noqa: E402

router = APIRouter()

# ---- Response schemas (pool #43 / FS-255). Documented, not reshaped.


class MessageResponse(BaseModel):
    """Tag and untag both acknowledge with a message alone."""

    message: str


class RecordResidency(BaseModel):
    table_name: str
    record_id: str
    tagged: bool
    region: Optional[str] = None
    #: Absent on the untagged branch, which returns four keys rather than six.
    #: Optional here rather than required, or every lookup of an untagged record
    #: would 500 on a response that is a perfectly normal answer.
    tagged_at: Optional[Any] = None
    tagged_by: Optional[str] = None


class ResidencyTagList(BaseModel):
    items: List[Dict[str, Any]]
    total: int


class ResidencySummary(BaseModel):
    total_tags: int
    #: Counter maps keyed by region / table name — the keys are data, so they
    #: cannot be a fixed model.
    by_region: Dict[str, int]
    by_table: Dict[str, int]


class ResidencyValidation(BaseModel):
    """What this check CAN see, and an explicit statement of what it cannot (FS-347).

    It previously reported `total_records = tagged_records`, so `untagged_records` was
    always 0 and `compliance_percentage` was computed over the tagged rows alone. An
    organisation with one tagged row and ten thousand untagged ones scored **100%** — on a
    data-residency check, whose entire purpose is finding data that is not where it should
    be. The untagged rows are the finding, and they were the ones it could not see.

    `total_records` and `untagged_records` are now `None` rather than a number, because
    counting the target table is not safely available here:

      * `table_names` is caller-supplied, so a real count means interpolating a caller's
        string into an identifier position;
      * counting an arbitrary caller-named table needs a session that can read it, and
        the target may be any RLS-protected table (`assets`, `alarms`, …).

    `data_residency_tags` DOES now carry an `organization_id` (FS-433, migration 062) and
    is under FORCE RLS, so the tag counts here are the caller's own — which is a change of
    meaning, not just of scope. They previously spanned every tenant. The unknown that
    remains is the denominator: how many rows exist in the target table at all.

    A cross-tenant row count needs the platform-admin role that does not exist yet
    (FS-311). Until then this reports the ratio it genuinely computes, names it after what
    it is over, and says plainly that coverage is unknown.
    """

    expected_region: str
    tables: Dict[str, Any]
    tagged_records: int
    correct_region_records: int
    incorrect_region_records: int
    #: Of the rows that ARE TAGGED — not residency compliance for the table. The old field
    #: was called `compliance_percentage`, which is the claim this cannot support.
    tagged_region_percentage: float
    #: `None`, deliberately. Zero would assert that nothing is untagged.
    total_records: Optional[int] = None
    untagged_records: Optional[int] = None
    coverage_warning: str



# Default region for USA compliance
DEFAULT_REGION = "USA"


@router.post("/tag", response_model=MessageResponse, summary="Tag record with residency", description="Tag a database record with its data residency region.", dependencies=[Depends(require_admin)])
@rate_limit("100/minute")
async def tag_record_residency(
    request: Request,
    table_name: str,
    record_id: str,
    region: str = DEFAULT_REGION,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db)
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
                # Explicit as well as by policy. RLS is the enforcement; this is what a
                # reader of the handler can see, and it keeps the query honest if the
                # table is ever read through a privileged session.
                DataResidencyTag.organization_id == str(current_user.organization_id),
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
        existing_tag.tagged_at = datetime.now(timezone.utc)
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
        # FROM THE TOKEN, never the body. Same rule the fleet_logistics and
        # logistics_correlation create paths were fixed to follow.
        organization_id=str(current_user.organization_id),
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


@router.get("/tag/{table_name}/{record_id}", response_model=RecordResidency, summary="Get record residency", description="Get the data residency tag for a specific record.")
@rate_limit("100/minute")
async def get_record_residency(
    request: Request,
    table_name: str,
    record_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Get data residency tag for a record"""
    result = await db.execute(
        select(DataResidencyTag).where(
            and_(
                # Explicit as well as by policy. RLS is the enforcement; this is what a
                # reader of the handler can see, and it keeps the query honest if the
                # table is ever read through a privileged session.
                DataResidencyTag.organization_id == str(current_user.organization_id),
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


@router.get("/tags", response_model=ResidencyTagList, summary="List residency tags", description="List all data residency tags, optionally filtered by table or region.")
@rate_limit("100/minute")
async def list_residency_tags(
    request: Request,
    table_name: Optional[str] = None,
    region: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db)
):
    """List data residency tags for the caller's organisation (FS-433).

    This listed EVERY tenant's tags to any authenticated user. Each row carries a
    `record_id` from a tenant-scoped table and the `tagged_by` user id, so it exposed both
    which of another organisation's records were tagged and who tagged them.
    """
    query = select(DataResidencyTag).where(
        DataResidencyTag.organization_id == str(current_user.organization_id)
    )
    
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


@router.delete("/tag/{table_name}/{record_id}", response_model=MessageResponse, summary="Remove residency tag", description="Remove a data residency tag from a record.", dependencies=[Depends(require_admin)])
@rate_limit("10/minute")
async def remove_residency_tag(
    request: Request,
    table_name: str,
    record_id: str,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Remove data residency tag"""
    result = await db.execute(
        select(DataResidencyTag).where(
            and_(
                # Explicit as well as by policy. RLS is the enforcement; this is what a
                # reader of the handler can see, and it keeps the query honest if the
                # table is ever read through a privileged session.
                DataResidencyTag.organization_id == str(current_user.organization_id),
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


@router.get("/summary", response_model=ResidencySummary, summary="Get residency summary", description="Get a summary of data residency across all tables.")
@rate_limit("100/minute")
async def get_residency_summary(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Data residency summary for the caller's organisation (FS-433).

    This counted every tenant's tags and returned the total as the caller's own compliance
    position — a figure an auditor is meant to rely on, computed over data the caller does
    not own.
    """
    result = await db.execute(
        select(DataResidencyTag).where(
            DataResidencyTag.organization_id == str(current_user.organization_id)
        )
    )
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


class DataResidencyValidateRequest(BaseModel):
    """FS-902. `expected_region` used to be a bare query parameter beside `table_names`
    (a list, read from the body) -- a body-only call (`{"table_names": [...]}`) had
    `expected_region` silently fall to `DEFAULT_REGION` and reported a pass against a
    region the caller never named. One body model."""

    table_names: List[str]
    expected_region: str = DEFAULT_REGION


@router.post("/validate", response_model=ResidencyValidation, summary="Validate data residency", description="Validate that all data in specified tables is tagged with correct residency.", dependencies=[Depends(require_admin)])
@rate_limit("10/minute")
async def validate_data_residency(
    request: Request,
    body: DataResidencyValidateRequest,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_tenant_db)
):
    """Validate data residency for specified tables. See `ResidencyValidation` for what
    this can and cannot see — the untagged rows are the finding, and they are invisible
    here until FS-311 provides a cross-tenant read path."""
    validation_results: Dict[str, Any] = {
        "expected_region": body.expected_region,
        "tables": {},
        "tagged_records": 0,
        "correct_region_records": 0,
        "incorrect_region_records": 0,
        "tagged_region_percentage": 0.0,
        "total_records": None,
        "untagged_records": None,
        "coverage_warning": (
            "Counts tagged rows only. Rows with no residency tag are not visible to this "
            "check, so it cannot report coverage — a high percentage here means the "
            "tagged rows are in the expected region, NOT that the table is compliant."
        ),
    }

    for table_name in body.table_names:
        # Get all tags for this table
        result = await db.execute(
            select(DataResidencyTag).where(
                DataResidencyTag.organization_id == str(current_user.organization_id),
                DataResidencyTag.table_name == table_name,
            )
        )
        tags = result.scalars().all()

        # Count tagged records with correct region
        correct_tags = [t for t in tags if t.region == body.expected_region]

        validation_results["tables"][table_name] = {
            "tagged_count": len(tags),
            "correct_region_count": len(correct_tags),
            "incorrect_region_count": len(tags) - len(correct_tags),
        }

        validation_results["tagged_records"] += len(tags)
        validation_results["correct_region_records"] += len(correct_tags)
        validation_results["incorrect_region_records"] += len(tags) - len(correct_tags)

    # OVER THE TAGGED ROWS, and named for it. This used to divide by `total_records`,
    # which was itself set to `tagged_records` one line earlier — so the denominator was
    # the tagged set while the field was called `compliance_percentage`, which reads as a
    # statement about the table.
    if validation_results["tagged_records"] > 0:
        validation_results["tagged_region_percentage"] = (
            validation_results["correct_region_records"]
            / validation_results["tagged_records"]
        ) * 100
    
    logger.info(
        "data_residency_validation",
        table_names=body.table_names,
        expected_region=body.expected_region,
        # Renamed with the field. Logging it as `compliance_percentage` would put the
        # claim this endpoint cannot support into the log line instead of the response,
        # where a dashboard built on structlog would pick it up unchallenged.
        tagged_region_percentage=validation_results["tagged_region_percentage"],
        tagged_records=validation_results["tagged_records"],
    )
    
    return validation_results
