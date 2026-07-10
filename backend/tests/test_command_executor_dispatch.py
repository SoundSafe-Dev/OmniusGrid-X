from datetime import datetime, timedelta
from unittest.mock import AsyncMock

import pytest

from app.core.config import settings
from app.services.command_executor import (
    CommandExecutor,
    CommandResult,
    CommandStatus,
)


def _command_info(**overrides):
    info = {
        "command_id": "cmd-123",
        "asset_id": "asset-1",
        "organization_id": "org-1",
        "command_type": "operator",
        "action_id": "set_speed",
        "parameters": {"speed": 42},
        "timeout": 30,
        "retry_count": 0,
        "submitted_at": datetime.utcnow(),
    }
    info.update(overrides)
    return info


@pytest.mark.asyncio
async def test_send_to_edge_agent_publishes_command_envelope(monkeypatch):
    executor = CommandExecutor()
    producer = AsyncMock()
    executor._producer = producer
    monkeypatch.setattr(settings, "REDPANDA_COMMAND_TOPIC", "opsgrid.commands")
    monkeypatch.setattr(settings, "REDPANDA_COMMAND_ACK_TOPIC", "opsgrid.commands.acks")

    result = await executor._send_to_edge_agent(
        command_id="cmd-123",
        asset_id="asset-1",
        organization_id="org-1",
        action_id="set_speed",
        parameters={"speed": 42},
        timeout_seconds=30,
    )

    assert result.success is True
    producer.send_and_wait.assert_awaited_once()
    topic, payload = producer.send_and_wait.await_args.args[:2]
    assert topic == "opsgrid.commands"
    assert producer.send_and_wait.await_args.kwargs["key"] == b"cmd-123"
    assert payload["schema_version"] == 1
    assert payload["message_type"] == "command"
    assert payload["command_id"] == "cmd-123"
    assert payload["asset_id"] == "asset-1"
    assert payload["organization_id"] == "org-1"
    assert payload["action_id"] == "set_speed"
    assert payload["parameters"] == {"speed": 42}
    assert payload["timeout_seconds"] == 30
    assert result.data["topic"] == "opsgrid.commands"
    assert result.data["ack_topic"] == "opsgrid.commands.acks"


@pytest.mark.asyncio
async def test_execute_command_dispatches_and_leaves_pending_until_ack():
    executor = CommandExecutor()
    command_info = _command_info()
    executor._pending_commands[command_info["command_id"]] = command_info
    executor._send_to_edge_agent = AsyncMock(
        return_value=CommandResult(
            success=True,
            message="sent",
            data={"topic": "opsgrid.commands"},
        )
    )
    executor._update_command_status = AsyncMock()
    executor._broadcast_command_status = AsyncMock()

    await executor._execute_command(command_info)

    executor._send_to_edge_agent.assert_awaited_once_with(
        command_id="cmd-123",
        asset_id="asset-1",
        organization_id="org-1",
        action_id="set_speed",
        parameters={"speed": 42},
        timeout_seconds=30,
    )
    status_updates = [
        call.args[1] for call in executor._update_command_status.await_args_list
    ]
    assert status_updates == [CommandStatus.EXECUTING, CommandStatus.EXECUTING]
    assert "cmd-123" in executor._pending_commands


@pytest.mark.asyncio
async def test_handle_success_ack_completes_command_and_removes_pending():
    executor = CommandExecutor()
    executor._pending_commands["cmd-123"] = _command_info()
    executor._update_command_status = AsyncMock()
    executor._broadcast_command_status = AsyncMock()

    handled = await executor.handle_command_ack(
        {
            "command_id": "cmd-123",
            "status": "completed",
            "success": True,
            "message": "done",
            "data": {"actual_speed": 42},
        }
    )

    assert handled is True
    executor._update_command_status.assert_awaited_once()
    command_id, status = executor._update_command_status.await_args.args[:2]
    result = executor._update_command_status.await_args.kwargs["result"]
    assert command_id == "cmd-123"
    assert status == CommandStatus.COMPLETED
    assert result["edge_ack"]["data"] == {"actual_speed": 42}
    executor._broadcast_command_status.assert_awaited_once()
    assert executor._broadcast_command_status.await_args.args[3] == CommandStatus.COMPLETED
    assert "cmd-123" not in executor._pending_commands


