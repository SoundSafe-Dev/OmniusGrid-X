"""Residency tags belong to a tenant (FS-433).

`data_residency_tags` has **no `organization_id` column and no RLS policy**, so every
tenant's tags sit in one pool with no owner. Six endpoints read and write it:

    POST   /data-residency/tag                      require_admin
    DELETE /data-residency/tag/{table}/{record_id}  require_admin
    POST   /data-residency/validate                 require_admin
    GET    /data-residency/tag/{table}/{record_id}  any authenticated user
    GET    /data-residency/tags                     any authenticated user
    GET    /data-residency/summary                  any authenticated user

`require_admin` in this codebase is a **per-organisation** admin — that is the whole reason
FS-311 exists, recording that eight data-retention routes are dark because "a per-org admin
would let one tenant purge another's data". The same argument applies here and nothing
enforced it.

So before the fix: org A's admin could delete org B's residency tags, and any authenticated
user could enumerate every tenant's tagged `record_id`s and the user ids that tagged them.
`/validate` and `/summary` counted across all tenants and reported the total as the caller's
own compliance position.

These tests are written to FAIL on the unfixed schema. That is the point — they were run
against it first.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

from tests._realdb import require_testcontainers
import pytest_asyncio

pytestmark = pytest.mark.asyncio

require_testcontainers()  # FS-808: skips on a laptop, FAILS when REQUIRE_REALDB=1

TABLE = "assets"


@pytest_asyncio.fixture
async def tags_for_both_orgs(admin_sync_url, seeded_orgs):
    """One residency tag per organisation, inserted past RLS as a superuser."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    tag_a, tag_b = uuid4(), uuid4()
    rec_a, rec_b = uuid4(), uuid4()
    with conn.cursor() as cur:
        for tag_id, rec_id, org_key, user_key in (
            (tag_a, rec_a, "org_a_id", "user_a_id"),
            (tag_b, rec_b, "org_b_id", "user_b_id"),
        ):
            cur.execute(
                "INSERT INTO data_residency_tags "
                "(id, organization_id, table_name, record_id, region, tagged_by) "
                "VALUES (%s, %s, %s, %s, 'us-east-1', %s)",
                (
                    str(tag_id),
                    str(seeded_orgs[org_key]),
                    TABLE,
                    str(rec_id),
                    str(seeded_orgs[user_key]),
                ),
            )
    yield {"tag_a": tag_a, "tag_b": tag_b, "rec_a": rec_a, "rec_b": rec_b}
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM data_residency_tags WHERE id IN (%s, %s)",
            (str(tag_a), str(tag_b)),
        )
    conn.close()


def _rows(payload):
    if isinstance(payload, dict):
        return payload.get("items") or payload.get("tags") or []
    return payload


class TestTheListIsScoped:
    async def test_the_owner_sees_their_own_tag(self, client_a, tags_for_both_orgs):
        """Asserted first and deliberately: without it, everything below is satisfied by
        an empty list — the failure mode FS-431 found in the kanban suite."""
        rows = _rows((await client_a.get("/api/v1/data-residency/tags")).json())
        assert any(
            str(r.get("record_id")) == str(tags_for_both_orgs["rec_a"]) for r in rows
        ), f"org A cannot see its own residency tag ({len(rows)} rows returned)"

    async def test_the_other_tenants_tag_is_not_listed(
        self, client_a, tags_for_both_orgs
    ):
        rows = _rows((await client_a.get("/api/v1/data-residency/tags")).json())
        assert not any(
            str(r.get("record_id")) == str(tags_for_both_orgs["rec_b"]) for r in rows
        ), (
            "org A can enumerate org B's tagged record ids. Each row also carries "
            "`tagged_by`, so this exposes which of another tenant's users tagged what"
        )


