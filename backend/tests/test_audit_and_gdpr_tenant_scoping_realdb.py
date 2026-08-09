"""The audit trail and the GDPR processing records must actually return rows.

THE DEFECT. `audit_logs` and `data_processing_records` have had tenant policies since
migration 011, and every handler in `audit.py` and `gdpr.py` ran on `get_db` — which
sets no `app.current_org_id`. `NULLIF(current_setting(...), '')` is then NULL, the
policy matches nothing, and **every endpoint returned zero rows, including for the
caller's own organization**.

So the audit trail was silently blank. That is the precise failure an audit trail exists
to make impossible, and it is invisible from the outside: HTTP 200 with an empty list
reads as "nothing has happened yet", not as a bug. The glossary already named this
failure mode — "the silently empty audit trail" — which makes it a good example of a
known class outliving the note about it.

`gdpr.py` is the sharper illustration. Its handlers filtered on
`current_user.organization_id` **correctly**. It made no difference: a correct
application-layer filter is no help when RLS has already removed the row.

WHAT WAS DELIBERATELY DECIDED, not merely fixed. `list_audit_logs` carried:

    if current_user.role != "admin" and current_user.organization_id:
        query = query.where(AuditLog.organization_id == current_user.organization_id)

unreachable, because the endpoint is gated on `require_admin` so `role` is always
"admin". It was written for a cross-organization admin view. A tenant admin reading
another tenant's audit trail is exactly what an audit trail should preclude, so the
scoping is now the caller's own organization, enforced by the policy. Genuine cross-org
access needs the super-admin role that does not exist yet.

`consent_records` is untouched: no `organization_id`, no policy, scoped by `user_id`,
which is the right grain for consent.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio


@pytest_asyncio.fixture
async def audit_rows(admin_sync_url, seeded_orgs):
    import psycopg2

    log_a, log_b = uuid.uuid4(), uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        for log_id, org_key, action in (
            (log_a, "org_a_id", "scoping_test_a"),
            (log_b, "org_b_id", "scoping_test_b"),
        ):
            cur.execute(
                "INSERT INTO audit_logs (id, organization_id, action, resource_type, "
                "timestamp) VALUES (%s, %s, %s, 'test', %s)",
                (str(log_id), str(seeded_orgs[org_key]), action,
                 datetime.now(timezone.utc)),
            )
    yield log_a, log_b
    with conn.cursor() as cur:
        cur.execute("DELETE FROM audit_logs WHERE id IN (%s, %s)",
                    (str(log_a), str(log_b)))
    conn.close()


@pytest_asyncio.fixture
async def processing_records(admin_sync_url, seeded_orgs):
    import psycopg2

    rec_a, rec_b = uuid.uuid4(), uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        for rec_id, org_key, purpose in (
            (rec_a, "org_a_id", "PURPOSE-A"),
            (rec_b, "org_b_id", "PURPOSE-B"),
        ):
            cur.execute(
                "INSERT INTO data_processing_records "
                "(id, organization_id, processing_activity, data_categories, purposes, "
                # data_categories/purposes are text[] in the database, though the ORM
                # declares them JSON — the model is not the schema.
                " legal_basis) VALUES (%s, %s, %s, '{}'::text[], '{}'::text[], 'consent')",
                (str(rec_id), str(seeded_orgs[org_key]), purpose),
            )
    yield rec_a, rec_b
    with conn.cursor() as cur:
        cur.execute("DELETE FROM data_processing_records WHERE id IN (%s, %s)",
                    (str(rec_a), str(rec_b)))
    conn.close()


def _rows(payload):
    return payload["items"] if isinstance(payload, dict) and "items" in payload else payload


class TestTheAuditTrailIsNotBlank:
    async def test_the_callers_own_entry_is_returned(self, client_a, audit_rows):
        """THE ASSERTION THIS FILE EXISTS FOR. This returned nothing — an audit trail
        that reports no activity is worse than one that errors."""
        log_a, _log_b = audit_rows
        response = await client_a.get("/api/v1/audit/logs")
        assert response.status_code == 200, response.text
        ids = {row.get("id") for row in _rows(response.json())}
        assert str(log_a) in ids, (
            "the caller's own audit entry is missing — the endpoint is still returning "
            "nothing, which is what a tenant policy with no GUC produces"
        )

    async def test_another_orgs_entry_is_not_returned(self, client_a, audit_rows):
        _log_a, log_b = audit_rows
        response = await client_a.get("/api/v1/audit/logs")
        ids = {row.get("id") for row in _rows(response.json())}
        assert str(log_b) not in ids, "one tenant's admin read another tenant's audit trail"

    async def test_each_org_sees_its_own(self, client_a, client_b, audit_rows):
        log_a, log_b = audit_rows
        a_ids = {r.get("id") for r in _rows((await client_a.get("/api/v1/audit/logs")).json())}
        b_ids = {r.get("id") for r in _rows((await client_b.get("/api/v1/audit/logs")).json())}
        assert str(log_a) in a_ids and str(log_a) not in b_ids
        assert str(log_b) in b_ids and str(log_b) not in a_ids

    async def test_naming_another_org_in_the_query_string_returns_nothing_extra(
        self, client_a, audit_rows, seeded_orgs
    ):
        """The endpoint still accepts an `organization_id` filter. It can narrow within
        the caller's own tenant; it must not widen beyond it."""
        _log_a, log_b = audit_rows
        response = await client_a.get(
            f"/api/v1/audit/logs?organization_id={seeded_orgs['org_b_id']}"
        )
        assert response.status_code == 200, response.text
        assert str(log_b) not in {row.get("id") for row in _rows(response.json())}


class TestGdprProcessingRecordsAreNotBlank:
    async def test_the_callers_own_record_is_returned(self, client_a, processing_records):
        """gdpr.py filtered on current_user.organization_id correctly and still
        returned nothing: RLS had already removed the row."""
        rec_a, _rec_b = processing_records
        response = await client_a.get("/api/v1/gdpr/processing-records")
        assert response.status_code == 200, response.text
        ids = {row.get("id") for row in _rows(response.json())}
        assert str(rec_a) in ids, "the caller's own processing record is missing"

    async def test_another_orgs_record_is_not_returned(self, client_a, processing_records):
        _rec_a, rec_b = processing_records
        response = await client_a.get("/api/v1/gdpr/processing-records")
        ids = {row.get("id") for row in _rows(response.json())}
        assert str(rec_b) not in ids
