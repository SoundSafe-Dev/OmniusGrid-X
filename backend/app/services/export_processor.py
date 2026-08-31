"""Data export processor (Task 5).

On-demand exports across telemetry (CSV), Kanban tasks + registries (Excel), and
OEE analytics (PDF). Mirrors the Task 1 / Task 7 service conventions
(``feature_flags`` / ``bulk_processor``):

* Small exports are built in-memory and returned synchronously by the API layer.
* Large telemetry pulls run as a Redis-tracked job on a FastAPI ``BackgroundTask``
  (the same Redis job store the bulk operations use), streaming the rows to a temp
  CSV file the client downloads once the job completes. The sync/async switch is by
  row count (:data:`SYNC_ROW_CAP`).
* Custom column selection: each resource exposes a fixed allowlist of exportable
  columns; callers and saved templates may select an ordered subset.
* Tenancy mirrors each domain's read endpoint; the organization is always derived
  from the authenticated user, never client input. Telemetry sets the
  ``app.current_org_id`` RLS GUC (like :func:`app.core.tenant.get_tenant_db`) since
  it runs outside the request session.
* Every export is recorded in ``audit_logs`` (``resource_type='export'``), mirroring
  :meth:`BulkProcessor._audit`.

Scheduled execution and email delivery live in ``export_delivery`` and the
dedicated Redpanda worker.
"""

import csv
import io
import json

from fastapi import HTTPException
from redis.exceptions import RedisError
import os
import tempfile
import time
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from typing import Any, Optional, Sequence

import redis.asyncio as redis
import structlog
from openpyxl import Workbook
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.lib.units import cm
from reportlab.platypus import (
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)
from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.services.export_store import get_export_store, export_object_key
from app.core.tenant import tenant_session
from app.db.database import AsyncSessionLocal
from app.db.models import (
    ActionableRegistry,
    ActionableRegistryItem,
    Asset,
    Task,
    TaskBoard,
    TaskColumn,
    Telemetry,
)
from app.services.oee_calculator import OEEMetrics

logger = structlog.get_logger()

JOB_KEY_PREFIX = "export_job:"
JOB_TTL_SECONDS = 24 * 60 * 60
SYNC_ROW_CAP = 50_000        # telemetry rows streamed inline; above this -> async job
MAX_EXPORT_ROWS = 2_000_000  # hard ceiling for a single async export
EXPORT_DIR = settings.EXPORT_STORAGE_PATH or os.path.join(
    tempfile.gettempdir(), "omniusgrid_exports"
)

# Ordered allowlists of exportable columns per resource. List order is the default
# column order; a ``columns`` request may pass an ordered subset of these names.
TELEMETRY_COLUMNS = [
    "time", "metric_name", "value", "unit", "packml_state", "sequence_num", "asset_id",
]
TASK_COLUMNS = [
    "id", "title", "task_type", "priority", "status", "column", "assigned_to",
    "due_date", "planned_start", "actual_start", "actual_end", "progress_percent",
    "time_logged_minutes", "tags", "created_at", "updated_at",
]
REGISTRY_COLUMNS = [
    "id", "registry_name", "registry_type", "registry_category", "priority_level",
    "is_active", "is_compliance", "frequency", "next_due_date", "last_completed_date",
    "compliance_score", "created_at",
]
REGISTRY_ITEM_COLUMNS = [
    "id", "item_code", "item_name", "severity_level", "is_required", "is_active",
    "verification_method", "estimated_effort_minutes", "last_completed_at",
    "next_due_at", "completion_frequency", "compliance_score", "risk_score",
]

EXPORT_DEFINITIONS = {
    "telemetry": {
        "format": "csv",
        "columns": TELEMETRY_COLUMNS,
        "filters": {"asset_id", "metric_name", "start_time", "end_time"},
        "required_filters": {"asset_id"},
    },
    "kanban_tasks": {
        "format": "xlsx",
        "columns": TASK_COLUMNS,
        "filters": {"status"},
        "required_filters": set(),
    },
    "registries": {
        "format": "xlsx",
        "columns": REGISTRY_COLUMNS,
        "filters": {"registry_type"},
        "required_filters": set(),
    },
    "registry_items": {
        "format": "xlsx",
        "columns": REGISTRY_ITEM_COLUMNS,
        "filters": {"registry_id"},
        "required_filters": {"registry_id"},
    },
    "oee_asset": {
        "format": "pdf",
        "columns": [],
        "filters": {"asset_id", "time_window_hours"},
        "required_filters": {"asset_id"},
    },
    "oee_summary": {
        "format": "pdf",
        "columns": [],
        "filters": {"time_window_hours"},
        "required_filters": set(),
    },
}



