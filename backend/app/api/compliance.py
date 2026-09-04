"""SOC 2 and ISO 27001 Compliance API Endpoints"""

from datetime import datetime, date, timezone
from typing import Any, Dict, Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import status as http_status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import (
    ConsentRecord,
    DataProcessingRecord,
    User,
    VendorRiskAssessment,
    SecurityAsset,
)
from app.api.auth import get_current_active_user
from app.middleware.rbac import require_admin
from app.middleware.rate_limit import rate_limit
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id
import structlog

logger = structlog.get_logger()

from pydantic import BaseModel  # noqa: E402

router = APIRouter()

# ---- Response schemas (pool #43 / FS-253). Documented, not reshaped.


class CreatedWithMessage(BaseModel):
    """Both creates echo the new id, its display name, and a message. The two
    name keys differ (`vendor_name` / `asset_name`), so each gets its own model
    rather than a shared one with both optional — an optional key here would
    start emitting a null the caller never had."""

    id: str
    message: str


class VendorAssessmentCreated(CreatedWithMessage):
    vendor_name: str


class VendorAssessmentCreate(BaseModel):
    """FS-902. `vendor_name`, `risk_level` and `assessment_date` (among others) used to
    be bare query parameters beside `findings`/`controls` (lists, so FastAPI reads them
    from the body) -- a body-only client filed an assessment against a DEFAULT vendor at
    a DEFAULT risk level. One body model closes the gap."""

    vendor_name: str
    vendor_type: Optional[str] = None
    risk_level: Optional[str] = None
    assessment_date: Optional[date] = None
    next_review_date: Optional[date] = None
    findings: Optional[List[str]] = None
    controls: Optional[List[str]] = None


class VendorAssessmentUpdate(BaseModel):
    """FS-902. `risk_level` and `status` used to be bare query parameters beside
    `findings`/`controls` (lists, read from the body) -- no single request a client
    sends fills both halves, so a caller posting `{"findings": [...]}` had no way to
    ALSO send `risk_level` in the same document; it silently stayed query-string-default
    (unset), and the handler's `if risk_level:` guard then left the stored value
    untouched even when the caller's intent was to change it in the same call."""

    risk_level: Optional[str] = None
    next_review_date: Optional[date] = None
    findings: Optional[List[str]] = None
    controls: Optional[List[str]] = None
    status: Optional[str] = None


class SecurityAssetCreated(CreatedWithMessage):
    asset_name: str


class MessageResponse(BaseModel):
    """The two updates and the delete acknowledge with a message alone."""

    message: str


class SecurityAssetList(BaseModel):
    items: List[Dict[str, Any]]
    total: int


class ComplianceSummary(BaseModel):
    """One block per framework. The blocks are open objects: each is assembled
    from a different set of counters and they do not share a shape."""

    iso_27001: Dict[str, Any]
    soc_2: Dict[str, Any]
    gdpr: Dict[str, Any]




# SOC 2 Compliance Endpoints

