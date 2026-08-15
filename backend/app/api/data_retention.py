"""Data Retention Policies API Routes"""

from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field, model_validator
try:
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import AsyncSession
    from app.db.database import get_db
except ImportError:
    text = None
    AsyncSession = None
    get_db = None

from app.core.responses import conflict_response
from app.api.auth import get_current_active_user
from app.db.models import User
from app.middleware.rbac import require_admin
from app.middleware.tenant_isolation import get_tenant_db, get_tenant_org_id

# `router` is DELIBERATELY NOT MOUNTED (only `tenant_router` is, in main.py).
#
# Its routes are a GLOBAL, system-operator surface: they read/write
# data_retention_config (keyed by table_name, no organization_id — one config
# for the whole database) and trigger the archive_to_cold_storage() /
# purge_old_data() DB functions, which act across every table and every tenant.
# The only gate here is `require_admin`, which is a PER-ORG admin — so mounting
# this as-is would let any tenant's admin read global retention config and
# purge/archive all tenants' data. That is why it is unmounted.
#
# To expose it, gate it behind a super-admin / operator role (not per-org
# require_admin) and mount it on an ops-only path. Until then it stays dark.
# A guard (tests/test_data_retention_router_unmounted.py) fails if it is mounted
# without that change. The tenant-scoped retention surface is `tenant_router`.
router = APIRouter()

# ---- Response schemas (pool #43). Documented, not reshaped.


class HistorianPolicyOut(BaseModel):
    """`_historian_policy_payload`, shared by get / create / update."""

    id: str
    organization_id: str
    metric_name: str
    hot_retention_days: int
    warm_retention_days: int
    cold_retention_days: int
    #: INT, not str. It is a numeric priority (1..n) and the name reads like a
    #: label — the kind of guess a reader makes and a database refuses.
    ingestion_priority: int
    ingestion_sample_rate: float
    max_ingest_age_seconds: int
    archival_enabled: bool
    created_by: Optional[str] = None
    created_at: str
    updated_at: str


class HistorianPolicyList(BaseModel):
    policies: List[HistorianPolicyOut]
    count: int


class EnforceResult(BaseModel):
    organization_id: str
    deleted_rows: int


class RetentionStatusResponse(BaseModel):
    #: Rows describe TimescaleDB hypertable chunks; the columns depend on the
    #: server's Timescale version, so they stay open.
    tables: List[Dict[str, Any]]
    count: int


class RetentionConfigOut(BaseModel):
    table_name: str
    hot_retention_days: int
    warm_retention_days: int
    cold_retention_days: int
    compliance_retention_days: int
    compliance_standard: Optional[str] = None
    archival_enabled: bool
    archival_destination: Optional[str] = None
    created_at: Optional[Any] = None
    updated_at: Optional[Any] = None


class ConfigCreated(BaseModel):
    message: str
    config: Dict[str, Any]


class PolicyUpdated(BaseModel):
    message: str
    table_name: str
    retention_days: int


class OperationResults(BaseModel):
    """`/archive` and `/purge` both report a message plus per-table results."""

    message: str
    results: List[Dict[str, Any]]


class ComplianceCheckResponse(BaseModel):
    compliance_checks: List[Dict[str, Any]]
    count: int


class AggregatesResponse(BaseModel):
    aggregates: List[Dict[str, Any]]
    count: int


tenant_router = APIRouter()


class HistorianRetentionSettings(BaseModel):
    hot_retention_days: int = Field(30, ge=1, le=1825)
    warm_retention_days: int = Field(365, ge=1, le=1825)
    cold_retention_days: int = Field(1825, ge=1, le=3650)
    ingestion_priority: int = Field(3, ge=1, le=5)
    ingestion_sample_rate: float = Field(1.0, gt=0, le=1)
    max_ingest_age_seconds: int = Field(30, ge=1, le=86400)
    archival_enabled: bool = True

    @model_validator(mode="after")
    def validate_retention_order(self):
        if not (
            self.hot_retention_days
            <= self.warm_retention_days
            <= self.cold_retention_days
        ):
            raise ValueError(
                "retention days must satisfy hot <= warm <= cold"
            )
        return self


