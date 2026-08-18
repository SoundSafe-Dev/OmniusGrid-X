"""Password hashing, in one place, on a FIPS-approved KDF (FS-748).

WHY THIS MODULE EXISTS AT ALL. There were two `CryptContext` objects — one in
`app/api/auth.py`, one in `app/core/sso.py` — configured identically and independently. That
is not a style problem: a migration has to change every context, and a second one nobody
remembers is a second algorithm still in service. This is the same defect shape as the audit
hash chain (FS-743), where two implementations of one digest drifted until neither could
verify the other.

THE FIPS POSITION, measured rather than assumed. **bcrypt is not a FIPS-approved
algorithm.** SP 800-132 approves PBKDF2 for password storage, and FIPS 140-3 validated
modules do not provide bcrypt, so in an enforcing environment `bcrypt.verify` may be
*unavailable* rather than merely discouraged. For CMMC 3.13.11 (FIPS-validated cryptography
protecting CUI) this is the single most-used primitive in the application and it does not
qualify.

What is NOT changing, because measurement said so: Ed25519 OTA signing, EC P-256 X.509 in
the edge CA, HS256 JWTs (HMAC-SHA-256 is approved — the JWT work is key rotation, a separate
concern), and unsalted SHA-256 digests of high-entropy random tokens. SP 800-132 governs
passwords; a 256-bit random session token is not one, and adding a KDF there would cost
latency for no security.

THE MIGRATION IS DUAL-READ, and it has a deadline for a reason. `verify_and_update` accepts
an existing bcrypt hash, checks it, and returns a PBKDF2 replacement to store — so users
migrate silently as they log in and no password reset is needed. Existing bcrypt hashes are
NOT convertible without the plaintext, so they age out rather than being rewritten in bulk.

**The window must close before the FIPS base image lands.** In enforcing mode the legacy
verify path may raise rather than return False, which would lock out every user who had not
logged in since the cutover — a worse outage than the forced reset it was avoiding.
`auth_password_hash_scheme_total` makes "how many are still on bcrypt" a dashboard number so
that decision is made on data.

600,000 iterations follows OWASP's current PBKDF2-HMAC-SHA256 guidance. It is deliberately
expensive; `AUTH_LOGIN_RATE_LIMIT` and the account-lockout work are what stop that expense
becoming a denial-of-service vector.
"""

from __future__ import annotations

import structlog
from passlib.context import CryptContext

logger = structlog.get_logger()

#: PBKDF2-HMAC-SHA256 is the only SP 800-132-approved password KDF available here.
#: `bcrypt` stays as a DEPRECATED scheme so existing hashes still verify during the
#: migration window — remove it, and every user who has not logged in since the cutover is
#: locked out.
PREFERRED_SCHEME = "pbkdf2_sha256"
LEGACY_SCHEMES = ("bcrypt",)
PBKDF2_ROUNDS = 600_000

pwd_context = CryptContext(
    schemes=[PREFERRED_SCHEME, *LEGACY_SCHEMES],
    deprecated=list(LEGACY_SCHEMES),
    pbkdf2_sha256__rounds=PBKDF2_ROUNDS,
)


def hash_password(password: str) -> str:
    """Hash with the preferred scheme. New passwords are never bcrypt."""
    return pwd_context.hash(password)


def identify_scheme(hashed_password: str) -> str:
    """Which scheme a stored hash uses, for reporting migration progress."""
    try:
        return pwd_context.identify(hashed_password) or "unknown"
    except ValueError:
        return "unknown"


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify only. Prefer `verify_and_migrate` on any path that can persist."""
    if not hashed_password:
        # An SSO user whose local login was disabled by storing an empty hash, or a
        # deactivated account. `passlib` raises on an empty hash rather than returning
        # False, and a 500 on the login path is both an outage and an oracle.
        return False
    try:
        return pwd_context.verify(plain_password, hashed_password)
    except ValueError:
        # An unrecognised or corrupt hash is a failed login, not a crash. Reached in
        # practice by rows written before this module existed.
        return False


def verify_password_and_migrate(
    plain_password: str, hashed_password: str
) -> tuple[bool, str | None]:
    """Verify, and return a replacement hash when the stored one is on a legacy scheme.

    Returns `(ok, new_hash_or_None)`. The caller persists `new_hash` if it is not None —
    that is the whole migration: users move to PBKDF2 as they log in, with no reset and no
    bulk rewrite, because a bcrypt hash cannot be converted without the plaintext and the
    plaintext exists only here, for this instant.
    """
    if not hashed_password:
        return False, None
    try:
        ok, new_hash = pwd_context.verify_and_update(plain_password, hashed_password)
    except ValueError:
        return False, None
    if ok and new_hash:
        logger.info(
            "password_hash_migrated",
            from_scheme=identify_scheme(hashed_password),
            to_scheme=PREFERRED_SCHEME,
        )
    return bool(ok), new_hash


def disabled_login_hash() -> str:
    """A hash no password can satisfy, for accounts that must not log in locally.

    SSO users get one of these: `hash_password` over a random secret that is discarded
    immediately, so `verify_password` cannot succeed for any input. Kept here rather than in
    `sso.py` so it uses the same context as everything else — the previous version built its
    own `CryptContext`, which is exactly the second-implementation problem this module
    exists to remove.
    """
    import secrets

    return hash_password(secrets.token_urlsafe(32))
