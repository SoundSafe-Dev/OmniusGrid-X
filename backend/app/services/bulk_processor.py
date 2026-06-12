"""Bulk operations processor (Task 7).

Async, Redis-tracked bulk operations across assets, Kanban tasks, alarms, and
registry items. Job progress lives in Redis (the same store the Task 1 feature
flags use); the work itself runs in a FastAPI ``BackgroundTask``. Every bulk
action is recorded in the existing ``audit_logs`` table (migration 009), whose
BEFORE INSERT trigger computes the tamper-evident hash chain.

Design notes
------------
* ``BackgroundTasks`` run AFTER the response is sent, so the request-scoped DB
  session is already closed. Each executor therefore opens its own
  ``AsyncSessionLocal``. For RLS-protected tables (assets, workcells — migration
  011) the executor sets the ``app.current_org_id`` GUC itself via
  :meth:`_tenant_session`, mirroring :func:`app.core.tenant.get_tenant_db`.
* Partial success: a failing row is recorded in ``errors`` and the batch
  continues. The job only reports ``failed`` if it raises around the whole loop.
* Per-domain tenancy matches each domain's single-record endpoint: assets are
  org-scoped through RLS + an explicit ``organization_id`` filter; alarms (which
  have no ``organization_id`` column) are scoped via a join to ``assets``; Kanban
  tasks are scoped through their board's organization.
* Jobs are in-process and do NOT survive a backend restart — this matches the
  codebase (no Celery/arq). A durable multi-worker queue would be a separate
  infrastructure decision.
"""

import csv
import io
import json
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Any, Optional

import redis.asyncio as redis
import structlog
from sqlalchemy import and_, func, select, text

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import (
    ActionableRegistry,
    ActionableRegistryItem,
    Alarm,
    Asset,
    AssetType,
    Task,
    TaskBoard,
    TaskColumn,
    User,
    Workcell,
)

logger = structlog.get_logger()

JOB_KEY_PREFIX = "bulk_job:"
JOB_TTL_SECONDS = 24 * 60 * 60
MAX_STORED_ERRORS = 1000

# Asset CSV columns we accept. asset_type/workcell may be supplied by name or by
# *_id (id wins when both are present); update-vs-create is keyed on `id` only.
ASSET_CSV_COLUMNS = {
    "id", "name", "serial_number", "vendor", "model", "is_active",
    "asset_type", "asset_type_id", "workcell", "workcell_id",
}


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


_TRUE_TOKENS = {"1", "true", "yes", "y", "t"}
_FALSE_TOKENS = {"0", "false", "no", "n", "f"}


def _coerce_bool(value: Any, default: bool = True) -> bool:
    """Parse a CSV boolean cell, rejecting values we don't recognise.

    An empty/missing cell falls back to ``default``; anything else must be an
    explicit true/false token. Unrecognised values raise :class:`_RowError` so
    the row fails loudly instead of silently coercing a typo to ``False``.
    """
    if value is None or value == "":
        return default
    token = str(value).strip().lower()
    if token in _TRUE_TOKENS:
        return True
    if token in _FALSE_TOKENS:
        return False
    raise _RowError(
        f"invalid boolean '{value}'; expected one of "
        f"{', '.join(sorted(_TRUE_TOKENS | _FALSE_TOKENS))}"
    )


class BulkOperationError(Exception):
    """Raised for a bulk request that fails validation before any work starts."""


class _RowError(Exception):
    """Internal: one row/item failed; it is recorded and the batch continues."""