class HistorianRetentionReplace(HistorianRetentionSettings):
    """The PUT body: every field required (FS-470).

    PUT replaces, and this route's SQL sets every column — so a body missing
    `cold_retention_days` does not leave it alone, it resets it to 1825. That is correct
    PUT semantics and a silent trap for the first client that treats the route as a PATCH,
    which is how the allowance in `test_partial_updates_do_not_wipe_fields.py` described
    it: "if a consumer appears, this entry should be revisited before it does."

    Requiring the fields settles it without changing the verb or the semantics. A partial
    body is now a 422 naming the missing field instead of six retention settings quietly
    returning to defaults — the difference between an error and an incident.

    The defaults stay on the base, which `HistorianRetentionCreate` inherits: creating a
    policy from sane values is exactly what a default is for. **Replacing one is not.**
    """

    hot_retention_days: int = Field(..., ge=1, le=1825)
    warm_retention_days: int = Field(..., ge=1, le=1825)
    cold_retention_days: int = Field(..., ge=1, le=3650)
    ingestion_priority: int = Field(..., ge=1, le=5)
    ingestion_sample_rate: float = Field(..., gt=0, le=1)
    max_ingest_age_seconds: int = Field(..., ge=1, le=86400)
    archival_enabled: bool = Field(...)


class HistorianRetentionCreate(HistorianRetentionSettings):
    metric_name: str = Field(
        "*",
        min_length=1,
        max_length=100,
        pattern=r"^(\*|[A-Za-z0-9_.:-]+)$",
    )


def _historian_policy_payload(row):
    values = row._mapping if hasattr(row, "_mapping") else row
    return {
        "id": str(values["id"]),
        "organization_id": str(values["organization_id"]),
        "metric_name": values["metric_name"],
        "hot_retention_days": values["hot_retention_days"],
        "warm_retention_days": values["warm_retention_days"],
        "cold_retention_days": values["cold_retention_days"],
        "ingestion_priority": values["ingestion_priority"],
        "ingestion_sample_rate": float(values["ingestion_sample_rate"]),
        "max_ingest_age_seconds": values["max_ingest_age_seconds"],
        "archival_enabled": values["archival_enabled"],
        "created_by": str(values["created_by"]) if values["created_by"] else None,
        "created_at": values["created_at"].isoformat(),
        "updated_at": values["updated_at"].isoformat(),
    }


_HISTORIAN_POLICY_COLUMNS = """
    id, organization_id, metric_name,
    hot_retention_days, warm_retention_days, cold_retention_days,
    ingestion_priority, ingestion_sample_rate, max_ingest_age_seconds,
    archival_enabled, created_by, created_at, updated_at
"""


