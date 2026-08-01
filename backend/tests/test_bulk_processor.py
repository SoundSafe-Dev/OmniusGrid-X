"""Focused unit tests for Task 7 bulk-processor parsing/validation helpers.

Pure-function level (no DB/Redis): CSV structural validation, the boolean
coercion that now rejects unrecognised tokens (#15), and UUID validation.
"""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.bulk_processor import (
    BulkJobCancellationError,
    BulkOperationError,
    BulkProcessor,
    _RowError,
    _coerce_bool,
    parse_asset_csv,
)


class _MemoryRedis:
    def __init__(self):
        self.store = {}

    async def set(self, key, value, ex=None):
        self.store[key] = value

    async def get(self, key):
        return self.store.get(key)

    async def aclose(self):
        self.store.clear()


# --- parse_asset_csv --------------------------------------------------------
def test_parse_csv_happy_path():
    raw = b"name,serial_number,is_active\nPump A,SN1,true\nPump B,SN2,false\n"
    rows = parse_asset_csv(raw)
    assert len(rows) == 2
    assert rows[0]["name"] == "Pump A" and rows[0]["is_active"] == "true"


def test_parse_csv_unknown_column_raises():
    with pytest.raises(BulkOperationError):
        parse_asset_csv(b"name,bogus_col\nPump,1\n")


def test_parse_csv_requires_id_or_name():
    with pytest.raises(BulkOperationError):
        parse_asset_csv(b"serial_number,vendor\nSN1,Acme\n")


def test_parse_csv_header_only_raises():
    with pytest.raises(BulkOperationError):
        parse_asset_csv(b"name,serial_number\n")


def test_parse_csv_rejects_non_utf8():
    with pytest.raises(BulkOperationError):
        parse_asset_csv(b"name\n\xff\xfe\x00bad")


# A MALFORMED CSV IS THE CALLER'S FILE, NOT A SERVER FAULT (FS-259).
#
# `parse_asset_csv` documents that it converts structural problems into
# `BulkOperationError` so the endpoint can answer 400 — and it did that for a bad
# encoding while letting `csv.Error` straight through. Two ordinary malformed uploads
# therefore reached `POST /bulk/assets/import` as 500s. Found by the contract gate
# driving generated multipart bodies at it.
def test_parse_csv_rejects_an_oversized_field():
    """csv caps a field at 131072 characters and raises `_csv.Error` past it."""
    with pytest.raises(BulkOperationError):
        parse_asset_csv(b"name\n" + b"a" * 200_000 + b"\n")


def test_parse_csv_rejects_a_bare_carriage_return():
    """"new-line character seen in unquoted field" — a Classic-Mac line ending."""
    with pytest.raises(BulkOperationError):
        parse_asset_csv(b"name\rPump\r")


def test_a_malformed_row_after_a_clean_header_is_still_a_400():
    """The header and the body rows raise from different places, so both are wrapped."""
    with pytest.raises(BulkOperationError):
        parse_asset_csv(b"name,vendor\nPump,Acme\n" + b"b" * 200_000 + b"\n")


def test_a_valid_csv_still_parses_after_the_guards():
    """The fix must not turn a good file into a rejection."""
    rows = parse_asset_csv(b"name,vendor\nPress-1,Acme\nPress-2,Acme\n")
    assert [r["name"] for r in rows] == ["Press-1", "Press-2"]


def test_parse_csv_skips_blank_lines():
    rows = parse_asset_csv(b"name\nA\n\n\nB\n")
    assert [r["name"] for r in rows] == ["A", "B"]


# --- _coerce_bool (#15) -----------------------------------------------------
@pytest.mark.parametrize("token", ["1", "true", "TRUE", "Yes", "y", "t"])
def test_coerce_bool_true_tokens(token):
    assert _coerce_bool(token) is True


@pytest.mark.parametrize("token", ["0", "false", "No", "n", "f"])
def test_coerce_bool_false_tokens(token):
    assert _coerce_bool(token) is False


def test_coerce_bool_empty_uses_default():
    assert _coerce_bool("", default=True) is True
    assert _coerce_bool(None, default=False) is False


@pytest.mark.parametrize("token", ["Flase", "ye", "maybe", "2", "tru"])
def test_coerce_bool_invalid_raises(token):
    # Previously these silently became False; now they fail the row loudly.
    with pytest.raises(_RowError):
        _coerce_bool(token)


# --- _as_uuid ---------------------------------------------------------------
def test_as_uuid_valid_and_invalid():
    good = "11111111-1111-1111-1111-111111111111"
    assert str(BulkProcessor._as_uuid(good, "id")) == good
    with pytest.raises(_RowError):
        BulkProcessor._as_uuid("not-a-uuid", "id")


@pytest.mark.asyncio
async def test_cancel_job_marks_pending_job_cancelled():
    processor = BulkProcessor()
    processor._client = _MemoryRedis()
    org_id = uuid4()
    actor_id = uuid4()
    job = await processor.create_job(
        "asset_import",
        total=3,
        organization_id=org_id,
        actor_id=actor_id,
    )

    cancelled = await processor.cancel_job(job["job_id"], org_id, actor_id)

    assert cancelled["status"] == "cancelled"
    assert cancelled["cancelled_by"] == str(actor_id)
    assert cancelled["cancelled_at"]
    assert (await processor.get_job(job["job_id"]))["status"] == "cancelled"


