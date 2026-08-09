from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.models import Command
from app.services.command_executor import CommandExecutor, CommandStatus


class _Result:
    def __init__(self, command):
        self.command = command

    def scalar_one_or_none(self):
        return self.command


class _Session:
    def __init__(self, command):
        self.command = command
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get_bind(self):
        return None

    async def execute(self, _query):
        return _Result(self.command)

    async def commit(self):
        self.commits += 1


@pytest.mark.asyncio
async def test_corrective_rollback_ack_overwrites_completed_self_update():
    organization_id = uuid4()
    asset_id = uuid4()
    command_id = uuid4()
    command = Command(
        id=command_id,
        organization_id=organization_id,
        asset_id=asset_id,
        command_type="system",
        action_id="agent_self_update",
        parameters={},
        status=CommandStatus.COMPLETED.value,
        result={"edge_ack": {"status": "completed"}},
    )
    session = _Session(command)
    executor = CommandExecutor(session_factory=lambda: session)
    executor._broadcast_safely = AsyncMock()

    handled = await executor.handle_command_ack(
        {
            "command_id": str(command_id),
            "organization_id": str(organization_id),
            "asset_id": str(asset_id),
            "status": "failed",
            "success": False,
            "error": "candidate exited before ready marker",
            "result": {
                "attempted_version": "2.0.0",
                "running_version": "1.0.0",
                "rolled_back": True,
                "phase": "process_exit",
            },
        }
    )

    assert handled is True
    assert session.commits == 1
    assert command.status == CommandStatus.FAILED.value
    assert command.result["edge_ack"]["result"]["rolled_back"] is True
    assert command.result["edge_ack"]["result"]["running_version"] == "1.0.0"
    executor._broadcast_safely.assert_awaited_once()
