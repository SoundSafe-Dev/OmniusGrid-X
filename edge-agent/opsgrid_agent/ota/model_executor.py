"""Abort-safe model-artifact OTA executor (Task 2).

Mirrors ``ota/executor.py`` but delivers a trained model instead of a config
bundle: download the signed ``.pt`` via the release URL, verify checksum +
Ed25519 signature, atomically swap it into the active model path, and hot-swap
it into the inference engine (``swap_callback`` -> tactical_engine /
mlops_pipeline). Any failure rolls the ``.pt`` back and re-swaps the previous
model, leaving the running agent undisturbed. No buffer drain — a model
hot-swap does not restart collectors.
"""

import asyncio
import base64
import hashlib
import inspect
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx
import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

logger = structlog.get_logger()

SwapCallback = Callable[[Path], Awaitable[None] | None]


class ModelUpdateError(RuntimeError):
    """Model update failure with a stable phase for command acknowledgements."""

    def __init__(self, phase: str, message: str):
        self.phase = phase
        super().__init__(message)


@dataclass(frozen=True)
class AppliedModel:
    had_previous: bool
    active_path: Path
    previous_path: Path


class ModelUpdateExecutor:
    """Download, verify, hot-swap, and rollback model-artifact updates."""

    def __init__(
        self,
        *,
        signing_public_key: str,
        active_model_path: str,
        staging_dir: str,
        swap_callback: Optional[SwapCallback] = None,
    ):
        self.signing_public_key = signing_public_key
        self.active_model_path = Path(active_model_path)
        self.previous_model_path = self.active_model_path.with_suffix(
            self.active_model_path.suffix + ".previous"
        )
        self.staging_dir = Path(staging_dir)
        self.swap_callback = swap_callback
        self._lock = asyncio.Lock()

    def register(self, command_consumer) -> None:
        """Register the model_update handler on the command transport."""
        command_consumer.register_handler("model_update", self.handle_command)

    async def handle_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        if self._lock.locked():
            raise ModelUpdateError("preflight", "Another model update is already in progress")

        async with self._lock:
            params = command.get("parameters") or {}
            release_id = self._required(params, "release_id")
            model_name = self._required(params, "model_name")
            target_version = self._required(params, "target_version")
            bundle_url = self._required(params, "bundle_url")
            checksum_sha256 = self._required(params, "checksum_sha256")
            signature_ed25519 = self._required(params, "signature_ed25519")

            staged_path: Optional[Path] = None
            applied: Optional[AppliedModel] = None
            try:
                artifact = await self._download(bundle_url)
                self._verify_checksum(artifact, checksum_sha256)
                self._verify_signature(artifact, signature_ed25519)
                staged_path = self._stage(artifact, release_id)
                applied = self._apply(staged_path)
                await self._swap(applied.active_path)
                logger.info(
                    "model_update_completed",
                    release_id=release_id,
                    model_name=model_name,
                    new_version=target_version,
                )
                return {
                    "release_id": release_id,
                    "model_name": model_name,
                    "new_model_version": target_version,
                    "active_model_path": str(applied.active_path),
                    "previous_model_available": applied.had_previous,
                }
            except ModelUpdateError:
                await self._rollback(applied)
                raise
            except Exception as exc:
                await self._rollback(applied)
                raise ModelUpdateError("apply", str(exc)) from exc
            finally:
                if staged_path and staged_path.exists():
                    staged_path.unlink(missing_ok=True)

    @staticmethod
    def _required(params: Dict[str, Any], key: str) -> str:
        value = params.get(key)
        if value in (None, ""):
            raise ModelUpdateError("preflight", f"Missing update parameter: {key}")
        return str(value)

    async def _download(self, bundle_url: str) -> bytes:
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                response = await client.get(bundle_url)
                response.raise_for_status()
                return response.content
        except httpx.HTTPError as exc:
            raise ModelUpdateError("download", str(exc)) from exc

    @staticmethod
    def _verify_checksum(artifact: bytes, expected_sha256: str) -> None:
        actual = hashlib.sha256(artifact).hexdigest()
        if actual.lower() != expected_sha256.lower():
            raise ModelUpdateError("verify", "Model artifact checksum mismatch")

    def _verify_signature(self, artifact: bytes, signature_ed25519: str) -> None:
        if not self.signing_public_key:
            raise ModelUpdateError("verify", "OTA signing public key is not configured")
        try:
            public_key = self._load_public_key(self.signing_public_key)
            public_key.verify(base64.b64decode(signature_ed25519), artifact)
        except (InvalidSignature, ValueError) as exc:
            raise ModelUpdateError("verify", "Model artifact signature mismatch") from exc

    @staticmethod
    def _load_public_key(value: str) -> Ed25519PublicKey:
        raw = value.encode("utf-8")
        if b"BEGIN PUBLIC KEY" in raw:
            key = serialization.load_pem_public_key(raw)
        else:
            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(value))
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("OTA signing public key must be Ed25519")
        return key

    def _stage(self, artifact: bytes, release_id: str) -> Path:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            dir=self.staging_dir,
            prefix=f".{release_id}.",
            suffix=".pt",
        )
        os.close(fd)
        path = Path(temp_name)
        path.write_bytes(artifact)
        return path

    def _apply(self, staged_path: Path) -> AppliedModel:
        active_path = self.active_model_path
        previous_path = self.previous_model_path
        active_path.parent.mkdir(parents=True, exist_ok=True)
        had_previous = active_path.exists()

        if previous_path.exists():
            previous_path.unlink()
        if had_previous:
            os.replace(active_path, previous_path)
        os.replace(staged_path, active_path)
        return AppliedModel(
            had_previous=had_previous,
            active_path=active_path,
            previous_path=previous_path,
        )

    async def _rollback(self, applied: Optional[AppliedModel]) -> None:
        if applied is None:
            return
        try:
            if applied.active_path.exists():
                applied.active_path.unlink()
            if applied.had_previous and applied.previous_path.exists():
                os.replace(applied.previous_path, applied.active_path)
                # Re-load the previous model so the engine matches disk.
                await self._swap_safe(applied.active_path)
            logger.warning("model_update_rolled_back", active_path=str(applied.active_path))
        except Exception as exc:
            logger.error("model_update_rollback_failed", error=str(exc))

    async def _swap(self, active_path: Path) -> None:
        if self.swap_callback is None:
            return
        try:
            result = self.swap_callback(active_path)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            raise ModelUpdateError("swap", str(exc)) from exc

    async def _swap_safe(self, active_path: Path) -> None:
        if self.swap_callback is None:
            return
        try:
            result = self.swap_callback(active_path)
            if inspect.isawaitable(result):
                await result
        except Exception as exc:  # best-effort during rollback
            logger.error("model_update_reswap_failed", error=str(exc))
