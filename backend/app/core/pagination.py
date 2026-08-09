"""Generic pagination envelope (task 8).

A single ``PaginatedResponse[T]`` shape so list endpoints stop returning bare
arrays with ad-hoc skip/limit. Applied to the **unowned** read domains only
(operations, dashboard, yard, transportation, geotab) — owned routers keep their
current contracts to avoid churn on other devs' branches.

Usage::

    from app.core.pagination import PageParams, PaginatedResponse, paginate

    @router.get("/things", response_model=PaginatedResponse[Thing])
    async def list_things(page: PageParams = Depends()):
        rows, total = await repo.list(offset=page.skip, limit=page.limit)
        return paginate(rows, total, page)
"""

from typing import Generic, List, Sequence, TypeVar

from fastapi import Query, Response
from pydantic import BaseModel

T = TypeVar("T")

#: Upper bound for `skip`, and it is the DATABASE'S limit rather than a product one.
#:
#: `OFFSET :skip` binds to a Postgres **bigint**. A larger integer is not a big offset —
#: it is a value asyncpg cannot encode, so the driver raises and the request 500s where
#: the contract promises a 4xx. Every `skip` in this codebase was declared `ge=0` with no
#: ceiling, which reads as "any non-negative offset" and is true of exactly none of them.
#:
#: Found by the contract gate (FS-259) on `GET /api/v1/transportation/vehicles`, which was
#: the only one of THIRTEEN identical declarations that schemathesis happened to draw a
#: large enough value for. Fixing just that one would have been a fix by luck; the bound
#: is shared so the next endpoint to be drawn large is already covered.
#:
#: Deliberately the bigint ceiling and not a smaller "sensible" number: at this value no
#: request that works today starts failing, and the only behaviour that changes is the
#: 500 becoming the 422 the schema already documents.
MAX_OFFSET = 2**63 - 1


class PageParams:
    """Shared skip/limit query params (FastAPI dependency)."""

    def __init__(
        self,
        skip: int = Query(0, ge=0, le=MAX_OFFSET, description="items to skip"),
        limit: int = Query(50, ge=1, le=500, description="max items to return"),
    ):
        self.skip = skip
        self.limit = limit


class PageMeta(BaseModel):
    total: int
    skip: int
    limit: int
    count: int
    has_more: bool


class PaginatedResponse(BaseModel, Generic[T]):
    items: List[T]
    meta: PageMeta


def paginate(items: Sequence[T], total: int, page: PageParams) -> "PaginatedResponse[T]":
    """Build a PaginatedResponse from a page of items and the total count."""
    items = list(items)
    return PaginatedResponse[T](
        items=items,
        meta=PageMeta(
            total=total,
            skip=page.skip,
            limit=page.limit,
            count=len(items),
            has_more=(page.skip + len(items)) < total,
        ),
    )


def mark_truncated(response: Response, rows: Sequence[T], limit: int) -> List[T]:
    """Trim to `limit` and tell the caller when there was more.

    A bare-array endpoint returning exactly `limit` rows is indistinguishable from one
    returning the complete set, so a page reads as the whole fleet. `/api/v1/rul` is the
    sharpest case: its rows are ordered by asset NAME — remaining useful life is computed
    per asset in Python, so risk is not a sortable column — which means the cap keeps the
    alphabetically-first N and an asset near failure whose name sorts late is simply
    absent from the risk view, with the summary tiles counting it as though the fleet
    were fully assessed.

    Callers select `limit + 1` rows; if the extra one came back there is more to see.
    That costs one row instead of a COUNT over the whole table.

    The signal is a HEADER, not an envelope: the body is a bare array that clients
    already consume, and changing its shape would break every caller in order to fix a
    problem they could then no longer see. Lifted here unchanged from
    `erp_integrations._mark_truncated`, which is now a thin delegation — the convention
    is documented in the README and belonged in a shared module the moment it had a
    second user.
    """
    truncated = len(rows) > limit
    response.headers["X-Result-Limit"] = str(limit)
    response.headers["X-Result-Truncated"] = "true" if truncated else "false"
    return list(rows[:limit])


#: Response header naming a background loop that is not running (FS-530).
#:
#: A list endpoint served from an engine's in-memory state returns `[]` for two entirely
#: different reasons: the engine ran and found nothing, or the engine was never started. The
#: body cannot tell them apart, and the frontend renders "No recommendations" for both —
#: which is the "failure that renders as emptiness" class FS-487 exists to prevent.
#:
#: A HEADER for the same reason `X-Result-Truncated` is one: the body is a bare array that
#: clients already consume, and changing its shape would break every caller in order to fix
#: something they could then no longer see.
ENGINE_NOT_RUNNING_HEADER = "X-Engine-Not-Running"


def mark_engine_stopped(response: Response, engine: str, running: bool) -> None:
    """Set `X-Engine-Not-Running: <engine>` when the loop behind this data is not up."""
    if not running:
        response.headers[ENGINE_NOT_RUNNING_HEADER] = engine
