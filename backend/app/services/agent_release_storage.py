"""Storage helpers for signed edge-agent OTA config bundles."""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from app.core.config import settings
from app.services.agent_signing import sign_bundle
from app.utils.signed_urls import build_agent_release_signed_download_url


class AgentReleaseStorageError(ValueError):
    """Invalid or unsafe OTA release storage operation."""


@dataclass(frozen=True)
class StoredBundle:
    storage_key: str
    checksum_sha256: str
    signature_ed25519: str
    signing_key_id: str
    size_bytes: int


def ota_storage_root() -> Path:
    return Path(settings.OTA_STORAGE_PATH).resolve()


def resolve_bundle_path(organization_id: UUID, release_id: UUID) -> tuple[Path, str]:
    root = ota_storage_root()
    relative = Path(str(organization_id)) / f"{release_id}.bundle"
    absolute = (root / relative).resolve()
    if not absolute.is_relative_to(root):
        raise AgentReleaseStorageError("Resolved OTA bundle path escapes storage root")
    return absolute, str(relative)


def absolute_bundle_path(storage_key: str) -> Path:
    root = ota_storage_root()
    absolute = (root / storage_key).resolve()
    if not absolute.is_relative_to(root):
        raise AgentReleaseStorageError("OTA bundle path escapes storage root")
    return absolute


def store_config_bundle(
    organization_id: UUID,
    release_id: UUID,
    bundle: bytes,
) -> StoredBundle:
    if not bundle:
        raise AgentReleaseStorageError("Config bundle cannot be empty")

    output_path, storage_key = resolve_bundle_path(organization_id, release_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    checksum = hashlib.sha256(bundle).hexdigest()
    signature = sign_bundle(bundle)

    fd, temp_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_bytes(bundle)
        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

    signing_key_id = Path(settings.OTA_SIGNING_PRIVATE_KEY_PATH).stem or "default"
    return StoredBundle(
        storage_key=storage_key,
        checksum_sha256=checksum,
        signature_ed25519=signature,
        signing_key_id=signing_key_id,
        size_bytes=len(bundle),
    )


def issue_release_bundle_url(
    release_id: UUID,
    organization_id: UUID,
    *,
    expires_at: datetime | None = None,
) -> tuple[str, datetime]:
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.EXPORT_LINK_EXPIRE_MINUTES
        )
    return build_agent_release_signed_download_url(
        release_id,
        organization_id,
        expires_at,
    )