@tenant_router.get("/policies", response_model=HistorianPolicyList)
async def list_historian_retention_policies(
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = await db.execute(
        text(
            f"""
            SELECT {_HISTORIAN_POLICY_COLUMNS}
            FROM historian_retention_policies
            WHERE organization_id = :organization_id
            ORDER BY CASE WHEN metric_name = '*' THEN 0 ELSE 1 END, metric_name
            """
        ),
        {"organization_id": str(organization_id)},
    )
    policies = [_historian_policy_payload(row) for row in result.fetchall()]
    return {"policies": policies, "count": len(policies)}


@tenant_router.get("/policies/{metric_name}", response_model=HistorianPolicyOut)
async def get_historian_retention_policy(
    metric_name: str,
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = await db.execute(
        text(
            f"""
            SELECT {_HISTORIAN_POLICY_COLUMNS}
            FROM historian_retention_policies
            WHERE organization_id = :organization_id
              AND metric_name = :metric_name
            """
        ),
        {"organization_id": str(organization_id), "metric_name": metric_name},
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Retention policy not found")
    return _historian_policy_payload(row)


@tenant_router.post("/policies", response_model=HistorianPolicyOut, status_code=status.HTTP_201_CREATED, dependencies=[Depends(require_admin)], responses={**conflict_response})
async def create_historian_retention_policy(
    policy: HistorianRetentionCreate,
    current_user: User = Depends(get_current_active_user),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    from sqlalchemy.exc import IntegrityError

    try:
        result = await db.execute(
            text(
                f"""
                INSERT INTO historian_retention_policies (
                    id, organization_id, metric_name,
                    hot_retention_days, warm_retention_days, cold_retention_days,
                    ingestion_priority, ingestion_sample_rate,
                    max_ingest_age_seconds, archival_enabled, created_by
                ) VALUES (
                    :id, :organization_id, :metric_name,
                    :hot_retention_days, :warm_retention_days, :cold_retention_days,
                    :ingestion_priority, :ingestion_sample_rate,
                    :max_ingest_age_seconds, :archival_enabled, :created_by
                )
                RETURNING {_HISTORIAN_POLICY_COLUMNS}
                """
            ),
            {
                "id": str(uuid4()),
                "organization_id": str(organization_id),
                "metric_name": policy.metric_name,
                **policy.model_dump(exclude={"metric_name"}),
                "created_by": str(current_user.id),
            },
        )
    except IntegrityError as exc:
        raise HTTPException(
            status_code=409,
            detail="A retention policy already exists for this metric",
        ) from exc
    return _historian_policy_payload(result.fetchone())


@tenant_router.put("/policies/{metric_name}", response_model=HistorianPolicyOut, dependencies=[Depends(require_admin)])
async def update_historian_retention_policy(
    metric_name: str,
    policy: HistorianRetentionReplace,
    current_user: User = Depends(get_current_active_user),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = await db.execute(
        text(
            f"""
            UPDATE historian_retention_policies
            SET hot_retention_days = :hot_retention_days,
                warm_retention_days = :warm_retention_days,
                cold_retention_days = :cold_retention_days,
                ingestion_priority = :ingestion_priority,
                ingestion_sample_rate = :ingestion_sample_rate,
                max_ingest_age_seconds = :max_ingest_age_seconds,
                archival_enabled = :archival_enabled,
                updated_at = NOW()
            WHERE organization_id = :organization_id
              AND metric_name = :metric_name
            RETURNING {_HISTORIAN_POLICY_COLUMNS}
            """
        ),
        {
            "organization_id": str(organization_id),
            "metric_name": metric_name,
            **policy.model_dump(),
        },
    )
    row = result.fetchone()
    if row is None:
        raise HTTPException(status_code=404, detail="Retention policy not found")
    return _historian_policy_payload(row)


@tenant_router.delete("/policies/{metric_name}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_historian_retention_policy(
    metric_name: str,
    current_user: User = Depends(get_current_active_user),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = await db.execute(
        text(
            """
            DELETE FROM historian_retention_policies
            WHERE organization_id = :organization_id
              AND metric_name = :metric_name
            RETURNING id
            """
        ),
        {"organization_id": str(organization_id), "metric_name": metric_name},
    )
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=404, detail="Retention policy not found")


class RetentionEnforced(BaseModel):
    """`deleted_rows` is the return of `enforce_tenant_historian_retention()`, and it is
    the whole point of the endpoint — an enforcement run that reports nothing is
    indistinguishable from one that did nothing."""

    organization_id: str
    deleted_rows: int


@tenant_router.post("/enforce", response_model=RetentionEnforced,
                    dependencies=[Depends(require_admin)])
async def enforce_historian_retention(
    current_user: User = Depends(get_current_active_user),
    organization_id: UUID = Depends(get_tenant_org_id),
    db: AsyncSession = Depends(get_tenant_db),
):
    result = await db.execute(
        text("SELECT enforce_tenant_historian_retention(:organization_id)"),
        {"organization_id": str(organization_id)},
    )
    return {
        "organization_id": str(organization_id),
        "deleted_rows": int(result.scalar_one()),
    }


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


@router.get("/status", response_model=RetentionStatusResponse)
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


@router.get("/config/{table_name}", response_model=RetentionConfigOut)
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


@router.post("/config", response_model=ConfigCreated, dependencies=[Depends(require_admin)])
async def create_retention_config(
    config: RetentionConfig,
    current_user: User = Depends(get_current_active_user),
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


@router.put("/policy/{table_name}", response_model=PolicyUpdated, dependencies=[Depends(require_admin)])
async def update_retention_policy(
    table_name: str,
    policy: RetentionPolicyUpdate,
    current_user: User = Depends(get_current_active_user),
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


@router.post("/archive", response_model=OperationResults, dependencies=[Depends(require_admin)])
async def archive_to_cold_storage(
    current_user: User = Depends(get_current_active_user),
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


@router.post("/purge", response_model=OperationResults, dependencies=[Depends(require_admin)])
async def purge_old_data(
    current_user: User = Depends(get_current_active_user),
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


@router.get("/compliance", response_model=ComplianceCheckResponse)
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


@router.get("/aggregates", response_model=AggregatesResponse)
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
