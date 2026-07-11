import base64
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from opsgrid_agent.ota import OTAUpdateError, OTAUpdateExecutor


class FakeBuffer:
    def __init__(self, counts=None):
        self.counts = list(counts or [0])

    async def get_stats(self):
        count = self.counts.pop(0) if self.counts else 0
        return {"total_messages": count}


def _keypair():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, base64.b64encode(public_key).decode("ascii")


def _signature(private_key, bundle):
    return base64.b64encode(private_key.sign(bundle)).decode("ascii")


def _checksum(bundle):
    return hashlib.sha256(bundle).hexdigest()


def _command(bundle, private_key, **overrides):
    params = {
        "release_id": "rel-1",
        "target_version": "1.2.3",
        "bundle_url": "https://example.test/bundles/rel-1",
        "checksum_sha256": _checksum(bundle),
        "signature_ed25519": _signature(private_key, bundle),
    }
    params.update(overrides)
    return {"command_id": "cmd-1", "parameters": params}


def _executor(tmp_path, public_key, **overrides):
    kwargs = {
        "buffer": FakeBuffer(),
        "signing_public_key": public_key,
        "active_bundle_path": str(tmp_path / "config_bundle.active"),
        "staging_dir": str(tmp_path / "staging"),
        "drain_timeout_seconds": 1,
        "restart_callback": AsyncMock(),
    }
    kwargs.update(overrides)
    return OTAUpdateExecutor(**kwargs)


@pytest.mark.asyncio
async def test_applies_verified_bundle_and_restarts_runtime(tmp_path):
    private_key, public_key = _keypair()
    old_bundle = b"old-config"
    new_bundle = b"new-config"
    active_path = tmp_path / "config_bundle.active"
    active_path.write_bytes(old_bundle)
    restart_callback = AsyncMock()
    executor = _executor(
        tmp_path,
        public_key,
        restart_callback=restart_callback,
    )
    executor._download_bundle = AsyncMock(return_value=new_bundle)

    result = await executor.handle_command(_command(new_bundle, private_key))

    assert result["release_id"] == "rel-1"
    assert result["new_version"] == "1.2.3"
    assert result["previous_bundle_available"] is True
    assert Path(result["active_bundle_path"]).read_bytes() == new_bundle
    assert executor.previous_bundle_path.read_bytes() == old_bundle
    restart_callback.assert_awaited_once()
    assert not list((tmp_path / "staging").glob("*"))


@pytest.mark.asyncio
async def test_checksum_mismatch_aborts_before_apply(tmp_path):
    private_key, public_key = _keypair()
    old_bundle = b"old-config"
    new_bundle = b"new-config"
    active_path = tmp_path / "config_bundle.active"
    active_path.write_bytes(old_bundle)
    restart_callback = AsyncMock()
    executor = _executor(
        tmp_path,
        public_key,
        restart_callback=restart_callback,
    )
    executor._download_bundle = AsyncMock(return_value=new_bundle)

    with pytest.raises(OTAUpdateError) as excinfo:
        await executor.handle_command(
            _command(new_bundle, private_key, checksum_sha256="0" * 64)
        )

    assert excinfo.value.phase == "verify"
    assert active_path.read_bytes() == old_bundle
    assert not executor.previous_bundle_path.exists()
    restart_callback.assert_not_awaited()


@pytest.mark.asyncio
async def test_signature_mismatch_aborts_before_apply(tmp_path):
    private_key, public_key = _keypair()
    other_private_key, _ = _keypair()
    old_bundle = b"old-config"
    new_bundle = b"new-config"
    active_path = tmp_path / "config_bundle.active"
    active_path.write_bytes(old_bundle)
    executor = _executor(tmp_path, public_key)
    executor._download_bundle = AsyncMock(return_value=new_bundle)

    with pytest.raises(OTAUpdateError) as excinfo:
        await executor.handle_command(_command(new_bundle, other_private_key))

    assert excinfo.value.phase == "verify"
    assert active_path.read_bytes() == old_bundle


@pytest.mark.asyncio
async def test_bundle_validation_failure_aborts_before_apply(tmp_path):
    private_key, public_key = _keypair()
    old_bundle = b"old-config"
    new_bundle = b"new-config"
    active_path = tmp_path / "config_bundle.active"
    active_path.write_bytes(old_bundle)

    def validate_bundle(_bundle):
        raise ValueError("missing collectors")

    executor = _executor(
        tmp_path,
        public_key,
        bundle_validator=validate_bundle,
    )
    executor._download_bundle = AsyncMock(return_value=new_bundle)

    with pytest.raises(OTAUpdateError) as excinfo:
        await executor.handle_command(_command(new_bundle, private_key))

    assert excinfo.value.phase == "verify"
    assert "missing collectors" in str(excinfo.value)
    assert active_path.read_bytes() == old_bundle


@pytest.mark.asyncio
async def test_buffer_drain_timeout_aborts_before_apply(tmp_path):
    private_key, public_key = _keypair()
    old_bundle = b"old-config"
    new_bundle = b"new-config"
    active_path = tmp_path / "config_bundle.active"
    active_path.write_bytes(old_bundle)
    executor = _executor(
        tmp_path,
        public_key,
        buffer=FakeBuffer([1]),
        drain_timeout_seconds=0,
    )
    executor._download_bundle = AsyncMock(return_value=new_bundle)

    with pytest.raises(OTAUpdateError) as excinfo:
        await executor.handle_command(_command(new_bundle, private_key))

    assert excinfo.value.phase == "drain"
    assert active_path.read_bytes() == old_bundle


@pytest.mark.asyncio
async def test_restart_failure_rolls_back_applied_bundle(tmp_path):
    private_key, public_key = _keypair()
    old_bundle = b"old-config"
    new_bundle = b"new-config"
    active_path = tmp_path / "config_bundle.active"
    active_path.write_bytes(old_bundle)

    async def restart_callback():
        raise RuntimeError("collector restart failed")

    executor = _executor(
        tmp_path,
        public_key,
        restart_callback=restart_callback,
    )
    executor._download_bundle = AsyncMock(return_value=new_bundle)

    with pytest.raises(OTAUpdateError) as excinfo:
        await executor.handle_command(_command(new_bundle, private_key))

    assert excinfo.value.phase == "restart"
    assert active_path.read_bytes() == old_bundle


@pytest.mark.asyncio
async def test_rejects_concurrent_update(tmp_path):
    private_key, public_key = _keypair()
    bundle = b"new-config"
    executor = _executor(tmp_path, public_key)

    await executor._lock.acquire()
    try:
        with pytest.raises(OTAUpdateError) as excinfo:
            await executor.handle_command(_command(bundle, private_key))
    finally:
        executor._lock.release()

    assert excinfo.value.phase == "preflight"
