import base64
import hashlib
import io
import json
import zipfile
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from opsgrid_agent.commands import DeferredCommandAck
from opsgrid_agent.ota import AgentSelfUpdateError, AgentSelfUpdateExecutor


ORGANIZATION_ID = "22222222-2222-4222-8222-222222222222"
ASSET_ID = "44444444-4444-4444-8444-444444444444"
COMMAND_ID = "11111111-1111-4111-8111-111111111111"


class EmptyBuffer:
    async def get_stats(self):
        return {"total_messages": 0}


class AckConsumer:
    def __init__(self):
        self.emit_command_ack = AsyncMock()


def _keypair():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, base64.b64encode(public_key).decode("ascii")


def _wheel(version: str = "2.0.0") -> bytes:
    output = io.BytesIO()
    dist_info = f"opsgrid_agent-{version}.dist-info"
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr(
            "opsgrid_agent/__init__.py",
            f'__version__ = "{version}"\n',
        )
        archive.writestr("opsgrid_agent/main.py", "")
        archive.writestr(
            f"{dist_info}/METADATA",
            "Metadata-Version: 2.1\n"
            "Name: opsgrid-agent\n"
            f"Version: {version}\n\n",
        )
        archive.writestr(
            f"{dist_info}/WHEEL",
            "Wheel-Version: 1.0\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n\n",
        )
        archive.writestr(f"{dist_info}/RECORD", "")
    return output.getvalue()


def _command(artifact: bytes, private_key, **parameter_overrides):
    parameters = {
        "release_id": "release-2",
        "target_version": "2.0.0",
        "bundle_url": "https://example.test/agent.whl",
        "checksum_sha256": hashlib.sha256(artifact).hexdigest(),
        "signature_ed25519": base64.b64encode(
            private_key.sign(artifact)
        ).decode("ascii"),
        "artifact_format": "wheel",
        "artifact_filename": "opsgrid_agent-2.0.0-py3-none-any.whl",
        "artifact_size_bytes": len(artifact),
        "package_name": "opsgrid-agent",
        "minimum_bootstrap_version": "1.0.0",
    }
    parameters.update(parameter_overrides)
    return {
        "command_id": COMMAND_ID,
        "agent_id": "agent-1",
        "asset_id": ASSET_ID,
        "organization_id": ORGANIZATION_ID,
        "action_id": "agent_self_update",
        "parameters": parameters,
    }


def _executor(tmp_path, public_key, restart_callback):
    return AgentSelfUpdateExecutor(
        buffer=EmptyBuffer(),
        signing_public_key=public_key,
        runtime_root=str(tmp_path / "runtime"),
        drain_timeout_seconds=0,
        preflight_timeout_seconds=1,
        bootstrap_version="1.0.0",
        restart_callback=restart_callback,
    )


def test_staging_preserves_canonical_wheel_filename(tmp_path):
    _, public_key = _keypair()
    artifact = _wheel()
    executor = _executor(tmp_path, public_key, AsyncMock())
    filename = "opsgrid_agent-2.0.0-py3-none-any.whl"

    staged = executor._stage_artifact(
        artifact,
        release_id="release-2",
        filename=filename,
    )

    assert staged.name == filename
    assert staged.parent.parent == executor.staging_dir
    assert staged.read_bytes() == artifact