def _job_state_unavailable(exc: Exception) -> HTTPException:
    """A 503 that says which dependency is down, not a 500 that says we are broken.

    FS-855. Job state lives in Redis and nothing else holds it, so an unreachable Redis is
    a dependency outage rather than a defect here — and the distinction matters to the
    caller, who should retry rather than report a bug.
    """
    logger.warning("job_state_unavailable", error=str(exc)[:200])
    return HTTPException(
        status_code=503,
        detail=(
            "Job state is temporarily unavailable. This is a dependency outage, not a "
            "rejection of your request; the work itself is unaffected. Retry shortly."
        ),
    )

class ExportError(Exception):
    """A bad export request (invalid column, range, etc.) -> 400 at the API layer."""


def select_columns(allowlist: Sequence[str], requested: Optional[str]) -> list[str]:
    """Resolve the ``columns`` query param against a resource's allowlist.

    ``None``/empty returns the full default ordering. Otherwise the caller's
    comma-separated, ordered subset is returned; an unknown column raises
    :class:`ExportError` so the API can fast-fail with a 400.
    """
    if not requested:
        return list(allowlist)
    chosen = [c.strip() for c in requested.split(",") if c.strip()]
    if not chosen:
        return list(allowlist)
    allowed = set(allowlist)
    unknown = [c for c in chosen if c not in allowed]
    if unknown:
        raise ExportError(
            f"Unknown column(s): {', '.join(unknown)}. "
            f"Allowed: {', '.join(allowlist)}"
        )
    return chosen


def validate_export_configuration(
    export_type: str,
    export_format: str,
    columns: Optional[Sequence[str]],
    filters: Optional[dict[str, Any]],
) -> tuple[list[str], dict[str, Any]]:
    """Validate and normalize a saved export template configuration."""
    definition = EXPORT_DEFINITIONS.get(export_type)
    if definition is None:
        raise ExportError(
            f"Unknown export_type '{export_type}'. "
            f"Allowed: {', '.join(sorted(EXPORT_DEFINITIONS))}"
        )

    expected_format = definition["format"]
    if export_format != expected_format:
        raise ExportError(
            f"export_type '{export_type}' requires format '{expected_format}'"
        )

    chosen_columns = list(columns or definition["columns"])
    if definition["columns"]:
        unknown_columns = [c for c in chosen_columns if c not in definition["columns"]]
        if unknown_columns:
            raise ExportError(
                f"Unknown column(s): {', '.join(unknown_columns)}. "
                f"Allowed: {', '.join(definition['columns'])}"
            )
    elif chosen_columns:
        raise ExportError(f"export_type '{export_type}' does not support column selection")

    normalized_filters = dict(filters or {})
    unknown_filters = sorted(set(normalized_filters) - definition["filters"])
    if unknown_filters:
        raise ExportError(
            f"Unknown filter(s): {', '.join(unknown_filters)}. "
            f"Allowed: {', '.join(sorted(definition['filters'])) or 'none'}"
        )
    missing_filters = sorted(
        key for key in definition["required_filters"] if not normalized_filters.get(key)
    )
    if missing_filters:
        raise ExportError(f"Missing required filter(s): {', '.join(missing_filters)}")

    for key in ("asset_id", "registry_id"):
        if key in normalized_filters:
            try:
                normalized_filters[key] = str(uuid.UUID(str(normalized_filters[key])))
            except (TypeError, ValueError, AttributeError):
                raise ExportError(f"filter '{key}' must be a UUID")

    if "time_window_hours" in normalized_filters:
        try:
            hours = float(normalized_filters["time_window_hours"])
        except (TypeError, ValueError):
            raise ExportError("filter 'time_window_hours' must be a number")
        if not 0.5 <= hours <= 24:
            raise ExportError("filter 'time_window_hours' must be between 0.5 and 24")
        normalized_filters["time_window_hours"] = hours

    return chosen_columns, normalized_filters


