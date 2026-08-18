"""A confirmed second factor is demanded at login (FS-750).

NIST SP 800-171 **3.5.3** — multifactor for local and network access to privileged accounts.
A named CMMC Level 2 practice with no partial credit, and the largest single gap in the
control catalogue until now.

WHY THIS FILE IS THE CONTROL AND THE ENDPOINTS ARE NOT. `keycloak_service.enable_mfa`
already existed and was on this repository's orphaned-definition list — present, untested,
called by nothing. Enrolment endpoints alone would have reproduced exactly that: an MFA
feature you can turn on that changes nothing about how anybody authenticates. **The
assertion that matters is that login REFUSES without the code**, and every other test here
supports it.

WHAT IS PINNED, in the order that decides whether this is real:

  1. login with the right password and no code is REFUSED once MFA is confirmed;
  2. login with the right password and the right code succeeds;
  3. an UNCONFIRMED enrolment does not gate login — an account that believes it has MFA and
     does not is worse than one that knows it has none, so the two states must differ;
  4. a code cannot be replayed inside its own 30-second window (RFC 6238 s5.2);
  5. a recovery code works once and then does not;
  6. disabling requires a code — otherwise a stolen session removes the factor, and the
     factor is worth exactly what the session is worth.
"""

from __future__ import annotations

import uuid

import pytest
import pytest_asyncio

from app.core import mfa as totp

pytestmark = pytest.mark.asyncio

LOGIN = "/api/v1/auth/login"
MFA = "/api/v1/mfa"
PASSWORD = "a-sufficiently-long-test-password"


def _conn(admin_sync_url):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    return conn


@pytest_asyncio.fixture
async def mfa_user(app, admin_sync_url, seeded_orgs):
    """A real user with a REAL password hash — the seeded fixtures use a synthetic one, and
    this file has to drive the actual login path rather than patch around it."""
    from httpx import ASGITransport, AsyncClient

    from app.core.password import hash_password
    from tests.conftest import _make_jwt
    from app.core.config import settings

    user_id = uuid.uuid4()
    email = f"mfa-{user_id.hex[:8]}@test.local"
    conn = _conn(admin_sync_url)
    with conn.cursor() as cur:
        cur.execute(
            "INSERT INTO users (id, email, hashed_password, organization_id, role, "
            "is_active) VALUES (%s, %s, %s, %s, 'admin', true)",
            (str(user_id), email, hash_password(PASSWORD), str(seeded_orgs["org_a_id"])),
        )
    token = _make_jwt(user_id, settings.JWT_SECRET_KEY, settings.JWT_ALGORITHM)
    transport = ASGITransport(app=app)
    async with AsyncClient(
        transport=transport,
        base_url="http://test",
        headers={"Authorization": f"Bearer {token}"},
    ) as client:
        yield {"client": client, "email": email, "id": user_id}
    with conn.cursor() as cur:
        cur.execute("DELETE FROM user_mfa WHERE user_id = %s", (str(user_id),))
        cur.execute("DELETE FROM users WHERE id = %s", (str(user_id),))
    conn.close()


async def _login(client, email, code=None):
    form = {"username": email, "password": PASSWORD}
    if code is not None:
        form["client_secret"] = code
    return await client.post(LOGIN, data=form)


async def _enrol_and_confirm(user):
    """Returns (secret, recovery_codes)."""
    enroll = await user["client"].post(f"{MFA}/enroll")
    assert enroll.status_code == 200, enroll.text[:300]
    secret = enroll.json()["secret"]
    code = totp._code_for_window(secret, totp.current_window())
    confirmed = await user["client"].post(f"{MFA}/confirm", json={"code": code})
    assert confirmed.status_code == 200, confirmed.text[:300]
    return secret, confirmed.json()["recovery_codes"]


