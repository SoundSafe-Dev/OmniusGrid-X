from __future__ import annotations

from uuid import uuid4

import pytest
from psycopg2.extras import Json

from app.services.rollout_orchestrator import RolloutOrchestrator


class FakeCommandClient:
    def __init__(self):
        self.submissions = []
        self.statuses = {}

    async def submit_command(self, **kwargs):
        command_id = f"cmd-{len(self.submissions) + 1}"
        self.submissions.append({"command_id": command_id, **kwargs})
        self.statuses[command_id] = {"status": "executing", "result": {}}
        return command_id

    async def get_command_status(self, command_id):
        return self.statuses.get(command_id)


def _seed_rollout(
    admin_sync_url,
    seeded_orgs,
    *,
    strategy=None,
    waves=(0, 1),
):
    import psycopg2

    org_id = seeded_orgs["org_a_id"]
    user_id = seeded_orgs["user_a_id"]
    workcell_id = seeded_orgs["workcell_a_id"]
    asset_type_id = uuid4()
    release_id = uuid4()
    rollback_release_id = uuid4()
    rollout_id = uuid4()
    asset_ids = [uuid4() for _ in waves]

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO asset_types (id, name, category) VALUES (%s, %s, %s);",
                (str(asset_type_id), f"OTA type {asset_type_id.hex[:8]}", "test"),
            )
            for index, asset_id in enumerate(asset_ids):
                cur.execute(
                    """
                    INSERT INTO assets
                        (id, organization_id, workcell_id, asset_type_id, name, is_active)
                    VALUES (%s, %s, %s, %s, %s, true);
                    """,
                    (
                        str(asset_id),
                        str(org_id),
                        str(workcell_id),
                        str(asset_type_id),
                        f"OTA asset {index}",
                    ),
                )
            for rid, version in ((release_id, "2.0.0"), (rollback_release_id, "1.0.0")):
                cur.execute(
                    """
                    INSERT INTO agent_releases
                        (id, organization_id, version, channel, image_tag,
                         bundle_storage_key, checksum_sha256, signature_ed25519,
                         signing_key_id, status, created_by)
                    VALUES (%s, %s, %s, 'stable', %s, %s, %s, %s, %s, 'published', %s);
                    """,
                    (
                        str(rid),
                        str(org_id),
                        version,
                        f"registry.local/opsgrid-agent:{version}",
                        f"{org_id}/{rid}.bundle",
                        "a" * 64,
                        "signature",
                        "test-key",
                        str(user_id),
                    ),
                )
            cur.execute(
                """
                INSERT INTO agent_rollouts
                    (id, organization_id, release_id, name, target_selector,
                     strategy, status, created_by)
                VALUES (%s, %s, %s, %s, %s, %s, 'pending', %s);
                """,
                (
                    str(rollout_id),
                    str(org_id),
                    str(release_id),
                    "OTA rollout",
                    Json({"asset_ids": [str(asset_id) for asset_id in asset_ids]}),
                    Json(strategy or {"min_success_ratio": 1.0, "failure_threshold": 1}),
                    str(user_id),
                ),
            )
            for asset_id, wave_index in zip(asset_ids, waves):
                target_id = uuid4()
                cur.execute(
                    """
                    INSERT INTO agent_rollout_targets
                        (id, rollout_id, organization_id, asset_id, wave_index, status)
                    VALUES (%s, %s, %s, %s, %s, 'pending');
                    """,
                    (
                        str(target_id),
                        str(rollout_id),
                        str(org_id),
                        str(asset_id),
                        wave_index,
                    ),
                )
    finally:
        conn.close()

    return {
        "org_id": org_id,
        "release_id": release_id,
        "rollback_release_id": rollback_release_id,
        "rollout_id": rollout_id,
        "asset_ids": asset_ids,
    }


