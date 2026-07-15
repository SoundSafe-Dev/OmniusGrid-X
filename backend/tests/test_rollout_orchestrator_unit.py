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
