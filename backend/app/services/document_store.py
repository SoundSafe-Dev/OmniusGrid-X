"""
Document Store Service

Async wrapper around the SeaweedFS S3 gateway (S3-compatible object storage).
This is the blob layer for the RAG pipeline: raw source documents (PDF/DOCX/
images) and optionally cached extracted text live here. The returned object key
is the single thread that links a stored document to its metadata row in
Postgres and its vector payload in Qdrant.

Design notes:
- Uses ``aioboto3`` to stay consistent with the rest of the async backend.
- Forces **path-style addressing** - SeaweedFS (and MinIO) do not support the
  virtual-host bucket addressing that boto3 defaults to.
- Graceful degradation: if ``aioboto3`` is not installed the service imports
  cleanly and raises a clear error only when actually used, so the rest of the
  app keeps working (same pattern as the Keycloak/vision services).
- Endpoint and credentials come from ``settings`` so the exact same code runs
  against SeaweedFS, MinIO, or real AWS S3 by changing env vars only.
"""

import re
from typing import Optional, List, Dict, Any
from functools import lru_cache

import structlog

from app.core.config import settings

try:
    import aioboto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:  # aioboto3 not installed - service disabled until used
    aioboto3 = None
    Config = None
    ClientError = Exception

logger = structlog.get_logger()


_DOC_ID_RE = re.compile(r"^(?!\.+\Z)[A-Za-z0-9._-]{1,128}\Z")


class InvalidDocumentId(ValueError):
    """A caller-supplied doc_id that cannot safely be used in an object key."""


def validate_doc_id(doc_id: str) -> str:
    """Reject a doc_id that would escape the tenant prefix or break the key.

    Object keys are ``{org_id}/{doc_id}/{filename}``. Because ``doc_id`` comes
    straight from the client, an unvalidated ``../other-org`` would write
    outside the caller's own prefix, and any ``/`` silently breaks the
    three-segment layout that key parsers rely on.
    """
    if not isinstance(doc_id, str) or not _DOC_ID_RE.match(doc_id):
        raise InvalidDocumentId(
            "doc_id must be 1-128 characters of letters, digits, "
            "'.', '_' or '-'."
        )
    return doc_id


def build_document_key(org_id: str, doc_id: str, filename: str) -> str:
    """Build a stable object key for a source document.

    Structure: ``{org_id}/{doc_id}/{filename}``. The ``doc_id`` keeps keys
    unique and stable even when two uploads share a filename. ``doc_id`` is
    validated first — see ``validate_doc_id``.
    """
    validate_doc_id(doc_id)
    return f"{org_id}/{doc_id}/{filename}"


