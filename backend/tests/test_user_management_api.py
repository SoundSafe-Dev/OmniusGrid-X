"""Admin user management (FS-221) against a real Postgres.

`users` is NOT an RLS-protected table — it is absent from migrations 011/033 — so
`app.current_org_id` does nothing for it and the ONLY thing separating tenants is
the explicit `organization_id` predicate in each query. That is the same situation
`alarms` was in when five of its six endpoints leaked (FS-216), so every endpoint
here is asserted individually rather than a representative sample, and the write
paths are checked for what actually landed in the database rather than trusting a
404 response.

The last-admin guards are the other focus. Losing the final active admin in an
organization is unrecoverable through the product — nobody left can manage users —
so it has to be refused rather than merely discouraged.
"""

from __future__ import annotations

from uuid import uuid4


def _payload(**over) -> dict:
    base = {
        "email": f"new-{uuid4().hex[:10]}@test.local",
        "full_name": "New Person",
        "password": "a-sufficiently-long-password",
        "role": "operator",
    }
    base.update(over)
    return base


def _set_role(admin_sync_url: str, user_id, role: str) -> None:
    """Force a user's role (superuser, bypasses RLS).

    NOTE: the `seeded_orgs` fixture already creates BOTH users as `admin`, so
    tests that need a non-admin caller must demote explicitly. Assuming the
    default `operator` here would make an admin-gate test pass for the wrong
    reason — it would be asserting against an admin and never exercising the gate.
    """
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("UPDATE users SET role = %s WHERE id = %s;", (role, str(user_id)))
    finally:
        conn.close()


def _read_user(admin_sync_url: str, user_id) -> dict | None:
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT role, is_active, organization_id, full_name FROM users WHERE id = %s;",
                (str(user_id),),
            )
            row = cur.fetchone()
    finally:
        conn.close()
    if row is None:
        return None
    return {
        "role": row[0],
        "is_active": row[1],
        "organization_id": row[2],
        "full_name": row[3],
    }


