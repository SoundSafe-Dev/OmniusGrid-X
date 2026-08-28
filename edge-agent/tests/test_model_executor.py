"""The model-update executor, which was fully written and never tested.

WHY THIS FILE EXISTS NOW. `ModelUpdateExecutor` is 220 lines that download, verify,
hot-swap and roll back a model artifact, and until 2026-08-28 nothing exercised any of
it. That was recorded rather than fixed because the class was also never *wired*:
`register()` is what binds `model_update`, `main.py` never constructed the class, so the
agent answered `unknown_action` to every model rollout the cloud dispatched. Two
registers held the pair — `edge-agent/tests/test_no_new_unreachable_modules.py` and
`backend/tests/test_dispatched_commands_have_a_handler.py` — and both deferred to the OTA
lane's owner, who has since left the company.

Both also cited this gap as "(FS-507)", which it is not: FS-507 is the HTTP-collector
slice (`docs/DELIVERY-LOG.md:5938`). The number was picked up from the paragraph next to
it and copied into three files. Corrected where it appeared, and worth naming because a
wrong reference costs more than a missing one — it sends the reader somewhere plausible.

So the deferral became a decision, and the order matters: **an untested handler must not
be switched into the live command path.** These tests come first; the wiring in
`main.py` is what they make safe.

The properties worth pinning are the destructive ones. A model update replaces the file
the inference engine reads, in place, on a device that may be at the end of a satellite
link. The interesting question is never "does the happy path work" — it is *what is on
disk when the update fails halfway*, because that is the state the device runs in until
someone drives to it.
"""

import asyncio
import base64
import hashlib
from pathlib import Path
from unittest.mock import AsyncMock

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from opsgrid_agent.ota.model_executor import ModelUpdateError, ModelUpdateExecutor


def _keypair():
    private_key = Ed25519PrivateKey.generate()
    public_key = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )
    return private_key, base64.b64encode(public_key).decode("ascii")


def _signature(private_key, artifact):
    return base64.b64encode(private_key.sign(artifact)).decode("ascii")


def _command(artifact, private_key, **overrides):
    """The payload as `rollout_orchestrator._dispatch` actually builds it.

    The six keys below are exactly what the cloud sends for `artifact_type == "model"`
    (`backend/app/services/rollout_orchestrator.py`), and `_required` rejects any of them
    being absent. Keeping the shape honest here is what makes the wiring safe: a handler
    that registers for an action whose payload it cannot parse turns `unknown_action`
    into `Missing update parameter`, which is a different message for the same failed
    rollout.
    """
    params = {
        "release_id": "rel-1",
        "model_name": "defect-classifier",
        "target_version": "4.1.0",
        "bundle_url": "https://example.test/bundles/rel-1",
        "checksum_sha256": hashlib.sha256(artifact).hexdigest(),
        "signature_ed25519": _signature(private_key, artifact),
    }
    params.update(overrides)
    return {"command_id": "cmd-1", "parameters": params}


def _executor(tmp_path, public_key, **overrides):
    kwargs = {
        "signing_public_key": public_key,
        "active_model_path": str(tmp_path / "model.pt"),
        "staging_dir": str(tmp_path / "staging"),
        "swap_callback": AsyncMock(),
    }
    kwargs.update(overrides)
    return ModelUpdateExecutor(**kwargs)


