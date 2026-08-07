"""`GET /audit/logs` must not 500 on a row that has an IP address (FS-503).

THE DEFECT. `AuditLog.ip_address` is `String(45).with_variant(INET, "postgresql")`
(`app/db/models.py:1569`), so on Postgres the column is `INET` and the driver returns an
`ipaddress.IPv4Address`. The response model declares `ip_address: Optional[str]`
(`app/api/audit.py:36`). Pydantic will not accept an `IPv4Address` for a `str` field, so
serialising the response raises — twenty-five validation errors on a hundred-row page — and
FastAPI turns that into a **500**.

Every row with an IP breaks the page it appears on. The audit log is a compliance surface;
this is the endpoint an auditor opens.

WHY EVERY EXISTING TEST PASSES. Two independent reasons, and both are ordinary:

  * The tenant-scoping fixtures insert audit rows with **no ip_address**
    (`test_audit_and_gdpr_tenant_scoping_realdb.py:57-62`), so the column is NULL and
    `Optional[str]` accepts None happily.
  * SQLite has no `inet` type, so the variant falls back to `VARCHAR(45)` and the driver
    returns a plain string. Anything not marked `realdb` cannot see this at all.

HOW IT WAS FOUND. Not by a test — by FS-307. Moving the contract gate off the superuser
changed which rows RLS returned, the page came back containing an IP, and the endpoint 500'd.
It had been passing as a superuser because the rows it happened to see had none. **The defect
is a property of the schema and the failure is a property of the data**, which is Rule 117,
and this is the second instance of it in a week.

There is a comment directly above the column recording a *previous* incident on this same
field — inserts bound VARCHAR against an INET column and `audit_trail` swallowed the failure,
so "the audit trail has been silently empty on real deployments while every write appeared to
succeed". The write side of this field has already cost once.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest
import pytest_asyncio


@pytest_asyncio.fixture
async def audit_row_with_an_ip(admin_sync_url, seeded_orgs):
    """One audit row for org A, with the IP column populated.

    The existing fixtures leave it NULL, which is the whole reason this endpoint's failure
    went unnoticed.
    """
    import psycopg2

    log_id = uuid.uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO audit_logs (id, organization_id, action, resource_type, "
            "ip_address, user_agent, timestamp) "
            "VALUES (%s, %s, 'ip_address_regression', 'test', %s, %s, %s)",
            (
                str(log_id),
                str(seeded_orgs["org_a_id"]),
                "127.0.0.1",
                "pytest",
                datetime.now(timezone.utc),
            ),
        )
    yield log_id
    with conn.cursor() as cur:
        cur.execute("DELETE FROM audit_logs WHERE id = %s", (str(log_id),))
    conn.close()


def _rows(payload):
    return payload["items"] if isinstance(payload, dict) and "items" in payload else payload


@pytest.mark.realdb
class TestAnIPAddressDoesNotBreakThePage:
    async def test_the_list_returns_200(self, client_a, audit_row_with_an_ip):
        """The assertion the endpoint failed for as long as any row carried an IP."""
        response = await client_a.get("/api/v1/audit/logs")

        assert response.status_code == 200, (
            f"GET /audit/logs returned {response.status_code} for a page containing a row "
            f"with an ip_address. On Postgres the column is INET and the driver returns an "
            f"IPv4Address; the response model declares `str`, so pydantic rejects it and "
            f"FastAPI raises. Every row with an IP breaks the page it lands on."
        )

    async def test_the_ip_is_serialised_as_a_string(self, client_a, audit_row_with_an_ip):
        """And it must still be *there*. Dropping the field would make the test above pass
        while removing the value an auditor came for."""
        response = await client_a.get("/api/v1/audit/logs")
        assert response.status_code == 200

        rows = _rows(response.json())
        mine = [r for r in rows if r.get("id") == str(audit_row_with_an_ip)]
        assert mine, "the seeded row is not in the response at all"
        assert mine[0]["ip_address"] == "127.0.0.1", (
            f"expected the address as a string, got {mine[0]['ip_address']!r}"
        )

    async def test_a_null_ip_is_still_allowed(self, client_a, audit_row_with_an_ip):
        """The other direction. The column is nullable and most rows have no address —
        a fix that required one would break every row the old code handled."""
        response = await client_a.get("/api/v1/audit/logs")
        assert response.status_code == 200

        # The seeded row from other fixtures and any pre-existing rows have NULL here.
        for row in _rows(response.json()):
            assert "ip_address" in row, "the field vanished from the payload"