def _fetch_rollout(admin_sync_url, rollout_id):
    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(admin_sync_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("SELECT status FROM agent_rollouts WHERE id = %s;", (str(rollout_id),))
            rollout = dict(cur.fetchone())
            cur.execute(
                """
                SELECT asset_id, wave_index, status, command_id, rollback_command_id,
                       failure_reason
                FROM agent_rollout_targets
                WHERE rollout_id = %s
                ORDER BY wave_index, asset_id;
                """,
                (str(rollout_id),),
            )
            targets = [dict(row) for row in cur.fetchall()]
            cur.execute(
                """
                SELECT event_type, asset_id, detail
                FROM agent_rollout_events
                WHERE rollout_id = %s
                ORDER BY created_at, id;
                """,
                (str(rollout_id),),
            )
            events = [dict(row) for row in cur.fetchall()]
    finally:
        conn.close()
    return rollout, targets, events


@pytest.mark.asyncio
async def test_rollout_promotes_canary_to_full_and_completes(
    app,
    admin_sync_url,
    seeded_orgs,
    monkeypatch,
):
    monkeypatch.setattr("app.core.config.settings.EXPORT_PUBLIC_BASE_URL", "http://test")
    seeded = _seed_rollout(admin_sync_url, seeded_orgs, waves=(0, 1))
    fake_commands = FakeCommandClient()
    orchestrator = RolloutOrchestrator(command_client=fake_commands)

    async def healthy(_session, _target, _release, _strategy):
        return True

    monkeypatch.setattr(orchestrator, "_target_healthy", healthy)

    await orchestrator.dispatch_rollout(seeded["rollout_id"], seeded["org_id"])
    assert len(fake_commands.submissions) == 1

    fake_commands.statuses["cmd-1"] = {"status": "completed", "result": {"new_version": "2.0.0"}}
    await orchestrator.dispatch_rollout(seeded["rollout_id"], seeded["org_id"])
    assert len(fake_commands.submissions) == 2

    fake_commands.statuses["cmd-2"] = {"status": "completed", "result": {"new_version": "2.0.0"}}
    await orchestrator.dispatch_rollout(seeded["rollout_id"], seeded["org_id"])

    rollout, targets, events = _fetch_rollout(admin_sync_url, seeded["rollout_id"])
    assert rollout["status"] == "completed"
    assert [target["status"] for target in targets] == ["success", "success"]
    assert [item["action_id"] for item in fake_commands.submissions] == [
        "agent_update",
        "agent_update",
    ]
    assert "started" in {event["event_type"] for event in events}
    assert "wave_started" in {event["event_type"] for event in events}
    assert "completed" in {event["event_type"] for event in events}


@pytest.mark.asyncio
async def test_health_timeout_dispatches_rollback_and_halts_rollout(
    app,
    admin_sync_url,
    seeded_orgs,
    monkeypatch,
):
    monkeypatch.setattr("app.core.config.settings.EXPORT_PUBLIC_BASE_URL", "http://test")
    seeded = _seed_rollout(
        admin_sync_url,
        seeded_orgs,
        strategy={
            "health_timeout_seconds": 0,
            "failure_threshold": 1,
            "rollback_release_id": "",
        },
        waves=(0, 1),
    )
    # Patch the rollback id after seeding so it can reference the generated release.
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE agent_rollouts SET strategy = strategy || %s::jsonb WHERE id = %s;",
                (
                    Json({"rollback_release_id": str(seeded["rollback_release_id"])}),
                    str(seeded["rollout_id"]),
                ),
            )
    finally:
        conn.close()

    fake_commands = FakeCommandClient()
    orchestrator = RolloutOrchestrator(command_client=fake_commands)

    async def unhealthy(_session, _target, _release, _strategy):
        return False

    monkeypatch.setattr(orchestrator, "_target_healthy", unhealthy)

    await orchestrator.dispatch_rollout(seeded["rollout_id"], seeded["org_id"])
    fake_commands.statuses["cmd-1"] = {"status": "completed", "result": {}}
    await orchestrator.dispatch_rollout(seeded["rollout_id"], seeded["org_id"])

    rollout, targets, events = _fetch_rollout(admin_sync_url, seeded["rollout_id"])
    assert rollout["status"] == "rolled_back"
    assert targets[0]["status"] == "rolled_back"
    assert targets[0]["rollback_command_id"] == "cmd-2"
    assert targets[1]["status"] == "skipped"
    assert {event["event_type"] for event in events} >= {
        "device_failed",
        "rolled_back",
        "device_rollback_dispatched",
    }


@pytest.mark.asyncio
async def test_running_target_is_not_dispatched_twice(
    app,
    admin_sync_url,
    seeded_orgs,
    monkeypatch,
):
    monkeypatch.setattr("app.core.config.settings.EXPORT_PUBLIC_BASE_URL", "http://test")
    seeded = _seed_rollout(admin_sync_url, seeded_orgs, waves=(0,))
    fake_commands = FakeCommandClient()
    orchestrator = RolloutOrchestrator(command_client=fake_commands)

    await orchestrator.dispatch_rollout(seeded["rollout_id"], seeded["org_id"])
    await orchestrator.dispatch_rollout(seeded["rollout_id"], seeded["org_id"])

    assert len(fake_commands.submissions) == 1
    _, targets, _ = _fetch_rollout(admin_sync_url, seeded["rollout_id"])
    assert targets[0]["status"] == "updating"
    assert targets[0]["command_id"] == "cmd-1"
