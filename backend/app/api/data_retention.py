"""Data Retention Policies API Routes"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
try:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.db.database import get_db
except ImportError:
    text = None
    AsyncSession = None
    get_db = None

router = APIRouter()


class RetentionConfig(BaseModel):
    table_name: str
    hot_retention_days: int = 7
    warm_retention_days: int = 30
    cold_retention_days: int = 365
    compliance_retention_days: Optional[int] = None
    compliance_standard: Optional[str] = None
    archival_enabled: bool = True
    archival_destination: str = "s3://omniusgrid-archive"


class RetentionPolicyUpdate(BaseModel):
    retention_days: int


@router.get("/status")
async def get_retention_status(
    db: AsyncSession = Depends(get_db)
):
    """Get current data retention status for all tables."""
    try:
        query = text("SELECT * FROM retention_status")
        result = await db.execute(query)
        rows = result.fetchall()
        
        return {
            "tables": [
                {
                    "table_name": row.table_name,
                    "hot_retention_days": row.hot_retention_days,
                    "warm_retention_days": row.warm_retention_days,
                    "cold_retention_days": row.cold_retention_days,
                    "compliance_retention_days": row.compliance_retention_days,
                    "compliance_standard": row.compliance_standard,
                    "archival_enabled": row.archival_enabled,
                    "archival_destination": row.archival_destination,
                    "current_size": row.current_size,
                    "has_stats": row.has_stats
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve retention status: {str(e)}"
        )


@router.get("/config/{table_name}")
async def get_retention_config(
    table_name: str,
    db: AsyncSession = Depends(get_db)
):
    """Get retention configuration for a specific table."""
    try:
        query = text("""
            SELECT * FROM data_retention_config
            WHERE table_name = :table_name
        """)
        result = await db.execute(query, {"table_name": table_name})
        row = result.fetchone()
        
        if not row:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Retention config not found for table: {table_name}"
            )
        
        return {
            "table_name": row.table_name,
            "hot_retention_days": row.hot_retention_days,
            "warm_retention_days": row.warm_retention_days,
            "cold_retention_days": row.cold_retention_days,
            "compliance_retention_days": row.compliance_retention_days,
            "compliance_standard": row.compliance_standard,
            "archival_enabled": row.archival_enabled,
            "archival_destination": row.archival_destination,
            "created_at": row.created_at.isoformat() if row.created_at else None,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None
        }
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve retention config: {str(e)}"
        )


@router.post("/config")
async def create_retention_config(
    config: RetentionConfig,
    db: AsyncSession = Depends(get_db)
):
    """Create retention configuration for a table."""
    try:
        query = text("""
            INSERT INTO data_retention_config (
                table_name, hot_retention_days, warm_retention_days,
                cold_retention_days, compliance_retention_days, compliance_standard,
                archival_enabled, archival_destination
            )
            VALUES (
                :table_name, :hot_retention_days, :warm_retention_days,
                :cold_retention_days, :compliance_retention_days, :compliance_standard,
                :archival_enabled, :archival_destination
            )
            ON CONFLICT (table_name) DO UPDATE SET
                hot_retention_days = EXCLUDED.hot_retention_days,
                warm_retention_days = EXCLUDED.warm_retention_days,
                cold_retention_days = EXCLUDED.cold_retention_days,
                compliance_retention_days = EXCLUDED.compliance_retention_days,
                compliance_standard = EXCLUDED.compliance_standard,
                archival_enabled = EXCLUDED.archival_enabled,
                archival_destination = EXCLUDED.archival_destination,
                updated_at = NOW()
            RETURNING *
        """)
        
        result = await db.execute(query, {
            "table_name": config.table_name,
            "hot_retention_days": config.hot_retention_days,
            "warm_retention_days": config.warm_retention_days,
            "cold_retention_days": config.cold_retention_days,
            "compliance_retention_days": config.compliance_retention_days,
            "compliance_standard": config.compliance_standard,
            "archival_enabled": config.archival_enabled,
            "archival_destination": config.archival_destination
        })
        await db.commit()
        
        row = result.fetchone()
        
        return {
            "message": "Retention configuration created/updated successfully",
            "config": {
                "table_name": row.table_name,
                "hot_retention_days": row.hot_retention_days,
                "warm_retention_days": row.warm_retention_days,
                "cold_retention_days": row.cold_retention_days
            }
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to create retention config: {str(e)}"
        )


@router.put("/policy/{table_name}")
async def update_retention_policy(
    table_name: str,
    policy: RetentionPolicyUpdate,
    db: AsyncSession = Depends(get_db)
):
    """Update retention policy for a table."""
    try:
        query = text("SELECT update_retention_policy(:table_name, :retention_days)")
        await db.execute(query, {
            "table_name": table_name,
            "retention_days": policy.retention_days
        })
        await db.commit()
        
        return {
            "message": f"Retention policy updated for {table_name}",
            "table_name": table_name,
            "retention_days": policy.retention_days
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to update retention policy: {str(e)}"
        )


@router.post("/archive")
async def archive_to_cold_storage(
    db: AsyncSession = Depends(get_db)
):
    """Trigger archival of data to cold storage."""
    try:
        query = text("SELECT * FROM archive_to_cold_storage()")
        result = await db.execute(query)
        rows = result.fetchall()
        
        await db.commit()
        
        return {
            "message": "Archival process completed",
            "results": [
                {
                    "table_name": row.table_name,
                    "archived_rows": row.archived_rows,
                    "archival_time": row.archival_time.isoformat() if row.archival_time else None
                }
                for row in rows
            ]
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to archive data: {str(e)}"
        )


@router.post("/purge")
async def purge_old_data(
    db: AsyncSession = Depends(get_db)
):
    """Trigger purging of old data."""
    try:
        query = text("SELECT * FROM purge_old_data()")
        result = await db.execute(query)
        rows = result.fetchall()
        
        await db.commit()
        
        return {
            "message": "Purge process completed",
            "results": [
                {
                    "table_name": row.table_name,
                    "purged_rows": row.purged_rows,
                    "purge_time": row.purge_time.isoformat() if row.purge_time else None
                }
                for row in rows
            ]
        }
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to purge data: {str(e)}"
        )


@router.get("/compliance")
async def check_compliance_retention(
    db: AsyncSession = Depends(get_db)
):
    """Check if retention policies meet compliance requirements."""
    try:
        query = text("SELECT * FROM check_compliance_retention()")
        result = await db.execute(query)
        rows = result.fetchall()
        
        return {
            "compliance_checks": [
                {
                    "table_name": row.table_name,
                    "compliance_standard": row.compliance_standard,
                    "required_retention_days": row.required_retention_days,
                    "current_retention_days": row.current_retention_days,
                    "is_compliant": row.is_compliant,
                    "recommendation": row.recommendation
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to check compliance: {str(e)}"
        )


@router.get("/aggregates")
async def get_continuous_aggregates(
    db: AsyncSession = Depends(get_db)
):
    """Get information about continuous aggregates for long-term retention."""
    try:
        query = text("""
            SELECT 
                viewname,
                viewowner,
                definition
            FROM pg_matviews
            WHERE viewname LIKE '%oee%'
            ORDER BY viewname
        """)
        result = await db.execute(query)
        rows = result.fetchall()
        
        return {
            "aggregates": [
                {
                    "view_name": row.viewname,
                    "owner": row.viewowner,
                    "definition": row.definition[:200] + "..." if len(row.definition) > 200 else row.definition
                }
                for row in rows
            ],
            "count": len(rows)
        }
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve aggregates: {str(e)}"
        )
