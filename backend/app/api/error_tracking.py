"""Error Triage admin API (read + status workflow over aggregated errors).

Every endpoint uses the shared admin dependency and is rate-limited. The feature
is a platform-level triage view: rows carry `organization_id` for context but
the API is not tenant-filtered (open question flagged to the manager). All
queries hit only the two error-tracking tables, so there is zero impact on any
existing table.
"""


from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.pagination import MAX_OFFSET
from app.api.auth import get_current_active_user
from app.db.database import get_db
from app.db.models import User
from app.middleware.rate_limit import rate_limit
from app.middleware.rbac import require_admin

logger = structlog.get_logger()

router = APIRouter()

_RANGES = {"24h": timedelta(hours=24), "7d": timedelta(days=7), "30d": timedelta(days=30)}
_STATUSES = ("open", "acknowledged", "resolved")

# Valid status transitions for the triage workflow. Resolved->open is a manual
# reopen; the tracker also auto-reopens on regression (handled in the flush UPSERT).
_TRANSITIONS = {
    "open": {"acknowledged", "resolved"},
    "acknowledged": {"resolved", "open"},
    "resolved": {"open"},
}


# ==================== Response Schemas ====================

class ErrorEventSummary(BaseModel):
    fingerprint: str
    exception_type: str
    route: str
    method: str
    status_code: int
    status: str
    total_count: int
    count_in_range: int
    regression_count: int
    first_seen: datetime
    last_seen: datetime


class ErrorListResponse(BaseModel):
    items: list[ErrorEventSummary]
    total: int


class HourlyPoint(BaseModel):
    hour: datetime
    count: int


class TopError(BaseModel):
    fingerprint: str
    exception_type: str
    route: str
    count_in_range: int


class ErrorSummaryResponse(BaseModel):
    range: str
    open_count: int
    acknowledged_count: int
    events_in_range: int
    regressions_in_range: int
    top_error: Optional[TopError]
    series: list[HourlyPoint]


class ErrorEventDetail(BaseModel):
    fingerprint: str
    exception_type: str
    route: str
    method: str
    status_code: int
    status: str
    total_count: int
    count_in_range: int
    regression_count: int
    message_sample: Optional[str]
    traceback_sample: Optional[str]
    #: True when the two samples above were withheld because the row belongs to another
    #: organisation (FS-477). The withheld value is a sentence, not a traceback, and the
    #: client cannot tell the difference by looking at it — `_REDACTED` is prose, and a
    #: client matching on prose is a coupling nobody declared.
    #:
    #: Without this the detail page rendered the sentence inside a `<pre>` under the
    #: subtitle "Latest occurrence · scrubbed of PII", with the Copy button ENABLED — so
    #: an operator could paste "[redacted: belongs to another organization]" into a bug
    #: report believing it was a stack trace.
    samples_redacted: bool = False
    organization_id: Optional[str]
    status_changed_by: Optional[str]
    status_changed_at: Optional[datetime]
    first_seen: datetime
    last_seen: datetime
    series: list[HourlyPoint]


class StatusUpdateRequest(BaseModel):
    status: Literal["open", "acknowledged", "resolved"]


def _range_start(range_key: str) -> Optional[datetime]:
    delta = _RANGES.get(range_key)
    if delta is None:
        return None
    return datetime.now(timezone.utc) - delta


# ==================== Endpoints ====================

