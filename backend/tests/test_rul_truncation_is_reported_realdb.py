"""`GET /api/v1/rul` must say when it returned only part of the fleet.

WHY THIS ENDPOINT AND NOT THE OTHER ELEVEN. Twelve list endpoints return a bare JSON
array capped at `limit`, so a full page is indistinguishable from the complete set. On
most of them that is ambiguity. Here it is misleading in a specific, harmful direction.

Remaining useful life is computed per asset in Python by `rul_service.assess_asset`, so
risk is not a column and cannot be sorted on in SQL. The page is therefore ordered by
asset NAME — which means the cap keeps the alphabetically-FIRST `limit` assets. An asset
three days from failure whose name begins with W is absent from the risk view entirely,
and the summary tiles ("Assets Assessed", "High / Critical Risk") counted the survivors as
though the fleet had been fully assessed. The one page whose purpose is finding machines
about to fail was quietly excluding some of them.

THE SIGNAL IS A HEADER, NOT AN ENVELOPE. The body is a bare array that clients already
consume; changing its shape would break every caller in order to fix a problem they could
then no longer see. `X-Result-Truncated` comes from a `limit + 1` probe — one extra row
rather than a COUNT over the whole table.

The convention already existed on the three ERP list endpoints. It moved to
`app/core/pagination.py` when this became its second user, and
`erp_integrations._mark_truncated` now delegates rather than keeping a second copy that
would drift the moment either was edited.
"""

from __future__ import annotations

from uuid import uuid4

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

EXTRA_ASSETS = 4


@pytest_asyncio.fixture
async def named_assets(admin_sync_url, seeded_orgs):
    """Assets whose names span the alphabet, so ordering is observable.

    The last name deliberately sorts after everything else: it is the asset a
    name-ordered cap drops first, and the one this test is really about.
    """
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    names = ["aardvark", "beryl", "cobalt", "zulu-critical"]
    ids = [uuid4() for _ in names]
    type_id = uuid4()
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'test')",
            (str(type_id), f"RUL-{type_id.hex[:8]}"),
        )
        for asset_id, name in zip(ids, names):
            cur.execute(
                "INSERT INTO assets (id, organization_id, workcell_id, asset_type_id, "
                "name, is_active) VALUES (%s, %s, %s, %s, %s, true)",
                (
                    str(asset_id),
                    str(seeded_orgs["org_a_id"]),
                    str(seeded_orgs["workcell_a_id"]),
                    str(type_id),
                    name,
                ),
            )
    yield {"names": names, "ids": ids, "count": len(names)}
    with conn.cursor() as cur:
        cur.execute("DELETE FROM assets WHERE id = ANY(%s::uuid[])", ([str(i) for i in ids],))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(type_id),))
    conn.close()


class TestTheSetupIsReal:
    """Every assertion below is about a cap that bites. If the org fits in one page,
    they all pass without the feature existing."""

    async def test_the_org_has_more_assets_than_the_page_under_test(
        self, client_a, named_assets
    ):
        full = await client_a.get("/api/v1/rul", params={"limit": 500})
        assert full.status_code == 200, full.text
        assert len(full.json()) > 2, (
            "fewer than three assets assessed; a limit of 2 cannot be shown to truncate"
        )


class TestTruncationIsReported:
    async def test_a_full_page_says_there_is_more(self, client_a, named_assets):
        """THE ASSERTION THIS FILE EXISTS FOR. Before the fix this returned exactly two
        rows with nothing to distinguish it from a two-asset fleet."""
        response = await client_a.get("/api/v1/rul", params={"limit": 2})
        assert response.status_code == 200, response.text
        assert len(response.json()) == 2
        assert response.headers.get("x-result-truncated") == "true", (
            "two of several assets were returned and the response claims to be complete"
        )

    async def test_the_last_page_does_not(self, client_a, named_assets):
        """The negative control. A header hardcoded to 'true' would satisfy the test
        above and tell a caller nothing."""
        response = await client_a.get("/api/v1/rul", params={"limit": 500})
        assert response.headers.get("x-result-truncated") == "false"

    async def test_the_applied_limit_is_reported(self, client_a, named_assets):
        response = await client_a.get("/api/v1/rul", params={"limit": 2})
        assert response.headers.get("x-result-limit") == "2"

    async def test_the_probe_row_is_not_returned_to_the_caller(
        self, client_a, named_assets
    ):
        """`limit + 1` is fetched to detect truncation. Returning it would hand back one
        more row than was asked for, which is its own quiet contract break."""
        body = (await client_a.get("/api/v1/rul", params={"limit": 3})).json()
        assert len(body) == 3


class TestWhatTruncationActuallyCosts:
    """Naming the harm, so a later change that reorders or re-caps this endpoint has to
    confront it rather than rediscover it."""

    @staticmethod
    def _ids(page) -> list:
        """`RULResponse` carries no asset name — only `asset_id`. Asserting on names
        made the short-page check pass against ANY response, including an empty one."""
        return [row["asset_id"] for row in page]

    async def test_the_alphabetically_last_asset_is_absent_from_a_short_page(
        self, client_a, named_assets
    ):
        """Concretely: the asset named `zulu-critical` is not in a two-row page, and IS
        in the full one. That is the whole reason the header matters — nothing else in
        the response would tell a reader the fleet's worst asset might be missing."""
        zulu = str(named_assets["ids"][-1])

        page = self._ids((await client_a.get("/api/v1/rul", params={"limit": 2})).json())
        full = self._ids((await client_a.get("/api/v1/rul", params={"limit": 500})).json())

        assert zulu in full, (
            "the asset is missing from the FULL list too, so its absence from the short "
            "page would prove nothing"
        )
        assert zulu not in page, (
            "the name-ordered cap no longer drops the alphabetical tail; if this page is "
            "now risk-ordered, the truncation notice on PredictiveMaintenance.tsx says "
            "the wrong thing and must change with it"
        )

    async def test_the_page_returns_the_alphabetically_first_assets(
        self, client_a, named_assets
    ):
        """The other half: what a short page DOES contain. Together these pin the
        ordering the frontend notice describes."""
        page = self._ids((await client_a.get("/api/v1/rul", params={"limit": 2})).json())
        aardvark, beryl = str(named_assets["ids"][0]), str(named_assets["ids"][1])
        assert aardvark in page and beryl in page


class TestTenantScopingSurvivedTheChange:
    async def test_another_organisation_is_not_assessed(
        self, client_b, named_assets, seeded_orgs
    ):
        """The query gained a `+ 1` and a helper call. The org filter is what keeps this
        from assessing someone else's machines."""
        body = (await client_b.get("/api/v1/rul", params={"limit": 500})).json()
        theirs = {str(i) for i in named_assets["ids"]}
        assert not theirs & {row["asset_id"] for row in body}, (
            "org B is assessing org A's assets"
        )
