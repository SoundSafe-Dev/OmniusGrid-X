"""Focused unit tests for Task 7 bulk-processor parsing/validation helpers.

Pure-function level (no DB/Redis): CSV structural validation, the boolean
coercion that now rejects unrecognised tokens (#15), and UUID validation.
"""

from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.services.bulk_processor import (
    BulkOperationError,
    BulkProcessor,
    _RowError,
    _coerce_bool,
    parse_asset_csv,
)


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
