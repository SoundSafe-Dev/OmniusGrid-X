from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import pytest

from opsgrid_agent.buffer.store_forward import StoreForwardBuffer
from opsgrid_agent.collectors.coordinator import (
    CollectorConfig,
    UnifiedCollectorCoordinator,
)
from opsgrid_agent.commands import CommandConsumer
from opsgrid_agent.remote_ops import AgentRemoteOperations
from opsgrid_agent.remote_ops.log_buffer import StructuredLogBuffer
from opsgrid_agent.remote_ops.safety import REDACTED, sanitize


ORGANIZATION_ID = "22222222-2222-4222-8222-222222222222"
ASSET_ID = "44444444-4444-4444-8444-444444444444"
SECOND_ASSET_ID = "55555555-5555-4555-8555-555555555555"
COMMAND_ID = "11111111-1111-4111-8111-111111111111"


class _Buffer:
    async def get_stats(self):
        return {
            "total_messages": 3,
            "failed_messages": 1,
            "size_mb": 0.5,
        }


class _Coordinator:
    def __init__(self):
        self.restart_calls = []

    def get_status(self):
        return {
            "running": True,
            "total_collectors": 2,
            "active_collectors": 2,
            "collectors": {
                ASSET_ID: {
                    "type": "mqtt",
                    "enabled": True,
                    "running": True,
                },
                SECOND_ASSET_ID: {
                    "type": "modbus",
                    "enabled": True,
                    "running": True,
                },
            },
        }

    async def restart_collector(self, asset_id, *, readiness_timeout_seconds):
        self.restart_calls.append((asset_id, readiness_timeout_seconds))
        return {
            "before": {"asset_id": asset_id, "running": True},
            "after": {"asset_id": asset_id, "running": True},
        }


def _service(log_buffer=None, coordinator=None):
    config = {
        "buffer_path": "/tmp/opsgrid-test-buffer.db",
        "heartbeat_interval_seconds": 60,
        "buffer_retention_hours": 24,
        "bootstrap_managed": True,
        "collectors": [
            {
                "asset_id": ASSET_ID,
                "type": "mqtt",
                "config": {
                    "broker_host": "mqtt.local",
                    "password": "do-not-return",
                    "artifact_url": "https://example.test/a?token=secret",
                },
            }
        ],
    }
    return AgentRemoteOperations(
        agent_id="agent-1",
        config_provider=lambda: config,
        manifest_provider=lambda: {
            "agent_version": "2.0.0",
            "build_id": "build-1",
            "git_sha": "abc123",
            "build_time": "2026-07-24T00:00:00Z",
        },
        config_hash_provider=lambda: "a" * 64,
        buffer=_Buffer(),
        coordinator=coordinator or _Coordinator(),
        kafka_connected=lambda: True,
        command_connected=lambda: True,
        log_buffer=log_buffer or StructuredLogBuffer(capacity=10),
        started_monotonic=0,
    )


def _command(action, parameters, *, asset_id=ASSET_ID):
    return {
        "command_id": COMMAND_ID,
        "asset_id": asset_id,
        "organization_id": ORGANIZATION_ID,
        "action_id": action,
        "parameters": parameters,
    }


def test_recursive_redaction_scrubs_keys_inline_secrets_and_signed_urls():
    cleaned = sanitize(
        {
            "password": "plain",
            "nested": {
                "api_key": "abc",
                "message": "authorization=Bearer-secret",
                "url": "https://user:pass@example.test/a?signature=abc",
            },
        }
    )

    assert cleaned.value["password"] == REDACTED
    assert cleaned.value["nested"]["api_key"] == REDACTED
    assert REDACTED in cleaned.value["nested"]["message"]
    assert "user:pass" not in cleaned.value["nested"]["url"]
    assert "signature=abc" not in cleaned.value["nested"]["url"]
    assert cleaned.redacted_fields >= 4


def test_log_buffer_is_bounded_filtered_and_redacted():
    ring = StructuredLogBuffer(capacity=3)
    ring.append("info", {"event": "first", "password": "secret"})
    cutoff = datetime.now(timezone.utc) - timedelta(seconds=1)
    ring.append("warning", {"event": "second", "token": "secret"})
    ring.append("error", {"event": "third"})
    ring.append("debug", {"event": "fourth"})

    entries, available, redacted, truncated = ring.fetch(
        limit=2,
        since=cutoff,
        levels={"warning", "error"},
    )

    assert [entry["event"] for entry in entries] == ["second", "third"]
    assert available == 2
    assert redacted == 1
    assert truncated is False
    assert entries[0]["fields"]["token"] == REDACTED


@pytest.mark.asyncio
async def test_effective_config_is_redacted_and_contains_no_environment_dump():
    result = await _service().effective_config(
        _command(
            "agent_effective_config",
            {"schema_version": 1},
        )
    )

    collector = result["effective_config"]["collectors"][0]
    assert collector["config"]["password"] == REDACTED
    assert "token=secret" not in collector["config"]["artifact_url"]
    assert "environment" not in result["effective_config"]
    assert result["redacted_fields"] >= 2
    assert result["config_hash"] == "a" * 64