def _cell(value: Any) -> Any:
    """Normalize a model value for a CSV/Excel cell."""
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (list, dict)):
        return json.dumps(value, default=str)
    if isinstance(value, uuid.UUID):
        return str(value)
    if isinstance(value, str) and value.startswith(("=", "+", "-", "@")):
        return f"'{value}"
    return value


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_datetime(value: Any) -> Optional[datetime]:
    if not value:
        return None
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _write_bytes(path: str, content: bytes) -> None:
    with open(path, "wb") as fh:
        fh.write(content)


class ExportTooLarge(Exception):
    """An export whose row count exceeds `MAX_EXPORT_ROWS` (FS-842).

    Raised BEFORE the spreadsheet is built, because building it is the unbounded
    allocation being prevented. Carries the numbers so the caller can say which limit was
    hit and by how much rather than "export failed".
    """

    def __init__(self, rows: int, limit: int, what: str) -> None:
        self.rows = rows
        self.limit = limit
        self.what = what
        super().__init__(
            f"This {what} export would contain {rows:,} rows, above the limit of "
            f"{limit:,}. Narrow the filters or the date range and try again."
        )


def _guard_row_count(rows: list, what: str) -> list:
    """Refuse a result set too large to turn into a spreadsheet in memory.

    Checked on the materialised list rather than with a COUNT: a separate COUNT is a
    second round trip AND a race — the count and the fetch see different snapshots — and
    the rows are already in memory by the time anything can be decided. What this prevents
    is the NEXT allocation, which is the expensive one: `_build_xlsx` holds the whole
    workbook, its XML, and the compressed output at once, several times the size of the
    rows themselves.

    Bounding the query with LIMIT instead would silently TRUNCATE an export, which for a
    compliance artefact is the worst available outcome: a file that looks complete and is
    not.
    """
    limit = settings.MAX_EXPORT_ROWS
    if limit > 0 and len(rows) > limit:
        raise ExportTooLarge(len(rows), limit, what)
    return rows


