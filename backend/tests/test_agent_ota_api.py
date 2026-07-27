from __future__ import annotations

import hashlib
import io
import zipfile
from urllib.parse import urlsplit
from uuid import uuid4

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from fastapi import HTTPException

from app.api.agent_rollouts import (
    CANCELLABLE_ROLLOUT_STATUSES,
    PAUSABLE_ROLLOUT_STATUSES,
    RESUMABLE_ROLLOUT_STATUSES,
    _require_rollout_status,
)
from app.core.config import settings
from app.db.models import AgentRollout
from app.services.agent_signing import public_key_to_base64, verify_bundle_signature


def _agent_wheel(version: str = "2.0.0") -> bytes:
    dist_info = f"opsgrid_agent-{version}.dist-info"
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "opsgrid_agent/__init__.py",
            f'__version__ = "{version}"\n',
        )
        archive.writestr("opsgrid_agent/main.py", "def main(): pass\n")
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\n"
            "Name: opsgrid-agent\n"
            f"Version: {version}\n\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\n"
            "Generator: opsgrid-test\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")
    return output.getvalue()


def _write_signing_key(tmp_path, monkeypatch):
    private_key = Ed25519PrivateKey.generate()
    private_path = tmp_path / "ota-release-test-key.pem"
    private_path.write_bytes(
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        )
    )
    monkeypatch.setattr(settings, "OTA_SIGNING_PRIVATE_KEY_PATH", str(private_path))
    monkeypatch.setattr(
        settings,
        "OTA_SIGNING_PUBLIC_KEY",
        public_key_to_base64(private_key.public_key()),
    )
    monkeypatch.setattr(settings, "OTA_STORAGE_PATH", str(tmp_path / "ota-storage"))
    monkeypatch.setattr(settings, "EXPORT_PUBLIC_BASE_URL", "http://test")
    return private_key


def _release_payload(version: str = "1.2.3") -> dict:
    return {
        "version": version,
        "channel": "stable",
        "image_tag": f"registry.local/opsgrid-agent:{version}",
        "config_bundle": "collectors:\n  - type: mqtt\n",
        "bundle_encoding": "text",
        "release_notes": "test release",
    }


async def _seed_asset_type(admin_sync_url: str) -> str:
    import psycopg2

    asset_type_id = str(uuid4())
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s);",
                (asset_type_id, f"OTA type {asset_type_id[:8]}", "test"),
            )
    finally:
        conn.close()
    return asset_type_id