@router.get(
    "/vendor-assessments",
    response_model=SecurityAssetList,
    summary="List vendor risk assessments",
    description="List vendor risk assessments for the authenticated organization (SOC 2).",
)
@rate_limit("100/minute")
async def list_vendor_assessments(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """List vendor risk assessments"""
    result = await db.execute(
        select(VendorRiskAssessment)
        .where(VendorRiskAssessment.organization_id == org_id)
        .order_by(VendorRiskAssessment.assessment_date.desc())
    )
    assessments = result.scalars().all()

    assessment_list = [
        {
            "id": str(assessment.id),
            "vendor_name": assessment.vendor_name,
            "vendor_type": assessment.vendor_type,
            "risk_level": assessment.risk_level,
            "assessment_date": assessment.assessment_date.isoformat() if assessment.assessment_date else None,
            "next_review_date": assessment.next_review_date.isoformat() if assessment.next_review_date else None,
            "status": assessment.status,
            "findings": assessment.findings,
            "controls": assessment.controls
        }
        for assessment in assessments
    ]

    return {"items": assessment_list, "total": len(assessment_list)}


@router.post("/vendor-assessments", response_model=VendorAssessmentCreated, summary="Create vendor risk assessment", description="Create a new vendor risk assessment for SOC 2 compliance.", dependencies=[Depends(require_admin)])
@rate_limit("10/minute")
async def create_vendor_assessment(
    request: Request,
    body: VendorAssessmentCreate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Create vendor risk assessment"""
    assessment = VendorRiskAssessment(
        vendor_name=body.vendor_name,
        vendor_type=body.vendor_type,
        risk_level=body.risk_level,
        assessment_date=body.assessment_date or date.today(),
        next_review_date=body.next_review_date,
        assessor_id=current_user.id,
        organization_id=org_id,
        findings=body.findings,
        controls=body.controls,
        status="pending"
    )

    db.add(assessment)
    await db.commit()

    logger.info(
        "vendor_assessment_created",
        assessment_id=str(assessment.id),
        vendor_name=body.vendor_name,
        organization_id=str(org_id),
    )

    return {
        "id": str(assessment.id),
        "vendor_name": body.vendor_name,
        "message": "Vendor risk assessment created successfully"
    }


@router.put("/vendor-assessments/{assessment_id}", response_model=MessageResponse, summary="Update vendor risk assessment", description="Update an existing vendor risk assessment.", dependencies=[Depends(require_admin)])
@rate_limit("10/minute")
async def update_vendor_assessment(
    request: Request,
    assessment_id: UUID,
    body: VendorAssessmentUpdate,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Update vendor risk assessment"""
    result = await db.execute(
        select(VendorRiskAssessment).where(
            VendorRiskAssessment.id == assessment_id,
            VendorRiskAssessment.organization_id == org_id,
        )
    )
    assessment = result.scalar_one_or_none()

    if not assessment:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Vendor assessment not found"
        )

    if body.risk_level:
        assessment.risk_level = body.risk_level
    if body.next_review_date:
        assessment.next_review_date = body.next_review_date
    if body.findings:
        assessment.findings = body.findings
    if body.controls:
        assessment.controls = body.controls
    if body.status:
        assessment.status = body.status

    assessment.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(
        "vendor_assessment_updated",
        assessment_id=assessment_id,
        organization_id=str(org_id),
    )

    return {"message": "Vendor risk assessment updated successfully"}


# ISO 27001 Compliance Endpoints

@router.get(
    "/security-assets",
    response_model=SecurityAssetList,
    summary="List security assets",
    description="List security assets for the authenticated organization (ISO 27001).",
)
@rate_limit("100/minute")
async def list_security_assets(
    request: Request,
    asset_type: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """List security assets"""
    query = select(SecurityAsset).where(SecurityAsset.organization_id == org_id)

    if asset_type:
        query = query.where(SecurityAsset.asset_type == asset_type)

    result = await db.execute(query.order_by(SecurityAsset.created_at.desc()))
    assets = result.scalars().all()

    asset_list = [
        {
            "id": str(asset.id),
            "asset_type": asset.asset_type,
            "asset_name": asset.asset_name,
            "asset_id": asset.asset_id,
            "classification": asset.classification,
            "location": asset.location,
            "status": asset.status,
            "created_at": asset.created_at.isoformat() if asset.created_at else None
        }
        for asset in assets
    ]

    return {"items": asset_list, "total": len(asset_list)}


@router.post("/security-assets", response_model=SecurityAssetCreated, summary="Create security asset", description="Create a new security asset for ISO 27001 compliance.", dependencies=[Depends(require_admin)])
@rate_limit("10/minute")
async def create_security_asset(
    request: Request,
    asset_type: str,
    asset_name: str,
    asset_id: Optional[str] = None,
    classification: Optional[str] = None,
    location: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Create security asset"""
    asset = SecurityAsset(
        asset_type=asset_type,
        asset_name=asset_name,
        asset_id=asset_id,
        owner_id=current_user.id,
        organization_id=org_id,
        classification=classification,
        location=location,
        status="active"
    )

    db.add(asset)
    await db.commit()

    logger.info(
        "security_asset_created",
        asset_id=str(asset.id),
        asset_name=asset_name,
        organization_id=str(org_id),
    )

    return {
        "id": str(asset.id),
        "asset_name": asset_name,
        "message": "Security asset created successfully"
    }


@router.put("/security-assets/{asset_id}", response_model=MessageResponse, summary="Update security asset", description="Update an existing security asset.", dependencies=[Depends(require_admin)])
@rate_limit("10/minute")
async def update_security_asset(
    request: Request,
    asset_id: UUID,
    classification: Optional[str] = None,
    location: Optional[str] = None,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Update security asset"""
    result = await db.execute(
        select(SecurityAsset).where(
            SecurityAsset.id == asset_id,
            SecurityAsset.organization_id == org_id,
        )
    )
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Security asset not found"
        )

    if classification:
        asset.classification = classification
    if location:
        asset.location = location
    if status:
        asset.status = status

    asset.updated_at = datetime.now(timezone.utc)
    await db.commit()

    logger.info(
        "security_asset_updated",
        asset_id=asset_id,
        organization_id=str(org_id),
    )

    return {"message": "Security asset updated successfully"}


@router.delete("/security-assets/{asset_id}", response_model=MessageResponse, summary="Delete security asset", description="Delete a security asset.", dependencies=[Depends(require_admin)])
@rate_limit("10/minute")
async def delete_security_asset(
    request: Request,
    asset_id: UUID,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Delete security asset"""
    result = await db.execute(
        select(SecurityAsset).where(
            SecurityAsset.id == asset_id,
            SecurityAsset.organization_id == org_id,
        )
    )
    asset = result.scalar_one_or_none()

    if not asset:
        raise HTTPException(
            status_code=http_status.HTTP_404_NOT_FOUND,
            detail="Security asset not found"
        )

    await db.delete(asset)
    await db.commit()

    logger.info(
        "security_asset_deleted",
        asset_id=asset_id,
        organization_id=str(org_id),
    )

    return {"message": "Security asset deleted successfully"}


@router.get("/compliance-summary", response_model=ComplianceSummary, summary="Get compliance summary", description="Get a summary of compliance status across all frameworks.")
@rate_limit("100/minute")
async def get_compliance_summary(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get compliance summary.

    FOUR OF THESE SIX FIGURES WERE NOT COMPUTED (FS-346). `active_assets` was
    `total_assets`, `pending_assessments` was `total_vendor_assessments`, and both GDPR
    counters were the literal `0` behind `# Will be populated from…`.

    That is a worse failure here than almost anywhere else in the codebase, because the
    blocks are labelled **ISO 27001**, **SOC 2** and **GDPR**. A reader takes
    `active_assets == total_assets` as "every asset is active" rather than "nobody computed
    this", and `consent_records: 0` reads as a finding — an organisation that has recorded
    no consent — rather than as an unimplemented counter. A compliance summary is read
    precisely when someone needs to trust it.

    Every column needed already existed: `security_assets.status`,
    `vendor_risk_assessments.status`, and both GDPR tables.

    `consent_records` is counted through `users` because that table has **no
    `organization_id`** — it is scoped by `user_id`, which `gdpr.py` records as the right
    grain for consent. So the org count is a join, not a filter, and it is the one figure
    here whose scoping is not a policy predicate.
    """
    total_assets = (
        await db.execute(
            select(func.count())
            .select_from(SecurityAsset)
            .where(SecurityAsset.organization_id == org_id)
        )
    ).scalar_one()

    # COUNTED, not assumed. `status` defaults to "active", so on a seeded database this
    # will often equal `total_assets` — the point is that it now differs when it should.
    active_assets = (
        await db.execute(
            select(func.count())
            .select_from(SecurityAsset)
            .where(
                SecurityAsset.organization_id == org_id,
                SecurityAsset.status == "active",
            )
        )
    ).scalar_one()

    total_vendors = (
        await db.execute(
            select(func.count())
            .select_from(VendorRiskAssessment)
            .where(VendorRiskAssessment.organization_id == org_id)
        )
    ).scalar_one()

    high_risk_vendors = (
        await db.execute(
            select(func.count())
            .select_from(VendorRiskAssessment)
            .where(
                VendorRiskAssessment.organization_id == org_id,
                VendorRiskAssessment.risk_level == "high",
            )
        )
    ).scalar_one()

    pending_assessments = (
        await db.execute(
            select(func.count())
            .select_from(VendorRiskAssessment)
            .where(
                VendorRiskAssessment.organization_id == org_id,
                VendorRiskAssessment.status == "pending",
            )
        )
    ).scalar_one()

    consent_records = (
        await db.execute(
            select(func.count())
            .select_from(ConsentRecord)
            .join(User, User.id == ConsentRecord.user_id)
            .where(User.organization_id == org_id)
        )
    ).scalar_one()

    data_processing_records = (
        await db.execute(
            select(func.count())
            .select_from(DataProcessingRecord)
            .where(DataProcessingRecord.organization_id == org_id)
        )
    ).scalar_one()

    return {
        "iso_27001": {
            "total_assets": total_assets,
            "active_assets": active_assets,
        },
        "soc_2": {
            "total_vendor_assessments": total_vendors,
            "high_risk_vendors": high_risk_vendors,
            "pending_assessments": pending_assessments,
        },
        "gdpr": {
            "consent_records": consent_records,
            "data_processing_records": data_processing_records,
        },
    }