@pytest.mark.asyncio
async def test_handle_failure_ack_fails_command_and_removes_pending():
    executor = CommandExecutor()
    executor._pending_commands["cmd-123"] = _command_info()
    executor._update_command_status = AsyncMock()
    executor._broadcast_command_status = AsyncMock()

    handled = await executor.handle_command_ack(
        {
            "command_id": "cmd-123",
            "status": "failed",
            "success": False,
            "error": "PLC rejected command",
        }
    )

    assert handled is True
    command_id, status = executor._update_command_status.await_args.args[:2]
    result = executor._update_command_status.await_args.kwargs["result"]
    assert command_id == "cmd-123"
    assert status == CommandStatus.FAILED
    assert result["error"] == "PLC rejected command"
    assert executor._broadcast_command_status.await_args.args[3] == CommandStatus.FAILED
    assert executor._broadcast_command_status.await_args.kwargs["error"] == "PLC rejected command"
    assert "cmd-123" not in executor._pending_commands


@pytest.mark.asyncio
async def test_unknown_or_malformed_ack_is_ignored():
    executor = CommandExecutor()
    executor._update_command_status = AsyncMock()

    assert await executor.handle_command_ack({"status": "completed"}) is False
    assert await executor.handle_command_ack({"command_id": "missing"}) is False
    executor._update_command_status.assert_not_awaited()


@pytest.mark.asyncio
async def test_mark_command_timeout_updates_broadcasts_and_removes_pending():
    executor = CommandExecutor()
    executor._pending_commands["cmd-123"] = _command_info()
    executor._update_command_status = AsyncMock()
    executor._broadcast_command_status = AsyncMock()
    now = datetime.utcnow() + timedelta(seconds=31)

    await executor._mark_command_timeout("cmd-123", now)

    command_id, status = executor._update_command_status.await_args.args[:2]
    result = executor._update_command_status.await_args.kwargs["result"]
    assert command_id == "cmd-123"
    assert status == CommandStatus.TIMEOUT
    assert result["timeout_at"] == now.isoformat()
    assert executor._broadcast_command_status.await_args.args[3] == CommandStatus.TIMEOUT
    assert "cmd-123" not in executor._pending_commands


@pytest.mark.asyncio
async def test_publish_failure_requeues_with_backoff(monkeypatch):
    executor = CommandExecutor()
    command_info = _command_info()
    executor._pending_commands["cmd-123"] = command_info
    executor._send_to_edge_agent = AsyncMock(
        return_value=CommandResult(
            success=False,
            message="broker unavailable",
            error_code="SEND_FAILED",
        )
    )
    executor._update_command_status = AsyncMock()
    executor._broadcast_command_status = AsyncMock()
    sleep = AsyncMock()
    monkeypatch.setattr("app.services.command_executor.asyncio.sleep", sleep)

    await executor._execute_command(command_info)

    sleep.assert_awaited_once_with(2)
    requeued = await executor._command_queue.get()
    assert requeued["command_id"] == "cmd-123"
    assert requeued["retry_count"] == 1
    assert "cmd-123" not in executor._pending_commands
    status_updates = [
        call.args[1] for call in executor._update_command_status.await_args_list
    ]
    assert status_updates == [CommandStatus.EXECUTING]


@pytest.mark.asyncio
async def test_publish_failure_after_retry_budget_marks_failed():
    executor = CommandExecutor()
    command_info = _command_info(retry_count=2)
    executor._pending_commands["cmd-123"] = command_info
    executor._send_to_edge_agent = AsyncMock(
        return_value=CommandResult(
            success=False,
            message="broker unavailable",
            error_code="SEND_FAILED",
        )
    )
    executor._update_command_status = AsyncMock()
    executor._broadcast_command_status = AsyncMock()

    await executor._execute_command(command_info)

    assert executor._command_queue.empty()
    assert "cmd-123" not in executor._pending_commands
    command_id, status = executor._update_command_status.await_args.args[:2]
    result = executor._update_command_status.await_args.kwargs["result"]
    assert command_id == "cmd-123"
    assert status == CommandStatus.FAILED
    assert result["error"] == "broker unavailable"