def parse_asset_csv(raw: bytes) -> list[dict]:
    """Parse + validate the asset CSV upload into a list of trimmed row dicts.

    Raises :class:`BulkOperationError` for structural problems (bad encoding,
    unknown columns, no usable key column, no data rows) so the API layer can
    fast-fail with a 400 before a job is ever created.
    """
    try:
        text_data = raw.decode("utf-8-sig")  # utf-8-sig also strips a BOM
    except UnicodeDecodeError:
        raise BulkOperationError("CSV must be UTF-8 encoded")

    reader = csv.DictReader(io.StringIO(text_data))
    if not reader.fieldnames:
        raise BulkOperationError("CSV is empty or missing a header row")

    headers = {(h or "").strip() for h in reader.fieldnames}
    headers.discard("")
    unknown = headers - ASSET_CSV_COLUMNS
    if unknown:
        raise BulkOperationError(
            f"Unknown CSV column(s): {', '.join(sorted(unknown))}. "
            f"Allowed: {', '.join(sorted(ASSET_CSV_COLUMNS))}"
        )
    if "name" not in headers and "id" not in headers:
        raise BulkOperationError("CSV must contain at least an 'id' or 'name' column")

    rows: list[dict] = []
    for raw_row in reader:
        row = {
            (k or "").strip(): (v.strip() if isinstance(v, str) else v)
            for k, v in raw_row.items()
            if k
        }
        if any(row.values()):  # skip blank lines
            rows.append(row)

    if not rows:
        raise BulkOperationError("CSV has a header but no data rows")
    return rows


