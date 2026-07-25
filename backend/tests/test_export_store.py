"""Unit tests for the export object-store backend (S3/SeaweedFS).

Uses a fake aioboto3 session so no live S3 is needed: the fake records
upload/get/head/delete calls and lets us assert the roundtrip and the
``enabled`` gating without network I/O.
"""
import io

import pytest

from app.services import export_store as es_module
from app.services.export_store import ExportStore, export_object_key


class _FakeBody:
    """Mimics the aiobotocore streaming Body: async context manager + read()."""

    def __init__(self, data: bytes):
        self._buf = io.BytesIO(data)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def read(self, n: int = -1) -> bytes:
        return self._buf.read(n)


class _FakeS3:
    def __init__(self, store: dict, fail_head: bool = False):
        self._store = store
        self._fail_head = fail_head
        self.created_buckets: list[str] = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False

    async def head_bucket(self, Bucket):
        if self._fail_head:
            raise RuntimeError("no such bucket")

    async def create_bucket(self, Bucket):
        self.created_buckets.append(Bucket)

    async def upload_file(self, local_path, bucket, key):
        with open(local_path, "rb") as fh:
            self._store[(bucket, key)] = fh.read()

    async def get_object(self, Bucket, Key):
        return {"Body": _FakeBody(self._store[(Bucket, Key)])}

    async def head_object(self, Bucket, Key):
        if (Bucket, Key) not in self._store:
            raise RuntimeError("404")

    async def delete_object(self, Bucket, Key):
        self._store.pop((Bucket, Key), None)


class _FakeSession:
    """Stands in for aioboto3.Session; hands out a shared fake S3 client."""

    def __init__(self, fail_head: bool = False):
        self.store: dict = {}
        self._fail_head = fail_head

    def client(self, *args, **kwargs):
        return _FakeS3(self.store, fail_head=self._fail_head)


def test_export_object_key_strips_leading_dot():
    assert export_object_key("job-123", ".csv") == "exports/job-123.csv"
    assert export_object_key("job-123", "pdf") == "exports/job-123.pdf"


def test_enabled_requires_flag_and_session(monkeypatch):
    monkeypatch.setattr(es_module.settings, "EXPORT_USE_S3", False, raising=False)
    store = ExportStore(session=_FakeSession())
    assert store.enabled is False

    monkeypatch.setattr(es_module.settings, "EXPORT_USE_S3", True, raising=False)
    assert store.enabled is True

    # Flag on but no client available (dep missing) -> still disabled.
    store_no_session = ExportStore(session=None)
    store_no_session._session = None
    assert store_no_session.enabled is False


@pytest.mark.asyncio
async def test_upload_then_download_roundtrip(monkeypatch, tmp_path):
    monkeypatch.setattr(es_module.settings, "EXPORT_USE_S3", True, raising=False)
    session = _FakeSession()
    store = ExportStore(session=session)

    src = tmp_path / "report.csv"
    payload = b"col_a,col_b\n1,2\n3,4\n"
    src.write_bytes(payload)

    key = export_object_key("job-abc", "csv")
    await store.upload_file(key, str(src))

    assert (store.bucket, key) in session.store

    chunks = [c async for c in store.download_stream(key)]
    assert b"".join(chunks) == payload


@pytest.mark.asyncio
async def test_exists_true_and_false(monkeypatch, tmp_path):
    monkeypatch.setattr(es_module.settings, "EXPORT_USE_S3", True, raising=False)
    session = _FakeSession()
    store = ExportStore(session=session)

    key = export_object_key("job-xyz", "csv")
    assert await store.exists(key) is False

    src = tmp_path / "f.csv"
    src.write_bytes(b"x")
    await store.upload_file(key, str(src))
    assert await store.exists(key) is True


@pytest.mark.asyncio
async def test_delete_is_best_effort(monkeypatch, tmp_path):
    monkeypatch.setattr(es_module.settings, "EXPORT_USE_S3", True, raising=False)
    session = _FakeSession()
    store = ExportStore(session=session)

    key = export_object_key("job-del", "csv")
    src = tmp_path / "f.csv"
    src.write_bytes(b"x")
    await store.upload_file(key, str(src))
    await store.delete(key)
    assert await store.exists(key) is False

    # Deleting an absent key must not raise.
    await store.delete(export_object_key("missing", "csv"))


@pytest.mark.asyncio
async def test_ensure_bucket_creates_when_missing(monkeypatch):
    monkeypatch.setattr(es_module.settings, "EXPORT_USE_S3", True, raising=False)
    session = _FakeSession(fail_head=True)
    store = ExportStore(session=session)
    # head_bucket raises -> create_bucket is invoked; must not raise.
    await store.ensure_bucket()
