"""Passwords are hashed with a FIPS-approved KDF, and legacy hashes still verify (FS-748).

bcrypt is not FIPS-approved. SP 800-132 approves PBKDF2 for password storage, and a
validated module does not provide bcrypt at all — so in an enforcing runtime the bcrypt path
may RAISE rather than return False. For CMMC 3.13.11 this was the most-used primitive in the
application and it did not qualify.

THE MIGRATION IS THE RISKY PART, NOT THE ALGORITHM. Switching the preferred scheme is one
line. Doing it without locking anybody out means every existing bcrypt hash must keep
verifying until its owner next logs in, at which point it is silently replaced. Both halves
are asserted here, and the second one is the half that would fail quietly: if
rehash-on-login stopped working, everything would keep passing — users would simply stay on
bcrypt forever, and the migration would be discovered incomplete on the day the base image
made bcrypt unreadable.

WHAT THIS PINS
  1. a new password is PBKDF2, never bcrypt;
  2. an existing bcrypt hash still verifies (nobody is locked out mid-migration);
  3. verifying a legacy hash RETURNS a replacement, so the caller can persist it;
  4. a correct password on an already-migrated hash returns no replacement — otherwise
     every login would write, which is a needless write and a timing signal;
  5. a wrong password never yields a replacement, which would be a rehash oracle;
  6. there is exactly ONE password context in the codebase.
"""

from __future__ import annotations

import pathlib

import pytest

from app.core.password import (
    LEGACY_SCHEMES,
    PBKDF2_ROUNDS,
    PREFERRED_SCHEME,
    hash_password,
    identify_scheme,
    verify_password,
    verify_password_and_migrate,
)

BACKEND = pathlib.Path(__file__).resolve().parents[1]
PASSWORD = "correct horse battery staple"


def _legacy_bcrypt_hash(plain: str) -> str:
    from passlib.hash import bcrypt

    # Cost 4: the lowest bcrypt permits. This is a fixture, not a credential — 12 rounds
    # here would add seconds to the suite for no assertion strength.
    return bcrypt.using(rounds=4).hash(plain)


class TestNewPasswordsUseTheApprovedKdf:
    def test_the_preferred_scheme_is_pbkdf2(self):
        assert PREFERRED_SCHEME == "pbkdf2_sha256", (
            f"the preferred scheme is {PREFERRED_SCHEME!r}. SP 800-132 approves PBKDF2; "
            f"bcrypt and argon2 are not available from a FIPS-validated module."
        )

    def test_a_new_hash_is_pbkdf2(self):
        assert identify_scheme(hash_password(PASSWORD)) == "pbkdf2_sha256"

    def test_the_iteration_count_is_current(self):
        assert PBKDF2_ROUNDS >= 600_000, (
            f"PBKDF2 rounds are {PBKDF2_ROUNDS:,}; OWASP's current guidance for "
            f"PBKDF2-HMAC-SHA256 is 600,000. Lowering this is a decision that needs a "
            f"reason written next to it."
        )

    def test_a_new_hash_verifies(self):
        assert verify_password(PASSWORD, hash_password(PASSWORD)) is True
        assert verify_password("wrong", hash_password(PASSWORD)) is False


class TestTheMigrationDoesNotLockAnybodyOut:
    """The half that fails silently: if these break, nothing errors — users just never
    migrate, and it surfaces when a FIPS runtime makes bcrypt unreadable."""

    def test_bcrypt_is_still_a_registered_scheme(self):
        assert "bcrypt" in LEGACY_SCHEMES, (
            "bcrypt was removed from the scheme list. Every user who has not logged in "
            "since the cutover is now locked out — their stored hash cannot be read at all."
        )

    def test_a_legacy_hash_still_verifies(self):
        legacy = _legacy_bcrypt_hash(PASSWORD)
        assert identify_scheme(legacy) == "bcrypt"
        assert verify_password(PASSWORD, legacy) is True

    def test_verifying_a_legacy_hash_returns_a_replacement(self):
        legacy = _legacy_bcrypt_hash(PASSWORD)
        ok, replacement = verify_password_and_migrate(PASSWORD, legacy)
        assert ok is True
        assert replacement, (
            "a correct password against a bcrypt hash produced no replacement, so the "
            "caller has nothing to persist and the user stays on bcrypt forever"
        )
        assert identify_scheme(replacement) == "pbkdf2_sha256"
        assert verify_password(PASSWORD, replacement) is True

    def test_an_already_migrated_hash_needs_no_replacement(self):
        """Otherwise every single login writes to the users table."""
        current = hash_password(PASSWORD)
        ok, replacement = verify_password_and_migrate(PASSWORD, current)
        assert ok is True
        assert replacement is None

    def test_a_wrong_password_never_yields_a_replacement(self):
        """A rehash returned on a failed verify would be an oracle, and would let an
        attacker overwrite a victim's stored hash."""
        legacy = _legacy_bcrypt_hash(PASSWORD)
        ok, replacement = verify_password_and_migrate("not the password", legacy)
        assert ok is False
        assert replacement is None


class TestTheEdgesDoNotCrash:
    """`passlib` raises on an empty or malformed hash. On the login path that is a 500 —
    an outage, and an oracle distinguishing 'no such user' from 'malformed hash'."""

    @pytest.mark.parametrize("stored", ["", "not-a-hash", "$2b$12$" + "x" * 53])
    def test_an_unusable_stored_hash_is_a_failed_login(self, stored: str):
        assert verify_password(PASSWORD, stored) is False
        assert verify_password_and_migrate(PASSWORD, stored) == (False, None)


class TestThereIsOnlyOnePasswordContext:
    def test_no_second_cryptcontext_exists(self):
        """There were two — `app/api/auth.py` and `app/core/sso.py` — configured identically
        and independently, which is how a migration leaves an unapproved scheme in service
        on the path nobody remembered."""
        offenders = []
        for path in (BACKEND / "app").rglob("*.py"):
            if path.name == "password.py":
                continue
            if "CryptContext(" in path.read_text():
                offenders.append(str(path.relative_to(BACKEND)))
        assert not offenders, (
            f"{offenders} build their own CryptContext. All password hashing must go "
            f"through app/core/password.py, or the next algorithm change will miss one."
        )
