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


class PageParams:
    """Shared skip/limit query params (FastAPI dependency)."""

    def __init__(
        self,
        skip: int = Query(0, ge=0, description="items to skip"),
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
