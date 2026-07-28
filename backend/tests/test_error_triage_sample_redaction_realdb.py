"""Another tenant's error message and traceback must not be readable.

THE DISCLOSURE. `error_events` is keyed on `fingerprint` alone — one row per distinct
error for the whole platform — so `/api/v1/admin/errors` is a cross-tenant triage view by
construction. `require_admin` means a TENANT admin, because no platform-admin role exists
yet. The detail endpoint therefore handed any tenant's admin any other tenant's
`message_sample` and `traceback_sample`.

Confirmed against a real database before the fix: org A retrieved a row owned by org B
carrying `customer_ssn=123-45-6789` in the message and a card number in the traceback,
and could PATCH its status. Exception text and tracebacks are the two fields most likely
to contain customer data, precisely because nobody chooses what goes into them.

The module docstring already flagged the tenant-filtering question as open. What it did
not have was evidence of what was actually exposed, which is the difference between a
design question and a disclosure.

WHAT CHANGED, AND WHAT DELIBERATELY DID NOT. Only the two payload-bearing fields are
withheld, and only from a viewer in a different organisation. Counts, route, method,
status and timestamps stay visible for everyone — that is the triage value and it carries
no payload. The list endpoint was already safe: it returns no samples at all.

Scoping the whole view by `organization_id` was rejected: with `fingerprint` as the
primary key a single row is shared by every tenant that hits the same bug, and its
`organization_id` names only one of them, so filtering would hide errors that genuinely
are the caller's. Redaction removes the leak without pretending the table is
tenant-partitioned when it is not.

If a platform-admin role is added, gate the samples on that rather than dropping the
check.
"""

from __future__ import annotations

from datetime import datetime, timezone

import pytest
import pytest_asyncio

pytestmark = pytest.mark.asyncio

FP_OTHER = "fp-owned-by-b01"       # fingerprint is varchar(16)
FP_OWN = "fp-owned-by-a01"
FP_ORPHAN = "fp-no-owner-001"
SECRET_MESSAGE = "customer_ssn=123-45-6789 failed validation"
SECRET_TRACE = 'File "handler.py", line 9\n  card="4111111111111111"'


@pytest_asyncio.fixture
async def errors(admin_sync_url, seeded_orgs):
    """One error owned by org B, one by org A, one with no owner."""
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    now = datetime.now(timezone.utc)
    rows = (
        (FP_OTHER, str(seeded_orgs["org_b_id"])),
        (FP_OWN, str(seeded_orgs["org_a_id"])),
        (FP_ORPHAN, None),
    )
    with conn.cursor() as cur:
        for fingerprint, org in rows:
            cur.execute(
                "INSERT INTO error_events (fingerprint, organization_id, exception_type, "
                "route, method, status_code, total_count, regression_count, status, "
                "first_seen, last_seen, message_sample, traceback_sample) "
                "VALUES (%s, %s, 'ValueError', '/api/v1/x', 'GET', 500, 1, 0, 'open', "
                "%s, %s, %s, %s)",
                (fingerprint, org, now, now, SECRET_MESSAGE, SECRET_TRACE),
            )
    yield
    with conn.cursor() as cur:
        cur.execute(
            "DELETE FROM error_events WHERE fingerprint IN (%s, %s, %s)",
            (FP_OTHER, FP_OWN, FP_ORPHAN),
        )
    conn.close()


class TestAnotherTenantsPayloadIsWithheld:
    async def test_the_message_sample_is_redacted(self, client_a, errors):
        """THE ASSERTION THIS FILE EXISTS FOR."""
        response = await client_a.get(f"/api/v1/admin/errors/{FP_OTHER}")
        assert response.status_code == 200, response.text
        assert SECRET_MESSAGE not in (response.json()["message_sample"] or ""), (
            "another tenant's error message — containing what looks like a customer "
            "SSN — was returned in full"
        )

    async def test_the_traceback_sample_is_redacted(self, client_a, errors):
        response = await client_a.get(f"/api/v1/admin/errors/{FP_OTHER}")
        assert "4111111111111111" not in (response.json()["traceback_sample"] or ""), (
            "another tenant's traceback, containing a card number, was returned in full"
        )

    async def test_the_redaction_says_why(self, client_a, errors):
        """An empty field reads as 'this error had no message', which is a different
        and false statement. The placeholder names the reason."""
        body = (await client_a.get(f"/api/v1/admin/errors/{FP_OTHER}")).json()
        assert "redacted" in (body["message_sample"] or "").lower()

    async def test_the_triage_data_is_still_there(self, client_a, errors):
        """Redacting the payload must not blind the platform triage view — the counts
        and route are the reason the cross-tenant view exists."""
        body = (await client_a.get(f"/api/v1/admin/errors/{FP_OTHER}")).json()
        assert body["exception_type"] == "ValueError"
        assert body["route"] == "/api/v1/x"
        assert body["total_count"] == 1
        assert body["status"] == "open"


class TestTheCallersOwnPayloadIsIntact:
    """Guards the opposite failure: redacting everything would satisfy the assertions
    above and make the feature useless for the tenant it belongs to."""

    async def test_the_owners_message_is_returned_in_full(self, client_a, errors):
        body = (await client_a.get(f"/api/v1/admin/errors/{FP_OWN}")).json()
        assert body["message_sample"] == SECRET_MESSAGE

    async def test_the_owners_traceback_is_returned_in_full(self, client_a, errors):
        body = (await client_a.get(f"/api/v1/admin/errors/{FP_OWN}")).json()
        assert body["traceback_sample"] == SECRET_TRACE

    async def test_an_unattributed_error_is_visible_to_everyone(self, client_a, errors):
        """A row with no organization_id is platform-level — it happened outside a
        tenant request, or predates attribution. Withholding it would hide shared
        infrastructure errors from the view that exists to triage them."""
        body = (await client_a.get(f"/api/v1/admin/errors/{FP_ORPHAN}")).json()
        assert body["message_sample"] == SECRET_MESSAGE


class TestTheListWasAlreadySafe:
    async def test_the_list_returns_no_samples(self, client_a, errors):
        """Pinned so a later change cannot add the payload back to the list, where the
        redaction does not apply."""
        response = await client_a.get("/api/v1/admin/errors")
        assert response.status_code == 200, response.text
        body = response.json()
        items = body["items"] if isinstance(body, dict) and "items" in body else body
        assert items, "no errors listed; the assertion below would be vacuous"
        for item in items:
            assert "message_sample" not in item
            assert "traceback_sample" not in item