class TestReadByIdIsScoped:
    async def test_the_owner_can_read_their_tag(self, client_a, tags_for_both_orgs):
        response = await client_a.get(
            f"/api/v1/data-residency/tag/{TABLE}/{tags_for_both_orgs['rec_a']}"
        )
        assert response.status_code == 200, response.text

    async def test_another_tenants_tag_reads_as_untagged(
        self, client_a, tags_for_both_orgs
    ):
        """`tagged: false`, not 404 — and that is the better answer.

        A 404 would distinguish "no tag exists" from "a tag exists but is not yours",
        which tells the caller that a record id they guessed is real and tagged by someone
        else. This endpoint declines to make that distinction, so probing it reveals
        nothing either way. The scoping is what makes it true; before the fix this returned
        org B's region and `tagged_by` user id.
        """
        body = (
            await client_a.get(
                f"/api/v1/data-residency/tag/{TABLE}/{tags_for_both_orgs['rec_b']}"
            )
        ).json()
        assert body["tagged"] is False, "org A read org B's residency tag directly"
        assert body.get("region") is None
        assert body.get("tagged_by") is None, (
            "another tenant's tagging user id was disclosed"
        )


class TestTheAggregatesCountOnlyTheCallersOwn:
    async def test_the_summary_does_not_count_the_other_tenant(
        self, client_a, tags_for_both_orgs
    ):
        body = (await client_a.get("/api/v1/data-residency/summary")).json()
        assert body["by_table"].get(TABLE) == 1, (
            f"the residency summary counted {body['by_table'].get(TABLE)} tags for "
            f"'{TABLE}' where the caller owns 1 — it is reporting another tenant's "
            f"compliance position as this tenant's"
        )

    async def test_validate_does_not_count_the_other_tenant(
        self, client_a, tags_for_both_orgs
    ):
        # FS-902: table_names and expected_region are now one body model instead of
        # a body/query split.
        response = await client_a.post(
            "/api/v1/data-residency/validate",
            json={"table_names": [TABLE], "expected_region": "us-east-1"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["tagged_records"] == 1, (
            "/validate counted another tenant's tagged rows into this tenant's total"
        )


class TestWritesCannotReachAnotherTenant:
    async def test_a_per_org_admin_cannot_delete_another_tenants_tag(
        self, client_a, tags_for_both_orgs, admin_sync_url
    ):
        """`require_admin` is per-organisation. FS-311 records exactly this argument for
        the data-retention routes; nothing enforced it here."""
        import psycopg2

        response = await client_a.delete(
            f"/api/v1/data-residency/tag/{TABLE}/{tags_for_both_orgs['rec_b']}"
        )
        assert response.status_code == 404, (
            f"org A's admin deleted org B's residency tag: {response.status_code}"
        )

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT count(*) FROM data_residency_tags WHERE id = %s",
                    (str(tags_for_both_orgs["tag_b"]),),
                )
                assert cur.fetchone()[0] == 1, "org B's tag was deleted"
        finally:
            conn.close()

    async def test_a_new_tag_takes_its_org_from_the_token(
        self, client_a, seeded_orgs, admin_sync_url
    ):
        """The caller cannot choose the organisation a tag lands in.

        There is nowhere to try: `table_name`, `record_id` and `region` are QUERY
        parameters here (bare non-Pydantic params on a POST — the FS-379/FS-420 shape),
        and no organisation is accepted anywhere. This asserts the row lands on the
        caller's own org, which is the property that matters however it is supplied.
        """
        import psycopg2

        record_id = uuid4()
        response = await client_a.post(
            "/api/v1/data-residency/tag",
            params={
                "table_name": TABLE,
                "record_id": str(record_id),
                # 'USA' is the only region the write path accepts today.
                "region": "USA",
                "organization_id": str(seeded_orgs["org_b_id"]),  # not a parameter
            },
        )
        assert response.status_code in (200, 201), response.text

        conn = psycopg2.connect(admin_sync_url)
        try:
            with conn.cursor() as cur:
                cur.execute(
                    "SELECT organization_id FROM data_residency_tags WHERE record_id = %s",
                    (str(record_id),),
                )
                row = cur.fetchone()
                assert row is not None, "the tag was not written"
                assert str(row[0]) == str(seeded_orgs["org_a_id"]), (
                    "the tag was written against the organisation named in the BODY "
                    "rather than the caller's own"
                )
                cur.execute(
                    "DELETE FROM data_residency_tags WHERE record_id = %s",
                    (str(record_id),),
                )
        finally:
            conn.close()