async def _create_asset(client, asset_type_id: str, workcell_id, name: str) -> dict:
    response = await client.post(
        "/api/v1/assets/",
        json={
            "name": name,
            "asset_type_id": asset_type_id,
            "organization_id": str(uuid4()),
            "workcell_id": str(workcell_id),
            "connection_config": {},
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


async def _create_release(client, tmp_path, monkeypatch, version: str = "1.2.3") -> dict:
    _write_signing_key(tmp_path, monkeypatch)
    response = await client.post("/api/v1/fleet/releases", json=_release_payload(version))
    assert response.status_code == 201, response.text
    return response.json()


@pytest.mark.parametrize("rollout_status", ["completed", "cancelled", "rolled_back", "failed"])
def test_terminal_rollout_states_reject_lifecycle_mutations(rollout_status):
    rollout = AgentRollout(status=rollout_status)

    for allowed_statuses, action in (
        (PAUSABLE_ROLLOUT_STATUSES, "paused"),
        (RESUMABLE_ROLLOUT_STATUSES, "resumed"),
        (CANCELLABLE_ROLLOUT_STATUSES, "cancelled"),
    ):
        with pytest.raises(HTTPException) as exc_info:
            _require_rollout_status(rollout, allowed_statuses, action)
        assert exc_info.value.status_code == 400


@pytest.mark.asyncio
async def test_release_create_signs_stores_and_downloads_bundle(client_a, tmp_path, monkeypatch):
    release = await _create_release(client_a, tmp_path, monkeypatch)

    assert release["status"] == "draft"
    assert release["image_tag"] == "registry.local/opsgrid-agent:1.2.3"
    assert release["checksum_sha256"] == hashlib.sha256(
        b"collectors:\n  - type: mqtt\n"
    ).hexdigest()
    assert verify_bundle_signature(
        b"collectors:\n  - type: mqtt\n",
        release["signature_ed25519"],
        settings.OTA_SIGNING_PUBLIC_KEY,
    )
    assert "bundle_url" in release

    bundle_path = urlsplit(release["bundle_url"]).path
    bundle_query = urlsplit(release["bundle_url"]).query
    download = await client_a.get(f"{bundle_path}?{bundle_query}")
    assert download.status_code == 200, download.text
    assert download.content == b"collectors:\n  - type: mqtt\n"
    assert download.headers["x-checksum-sha256"] == release["checksum_sha256"]
    assert download.headers["x-signature-ed25519"] == release["signature_ed25519"]


@pytest.mark.asyncio
async def test_agent_wheel_release_is_signed_downloadable_and_type_scoped(
    client_a,
    tmp_path,
    monkeypatch,
):
    _write_signing_key(tmp_path, monkeypatch)
    config_release = await client_a.post(
        "/api/v1/fleet/releases",
        json=_release_payload("2.0.0"),
    )
    assert config_release.status_code == 201, config_release.text

    wheel = _agent_wheel("2.0.0")
    response = await client_a.post(
        "/api/v1/fleet/releases/agent",
        data={
            "version": "2.0.0",
            "channel": "stable",
            "minimum_bootstrap_version": "1.0.0",
            "release_notes": "agent process update",
        },
        files={
            "artifact": (
                "opsgrid_agent-2.0.0-py3-none-any.whl",
                wheel,
                "application/zip",
            )
        },
    )

    assert response.status_code == 201, response.text
    release = response.json()
    assert release["artifact_type"] == "agent"
    assert release["artifact_format"] == "wheel"
    assert release["artifact_filename"] == "opsgrid_agent-2.0.0-py3-none-any.whl"
    assert release["artifact_size_bytes"] == len(wheel)
    assert release["package_name"] == "opsgrid-agent"
    assert release["minimum_bootstrap_version"] == "1.0.0"
    assert release["checksum_sha256"] == hashlib.sha256(wheel).hexdigest()
    assert verify_bundle_signature(
        wheel,
        release["signature_ed25519"],
        settings.OTA_SIGNING_PUBLIC_KEY,
    )

    artifact_url = urlsplit(release["artifact_url"])
    download = await client_a.get(
        f"{artifact_url.path}?{artifact_url.query}"
    )
    assert download.status_code == 200, download.text
    assert download.content == wheel
    assert download.headers["content-type"].startswith("application/zip")

    listed = await client_a.get(
        "/api/v1/fleet/releases",
        params={"artifact_type": "agent"},
    )
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [release["id"]]


@pytest.mark.asyncio
async def test_agent_wheel_release_rejects_metadata_version_mismatch(
    client_a,
    tmp_path,
    monkeypatch,
):
    _write_signing_key(tmp_path, monkeypatch)
    response = await client_a.post(
        "/api/v1/fleet/releases/agent",
        data={"version": "2.0.1"},
        files={
            "artifact": (
                "opsgrid_agent-2.0.0-py3-none-any.whl",
                _agent_wheel("2.0.0"),
                "application/zip",
            )
        },
    )

    assert response.status_code == 400
    assert "version does not match" in response.json()["detail"]


@pytest.mark.asyncio
async def test_release_lifecycle_and_cross_tenant_404(client_a, client_b, tmp_path, monkeypatch):
    release = await _create_release(client_a, tmp_path, monkeypatch, "1.2.4")

    listed = await client_a.get("/api/v1/fleet/releases")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [release["id"]]

    foreign = await client_b.get(f"/api/v1/fleet/releases/{release['id']}")
    assert foreign.status_code == 404

    published = await client_a.post(f"/api/v1/fleet/releases/{release['id']}/publish")
    assert published.status_code == 200, published.text
    assert published.json()["status"] == "published"

    yanked = await client_a.post(f"/api/v1/fleet/releases/{release['id']}/yank")
    assert yanked.status_code == 200, yanked.text
    assert yanked.json()["status"] == "yanked"


@pytest.mark.asyncio
async def test_ota_mutations_require_admin(
    client_a,
    admin_sync_url,
    seeded_orgs,
    tmp_path,
    monkeypatch,
):
    import psycopg2

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

    _write_signing_key(tmp_path, monkeypatch)
    response = await client_a.post("/api/v1/fleet/releases", json=_release_payload("1.2.5"))
    assert response.status_code == 403

    missing_rollout_id = uuid4()
    for action in ("pause", "resume", "cancel"):
        response = await client_a.post(
            f"/api/v1/fleet/rollouts/{missing_rollout_id}/{action}"
        )
        assert response.status_code == 403


@pytest.mark.asyncio
async def test_rollout_creation_resolves_only_tenant_targets(
    client_a,
    client_b,
    admin_sync_url,
    seeded_orgs,
    tmp_path,
    monkeypatch,
):
    release = await _create_release(client_a, tmp_path, monkeypatch, "1.3.0")
    published = await client_a.post(f"/api/v1/fleet/releases/{release['id']}/publish")
    assert published.status_code == 200

    asset_type_id = await _seed_asset_type(admin_sync_url)
    asset_a1 = await _create_asset(
        client_a,
        asset_type_id,
        seeded_orgs["workcell_a_id"],
        "OTA target A1",
    )
    asset_a2 = await _create_asset(
        client_a,
        asset_type_id,
        seeded_orgs["workcell_a_id"],
        "OTA target A2",
    )
    asset_b = await _create_asset(
        client_b,
        asset_type_id,
        seeded_orgs["workcell_b_id"],
        "OTA target B",
    )

    cross_tenant = await client_a.post(
        "/api/v1/fleet/target-previews",
        json={
            "release_id": release["id"],
            "selector": {"asset_ids": [asset_a1["id"], asset_b["id"]]},
        },
    )
    assert cross_tenant.status_code == 422

    preview_response = await client_a.post(
        "/api/v1/fleet/target-previews",
        json={
            "release_id": release["id"],
            "selector": {"asset_ids": [asset_a1["id"], asset_a2["id"]]},
        },
    )
    assert preview_response.status_code == 201, preview_response.text
    preview = preview_response.json()

    rollout = await client_a.post(
        "/api/v1/fleet/rollouts",
        json={
            "name": "canary rollout",
            "release_id": release["id"],
            "target_selector": {"asset_ids": [asset_a1["id"], asset_a2["id"]]},
            "preview_id": preview["id"],
            "membership_hash": preview["membership_hash"],
            "strategy": {"canary_percentage": 50},
        },
    )
    assert rollout.status_code == 201, rollout.text
    body = rollout.json()
    assert body["status"] == "pending"
    assert len(body["targets"]) == 2
    assert [target["wave_index"] for target in body["targets"]] == [0, 1]
    assert body["events"][0]["event_type"] == "created"

    foreign = await client_b.get(f"/api/v1/fleet/rollouts/{body['id']}")
    assert foreign.status_code == 404

    paused = await client_a.post(f"/api/v1/fleet/rollouts/{body['id']}/pause")
    assert paused.status_code == 200
    assert paused.json()["status"] == "paused"

    duplicate_pause = await client_a.post(f"/api/v1/fleet/rollouts/{body['id']}/pause")
    assert duplicate_pause.status_code == 400

    resumed = await client_a.post(f"/api/v1/fleet/rollouts/{body['id']}/resume")
    assert resumed.status_code == 200
    assert resumed.json()["status"] == "running"
    assert [event["event_type"] for event in resumed.json()["events"]][-2:] == [
        "paused",
        "resumed",
    ]

    duplicate_resume = await client_a.post(f"/api/v1/fleet/rollouts/{body['id']}/resume")
    assert duplicate_resume.status_code == 400

    foreign_resume = await client_b.post(f"/api/v1/fleet/rollouts/{body['id']}/resume")
    assert foreign_resume.status_code == 404

    paused_again = await client_a.post(f"/api/v1/fleet/rollouts/{body['id']}/pause")
    assert paused_again.status_code == 200
    assert paused_again.json()["status"] == "paused"

    cancelled = await client_a.post(f"/api/v1/fleet/rollouts/{body['id']}/cancel")
    assert cancelled.status_code == 200
    assert cancelled.json()["status"] == "cancelled"
    assert {target["status"] for target in cancelled.json()["targets"]} == {"cancelled"}

    duplicate_cancel = await client_a.post(f"/api/v1/fleet/rollouts/{body['id']}/cancel")
    assert duplicate_cancel.status_code == 400


@pytest.mark.asyncio
async def test_agent_ota_rls_hides_rows_without_tenant_context(
    client_a,
    admin_sync_url,
    seeded_orgs,
    tmp_path,
    monkeypatch,
):
    import psycopg2
    from urllib.parse import urlsplit, urlunsplit

    release = await _create_release(client_a, tmp_path, monkeypatch, "1.4.0")
    parts = urlsplit(admin_sync_url)
    host = parts.hostname or "localhost"
    netloc = f"tenant_user:tenant_pass@{host}"
    if parts.port:
        netloc = f"{netloc}:{parts.port}"
    tenant_sync_url = urlunsplit(("postgresql", netloc, parts.path, "", ""))

    conn = psycopg2.connect(tenant_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT count(*) FROM agent_releases;")
            assert cur.fetchone()[0] == 0

            cur.execute(
                "SELECT set_config('app.current_org_id', %s, false);",
                (str(seeded_orgs["org_a_id"]),),
            )
            cur.execute("SELECT id FROM agent_releases;")
            assert [str(row[0]) for row in cur.fetchall()] == [release["id"]]

            cur.execute(
                "SELECT set_config('app.current_org_id', %s, false);",
                (str(seeded_orgs["org_b_id"]),),
            )
            cur.execute("SELECT count(*) FROM agent_releases;")
            assert cur.fetchone()[0] == 0
    finally:
        conn.close()
