"""Encrypt the store-and-forward buffer's payloads at rest (FS-749).

THE THREAT THIS ADDRESSES, stated precisely, because encryption-at-rest claims are usually
vaguer than they should be.

An edge gateway sits on a plant floor, in a vehicle, or at a remote site. The store-and-forward
buffer holds every reading the uplink has not yet accepted — by design, for up to 24 hours,
and in a genuine DDIL outage that is the entire operational picture of the site. It was
plaintext SQLite on local disk.

So the threat is **the device leaving with its disk**: theft, decommissioning without
sanitisation, a returned RMA unit, or a captured vehicle. Against that, this works — the
payload ciphertext is useless without the key, and the key does not live in the database.

It does NOT defend against an attacker with code execution on a running device. They can
read the key file exactly as the agent does. Claiming otherwise would be the kind of
overstatement that costs an assessor's trust in everything else; NIST SP 800-171 3.8.1 and
3.13.16 are about media, and media protection is what this is.

WHY APPLICATION-LAYER AND NOT SQLCIPHER. SQLCipher encrypts the whole file, which is
strictly better coverage — and it needs a compiled native extension on every edge platform
the agent ships to, including ARM gateways with no toolchain. `cryptography` is already a
dependency here (the mTLS enrollment chain uses it), so this adds nothing to the install and
cannot fail to build on a device in the field. The trade is visible: metadata columns
(`asset_id`, `timestamp_edge`, `topic`) stay in the clear. That is deliberate — the buffer
ORDERS and PRUNES by those columns, and encrypting them would mean decrypting every row to
sort it. The reading values are the sensitive part and those are inside the payload.

MIXED CONTENT IS THE NORMAL STATE, not an edge case. Every deployed device already has a
buffer full of plaintext rows, and they must keep draining after an upgrade. `decrypt`
therefore passes through anything that is not a recognised envelope, and `is_encrypted`
exists so the agent can report the mix rather than guess at it.
"""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Optional

import structlog
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

logger = structlog.get_logger()

#: Envelope prefix. Versioned so a future algorithm change is DETECTED rather than guessed
#: at — the same reason the ERP field encryption carries one.
ENVELOPE_PREFIX = "encv1:"

#: Where the key comes from, in priority order. A file is preferred over an environment
#: variable: env vars leak into process listings, crash dumps and `docker inspect`, and an
#: edge gateway is exactly the machine somebody debugs over a shoulder.
KEY_FILE_ENV = "BUFFER_ENCRYPTION_KEY_FILE"
KEY_ENV = "BUFFER_ENCRYPTION_KEY"

#: Fail-closed switch, matching the agent's existing `EDGE_REQUIRE_*` idiom. With this set
#: the agent refuses to start without a key rather than silently buffering CUI in the clear
#: — which is the failure this module exists to prevent, and it is silent by nature.
REQUIRE_ENV = "BUFFER_ENCRYPTION_REQUIRED"


class BufferEncryptionUnavailable(RuntimeError):
    """Encryption is required and no usable key was configured."""


def _load_key_material() -> Optional[bytes]:
    path = os.getenv(KEY_FILE_ENV)
    if path:
        try:
            material = open(path, "rb").read().strip()
        except OSError as exc:
            raise BufferEncryptionUnavailable(
                f"{KEY_FILE_ENV}={path} could not be read: {exc}"
            ) from exc
        if not material:
            raise BufferEncryptionUnavailable(f"{KEY_FILE_ENV}={path} is empty")
        return material

    inline = os.getenv(KEY_ENV)
    if inline:
        logger.warning(
            "buffer_key_from_environment",
            hint=f"prefer {KEY_FILE_ENV}; environment variables appear in process "
                 f"listings, crash dumps and container inspection output",
        )
        return inline.encode()
    return None


class BufferCipher:
    """AES-256-GCM over the payload column, keyed by HKDF from device key material.

    One instance per buffer. Constructing it with no key material configured yields a
    pass-through cipher — `enabled` is False, `encrypt` returns its input — so an existing
    deployment is unaffected until a key is provisioned. `BUFFER_ENCRYPTION_REQUIRED=true`
    turns that same absence into a refusal to start.
    """

    def __init__(self, key_material: Optional[bytes] = None, *, required: Optional[bool] = None):
        if required is None:
            required = os.getenv(REQUIRE_ENV, "false").lower() == "true"
        if key_material is None:
            key_material = _load_key_material()

        if key_material is None:
            if required:
                raise BufferEncryptionUnavailable(
                    f"{REQUIRE_ENV}=true but neither {KEY_FILE_ENV} nor {KEY_ENV} is set. "
                    f"Refusing to start rather than buffer telemetry in cleartext on local "
                    f"disk."
                )
            self._aead = None
            logger.warning(
                "buffer_encryption_disabled",
                hint=f"set {KEY_FILE_ENV} to encrypt buffered payloads at rest; required "
                     f"where the buffer may hold CUI",
            )
            return

        # HKDF, not a bare hash: `info` binds the key to this purpose so the same device
        # secret can key something else tomorrow without the two sharing a key.
        key = HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"opsgrid.edge.buffer.v1",
            info=b"store-and-forward-payload",
        ).derive(key_material)
        self._aead = AESGCM(key)
        # A short, non-reversible fingerprint so an operator can tell whether two devices
        # (or a device and its backup) share a key WITHOUT the key appearing in a log.
        self.key_fingerprint = hashlib.sha256(key).hexdigest()[:12]
        logger.info("buffer_encryption_enabled", key_fingerprint=self.key_fingerprint)

    @property
    def enabled(self) -> bool:
        return self._aead is not None

    @staticmethod
    def is_encrypted(value: str) -> bool:
        return isinstance(value, str) and value.startswith(ENVELOPE_PREFIX)

    def encrypt(self, plaintext: str) -> str:
        if self._aead is None or not plaintext:
            return plaintext
        nonce = os.urandom(12)
        ciphertext = self._aead.encrypt(nonce, plaintext.encode(), None)
        return (
            ENVELOPE_PREFIX
            + base64.urlsafe_b64encode(nonce).decode()
            + ":"
            + base64.urlsafe_b64encode(ciphertext).decode()
        )

    def decrypt(self, value: str) -> str:
        """Decrypt an envelope; pass anything else through unchanged.

        THE PASS-THROUGH IS THE MIGRATION. Every device already running has a buffer of
        plaintext rows, and they have to keep draining across the upgrade — refusing them
        would turn a security improvement into data loss, which is a bad trade for data
        that is already written.
        """
        if not self.is_encrypted(value):
            return value
        if self._aead is None:
            # Encrypted rows and no key: the key was lost or rotated without re-keying.
            # Loud, and NOT silently dropped — the operator needs to know the backlog is
            # unreadable rather than empty.
            logger.error(
                "buffer_payload_unreadable",
                reason="row is encrypted and no key is configured",
            )
            raise BufferEncryptionUnavailable(
                "buffered payload is encrypted and no key is configured"
            )
        try:
            _prefix, nonce_b64, ciphertext_b64 = value.split(":", 2)
            plaintext = self._aead.decrypt(
                base64.urlsafe_b64decode(nonce_b64),
                base64.urlsafe_b64decode(ciphertext_b64),
                None,
            )
            return plaintext.decode()
        except BufferEncryptionUnavailable:
            raise
        except Exception as exc:  # noqa: BLE001
            # GCM authenticates, so this fires on tampering as well as on a wrong key.
            logger.error("buffer_payload_decrypt_failed", error=str(exc))
            raise BufferEncryptionUnavailable(
                "buffered payload failed authenticated decryption"
            ) from exc