class TestTheUpdateApplies:
    @pytest.mark.asyncio
    async def test_a_verified_artifact_replaces_the_active_model(self, tmp_path):
        private_key, public_key = _keypair()
        new_model = b"new-model-weights"
        active = tmp_path / "model.pt"
        active.write_bytes(b"old-model-weights")
        swap = AsyncMock()
        executor = _executor(tmp_path, public_key, swap_callback=swap)
        executor._download = AsyncMock(return_value=new_model)

        result = await executor.handle_command(_command(new_model, private_key))

        assert active.read_bytes() == new_model
        assert executor.previous_model_path.read_bytes() == b"old-model-weights"
        assert result["new_model_version"] == "4.1.0"
        assert result["model_name"] == "defect-classifier"
        assert result["previous_model_available"] is True
        swap.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_the_staging_directory_is_left_empty(self, tmp_path):
        """A staged artifact that outlives the update fills the device's disk one
        release at a time, and an edge device is the worst place to discover that."""
        private_key, public_key = _keypair()
        new_model = b"new-model-weights"
        executor = _executor(tmp_path, public_key)
        executor._download = AsyncMock(return_value=new_model)

        await executor.handle_command(_command(new_model, private_key))

        assert list((tmp_path / "staging").glob("*")) == []

    @pytest.mark.asyncio
    async def test_a_first_install_reports_no_previous_model(self, tmp_path):
        """`previous_model_available` is what tells the cloud whether this device can be
        rolled back at all — reporting True with nothing to roll back to would make a
        recovery plan that cannot run."""
        private_key, public_key = _keypair()
        new_model = b"first-model"
        executor = _executor(tmp_path, public_key)
        executor._download = AsyncMock(return_value=new_model)

        result = await executor.handle_command(_command(new_model, private_key))

        assert result["previous_model_available"] is False


class TestNothingUnverifiedReachesTheEngine:
    @pytest.mark.asyncio
    async def test_a_checksum_mismatch_leaves_the_active_model_untouched(self, tmp_path):
        private_key, public_key = _keypair()
        active = tmp_path / "model.pt"
        active.write_bytes(b"old-model-weights")
        swap = AsyncMock()
        executor = _executor(tmp_path, public_key, swap_callback=swap)
        executor._download = AsyncMock(return_value=b"corrupted-in-transit")

        with pytest.raises(ModelUpdateError) as excinfo:
            await executor.handle_command(
                _command(b"corrupted-in-transit", private_key, checksum_sha256="0" * 64)
            )

        assert excinfo.value.phase == "verify"
        assert active.read_bytes() == b"old-model-weights"
        swap.assert_not_awaited()

    @pytest.mark.asyncio
    async def test_a_signature_from_the_wrong_key_is_refused(self, tmp_path):
        """The checksum proves the bytes arrived intact. Only the signature proves they
        came from us — an attacker who can influence `bundle_url` controls both the
        artifact and the checksum computed over it."""
        _, public_key = _keypair()
        attacker_key, _ = _keypair()
        active = tmp_path / "model.pt"
        active.write_bytes(b"old-model-weights")
        executor = _executor(tmp_path, public_key)
        executor._download = AsyncMock(return_value=b"attacker-model")

        with pytest.raises(ModelUpdateError) as excinfo:
            await executor.handle_command(_command(b"attacker-model", attacker_key))

        assert excinfo.value.phase == "verify"
        assert active.read_bytes() == b"old-model-weights"

    @pytest.mark.asyncio
    async def test_an_unconfigured_signing_key_refuses_rather_than_skips(self, tmp_path):
        """The dangerous reading of "no key configured" is "nothing to check against, so
        proceed". It must be the other way round."""
        private_key, _ = _keypair()
        executor = _executor(tmp_path, "")
        executor._download = AsyncMock(return_value=b"any-model")

        with pytest.raises(ModelUpdateError) as excinfo:
            await executor.handle_command(_command(b"any-model", private_key))

        assert excinfo.value.phase == "verify"

    @pytest.mark.parametrize(
        "missing",
        [
            "release_id",
            "model_name",
            "target_version",
            "bundle_url",
            "checksum_sha256",
            "signature_ed25519",
        ],
    )
    @pytest.mark.asyncio
    async def test_every_required_parameter_is_required(self, tmp_path, missing):
        """Parameterised over all six deliberately. These are the exact keys the cloud
        sends, so this is the cross-repo contract: if the dispatcher ever stops sending
        one, this names which."""
        private_key, public_key = _keypair()
        executor = _executor(tmp_path, public_key)
        executor._download = AsyncMock(return_value=b"model")

        with pytest.raises(ModelUpdateError) as excinfo:
            await executor.handle_command(
                _command(b"model", private_key, **{missing: None})
            )

        assert excinfo.value.phase == "preflight"
        assert missing in str(excinfo.value)