class TestLoginDemandsTheSecondFactor:
    async def test_without_mfa_the_password_alone_works(self, app, mfa_user):
        """The denominator. If this fails, the refusal below proves nothing about MFA."""
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as anon:
            response = await _login(anon, mfa_user["email"])
        assert response.status_code == 200, response.text[:300]

    async def test_a_confirmed_factor_refuses_a_password_only_login(self, app, mfa_user):
        """THE ASSERTION THIS WHOLE FEATURE EXISTS FOR."""
        await _enrol_and_confirm(mfa_user)
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as anon:
            response = await _login(anon, mfa_user["email"])
        assert response.status_code == 401, (
            f"the correct password alone returned {response.status_code} for an account "
            f"with MFA enabled — the second factor is not enforced, which is the exact "
            f"shape of the unreachable Keycloak helpers this replaced"
        )
        assert "multifactor" in response.text.lower()

    async def test_the_right_code_lets_you_in(self, app, mfa_user):
        secret, _codes = await _enrol_and_confirm(mfa_user)
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as anon:
            code = totp._code_for_window(secret, totp.current_window() + 1)
            response = await _login(anon, mfa_user["email"], code)
        assert response.status_code == 200, response.text[:300]
        assert response.json()["access_token"]

    async def test_a_wrong_code_is_refused(self, app, mfa_user):
        await _enrol_and_confirm(mfa_user)
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as anon:
            response = await _login(anon, mfa_user["email"], "000000")
        assert response.status_code == 401


class TestAnUnconfirmedEnrolmentIsNotProtection:
    async def test_it_does_not_gate_login(self, app, mfa_user):
        """An account that believes it has MFA and does not is worse than one that knows it
        has none: the user relaxes about their password and the control is absent exactly
        where it is being counted. `confirmed_at` is that distinction."""
        enroll = await mfa_user["client"].post(f"{MFA}/enroll")
        assert enroll.status_code == 200
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as anon:
            response = await _login(anon, mfa_user["email"])
        assert response.status_code == 200, (
            "an unconfirmed enrolment blocked login — the user cannot get in and cannot "
            "finish enrolling, which is a lockout produced by a half-configured control"
        )

    async def test_status_distinguishes_the_two(self, mfa_user):
        before = (await mfa_user["client"].get(f"{MFA}/status")).json()
        assert before == {
            "enrolled": False, "confirmed": False, "recovery_codes_remaining": 0
        }
        await mfa_user["client"].post(f"{MFA}/enroll")
        mid = (await mfa_user["client"].get(f"{MFA}/status")).json()
        assert mid["enrolled"] is True and mid["confirmed"] is False


class TestACodeCannotBeReplayed:
    async def test_the_same_code_fails_the_second_time(self, app, mfa_user):
        """RFC 6238 s5.2. Without this a code captured in a proxy log or over a shoulder is
        good for the rest of its 30-second window, which is ample."""
        secret, _codes = await _enrol_and_confirm(mfa_user)
        from httpx import ASGITransport, AsyncClient

        code = totp._code_for_window(secret, totp.current_window() + 1)
        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as anon:
            first = await _login(anon, mfa_user["email"], code)
            second = await _login(anon, mfa_user["email"], code)
        assert first.status_code == 200, first.text[:200]
        assert second.status_code == 401, (
            "the same code was accepted twice inside its own window"
        )


class TestRecoveryCodes:
    async def test_one_works_once(self, app, mfa_user):
        _secret, codes = await _enrol_and_confirm(mfa_user)
        from httpx import ASGITransport, AsyncClient

        async with AsyncClient(
            transport=ASGITransport(app=app), base_url="http://test"
        ) as anon:
            first = await _login(anon, mfa_user["email"], codes[0])
            again = await _login(anon, mfa_user["email"], codes[0])
        assert first.status_code == 200, first.text[:200]
        assert again.status_code == 401, "a recovery code was reusable"

    async def test_they_are_not_recoverable_from_the_api(self, mfa_user):
        """Shown once. Stored as digests — if `/status` could return them they would be a
        static password the API hands out."""
        await _enrol_and_confirm(mfa_user)
        body = (await mfa_user["client"].get(f"{MFA}/status")).json()
        assert set(body) == {"enrolled", "confirmed", "recovery_codes_remaining"}
        assert body["recovery_codes_remaining"] == 10


class TestDisablingRequiresProof:
    async def test_a_session_alone_cannot_remove_the_factor(self, mfa_user):
        """Otherwise a stolen token removes MFA, and the factor is worth what the session
        is worth — which is what it was protecting against."""
        await _enrol_and_confirm(mfa_user)
        response = await mfa_user["client"].request(
            "DELETE", f"{MFA}/", json={"code": "000000"}
        )
        assert response.status_code == 400, response.text[:200]

    async def test_a_current_code_disables_it(self, mfa_user):
        secret, _codes = await _enrol_and_confirm(mfa_user)
        code = totp._code_for_window(secret, totp.current_window() + 1)
        response = await mfa_user["client"].request(
            "DELETE", f"{MFA}/", json={"code": code}
        )
        assert response.status_code == 204, response.text[:200]
        assert (await mfa_user["client"].get(f"{MFA}/status")).json()["enrolled"] is False