class BulkProcessor:
    """Redis-backed job tracking + per-domain bulk executors."""

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None

    def _redis(self) -> redis.Redis:
        """Lazily create a shared async Redis client (decoded strings)."""
        if self._client is None:
            self._client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        return self._client

    # --- Job lifecycle --------------------------------------------------------
    async def create_job(
        self,
        job_type: str,
        total: int,
        organization_id: Optional[Any] = None,
        actor_id: Optional[Any] = None,
    ) -> dict:
        job = {
            "job_id": str(uuid.uuid4()),
            "type": job_type,
            "status": "pending",
            "total": total,
            "processed": 0,
            "succeeded": 0,
            "failed": 0,
            "errors": [],
            "created_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "organization_id": str(organization_id) if organization_id else None,
            "actor_id": str(actor_id) if actor_id else None,
        }
        await self._save(job)
        return job

    async def get_job(self, job_id: str) -> Optional[dict]:
        raw = await self._redis().get(f"{JOB_KEY_PREFIX}{job_id}")
        return json.loads(raw) if raw else None

    async def _save(self, job: dict) -> None:
        job["updated_at"] = _utc_now_iso()
        await self._redis().set(
            f"{JOB_KEY_PREFIX}{job['job_id']}", json.dumps(job), ex=JOB_TTL_SECONDS
        )

    def _record(
        self,
        job: dict,
        ok: bool,
        ref: Any = None,
        error: Optional[str] = None,
        position: Any = None,
    ) -> None:
        job["processed"] += 1
        if ok:
            job["succeeded"] += 1
        else:
            job["failed"] += 1
            if len(job["errors"]) < MAX_STORED_ERRORS:
                # ``position`` makes a failure addressable even when ``ref`` (e.g.
                # an asset name) is not unique: row number for CSV, index for lists.
                job["errors"].append({"position": position, "ref": ref, "error": error})

    @asynccontextmanager
    async def _tenant_session(self, organization_id: Any):
        """Yield a session bound to the caller's tenant via the RLS GUC.

        Mirrors :func:`app.core.tenant.get_tenant_db` for use outside the request
        lifecycle (background tasks). The GUC is session-scoped (``false``) so it
        survives the per-row commits, then reset in ``finally`` so it cannot leak
        onto a pooled connection.
        """
        async with AsyncSessionLocal() as session:
            await session.execute(
                text("SELECT set_config('app.current_org_id', :org, false)"),
                {"org": str(organization_id)},
            )
            try:
                yield session
            finally:
                await session.execute(
                    text("SELECT set_config('app.current_org_id', '', false)")
                )
                await session.commit()

    @staticmethod
    def _as_uuid(value: Any, field: str) -> uuid.UUID:
        try:
            return uuid.UUID(str(value))
        except (ValueError, TypeError, AttributeError):
            raise _RowError(f"invalid {field}: '{value}'")

    # --- Assets ---------------------------------------------------------------
    async def run_asset_import(
        self, job_id: str, rows: list[dict], organization_id: Any, actor_id: Any
    ) -> None:
        job = await self.get_job(job_id)
        if job is None:
            return
        job["status"] = "running"
        await self._save(job)
        try:
            async with self._tenant_session(organization_id) as session:
                for idx, row in enumerate(rows):
                    row_number = idx + 1  # 1-based data row (header excluded)
                    ref = row.get("id") or row.get("name") or f"row {row_number}"
                    try:
                        await self._import_asset_row(session, row, organization_id)
                        await session.commit()
                        self._record(job, True, ref, position=row_number)
                    except _RowError as exc:
                        await session.rollback()
                        self._record(job, False, ref, str(exc), position=row_number)
                    except Exception as exc:  # don't let one bad row kill the job
                        await session.rollback()
                        logger.warning("bulk_asset_row_failed", ref=str(ref), error=str(exc))
                        self._record(job, False, ref, f"unexpected error: {exc}", position=row_number)
                    await self._save(job)
            job["status"] = "completed"
        except Exception as exc:
            logger.error("bulk_asset_import_failed", job_id=job_id, error=str(exc))
            job["status"] = "failed"
            if len(job["errors"]) < MAX_STORED_ERRORS:
                job["errors"].append({"ref": None, "error": f"job failed: {exc}"})
        await self._save(job)
        await self._audit("bulk_asset_import", job, organization_id, actor_id)

    async def _import_asset_row(self, session, row: dict, organization_id: Any) -> None:
        asset_id = (row.get("id") or "").strip()
        if asset_id:
            await self._update_asset_row(session, asset_id, row, organization_id)
        else:
            await self._create_asset_row(session, row, organization_id)

    async def _create_asset_row(self, session, row: dict, organization_id: Any) -> None:
        name = (row.get("name") or "").strip()
        if not name:
            raise _RowError("name is required to create an asset")
        asset = Asset(
            organization_id=organization_id,
            asset_type_id=await self._resolve_asset_type(session, row),
            workcell_id=await self._resolve_workcell(session, row, organization_id, required=True),
            name=name,
            serial_number=row.get("serial_number") or None,
            vendor=row.get("vendor") or None,
            model=row.get("model") or None,
            is_active=_coerce_bool(row.get("is_active"), True),
        )
        session.add(asset)

    async def _update_asset_row(
        self, session, asset_id: str, row: dict, organization_id: Any
    ) -> None:
        uid = self._as_uuid(asset_id, "id")
        result = await session.execute(
            select(Asset).where(
                Asset.id == uid, Asset.organization_id == organization_id
            )
        )
        asset = result.scalar_one_or_none()
        if asset is None:
            raise _RowError("asset not found in your organization")

        # Only touch columns explicitly present (and non-empty) in the row.
        if row.get("name"):
            asset.name = row["name"].strip()
        for col in ("serial_number", "vendor", "model"):
            if col in row and row[col] != "":
                setattr(asset, col, row[col])
        if row.get("is_active") not in (None, ""):
            asset.is_active = _coerce_bool(row["is_active"])
        if row.get("asset_type") or row.get("asset_type_id"):
            asset.asset_type_id = await self._resolve_asset_type(session, row)
        if row.get("workcell") or row.get("workcell_id"):
            asset.workcell_id = await self._resolve_workcell(session, row, organization_id)
        asset.updated_at = datetime.utcnow()

    async def _resolve_asset_type(self, session, row: dict) -> uuid.UUID:
        """Resolve asset_type by id (wins) or name. AssetType is global (no org)."""
        raw_id = (row.get("asset_type_id") or "").strip()
        if raw_id:
            tid = self._as_uuid(raw_id, "asset_type_id")
            found = await session.execute(select(AssetType.id).where(AssetType.id == tid))
            if found.scalar_one_or_none() is None:
                raise _RowError(f"asset_type_id '{raw_id}' not found")
            return tid

        name = (row.get("asset_type") or "").strip()
        if not name:
            raise _RowError("asset_type or asset_type_id is required")
        result = await session.execute(
            select(AssetType.id).where(func.lower(AssetType.name) == name.lower())
        )
        ids = result.scalars().all()
        if not ids:
            raise _RowError(f"asset type '{name}' not found")
        if len(ids) > 1:
            raise _RowError(
                f"asset type name '{name}' is ambiguous ({len(ids)} matches); use asset_type_id"
            )
        return ids[0]

    async def _resolve_workcell(
        self, session, row: dict, organization_id: Any, required: bool = False
    ) -> Optional[uuid.UUID]:
        """Resolve workcell by id (wins) or name, scoped to the org.

        ``required=True`` on the create path because ``assets.workcell_id`` is
        NOT NULL in the model-built schema; the update path leaves it optional.
        """
        raw_id = (row.get("workcell_id") or "").strip()
        if raw_id:
            wid = self._as_uuid(raw_id, "workcell_id")
            found = await session.execute(
                select(Workcell.id).where(
                    Workcell.id == wid, Workcell.organization_id == organization_id
                )
            )
            if found.scalar_one_or_none() is None:
                raise _RowError(f"workcell_id '{raw_id}' not found in your organization")
            return wid

        name = (row.get("workcell") or "").strip()
        if not name:
            if required:
                raise _RowError("workcell or workcell_id is required")
            return None
        result = await session.execute(
            select(Workcell.id).where(
                func.lower(Workcell.name) == name.lower(),
                Workcell.organization_id == organization_id,
            )
        )
        ids = result.scalars().all()
        if not ids:
            raise _RowError(f"workcell '{name}' not found in your organization")
        if len(ids) > 1:
            raise _RowError(f"workcell name '{name}' is ambiguous; use workcell_id")
        return ids[0]

    # --- Kanban tasks ---------------------------------------------------------
    async def run_kanban_bulk(
        self,
        job_id: str,
        operation: str,
        task_ids: list[str],
        params: dict,
        actor_id: Any,
        organization_id: Any,
    ) -> None:
        job = await self.get_job(job_id)
        if job is None:
            return
        job["status"] = "running"
        await self._save(job)
        try:
            async with AsyncSessionLocal() as session:
                for idx, task_id in enumerate(task_ids):
                    try:
                        await self._kanban_one(
                            session, operation, str(task_id), params, actor_id, organization_id
                        )
                        await session.commit()
                        self._record(job, True, str(task_id), position=idx)
                    except _RowError as exc:
                        await session.rollback()
                        self._record(job, False, str(task_id), str(exc), position=idx)
                    except Exception as exc:
                        await session.rollback()
                        logger.warning("bulk_kanban_row_failed", task_id=str(task_id), error=str(exc))
                        self._record(job, False, str(task_id), f"unexpected error: {exc}", position=idx)
                    await self._save(job)
            job["status"] = "completed"
        except Exception as exc:
            logger.error("bulk_kanban_failed", job_id=job_id, error=str(exc))
            job["status"] = "failed"
        await self._save(job)
        await self._audit(f"bulk_kanban_{operation}", job, organization_id, actor_id)

    async def _kanban_one(
        self,
        session,
        operation: str,
        task_id: str,
        params: dict,
        actor_id: Any,
        organization_id: Any,
    ) -> None:
        # Tasks have no organization_id column; scope via their board's org so a
        # caller cannot move/assign/delete another tenant's task by guessing ids.
        result = await session.execute(
            select(Task)
            .join(TaskBoard, Task.board_id == TaskBoard.id)
            .where(Task.id == task_id, TaskBoard.organization_id == organization_id)
        )
        task = result.scalar_one_or_none()
        if task is None:
            raise _RowError("task not found in your organization")
        now = datetime.utcnow()

        if operation == "move":
            target_column_id = params.get("target_column_id")
            if not target_column_id:
                raise _RowError("target_column_id is required for move")
            col_result = await session.execute(
                select(TaskColumn).where(TaskColumn.id == target_column_id)
            )
            column = col_result.scalar_one_or_none()
            if column is None:
                raise _RowError("target column not found")
            if column.board_id != task.board_id:
                raise _RowError("cannot move task to a different board")

            if params.get("position") is not None:
                task.position = params["position"]
            else:
                max_pos = (
                    await session.execute(
                        select(func.max(Task.position)).where(Task.column_id == column.id)
                    )
                ).scalar() or 0
                task.position = max_pos + 1
            task.column_id = column.id
            if column.column_type == "in_progress" and task.status != "in_progress":
                task.status = "in_progress"
                task.actual_start = task.actual_start or now
            elif column.column_type == "done":
                # Mirror the single-task completion metadata set by kanban.py's
                # move_task/complete_task so a bulk-completed task is indistinguishable.
                task.status = "completed"
                task.progress_percent = 100
                task.actual_end = now
                task.completed_at = now
                task.completed_by = actor_id
            task.updated_at = now

        elif operation == "assign":
            assignee = params.get("assigned_to")
            if not assignee:
                raise _RowError("assigned_to is required for assign")
            assignee_id = self._as_uuid(assignee, "assigned_to")
            found = await session.execute(
                select(User.id).where(
                    User.id == assignee_id, User.organization_id == organization_id
                )
            )
            if found.scalar_one_or_none() is None:
                raise _RowError("assignee not found in your organization")
            task.assigned_to = assignee_id
            task.assigned_by = actor_id
            task.assigned_at = now
            task.updated_at = now

        elif operation == "delete":
            # Soft delete: move to the board's "done" column and mark cancelled,
            # mirroring the single-task delete endpoint in kanban.py.
            done_col = (
                await session.execute(
                    select(TaskColumn).where(
                        and_(
                            TaskColumn.board_id == task.board_id,
                            TaskColumn.column_type == "done",
                        )
                    )
                )
            ).scalar_one_or_none()
            if done_col is not None:
                task.column_id = done_col.id
            task.status = "cancelled"
            task.updated_at = now

        else:
            raise _RowError(f"unknown operation '{operation}'")

    # --- Alarms ---------------------------------------------------------------
    async def run_alarm_acknowledge(
        self,
        job_id: str,
        alarm_ids: list[str],
        comment: Optional[str],
        actor_id: Any,
        organization_id: Any,
    ) -> None:
        job = await self.get_job(job_id)
        if job is None:
            return
        job["status"] = "running"
        await self._save(job)
        try:
            # Alarms carry no organization_id; we scope via a join to assets,
            # which is RLS-protected, so a tenant-bound session is required.
            async with self._tenant_session(organization_id) as session:
                for idx, alarm_id in enumerate(alarm_ids):
                    try:
                        await self._ack_one(session, str(alarm_id), comment, actor_id, organization_id)
                        await session.commit()
                        self._record(job, True, str(alarm_id), position=idx)
                    except _RowError as exc:
                        await session.rollback()
                        self._record(job, False, str(alarm_id), str(exc), position=idx)
                    except Exception as exc:
                        await session.rollback()
                        logger.warning("bulk_alarm_row_failed", alarm_id=str(alarm_id), error=str(exc))
                        self._record(job, False, str(alarm_id), f"unexpected error: {exc}", position=idx)
                    await self._save(job)
            job["status"] = "completed"
        except Exception as exc:
            logger.error("bulk_alarm_ack_failed", job_id=job_id, error=str(exc))
            job["status"] = "failed"
        await self._save(job)
        await self._audit("bulk_alarm_acknowledge", job, organization_id, actor_id)

    async def _ack_one(self, session, alarm_id: str, comment: Optional[str], actor_id: Any, organization_id: Any) -> None:
        aid = self._as_uuid(alarm_id, "alarm_id")
        result = await session.execute(
            select(Alarm)
            .join(Asset, Alarm.asset_id == Asset.id)
            .where(and_(Alarm.id == aid, Asset.organization_id == organization_id))
        )
        alarm = result.scalar_one_or_none()
        if alarm is None:
            raise _RowError("alarm not found in your organization")
        if alarm.is_acknowledged:
            raise _RowError("alarm already acknowledged")
        alarm.is_acknowledged = True
        alarm.acknowledged_by = str(actor_id)  # acknowledged_by is String(36)
        alarm.acknowledged_at = datetime.utcnow()
        if comment:
            alarm.acknowledged_comment = comment

    # --- Registry items -------------------------------------------------------
    async def run_registry_items(
        self,
        job_id: str,
        registry_id: Any,
        items: list[dict],
        actor_id: Any,
        organization_id: Any,
    ) -> None:
        job = await self.get_job(job_id)
        if job is None:
            return
        job["status"] = "running"
        await self._save(job)
        try:
            async with AsyncSessionLocal() as session:
                registry = (
                    await session.execute(
                        select(ActionableRegistry).where(
                            and_(
                                ActionableRegistry.id == registry_id,
                                ActionableRegistry.organization_id == organization_id,
                            )
                        )
                    )
                ).scalar_one_or_none()
                if registry is None:
                    job["status"] = "failed"
                    if len(job["errors"]) < MAX_STORED_ERRORS:
                        job["errors"].append(
                            {"ref": str(registry_id), "error": "registry not found in your organization"}
                        )
                    await self._save(job)
                    await self._audit("bulk_registry_items", job, organization_id, actor_id)
                    return

                for idx, item in enumerate(items):
                    ref = item.get("item_code") or f"item {idx + 1}"
                    try:
                        session.add(ActionableRegistryItem(registry_id=registry_id, **item))
                        await session.commit()
                        self._record(job, True, ref, position=idx)
                    except Exception as exc:
                        await session.rollback()
                        logger.warning("bulk_registry_item_failed", ref=str(ref), error=str(exc))
                        self._record(job, False, ref, f"could not create item: {exc}", position=idx)
                    await self._save(job)
            job["status"] = "completed"
        except Exception as exc:
            logger.error("bulk_registry_items_failed", job_id=job_id, error=str(exc))
            job["status"] = "failed"
        await self._save(job)
        await self._audit("bulk_registry_items", job, organization_id, actor_id)

    # --- Audit ----------------------------------------------------------------
    async def _audit(self, action: str, job: dict, organization_id: Any, actor_id: Any) -> None:
        """Record a bulk action in audit_logs (non-fatal on failure).

        hash_chain is filled by the audit_log_hash_chain_trigger (migration 009).
        Mirrors FeatureFlagService._audit.
        """
        details = {
            "job_id": job["job_id"],
            "type": job["type"],
            "total": job["total"],
            "succeeded": job["succeeded"],
            "failed": job["failed"],
            "status": job["status"],
        }
        try:
            async with AsyncSessionLocal() as session:
                await session.execute(
                    text(
                        """
                        INSERT INTO audit_logs
                            (user_id, organization_id, action, resource_type, details)
                        VALUES
                            (:user_id, :organization_id, :action, 'bulk_operation',
                             CAST(:details AS JSONB))
                        """
                    ),
                    {
                        "user_id": str(actor_id) if actor_id else None,
                        "organization_id": str(organization_id) if organization_id else None,
                        "action": action,
                        "details": json.dumps(details),
                    },
                )
                await session.commit()
        except Exception as exc:
            logger.error("bulk_audit_failed", action=action, error=str(exc))

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


bulk_processor = BulkProcessor()
