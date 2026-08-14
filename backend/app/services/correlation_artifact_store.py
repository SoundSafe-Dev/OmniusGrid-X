"""Durable raw-artifact handling for the evidence correlation pipeline.

The original Intake Inbox stored every raw upload as base64 in Postgres.  That
is useful for a developer laptop but becomes expensive and memory-heavy for
real operational files.  This module makes object storage the normal path
while retaining a small, explicit compatibility fallback for existing local
deployments without SeaweedFS/S3.

Only opaque object references belong in relational metadata.  Callers should
never expose the returned object key directly to an untrusted client.
"""

from __future__ import annotations

import base64
import mimetypes
import re
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from app.core.config import settings
from app.services.document_store import get_document_store

logger = structlog.get_logger()


def _safe_filename(filename: Optional[str]) -> str:
    """Return a stable, path-safe filename for an object key."""
    raw = Path(filename or "upload").name
    safe = re.sub(r"[^A-Za-z0-9._-]+", "-", raw).strip(".-")
    return safe[:180] or "upload"


def _content_type(filename: Optional[str], supplied: Optional[str] = None) -> str:
    if supplied and "/" in supplied:
        return supplied.split(";", 1)[0].strip()
    return mimetypes.guess_type(filename or "")[0] or "application/octet-stream"


@dataclass(frozen=True)
class CorrelationArtifactReference:
    """Serializable pointer to raw correlation input bytes."""

    storage: str
    key: Optional[str]
    size_bytes: int
    filename: str
    content_type: str
    inline_base64: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "storage": self.storage,
            "key": self.key,
            "size_bytes": self.size_bytes,
            "filename": self.filename,
            "content_type": self.content_type,
        }
        if self.inline_base64 is not None:
            payload["inline_base64"] = self.inline_base64
        return payload


def build_correlation_object_key(
    organization_id: Any,
    artifact_id: Any,
    filename: Optional[str],
) -> str:
    """Build a tenant-isolated, collision-resistant raw-artifact key."""
    org = str(organization_id or "unassigned")
    artifact = str(artifact_id or uuid.uuid4())
    return f"correlation/{org}/{artifact}/{_safe_filename(filename)}"


async def store_correlation_artifact(
    content: bytes,
    *,
    organization_id: Any,
    artifact_id: Any = None,
    filename: Optional[str] = None,
    content_type: Optional[str] = None,
) -> CorrelationArtifactReference:
    """Persist raw input in object storage, with a dev-only inline fallback.

    In production, an unavailable configured object store is a hard failure:
    silently pushing 50 MB uploads into Postgres would defeat the scale and
    durability guarantees of the evidence pipeline.
    """
    resolved_name = _safe_filename(filename)
    resolved_type = _content_type(resolved_name, content_type)
    store = get_document_store()

    if settings.CORRELATION_USE_OBJECT_STORAGE and store.available:
        key = build_correlation_object_key(organization_id, artifact_id, resolved_name)
        try:
            await store.ensure_bucket(store.raw_bucket)
            await store.put_document(
                key,
                content,
                content_type=resolved_type,
                metadata={"purpose": "correlation-evidence"},
            )
            return CorrelationArtifactReference(
                storage="object",
                key=key,
                size_bytes=len(content),
                filename=resolved_name,
                content_type=resolved_type,
            )
        except Exception as exc:
            logger.error("correlation_artifact_store_failed", error=str(exc), key=key)
            if settings.ENVIRONMENT.lower() == "production":
                raise RuntimeError("Correlation object storage is unavailable") from exc

    # The fallback is intentionally visible in metadata so operators can find
    # and migrate legacy inline blobs before deploying multi-worker ingestion.
    return CorrelationArtifactReference(
        storage="inline_base64",
        key=None,
        size_bytes=len(content),
        filename=resolved_name,
        content_type=resolved_type,
        inline_base64=base64.b64encode(content).decode("ascii"),
    )


async def load_correlation_artifact(
    reference: Optional[Dict[str, Any]],
    *,
    legacy_inline_base64: Optional[str] = None,
) -> bytes:
    """Load raw bytes from a correlation artifact reference or legacy field."""
    ref = reference or {}
    storage = ref.get("storage")
    if storage == "object":
        key = ref.get("key")
        if not key:
            raise ValueError("Correlation artifact reference is missing an object key")
        return await get_document_store().get_document(str(key))

    encoded = ref.get("inline_base64") if storage == "inline_base64" else None
    encoded = encoded or legacy_inline_base64
    if not encoded:
        raise ValueError("Correlation source no longer has raw content")
    try:
        return base64.b64decode(encoded, validate=True)
    except Exception as exc:
        raise ValueError("Correlation source has invalid stored content") from exc

