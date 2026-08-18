"""TOTP second factor for local accounts (FS-750).

NIST SP 800-171 **3.5.3** requires multifactor authentication for local and network access to
privileged accounts, and for network access to non-privileged ones. It is a named CMMC Level
2 practice with no partial credit, and it was the largest single gap in the control
catalogue. What existed before was `enable_mfa`/`disable_mfa` in `keycloak_service.py` — on
this repository's own orphaned-definition list, so present, untested and called by nothing —
and which would only ever have served deployments running Keycloak, disabled by default.

RFC 6238 IMPLEMENTED HERE RATHER THAN ADDED AS A DEPENDENCY. TOTP is HMAC over a counter and
a truncation; it is about twenty lines, and `hmac`/`hashlib` are stdlib. Taking `pyotp` for
that would add a dependency to the authentication path — the one place where a supply-chain
compromise is worth the most — for code we can read in full. That reasoning is the same one
this repository applied when it dropped `python-jose` for `PyJWT`.

THE FIPS POSITION ON SHA-1, because it looks like a contradiction and is not.

RFC 6238's default is HMAC-SHA-1, and every authenticator app supports it; SHA-256 TOTP is
permitted by the RFC and unevenly supported in practice, so choosing it trades a real
usability failure for an apparent compliance win. **HMAC-SHA-1 remains approved.** NIST SP
800-131A retires SHA-1 for digital signatures, where collision resistance is the property
that matters; HMAC's security rests on the key and on PRF behaviour, not on collision
resistance, and HMAC-SHA-1 is explicitly still acceptable. `test_no_unapproved_primitive_is_reachable`
carries an exemption for this module naming that reasoning, so the decision is visible rather
than a silent hole in the sweep.

WHAT IS DELIBERATELY STORED, AND HOW:

  * the secret is an **AES-256-GCM envelope**, never plaintext. A database backup or a
    read-only leak would otherwise hand over the second factor, and a second factor an
    attacker can read is theatre;
  * recovery codes are **SHA-256 digests** of 160-bit random values — unsalted, which is
    correct for the same reason it is for session tokens: these are not passwords;
  * `last_used_window` is persisted so a code cannot be replayed inside its own validity
    window. RFC 6238 §5.2 requires this and it is the step most implementations skip —
    without it, a code shoulder-surfed or captured in a proxy log is good for another 30
    seconds, which is exactly long enough.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import os
import secrets
import struct
import time
from typing import Iterable, List, Optional, Tuple

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from app.core.config import settings

#: RFC 6238 defaults. 30-second steps, 6 digits.
TIME_STEP_SECONDS = 30
DIGITS = 6

#: How many steps either side of now are accepted. One step (±30s) absorbs ordinary clock
#: drift between a phone and a server. Wider is a bigger replay surface for no real gain —
#: a device more than a minute out has a clock problem worth fixing, not working around.
ALLOWED_DRIFT_STEPS = 1

#: Recovery codes: count, and entropy per code.
RECOVERY_CODE_COUNT = 10
RECOVERY_CODE_BYTES = 20  # 160 bits

ENVELOPE_PREFIX = "mfav1:"


def _secret_key() -> bytes:
    """The key wrapping every TOTP secret, derived from the application master key.

    Deliberately the same master as ERP field encryption rather than a new setting: another
    secret to provision is another secret to lose, and losing this one means every enrolled
    user must re-enrol. `info` separates the two derived keys so they are not the same key
    doing two jobs.
    """
    master = settings.ERP_ENCRYPTION_KEY or settings.JWT_SECRET_KEY
    return HKDF(
        algorithm=hashes.SHA256(),
        length=32,
        salt=b"omniusgrid.mfa.totp-secret.v1",
        info=b"totp-secret-wrapping",
    ).derive(master.encode())


def generate_secret() -> str:
    """A fresh base32 TOTP secret, in the form authenticator apps expect."""
    return base64.b32encode(os.urandom(20)).decode().rstrip("=")


def encrypt_secret(secret: str) -> str:
    nonce = os.urandom(12)
    ciphertext = AESGCM(_secret_key()).encrypt(nonce, secret.encode(), None)
    return (
        ENVELOPE_PREFIX
        + base64.urlsafe_b64encode(nonce).decode()
        + ":"
        + base64.urlsafe_b64encode(ciphertext).decode()
    )


def decrypt_secret(envelope: str) -> str:
    if not envelope.startswith(ENVELOPE_PREFIX):
        raise ValueError("not an MFA secret envelope")
    _prefix, nonce_b64, ciphertext_b64 = envelope.split(":", 2)
    return AESGCM(_secret_key()).decrypt(
        base64.urlsafe_b64decode(nonce_b64),
        base64.urlsafe_b64decode(ciphertext_b64),
        None,
    ).decode()


def _code_for_window(secret: str, window: int) -> str:
    """RFC 6238 / RFC 4226: HMAC over the counter, dynamic truncation, modulo 10^digits."""
    key = base64.b32decode(secret + "=" * (-len(secret) % 8))
    digest = hmac.new(key, struct.pack(">Q", window), hashlib.sha1).digest()
    offset = digest[-1] & 0x0F
    truncated = struct.unpack(">I", digest[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(truncated % (10 ** DIGITS)).zfill(DIGITS)


def current_window(at: Optional[float] = None) -> int:
    return int((at if at is not None else time.time()) // TIME_STEP_SECONDS)


def verify_code(
    secret: str,
    code: str,
    *,
    last_used_window: Optional[int] = None,
    at: Optional[float] = None,
) -> Tuple[bool, Optional[int]]:
    """Verify a code, returning `(ok, window_used)`.

    The caller MUST persist `window_used` as `last_used_window`. That is what makes a code
    single-use: without it a code captured in a proxy log, over a shoulder, or in a phishing
    relay stays valid for the rest of its 30-second window — which is ample.
    """
    if not code or not code.strip().isdigit():
        return False, None
    code = code.strip()
    now = current_window(at)
    for offset in range(-ALLOWED_DRIFT_STEPS, ALLOWED_DRIFT_STEPS + 1):
        window = now + offset
        if last_used_window is not None and window <= last_used_window:
            # Already spent. Checked BEFORE comparing, so a replayed code is refused
            # without the comparison telling a timing story about whether it was right.
            continue
        if hmac.compare_digest(_code_for_window(secret, window), code):
            return True, window
    return False, None


def provisioning_uri(secret: str, account: str, issuer: str = "OmniusGrid") -> str:
    """The `otpauth://` URI an authenticator app scans."""
    from urllib.parse import quote

    return (
        f"otpauth://totp/{quote(issuer)}:{quote(account)}"
        f"?secret={secret}&issuer={quote(issuer)}&algorithm=SHA1"
        f"&digits={DIGITS}&period={TIME_STEP_SECONDS}"
    )


def generate_recovery_codes(count: int = RECOVERY_CODE_COUNT) -> List[str]:
    """Plaintext recovery codes — shown ONCE, never stored in this form."""
    return [secrets.token_hex(RECOVERY_CODE_BYTES // 2) for _ in range(count)]


def hash_recovery_code(code: str) -> str:
    return hashlib.sha256(code.strip().lower().encode()).hexdigest()


def consume_recovery_code(code: str, hashes_: Iterable[str]) -> Tuple[bool, List[str]]:
    """Check a recovery code and return the REMAINING hashes.

    Single use: the matched hash is removed. A recovery code that survives its own use is a
    static password with extra steps.
    """
    remaining = list(hashes_)
    candidate = hash_recovery_code(code)
    for stored in remaining:
        if hmac.compare_digest(stored, candidate):
            remaining.remove(stored)
            return True, remaining
    return False, remaining
