"""End-to-end tests for the cloud model registry API.

Exercises the whole Task 1 loop: seed telemetry -> POST /train (assemble +
train + register) -> publish -> GET /{name}/latest ({version, download_url,
sha256_hash}) -> download via signed URL -> the bytes load as TorchScript at
(1, 8). Plus RBAC, cross-tenant isolation, and the insufficient-data path.
"""

from __future__ import annotations

import hashlib
import io
from urllib.parse import urlsplit
from uuid import uuid4

import psycopg2
import pytest
import torch

from app.core.config import settings


def _seed_asset_and_telemetry(admin_sync_url, org_id, workcell_id, hours: int = 15) -> str:
    """Seed one asset + `hours` hourly telemetry rows (4 metrics) as superuser."""
    asset_type_id = str(uuid4())
    asset_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s);",
                (asset_type_id, f"ML {asset_type_id[:8]}", "test"),
            )
            cur.execute(
                "INSERT INTO assets "
                "(id, organization_id, workcell_id, asset_type_id, name) "
                "VALUES (%s, %s, %s, %s, %s);",
                (asset_id, str(org_id), str(workcell_id), asset_type_id, "ml-asset"),
            )
            cur.execute(
                """
                INSERT INTO telemetry (time, asset_id, metric_name, value, packml_state)
                SELECT now() - make_interval(hours => g),
                       %s,
                       m.metric_name,
                       m.base + (g %% 5),
                       CASE WHEN g %% 2 = 0 THEN 'Execute' ELSE 'Idle' END
                FROM generate_series(1, %s) g
                CROSS JOIN (VALUES ('temp_nozzle', 200.0), ('temp_bed', 60.0),
                                   ('print_speed', 80.0), ('progress', 10.0))
                     AS m(metric_name, base);
                """,
                (asset_id, hours),
            )
    finally:
        conn.close()
    return asset_id


@pytest.fixture
def model_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "MODEL_STORAGE_PATH", str(tmp_path / "models"))
    monkeypatch.setattr(settings, "EXPORT_PUBLIC_BASE_URL", "http://test")
    return tmp_path


@pytest.mark.asyncio
async def test_train_publish_latest_download_roundtrip(
    client_a, admin_sync_url, seeded_orgs, model_storage
):
    _seed_asset_and_telemetry(
        admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"]
    )

    # Train (synchronous): assemble -> train -> store -> register.
    resp = await client_a.post(
        "/api/v1/models/anomaly/train",
        json={"bucket_seconds": 3600, "window_days": 7},
    )
    assert resp.status_code == 201, resp.text
    run = resp.json()
    assert run["status"] == "succeeded"
    assert run["sample_count"] >= 10
    model_id = run["produced_model_id"]
    assert model_id

    # Draft model is not served by /latest.
    assert (await client_a.get("/api/v1/models/anomaly/latest")).status_code == 404

    # Publish, then /latest returns the exact edge contract.
    pub = await client_a.post(f"/api/v1/models/{model_id}/publish")
    assert pub.status_code == 200 and pub.json()["status"] == "published"

    latest = await client_a.get("/api/v1/models/anomaly/latest")
    assert latest.status_code == 200
    body = latest.json()
    assert set(body) == {"version", "download_url", "sha256_hash"}

    # Download via the signed URL and confirm integrity + TorchScript load.
    parts = urlsplit(body["download_url"])
    dl = await client_a.get(f"{parts.path}?{parts.query}")
    assert dl.status_code == 200, dl.text
    assert dl.headers["X-Checksum-SHA256"] == body["sha256_hash"]
    assert hashlib.sha256(dl.content).hexdigest() == body["sha256_hash"]

    model = torch.jit.load(io.BytesIO(dl.content))
    with torch.no_grad():
        out = model(torch.randn(1, 8))
    assert tuple(out.shape) == (1, 1)


@pytest.mark.asyncio
async def test_cross_tenant_model_get_returns_404(
    client_a, client_b, admin_sync_url, seeded_orgs, model_storage
):
    _seed_asset_and_telemetry(
        admin_sync_url, seeded_orgs["org_a_id"], seeded_orgs["workcell_a_id"]
    )
    run = (await client_a.post("/api/v1/models/anomaly/train", json={})).json()
    model_id = run["produced_model_id"]

    # Org B must not see Org A's model.
    assert (await client_b.get(f"/api/v1/models/{model_id}")).status_code == 404


@pytest.mark.asyncio
async def test_train_requires_admin(client_a, admin_sync_url, seeded_orgs, model_storage):
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE users SET role = 'operator' WHERE id = %s;",
                (str(seeded_orgs["user_a_id"]),),
            )
    finally:
        conn.close()

    resp = await client_a.post("/api/v1/models/anomaly/train", json={})
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_train_with_no_data_returns_422(
    client_a, seeded_orgs, model_storage
):
    # No telemetry seeded -> 0 samples -> recorded failed run -> 422.
    resp = await client_a.post("/api/v1/models/anomaly/train", json={})
    assert resp.status_code == 422
