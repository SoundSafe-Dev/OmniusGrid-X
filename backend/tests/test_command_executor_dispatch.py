import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from aiokafka import TopicPartition
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.core.config import settings
from app.db.models import (
    Asset,
    AssetType,
    Base,
    Command,
    Organization,
    User,
    Workcell,
)
from app.services.command_executor import CommandExecutor, CommandStatus


@pytest_asyncio.fixture
async def command_db(tmp_path: Path):
    engine = create_async_engine(f"sqlite+aiosqlite:///{tmp_path / 'commands.db'}")
    sessions = async_sessionmaker(engine, expire_on_commit=False, autoflush=False)
    tables = [
        Organization.__table__,
        AssetType.__table__,
        Workcell.__table__,
        Asset.__table__,
        User.__table__,
        Command.__table__,
    ]

    async with engine.begin() as connection:
        await connection.run_sync(
            lambda sync_connection: Base.metadata.create_all(
                sync_connection,
                tables=tables,
            )
        )

    organization_id = uuid4()
    asset_type_id = uuid4()
    workcell_id = uuid4()
    asset_id = uuid4()
    async with sessions() as session:
        session.add_all(
            [
                Organization(
                    id=organization_id,
                    name="Command Test Organization",
                    slug=f"command-test-{organization_id.hex[:8]}",
                ),
                AssetType(
                    id=asset_type_id,
                    name="Test Asset",
                    category="test",
                ),
                Workcell(
                    id=workcell_id,
                    organization_id=organization_id,
                    name="Test Workcell",
                ),
                Asset(
                    id=asset_id,
                    organization_id=organization_id,
                    workcell_id=workcell_id,
                    asset_type_id=asset_type_id,
                    name="Test Asset",
                ),
            ]
        )
        await session.commit()

    try:
        yield {
            "sessions": sessions,
            "organization_id": organization_id,
            "asset_id": asset_id,
        }
    finally:
        await engine.dispose()


def _executor(command_db) -> CommandExecutor:
    executor = CommandExecutor(session_factory=command_db["sessions"])
    executor._broadcast_safely = AsyncMock()
    return executor


async def _submit(executor: CommandExecutor, command_db, **overrides) -> str:
    values = {
        "asset_id": str(command_db["asset_id"]),
        "organization_id": str(command_db["organization_id"]),
        "command_type": "operator",
        "action_id": "set_speed",
        "parameters": {"speed": 42},
        "timeout_seconds": 30,
    }
    values.update(overrides)
    return await executor.submit_command(**values)


async def _load_command(command_db, command_id: str) -> Command:
    async with command_db["sessions"]() as session:
        return (
            await session.execute(
                select(Command).where(Command.id == UUID(command_id))
            )
        ).scalar_one()


@pytest.mark.asyncio
async def test_send_to_edge_agent_publishes_uuid_command_envelope(
    monkeypatch,
    command_db,
):
    executor = _executor(command_db)
    producer = AsyncMock()
    executor._producer = producer
    command_id = str(uuid4())
    monkeypatch.setattr(settings, "REDPANDA_COMMAND_TOPIC", "opsgrid.commands")
    monkeypatch.setattr(settings, "REDPANDA_COMMAND_ACK_TOPIC", "opsgrid.commands.acks")

    result = await executor._send_to_edge_agent(
        command_id=command_id,
        asset_id=str(command_db["asset_id"]),
        organization_id=str(command_db["organization_id"]),
        action_id="set_speed",
        parameters={"speed": 42},
        timeout_seconds=30,
    )

    assert result.success is True
    topic, payload = producer.send_and_wait.await_args.args[:2]
    assert topic == "opsgrid.commands"
    assert producer.send_and_wait.await_args.kwargs["key"] == command_id.encode()
    assert payload == {
        "schema_version": 1,
        "message_type": "command",
        "command_id": command_id,
        "asset_id": str(command_db["asset_id"]),
        "organization_id": str(command_db["organization_id"]),
        "action_id": "set_speed",
        "parameters": {"speed": 42},
        "timeout_seconds": 30,
        "timestamp": payload["timestamp"],
    }
    assert result.data["ack_topic"] == "opsgrid.commands.acks"


