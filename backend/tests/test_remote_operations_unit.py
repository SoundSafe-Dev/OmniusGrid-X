from datetime import datetime, timezone
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.db.models import AuditLog, Command
from app.services.command_executor import CommandExecutor, CommandStatus
from app.services.remote_operations import (
    MAX_COMMAND_ACK_BYTES,
    RemoteOperationAuditContext,
    RemoteOperationContractError,
    normalize_remote_ack,
    normalize_remote_parameters,
)


class _Result:
    def __init__(self, command):
        self.command = command

    def scalar_one_or_none(self):
        return self.command


class _Session:
    def __init__(self, command=None):
        self.command = command
        self.added = []
        self.commits = 0

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def get_bind(self):
        return None

    async def execute(self, _query):
        return _Result(self.command)

    def add(self, value):
        self.added.append(value)
        if isinstance(value, Command):
            self.command = value

    async def commit(self):
        self.commits += 1


def _logs_result(*, fields=None):
    return {
        "schema_version": 1,
        "action": "agent_fetch_logs",
        "agent_id": "agent-1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "entries": [
            {
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "level": "error",
                "event": "collector_failed",
                "fields": fields or {},
            }
        ],
        "returned_count": 1,
        "available_count": 1,
        "truncated": False,
        "redacted_fields": 0,
    }


def test_parameter_contract_rejects_path_and_unknown_fields():
    with pytest.raises(RemoteOperationContractError):
        normalize_remote_parameters(
            "agent_fetch_logs",
            {
                "schema_version": 1,
                "limit": 10,
                "path": "/var/log/messages",
            },
        )


def test_backend_redacts_success_result_before_persistence():
    safe_ack, error = normalize_remote_ack(
        "agent_fetch_logs",
        {
            "command_id": str(uuid4()),
            "agent_id": "agent-1",
            "asset_id": str(uuid4()),
            "organization_id": str(uuid4()),
            "status": "completed",
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": _logs_result(
                fields={
                    "password": "do-not-store",
                    "url": "https://example.test/logs?token=secret",
                }
            ),
            "untrusted_extra": "discarded",
        },
        successful=True,
    )

    fields = safe_ack["result"]["entries"][0]["fields"]
    assert fields["password"] == "<redacted>"
    assert "token=secret" not in fields["url"]
    assert safe_ack["result"]["redacted_fields"] >= 2
    assert "untrusted_extra" not in safe_ack
    assert error is None


@pytest.mark.asyncio
async def test_submit_persists_requested_audit_atomically_without_result_content():
    organization_id = uuid4()
    asset_id = uuid4()
    user_id = uuid4()
    session = _Session()
    executor = CommandExecutor()
    executor._broadcast_safely = AsyncMock()

    command_id = await executor.submit_command(
        asset_id=str(asset_id),
        command_type="system",
        action_id="agent_diagnostics",
        parameters={"schema_version": 1},
        issued_by=str(user_id),
        organization_id=str(organization_id),
        remote_audit=RemoteOperationAuditContext(
            ip_address="203.0.113.1",
            user_agent="test",
            target_agent_id="agent-1",
        ),
        db_session=session,
    )

    commands = [item for item in session.added if isinstance(item, Command)]
    audits = [item for item in session.added if isinstance(item, AuditLog)]
    assert len(commands) == 1
    assert len(audits) == 1
    assert str(commands[0].id) == command_id
    assert audits[0].action == "remote_agent_operation_requested"
    assert audits[0].details["target_agent_id"] == "agent-1"
    assert "result" not in audits[0].details
    assert session.commits == 1


@pytest.mark.asyncio
async def test_ack_persists_typed_result_and_one_content_free_terminal_audit():
    organization_id = uuid4()
    asset_id = uuid4()
    command_id = uuid4()
    command = Command(
        id=command_id,
        organization_id=organization_id,
        asset_id=asset_id,
        issued_by=uuid4(),
        command_type="system",
        action_id="agent_fetch_logs",
        parameters={"schema_version": 1, "limit": 1, "levels": []},
        status=CommandStatus.EXECUTING.value,
    )
    session = _Session(command)
    executor = CommandExecutor(session_factory=lambda: session)
    executor._broadcast_safely = AsyncMock()

    handled = await executor.handle_command_ack(
        {
            "command_id": str(command_id),
            "organization_id": str(organization_id),
            "asset_id": str(asset_id),
            "agent_id": "agent-1",
            "status": "completed",
            "success": True,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "result": _logs_result(fields={"token": "edge-secret"}),
        }
    )

    audits = [item for item in session.added if isinstance(item, AuditLog)]
    assert handled is True
    assert command.status == CommandStatus.COMPLETED.value
    assert (
        command.result["edge_ack"]["result"]["entries"][0]["fields"]["token"]
        == "<redacted>"
    )
    assert len(audits) == 1
    assert audits[0].action == "remote_agent_operation_completed"
    assert "entries" not in str(audits[0].details)
    executor._broadcast_safely.assert_awaited_once()


@pytest.mark.asyncio
async def test_oversized_ack_is_rejected_before_database_lookup():
    session = _Session()
    executor = CommandExecutor(session_factory=lambda: session)

    handled = await executor.handle_command_ack(
        {
            "command_id": str(uuid4()),
            "status": "completed",
            "success": True,
            "result": {"value": "x" * MAX_COMMAND_ACK_BYTES},
        }
    )

    assert handled is False
    assert session.commits == 0
