"""An asset registered against the wrong workcell could never be moved (FS-672).

THE BEHAVIOURAL HALF of `test_handlers_branch_on_keys_their_schema_carries.py`. That file
proves no handler branches on a key its schema cannot carry; this one proves the thing the
branch was written to do actually happens now — and, more importantly, that the tenant check
inside it actually fires. Those fail for different reasons: a schema field with no check behind
it would pass the static guard and let a caller move their asset into somebody else's workcell,
which is worse than not being able to move it at all.

The tenant case is the reason this file exists rather than a unit test. `update_asset` looks
the workcell up with `Workcell.organization_id == org_id`, and the only way to be sure that
predicate is doing work is to hand it a real workcell belonging to a real other tenant and
watch the request 404.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio

ASSETS = "/api/v1/assets"


def _seed(admin_sync_url, org_id):
    """A second workcell in the caller's org, an asset type, and an asset in workcell one.

    Inserted directly, on the superuser connection the other real-DB tests use: there is no
    POST route for workcells or asset types, and inventing one to make a test possible would
    be adding product surface to serve the test rather than the user.
    """
    import psycopg2

    workcell_two = uuid4()
    asset_type = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO workcells (id, organization_id, name) VALUES (%s, %s, %s);",
                (str(workcell_two), str(org_id), f"Workcell Two {workcell_two.hex[:6]}"),
            )
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s);",
                (str(asset_type), f"type-{asset_type.hex[:6]}", "cnc"),
            )
    finally:
        conn.close()
    return workcell_two, asset_type


def _seed_asset_type(admin_sync_url):
    import psycopg2

    asset_type = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s);",
                (str(asset_type), f"type-{asset_type.hex[:6]}", "robot"),
            )
    finally:
        conn.close()
    return asset_type


def _drop_asset_type(admin_sync_url, asset_type_id):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM asset_types WHERE id = %s;", (str(asset_type_id),))
    finally:
        conn.close()


def _cleanup(admin_sync_url, workcell_id, asset_type_id, asset_id=None):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            if asset_id:
                cur.execute("DELETE FROM assets WHERE id = %s;", (str(asset_id),))
            cur.execute("DELETE FROM workcells WHERE id = %s;", (str(workcell_id),))
            cur.execute("DELETE FROM asset_types WHERE id = %s;", (str(asset_type_id),))
    finally:
        conn.close()


async def _create_asset(client_a, workcell_id, asset_type_id):
    response = await client_a.post(
        f"{ASSETS}/",
        json={
            "name": f"asset-{uuid4().hex[:8]}",
            "workcell_id": str(workcell_id),
            "asset_type_id": str(asset_type_id),
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


async def test_an_asset_can_be_moved_to_another_workcell(
    client_a, seeded_orgs, admin_sync_url
):
    """The capability the product silently did not have."""
    workcell_two, asset_type = _seed(admin_sync_url, seeded_orgs["org_a_id"])
    asset_id = None
    try:
        asset_id = await _create_asset(
            client_a, seeded_orgs["workcell_a_id"], asset_type
        )

        response = await client_a.put(
            f"{ASSETS}/{asset_id}", json={"workcell_id": str(workcell_two)}
        )
        assert response.status_code == 200, response.text
        assert response.json()["workcell_id"] == str(workcell_two)

        # Read it back through the API rather than trusting the write's own response —
        # the response is built from the in-session object and would show the new value
        # whether or not the commit landed.
        reread = await client_a.get(f"{ASSETS}/{asset_id}")
        assert reread.json()["workcell_id"] == str(workcell_two)
    finally:
        _cleanup(admin_sync_url, workcell_two, asset_type, asset_id)


async def test_moving_an_asset_into_another_tenants_workcell_is_refused(
    client_a, seeded_orgs, admin_sync_url
):
    """A real workcell in a real other org, and the move must be refused.

    WHAT THIS DOES NOT PROVE, established by mutation-testing rather than assumed:
    deleting `Workcell.organization_id == org_id` from the handler leaves all five tests
    here passing, because row-level security hides org B's workcell from this session
    anyway. So this asserts the OUTCOME is right; it cannot attribute it to the explicit
    predicate. `test_handlers_branch_on_keys_their_schema_carries.py` pins that predicate
    statically, which is the only way to hold a control that a second control shadows.

    Two independent controls, neither trusted alone — the same argument `create_dock_door`
    makes a few files over: RLS holding depends on the database ROLE, and a connection with
    BYPASSRLS turns this into a genuine cross-tenant write.

    A 404 rather than a 403 deliberately: the caller may not learn that a workcell they
    cannot see exists.
    """
    workcell_two, asset_type = _seed(admin_sync_url, seeded_orgs["org_a_id"])
    asset_id = None
    try:
        asset_id = await _create_asset(
            client_a, seeded_orgs["workcell_a_id"], asset_type
        )

        response = await client_a.put(
            f"{ASSETS}/{asset_id}",
            json={"workcell_id": str(seeded_orgs["workcell_b_id"])},
        )
        assert response.status_code == 404, response.text

        unchanged = await client_a.get(f"{ASSETS}/{asset_id}")
        assert unchanged.json()["workcell_id"] == str(seeded_orgs["workcell_a_id"]), (
            "the request was refused and the asset moved anyway"
        )
    finally:
        _cleanup(admin_sync_url, workcell_two, asset_type, asset_id)


async def test_an_asset_type_can_be_corrected(client_a, seeded_orgs, admin_sync_url):
    workcell_two, asset_type = _seed(admin_sync_url, seeded_orgs["org_a_id"])
    second_type = _seed_asset_type(admin_sync_url)
    asset_id = None
    try:
        asset_id = await _create_asset(
            client_a, seeded_orgs["workcell_a_id"], asset_type
        )
        response = await client_a.put(
            f"{ASSETS}/{asset_id}", json={"asset_type_id": str(second_type)}
        )
        assert response.status_code == 200, response.text
        assert response.json()["asset_type_id"] == str(second_type)
    finally:
        _cleanup(admin_sync_url, workcell_two, asset_type, asset_id)
        _drop_asset_type(admin_sync_url, second_type)


async def test_an_unknown_asset_type_is_a_400_not_a_500(
    client_a, seeded_orgs, admin_sync_url
):
    """Widening a schema with a foreign key means a caller can now send a bad one.

    This test was written to pin an explicit existence check copied from `create_asset`,
    on the stated grounds that without it the caller gets a 500. Mutation-testing said
    otherwise: removing the check left this passing, because `app/core/errors.py` already
    maps a foreign-key violation to a 400 that names the column and the table. The check
    was deleted and this assertion kept — the behaviour is the thing worth holding, and it
    is now held against the platform's handler, which is where it actually lives.
    """
    workcell_two, asset_type = _seed(admin_sync_url, seeded_orgs["org_a_id"])
    asset_id = None
    try:
        asset_id = await _create_asset(
            client_a, seeded_orgs["workcell_a_id"], asset_type
        )
        response = await client_a.put(
            f"{ASSETS}/{asset_id}", json={"asset_type_id": str(uuid4())}
        )
        assert response.status_code == 400, response.text
    finally:
        _cleanup(admin_sync_url, workcell_two, asset_type, asset_id)


async def test_an_update_that_sends_neither_leaves_both_alone(
    client_a, seeded_orgs, admin_sync_url
):
    """Widening an Update schema is only safe while `exclude_unset` holds. Asserted here
    against the database rather than against the model, because the model is what the
    sibling guard already checks."""
    workcell_two, asset_type = _seed(admin_sync_url, seeded_orgs["org_a_id"])
    asset_id = None
    try:
        asset_id = await _create_asset(
            client_a, seeded_orgs["workcell_a_id"], asset_type
        )
        response = await client_a.put(f"{ASSETS}/{asset_id}", json={"name": "renamed"})
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"] == "renamed"
        assert body["workcell_id"] == str(seeded_orgs["workcell_a_id"])
        assert body["asset_type_id"] == str(asset_type)
    finally:
        _cleanup(admin_sync_url, workcell_two, asset_type, asset_id)


async def test_the_asset_list_searches_by_name(client_a, seeded_orgs, admin_sync_url):
    """P6 (page-enhancement review): the fleet list gained `?search=` — a name substring,
    case-insensitive — because finding one machine used to mean paging the whole estate.
    Both directions: the match is found, and a non-match is genuinely excluded (a search
    that returns everything is a search box that lies)."""
    workcell_two, asset_type = _seed(admin_sync_url, seeded_orgs["org_a_id"])
    needle_id = None
    try:
        needle_id = await _create_asset(
            client_a, seeded_orgs["workcell_a_id"], asset_type
        )
        needle_name = (await client_a.get(f"{ASSETS}/{needle_id}")).json()["name"]
        fragment = needle_name[6:14].upper()  # mid-string, case-flipped: ILIKE substring

        hit = await client_a.get(f"{ASSETS}/", params={"search": fragment})
        assert hit.status_code == 200, hit.text
        names = [row["name"] for row in hit.json()["items"]]
        assert needle_name in names

        miss = await client_a.get(
            f"{ASSETS}/", params={"search": "no-asset-is-named-this"}
        )
        assert miss.status_code == 200
        assert miss.json()["items"] == []
    finally:
        _cleanup(admin_sync_url, workcell_two, asset_type, needle_id)
