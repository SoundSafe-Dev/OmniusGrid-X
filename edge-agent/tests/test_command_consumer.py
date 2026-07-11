import json
from unittest.mock import AsyncMock

import pytest

from opsgrid_agent.commands import CommandConsumer


class PhasedError(RuntimeError):
    def __init__(self, phase, message):
        self.phase = phase
        super().__init__(message)


def _consumer(**overrides):
    consumer = CommandConsumer(
        agent_id="agent-1",
        organization_id="org-1",
        asset_ids={"asset-1", "asset-2"},
        redpanda_url="localhost:9092",
        **overrides,
    )
    consumer._producer = AsyncMock()
    return consumer


def _command(**overrides):
    payload = {
        "schema_version": 1,
        "message_type": "command",
        "command_id": "cmd-1",
        "asset_id": "asset-1",
        "organization_id": "org-1",
        "action_id": "set_speed",
        "parameters": {"speed": 42},
        "timeout_seconds": 30,
        "timestamp": "2030-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_dispatches_command_for_owned_asset_and_emits_success_ack():
    consumer = _consumer()
    handler = AsyncMock(return_value={"actual_speed": 42})
    consumer.register_handler("set_speed", handler)

    ack = await consumer.handle_message(_command())

    handler.assert_awaited_once()
    assert handler.await_args.args[0]["parameters"] == {"speed": 42}
    assert ack["command_id"] == "cmd-1"
    assert ack["agent_id"] == "agent-1"
    assert ack["asset_id"] == "asset-1"
    assert ack["status"] == "completed"
    assert ack["success"] is True
    assert ack["result"] == {"actual_speed": 42}
    consumer._producer.send_and_wait.assert_awaited_once_with(
        "opsgrid.commands.acks",
        ack,
        key="cmd-1",
    )


@pytest.mark.asyncio
async def test_dispatches_command_targeted_to_agent_without_asset_match():
    consumer = _consumer()
    handler = AsyncMock(return_value={})
    consumer.register_handler("set_speed", handler)

    ack = await consumer.handle_message(
        _command(agent_id="agent-1", asset_id="other-asset")
    )

    assert ack["status"] == "completed"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_skips_commands_for_other_agent_asset_or_organization():
    consumer = _consumer()
    handler = AsyncMock(return_value={})
    consumer.register_handler("set_speed", handler)

    assert await consumer.handle_message(_command(agent_id="agent-2")) is None
    assert await consumer.handle_message(_command(asset_id="asset-99")) is None
    assert await consumer.handle_message(_command(organization_id="org-2")) is None
    assert await consumer.handle_message(_command(message_type="heartbeat")) is None

    handler.assert_not_awaited()
    consumer._producer.send_and_wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_unknown_action_is_rejected_with_backend_compatible_ack():
    consumer = _consumer()

    ack = await consumer.handle_message(_command(action_id="not_registered"))

    assert ack["status"] == "rejected"
    assert ack["success"] is False
    assert ack["error"] == "unknown_action"
    assert ack["result"] == {
        "error": "unknown_action",
        "action_id": "not_registered",
    }
    consumer._producer.send_and_wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_malformed_payloads_are_skipped():
    consumer = _consumer()

    assert await consumer.handle_message(b"{not-json") is None
    assert await consumer.handle_message(["not", "a", "dict"]) is None
    assert await consumer.handle_message(_command(command_id="")) is None

    consumer._producer.send_and_wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_handler_exception_emits_failed_ack():
    consumer = _consumer()

    async def handler(_payload):
        raise RuntimeError("PLC rejected command")

    consumer.register_handler("set_speed", handler)

    ack = await consumer.handle_message(_command())

    assert ack["status"] == "failed"
    assert ack["success"] is False
    assert ack["error"] == "PLC rejected command"
    assert ack["result"]["error"] == "PLC rejected command"
    consumer._producer.send_and_wait.assert_awaited_once()


@pytest.mark.asyncio
async def test_handler_phased_exception_includes_phase_in_failed_ack():
    consumer = _consumer()

    async def handler(_payload):
        raise PhasedError("verify", "Config bundle checksum mismatch")

    consumer.register_handler("set_speed", handler)

    ack = await consumer.handle_message(_command())

    assert ack["status"] == "failed"
    assert ack["success"] is False
    assert ack["result"]["phase"] == "verify"
    assert ack["result"]["error"] == "Config bundle checksum mismatch"


@pytest.mark.asyncio
async def test_duplicate_command_reemits_cached_ack_without_rerunning_handler():
    consumer = _consumer()
    handler = AsyncMock(return_value={"ok": True})
    consumer.register_handler("set_speed", handler)

    first_ack = await consumer.handle_message(_command())
    second_ack = await consumer.handle_message(_command())

    assert second_ack == first_ack
    handler.assert_awaited_once()
    assert consumer._producer.send_and_wait.await_count == 2


@pytest.mark.asyncio
async def test_bytes_payload_is_decoded_and_dispatched():
    consumer = _consumer()
    handler = AsyncMock(return_value={"ok": True})
    consumer.register_handler("set_speed", handler)

    ack = await consumer.handle_message(json.dumps(_command()).encode("utf-8"))

    assert ack["status"] == "completed"
    handler.assert_awaited_once()
