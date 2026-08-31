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
NOT_YET_BOUNDED: dict[str, str] = {
    # Empty, and meant to stay that way. FS-842 named five resources — assets, seats,
    # ingestion rate, storage and export size — and all five are bounded now:
    # `MAX_ASSETS_PER_ORG`, `MAX_USERS_PER_ORG`, `RATE_LIMIT_PER_TENANT` (FS-843),
    # `MAX_STORAGE_BYTES_PER_ORG` across all three producers, and `MAX_EXPORT_ROWS`.
    #
    # An entry here is a resource a tenant can consume without limit, so it is a promise
    # to fix rather than an excuse — and the tests below assert any entry is genuinely
    # still unbounded, so one cannot go stale.
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
    def test_every_unbounded_resource_says_why(self):
        """An unexplained absence reads as a decision that was never taken.

        A LOOP, NOT `parametrize`. With the register empty — which is now the case, all
        five of FS-842's resources are bounded — a parametrized test SKIPS, and a skip is
        indistinguishable from a pass in a CI summary. The register being empty is the
        goal, so the test has to still run and say so.
        """
        for resource, reason in sorted(NOT_YET_BOUNDED.items()):
            assert len(reason) > 80, (
                f"{resource} is recorded as unbounded without a real explanation, which "
                f"is an exemption nobody will revisit"
            )

    def test_the_bounded_ones_are_not_also_listed(self):
        """A register that names something already done is stale, and a stale register is
        worse than none — it reports solved work as outstanding."""
        for done in ("assets", "seats", "storage_bytes", "export_size", "export_row_count"):
            assert done not in NOT_YET_BOUNDED, (
                f"{done!r} is bounded now and still listed as outstanding."
            )


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


class TestTheStorageQuotaCountsEveryProducer:
    """A storage quota that omits a producer is worse than none.

    Three things write objects for a tenant: RAG documents, compliance reports and export
    artefacts. Exports recorded no size at all until migration 075 — the processor
    uploaded from a local path and discarded the figure — so a quota built before that
    would have reported a tenant inside its limit while the class most likely to exceed it
    went uncounted. Generating exports is exactly how a tenant would blow a storage
    budget.
    """

    def test_all_three_producers_are_summed(self):
        """SCOPED TO THE FUNCTION, not the file. The first version asked whether each
        model name appeared anywhere in `tenant_quotas.py` — which still passed when the
        export term was deleted from the sum, because the name remained in the import
        list. Mutation-testing is the only reason that was found; rule 37 again, and the
        second time in this sprint that a name-in-source check could not distinguish the
        states it claimed to.
        """
        tree = ast.parse((APP / "services/tenant_quotas.py").read_text())
        fn = next(
            (
                node
                for node in ast.walk(tree)
                if isinstance(node, ast.AsyncFunctionDef) and node.name == "storage_bytes"
            ),
            None,
        )
        assert fn is not None, "storage_bytes() has moved; this guard is now blind"
        referenced = {
            node.id for node in ast.walk(fn) if isinstance(node, ast.Name)
        } | {
            node.attr for node in ast.walk(fn) if isinstance(node, ast.Attribute)
        }
        for model in ("RagDocument", "ComplianceReportJob", "ExportDeliveryJob"):
            assert model in referenced, (
                f"{model} is not summed inside storage_bytes(), so that producer's "
                f"objects are invisible to the quota and a tenant can exceed its storage "
                f"limit entirely through them. Summed: {sorted(referenced)}"
            )

    def test_the_export_worker_records_the_size(self):
        """The only moment the number exists: the file is on the worker's disk and is
        deleted moments later."""
        source = (APP / "workers/export_delivery.py").read_text()
        assert "job.size_bytes = os.path.getsize(path)" in source, (
            "the delivery worker no longer records the artefact size, so every new export "
            "counts as 0 bytes and the storage quota silently stops seeing exports."
        )

    def test_generation_is_refused_before_the_expensive_half(self):
        """An export's size is unknowable until it exists, so the check has to happen
        before generation — otherwise a tenant over its limit produces the artefact and
        the total is discovered afterwards."""
        source = (APP / "workers/export_delivery.py").read_text()
        body = source[source.index("async def process_job") :]
        assert body.index("_storage_rejection") < body.index(
            "generate_scheduled_export"
        ), (
            "process_job generates the export before checking the storage quota, so the "
            "refusal costs exactly the work it was refusing to do."
        )

    @pytest.mark.asyncio
    async def test_zero_means_unlimited_and_does_not_query(self, monkeypatch):
        from app.core.config import settings
        from app.services.tenant_quotas import check_storage_quota

        monkeypatch.setattr(settings, "MAX_STORAGE_BYTES_PER_ORG", 0)
        db = _db(999)
        assert await check_storage_quota(db, "org-1") is None
        db.execute.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_tenant_over_its_limit_is_refused(self, monkeypatch):
        from app.core.config import settings
        from app.services.tenant_quotas import check_storage_quota

        monkeypatch.setattr(settings, "MAX_STORAGE_BYTES_PER_ORG", 3 * 1024 ** 3)
        # _db returns the same scalar for each of the three sums: 3 x 2GiB = 6GiB.
        rejection = await check_storage_quota(_db(2 * 1024 ** 3), "org-1")
        assert rejection is not None and rejection.status == 409
        assert "GiB" in rejection.detail


class TestAnExportCannotOomTheWorker:
    """Every export builder materialised EVERY row for an organisation and built the
    spreadsheet in memory, with no LIMIT on any query. In a worker capped at 512Mi that is
    an unbounded allocation: a tenant with enough history does not receive a large file,
    it gets the worker OOM-killed part-way through — with no message, no failed-job
    status anybody can read, and a restart that tries the same export again.
    """

    def test_a_row_count_past_the_ceiling_is_refused(self):
        from app.core.config import settings
        from app.services.export_processor import ExportTooLarge, _guard_row_count

        with pytest.raises(ExportTooLarge) as excinfo:
            _guard_row_count(list(range(settings.MAX_EXPORT_ROWS + 1)), "tasks")
        assert str(settings.MAX_EXPORT_ROWS) in str(excinfo.value).replace(",", "")

    def test_the_message_names_the_remedy(self):
        """A refusal that does not say what to change generates a support ticket."""
        from app.core.config import settings
        from app.services.export_processor import ExportTooLarge, _guard_row_count

        with pytest.raises(ExportTooLarge) as excinfo:
            _guard_row_count(list(range(settings.MAX_EXPORT_ROWS + 1)), "tasks")
        assert "Narrow the filters" in str(excinfo.value)

    def test_it_ships_on_unlike_the_other_quotas(self):
        """0 elsewhere preserves a working feature; 0 here would preserve an unbounded
        allocation. The ceiling takes away nothing that works today — an export past this
        size already fails, as an OOM kill rather than a refusal."""
        from app.core.config import Settings

        assert Settings().MAX_EXPORT_ROWS > 0

    def test_every_builder_is_guarded(self):
        """One unguarded builder is an unbounded allocation, and it is the one a tenant
        will find.

        PER FUNCTION, VIA AST. Two earlier versions of this check were wrong in different
        ways and both were caught by mutation-testing rather than by reading:

        * matching `rows = [` missed the OEE builder entirely, because it accumulates in a
          loop rather than a comprehension — and that builder was genuinely unguarded, so
          the check found the right file for the wrong reason;
        * matching lines and locating them with `str.index` broke on `).scalars().all()`,
          which appears several times, so it kept testing the first occurrence.

        The claim is about BUILDERS, not lines: a function that materialises a full result
        set must also apply the ceiling. That is what is asserted.
        """
        tree = ast.parse((APP / "services/export_processor.py").read_text())
        offenders = []
        checked = 0
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            calls = [
                c
                for c in ast.walk(node)
                if isinstance(c, ast.Call) and isinstance(c.func, ast.Attribute)
            ]
            if not any(c.func.attr == "all" for c in calls):
                continue
            checked += 1
            guarded = any(
                isinstance(c.func, ast.Name) and c.func.id == "_guard_row_count"
                for c in ast.walk(node)
                if isinstance(c, ast.Call)
            )
            if not guarded:
                offenders.append(node.name)

        assert checked >= 4, (
            f"only {checked} functions materialise a result set; the walk is broken and "
            f"this check would pass over almost nothing"
        )
        assert not offenders, (
            f"these export builders materialise a full result set without applying "
            f"MAX_EXPORT_ROWS: {offenders}. Each is an unbounded in-memory spreadsheet in "
            f"a worker capped at 512Mi."
        )

    def test_it_refuses_rather_than_truncating(self):
        """A LIMIT on the query would have been cheaper and is the wrong answer: it
        silently truncates. For a compliance artefact a file that looks complete and is
        not is the worst available outcome."""
        source = (APP / "services/export_processor.py").read_text()
        guard = source[source.index("def _guard_row_count") : source.index("class ExportProcessor")]
        assert "raise ExportTooLarge" in guard
        assert ".limit(" not in guard