class DocumentStore:
    """Async S3 client for the document blob store (SeaweedFS gateway)."""

    def __init__(self) -> None:
        self.endpoint_url: str = settings.S3_ENDPOINT_URL
        self.access_key: str = settings.S3_ACCESS_KEY
        self.secret_key: str = settings.S3_SECRET_KEY
        self.region: str = settings.S3_REGION
        self.raw_bucket: str = settings.S3_RAW_BUCKET
        self.text_bucket: str = settings.S3_TEXT_BUCKET
        self._session = aioboto3.Session() if aioboto3 is not None else None

    @property
    def available(self) -> bool:
        """True if the S3 client dependency is installed."""
        return self._session is not None

    def _require_client(self):
        if self._session is None:
            raise RuntimeError(
                "aioboto3 is not installed - cannot reach the document store. "
                "Add 'aioboto3' to requirements and reinstall."
            )
        # Path-style addressing is mandatory for SeaweedFS/MinIO.
        config = Config(
            s3={"addressing_style": "path"},
            signature_version="s3v4",
            retries={"max_attempts": 3, "mode": "standard"},
        )
        return self._session.client(
            "s3",
            endpoint_url=self.endpoint_url,
            aws_access_key_id=self.access_key,
            aws_secret_access_key=self.secret_key,
            region_name=self.region,
            config=config,
        )

    async def ensure_bucket(self, bucket: str) -> None:
        """Create the bucket if it does not already exist (idempotent)."""
        async with self._require_client() as s3:
            try:
                await s3.head_bucket(Bucket=bucket)
                return
            except ClientError as exc:
                code = exc.response.get("Error", {}).get("Code", "")
                if code not in ("404", "NoSuchBucket", "NotFound"):
                    raise
            await s3.create_bucket(Bucket=bucket)
            logger.info("document_store.bucket_created", bucket=bucket)

    async def put_document(
        self,
        key: str,
        data: bytes,
        content_type: str = "application/octet-stream",
        bucket: Optional[str] = None,
        metadata: Optional[Dict[str, str]] = None,
    ) -> str:
        """Store raw bytes and return the object key."""
        bucket = bucket or self.raw_bucket
        async with self._require_client() as s3:
            await s3.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata=metadata or {},
            )
        logger.info(
            "document_store.put",
            bucket=bucket,
            key=key,
            bytes=len(data),
            content_type=content_type,
        )
        return key

    async def get_document(self, key: str, bucket: Optional[str] = None) -> bytes:
        """Fetch and return the full object bytes."""
        bucket = bucket or self.raw_bucket
        async with self._require_client() as s3:
            resp = await s3.get_object(Bucket=bucket, Key=key)
            async with resp["Body"] as stream:
                return await stream.read()

    async def delete_document(self, key: str, bucket: Optional[str] = None) -> None:
        """Delete an object. No error if it is already gone."""
        bucket = bucket or self.raw_bucket
        async with self._require_client() as s3:
            await s3.delete_object(Bucket=bucket, Key=key)
        logger.info("document_store.delete", bucket=bucket, key=key)

    async def list_documents(
        self, prefix: str = "", bucket: Optional[str] = None
    ) -> List[str]:
        """List object keys under a prefix (handles pagination).

        Raises ``RuntimeError`` with a generic, client-safe message if the
        object store cannot be reached — the real exception (which may name
        internal hosts/ports) is logged server-side, not propagated.
        """
        bucket = bucket or self.raw_bucket
        keys: List[str] = []
        try:
            async with self._require_client() as s3:
                paginator = s3.get_paginator("list_objects_v2")
                async for page in paginator.paginate(Bucket=bucket, Prefix=prefix):
                    for obj in page.get("Contents", []):
                        keys.append(obj["Key"])
        except RuntimeError:
            raise  # aioboto3 not installed - already a clean, client-safe message
        except Exception as exc:
            logger.error(
                "document_store.list_failed", bucket=bucket, prefix=prefix, error=str(exc)
            )
            raise RuntimeError("Document store is currently unavailable.") from exc
        return keys

    async def generate_presigned_url(
        self,
        key: str,
        bucket: Optional[str] = None,
        expires_in: Optional[int] = None,
    ) -> str:
        """Presigned GET URL so a client can fetch a document directly."""
        bucket = bucket or self.raw_bucket
        expires_in = expires_in or settings.S3_PRESIGN_EXPIRE_SECONDS
        async with self._require_client() as s3:
            return await s3.generate_presigned_url(
                "get_object",
                Params={"Bucket": bucket, "Key": key},
                ExpiresIn=expires_in,
            )

    async def health_check(self) -> Dict[str, Any]:
        """Lightweight connectivity probe for a /health endpoint."""
        if not self.available:
            return {"available": False, "reason": "aioboto3 not installed"}
        try:
            async with self._require_client() as s3:
                await s3.list_buckets()
            return {"available": True, "endpoint": self.endpoint_url}
        except Exception as exc:  # surface as unhealthy, do not crash the probe
            logger.warning("document_store.health_check_failed", error=str(exc))
            return {"available": False, "reason": str(exc)}


@lru_cache()
def get_document_store() -> DocumentStore:
    """Cached singleton accessor, mirroring ``get_settings()``."""
    return DocumentStore()
