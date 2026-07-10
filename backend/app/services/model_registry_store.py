"""Storage helpers for cloud-trained model artifacts (TorchScript ``.pt``).

Mirrors ``services/agent_release_storage.py``: an atomic write under a
per-tenant path, a SHA-256 checksum, and an HMAC-signed, time-limited download
URL. Unlike OTA config bundles, model artifacts are integrity-checked by
checksum only — the edge MLOps client (``services/mlops_pipeline.py``)
validates ``sha256_hash`` on download. Ed25519 signing belongs to the model-OTA
delivery task, not the registry.
"""

from __future__ import annotations

import hashlib
import os
import re
import tempfile
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from uuid import UUID

from app.core.config import settings
from app.utils.signed_urls import build_model_artifact_signed_download_url


class ModelArtifactStorageError(ValueError):
    """Invalid or unsafe model artifact storage operation."""


# Model ``name``/``version`` become path components, so constrain them to a
# safe charset (no separators, no dot-segments) in addition to the
# escape-the-root check below.
_SAFE_COMPONENT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


@dataclass(frozen=True)
class StoredModelArtifact:
    storage_key: str
    checksum_sha256: str
    size_bytes: int


def model_storage_root() -> Path:
    return Path(settings.MODEL_STORAGE_PATH).resolve()


def _safe_component(value: str, label: str) -> str:
    if not value or ".." in value or not _SAFE_COMPONENT.match(value):
        raise ModelArtifactStorageError(f"Unsafe model {label}: {value!r}")
    return value


def resolve_artifact_path(
    organization_id: UUID, name: str, version: str
) -> tuple[Path, str]:
    safe_name = _safe_component(name, "name")
    safe_version = _safe_component(version, "version")
    root = model_storage_root()
    relative = Path(str(organization_id)) / safe_name / f"{safe_version}.pt"
    absolute = (root / relative).resolve()
    if not absolute.is_relative_to(root):
        raise ModelArtifactStorageError("Resolved model path escapes storage root")
    return absolute, str(relative)


def absolute_artifact_path(storage_key: str) -> Path:
    root = model_storage_root()
    absolute = (root / storage_key).resolve()
    if not absolute.is_relative_to(root):
        raise ModelArtifactStorageError("Model path escapes storage root")
    return absolute


def store_model_artifact(
    organization_id: UUID,
    name: str,
    version: str,
    artifact: bytes,
) -> StoredModelArtifact:
    if not artifact:
        raise ModelArtifactStorageError("Model artifact cannot be empty")

    output_path, storage_key = resolve_artifact_path(organization_id, name, version)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    checksum = hashlib.sha256(artifact).hexdigest()

    fd, temp_name = tempfile.mkstemp(
        dir=output_path.parent,
        prefix=f".{output_path.name}.",
        suffix=".tmp",
    )
    os.close(fd)
    temp_path = Path(temp_name)
    try:
        temp_path.write_bytes(artifact)
        os.replace(temp_path, output_path)
    finally:
        if temp_path.exists():
            temp_path.unlink(missing_ok=True)

    return StoredModelArtifact(
        storage_key=storage_key,
        checksum_sha256=checksum,
        size_bytes=len(artifact),
    )


def load_model_artifact(storage_key: str) -> bytes:
    return absolute_artifact_path(storage_key).read_bytes()


def artifact_exists(storage_key: str) -> bool:
    return absolute_artifact_path(storage_key).is_file()


def issue_model_artifact_url(
    model_id: UUID,
    organization_id: UUID,
    *,
    expires_at: datetime | None = None,
) -> tuple[str, datetime]:
    if expires_at is None:
        expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=settings.EXPORT_LINK_EXPIRE_MINUTES
        )
    return build_model_artifact_signed_download_url(
        model_id,
        organization_id,
        expires_at,
    )