@router.get("", summary="List aggregated errors", response_model=ErrorListResponse, dependencies=[Depends(require_admin)])
@router.get("/", include_in_schema=False, response_model=ErrorListResponse, dependencies=[Depends(require_admin)])
@rate_limit("100/minute")
async def list_errors(
    request: Request,
    status_filter: Literal["open", "acknowledged", "resolved", "active", "all"] = Query(
        "active", alias="status"
    ),
    q: Optional[str] = Query(None, max_length=255),
    sort: Literal["count", "last_seen", "first_seen"] = "count",
    order: Literal["asc", "desc"] = "desc",
    range: Literal["24h", "7d", "30d", "all"] = "7d",
    limit: int = Query(25, ge=1, le=100),
    offset: int = Query(0, ge=0, le=MAX_OFFSET),
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Paginated list of error fingerprints with range-scoped counts."""
    start = _range_start(range)
    params: dict = {"limit": limit, "offset": offset}
    where = []

    if status_filter == "active":
        where.append("e.status IN ('open', 'acknowledged')")
    elif status_filter != "all":
        where.append("e.status = :status")
        params["status"] = status_filter

    if q:
        where.append("(e.route ILIKE :q OR e.exception_type ILIKE :q)")
        params["q"] = f"%{q}%"

    # count_in_range is summed from hourly buckets; when range=all we use the
    # lifetime total_count instead.
    if start is not None:
        params["start"] = start
        count_expr = (
            "COALESCE((SELECT SUM(b.count) FROM error_event_buckets b "
            "WHERE b.fingerprint = e.fingerprint AND b.bucket_hour >= :start), 0)"
        )
    else:
        count_expr = "e.total_count"

    where_sql = (" WHERE " + " AND ".join(where)) if where else ""
    sort_col = {"count": "count_in_range", "last_seen": "e.last_seen",
                "first_seen": "e.first_seen"}[sort]
    order_sql = "ASC" if order == "asc" else "DESC"

    rows = (await db.execute(text(
        f"""
        SELECT e.fingerprint, e.exception_type, e.route, e.method, e.status_code,
               e.status, e.total_count, e.regression_count, e.first_seen, e.last_seen,
               {count_expr} AS count_in_range
        FROM error_events e
        {where_sql}
        ORDER BY {sort_col} {order_sql}, e.last_seen DESC
        LIMIT :limit OFFSET :offset
        """
    ), params)).mappings().all()

    total = (await db.execute(text(
        f"SELECT COUNT(*) FROM error_events e{where_sql}"
    ), params)).scalar() or 0

    items = [
        ErrorEventSummary(
            fingerprint=r["fingerprint"],
            exception_type=r["exception_type"],
            route=r["route"],
            method=r["method"],
            status_code=r["status_code"],
            status=r["status"],
            total_count=r["total_count"],
            count_in_range=r["count_in_range"],
            regression_count=r["regression_count"],
            first_seen=r["first_seen"],
            last_seen=r["last_seen"],
        )
        for r in rows
    ]
    return ErrorListResponse(items=items, total=total)


@router.get("/summary", summary="Error triage summary cards", response_model=ErrorSummaryResponse, dependencies=[Depends(require_admin)])
@rate_limit("100/minute")
async def error_summary(
    request: Request,
    range: Literal["24h", "7d", "30d", "all"] = "7d",
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Headline counts, the single most frequent error, and an hourly series."""
    start = _range_start(range)

    open_count = (await db.execute(
        text("SELECT COUNT(*) FROM error_events WHERE status = 'open'")
    )).scalar() or 0
    ack_count = (await db.execute(
        text("SELECT COUNT(*) FROM error_events WHERE status = 'acknowledged'")
    )).scalar() or 0

    bucket_where = "WHERE bucket_hour >= :start" if start is not None else ""
    params = {"start": start} if start is not None else {}

    events_in_range = (await db.execute(
        text(f"SELECT COALESCE(SUM(count), 0) FROM error_event_buckets {bucket_where}"),
        params,
    )).scalar() or 0

    if start is not None:
        regressions = (await db.execute(
            text("SELECT COALESCE(SUM(regression_count), 0) FROM error_events "
                 "WHERE last_seen >= :start"),
            {"start": start},
        )).scalar() or 0
    else:
        regressions = (await db.execute(
            text("SELECT COALESCE(SUM(regression_count), 0) FROM error_events")
        )).scalar() or 0

    top_row = (await db.execute(text(
        f"""
        SELECT e.fingerprint, e.exception_type, e.route,
               COALESCE(SUM(b.count), 0) AS count_in_range
        FROM error_events e
        JOIN error_event_buckets b ON b.fingerprint = e.fingerprint
        {"WHERE b.bucket_hour >= :start" if start is not None else ""}
        GROUP BY e.fingerprint, e.exception_type, e.route
        ORDER BY count_in_range DESC
        LIMIT 1
        """
    ), params)).mappings().first()

    top_error = (
        TopError(
            fingerprint=top_row["fingerprint"],
            exception_type=top_row["exception_type"],
            route=top_row["route"],
            count_in_range=top_row["count_in_range"],
        )
        if top_row else None
    )

    series_rows = (await db.execute(text(
        f"""
        SELECT bucket_hour AS hour, SUM(count) AS count
        FROM error_event_buckets
        {bucket_where}
        GROUP BY bucket_hour
        ORDER BY bucket_hour ASC
        """
    ), params)).mappings().all()
    series = [HourlyPoint(hour=r["hour"], count=r["count"]) for r in series_rows]

    return ErrorSummaryResponse(
        range=range,
        open_count=open_count,
        acknowledged_count=ack_count,
        events_in_range=events_in_range,
        regressions_in_range=regressions,
        top_error=top_error,
        series=series,
    )



_REDACTED = "[redacted: belongs to another organization]"


def _samples_are_redacted(row, viewer_org: Optional[str]) -> bool:
    """Whether `_visible_sample` withheld this row's samples (FS-477).

    Derived from the same condition rather than by comparing the returned value to
    `_REDACTED` — the marker is prose, and a caller that matches on prose breaks the day
    somebody improves the wording. The flag is what the client reads.
    """
    owner = row["organization_id"]
    outsider = owner is not None and (
        viewer_org is None or str(owner) != str(viewer_org)
    )
    # SOMETHING WAS ACTUALLY WITHHELD. An outsider viewing a row that carries no samples
    # has had nothing kept from them, and "redacted" there would put a withholding notice
    # over an error that simply never captured a traceback — an absence dressed as a
    # refusal, which is its own small lie.
    return outsider and bool(row["message_sample"] or row["traceback_sample"])


def _visible_sample(row, field: str, viewer_org: Optional[str]) -> Optional[str]:
    """Return an error sample only to a viewer in the row's own organisation.

    A row with no `organization_id` is platform-level (it predates attribution, or the
    error happened outside a tenant request) and is shown to everyone — withholding it
    would hide genuinely shared infrastructure errors from the triage view for no gain.
    """
    owner = row["organization_id"]
    if owner is None or (viewer_org is not None and str(owner) == str(viewer_org)):
        return row[field]
    return _REDACTED if row[field] else None


async def _build_detail(
    fingerprint: str, db: AsyncSession, viewer_org: Optional[str] = None
) -> ErrorEventDetail:
    """Shared detail builder used by GET detail and PATCH status (404 on miss)."""
    row = (await db.execute(text(
        "SELECT * FROM error_events WHERE fingerprint = :fp"
    ), {"fp": fingerprint})).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Error not found")

    week_start = datetime.now(timezone.utc) - timedelta(days=7)
    series_rows = (await db.execute(text(
        """
        SELECT bucket_hour AS hour, count
        FROM error_event_buckets
        WHERE fingerprint = :fp AND bucket_hour >= :start
        ORDER BY bucket_hour ASC
        """
    ), {"fp": fingerprint, "start": week_start})).mappings().all()
    series = [HourlyPoint(hour=r["hour"], count=r["count"]) for r in series_rows]
    count_in_range = sum(p.count for p in series) if series else 0

    return ErrorEventDetail(
        fingerprint=row["fingerprint"],
        exception_type=row["exception_type"],
        route=row["route"],
        method=row["method"],
        status_code=row["status_code"],
        status=row["status"],
        total_count=row["total_count"],
        count_in_range=count_in_range,
        regression_count=row["regression_count"],
        # REDACTED FOR ANOTHER TENANT'S ROW.
        #
        # `error_events` is keyed on `fingerprint` alone — one row per distinct error
        # for the whole platform — so this is a cross-tenant triage view by design, and
        # `require_admin` means a TENANT admin, since no platform-admin role exists yet.
        # Left as-is, any tenant's admin could read any other tenant's `message_sample`
        # and `traceback_sample`. Verified against a real database: org A retrieved a
        # row belonging to org B whose message carried a customer identifier and whose
        # traceback carried a payment-card value. Exception text and tracebacks are the two
        # fields most likely to contain customer data, precisely because nobody chooses
        # what goes in them.
        #
        # The counts, route and status stay visible — that is the triage value, and it
        # carries no payload. Only the samples are withheld, and only from a viewer in a
        # different organisation. If a platform-admin role is added, gate on that
        # instead of dropping the check.
        message_sample=_visible_sample(row, "message_sample", viewer_org),
        traceback_sample=_visible_sample(row, "traceback_sample", viewer_org),
        samples_redacted=_samples_are_redacted(row, viewer_org),
        organization_id=str(row["organization_id"]) if row["organization_id"] else None,
        status_changed_by=str(row["status_changed_by"]) if row["status_changed_by"] else None,
        status_changed_at=row["status_changed_at"],
        first_seen=row["first_seen"],
        last_seen=row["last_seen"],
        series=series,
    )


@router.get("/{fingerprint}", summary="Error detail", response_model=ErrorEventDetail, dependencies=[Depends(require_admin)])
@rate_limit("100/minute")
async def error_detail(
    fingerprint: str,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Full record for one fingerprint plus a 7-day hourly series."""
    return await _build_detail(
        fingerprint, db, viewer_org=str(current_user.organization_id)
        if current_user.organization_id else None,
    )


@router.patch("/{fingerprint}", summary="Change error status", response_model=ErrorEventDetail, dependencies=[Depends(require_admin)])
@rate_limit("30/minute")
async def update_error_status(
    fingerprint: str,
    payload: StatusUpdateRequest,
    request: Request,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db),
):
    """Transition an error through the triage workflow (validated transitions)."""
    row = (await db.execute(text(
        "SELECT status, organization_id FROM error_events WHERE fingerprint = :fp"
    ), {"fp": fingerprint})).mappings().first()
    if row is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Error not found")

    # YOU MAY READ EVERY ERROR AND ACT ONLY ON YOUR OWN.
    #
    # `error_events` is keyed on `fingerprint` alone — one row per distinct error for the
    # entire platform — so this endpoint is cross-tenant by construction, and
    # `require_admin` means a TENANT admin because no platform-admin role exists yet.
    # The READ side already reflects that: `_visible_sample` withholds another tenant's
    # message and traceback while leaving the triage metadata visible.
    #
    # The WRITE side did not. This updated by fingerprint alone, so one tenant's admin
    # could resolve or reopen an error owned by another and change what that tenant sees
    # in their own triage queue. Reading a shared row is defensible; mutating one on
    # somebody else's behalf is not.
    #
    # An unattributed row (organization_id IS NULL) is platform-level — it happened
    # outside a tenant request or predates attribution — and stays writable by any admin,
    # for the same reason its samples stay readable: it belongs to nobody in particular.
    owner = row["organization_id"]
    if owner is not None and str(owner) != str(current_user.organization_id):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This error belongs to another organization; you can view it but not triage it.",
        )

    current = row["status"]
    target = payload.status
    if target != current and target not in _TRANSITIONS.get(current, set()):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid transition: {current} -> {target}",
        )

    # The ownership predicate is repeated in the UPDATE rather than trusted from the
    # SELECT above: between the two statements is a gap, and the check that matters is
    # the one the write itself carries.
    result = await db.execute(text(
        """
        UPDATE error_events
        SET status = :status,
            status_changed_by = :user_id,
            status_changed_at = :now
        WHERE fingerprint = :fp
          AND (organization_id IS NULL OR organization_id = :org)
        """
    ), {
        "status": target,
        "user_id": current_user.id,
        "now": datetime.now(timezone.utc),
        "fp": fingerprint,
        "org": current_user.organization_id,
    })
    # ROWCOUNT IS CHECKED BECAUSE AN UPDATE FAILS QUIETLY. Under row-level security an
    # INSERT is REJECTED by the policy's WITH CHECK, loudly; an UPDATE is FILTERED, so it
    # succeeds and touches nothing. Without this, a write that matched no rows returned
    # 200 and the triage page showed the new status until the next refresh undid it.
    if result.rowcount == 0:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="The error changed or is no longer yours to triage; reload and retry.",
        )
    await db.commit()

    logger.info(
        "error_status_changed",
        fingerprint=fingerprint,
        from_status=current,
        to_status=target,
        user_id=str(current_user.id),
    )

    return await _build_detail(
        fingerprint, db, viewer_org=str(current_user.organization_id)
        if current_user.organization_id else None,
    )
