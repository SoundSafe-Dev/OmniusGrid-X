"""SOC 2 and ISO 27001 Compliance API Endpoints"""

from datetime import datetime, date
from typing import Optional, List
from uuid import UUID
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi import status as http_status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from app.db.database import get_db

from app.db.models import (
    User,
    VendorRiskAssessment,
    SecurityAsset,
)
from app.api.auth import get_current_active_user
from app.middleware.rbac import require_admin
from app.middleware.rate_limit import rate_limit
from app.core.tenant import get_tenant_db, get_tenant_org_id
import structlog

logger = structlog.get_logger()

router = APIRouter()


# SOC 2 Compliance Endpoints

@router.get(
    "/vendor-assessments",
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


@router.post("/vendor-assessments", summary="Create vendor risk assessment", description="Create a new vendor risk assessment for SOC 2 compliance.")
@rate_limit("10/minute")
@require_admin()
async def create_vendor_assessment(
    request: Request,
    vendor_name: str,
    vendor_type: Optional[str] = None,
    risk_level: Optional[str] = None,
    assessment_date: Optional[date] = None,
    next_review_date: Optional[date] = None,
    findings: Optional[List[str]] = None,
    controls: Optional[List[str]] = None,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Create vendor risk assessment"""
    assessment = VendorRiskAssessment(
        vendor_name=vendor_name,
        vendor_type=vendor_type,
        risk_level=risk_level,
        assessment_date=assessment_date or date.today(),
        next_review_date=next_review_date,
        assessor_id=current_user.id,
        organization_id=org_id,
        findings=findings,
        controls=controls,
        status="pending"
    )

    db.add(assessment)
    await db.commit()
    await db.refresh(assessment)

    logger.info(
        "vendor_assessment_created",
        assessment_id=str(assessment.id),
        vendor_name=vendor_name,
        organization_id=str(org_id),
    )

    return {
        "id": str(assessment.id),
        "vendor_name": vendor_name,
        "message": "Vendor risk assessment created successfully"
    }


@router.put("/vendor-assessments/{assessment_id}", summary="Update vendor risk assessment", description="Update an existing vendor risk assessment.")
@rate_limit("10/minute")
@require_admin()
async def update_vendor_assessment(
    request: Request,
    assessment_id: str,
    risk_level: Optional[str] = None,
    next_review_date: Optional[date] = None,
    findings: Optional[List[str]] = None,
    controls: Optional[List[str]] = None,
    status: Optional[str] = None,
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

    if risk_level:
        assessment.risk_level = risk_level
    if next_review_date:
        assessment.next_review_date = next_review_date
    if findings:
        assessment.findings = findings
    if controls:
        assessment.controls = controls
    if status:
        assessment.status = status

    assessment.updated_at = datetime.utcnow()
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


@router.post("/security-assets", summary="Create security asset", description="Create a new security asset for ISO 27001 compliance.")
@rate_limit("10/minute")
@require_admin()
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
    await db.refresh(asset)

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


@router.put("/security-assets/{asset_id}", summary="Update security asset", description="Update an existing security asset.")
@rate_limit("10/minute")
@require_admin()
async def update_security_asset(
    request: Request,
    asset_id: str,
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

    asset.updated_at = datetime.utcnow()
    await db.commit()

    logger.info(
        "security_asset_updated",
        asset_id=asset_id,
        organization_id=str(org_id),
    )

    return {"message": "Security asset updated successfully"}


@router.delete("/security-assets/{asset_id}", summary="Delete security asset", description="Delete a security asset.")
@rate_limit("10/minute")
@require_admin()
async def delete_security_asset(
    request: Request,
    asset_id: str,
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


@router.get("/compliance-summary", summary="Get compliance summary", description="Get a summary of compliance status across all frameworks.")
@rate_limit("100/minute")
async def get_compliance_summary(
    request: Request,
    current_user: User = Depends(get_current_active_user),
    org_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    """Get compliance summary"""
    assets_result = await db.execute(
        select(SecurityAsset).where(SecurityAsset.organization_id == org_id)
    )
    total_assets = len(assets_result.scalars().all())

    vendors_result = await db.execute(
        select(VendorRiskAssessment).where(VendorRiskAssessment.organization_id == org_id)
    )
    total_vendors = len(vendors_result.scalars().all())

    high_risk_result = await db.execute(
        select(VendorRiskAssessment).where(
            VendorRiskAssessment.organization_id == org_id,
            VendorRiskAssessment.risk_level == "high",
        )
    )
    high_risk_vendors = len(high_risk_result.scalars().all())

    return {
        "iso_27001": {
            "total_assets": total_assets,
            "active_assets": total_assets  # Simplified for now
        },
        "soc_2": {
            "total_vendor_assessments": total_vendors,
            "high_risk_vendors": high_risk_vendors,
            "pending_assessments": total_vendors  # Simplified for now
        },
        "gdpr": {
            "consent_records": 0,  # Will be populated from consent records
            "data_processing_records": 0  # Will be populated from processing records
        }
    }


@router.get("/report/generate", summary="Generate compliance report", description="Generate a comprehensive compliance report for download.")
@rate_limit("10/hour")
@require_admin()
async def generate_compliance_report(
    request: Request,
    framework: str = "all",  # all, gdpr, soc2, iso27001
    format: str = "json",  # json, pdf
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """Generate compliance report"""
    report = {
        "generated_at": datetime.utcnow().isoformat(),
        "generated_by": str(current_user.id),
        "framework": framework,
        "summary": {},
        "details": {}
    }
    
    if framework in ["all", "iso27001"]:
        # ISO 27001 data
        assets_result = await db.execute(select(SecurityAsset))
        assets = assets_result.scalars().all()
        
        report["summary"]["iso_27001"] = {
            "total_assets": len(assets),
            "by_type": {},
            "by_classification": {}
        }
        
        for asset in assets:
            report["summary"]["iso_27001"]["by_type"][asset.asset_type] = \
                report["summary"]["iso_27001"]["by_type"].get(asset.asset_type, 0) + 1
            if asset.classification:
                report["summary"]["iso_27001"]["by_classification"][asset.classification] = \
                    report["summary"]["iso_27001"]["by_classification"].get(asset.classification, 0) + 1
        
        report["details"]["iso_27001"] = [
            {
                "id": str(asset.id),
                "asset_type": asset.asset_type,
                "asset_name": asset.asset_name,
                "classification": asset.classification,
                "status": asset.status
            }
            for asset in assets
        ]
    
    if framework in ["all", "soc2"]:
        # SOC 2 data
        vendors_result = await db.execute(select(VendorRiskAssessment))
        vendors = vendors_result.scalars().all()
        
        report["summary"]["soc_2"] = {
            "total_assessments": len(vendors),
            "by_risk_level": {},
            "by_status": {}
        }
        
        for vendor in vendors:
            if vendor.risk_level:
                report["summary"]["soc_2"]["by_risk_level"][vendor.risk_level] = \
                    report["summary"]["soc_2"]["by_risk_level"].get(vendor.risk_level, 0) + 1
            if vendor.status:
                report["summary"]["soc_2"]["by_status"][vendor.status] = \
                    report["summary"]["soc_2"]["by_status"].get(vendor.status, 0) + 1
        
        report["details"]["soc_2"] = [
            {
                "id": str(vendor.id),
                "vendor_name": vendor.vendor_name,
                "risk_level": vendor.risk_level,
                "status": vendor.status,
                "assessment_date": vendor.assessment_date.isoformat() if vendor.assessment_date else None
            }
            for vendor in vendors
        ]
    
    if framework in ["all", "gdpr"]:
        # GDPR data
        from app.db.models import ConsentRecord, DataProcessingRecord
        
        consents_result = await db.execute(select(ConsentRecord))
        consents = consents_result.scalars().all()
        
        processing_result = await db.execute(select(DataProcessingRecord))
        processing = processing_result.scalars().all()
        
        report["summary"]["gdpr"] = {
            "total_consent_records": len(consents),
            "active_consents": sum(1 for c in consents if c.consent_given and not c.withdrawn_at),
            "data_processing_records": len(processing)
        }
        
        report["details"]["gdpr"] = {
            "consents": [
                {
                    "id": str(consent.id),
                    "consent_type": consent.consent_type,
                    "consent_given": consent.consent_given,
                    "withdrawn_at": consent.withdrawn_at.isoformat() if consent.withdrawn_at else None
                }
                for consent in consents
            ],
            "processing_records": [
                {
                    "id": str(record.id),
                    "processing_activity": record.processing_activity,
                    "legal_basis": record.legal_basis
                }
                for record in processing
            ]
        }
    
    logger.info(
        "compliance_report_generated",
        framework=framework,
        format=format,
        user_id=str(current_user.id)
    )
    
    return report
