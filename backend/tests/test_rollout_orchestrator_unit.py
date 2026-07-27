from __future__ import annotations

from uuid import uuid4

import pytest

from app.db.models import AgentRelease, AgentRollout, AgentRolloutEvent, AgentRolloutTarget
from app.services.rollout_orchestrator import RolloutOrchestrator


class FakeSession:
    def __init__(self):
        self.added = []

    def add(self, item):
        self.added.append(item)

    async def get(self, _model, _id):
        return None


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


def _release(version="2.0.0"):
    return AgentRelease(
        id=uuid4(),
        organization_id=uuid4(),
        version=version,
        channel="stable",
        image_tag=f"registry.local/opsgrid-agent:{version}",
        bundle_storage_key="bundle",
        checksum_sha256="a" * 64,
        signature_ed25519="signature",
        signing_key_id="test-key",
        status="published",
    )


def _rollout(*, waves=(0, 1), strategy=None):
    release = _release()
    rollout = AgentRollout(
        id=uuid4(),
        organization_id=release.organization_id,
        release_id=release.id,
        release=release,
        name="OTA rollout",
        target_selector={},
        strategy=strategy or {"min_success_ratio": 1.0, "failure_threshold": 1},
        status="pending",
        created_by=uuid4(),
    )
    rollout.targets = [
        AgentRolloutTarget(
            id=uuid4(),
            rollout_id=rollout.id,
            organization_id=rollout.organization_id,
            asset_id=uuid4(),
            wave_index=wave,
            status="pending",
        )
        for wave in waves
    ]
    return rollout


def _event_types(session):
    return [
        item.event_type
        for item in session.added
        if isinstance(item, AgentRolloutEvent)
    ]


@pytest.mark.asyncio
async def test_process_rollout_promotes_waves_and_completes(monkeypatch):
    session = FakeSession()
    fake_commands = FakeCommandClient()
    orchestrator = RolloutOrchestrator(command_client=fake_commands)
    rollout = _rollout(waves=(0, 1))

    async def healthy(_session, _target, _release, _strategy):
        return True

    monkeypatch.setattr(orchestrator, "_target_healthy", healthy)

    await orchestrator._process_rollout(session, rollout)
    assert rollout.status == "running"
    assert [target.status for target in rollout.targets] == ["updating", "pending"]
    assert len(fake_commands.submissions) == 1

    fake_commands.statuses["cmd-1"] = {"status": "completed", "result": {"new_version": "2.0.0"}}
    await orchestrator._process_rollout(session, rollout)
    assert [target.status for target in rollout.targets] == ["success", "updating"]
    assert len(fake_commands.submissions) == 2

    fake_commands.statuses["cmd-2"] = {"status": "completed", "result": {"new_version": "2.0.0"}}
    await orchestrator._process_rollout(session, rollout)
    assert rollout.status == "completed"
    assert [target.status for target in rollout.targets] == ["success", "success"]
    assert {"started", "wave_started", "device_updated", "completed"} <= set(_event_types(session))


@pytest.mark.asyncio
async def test_process_rollout_health_timeout_halts_and_dispatches_rollback(monkeypatch):
    session = FakeSession()
    fake_commands = FakeCommandClient()
    rollback_release = _release("1.0.0")
    rollout = _rollout(
        waves=(0, 1),
        strategy={
            "health_timeout_seconds": 0,
            "failure_threshold": 1,
            "rollback_release_id": str(rollback_release.id),
        },
    )
    orchestrator = RolloutOrchestrator(command_client=fake_commands)

    async def unhealthy(_session, _target, _release, _strategy):
        return False

    async def rollback(_session, _rollout):
        return rollback_release

    monkeypatch.setattr(orchestrator, "_target_healthy", unhealthy)
    monkeypatch.setattr(orchestrator, "_rollback_release", rollback)

    await orchestrator._process_rollout(session, rollout)
    fake_commands.statuses["cmd-1"] = {"status": "completed", "result": {}}
    await orchestrator._process_rollout(session, rollout)

    assert rollout.status == "rolled_back"
    assert rollout.targets[0].status == "rolled_back"
    assert rollout.targets[0].rollback_command_id == "cmd-2"
    assert rollout.targets[1].status == "skipped"
    assert {"device_failed", "rolled_back", "device_rollback_dispatched"} <= set(
        _event_types(session)
    )


@pytest.mark.asyncio
async def test_process_rollout_does_not_duplicate_dispatch_for_updating_target():
    session = FakeSession()
    fake_commands = FakeCommandClient()
    orchestrator = RolloutOrchestrator(command_client=fake_commands)
    rollout = _rollout(waves=(0,))

    await orchestrator._process_rollout(session, rollout)
    await orchestrator._process_rollout(session, rollout)

    assert len(fake_commands.submissions) == 1
    assert rollout.targets[0].status == "updating"
    assert rollout.targets[0].command_id == "cmd-1"