@pytest.mark.asyncio
async def test_submit_uses_unique_uuid_and_persists_tenant(command_db):
    executor = _executor(command_db)

    first_id = await _submit(executor, command_db)
    second_id = await _submit(executor, command_db)

    assert UUID(first_id) != UUID(second_id)
    first = await _load_command(command_db, first_id)
    assert first.organization_id == command_db["organization_id"]
    assert first.asset_id == command_db["asset_id"]
    assert first.status == CommandStatus.PENDING.value
    assert first.timeout_seconds == 30
    assert first.dispatch_attempts == 0


@pytest.mark.asyncio
async def test_new_executor_replica_dispatches_db_pending_command(command_db):
    submitting_replica = _executor(command_db)
    command_id = await _submit(submitting_replica, command_db)

    worker_after_restart = _executor(command_db)
    worker_after_restart._producer = AsyncMock()
    assert await worker_after_restart.dispatch_pending() == 1

    command = await _load_command(command_db, command_id)
    assert command.status == CommandStatus.EXECUTING.value
    assert command.dispatch_attempts == 1
    assert command.dispatched_at is not None
    assert command.deadline_at is not None
    sent_payload = worker_after_restart._producer.send_and_wait.await_args.args[1]
    assert sent_payload["command_id"] == command_id


@pytest.mark.asyncio
async def test_publish_failure_is_retried_from_db_after_restart(command_db):
    first_worker = _executor(command_db)
    command_id = await _submit(first_worker, command_db)
    first_worker._producer = AsyncMock()
    first_worker._producer.send_and_wait.side_effect = RuntimeError(
        "broker unavailable"
    )

    assert await first_worker.dispatch_pending() == 1
    command = await _load_command(command_db, command_id)
    assert command.status == CommandStatus.PENDING.value
    assert command.dispatch_attempts == 1
    assert "broker unavailable" in command.last_dispatch_error

    async with command_db["sessions"]() as session:
        command = (
            await session.execute(
                select(Command).where(Command.id == UUID(command_id))
            )
        ).scalar_one()
        command.next_dispatch_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

    worker_after_restart = _executor(command_db)
    worker_after_restart._producer = AsyncMock()
    assert await worker_after_restart.dispatch_pending() == 1

    command = await _load_command(command_db, command_id)
    assert command.status == CommandStatus.EXECUTING.value
    assert command.dispatch_attempts == 2
    assert command.last_dispatch_error is None
    assert command.error_message is None


@pytest.mark.asyncio
async def test_second_replica_reconciles_ack_from_database(command_db):
    first_replica = _executor(command_db)
    command_id = await _submit(first_replica, command_db)
    first_replica._producer = AsyncMock()
    await first_replica.dispatch_pending()

    second_replica = _executor(command_db)
    handled = await second_replica.handle_command_ack(
        {
            "command_id": command_id,
            "organization_id": str(command_db["organization_id"]),
            "asset_id": str(command_db["asset_id"]),
            "status": "completed",
            "success": True,
            "result": {"actual_speed": 42},
        }
    )

    assert handled is True
    command = await _load_command(command_db, command_id)
    assert command.status == CommandStatus.COMPLETED.value
    assert command.result["edge_ack"]["result"] == {"actual_speed": 42}
    second_replica._broadcast_safely.assert_awaited_once()


@pytest.mark.asyncio
async def test_duplicate_terminal_ack_is_idempotent(command_db):
    executor = _executor(command_db)
    command_id = await _submit(executor, command_db)
    ack = {
        "command_id": command_id,
        "organization_id": str(command_db["organization_id"]),
        "asset_id": str(command_db["asset_id"]),
        "status": "completed",
        "success": True,
        "result": {"attempt": 1},
    }

    assert await executor.handle_command_ack(ack) is True
    executor._broadcast_safely.reset_mock()
    assert await executor.handle_command_ack(ack) is True

    command = await _load_command(command_db, command_id)
    assert command.status == CommandStatus.COMPLETED.value
    assert command.result["edge_ack"]["result"] == {"attempt": 1}
    executor._broadcast_safely.assert_not_awaited()


@pytest.mark.asyncio
async def test_ack_with_wrong_asset_does_not_resolve_command(command_db):
    executor = _executor(command_db)
    command_id = await _submit(executor, command_db)

    handled = await executor.handle_command_ack(
        {
            "command_id": command_id,
            "organization_id": str(command_db["organization_id"]),
            "asset_id": str(uuid4()),
            "status": "completed",
            "success": True,
        }
    )

    assert handled is False
    assert (await _load_command(command_db, command_id)).status == "pending"


