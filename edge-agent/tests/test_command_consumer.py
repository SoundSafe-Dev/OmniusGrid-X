import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiokafka import TopicPartition

from opsgrid_agent.commands import CommandConsumer, DeferredCommandAck


COMMAND_ID = "11111111-1111-4111-8111-111111111111"
ORGANIZATION_ID = "22222222-2222-4222-8222-222222222222"
OTHER_ORGANIZATION_ID = "33333333-3333-4333-8333-333333333333"
ASSET_ID = "44444444-4444-4444-8444-444444444444"
SECOND_ASSET_ID = "55555555-5555-4555-8555-555555555555"
OTHER_ASSET_ID = "66666666-6666-4666-8666-666666666666"


class PhasedError(RuntimeError):
    def __init__(self, phase, message):
        self.phase = phase
        super().__init__(message)


def _consumer(**overrides):
    consumer = CommandConsumer(
        agent_id="agent-1",
        organization_id=ORGANIZATION_ID,
        asset_ids={ASSET_ID, SECOND_ASSET_ID},
        redpanda_url="localhost:9092",
        **overrides,
    )
    consumer._producer = AsyncMock()
    return consumer


def _command(**overrides):
    payload = {
        "schema_version": 1,
        "message_type": "command",
        "command_id": COMMAND_ID,
        "asset_id": ASSET_ID,
        "organization_id": ORGANIZATION_ID,
        "action_id": "set_speed",
        "parameters": {"speed": 42},
        "timeout_seconds": 30,
        "timestamp": "2030-01-01T00:00:00Z",
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_dispatches_owned_command_and_emits_tenant_ack():
    consumer = _consumer()
    handler = AsyncMock(return_value={"actual_speed": 42})
    consumer.register_handler("set_speed", handler)

    ack = await consumer.handle_message(_command())

    handler.assert_awaited_once()
    assert handler.await_args.args[0]["parameters"] == {"speed": 42}
    assert ack["command_id"] == COMMAND_ID
    assert ack["agent_id"] == "agent-1"
    assert ack["asset_id"] == ASSET_ID
    assert ack["organization_id"] == ORGANIZATION_ID
    assert ack["status"] == "completed"
    assert ack["success"] is True
    assert ack["result"] == {"actual_speed": 42}
    consumer._producer.send_and_wait.assert_awaited_once_with(
        "opsgrid.commands.acks",
        ack,
        key=COMMAND_ID,
    )


@pytest.mark.asyncio
async def test_dispatches_command_targeted_to_agent_without_asset_ownership():
    consumer = _consumer()
    handler = AsyncMock(return_value={})
    consumer.register_handler("set_speed", handler)

    ack = await consumer.handle_message(
        _command(agent_id="agent-1", asset_id=OTHER_ASSET_ID)
    )

    assert ack["status"] == "completed"
    handler.assert_awaited_once()


@pytest.mark.asyncio
async def test_valid_foreign_commands_are_skipped_without_dlq():
    consumer = _consumer()
    handler = AsyncMock(return_value={})
    consumer.register_handler("set_speed", handler)

    assert await consumer.handle_message(_command(agent_id="agent-2")) is None
    assert await consumer.handle_message(_command(asset_id=OTHER_ASSET_ID)) is None
    assert (
        await consumer.handle_message(
            _command(organization_id=OTHER_ORGANIZATION_ID)
        )
        is None
    )

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


@pytest.mark.parametrize(
    ("payload", "reason"),
    [
        (b"{not-json", "invalid_json"),
        (["not", "an", "object"], "payload_not_object"),
        (_command(message_type="heartbeat"), "unsupported_message_type"),
        (_command(command_id="not-a-uuid"), "invalid_command_id"),
        (_command(organization_id=""), "missing_organization_id"),
        (_command(asset_id="not-a-uuid"), "invalid_asset_id"),
        (_command(parameters=[]), "invalid_parameters"),
    ],
)
@pytest.mark.asyncio
async def test_malformed_commands_are_published_to_dlq(payload, reason):
    consumer = _consumer()

    assert (
        await consumer.handle_message(
            payload,
            source_partition=3,
            source_offset=12,
        )
        is None
    )

    topic, envelope = consumer._producer.send_and_wait.await_args.args[:2]
    assert topic == "opsgrid.commands.dlq"
    assert envelope["message_type"] == "dead_letter"
    assert envelope["reason"] == reason
    assert envelope["source_topic"] == "opsgrid.commands"
    assert envelope["source_partition"] == 3
    assert envelope["source_offset"] == 12
    assert envelope["agent_id"] == "agent-1"
    assert len(envelope["payload_sha256"]) == 64
    assert consumer._producer.send_and_wait.await_args.kwargs["key"]


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


class _OneMessageConsumer:
    def __init__(self, owner: CommandConsumer, message: SimpleNamespace):
        self.owner = owner
        self.message = message
        self.delivered = False
        self.commit = AsyncMock()
        self.seek = Mock()

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self.delivered:
            self.owner._running = False
            raise StopAsyncIteration
        self.delivered = True
        return self.message


@pytest.mark.asyncio
async def test_consumer_commits_exact_offset_after_dlq_publish():
    consumer = _consumer()
    message = SimpleNamespace(
        topic="opsgrid.commands",
        partition=4,
        offset=9,
        value=b"{not-json",
    )
    broker_consumer = _OneMessageConsumer(consumer, message)
    consumer._consumer = broker_consumer
    consumer._running = True

    await consumer._consume_loop()

    broker_consumer.commit.assert_awaited_once_with(
        {TopicPartition(message.topic, message.partition): message.offset + 1}
    )
    broker_consumer.seek.assert_not_called()
    dlq_topic = consumer._producer.send_and_wait.await_args.args[0]
    assert dlq_topic == "opsgrid.commands.dlq"


@pytest.mark.asyncio
async def test_dlq_publish_failure_does_not_commit_source_offset(monkeypatch):
    consumer = _consumer()
    message = SimpleNamespace(
        topic="opsgrid.commands",
        partition=5,
        offset=14,
        value=b"{not-json",
    )
    broker_consumer = _OneMessageConsumer(consumer, message)
    consumer._consumer = broker_consumer
    consumer._running = True

    async def fail_publish(*args, **kwargs):
        consumer._running = False
        raise RuntimeError("DLQ unavailable")

    consumer._producer.send_and_wait = AsyncMock(side_effect=fail_publish)
    sleep = AsyncMock()
    monkeypatch.setattr("opsgrid_agent.commands.consumer.asyncio.sleep", sleep)

    await consumer._consume_loop()

    broker_consumer.commit.assert_not_awaited()
    broker_consumer.seek.assert_called_once_with(
        TopicPartition(message.topic, message.partition),
        message.offset,
    )
    sleep.assert_awaited_once_with(1)


@pytest.mark.asyncio
async def test_deferred_ack_commits_offset_before_restart_callback():
    consumer = _consumer()
    message = SimpleNamespace(
        topic="opsgrid.commands",
        partition=6,
        offset=20,
        value=_command(action_id="agent_self_update"),
    )
    broker_consumer = _OneMessageConsumer(consumer, message)
    consumer._consumer = broker_consumer
    consumer._running = True
    callback_observations = []

    async def after_commit():
        callback_observations.append(broker_consumer.commit.await_count)

    async def handler(_payload):
        return DeferredCommandAck(
            reason="agent_process_restart",
            after_commit=after_commit,
        )

    consumer.register_handler("agent_self_update", handler)

    await consumer._consume_loop()

    broker_consumer.commit.assert_awaited_once_with(
        {TopicPartition(message.topic, message.partition): message.offset + 1}
    )
    assert callback_observations == [1]
    consumer._producer.send_and_wait.assert_not_awaited()


@pytest.mark.asyncio
async def test_deferred_post_commit_action_retries_without_seeking(monkeypatch):
    consumer = _consumer()
    consumer._running = True
    callback = AsyncMock(side_effect=[RuntimeError("restart unavailable"), None])
    sleep = AsyncMock()
    monkeypatch.setattr("opsgrid_agent.commands.consumer.asyncio.sleep", sleep)

    await consumer._run_deferred_after_commit(
        DeferredCommandAck(
            reason="agent_process_restart",
            after_commit=callback,
        ),
        command_offset=20,
    )

    assert callback.await_count == 2
    sleep.assert_awaited_once_with(5)
