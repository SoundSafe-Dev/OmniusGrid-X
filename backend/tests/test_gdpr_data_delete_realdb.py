"""The one route every walk deliberately skips (FS-358).

`/api/v1/gdpr/data-delete` sits in `SKIP_EXACT` in
`tests/test_write_endpoints_reject_cleanly_realdb.py`, and the reason recorded there is
sound:

    NEVER PROBED, AND NOT BECAUSE IT MIGHT FAIL. It takes no path parameter and erases the
    caller's data on request — a probe that "passes" here has deleted the organisation the
    rest of the walk is about. It is the one route where the cost of finding out is higher
    than the finding.

Correct for a walk, and the wrong outcome for coverage: it left a **destructive,
irreversible, GDPR-mandated endpoint with no test at all**. The skip protects the walk; it
was never meant to excuse the route.

THE ANSWER IS A DISPOSABLE SUBJECT. Every case below creates its own throwaway user and
deletes that user's data — never `client_a`'s, whose organisation the rest of the suite is
built on. That is the arrangement the walk cannot have, because a walk authenticates once
and reuses the session; a dedicated test can mint a subject per case and spend it.

WHAT "DELETE" MEANS HERE, and it is worth knowing before reading the assertions: the
handler calls `_anonymize_user`, so the row survives with its identifying fields cleared.
That is the right shape for GDPR erasure against a schema with foreign keys pointing at
`users` — a hard delete would either cascade into audit history or fail on a constraint,
and both are worse answers than anonymisation. The tests assert the identity is gone, not
that the row is.
"""

from __future__ import annotations

import uuid

import psycopg2
import pytest
from httpx import ASGITransport, AsyncClient

from app.core.config import settings

pytestmark = pytest.mark.asyncio

DELETE = "/api/v1/gdpr/data-delete"


def _make_user(admin_sync_url: str, organization_id) -> tuple[uuid.UUID, str]:
    """A user that exists only to be erased."""
    user_id = uuid.uuid4()
    email = f"erasure-{user_id.hex[:8]}@test.local"
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO users (id, email, hashed_password, organization_id, role,
                                   is_active, full_name)
                VALUES (%s, %s, %s, %s, %s, %s, %s);
                """,
                (str(user_id), email, "$2b$12$" + "x" * 53, str(organization_id),
                 "viewer", True, "Erasure Subject"),
            )
    finally:
        conn.close()
    return user_id, email


def _read_user(admin_sync_url: str, user_id: uuid.UUID):
    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT email, full_name, is_active FROM users WHERE id = %s",
                (str(user_id),),
            )
            return cur.fetchone()
    finally:
        conn.close()


def _client(app, user_id: uuid.UUID) -> AsyncClient:
    from tests.test_task10_rbac_api import _make_jwt

    token = _make_jwt(user_id, settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM)
    return AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    )


class TestTheConfirmationGuardHolds:
    """The only thing standing between a stray DELETE and an irreversible erasure."""

    async def test_no_confirmation_is_rejected(self, app, admin_sync_url, seeded_orgs):
        user_id, email = _make_user(admin_sync_url, seeded_orgs["org_a_id"])
        async with _client(app, user_id) as client:
            response = await client.delete(DELETE)
        assert response.status_code == 422, response.text
        assert _read_user(admin_sync_url, user_id)[0] == email, (
            "the account was erased by a request that carried no confirmation"
        )

    async def test_the_wrong_confirmation_is_rejected(self, app, admin_sync_url, seeded_orgs):
        user_id, email = _make_user(admin_sync_url, seeded_orgs["org_a_id"])
        async with _client(app, user_id) as client:
            response = await client.delete(DELETE, params={"confirmation": "delete"})
        assert response.status_code == 400, response.text
        assert _read_user(admin_sync_url, user_id)[0] == email, (
            "lowercase 'delete' erased the account — the guard is not exact"
        )

    async def test_an_anonymous_caller_cannot_erase_anyone(self, app):
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as anonymous:
            response = await anonymous.delete(DELETE, params={"confirmation": "DELETE"})
        assert response.status_code == 401


class TestTheErasureActuallyHappens:
    async def test_the_identifying_fields_are_cleared(self, app, admin_sync_url, seeded_orgs):
        """The assertion no walk could make: it needs a subject it is willing to lose."""
        user_id, email = _make_user(admin_sync_url, seeded_orgs["org_a_id"])

        async with _client(app, user_id) as client:
            response = await client.delete(DELETE, params={"confirmation": "DELETE"})
        assert response.status_code == 200, response.text

        row = _read_user(admin_sync_url, user_id)
        assert row is not None, (
            "the row was hard-deleted. GDPR erasure here is anonymisation by design — a "
            "hard delete would cascade into audit history or fail on a foreign key"
        )
        assert row[0] != email, "the email survived the erasure"
        assert row[1] != "Erasure Subject", "the full name survived the erasure"

    async def test_the_account_is_deactivated(self, app, admin_sync_url, seeded_orgs):
        """An anonymised account that can still authenticate is not erased."""
        user_id, _ = _make_user(admin_sync_url, seeded_orgs["org_a_id"])
        async with _client(app, user_id) as client:
            await client.delete(DELETE, params={"confirmation": "DELETE"})
        assert _read_user(admin_sync_url, user_id)[2] is False


class TestItErasesOnlyTheCaller:
    async def test_another_user_in_the_same_org_is_untouched(
        self, app, admin_sync_url, seeded_orgs
    ):
        """The endpoint takes no identifier, so the subject is entirely implicit — which is
        exactly the shape that erases the wrong person if the session is misread."""
        victim, _ = _make_user(admin_sync_url, seeded_orgs["org_a_id"])
        bystander, bystander_email = _make_user(admin_sync_url, seeded_orgs["org_a_id"])

        async with _client(app, victim) as client:
            await client.delete(DELETE, params={"confirmation": "DELETE"})

        assert _read_user(admin_sync_url, bystander)[0] == bystander_email, (
            "erasing one user's data also erased another user's in the same organisation"
        )
