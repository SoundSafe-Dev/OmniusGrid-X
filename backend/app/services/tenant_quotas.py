"""Per-tenant resource quotas (FS-842).

THE STATE THIS REPLACES. `quota`, `max_assets`, `tenant_limit` and `plan_limit` returned
**zero hits across `backend/app`**. Nothing bounded a tenant's assets, seats, storage or
exports, so one organisation could consume the platform's capacity and the only lever was
throttling one of its users at a time — which `docs/runbooks/noisy-tenant.md` had to open
by saying every containment option was blunt.

FS-843 bounded a tenant's REQUEST RATE. This bounds its VOLUME, and the two are different
failures: a tenant within its rate limit can still grow to a million assets, one row at a
time, and every dashboard aggregate and every retention sweep pays for it forever.

SHAPED AFTER THE RAG LANE'S INGEST QUOTA (`services/rag_index_queue.py`), which was the
first per-tenant limit in this backend and got the important parts right:

* **Counted from the rows themselves**, not from a maintained counter. A counter drifts
  the first time something is deleted outside the path that decrements it, and it drifts
  silently in the direction that lets a tenant exceed its quota.
* **Checked before the expensive work**, so a refusal costs nothing.
* **409, not 429.** Retrying does not help until something is deleted — a 429 invites the
  client to back off and try again, which will fail identically forever.
* **0 means unlimited**, so the feature ships off and is turned on per deployment.

WHAT IS DELIBERATELY NOT HERE. Storage bytes and export size are named in FS-842 and are
not implemented: both need a measured figure per tenant that no table currently holds, and
guessing one would produce a quota that refuses real work for the wrong reason.
`test_tenant_quotas_are_enforced.py` records them as outstanding rather than letting the
absence read as a decision.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.models import Asset, User


@dataclass(frozen=True)
class QuotaRejection:
    """Why a request was refused, in the shape the route needs to answer with."""

    status: int
    detail: str


@dataclass(frozen=True)
class QuotaUsage:
    """A tenant's current footprint against its limits. 0 limit means unlimited."""

    assets: int
    max_assets: int
    seats: int
    max_seats: int

    def as_dict(self) -> dict:
        return {
            "assets": self.assets,
            "max_assets": self.max_assets or None,
            "seats": self.seats,
            "max_seats": self.max_seats or None,
        }


async def _count(db: AsyncSession, model, organization_id) -> int:
    """COUNT(*) for one org, without materialising the rows.

    `len(result.scalars().all())` is the shape this deliberately avoids — it reads every
    row across the wire to produce a number, which is worst exactly for the tenant whose
    size made the quota necessary.
    """
    stmt = select(func.count()).select_from(model).where(
        model.organization_id == organization_id
    )
    if hasattr(model, "is_active"):
        stmt = stmt.where(model.is_active.is_(True))
    return int((await db.execute(stmt)).scalar_one())


async def check_asset_quota(db: AsyncSession, organization_id) -> Optional[QuotaRejection]:
    """Refuse an asset that would take this org past `MAX_ASSETS_PER_ORG`."""
    limit = settings.MAX_ASSETS_PER_ORG
    if limit <= 0:
        return None
    current = await _count(db, Asset, organization_id)
    if current >= limit:
        return QuotaRejection(
            status=409,
            detail=(
                f"This organization has reached its limit of {limit} assets "
                f"({current} in use). Deactivate an asset before adding another, or "
                f"contact support to raise the limit."
            ),
        )
    return None


async def check_seat_quota(db: AsyncSession, organization_id) -> Optional[QuotaRejection]:
    """Refuse a seat that would take this org past `MAX_USERS_PER_ORG`.

    A "seat" is an ACTIVE user. Deactivated users keep their rows so the audit trail
    survives (see `docs/runbooks/engineer-offboarding.md`), and they do not consume a
    seat — which is also why REACTIVATING a user has to be checked here and not only
    creation. A quota enforced on create alone is bypassed by deactivating and
    reactivating, and that path is a normal administrative action rather than an attack.
    """
    limit = settings.MAX_USERS_PER_ORG
    if limit <= 0:
        return None
    current = await _count(db, User, organization_id)
    if current >= limit:
        return QuotaRejection(
            status=409,
            detail=(
                f"This organization has reached its limit of {limit} active users "
                f"({current} in use). Deactivate a user before adding another, or "
                f"contact support to raise the limit."
            ),
        )
    return None


async def usage(db: AsyncSession, organization_id) -> QuotaUsage:
    """Current footprint and limits, so a client can see a 409 coming.

    A quota nobody can read is a surprise refusal partway through an import. The RAG lane
    reports its budget on the documents listing for the same reason.
    """
    return QuotaUsage(
        assets=await _count(db, Asset, organization_id),
        max_assets=settings.MAX_ASSETS_PER_ORG,
        seats=await _count(db, User, organization_id),
        max_seats=settings.MAX_USERS_PER_ORG,
    )