def _seed_extra_admin(admin_sync_url: str, org_id) -> str:
    """A second active admin, so last-admin guards don't block unrelated tests."""
    import psycopg2

    user_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (id, email, hashed_password, full_name,
                                   organization_id, role, is_active)
                VALUES (%s, %s, 'x', 'Spare Admin', %s, 'admin', TRUE);
                """,
                (user_id, f"spare-{user_id[:8]}@test.local", str(org_id)),
            )
    finally:
        conn.close()
    return user_id


# ---------------------------------------------------------------------------
# Authorization
# ---------------------------------------------------------------------------

class TestAdminOnly:
    async def test_non_admin_cannot_reach_any_endpoint(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """Every route must 403 for a non-admin.

        Asserted across all five rather than one: the gate is declared on the
        router, and this is what proves a future endpoint added there inherits it.
        """
        # The fixture seeds admins, so demote before testing the gate.
        _set_role(admin_sync_url, seeded_orgs["user_a_id"], "operator")
        uid = str(seeded_orgs["user_a_id"])
        for method, path in (
            ("get", "/api/v1/users/"),
            ("get", f"/api/v1/users/{uid}"),
            ("post", "/api/v1/users/"),
            ("patch", f"/api/v1/users/{uid}"),
            ("delete", f"/api/v1/users/{uid}"),
        ):
            call = getattr(client_a, method)
            resp = await (call(path, json=_payload()) if method in ("post", "patch") else call(path))
            assert resp.status_code == 403, f"{method.upper()} {path} was not admin-gated"


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------

class TestUserCrud:
    async def test_admin_can_create_and_list(self, client_a, admin_sync_url, seeded_orgs):

        created = await client_a.post("/api/v1/users/", json=_payload())
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["role"] == "operator"
        assert body["is_active"] is True
        # The response model must not leak the credential hash.
        assert "hashed_password" not in body

        # Placed in the CALLER's org, which the payload never mentions.
        row = _read_user(admin_sync_url, body["id"])
        assert str(row["organization_id"]) == str(seeded_orgs["org_a_id"])

        listed = await client_a.get("/api/v1/users/")
        assert listed.status_code == 200
        assert body["id"] in [u["id"] for u in listed.json()["items"]]

    async def test_duplicate_email_is_a_conflict_not_a_500(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """users.email is UNIQUE across the whole table, not per organization."""
        payload = _payload()
        assert (await client_a.post("/api/v1/users/", json=payload)).status_code == 201
        again = await client_a.post("/api/v1/users/", json=payload)
        assert again.status_code == 409, again.text

    async def test_patch_only_changes_what_was_sent(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        created = await client_a.post(
            "/api/v1/users/", json=_payload(full_name="Original", role="operator")
        )
        uid = created.json()["id"]

        patched = await client_a.patch(f"/api/v1/users/{uid}", json={"role": "viewer"})
        assert patched.status_code == 200
        body = patched.json()
        assert body["role"] == "viewer"
        # Omitting full_name must not blank it, and omitting is_active must not
        # flip it — the reason UserAdminUpdate is a separate schema.
        assert body["full_name"] == "Original"
        assert body["is_active"] is True

    async def test_delete_deactivates_and_preserves_the_row(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """Hard-deleting would break alarms.acknowledged_by and alarm_rules.created_by,
        or erase the record of who did what."""
        created = await client_a.post("/api/v1/users/", json=_payload())
        uid = created.json()["id"]

        resp = await client_a.delete(f"/api/v1/users/{uid}")
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False

        row = _read_user(admin_sync_url, uid)
        assert row is not None, "the user row was deleted rather than deactivated"
        assert row["is_active"] is False

    async def test_role_filter_narrows_the_list(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        await client_a.post("/api/v1/users/", json=_payload(role="viewer", full_name="V"))
        listed = await client_a.get("/api/v1/users/", params={"role": "viewer"})
        assert listed.status_code == 200
        assert all(u["role"] == "viewer" for u in listed.json()["items"])


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------

class TestValidation:
    async def test_invalid_role_is_rejected(self, client_a, admin_sync_url, seeded_orgs):
        resp = await client_a.post("/api/v1/users/", json=_payload(role="Admin"))
        assert resp.status_code == 422, (
            "a typo'd role would store fine and then match no dependency"
        )

    async def test_short_password_is_rejected(self, client_a, admin_sync_url, seeded_orgs):
        resp = await client_a.post("/api/v1/users/", json=_payload(password="short"))
        assert resp.status_code == 422

    async def test_malformed_email_is_rejected(self, client_a, admin_sync_url, seeded_orgs):
        for bad in ("no-at-sign", "spaces in@x.com", "missing@tld"):
            resp = await client_a.post("/api/v1/users/", json=_payload(email=bad))
            assert resp.status_code == 422, f"accepted {bad!r}"


# ---------------------------------------------------------------------------
# Tenancy — the table has no RLS, so these are the only barrier
# ---------------------------------------------------------------------------

class TestTenancy:
    async def test_list_excludes_other_organizations(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        listed = await client_a.get("/api/v1/users/")
        ids = [u["id"] for u in listed.json()["items"]]
        assert str(seeded_orgs["user_b_id"]) not in ids, "listed another org's user"

    async def test_get_patch_delete_are_404_for_a_foreign_user(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        foreign = str(seeded_orgs["user_b_id"])
        before = _read_user(admin_sync_url, foreign)

        assert (await client_a.get(f"/api/v1/users/{foreign}")).status_code == 404
        assert (
            await client_a.patch(f"/api/v1/users/{foreign}", json={"role": "admin"})
        ).status_code == 404
        assert (await client_a.delete(f"/api/v1/users/{foreign}")).status_code == 404

        # A 404 is not proof: confirm nothing was written.
        after = _read_user(admin_sync_url, foreign)
        assert after == before, "a cross-tenant write landed despite the 404"


# ---------------------------------------------------------------------------
# Last-admin guards
# ---------------------------------------------------------------------------

class TestLastAdminGuards:
    async def test_cannot_demote_the_last_active_admin(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """Unrecoverable through the product: nobody left could manage users."""
        spare = _seed_extra_admin(admin_sync_url, seeded_orgs["org_a_id"])

        # With two admins, demoting one is fine.
        ok = await client_a.patch(f"/api/v1/users/{spare}", json={"role": "operator"})
        assert ok.status_code == 200

        # Now the caller is the last admin — demoting them must be refused.
        me = str(seeded_orgs["user_a_id"])
        refused = await client_a.patch(f"/api/v1/users/{me}", json={"role": "operator"})
        assert refused.status_code == 409, refused.text
        assert _read_user(admin_sync_url, me)["role"] == "admin", "demotion landed anyway"

    async def test_cannot_deactivate_the_last_active_admin(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        spare = _seed_extra_admin(admin_sync_url, seeded_orgs["org_a_id"])

        refused = await client_a.patch(f"/api/v1/users/{spare}", json={"is_active": False})
        assert refused.status_code == 200, "two admins existed; this should be allowed"

        me = str(seeded_orgs["user_a_id"])
        refused = await client_a.patch(f"/api/v1/users/{me}", json={"is_active": False})
        assert refused.status_code == 409
        assert _read_user(admin_sync_url, me)["is_active"] is True

    async def test_cannot_deactivate_your_own_account(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """Even with another admin present: it would log the caller out mid-request."""
        _seed_extra_admin(admin_sync_url, seeded_orgs["org_a_id"])

        me = str(seeded_orgs["user_a_id"])
        resp = await client_a.delete(f"/api/v1/users/{me}")
        assert resp.status_code == 409
        assert _read_user(admin_sync_url, me)["is_active"] is True

    async def test_an_admin_in_another_org_does_not_count(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """The remaining-admin count must be scoped to the organization.

        If it counted admins globally, org B having an admin would permit org A to
        strand itself — the count is an authorization decision, so it needs the
        same tenant predicate as everything else on this table.
        """

        me = str(seeded_orgs["user_a_id"])
        refused = await client_a.patch(f"/api/v1/users/{me}", json={"role": "viewer"})
        assert refused.status_code == 409, (
            "another organization's admin was counted as cover"
        )


# ---------------------------------------------------------------------------
# Audit trail
# ---------------------------------------------------------------------------

def _audit_rows(admin_sync_url: str, resource_id) -> list[tuple]:
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT action, details, user_id, organization_id FROM audit_logs "
                "WHERE resource_type = 'user' AND resource_id = %s ORDER BY timestamp;",
                (str(resource_id),),
            )
            return cur.fetchall()
    finally:
        conn.close()


class TestAuditTrail:
    """The audit trail was SILENTLY EMPTY on real deployments.

    `AuditLog.ip_address` was declared VARCHAR while migrations create it as INET,
    so every insert was rejected — and the writer swallowed the failure as a debug
    log, so writes appeared to succeed. These tests therefore assert rows are
    actually READ BACK from the table, not that a helper returned truthily.
    """

    async def test_create_writes_an_audit_row(self, client_a, admin_sync_url, seeded_orgs):
        created = await client_a.post("/api/v1/users/", json=_payload())
        uid = created.json()["id"]

        rows = _audit_rows(admin_sync_url, uid)
        assert len(rows) == 1, f"no audit row for user_created: {rows}"
        action, details, actor, org = rows[0]
        assert action == "user_created"
        assert details["role"] == "operator"
        assert str(actor) == str(seeded_orgs["user_a_id"])
        assert str(org) == str(seeded_orgs["org_a_id"])

    async def test_role_change_is_audited_with_both_values(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """Recording only the new role would make the trail unusable for answering
        "what did this account lose access to?"."""
        created = await client_a.post("/api/v1/users/", json=_payload(role="operator"))
        uid = created.json()["id"]

        await client_a.patch(f"/api/v1/users/{uid}", json={"role": "admin"})

        actions = [r[0] for r in _audit_rows(admin_sync_url, uid)]
        assert "user_role_changed" in actions

        row = [r for r in _audit_rows(admin_sync_url, uid) if r[0] == "user_role_changed"][0]
        assert row[1] == {"previous_role": "operator", "new_role": "admin"}

    async def test_deactivation_is_audited(self, client_a, admin_sync_url, seeded_orgs):
        created = await client_a.post("/api/v1/users/", json=_payload())
        uid = created.json()["id"]
        await client_a.delete(f"/api/v1/users/{uid}")

        actions = [r[0] for r in _audit_rows(admin_sync_url, uid)]
        assert "user_deactivated" in actions

    async def test_a_refused_change_writes_no_audit_row(
        self, client_a, admin_sync_url, seeded_orgs
    ):
        """The audit row shares the transaction with the change it describes, so a
        409 must leave no trace of something that did not happen."""
        me = str(seeded_orgs["user_a_id"])
        before = len(_audit_rows(admin_sync_url, me))

        refused = await client_a.patch(f"/api/v1/users/{me}", json={"role": "viewer"})
        assert refused.status_code == 409

        assert len(_audit_rows(admin_sync_url, me)) == before, (
            "a refused role change was audited as if it happened"
        )