class TestAFailedSwapDoesNotStrandTheDevice:
    @pytest.mark.asyncio
    async def test_a_swap_failure_restores_the_previous_model(self, tmp_path):
        """THE PROPERTY THIS CLASS EXISTS FOR. `_apply` has already moved the new file
        into place when `_swap` runs, so a swap that raises leaves a device whose active
        model is one the engine could not load. Rollback has to put the old file back —
        otherwise the failure mode of a bad model is a device with no working model at
        all, reachable only by driving to it."""
        private_key, public_key = _keypair()
        active = tmp_path / "model.pt"
        active.write_bytes(b"old-model-weights")
        swap = AsyncMock(side_effect=[RuntimeError("engine refused the weights"), None])
        executor = _executor(tmp_path, public_key, swap_callback=swap)
        executor._download = AsyncMock(return_value=b"bad-model")

        with pytest.raises(ModelUpdateError) as excinfo:
            await executor.handle_command(_command(b"bad-model", private_key))

        assert excinfo.value.phase == "swap"
        assert active.read_bytes() == b"old-model-weights"
        # Rolled back AND re-loaded: disk and engine have to agree afterwards, or the
        # device serves the old file while the engine holds the new weights.
        assert swap.await_count == 2

    @pytest.mark.asyncio
    async def test_a_first_install_that_fails_leaves_no_active_model(self, tmp_path):
        """With no previous model there is nothing to restore, so the honest end state is
        *absent* rather than a half-written file the engine would try to load."""
        private_key, public_key = _keypair()
        active = tmp_path / "model.pt"
        swap = AsyncMock(side_effect=RuntimeError("engine refused the weights"))
        executor = _executor(tmp_path, public_key, swap_callback=swap)
        executor._download = AsyncMock(return_value=b"bad-model")

        with pytest.raises(ModelUpdateError):
            await executor.handle_command(_command(b"bad-model", private_key))

        assert not active.exists()


class TestTwoUpdatesDoNotInterleave:
    @pytest.mark.asyncio
    async def test_a_concurrent_update_is_refused_rather_than_queued(self, tmp_path):
        """Two `os.replace` sequences over one path interleave into a model file that is
        neither release. Refusing is right; queueing would hide that the cloud dispatched
        twice."""
        private_key, public_key = _keypair()
        started = asyncio.Event()
        release = asyncio.Event()

        async def _slow_swap(_path):
            started.set()
            await release.wait()

        executor = _executor(tmp_path, public_key, swap_callback=_slow_swap)
        executor._download = AsyncMock(return_value=b"model")

        first = asyncio.create_task(
            executor.handle_command(_command(b"model", private_key))
        )
        await asyncio.wait_for(started.wait(), timeout=5)

        with pytest.raises(ModelUpdateError) as excinfo:
            await executor.handle_command(_command(b"model", private_key))
        assert excinfo.value.phase == "preflight"
        assert "already in progress" in str(excinfo.value)

        release.set()
        await first


class TestItRegistersTheActionTheCloudDispatches:
    def test_register_binds_model_update(self):
        """The whole reason this class was dead: `register()` is the only thing that binds
        the action, and nothing called it. `backend/tests/test_dispatched_commands_have_a_handler.py`
        holds the other half of this contract."""
        recorded = {}

        class _Consumer:
            def register_handler(self, action, handler):
                recorded[action] = handler

        executor = ModelUpdateExecutor(
            signing_public_key="",
            active_model_path="/tmp/model.pt",
            staging_dir="/tmp/staging",
        )
        executor.register(_Consumer())

        assert "model_update" in recorded
        assert recorded["model_update"] == executor.handle_command
