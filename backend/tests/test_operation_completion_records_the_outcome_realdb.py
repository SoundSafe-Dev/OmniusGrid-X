"""Completing an operation records the outcome the caller sent (FS-720).

`POST /operations/{operation_id}/complete` appeared in no test file. `route_walk` drives it,
but with generated input that rejects at validation, so the handler's body had never run —
the same gap FS-680 names for the two routes it closed.

It also read its two inputs from two different places. `success: bool = True` is a bare
scalar, which FastAPI serves from the QUERY string; `metadata: Optional[dict]` is a body
parameter. A client posting the obvious `{"success": false, "metadata": {...}}` therefore had
its metadata applied and its `success` silently replaced by the default, and the route marked
a FAILED operation **completed** — with `actual_duration` and the PackML state-duration
rollup computed and stored against that outcome, and a 200 in reply.

Both inputs are now one `OperationCompletion` body. These tests assert the outcome that
reaches the DATABASE, not the response: the response echoes the ORM object either way, so a
test that only read the JSON would have passed against the defect.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

OPERATIONS = "/api/v1/operations"


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


@pytest_asyncio.fixture
async def running_operation(admin_sync_url, seeded_orgs):
    """A running operation on a real asset, which is what `complete` expects to find."""
    org = str(seeded_orgs["org_a_id"])
    ids = {"asset_type": uuid.uuid4(), "asset": uuid.uuid4(), "operation": uuid.uuid4()}
    started = datetime.now(timezone.utc) - timedelta(minutes=30)
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'machine')",
            (str(ids["asset_type"]), f"FS720-{uuid.uuid4().hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, asset_type_id, workcell_id, name, is_active) "
            "VALUES (%s, %s, %s, %s, 'FS720 Asset', true)",
            (str(ids["asset"]), org, str(ids["asset_type"]), str(seeded_orgs["workcell_a_id"])),
        )
        cur.execute(
            # `operations` HAS NO organization_id COLUMN and no RLS policy. Its tenant is
            # whichever organisation owns the asset, which is why the list route joins
            # `assets` — see the IDOR note on `get_active_operations`.
            "INSERT INTO operations (id, asset_id, operation_name, status, "
            "started_at, meta_data) VALUES (%s, %s, 'FS720 run', 'running', %s, '{}')",
            (str(ids["operation"]), str(ids["asset"]), started),
        )
    yield ids
    with conn.cursor() as cur:
        cur.execute("DELETE FROM operations WHERE id = %s", (str(ids["operation"]),))
        cur.execute("DELETE FROM assets WHERE id = %s", (str(ids["asset"]),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(ids["asset_type"]),))
    conn.close()


def _row(admin_sync_url, operation_id):
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "SELECT status, completed_at, actual_duration, meta_data FROM operations "
            "WHERE id = %s",
            (str(operation_id),),
        )
        row = cur.fetchone()
    conn.close()
    return row


class TestTheOutcomeThatWasSentIsTheOutcomeThatIsStored:
    async def test_a_failed_run_is_recorded_as_failed(
        self, client_a, admin_sync_url, running_operation
    ):
        """THE REGRESSION. With `success` in the query string this body was accepted, the
        default `True` applied, and the row read `completed`."""
        response = await client_a.post(
            f"{OPERATIONS}/{running_operation['operation']}/complete",
            json={"success": False},
        )
        assert response.status_code == 200, response.text[:300]

        status, completed_at, duration, _meta = _row(
            admin_sync_url, running_operation["operation"]
        )
        assert status == "failed", (
            f"the caller reported a FAILED run and the row says {status!r}. A completion "
            f"flag read from the query string is silently defaulted for any client that "
            f"posts a body."
        )
        assert completed_at is not None
        assert duration and duration > 0, (
            f"actual_duration is {duration!r}; the operation ran for 30 minutes"
        )

    async def test_a_successful_run_is_recorded_as_completed(
        self, client_a, admin_sync_url, running_operation
    ):
        """The other branch, so the test above cannot pass by the field being ignored in
        the opposite direction."""
        response = await client_a.post(
            f"{OPERATIONS}/{running_operation['operation']}/complete",
            json={"success": True},
        )
        assert response.status_code == 200, response.text[:300]
        assert _row(admin_sync_url, running_operation["operation"])[0] == "completed"

    async def test_metadata_is_merged_rather_than_replaced(
        self, client_a, admin_sync_url, running_operation
    ):
        """`metadata` was the half that always worked, and it must keep working now that it
        travels inside a model. The column is `meta_data`; the handler merges."""
        response = await client_a.post(
            f"{OPERATIONS}/{running_operation['operation']}/complete",
            json={"success": True, "metadata": {"operator_note": "belt replaced"}},
        )
        assert response.status_code == 200, response.text[:300]
        meta = _row(admin_sync_url, running_operation["operation"])[3]
        assert meta.get("operator_note") == "belt replaced"

    async def test_an_empty_body_still_completes(self, client_a, admin_sync_url, running_operation):
        """The body is optional and its default is success. Sending nothing must behave as
        the old no-argument call did, or this fix is a breaking change for a caller that
        relied on the default."""
        response = await client_a.post(
            f"{OPERATIONS}/{running_operation['operation']}/complete"
        )
        assert response.status_code == 200, response.text[:300]
        assert _row(admin_sync_url, running_operation["operation"])[0] == "completed"


class TestTheGuardsAroundIt:
    async def test_an_operation_that_is_not_running_is_refused(
        self, client_a, admin_sync_url, running_operation
    ):
        """Completing twice must not re-stamp a finished operation."""
        first = await client_a.post(
            f"{OPERATIONS}/{running_operation['operation']}/complete", json={"success": True}
        )
        assert first.status_code == 200
        second = await client_a.post(
            f"{OPERATIONS}/{running_operation['operation']}/complete", json={"success": False}
        )
        assert second.status_code == 400, (
            "a completed operation was completed again; its outcome and duration would be "
            "overwritten by whoever called last"
        )
        assert _row(admin_sync_url, running_operation["operation"])[0] == "completed"

    async def test_another_tenant_cannot_complete_it(
        self, client_b, admin_sync_url, running_operation
    ):
        """`operations` is tenant-scoped, and the handler selects by id alone — it relies
        entirely on the RLS session for isolation, which is exactly the arrangement that
        fails quiet when the session is wrong."""
        response = await client_b.post(
            f"{OPERATIONS}/{running_operation['operation']}/complete", json={"success": False}
        )
        assert response.status_code == 404, response.text[:200]
        assert _row(admin_sync_url, running_operation["operation"])[0] == "running", (
            "another organisation completed this operation"
        )


class TestTheWholeRouterIsScoped:
    """`operations` has no `organization_id` column, so it has NO RLS policy and the tenant
    session protects it not at all — the tenant of an operation is whoever owns its asset.

    Four of the five handlers selected `Operation` by id or not at all. `/active` was the
    one that joined `assets`, under a comment recording that the join "is no longer
    optional" after this same defect was fixed THERE. It was fixed on one handler and the
    other four kept the unscoped shape, which is why each is asserted separately here rather
    than trusting one representative.
    """

    async def test_the_list_does_not_return_another_tenants_operations(
        self, client_b, running_operation
    ):
        response = await client_b.get(f"{OPERATIONS}/")
        assert response.status_code == 200, response.text[:200]
        ids = {item["id"] for item in response.json()["items"]}
        assert str(running_operation["operation"]) not in ids, (
            "GET /operations/ returned an operation belonging to another organisation. The "
            "table has no RLS; the join to `assets` is the only thing scoping it."
        )

    async def test_the_list_total_counts_only_this_tenant(self, client_b, running_operation):
        """The denominator, separately (rule 165). A joined page with an unjoined COUNT
        reports 'showing 20 of 4,000' where the 4,000 is every tenant's rows."""
        response = await client_b.get(f"{OPERATIONS}/")
        meta = response.json()["meta"]
        items = response.json()["items"]
        assert meta["total"] >= len(items)
        own = await client_b.get(f"{OPERATIONS}/", params={"asset_id": str(running_operation["asset"])})
        assert own.json()["meta"]["total"] == 0, (
            "filtering by another tenant's asset id reported a non-zero total"
        )

    async def test_reading_one_by_id_is_scoped(self, client_b, running_operation):
        response = await client_b.get(f"{OPERATIONS}/{running_operation['operation']}")
        assert response.status_code == 404, response.text[:200]

    async def test_the_packml_summary_is_scoped(self, client_b, running_operation):
        response = await client_b.get(
            f"{OPERATIONS}/{running_operation['operation']}/packml-summary"
        )
        assert response.status_code == 404, response.text[:200]

    async def test_the_owner_can_still_read_it(self, client_a, running_operation):
        """The other direction, so none of the above passes by the route being broken for
        everybody."""
        assert (
            await client_a.get(f"{OPERATIONS}/{running_operation['operation']}")
        ).status_code == 200
        listed = await client_a.get(
            f"{OPERATIONS}/", params={"asset_id": str(running_operation["asset"])}
        )
        assert str(running_operation["operation"]) in {
            item["id"] for item in listed.json()["items"]
        }
