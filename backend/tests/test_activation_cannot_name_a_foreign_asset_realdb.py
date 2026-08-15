"""An activated insight may only name an asset the caller can see (FS-729).

THE FOURTH INSTANCE OF ONE CLASS, and the one that took the most work to see. A foreign-key
check is performed by the database at a level RLS does not filter, so a WRITE can reference a
row the writer cannot read — `operations` (FS-720), four shop-floor writes (FS-724), two
notification subscriptions (FS-726), and this.

WHAT MADE THIS ONE DIFFERENT. `insight_activations` **has no `asset_id` column**, so a sweep
that matches request fields against the columns of the table a route writes to would clear it.
The value is carried through into the Kanban `Task` the activation creates, and
`tasks.asset_id` is the foreign key. The id crosses the boundary one object later than the
route that accepted it.

AND IT DOES NOT REPRODUCE ON AN EMPTY TENANT. The task is only created when
`_pick_board_and_column` finds a board, so the first probe of this returned 201 and **zero**
rows, which reads exactly like "no defect here". Bootstrapping the caller's board first —
which every real deployment has, and a fresh fixture does not — produced the task. A negative
result from a fixture that is missing the state the code path needs is not a negative result.

The consequence is a card on org B's board pointing at a machine org B cannot resolve: the
asset renders as nothing, and the task's asset linkage is what correlation and reporting read
to attribute work to equipment.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

ACTIVATIONS = "/api/v1/insights/activations"


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


@pytest_asyncio.fixture
async def org_a_asset(admin_sync_url, seeded_orgs):
    ids = {"type": uuid.uuid4(), "asset": uuid.uuid4()}
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, 'machine')",
            (str(ids["type"]), f"FS729-{uuid.uuid4().hex[:8]}"),
        )
        cur.execute(
            "INSERT INTO assets (id, organization_id, asset_type_id, workcell_id, name, is_active) "
            "VALUES (%s, %s, %s, %s, 'FS729 Asset', true)",
            (
                str(ids["asset"]),
                str(seeded_orgs["org_a_id"]),
                str(ids["type"]),
                str(seeded_orgs["workcell_a_id"]),
            ),
        )
    yield ids["asset"]
    with conn.cursor() as cur:
        cur.execute("DELETE FROM tasks WHERE asset_id = %s", (str(ids["asset"]),))
        cur.execute("DELETE FROM assets WHERE id = %s", (str(ids["asset"]),))
        cur.execute("DELETE FROM asset_types WHERE id = %s", (str(ids["type"]),))
    conn.close()


@pytest_asyncio.fixture
async def org_a_session(admin_sync_url, seeded_orgs):
    """An analysis session owned by ORG A. `analysis_sessions` IS under RLS — which is the
    point: the read is protected and the REFERENCE is not."""
    import psycopg2

    session_id = uuid.uuid4()
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO analysis_sessions (id, organization_id, user_id, title) "
            "VALUES (%s, %s, %s, 'FS729 Session')",
            (str(session_id), str(seeded_orgs["org_a_id"]), str(seeded_orgs["user_a_id"])),
        )
    yield session_id
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM insight_activations WHERE session_id = %s", (str(session_id),)
        )
        cur.execute("DELETE FROM analysis_sessions WHERE id = %s", (str(session_id),))
    conn.close()


@pytest_asyncio.fixture
async def board_for_org_b(client_b):
    """THE STATE THE DEFECT NEEDS. `GET /kanban/board` creates the organisation's default
    board if it has none, and no task is created without one — so without this fixture the
    cross-tenant write silently does not happen and the test passes for the wrong reason."""
    response = await client_b.get("/api/v1/kanban/board")
    assert response.status_code == 200, response.text[:200]
    return response.json()["board"]["id"]


class TestAnActivationCannotReachAcrossTenants:
    async def test_another_tenants_asset_is_refused(
        self, client_b, board_for_org_b, org_a_asset
    ):
        response = await client_b.post(
            ACTIVATIONS, json={"title": "cross-tenant", "asset_id": str(org_a_asset)}
        )
        assert response.status_code == 404, (
            f"org B activated an insight against org A's asset and got "
            f"{response.status_code}. The foreign key is checked below RLS, so only the "
            f"handler can refuse it."
        )

    async def test_no_task_references_the_foreign_asset(
        self, client_b, board_for_org_b, org_a_asset, admin_sync_url
    ):
        """The status code is not the property. The task is created one object after the
        route returns its id, so the absence of the ROW is what has to be asserted."""
        await client_b.post(
            ACTIVATIONS, json={"title": "cross-tenant", "asset_id": str(org_a_asset)}
        )
        conn = _conn(admin_sync_url)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT count(*) FROM tasks WHERE asset_id = %s", (str(org_a_asset),)
            )
            count = cur.fetchone()[0]
        conn.close()
        assert count == 0, (
            "a Kanban task was created on org B's board pointing at org A's asset"
        )

    async def test_another_tenants_analysis_session_is_refused(
        self, client_b, board_for_org_b, org_a_session
    ):
        """THE SAME ROUTE, ONE FIELD OVER. `insight_activations.session_id` is a foreign key
        to `analysis_sessions`, so the asset fix alone left an identical door open — rule
        218: when the defect is a FIELD, enumerate every field on the route that carries
        one, not only the one the report named."""
        response = await client_b.post(
            ACTIVATIONS, json={"title": "cross-tenant session", "session_id": str(org_a_session)}
        )
        assert response.status_code == 404, (
            f"org B activated against org A's analysis session and got "
            f"{response.status_code}"
        )

    async def test_a_malformed_asset_is_a_422(self, client_b, board_for_org_b):
        response = await client_b.post(
            ACTIVATIONS, json={"title": "bad id", "asset_id": "not-a-uuid"}
        )
        assert response.status_code == 422, response.text[:200]


class TestTheOrdinaryPathsStillWork:
    """Everything above is satisfied by a route that refuses every activation."""

    async def test_the_owner_can_activate_against_their_own_asset(
        self, client_a, org_a_asset
    ):
        response = await client_a.post(
            ACTIVATIONS, json={"title": "own asset", "asset_id": str(org_a_asset)}
        )
        assert response.status_code == 201, response.text[:300]

    async def test_an_activation_without_an_asset_still_works(self, client_b):
        """`asset_id` is optional — a manually entered action names no machine, and the
        docstring on `ActivateRequest` says so."""
        response = await client_b.post(ACTIVATIONS, json={"title": "no asset"})
        assert response.status_code == 201, response.text[:300]