@pytest.mark.asyncio
async def test_pause_mid_wave_resume_reconciles_before_next_dispatch(monkeypatch):
    session = FakeSession()
    fake_commands = FakeCommandClient()
    orchestrator = RolloutOrchestrator(command_client=fake_commands)
    rollout = _rollout(waves=(0, 1))

    async def healthy(_session, _target, _release, _strategy):
        return True

    monkeypatch.setattr(orchestrator, "_target_healthy", healthy)

    await orchestrator._process_rollout(session, rollout)
    assert [target.status for target in rollout.targets] == ["updating", "pending"]

    rollout.status = "paused"
    fake_commands.statuses["cmd-1"] = {"status": "completed", "result": {}}
    await orchestrator._process_rollout(session, rollout)

    assert [target.status for target in rollout.targets] == ["updating", "pending"]
    assert len(fake_commands.submissions) == 1

    rollout.status = "running"
    await orchestrator._process_rollout(session, rollout)

    assert [target.status for target in rollout.targets] == ["success", "updating"]
    assert len(fake_commands.submissions) == 2
    assert _event_types(session).index("device_updated") < _event_types(session).index(
        "wave_started", 2
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("rollout_status", ["paused", "cancelled"])
async def test_inactive_rollout_never_dispatches(rollout_status):
    session = FakeSession()
    fake_commands = FakeCommandClient()
    orchestrator = RolloutOrchestrator(command_client=fake_commands)
    rollout = _rollout(waves=(0,))
    rollout.status = rollout_status

    await orchestrator._process_rollout(session, rollout)
    await orchestrator._dispatch_wave(session, rollout, 0)

    assert fake_commands.submissions == []
    assert rollout.targets[0].status == "pending"
    assert _event_types(session) == []


@pytest.mark.asyncio
async def test_agent_release_dispatches_self_update_with_artifact_metadata():
    session = FakeSession()
    fake_commands = FakeCommandClient()
    orchestrator = RolloutOrchestrator(command_client=fake_commands)
    rollout = _rollout(waves=(0,))
    rollout.release.artifact_type = "agent"
    rollout.release.artifact_format = "wheel"
    rollout.release.artifact_filename = "opsgrid_agent-2.0.0-py3-none-any.whl"
    rollout.release.artifact_size_bytes = 1234
    rollout.release.package_name = "opsgrid-agent"
    rollout.release.minimum_bootstrap_version = "1.0.0"

    await orchestrator._dispatch_wave(session, rollout, 0)

    submission = fake_commands.submissions[0]
    assert submission["action_id"] == "agent_self_update"
    assert submission["parameters"]["artifact_format"] == "wheel"
    assert submission["parameters"]["artifact_filename"].endswith(".whl")
    assert submission["parameters"]["artifact_size_bytes"] == 1234
    assert submission["parameters"]["package_name"] == "opsgrid-agent"
    assert submission["parameters"]["minimum_bootstrap_version"] == "1.0.0"
    assert rollout.targets[0].attempted_version == "2.0.0"


@pytest.mark.asyncio
async def test_multi_asset_agent_dispatches_once_and_promotes_as_one_group(
    monkeypatch,
):
    session = FakeSession()
    fake_commands = FakeCommandClient()
    orchestrator = RolloutOrchestrator(command_client=fake_commands)
    rollout = _rollout(waves=(0, 0, 1))
    route_asset_id = rollout.targets[0].asset_id
    for target in rollout.targets[:2]:
        target.agent_id = "agent-shared"
        target.route_asset_id = route_asset_id
    rollout.targets[2].agent_id = "agent-next"
    rollout.targets[2].route_asset_id = rollout.targets[2].asset_id

    async def healthy(_session, _target, _release, _strategy):
        return True

    monkeypatch.setattr(orchestrator, "_target_healthy", healthy)

    await orchestrator._process_rollout(session, rollout)
    assert len(fake_commands.submissions) == 1
    assert fake_commands.submissions[0]["asset_id"] == str(route_asset_id)
    assert [target.command_id for target in rollout.targets[:2]] == [
        "cmd-1",
        "cmd-1",
    ]
    assert [target.status for target in rollout.targets] == [
        "updating",
        "updating",
        "pending",
    ]

    fake_commands.statuses["cmd-1"] = {"status": "completed", "result": {}}
    await orchestrator._process_rollout(session, rollout)

    assert len(fake_commands.submissions) == 2
    assert [target.status for target in rollout.targets] == [
        "success",
        "success",
        "updating",
    ]


def test_failure_threshold_counts_unique_agent_groups():
    orchestrator = RolloutOrchestrator(command_client=FakeCommandClient())
    rollout = _rollout(
        waves=(0, 0, 0),
        strategy={"failure_threshold": 2},
    )
    for target in rollout.targets[:2]:
        target.agent_id = "agent-shared"
        target.status = "failed"
    rollout.targets[2].agent_id = "agent-healthy"
    rollout.targets[2].status = "success"

    assert (
        orchestrator._first_failed_wave_exceeding_threshold(
            rollout.targets,
            rollout.strategy,
        )
        is None
    )


@pytest.mark.asyncio
async def test_failed_ack_with_local_rollback_records_running_version():
    session = FakeSession()
    fake_commands = FakeCommandClient()
    orchestrator = RolloutOrchestrator(command_client=fake_commands)
    rollout = _rollout(waves=(0,))
    rollout.status = "running"
    target = rollout.targets[0]
    target.status = "updating"
    target.command_id = "cmd-1"
    target.current_version = "1.0.0"
    fake_commands.statuses["cmd-1"] = {
        "status": "failed",
        "result": {
            "edge_ack": {
                "result": {
                    "attempted_version": "2.0.0",
                    "running_version": "1.0.0",
                    "rolled_back": True,
                    "phase": "health_timeout",
                    "error": "v2 did not become healthy",
                }
            }
        },
    }

    await orchestrator._refresh_updating_targets(session, rollout)

    assert target.status == "rolled_back"
    assert target.local_rollback is True
    assert target.attempted_version == "2.0.0"
    assert target.running_version == "1.0.0"
    assert target.failure_reason == "v2 did not become healthy"
    assert "device_self_rolled_back" in _event_types(session)