class ExportProcessor:
    """CSV / Excel / PDF builders + Redis-tracked async telemetry export."""

    def __init__(self) -> None:
        self._client: Optional[redis.Redis] = None

    def _redis(self) -> redis.Redis:
        if self._client is None:
            from app.core.redis_client import get_redis

            self._client = get_redis()
        return self._client

    @asynccontextmanager
    async def _tenant_session(self, organization_id: Any):
        """Yield a session bound to the caller's tenant via the RLS GUC.

        DELEGATES rather than mirrors. This was a hand-rolled copy under a docstring
        reading *"Mirrors app.core.tenant.get_tenant_db"* — the same phrase the test
        harness's copies carried, and the same reason
        :func:`app.core.tenant.tenant_session` was extracted: a mirror reproduces the
        original's defects and then keeps them after the original is fixed.

        The copy also differed in a way that mattered. It used a SESSION-scoped GUC
        (``set_config(..., false)``) so the binding would survive intermediate commits,
        and reset it in ``finally`` so it could not leak onto a pooled connection —
        which holds only as long as that reset runs. ``tenant_session`` re-asserts the
        tenant on every ``after_begin`` instead, so the binding survives commits with a
        TRANSACTION-scoped GUC. Nothing can outlive the transaction, so there is nothing
        to reset and no path where a leak depends on cleanup running.
        """
        async with tenant_session(organization_id) as session:
            yield session

    # --- Telemetry ------------------------------------------------------------
    @staticmethod
    def _telemetry_query(asset_id: Any, start: datetime, end: datetime, metric: Optional[str]):
        # Select explicit columns (not the whole entity): only what we export, and
        # it avoids the ORM's drifted ``Telemetry.meta_data`` attribute (the live
        # column is ``metadata``), which a ``select(Telemetry)`` would reference.
        q = select(
            Telemetry.time,
            Telemetry.metric_name,
            Telemetry.value,
            Telemetry.unit,
            Telemetry.packml_state,
            Telemetry.sequence_num,
            Telemetry.asset_id,
        ).where(
            Telemetry.asset_id == asset_id,
            Telemetry.time >= start,
            Telemetry.time <= end,
        )
        if metric:
            q = q.where(Telemetry.metric_name == metric)
        return q.order_by(Telemetry.time.asc())

    @staticmethod
    def _telemetry_row(row) -> dict:
        return {
            "time": row.time,
            "metric_name": row.metric_name,
            "value": row.value,
            "unit": row.unit,
            "packml_state": row.packml_state,
            "sequence_num": row.sequence_num,
            "asset_id": row.asset_id,
        }

    async def count_telemetry(
        self, session: AsyncSession, asset_id: Any, start: datetime, end: datetime,
        metric: Optional[str],
    ) -> int:
        """Count matching telemetry rows (drives the sync-stream vs async-job switch).

        Uses the request's tenant-scoped session so any RLS policy is honored.
        """
        sub = self._telemetry_query(asset_id, start, end, metric).order_by(None).subquery()
        result = await session.execute(select(func.count()).select_from(sub))
        return int(result.scalar() or 0)

    async def stream_telemetry_csv(
        self, organization_id: Any, asset_id: Any, start: datetime, end: datetime,
        metric: Optional[str], columns: list[str],
    ):
        """Async generator yielding CSV text, one row at a time (bounded memory).

        Opens its own tenant-scoped session because a ``StreamingResponse`` body is
        produced after the request's own dependency session may have closed.
        """
        buffer = io.StringIO()
        writer = csv.writer(buffer)

        def _flush() -> str:
            chunk = buffer.getvalue()
            buffer.seek(0)
            buffer.truncate(0)
            return chunk

        writer.writerow(columns)
        yield _flush()
        async with self._tenant_session(organization_id) as session:
            result = await session.stream(
                self._telemetry_query(asset_id, start, end, metric)
            )
            async for row in result:
                d = self._telemetry_row(row)
                writer.writerow([_cell(d[c]) for c in columns])
                yield _flush()

    async def run_telemetry_export(
        self, job_id: str, organization_id: Any, asset_id: Any, start: datetime,
        end: datetime, metric: Optional[str], columns: list[str], filename: str,
        actor_id: Any,
    ) -> None:
        """Background job: stream telemetry to a temp CSV file, tracking progress."""
        job = await self.get_job(job_id)
        if job is None:
            return
        job["status"] = "running"
        await self._save(job)
        os.makedirs(EXPORT_DIR, exist_ok=True)
        path = os.path.join(EXPORT_DIR, f"{job_id}.csv")
        n = 0
        try:
            async with self._tenant_session(organization_id) as session:
                result = await session.stream(
                    self._telemetry_query(asset_id, start, end, metric)
                )
                with open(path, "w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(columns)
                    async for row in result:
                        d = self._telemetry_row(row)
                        writer.writerow([_cell(d[c]) for c in columns])
                        n += 1
                        if n % 5000 == 0:
                            job["processed"] = n
                            await self._save(job)
                        if n >= MAX_EXPORT_ROWS:
                            break
            job["processed"] = n
            job["succeeded"] = n
            job["file_path"] = path
            job["filename"] = filename
            job["status"] = "completed"
            # When object storage is on, the download is served by a different pod,
            # so push the artifact to S3. Local file stays as a same-pod fast path.
            store = get_export_store()
            if store.enabled:
                try:
                    await store.ensure_bucket()
                    await store.upload_file(export_object_key(str(job_id), "csv"), path)
                except Exception as exc:  # noqa: BLE001 - artifact still on local disk
                    logger.error(
                        "export_object_upload_failed", job_id=str(job_id), error=str(exc)
                    )
        except Exception as exc:  # noqa: BLE001 - record and surface via the job
            logger.error("export_telemetry_failed", job_id=job_id, error=str(exc))
            job["status"] = "failed"
            job["errors"] = [{"error": str(exc)}]
            if os.path.exists(path):
                try:
                    os.remove(path)
                except OSError:
                    pass
        await self._save(job)
        await self._audit("export_telemetry", job, organization_id, actor_id)
        self._cleanup_old_exports()

    # --- Excel (Kanban tasks / registries) ------------------------------------
    @staticmethod
    def _build_xlsx(sheet_title: str, columns: list[str], rows: list[dict]) -> bytes:
        wb = Workbook(write_only=True)  # write-only: streams rows, low memory
        ws = wb.create_sheet(title=sheet_title)
        ws.append(columns)
        for r in rows:
            ws.append([_cell(r.get(c)) for c in columns])
        bio = io.BytesIO()
        wb.save(bio)
        return bio.getvalue()

    @staticmethod
    def _task_row(task: Task, column_name: Optional[str]) -> dict:
        return {
            "id": task.id,
            "title": task.title,
            "task_type": task.task_type,
            "priority": task.priority,
            "status": task.status,
            "column": column_name,
            "assigned_to": task.assigned_to,
            "due_date": task.due_date,
            "planned_start": task.planned_start,
            "actual_start": task.actual_start,
            "actual_end": task.actual_end,
            "progress_percent": task.progress_percent,
            "time_logged_minutes": task.time_logged_minutes,
            "tags": task.tags,
            "created_at": task.created_at,
            "updated_at": task.updated_at,
        }

    async def export_tasks_xlsx(
        self, session: AsyncSession, organization_id: Any, columns: list[str],
        status: Optional[str] = None,
    ) -> tuple[bytes, int]:
        """All Kanban tasks whose board belongs to the org (joins board for scope)."""
        q = (
            select(Task, TaskColumn.name)
            .join(TaskBoard, Task.board_id == TaskBoard.id)
            .join(TaskColumn, Task.column_id == TaskColumn.id, isouter=True)
            .where(TaskBoard.organization_id == organization_id)
            .order_by(Task.created_at.desc())
        )
        if status:
            q = q.where(Task.status == status)
        result = await session.execute(q)
        rows = _guard_row_count(
            [self._task_row(task, column_name) for task, column_name in result.all()],
            "tasks",
        )
        return self._build_xlsx("Tasks", columns, rows), len(rows)

    @staticmethod
    def _registry_row(r: ActionableRegistry) -> dict:
        return {
            "id": r.id,
            "registry_name": r.registry_name,
            "registry_type": r.registry_type,
            "registry_category": r.registry_category,
            "priority_level": r.priority_level,
            "is_active": r.is_active,
            "is_compliance": r.is_compliance,
            "frequency": r.frequency,
            "next_due_date": r.next_due_date,
            "last_completed_date": r.last_completed_date,
            "compliance_score": r.compliance_score,
            "created_at": r.created_at,
        }

    async def export_registries_xlsx(
        self, session: AsyncSession, organization_id: Any, columns: list[str],
        registry_type: Optional[str] = None,
    ) -> tuple[bytes, int]:
        q = select(ActionableRegistry).where(
            ActionableRegistry.organization_id == organization_id
        )
        if registry_type:
            q = q.where(ActionableRegistry.registry_type == registry_type)
        q = q.order_by(ActionableRegistry.created_at.desc())
        result = await session.execute(q)
        rows = _guard_row_count(
            [self._registry_row(r) for r in result.scalars().all()], "registries"
        )
        return self._build_xlsx("Registries", columns, rows), len(rows)

    @staticmethod
    def _registry_item_row(i: ActionableRegistryItem) -> dict:
        return {
            "id": i.id,
            "item_code": i.item_code,
            "item_name": i.item_name,
            "severity_level": i.severity_level,
            "is_required": i.is_required,
            "is_active": i.is_active,
            "verification_method": i.verification_method,
            "estimated_effort_minutes": i.estimated_effort_minutes,
            "last_completed_at": i.last_completed_at,
            "next_due_at": i.next_due_at,
            "completion_frequency": i.completion_frequency,
            "compliance_score": i.compliance_score,
            "risk_score": i.risk_score,
        }

    async def export_registry_items_xlsx(
        self, session: AsyncSession, registry_id: Any, columns: list[str],
    ) -> tuple[bytes, int]:
        """Items for one registry (the API verifies the registry's org first)."""
        result = await session.execute(
            select(ActionableRegistryItem)
            .where(ActionableRegistryItem.registry_id == registry_id)
            .order_by(ActionableRegistryItem.item_code.asc())
        )
        rows = _guard_row_count(
            [self._registry_item_row(i) for i in result.scalars().all()],
            "registry items",
        )
        return self._build_xlsx("Registry Items", columns, rows), len(rows)

    # --- PDF (OEE) ------------------------------------------------------------
    @staticmethod
    def _table_style() -> TableStyle:
        return TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), colors.HexColor("#1F2937")),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("GRID", (0, 0), (-1, -1), 0.4, colors.HexColor("#9CA3AF")),
            ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#F3F4F6")]),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ])

    def build_oee_pdf(
        self, asset_name: str, asset_id: str, window_hours: float, oee: OEEMetrics,
    ) -> bytes:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=A4, title=f"OEE Report - {asset_name}",
            leftMargin=2 * cm, rightMargin=2 * cm, topMargin=2 * cm, bottomMargin=2 * cm,
        )
        styles = getSampleStyleSheet()
        elems = [
            Paragraph("OEE Report", styles["Title"]),
            Paragraph(f"Asset: {asset_name} ({asset_id})", styles["Normal"]),
            Paragraph(
                f"Window: last {window_hours:g} h &middot; "
                f"Generated {_utc_now_iso()}",
                styles["Normal"],
            ),
            Spacer(1, 0.6 * cm),
        ]
        data = [
            ["Metric", "Value"],
            ["OEE", f"{oee.oee:.1f}%"],
            ["Availability", f"{oee.availability:.1f}%"],
            ["Performance", f"{oee.performance:.1f}%"],
            ["Quality", f"{oee.quality:.1f}%"],
            ["Runtime (min)", f"{oee.runtime_minutes:.1f}"],
            ["Planned downtime (min)", f"{oee.planned_downtime_minutes:.1f}"],
            ["Unplanned downtime (min)", f"{oee.unplanned_downtime_minutes:.1f}"],
            ["Total parts", oee.total_parts],
            ["Good parts", oee.good_parts],
            ["Rejected parts", oee.rejected_parts],
        ]
        table = Table(data, hAlign="LEFT", colWidths=[8 * cm, 6 * cm])
        table.setStyle(self._table_style())
        elems.append(table)
        doc.build(elems)
        return buf.getvalue()

    def build_oee_summary_pdf(self, rows: list[dict]) -> bytes:
        buf = io.BytesIO()
        doc = SimpleDocTemplate(
            buf, pagesize=landscape(A4), title="OEE Fleet Summary",
            leftMargin=1.5 * cm, rightMargin=1.5 * cm, topMargin=1.5 * cm, bottomMargin=1.5 * cm,
        )
        styles = getSampleStyleSheet()
        header = [
            "Asset", "OEE %", "Availability %", "Performance %", "Quality %",
            "Runtime (min)", "Status",
        ]
        # NOT `_cell`, which is the CSV/Excel normaliser and maps None to "". A blank in
        # a spreadsheet reads as missing; a blank in a printed table reads as an
        # omission, and the reader supplies the zero themselves. An em dash refuses that.
        # A real 0 still prints as 0 — an asset that genuinely produced nothing is a
        # finding, and hiding it behind a dash is the opposite defect, so the
        # substitution is keyed on None and never on falsiness.
        def _report_cell(value):
            return "\u2014" if value is None else value

        data = [header] + [
            [
                r.get("asset_name"), _report_cell(r.get("oee")),
                _report_cell(r.get("availability")), _report_cell(r.get("performance")),
                _report_cell(r.get("quality")), _report_cell(r.get("runtime_minutes")),
                r.get("status"),
            ]
            for r in rows
        ]
        table = Table(data, repeatRows=1)
        table.setStyle(self._table_style())
        elems = [
            Paragraph("OEE Fleet Summary", styles["Title"]),
            Paragraph(
                f"{len(rows)} asset(s) &middot; Generated {_utc_now_iso()}",
                styles["Normal"],
            ),
            Spacer(1, 0.6 * cm),
            table,
        ]
        doc.build(elems)
        return buf.getvalue()

    async def generate_scheduled_export(
        self,
        export_type: str,
        columns: list[str],
        filters: dict[str, Any],
        organization_id: Any,
        job_id: Any,
    ) -> tuple[str, str]:
        """Generate one saved template to shared storage for email delivery."""
        os.makedirs(EXPORT_DIR, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        extension = EXPORT_DEFINITIONS[export_type]["format"]
        filename = f"{export_type}_{stamp}.{extension}"
        path = os.path.join(EXPORT_DIR, f"{job_id}.{extension}")

        async with self._tenant_session(organization_id) as session:
            if export_type == "telemetry":
                asset_id = uuid.UUID(filters["asset_id"])
                end = _parse_datetime(filters.get("end_time")) or datetime.now(timezone.utc)
                start = _parse_datetime(filters.get("start_time")) or (end - timedelta(hours=24))
                metric = filters.get("metric_name")
                with open(path, "w", newline="", encoding="utf-8") as fh:
                    writer = csv.writer(fh)
                    writer.writerow(columns)
                    result = await session.stream(
                        self._telemetry_query(asset_id, start, end, metric)
                    )
                    async for row in result:
                        values = self._telemetry_row(row)
                        writer.writerow([_cell(values[c]) for c in columns])
            elif export_type == "kanban_tasks":
                content, _ = await self.export_tasks_xlsx(
                    session, organization_id, columns, filters.get("status")
                )
                _write_bytes(path, content)
            elif export_type == "registries":
                content, _ = await self.export_registries_xlsx(
                    session, organization_id, columns, filters.get("registry_type")
                )
                _write_bytes(path, content)
            elif export_type == "registry_items":
                registry_id = uuid.UUID(filters["registry_id"])
                registry = (
                    await session.execute(
                        select(ActionableRegistry.id).where(
                            ActionableRegistry.id == registry_id,
                            ActionableRegistry.organization_id == organization_id,
                        )
                    )
                ).scalar_one_or_none()
                if registry is None:
                    raise ExportError("Registry not found")
                content, _ = await self.export_registry_items_xlsx(
                    session, registry_id, columns
                )
                _write_bytes(path, content)
            elif export_type == "oee_asset":
                asset_id = uuid.UUID(filters["asset_id"])
                asset = (
                    await session.execute(
                        select(Asset).where(
                            Asset.id == asset_id,
                            Asset.organization_id == organization_id,
                        )
                    )
                ).scalar_one_or_none()
                if asset is None:
                    raise ExportError("Asset not found")
                hours = float(filters.get("time_window_hours", 1))
                from app.services.oee_calculator import oee_calculator

                metrics = await oee_calculator.calculate_oee(str(asset_id), hours)
                _write_bytes(
                    path,
                    self.build_oee_pdf(
                        asset.name, str(asset_id), hours, metrics
                    ),
                )
            elif export_type == "oee_summary":
                hours = float(filters.get("time_window_hours", 24))
                assets = (
                    await session.execute(
                        select(Asset).where(
                            Asset.organization_id == organization_id,
                            Asset.is_active == True,  # noqa: E712
                        )
                    )
                ).scalars().all()
                from app.services.oee_calculator import oee_calculator

                # FS-842. Guarded on the ASSET list rather than on the finished rows: the
                # loop below calls `calculate_oee` once per asset, so refusing here also
                # avoids N round trips for an export that would be refused anyway. This
                # builder was missed on the first pass and found by the coverage test —
                # it accumulates into `rows` rather than a comprehension, so a check
                # looking for `rows = [...]` saw an empty initialiser and moved on.
                assets = _guard_row_count(list(assets), "OEE summary")

                rows = []
                for asset in assets:
                    metrics = await oee_calculator.calculate_oee(
                        str(asset.id), hours
                    )
                    rows.append({
                        "asset_name": asset.name,
                        "oee": metrics.oee,
                        "availability": metrics.availability,
                        "performance": metrics.performance,
                        "quality": metrics.quality,
                        "runtime_minutes": metrics.runtime_minutes,
                        "status": "healthy" if metrics.oee > 60 else "at_risk",
                    })
                _write_bytes(path, self.build_oee_summary_pdf(rows))
            else:
                raise ExportError(f"Unsupported scheduled export type '{export_type}'")

        # In a multi-pod deployment the API serves this download from a different
        # pod than the worker that wrote it, so a pod-local file is unreachable.
        # Upload to object storage (when EXPORT_USE_S3 is on) so any pod can
        # stream it; the local file stays as a same-pod cache. No-op otherwise.
        store = get_export_store()
        if store.enabled:
            try:
                await store.ensure_bucket()
                await store.upload_file(export_object_key(str(job_id), extension), path)
            except Exception as exc:  # noqa: BLE001
                # A store failure must not lose the artifact — it still exists on
                # the worker's disk; log loudly so delivery/monitoring can react.
                logger.error(
                    "export_object_upload_failed", job_id=str(job_id), error=str(exc)
                )

        return path, filename

    # --- Job lifecycle (Redis) ------------------------------------------------
    async def create_job(
        self, job_type: str, total: int, organization_id: Any, actor_id: Any,
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
            "file_path": None,
            "filename": None,
            "created_at": _utc_now_iso(),
            "updated_at": _utc_now_iso(),
            "organization_id": str(organization_id) if organization_id else None,
            "actor_id": str(actor_id) if actor_id else None,
        }
        await self._save(job)
        return job

    #: FS-855. Redis is NOT a cache for this service — it is where job state lives, and
    #: nothing else holds it. Four other consumers degrade safely (rate limiting, feature
    #: flags, idempotency and the correlation job store all have in-memory fallbacks); this
    #: one and the export processor do not, which is what makes Redis a single point of
    #: failure for real work rather than an optimisation.
    #:
    #: An in-memory fallback would be WORSE here, not better: job state is polled, and with
    #: more than one replica the poll lands on a pod that never saw the job — so the caller
    #: is told their import does not exist rather than that the platform is degraded. A
    #: silent wrong answer beats no answer only if nobody acts on it.
    #:
    #: So the failure is made legible instead: 503 with a reason, not a 500. Moving this
    #: state to Postgres is the real fix and is a larger change than a translation.
    async def get_job(self, job_id: str) -> Optional[dict]:
        try:
            raw = await self._redis().get(f"{JOB_KEY_PREFIX}{job_id}")
        except (RedisError, OSError) as exc:
            raise _job_state_unavailable(exc) from exc
        return json.loads(raw) if raw else None

    async def _save(self, job: dict) -> None:
        job["updated_at"] = _utc_now_iso()
        await self._redis().set(
            f"{JOB_KEY_PREFIX}{job['job_id']}", json.dumps(job), ex=JOB_TTL_SECONDS
        )

    def _cleanup_old_exports(self) -> None:
        """Best-effort removal of temp export files older than the job TTL."""
        try:
            if not os.path.isdir(EXPORT_DIR):
                return
            cutoff = time.time() - JOB_TTL_SECONDS
            for name in os.listdir(EXPORT_DIR):
                p = os.path.join(EXPORT_DIR, name)
                try:
                    if os.path.isfile(p) and os.path.getmtime(p) < cutoff:
                        os.remove(p)
                except OSError:
                    pass
        except Exception as exc:  # noqa: BLE001 - cleanup must never fail a job
            logger.warning("export_cleanup_failed", error=str(exc))

    # --- Audit ----------------------------------------------------------------
    async def _audit(self, action: str, job: dict, organization_id: Any, actor_id: Any) -> None:
        """Record an export in audit_logs (non-fatal). Mirrors BulkProcessor._audit."""
        details = {
            "job_id": job.get("job_id"),
            "type": job.get("type"),
            "total": job.get("total"),
            "succeeded": job.get("succeeded"),
            "status": job.get("status"),
        }
        try:
            async with AsyncSessionLocal() as session:
                # audit_logs is ENABLE + FORCE ROW LEVEL SECURITY (migrations 011/033),
                # and FORCE means the policy applies to the table owner too — so this
                # INSERT is REJECTED unless app.current_org_id is set on the connection.
                # AsyncSessionLocal never sets it, and the `except` below swallowed the
                # rejection, so this entry has never been written on a real deployment
                # while every caller saw its own work succeed. Found in the log noise of
                # a real-DB run: `export_audit_failed ... new row violates row-level
                # security policy for table "audit_logs"`, three times, passing by.
                #
                # is_local=true (transaction-scoped): there is no teardown here to reset
                # a session-scoped value before the connection returns to the pool.
                if organization_id and session.bind.dialect.name == "postgresql":
                    await session.execute(
                        text("SELECT set_config('app.current_org_id', :org, true)"),
                        {"org": str(organization_id)},
                    )
                # audit_logs.id and .timestamp are NOT NULL with no server default
                # (the model's default=uuid4 is Python-side only), so a raw INSERT
                # must supply them explicitly; the BEFORE INSERT trigger fills hash_chain.
                await session.execute(
                    text(
                        """
                        INSERT INTO audit_logs
                            (id, timestamp, user_id, organization_id, action, resource_type, details)
                        VALUES
                            (:id, now(), :user_id, :organization_id, :action, 'export',
                             CAST(:details AS JSONB))
                        """
                    ),
                    {
                        "id": str(uuid.uuid4()),
                        "user_id": str(actor_id) if actor_id else None,
                        "organization_id": str(organization_id) if organization_id else None,
                        "action": action,
                        "details": json.dumps(details),
                    },
                )
                await session.commit()
        except Exception as exc:  # noqa: BLE001
            logger.error("export_audit_failed", action=action, error=str(exc))

    async def audit_sync_export(self, action: str, organization_id: Any, actor_id: Any, total: int) -> None:
        """Audit a synchronous (non-job) export from the API layer."""
        await self._audit(
            action,
            {"job_id": None, "type": action, "total": total, "succeeded": total, "status": "completed"},
            organization_id,
            actor_id,
        )

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None


export_processor = ExportProcessor()