@pytest.mark.asyncio
async def test_contradictory_ack_does_not_resolve_command(command_db):
    executor = _executor(command_db)
    command_id = await _submit(executor, command_db)

    handled = await executor.handle_command_ack(
        {
            "command_id": command_id,
            "organization_id": str(command_db["organization_id"]),
            "asset_id": str(command_db["asset_id"]),
            "status": "completed",
            "success": False,
        }
    )

    assert handled is False
    assert (await _load_command(command_db, command_id)).status == "pending"


@pytest.mark.asyncio
async def test_cancel_wins_over_late_ack(command_db):
    executor = _executor(command_db)
    command_id = await _submit(executor, command_db)

    assert await executor.cancel_command(
        command_id,
        cancelled_by=str(uuid4()),
        organization_id=str(command_db["organization_id"]),
    )
    assert await executor.handle_command_ack(
        {
            "command_id": command_id,
            "organization_id": str(command_db["organization_id"]),
            "asset_id": str(command_db["asset_id"]),
            "status": "completed",
            "success": True,
        }
    )

    command = await _load_command(command_db, command_id)
    assert command.status == CommandStatus.CANCELLED.value
    assert command.result["cancelled_by"]


@pytest.mark.asyncio
async def test_restart_expires_durable_executing_deadline(command_db):
    executor = _executor(command_db)
    command_id = await _submit(executor, command_db)
    async with command_db["sessions"]() as session:
        command = (
            await session.execute(
                select(Command).where(Command.id == UUID(command_id))
            )
        ).scalar_one()
        command.status = CommandStatus.EXECUTING.value
        command.dispatched_at = datetime.now(timezone.utc) - timedelta(minutes=2)
        command.deadline_at = datetime.now(timezone.utc) - timedelta(seconds=1)
        await session.commit()

    executor_after_restart = _executor(command_db)
    assert await executor_after_restart.expire_timed_out() == 1

    command = await _load_command(command_db, command_id)
    assert command.status == CommandStatus.TIMEOUT.value
    assert command.error_message == "Command acknowledgement timed out"


class _OneMessageConsumer:
    def __init__(self, owner: CommandExecutor, message: SimpleNamespace):
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
async def test_ack_consumer_dead_letters_malformed_then_commits_exact_offset(
    command_db,
):
    executor = _executor(command_db)
    message = SimpleNamespace(
        topic="opsgrid.commands.acks",
        partition=2,
        offset=7,
        value=b"{not-json",
    )
    consumer = _OneMessageConsumer(executor, message)
    executor._ack_consumer = consumer
    executor._running = True
    executor._ensure_ack_consumer = AsyncMock(return_value=True)
    executor._publish_dead_letter = AsyncMock()

    await executor._ack_consumer_loop()

    executor._publish_dead_letter.assert_awaited_once()
    consumer.commit.assert_awaited_once_with(
        {TopicPartition(message.topic, message.partition): message.offset + 1}
    )
    consumer.seek.assert_not_called()


@pytest.mark.asyncio
async def test_ack_dlq_failure_leaves_offset_uncommitted(
    monkeypatch,
    command_db,
):
    executor = _executor(command_db)
    message = SimpleNamespace(
        topic="opsgrid.commands.acks",
        partition=1,
        offset=4,
        value=json.dumps({"not": "an ack"}).encode(),
    )
    consumer = _OneMessageConsumer(executor, message)
    executor._ack_consumer = consumer
    executor._running = True
    executor._ensure_ack_consumer = AsyncMock(return_value=True)

    async def fail_dead_letter(*args, **kwargs):
        executor._running = False
        raise RuntimeError("DLQ unavailable")

    executor._publish_dead_letter = AsyncMock(side_effect=fail_dead_letter)
    sleep = AsyncMock()
    monkeypatch.setattr("app.services.command_executor.asyncio.sleep", sleep)

    await executor._ack_consumer_loop()

    consumer.commit.assert_not_awaited()
    consumer.seek.assert_called_once_with(
        TopicPartition(message.topic, message.partition),
        message.offset,
    )
    sleep.assert_awaited_once_with(1)
