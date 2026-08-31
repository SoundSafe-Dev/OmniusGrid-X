"""A tenant's VOLUME is bounded, not just its request rate (FS-842).

FS-843 gave an organisation a request-rate budget. That does not bound growth: a tenant
comfortably inside its rate limit can still reach a million assets one row at a time, and
every dashboard aggregate, retention sweep and export pays for it afterwards, forever.

Before this, `quota`, `max_assets`, `tenant_limit` and `plan_limit` returned **zero hits
across `backend/app`** — nothing bounded a tenant's assets, seats, storage or exports.

WHAT IS ASSERTED HERE is that the limits refuse at the right moment, on every path that
consumes the resource — including the one a create-only quota misses.
"""
from __future__ import annotations

import ast
import pathlib
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.services.tenant_quotas import (
    QuotaRejection,
    check_asset_quota,
    check_seat_quota,
    usage,
)

REPO = pathlib.Path(__file__).resolve().parents[2]
APP = REPO / "backend/app"

#: Resources FS-842 names that are NOT bounded yet, with why. An empty absence reads as a
#: decision; this says plainly that it is not one.
NOT_YET_BOUNDED = {
    "storage_bytes": (
        "No table holds a per-tenant byte total. Object storage is written by the export "
        "and compliance paths and by the RAG document store, each with its own prefix, "
        "and nothing sums them per organisation. A limit guessed without that figure "
        "would refuse real work for the wrong reason."
    ),
    "export_size": (
        "An export's size is known only once it is generated, so a quota has to bound "
        "either the ROW COUNT requested (cheap, and already partly bounded by the "
        "pagination ceilings) or the produced artefact (accurate, and refuses after the "
        "work is done). Choosing between those is a product decision, not a defaulting."
    ),
}


class _Result:
    def __init__(self, value):
        self._value = value

    def scalar_one(self):
        return self._value


def _db(count: int) -> SimpleNamespace:
    return SimpleNamespace(execute=AsyncMock(return_value=_Result(count)))


class TestTheAssetQuota:
    @pytest.mark.asyncio
    async def test_zero_means_unlimited(self, monkeypatch):
        """Ships OFF. A quota switched on by default refuses real work in every existing
        environment the day it deploys, which is how a safety feature gets reverted."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "MAX_ASSETS_PER_ORG", 0)
        db = _db(10_000)
        assert await check_asset_quota(db, "org-1") is None
        db.execute.assert_not_awaited()  # and it does not even count

    @pytest.mark.asyncio
    async def test_a_tenant_under_its_limit_passes(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "MAX_ASSETS_PER_ORG", 100)
        assert await check_asset_quota(_db(99), "org-1") is None

    @pytest.mark.asyncio
    async def test_a_tenant_at_its_limit_is_refused_with_409(self, monkeypatch):
        """409, not 429. Retrying does not help until something is deactivated, and a 429
        tells the client to back off and try the identical request again forever."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "MAX_ASSETS_PER_ORG", 100)
        rejection = await check_asset_quota(_db(100), "org-1")
        assert isinstance(rejection, QuotaRejection)
        assert rejection.status == 409
        assert "100" in rejection.detail

    @pytest.mark.asyncio
    async def test_the_message_says_what_to_do(self, monkeypatch):
        """A refusal that does not name the remedy generates a support ticket."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "MAX_ASSETS_PER_ORG", 5)
        rejection = await check_asset_quota(_db(5), "org-1")
        assert "Deactivate" in rejection.detail


class TestTheSeatQuota:
    @pytest.mark.asyncio
    async def test_a_full_organisation_cannot_invite(self, monkeypatch):
        from app.core.config import settings

        monkeypatch.setattr(settings, "MAX_USERS_PER_ORG", 3)
        rejection = await check_seat_quota(_db(3), "org-1")
        assert rejection is not None and rejection.status == 409

    @pytest.mark.asyncio
    async def test_seats_count_active_users_only(self, monkeypatch):
        """Deactivated users keep their rows so the audit trail survives an offboarding.
        Counting them as seats would make a departure fail to free capacity, which is the
        opposite of what deactivation is for."""
        from app.services import tenant_quotas
        from app.db.models import User

        assert hasattr(User, "is_active"), "the seat count depends on this column"
        source = pathlib.Path(tenant_quotas.__file__).read_text()
        assert "is_active.is_(True)" in source, (
            "the count no longer filters on is_active, so deactivated users consume seats "
            "and offboarding stops freeing capacity"
        )


class TestTheBypassAQuotaOnCreateWouldMiss:
    def test_reactivation_checks_the_seat_quota(self):
        """THE PATH THAT MATTERS. A quota enforced only where a user is CREATED is
        bypassed by deactivating and reactivating — an ordinary administrative action, so
        it would have been discovered by an admin doing their job rather than reported as
        a bug.

        Asserted structurally: the reactivate handler must call the check.
        """
        source = (APP / "api/users.py").read_text()
        tree = ast.parse(source)
        handler = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "reactivate_user"
            ),
            None,
        )
        assert handler is not None, "reactivate_user has moved; this guard is now blind"
        calls = {
            node.func.id
            for node in ast.walk(handler)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "check_seat_quota" in calls, (
            "reactivate_user does not check the seat quota, so an organisation at its "
            "limit can deactivate a user and reactivate another indefinitely."
        )

    def test_invitation_checks_the_seat_quota(self):
        """Gated at invitation rather than acceptance, so the refusal reaches the admin
        who can act on it instead of the person who was invited."""
        source = (APP / "api/users.py").read_text()
        tree = ast.parse(source)
        handler = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.AsyncFunctionDef)
                and node.name == "create_invitation"
            ),
            None,
        )
        assert handler is not None
        calls = {
            node.func.id
            for node in ast.walk(handler)
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
        }
        assert "check_seat_quota" in calls

    def test_asset_creation_checks_before_the_expensive_work(self):
        """The quota check must precede the reference walk and the lookups, or a refusal
        costs the platform the work it was refusing to do."""
        source = (APP / "api/assets.py").read_text()
        body = source[source.index("async def create_asset") :]
        quota_at = body.index("check_asset_quota")
        verify_at = body.index("verify_refs")
        assert quota_at < verify_at, (
            "create_asset validates references before checking the quota, so a tenant at "
            "its ceiling pays for the validation of a request that cannot succeed."
        )


class TestTheGapIsRecordedRatherThanImplied:
    @pytest.mark.parametrize("resource", sorted(NOT_YET_BOUNDED))
    def test_every_unbounded_resource_says_why(self, resource):
        """FS-842 names five resources; two are bounded. An unexplained absence reads as a
        decision that was never taken."""
        assert len(NOT_YET_BOUNDED[resource]) > 80

    def test_the_bounded_ones_are_not_also_listed(self):
        """A register that names something already done is stale, and a stale register is
        worse than none — it reports solved work as outstanding."""
        assert "assets" not in NOT_YET_BOUNDED
        assert "seats" not in NOT_YET_BOUNDED


class TestUsageIsReadable:
    @pytest.mark.asyncio
    async def test_usage_reports_limits_as_none_when_unlimited(self, monkeypatch):
        """A quota nobody can read is a surprise 409 partway through an import."""
        from app.core.config import settings

        monkeypatch.setattr(settings, "MAX_ASSETS_PER_ORG", 0)
        monkeypatch.setattr(settings, "MAX_USERS_PER_ORG", 25)
        reported = (await usage(_db(7), "org-1")).as_dict()
        assert reported["max_assets"] is None
        assert reported["max_seats"] == 25
        assert reported["assets"] == 7
