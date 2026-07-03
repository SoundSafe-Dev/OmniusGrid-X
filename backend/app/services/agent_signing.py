"""Ed25519 signing helpers for OTA config bundles."""

from __future__ import annotations

import base64
from pathlib import Path

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import (
    Ed25519PrivateKey,
    Ed25519PublicKey,
)

from app.core.config import settings


class AgentSigningError(ValueError):
    """Release-signing configuration or verification failure."""


def _load_private_key_from_path(path: str) -> Ed25519PrivateKey:
    if not path:
        raise AgentSigningError("OTA_SIGNING_PRIVATE_KEY_PATH is required")
    data = Path(path).read_bytes()
    key = serialization.load_pem_private_key(data, password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise AgentSigningError("OTA signing private key must be Ed25519")
    return key


def _load_public_key(value: str) -> Ed25519PublicKey:
    if not value:
        raise AgentSigningError("OTA_SIGNING_PUBLIC_KEY is required")
    raw = value.encode("utf-8")
    if b"BEGIN PUBLIC KEY" in raw:
        key = serialization.load_pem_public_key(raw)
    else:
        key = Ed25519PublicKey.from_public_bytes(base64.b64decode(value))
    if not isinstance(key, Ed25519PublicKey):
        raise AgentSigningError("OTA signing public key must be Ed25519")
    return key


def public_key_to_base64(public_key: Ed25519PublicKey) -> str:
    raw = public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return base64.b64encode(raw).decode("ascii")


def sign_bundle(bundle: bytes, private_key_path: str | None = None) -> str:
    private_key = _load_private_key_from_path(
        private_key_path
        if private_key_path is not None
        else settings.OTA_SIGNING_PRIVATE_KEY_PATH
    )
    signature = private_key.sign(bundle)
    return base64.b64encode(signature).decode("ascii")


def verify_bundle_signature(
    bundle: bytes,
    signature_ed25519: str,
    public_key: str | None = None,
) -> bool:
    key = _load_public_key(
        public_key if public_key is not None else settings.OTA_SIGNING_PUBLIC_KEY
    )
    try:
        key.verify(base64.b64decode(signature_ed25519), bundle)
        return True
    except (InvalidSignature, ValueError):
        return False