@pytest.mark.asyncio
async def test_diagnostics_are_fixed_and_report_transport_and_collectors():
    result = await _service().diagnostics(
        _command("agent_diagnostics", {"schema_version": 1})
    )

    assert result["agent"]["version"] == "2.0.0"
    assert result["buffer"]["stats"]["total_messages"] == 3
    assert result["transport"] == {
        "kafka_connected": True,
        "command_connected": True,
    }
    assert set(result["collectors"]["collectors"]) == {
        ASSET_ID,
        SECOND_ASSET_ID,
    }


@pytest.mark.asyncio
async def test_restart_targets_exactly_one_collector():
    coordinator = _Coordinator()
    result = await _service(coordinator=coordinator).restart_collector(
        _command(
            "collector_restart",
            {
                "schema_version": 1,
                "collector_asset_id": ASSET_ID,
                "readiness_timeout_seconds": 7,
            },
        )
    )

    assert coordinator.restart_calls == [(ASSET_ID, 7)]
    assert result["collector_asset_id"] == ASSET_ID
    assert result["ready"] is True


@pytest.mark.asyncio
async def test_remote_parameter_contract_rejects_arbitrary_path_before_handler():
    consumer = CommandConsumer(
        agent_id="agent-1",
        organization_id=ORGANIZATION_ID,
        asset_ids={ASSET_ID},
        redpanda_url="localhost:9092",
    )
    consumer._producer = AsyncMock()
    handler = AsyncMock(return_value={})
    consumer.register_handler("agent_fetch_logs", handler)

    ack = await consumer.handle_message(
        {
            "schema_version": 1,
            "message_type": "command",
            "command_id": COMMAND_ID,
            "asset_id": ASSET_ID,
            "organization_id": ORGANIZATION_ID,
            "action_id": "agent_fetch_logs",
            "parameters": {
                "schema_version": 1,
                "limit": 5,
                "path": "/var/log/messages",
            },
        }
    )

    assert ack["status"] == "rejected"
    assert ack["result"]["error_code"] == "invalid_parameters"
    handler.assert_not_awaited()


@pytest.mark.asyncio
async def test_duplicate_restart_command_reemits_ack_without_second_restart():
    coordinator = _Coordinator()
    service = _service(coordinator=coordinator)
    consumer = CommandConsumer(
        agent_id="agent-1",
        organization_id=ORGANIZATION_ID,
        asset_ids={ASSET_ID},
        redpanda_url="localhost:9092",
    )
    consumer._producer = AsyncMock()
    service.register(consumer)
    command = {
        "schema_version": 1,
        "message_type": "command",
        "command_id": COMMAND_ID,
        "asset_id": ASSET_ID,
        "organization_id": ORGANIZATION_ID,
        "action_id": "collector_restart",
        "parameters": {
            "schema_version": 1,
            "collector_asset_id": ASSET_ID,
            "readiness_timeout_seconds": 5,
        },
    }

    first = await consumer.handle_message(command)
    second = await consumer.handle_message(command)

    assert second == first
    assert coordinator.restart_calls == [(ASSET_ID, 5)]


class _FakeCollector:
    instances = []

    def __init__(self, **_kwargs):
        self.stops = 0
        self.__class__.instances.append(self)

    async def start(self):
        await asyncio.Event().wait()

    async def stop(self):
        self.stops += 1


@pytest.mark.asyncio
async def test_coordinator_restart_leaves_other_collector_task_untouched(tmp_path):
    _FakeCollector.instances.clear()
    buffer = StoreForwardBuffer(buffer_path=str(tmp_path / "buffer.db"))
    coordinator = UnifiedCollectorCoordinator(buffer)
    coordinator.SUPPORTED_COLLECTORS = {"fake": _FakeCollector}
    coordinator._running = True
    coordinator.register_collector(
        CollectorConfig("fake", ASSET_ID, {}, enabled=True)
    )
    coordinator.register_collector(
        CollectorConfig("fake", SECOND_ASSET_ID, {}, enabled=True)
    )
    assert await coordinator._start_collector(coordinator.configs[ASSET_ID])
    assert await coordinator._start_collector(
        coordinator.configs[SECOND_ASSET_ID]
    )
    other_task = coordinator.collector_tasks[SECOND_ASSET_ID]

    outcome = await coordinator.restart_collector(
        ASSET_ID,
        readiness_timeout_seconds=1,
    )

    assert outcome["after"]["running"] is True
    assert coordinator.collector_tasks[SECOND_ASSET_ID] is other_task
    assert not other_task.done()
    assert len(_FakeCollector.instances) == 3
    await coordinator.stop_all()
