"""Abort-safe config-bundle OTA executor."""

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

from .download import DownloadFailed, ResumableDownload
import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

logger = structlog.get_logger()

RestartCallback = Callable[[], Awaitable[None] | None]
BundleValidator = Callable[[bytes], Awaitable[None] | None]


class OTAUpdateError(RuntimeError):
    """Update failure with a stable phase for command acknowledgements."""

    def __init__(self, phase: str, message: str):
        self.phase = phase
        super().__init__(message)


@dataclass(frozen=True)
class AppliedBundle:
    had_previous: bool
    active_path: Path
    previous_path: Path


class OTAUpdateExecutor:
    """Download, verify, apply, and rollback config-bundle updates."""

    def __init__(
        self,
        *,
        buffer,
        signing_public_key: str,
        active_bundle_path: str,
        staging_dir: str,
        drain_timeout_seconds: int = 60,
        restart_callback: Optional[RestartCallback] = None,
        bundle_validator: Optional[BundleValidator] = None,
        max_artifact_bytes: int = 64 * 1024 * 1024,
    ):
        self.buffer = buffer
        self.signing_public_key = signing_public_key
        self.active_bundle_path = Path(active_bundle_path)
        self.previous_bundle_path = self.active_bundle_path.with_suffix(
            self.active_bundle_path.suffix + ".previous"
        )
        self.staging_dir = Path(staging_dir)
        #: FS-758. This path had NO size limit of any kind — `response.content` on an
        #: unbounded body, so a release record pointing at an oversized file exhausts the
        #: gateway's memory. It is a denial of service reachable by anyone who can influence
        #: a release URL, and it sat in FRONT of the signature check, which only runs once
        #: the bytes are already resident. The default matches the agent self-updater's.
        self.max_artifact_bytes = max(1, int(max_artifact_bytes))
        self.drain_timeout_seconds = drain_timeout_seconds
        self.restart_callback = restart_callback
        self.bundle_validator = bundle_validator
        self._lock = asyncio.Lock()

    def register(self, command_consumer) -> None:
        """Register the agent_update command handler on the command transport."""
        command_consumer.register_handler("agent_update", self.handle_command)

    async def handle_command(self, command: Dict[str, Any]) -> Dict[str, Any]:
        if self._lock.locked():
            raise OTAUpdateError("preflight", "Another update is already in progress")

        async with self._lock:
            params = command.get("parameters") or {}
            release_id = self._required(params, "release_id")
            target_version = self._required(params, "target_version")
            bundle_url = self._required(params, "bundle_url")
            checksum_sha256 = self._required(params, "checksum_sha256")
            signature_ed25519 = self._required(params, "signature_ed25519")

            staged_path: Optional[Path] = None
            applied: Optional[AppliedBundle] = None
            try:
                bundle = await self._download_bundle(bundle_url)
                self._verify_checksum(bundle, checksum_sha256)
                self._verify_signature(bundle, signature_ed25519)
                await self._validate_bundle(bundle)
                staged_path = self._stage_bundle(bundle, release_id)
                await self._drain_buffer()
                applied = self._apply_staged_bundle(staged_path)
                await self._restart_runtime()
                logger.info(
                    "ota_update_completed",
                    release_id=release_id,
                    target_version=target_version,
                )
                return {
                    "release_id": release_id,
                    "new_version": target_version,
                    "active_bundle_path": str(applied.active_path),
                    "previous_bundle_available": applied.had_previous,
                }
            except OTAUpdateError:
                if applied is not None:
                    self._rollback_bundle(applied)
                raise
            except Exception as exc:
                if applied is not None:
                    self._rollback_bundle(applied)
                raise OTAUpdateError("apply", str(exc)) from exc
            finally:
                if staged_path and staged_path.exists():
                    staged_path.unlink(missing_ok=True)

    @staticmethod
    def _required(params: Dict[str, Any], key: str) -> str:
        value = params.get(key)
        if value in (None, ""):
            raise OTAUpdateError("preflight", f"Missing update parameter: {key}")
        return str(value)

    async def _download_bundle(self, bundle_url: str) -> bytes:
        """Resumable, streamed to disk, and size-capped (FS-758).

        Was `response.content` on an unbounded `get()`: the whole bundle in memory with no
        limit of any kind, discarded entirely by a disconnect at 99%.
        """
        destination = self.staging_dir / "download.bundle.bin"
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        download = ResumableDownload(
            bundle_url, destination, max_bytes=self.max_artifact_bytes
        )
        try:
            path = await download.fetch()
        except DownloadFailed as exc:
            raise OTAUpdateError("download", str(exc)) from exc
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise OTAUpdateError("download", str(exc)) from exc
        try:
            return path.read_bytes()
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def _verify_checksum(bundle: bytes, expected_sha256: str) -> None:
        actual = hashlib.sha256(bundle).hexdigest()
        if actual.lower() != expected_sha256.lower():
            raise OTAUpdateError("verify", "Config bundle checksum mismatch")

    def _verify_signature(self, bundle: bytes, signature_ed25519: str) -> None:
        if not self.signing_public_key:
            raise OTAUpdateError("verify", "OTA signing public key is not configured")
        try:
            public_key = self._load_public_key(self.signing_public_key)
            public_key.verify(base64.b64decode(signature_ed25519), bundle)
        except (InvalidSignature, ValueError) as exc:
            raise OTAUpdateError("verify", "Config bundle signature mismatch") from exc

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

    async def _validate_bundle(self, bundle: bytes) -> None:
        if self.bundle_validator is None:
            return
        try:
            result = self.bundle_validator(bundle)
            if inspect.isawaitable(result):
                await result
        except OTAUpdateError:
            raise
        except Exception as exc:
            raise OTAUpdateError(
                "verify",
                f"Config bundle validation failed: {exc}",
            ) from exc

    def _stage_bundle(self, bundle: bytes, release_id: str) -> Path:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        fd, temp_name = tempfile.mkstemp(
            dir=self.staging_dir,
            prefix=f".{release_id}.",
            suffix=".bundle",
        )
        os.close(fd)
        path = Path(temp_name)
        path.write_bytes(bundle)
        return path

    async def _drain_buffer(self) -> None:
        deadline = asyncio.get_event_loop().time() + self.drain_timeout_seconds
        while True:
            stats = await self.buffer.get_stats()
            if int(stats.get("total_messages", 0)) == 0:
                return
            if asyncio.get_event_loop().time() >= deadline:
                raise OTAUpdateError("drain", "Timed out waiting for buffer to drain")
            await asyncio.sleep(1)

    def _apply_staged_bundle(self, staged_path: Path) -> AppliedBundle:
        active_path = self.active_bundle_path
        previous_path = self.previous_bundle_path
        active_path.parent.mkdir(parents=True, exist_ok=True)
        had_previous = active_path.exists()

        if previous_path.exists():
            previous_path.unlink()
        if had_previous:
            os.replace(active_path, previous_path)
        os.replace(staged_path, active_path)
        return AppliedBundle(
            had_previous=had_previous,
            active_path=active_path,
            previous_path=previous_path,
        )

    def _rollback_bundle(self, applied: AppliedBundle) -> None:
        try:
            if applied.active_path.exists():
                applied.active_path.unlink()
            if applied.had_previous and applied.previous_path.exists():
                os.replace(applied.previous_path, applied.active_path)
            logger.warning("ota_update_rolled_back", active_path=str(applied.active_path))
        except Exception as exc:
            logger.error("ota_update_rollback_failed", error=str(exc))

    async def _restart_runtime(self) -> None:
        if self.restart_callback is None:
            return
        try:
            result = self.restart_callback()
            if inspect.isawaitable(result):
                await result
        except Exception as exc:
            raise OTAUpdateError("restart", str(exc)) from exc
