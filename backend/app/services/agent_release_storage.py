"""Storage helpers for signed edge-agent OTA release artifacts."""

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


def resolve_bundle_path(
    organization_id: UUID,
    release_id: UUID,
    *,
    suffix: str = ".bundle",
) -> tuple[Path, str]:
    if suffix not in {".bundle", ".whl"}:
        raise AgentReleaseStorageError("Unsupported OTA artifact suffix")
    root = ota_storage_root()
    relative = Path(str(organization_id)) / f"{release_id}{suffix}"
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
    return store_release_artifact(
        organization_id,
        release_id,
        bundle,
        suffix=".bundle",
    )


def store_agent_wheel(
    organization_id: UUID,
    release_id: UUID,
    artifact: bytes,
) -> StoredBundle:
    if not artifact:
        raise AgentReleaseStorageError("Agent wheel cannot be empty")
    return store_release_artifact(
        organization_id,
        release_id,
        artifact,
        suffix=".whl",
    )


def store_release_artifact(
    organization_id: UUID,
    release_id: UUID,
    artifact: bytes,
    *,
    suffix: str,
) -> StoredBundle:
    output_path, storage_key = resolve_bundle_path(
        organization_id,
        release_id,
        suffix=suffix,
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    checksum = hashlib.sha256(artifact).hexdigest()
    signature = sign_bundle(artifact)

    fd, temp_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        with temp_path.open("wb") as handle:
            handle.write(artifact)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_path, output_path)
        _fsync_directory(output_path.parent)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

    signing_key_id = Path(settings.OTA_SIGNING_PRIVATE_KEY_PATH).stem or "default"
    return StoredBundle(
        storage_key=storage_key,
        checksum_sha256=checksum,
        signature_ed25519=signature,
        signing_key_id=signing_key_id,
        size_bytes=len(artifact),
    )


def delete_release_artifact(storage_key: str) -> None:
    """Best-effort cleanup for an artifact whose metadata transaction failed."""
    path = absolute_bundle_path(storage_key)
    path.unlink(missing_ok=True)
    _fsync_directory(path.parent)


def _fsync_directory(path: Path) -> None:
    try:
        descriptor = os.open(path, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(descriptor)
    finally:
        os.close(descriptor)


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
