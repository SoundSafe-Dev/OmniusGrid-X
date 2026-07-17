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

from fastapi import Query
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