@pytest.mark.asyncio
async def test_stages_signed_wheel_and_defers_ack_until_healthy_restart(
    tmp_path,
    monkeypatch,
):
    private_key, public_key = _keypair()
    artifact = _wheel()
    restart_callback = AsyncMock()
    executor = _executor(tmp_path, public_key, restart_callback)
    executor._download_artifact = AsyncMock(return_value=artifact)
    monkeypatch.setenv("OPSGRID_RUNNING_VERSION", "1.0.0")

    def install(_wheel_path, target_version, checksum):
        target = executor.versions_dir / target_version
        target.mkdir(parents=True)
        (target / "install.json").write_text(
            json.dumps(
                {
                    "version": target_version,
                    "checksum_sha256": checksum,
                }
            )
        )
        return target, True

    monkeypatch.setattr(executor, "_install_wheel", install)
    monkeypatch.setattr(executor, "_preflight_installed_version", lambda *_: None)

    outcome = await executor.handle_command(_command(artifact, private_key))

    assert isinstance(outcome, DeferredCommandAck)
    journal = executor.load_journal()
    assert journal["status"] == "switch_requested"
    assert journal["attempted_version"] == "2.0.0"
    assert journal["previous_version"] == "1.0.0"
    assert journal["command"]["parameters"] == {}
    assert "bundle_url" not in json.dumps(journal)

    await outcome.run_after_commit()
    assert executor.load_journal()["status"] == "restart_requested"
    restart_callback.assert_awaited_once()

    journal = executor.load_journal()
    journal["status"] = "booting"
    executor._atomic_write_json(executor.journal_path, journal)
    monkeypatch.setenv("OPSGRID_RUNNING_VERSION", "2.0.0")
    consumer = AckConsumer()

    assert await executor.complete_pending_update(consumer) is True
    consumer.emit_command_ack.assert_awaited_once()
    ack = consumer.emit_command_ack.await_args
    assert ack.kwargs["status"] == "completed"
    assert ack.kwargs["success"] is True
    assert ack.kwargs["result"]["running_version"] == "2.0.0"
    assert ack.kwargs["result"]["rolled_back"] is False
    assert executor.load_journal()["status"] == "completed"


@pytest.mark.asyncio
async def test_previous_version_reports_failed_ack_after_local_rollback(
    tmp_path,
    monkeypatch,
):
    _, public_key = _keypair()
    executor = _executor(tmp_path, public_key, AsyncMock())
    executor._atomic_write_json(
        executor.journal_path,
        {
            "status": "rollback_booting",
            "phase": "health_timeout",
            "release_id": "release-2",
            "attempted_version": "2.0.0",
            "previous_version": "1.0.0",
            "running_version": "1.0.0",
            "rolled_back": True,
            "error": "agent v2 failed its health check",
            "command": {
                "command_id": COMMAND_ID,
                "asset_id": ASSET_ID,
                "organization_id": ORGANIZATION_ID,
                "action_id": "agent_self_update",
                "parameters": {},
            },
        },
    )
    monkeypatch.setenv("OPSGRID_RUNNING_VERSION", "1.0.0")
    consumer = AckConsumer()

    assert await executor.complete_pending_update(consumer) is True

    ack = consumer.emit_command_ack.await_args
    assert ack.kwargs["status"] == "failed"
    assert ack.kwargs["success"] is False
    assert ack.kwargs["result"]["attempted_version"] == "2.0.0"
    assert ack.kwargs["result"]["running_version"] == "1.0.0"
    assert ack.kwargs["result"]["rolled_back"] is True
    assert ack.kwargs["result"]["phase"] == "health_timeout"
    assert executor.load_journal()["status"] == "rolled_back"


@pytest.mark.asyncio
async def test_signature_mismatch_never_creates_switch_journal(tmp_path):
    private_key, public_key = _keypair()
    other_key, _ = _keypair()
    artifact = _wheel()
    executor = _executor(tmp_path, public_key, AsyncMock())
    executor._download_artifact = AsyncMock(return_value=artifact)

    with pytest.raises(AgentSelfUpdateError) as exc_info:
        await executor.handle_command(_command(artifact, other_key))

    assert exc_info.value.phase == "verify"
    assert not executor.journal_path.exists()
    assert not executor.versions_dir.exists()


@pytest.mark.asyncio
async def test_self_update_is_rejected_without_stable_bootstrap(tmp_path):
    private_key, public_key = _keypair()
    artifact = _wheel()
    executor = _executor(tmp_path, public_key, None)

    with pytest.raises(AgentSelfUpdateError) as exc_info:
        await executor.handle_command(_command(artifact, private_key))

    assert exc_info.value.phase == "preflight"
    assert "Bootstrap" in str(exc_info.value)
