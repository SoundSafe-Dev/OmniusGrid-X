"""Restart-spanning, signed wheel self-update executor."""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from datetime import datetime, timezone
from email.parser import BytesParser
from pathlib import Path, PurePosixPath
from typing import Any, Awaitable, Callable, Dict, Optional

import httpx
import structlog
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

from opsgrid_agent import __version__
from opsgrid_agent.ota.download import DownloadFailed, ResumableDownload
from opsgrid_agent.commands import DeferredCommandAck


logger = structlog.get_logger()

EXPECTED_PACKAGE = "opsgrid-agent"
MAX_WHEEL_MEMBERS = 10_000
_NORMALIZE_NAME = re.compile(r"[-_.]+")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,99}$")
_COMPILED_SUFFIXES = (".so", ".pyd", ".dylib", ".dll")

RestartCallback = Callable[[], Awaitable[None] | None]


class AgentSelfUpdateError(RuntimeError):
    """Self-update failure with a stable acknowledgement phase."""

    def __init__(self, phase: str, message: str):
        self.phase = phase
        super().__init__(message)


class AgentSelfUpdateExecutor:
    """Verify and install a wheel, then hand a durable switch to the bootstrap."""

    def __init__(
        self,
        *,
        buffer,
        signing_public_key: str,
        runtime_root: str,
        drain_timeout_seconds: int = 60,
        preflight_timeout_seconds: int = 30,
        max_artifact_bytes: int = 64 * 1024 * 1024,
        max_uncompressed_bytes: int = 256 * 1024 * 1024,
        bootstrap_version: str = "1.0.0",
        restart_callback: Optional[RestartCallback] = None,
    ):
        self.buffer = buffer
        self.signing_public_key = signing_public_key
        self.runtime_root = Path(runtime_root).resolve()
        self.versions_dir = self.runtime_root / "versions"
        self.staging_dir = self.runtime_root / "staging"
        self.journal_path = self.runtime_root / "update-state.json"
        self.drain_timeout_seconds = max(0, int(drain_timeout_seconds))
        self.preflight_timeout_seconds = max(1, int(preflight_timeout_seconds))
        self.max_artifact_bytes = max(1, int(max_artifact_bytes))
        self.max_uncompressed_bytes = max(1, int(max_uncompressed_bytes))
        self.bootstrap_version = bootstrap_version
        self.restart_callback = restart_callback
        self._lock = asyncio.Lock()

    @property
    def running_version(self) -> str:
        return str(os.getenv("OPSGRID_RUNNING_VERSION") or __version__)

    def register(self, command_consumer) -> None:
        command_consumer.register_handler("agent_self_update", self.handle_command)

    async def handle_command(self, command: Dict[str, Any]) -> Dict[str, Any] | DeferredCommandAck:
        if self._lock.locked():
            raise AgentSelfUpdateError("preflight", "Another agent update is in progress")

        async with self._lock:
            params = command.get("parameters") or {}
            release_id = self._required(params, "release_id")
            target_version = self._required(params, "target_version")
            artifact_url = self._required(params, "bundle_url")
            checksum = self._required(params, "checksum_sha256")
            signature = self._required(params, "signature_ed25519")
            artifact_format = self._required(params, "artifact_format")
            package_name = self._required(params, "package_name")
            filename = self._required(params, "artifact_filename")
            expected_size = self._optional_int(params.get("artifact_size_bytes"))
            minimum_bootstrap = params.get("minimum_bootstrap_version")

            if artifact_format != "wheel":
                raise AgentSelfUpdateError("preflight", "Agent artifact must be a wheel")
            if self._normalize_name(package_name) != EXPECTED_PACKAGE:
                raise AgentSelfUpdateError("preflight", "Unexpected agent package name")
            if not _SAFE_VERSION.fullmatch(target_version):
                raise AgentSelfUpdateError("preflight", "Target version is not filesystem-safe")
            if minimum_bootstrap and not self._version_at_least(
                self.bootstrap_version,
                str(minimum_bootstrap),
            ):
                raise AgentSelfUpdateError(
                    "preflight",
                    "Agent bootstrap is older than the release minimum",
                )
            if self.restart_callback is None:
                raise AgentSelfUpdateError("preflight", "Bootstrap restart callback is unavailable")

            existing_journal = self.load_journal()
            if existing_journal:
                if (
                    existing_journal.get("command", {}).get("command_id")
                    == str(command.get("command_id"))
                    and existing_journal.get("status")
                    in {"switch_requested", "restart_requested"}
                ):
                    return self._deferred_restart()
                if existing_journal.get("status") not in {"completed", "rolled_back"}:
                    raise AgentSelfUpdateError(
                        "preflight",
                        "A different agent update is already pending",
                    )

            if target_version == self.running_version:
                return {
                    "release_id": release_id,
                    "attempted_version": target_version,
                    "running_version": self.running_version,
                    "already_running": True,
                    "rolled_back": False,
                }

            staged_path: Optional[Path] = None
            installed_path: Optional[Path] = None
            installed_now = False
            try:
                artifact = await self._download_artifact(artifact_url)
                if expected_size is not None and len(artifact) != expected_size:
                    raise AgentSelfUpdateError(
                        "verify",
                        "Agent wheel size does not match release metadata",
                    )
                self._verify_checksum(artifact, checksum)
                self._verify_signature(artifact, signature)
                self._validate_wheel(
                    artifact,
                    filename=filename,
                    expected_version=target_version,
                )
                staged_path = self._stage_artifact(
                    artifact,
                    release_id=release_id,
                    filename=filename,
                )
                installed_path, installed_now = await asyncio.to_thread(
                    self._install_wheel,
                    staged_path,
                    target_version,
                    checksum,
                )
                await asyncio.to_thread(
                    self._preflight_installed_version,
                    installed_path,
                    target_version,
                )
                await self._drain_buffer()
                self._persist_switch_journal(
                    command,
                    release_id=release_id,
                    target_version=target_version,
                    checksum=checksum,
                    installed_path=installed_path,
                )
                logger.info(
                    "agent_update_staged",
                    release_id=release_id,
                    attempted_version=target_version,
                    running_version=self.running_version,
                )
                return self._deferred_restart()
            except AgentSelfUpdateError:
                if installed_now and installed_path is not None:
                    self._remove_unselected_version(installed_path)
                raise
            except Exception as exc:
                if installed_now and installed_path is not None:
                    self._remove_unselected_version(installed_path)
                raise AgentSelfUpdateError("stage", str(exc)) from exc
            finally:
                if staged_path is not None:
                    shutil.rmtree(staged_path.parent, ignore_errors=True)

    async def complete_pending_update(self, command_consumer) -> bool:
        """Publish the terminal ack after the restarted child is fully healthy."""
        journal = self.load_journal()
        if not journal:
            return False
        command = journal.get("command")
        if not isinstance(command, dict) or not command.get("command_id"):
            raise AgentSelfUpdateError("ack", "Update journal has no command identity")

        attempted = str(journal.get("attempted_version") or "")
        previous = str(journal.get("previous_version") or "")
        running = self.running_version
        status = str(journal.get("status") or "")
        if status in {"switch_requested", "restart_requested"}:
            return False
        rolled_back = bool(journal.get("rolled_back")) or status in {
            "rollback_booting",
            "rolled_back",
        }

        if running == attempted and not rolled_back:
            result = {
                "release_id": journal.get("release_id"),
                "attempted_version": attempted,
                "running_version": running,
                "previous_version": previous or None,
                "rolled_back": False,
                "phase": "healthy",
            }
            await command_consumer.emit_command_ack(
                command,
                status="completed",
                success=True,
                result=result,
            )
            journal.update(
                {
                    "status": "completed",
                    "running_version": running,
                    "phase": "healthy",
                    "ack_published_at": self._utc_now(),
                }
            )
        elif running == previous and attempted and attempted != running:
            error = str(
                journal.get("error")
                or f"Agent {attempted} failed self-check; restored {running}"
            )
            result = {
                "release_id": journal.get("release_id"),
                "attempted_version": attempted,
                "running_version": running,
                "previous_version": previous or None,
                "rolled_back": True,
                "phase": journal.get("phase") or "boot",
                "error": error,
            }
            await command_consumer.emit_command_ack(
                command,
                status="failed",
                success=False,
                result=result,
                error=error,
            )
            journal.update(
                {
                    "status": "rolled_back",
                    "running_version": running,
                    "rolled_back": True,
                    "ack_published_at": self._utc_now(),
                }
            )
        else:
            raise AgentSelfUpdateError(
                "ack",
                "Running version does not match pending or previous agent version",
            )

        self._atomic_write_json(self.journal_path, journal)
        return True

    def load_journal(self) -> dict[str, Any]:
        if not self.journal_path.exists():
            return {}
        try:
            value = json.loads(self.journal_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AgentSelfUpdateError("journal", f"Cannot read update journal: {exc}") from exc
        if not isinstance(value, dict):
            raise AgentSelfUpdateError("journal", "Update journal is not an object")
        return value

    def _deferred_restart(self) -> DeferredCommandAck:
        return DeferredCommandAck(
            reason="agent_process_restart",
            after_commit=self._request_restart,
        )

    async def _request_restart(self) -> None:
        journal = self.load_journal()
        journal["status"] = "restart_requested"
        journal["restart_requested_at"] = self._utc_now()
        self._atomic_write_json(self.journal_path, journal)
        result = self.restart_callback()
        if inspect.isawaitable(result):
            await result

    async def _download_artifact(self, url: str) -> bytes:
        """Resumable, streamed to disk (FS-758).

        This used to accumulate into a `bytearray` and then copy it with `bytes(content)` —
        two full copies of the wheel resident at once, so a 64 MB artifact peaked at 128 MB
        on a device that may have 512 MB in total. And any interruption restarted from byte
        zero, which on a link that drops every few minutes means a large artifact does not
        arrive slowly, it never arrives at all.

        Still returns bytes because the verification chain below needs them — Ed25519 has no
        incremental API, and the wheel validator opens a zip. Peak is now one copy rather
        than two, and the DOWNLOAD itself is bounded by a chunk. Removing the last copy
        means signing the digest instead of the artifact, which changes the release-signing
        contract and belongs to the OTA lane.
        """
        destination = self.staging_dir / f"download-{abs(hash(url)) & 0xFFFFFFFF:08x}.bin"
        download = ResumableDownload(
            url, destination, max_bytes=self.max_artifact_bytes
        )
        try:
            path = await download.fetch()
        except DownloadFailed as exc:
            raise AgentSelfUpdateError("download", str(exc)) from exc
        except (httpx.HTTPError, OSError, ValueError) as exc:
            raise AgentSelfUpdateError("download", str(exc)) from exc
        try:
            return path.read_bytes()
        finally:
            path.unlink(missing_ok=True)

    @staticmethod
    def _verify_checksum(artifact: bytes, expected: str) -> None:
        actual = hashlib.sha256(artifact).hexdigest()
        if actual.lower() != expected.lower():
            raise AgentSelfUpdateError("verify", "Agent wheel checksum mismatch")

    def _verify_signature(self, artifact: bytes, signature: str) -> None:
        if not self.signing_public_key:
            raise AgentSelfUpdateError("verify", "OTA signing public key is not configured")
        try:
            public_key = self._load_public_key(self.signing_public_key)
            public_key.verify(base64.b64decode(signature, validate=True), artifact)
        except (InvalidSignature, ValueError) as exc:
            raise AgentSelfUpdateError("verify", "Agent wheel signature mismatch") from exc

    @staticmethod
    def _load_public_key(value: str) -> Ed25519PublicKey:
        raw = value.encode("utf-8")
        if b"BEGIN PUBLIC KEY" in raw:
            key = serialization.load_pem_public_key(raw)
        else:
            key = Ed25519PublicKey.from_public_bytes(base64.b64decode(value, validate=True))
        if not isinstance(key, Ed25519PublicKey):
            raise ValueError("OTA signing public key must be Ed25519")
        return key

    def _validate_wheel(
        self,
        artifact: bytes,
        *,
        filename: str,
        expected_version: str,
    ) -> None:
        if (
            not filename.endswith(".whl")
            or filename != PurePosixPath(filename).name
            or "\\" in filename
        ):
            raise AgentSelfUpdateError("verify", "Unsafe agent wheel filename")
        try:
            filename_name, filename_version, _, filename_tags = parse_wheel_filename(
                filename
            )
        except InvalidWheelFilename as exc:
            raise AgentSelfUpdateError(
                "verify",
                "Agent artifact filename is not a valid wheel name",
            ) from exc
        if self._normalize_name(str(filename_name)) != EXPECTED_PACKAGE:
            raise AgentSelfUpdateError("verify", "Agent wheel filename is invalid")
        if str(filename_version) != expected_version:
            raise AgentSelfUpdateError("verify", "Agent wheel filename version is invalid")
        if any(tag.abi != "none" or tag.platform != "any" for tag in filename_tags):
            raise AgentSelfUpdateError(
                "verify",
                "Agent wheel filename is platform-specific",
            )
        try:
            archive = zipfile.ZipFile(io.BytesIO(artifact))
        except zipfile.BadZipFile as exc:
            raise AgentSelfUpdateError("verify", "Agent artifact is not a wheel") from exc

        with archive:
            members = archive.infolist()
            if not members or len(members) > MAX_WHEEL_MEMBERS:
                raise AgentSelfUpdateError("verify", "Agent wheel has an invalid member count")
            total = 0
            seen_names: set[str] = set()
            metadata_files = []
            wheel_files = []
            for member in members:
                self._validate_member(member)
                if member.filename in seen_names:
                    raise AgentSelfUpdateError(
                        "verify",
                        "Agent wheel contains duplicate paths",
                    )
                seen_names.add(member.filename)
                total += member.file_size
                if total > self.max_uncompressed_bytes:
                    raise AgentSelfUpdateError(
                        "verify",
                        "Agent wheel expands beyond the configured limit",
                    )
                if member.filename.endswith(".dist-info/METADATA"):
                    metadata_files.append(member)
                elif member.filename.endswith(".dist-info/WHEEL"):
                    wheel_files.append(member)
                if member.filename.lower().endswith(_COMPILED_SUFFIXES):
                    raise AgentSelfUpdateError("verify", "Agent wheel must be pure Python")
            if len(metadata_files) != 1 or len(wheel_files) != 1:
                raise AgentSelfUpdateError(
                    "verify",
                    "Agent wheel metadata is incomplete or ambiguous",
                )
            metadata = BytesParser().parsebytes(archive.read(metadata_files[0]))
            wheel_metadata = BytesParser().parsebytes(archive.read(wheel_files[0]))

        if self._normalize_name(str(metadata.get("Name") or "")) != EXPECTED_PACKAGE:
            raise AgentSelfUpdateError("verify", "Agent wheel package name is invalid")
        if str(metadata.get("Version") or "") != expected_version:
            raise AgentSelfUpdateError("verify", "Agent wheel version is invalid")
        if str(wheel_metadata.get("Root-Is-Purelib") or "").lower() != "true":
            raise AgentSelfUpdateError("verify", "Agent wheel is not pure Python")
        if not any(
            str(tag).endswith("-none-any")
            for tag in (wheel_metadata.get_all("Tag") or [])
        ):
            raise AgentSelfUpdateError("verify", "Agent wheel is platform-specific")

    @staticmethod
    def _validate_member(member: zipfile.ZipInfo) -> None:
        name = member.filename
        path = PurePosixPath(name)
        if (
            not name
            or "\\" in name
            or path.is_absolute()
            or any(part in {"", ".", ".."} for part in path.parts)
        ):
            raise AgentSelfUpdateError("verify", "Agent wheel contains an unsafe path")
        if member.flag_bits & 0x1:
            raise AgentSelfUpdateError(
                "verify",
                "Agent wheel contains encrypted files",
            )
        file_type = (member.external_attr >> 16) & 0o170000
        if file_type == 0o120000:
            raise AgentSelfUpdateError("verify", "Agent wheel contains a symbolic link")

    def _stage_artifact(
        self,
        artifact: bytes,
        *,
        release_id: str,
        filename: str,
    ) -> Path:
        self.staging_dir.mkdir(parents=True, exist_ok=True)
        update_dir = Path(
            tempfile.mkdtemp(
                dir=self.staging_dir,
                prefix=f".{hashlib.sha256(release_id.encode()).hexdigest()[:12]}.",
            )
        )
        path = update_dir / filename
        descriptor = os.open(
            path,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
        )
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(artifact)
                handle.flush()
                os.fsync(handle.fileno())
            return path
        except Exception:
            shutil.rmtree(update_dir, ignore_errors=True)
            raise

    def _install_wheel(
        self,
        wheel_path: Path,
        target_version: str,
        checksum: str,
    ) -> tuple[Path, bool]:
        self.versions_dir.mkdir(parents=True, exist_ok=True)
        target = self.versions_dir / target_version
        if target.exists():
            marker = self._read_json(target / "install.json")
            if (
                marker.get("version") == target_version
                and marker.get("checksum_sha256") == checksum
            ):
                return target, False
            raise AgentSelfUpdateError(
                "stage",
                "Target version directory exists with different contents",
            )

        temporary = Path(
            tempfile.mkdtemp(
                prefix=f".{target_version}.",
                dir=self.versions_dir,
            )
        )
        try:
            completed = subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "pip",
                    "install",
                    "--disable-pip-version-check",
                    "--no-deps",
                    "--no-compile",
                    "--target",
                    str(temporary),
                    str(wheel_path),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "pip install failed")[-2000:]
                raise AgentSelfUpdateError("stage", detail)
            self._atomic_write_json(
                temporary / "install.json",
                {
                    "package_name": EXPECTED_PACKAGE,
                    "version": target_version,
                    "checksum_sha256": checksum,
                    "installed_at": self._utc_now(),
                },
            )
            os.replace(temporary, target)
            self._fsync_directory(self.versions_dir)
            return target, True
        except subprocess.TimeoutExpired as exc:
            raise AgentSelfUpdateError("stage", "Timed out installing agent wheel") from exc
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)

    def _preflight_installed_version(self, target: Path, expected_version: str) -> None:
        code = (
            "import sys;"
            f"sys.path.insert(0, {str(target)!r});"
            "import opsgrid_agent;"
            f"assert opsgrid_agent.__version__ == {expected_version!r};"
            "import opsgrid_agent.main"
        )
        environment = dict(os.environ)
        environment.pop("PYTHONPATH", None)
        environment["PYTHONNOUSERSITE"] = "1"
        try:
            completed = subprocess.run(
                [sys.executable, "-c", code],
                cwd=self.runtime_root,
                env=environment,
                capture_output=True,
                text=True,
                timeout=self.preflight_timeout_seconds,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise AgentSelfUpdateError("preflight", "Agent import preflight timed out") from exc
        if completed.returncode != 0:
            detail = (completed.stderr or completed.stdout or "import failed")[-2000:]
            raise AgentSelfUpdateError("preflight", detail)

    async def _drain_buffer(self) -> None:
        deadline = asyncio.get_running_loop().time() + self.drain_timeout_seconds
        while True:
            stats = await self.buffer.get_stats()
            if int(stats.get("total_messages", 0)) == 0:
                return
            if asyncio.get_running_loop().time() >= deadline:
                raise AgentSelfUpdateError("drain", "Timed out waiting for buffer to drain")
            await asyncio.sleep(1)

    def _persist_switch_journal(
        self,
        command: Dict[str, Any],
        *,
        release_id: str,
        target_version: str,
        checksum: str,
        installed_path: Path,
    ) -> None:
        minimal_command = {
            "command_id": str(command.get("command_id") or ""),
            "agent_id": str(command.get("agent_id") or ""),
            "asset_id": str(command.get("asset_id") or ""),
            "organization_id": str(command.get("organization_id") or ""),
            "action_id": "agent_self_update",
            "parameters": {},
        }
        if not all(
            minimal_command.get(key)
            for key in ("command_id", "asset_id", "organization_id")
        ):
            raise AgentSelfUpdateError("journal", "Command identity is incomplete")
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self._atomic_write_json(
            self.journal_path,
            {
                "schema_version": 1,
                "status": "switch_requested",
                "phase": "switch",
                "release_id": release_id,
                "attempted_version": target_version,
                "previous_version": self.running_version,
                "running_version": self.running_version,
                "artifact_checksum_sha256": checksum,
                "installed_path": str(installed_path),
                "command": minimal_command,
                "created_at": self._utc_now(),
            },
        )

    def _remove_unselected_version(self, path: Path) -> None:
        try:
            resolved = path.resolve()
            if resolved.parent != self.versions_dir.resolve():
                return
            if resolved.name == self.running_version:
                return
            shutil.rmtree(resolved, ignore_errors=True)
        except OSError:
            return

    @staticmethod
    def _required(params: Dict[str, Any], key: str) -> str:
        value = params.get(key)
        if value in (None, ""):
            raise AgentSelfUpdateError("preflight", f"Missing update parameter: {key}")
        return str(value)

    @staticmethod
    def _optional_int(value: Any) -> Optional[int]:
        if value is None:
            return None
        if isinstance(value, bool):
            raise AgentSelfUpdateError("preflight", "Artifact size is invalid")
        try:
            parsed = int(value)
        except (TypeError, ValueError) as exc:
            raise AgentSelfUpdateError("preflight", "Artifact size is invalid") from exc
        if parsed <= 0:
            raise AgentSelfUpdateError("preflight", "Artifact size is invalid")
        return parsed

    @staticmethod
    def _normalize_name(value: str) -> str:
        return _NORMALIZE_NAME.sub("-", value).lower()

    @staticmethod
    def _version_at_least(current: str, minimum: str) -> bool:
        def numeric(value: str) -> tuple[int, ...]:
            match = re.fullmatch(r"v?(\d+(?:\.\d+){0,3})", value.strip())
            if not match:
                raise AgentSelfUpdateError(
                    "preflight",
                    "Bootstrap version constraint must be numeric",
                )
            parts = tuple(int(part) for part in match.group(1).split("."))
            return parts + (0,) * (4 - len(parts))

        return numeric(current) >= numeric(minimum)

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return value if isinstance(value, dict) else {}

    @classmethod
    def _atomic_write_json(cls, path: Path, value: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temp_name)
        try:
            with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
                json.dump(value, handle, sort_keys=True, indent=2, default=str)
                handle.write("\n")
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            cls._fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _fsync_directory(path: Path) -> None:
        try:
            descriptor = os.open(path, os.O_RDONLY)
        except OSError:
            return
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)

    @staticmethod
    def _utc_now() -> str:
        return datetime.now(timezone.utc).isoformat()