@pytest.mark.asyncio
async def test_cancel_job_rejects_terminal_jobs():
    processor = BulkProcessor()
    processor._client = _MemoryRedis()
    org_id = uuid4()
    job = await processor.create_job(
        "asset_import",
        total=1,
        organization_id=org_id,
        actor_id=uuid4(),
    )
    job["status"] = "completed"
    await processor._save(job)

    with pytest.raises(BulkJobCancellationError):
        await processor.cancel_job(job["job_id"], org_id, uuid4())


@pytest.mark.asyncio
async def test_cancelled_asset_import_exits_before_opening_tenant_session(monkeypatch):
    processor = BulkProcessor()
    processor._client = _MemoryRedis()
    org_id = uuid4()
    actor_id = uuid4()
    job = await processor.create_job(
        "asset_import",
        total=1,
        organization_id=org_id,
        actor_id=actor_id,
    )
    await processor.cancel_job(job["job_id"], org_id, actor_id)
    monkeypatch.setattr(processor, "_audit", AsyncMock())

    def fail_if_opened(_organization_id):
        raise AssertionError("cancelled job should not open a tenant session")

    monkeypatch.setattr(processor, "_tenant_session", fail_if_opened)

    await processor.run_asset_import(
        job["job_id"],
        [{"name": "Pump A"}],
        org_id,
        actor_id,
    )

    saved = await processor.get_job(job["job_id"])
    assert saved["status"] == "cancelled"
    processor._audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_asset_import_records_job_level_failure(monkeypatch):
    processor = BulkProcessor()
    processor._client = _MemoryRedis()
    org_id = uuid4()
    actor_id = uuid4()
    job = await processor.create_job(
        "asset_import",
        total=1,
        organization_id=org_id,
        actor_id=actor_id,
    )
    monkeypatch.setattr(processor, "_audit", AsyncMock())

    @asynccontextmanager
    async def broken_tenant_session(_organization_id):
        raise RuntimeError("database unavailable")
        yield

    monkeypatch.setattr(processor, "_tenant_session", broken_tenant_session)

    await processor.run_asset_import(
        job["job_id"],
        [{"name": "Pump A"}],
        org_id,
        actor_id,
    )

    saved = await processor.get_job(job["job_id"])
    assert saved["status"] == "failed"
    assert saved["errors"] == [
        {"ref": None, "error": "job failed: database unavailable"}
    ]
    processor._audit.assert_awaited_once()


@pytest.mark.asyncio
async def test_bulk_job_status_and_cancel_are_tenant_scoped(
    client_a,
    client_b,
    seeded_orgs,
    monkeypatch,
):
    import app.api.bulk_operations as bulk_api

    job_id = str(uuid4())
    job = {
        "job_id": job_id,
        "type": "asset_import",
        "status": "pending",
        "total": 1,
        "processed": 0,
        "succeeded": 0,
        "failed": 0,
        "errors": [],
        "organization_id": str(seeded_orgs["org_a_id"]),
    }

    async def fake_get_job(_job_id):
        return dict(job)

    async def fake_cancel_job(_job_id, organization_id, actor_id):
        if str(organization_id) != job["organization_id"]:
            return None
        job["status"] = "cancelled"
        job["cancelled_by"] = str(actor_id)
        return dict(job)

    monkeypatch.setattr(bulk_api.bulk_processor, "get_job", fake_get_job)
    monkeypatch.setattr(bulk_api.bulk_processor, "cancel_job", fake_cancel_job)

    owner_status = await client_a.get(f"/api/v1/bulk/jobs/{job_id}")
    foreign_status = await client_b.get(f"/api/v1/bulk/jobs/{job_id}")
    foreign_cancel = await client_b.post(f"/api/v1/bulk/jobs/{job_id}/cancel")
    owner_cancel = await client_a.post(f"/api/v1/bulk/jobs/{job_id}/cancel")

    assert owner_status.status_code == 200
    assert owner_status.json()["status"] == "pending"
    assert foreign_status.status_code == 404
    assert foreign_cancel.status_code == 404
    assert owner_cancel.status_code == 200
    assert owner_cancel.json()["status"] == "cancelled"


@pytest.mark.asyncio
async def test_registry_bulk_preflight_is_tenant_scoped(
    client_a,
    client_b,
    admin_sync_url,
    seeded_orgs,
    monkeypatch,
):
    import psycopg2

    registry_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO actionable_registries (
                    id, organization_id, registry_name, registry_type,
                    assigned_owner_id, created_by
                ) VALUES (%s, %s, 'Tenant registry', 'operational', %s, %s)
                """,
                (
                    str(registry_id),
                    str(seeded_orgs["org_a_id"]),
                    str(seeded_orgs["user_a_id"]),
                    str(seeded_orgs["user_a_id"]),
                ),
            )
    finally:
        conn.close()

    from app.services.bulk_processor import bulk_processor

    monkeypatch.setattr(
        bulk_processor,
        "create_job",
        AsyncMock(
            return_value={
                "job_id": str(uuid4()),
                "type": "registry_items",
                "status": "queued",
                "total": 1,
            }
        ),
    )
    monkeypatch.setattr(bulk_processor, "run_registry_items", AsyncMock())
    payload = {"items": [{"item_code": "R-1", "item_name": "Inspect"}]}

    own = await client_a.post(
        f"/api/v1/bulk/registries/{registry_id}/items",
        json=payload,
    )
    foreign = await client_b.post(
        f"/api/v1/bulk/registries/{registry_id}/items",
        json=payload,
    )

    assert own.status_code == 202
    assert foreign.status_code == 404
