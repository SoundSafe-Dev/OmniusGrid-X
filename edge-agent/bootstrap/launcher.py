"""Stable supervisor for versioned OpsGrid agent wheels.

The bootstrap is baked into the base image and is deliberately not part of an
agent wheel. It owns the durable version pointers, starts one selected wheel,
and restores the previous wheel when a newly selected process cannot complete
its boot self-check.
"""

from __future__ import annotations

import glob
import hashlib
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone
from email.parser import BytesParser
from pathlib import Path
from typing import Any, Optional


BOOTSTRAP_VERSION = "1.0.0"
EXPECTED_PACKAGE = "opsgrid-agent"
_NORMALIZE_NAME = re.compile(r"[-_.]+")
_SAFE_VERSION = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,99}$")

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(message)s",
)
logger = logging.getLogger("opsgrid-bootstrap")


class BootstrapError(RuntimeError):
    """Bootstrap invariant or lifecycle failure."""


class AgentBootstrap:
    def __init__(
        self,
        *,
        runtime_root: str | Path,
        seed_wheel: str | Path,
        ready_timeout_seconds: int = 90,
        poll_interval_seconds: float = 0.2,
    ):
        self.runtime_root = Path(runtime_root).resolve()
        self.versions_dir = self.runtime_root / "versions"
        self.seed_wheel = Path(seed_wheel).resolve()
        self.ready_timeout_seconds = max(1, int(ready_timeout_seconds))
        self.poll_interval_seconds = max(0.05, float(poll_interval_seconds))
        self.current_path = self.runtime_root / "current"
        self.previous_path = self.runtime_root / "previous"
        self.journal_path = self.runtime_root / "update-state.json"
        self.ready_path = self.runtime_root / "boot-ready.json"
        self.last_update_path = self.runtime_root / "last-update.json"
        self._child: Optional[subprocess.Popen] = None
        self._stopping = False

    def run(self) -> int:
        self._prepare_runtime()
        self._install_signal_handlers()
        current = self._ensure_current_version()

        journal = self._read_json(self.journal_path)
        if journal.get("status") == "restart_requested":
            current = self._select_attempted_version(current, journal)

        while not self._stopping:
            journal = self._read_json(self.journal_path)
            candidate_boot = (
                journal.get("status") == "booting"
                and journal.get("attempted_version") == current
            )
            process = self._launch(current)
            ready, failure_phase, detail = self._wait_until_ready(process, current)

            if not ready:
                self._terminate(process)
                if self._stopping:
                    return 0
                if candidate_boot:
                    current = self._rollback_candidate(
                        attempted=current,
                        journal=journal,
                        failure_phase=failure_phase,
                        detail=detail,
                    )
                    process = self._launch(current)
                    ready, rollback_phase, rollback_detail = self._wait_until_ready(
                        process,
                        current,
                    )
                    if not ready:
                        self._terminate(process)
                        raise BootstrapError(
                            "Previous agent failed while recovering from "
                            f"{journal.get('attempted_version')}: "
                            f"{rollback_phase}: {rollback_detail}"
                        )
                    self._archive_finished_update()
                else:
                    raise BootstrapError(
                        f"Agent {current} failed boot self-check: "
                        f"{failure_phase}: {detail}"
                    )
            else:
                self._archive_finished_update()

            return_code = process.wait()
            self._child = None
            if self._stopping:
                return 0

            journal = self._read_json(self.journal_path)
            if journal.get("status") == "restart_requested":
                current = self._select_attempted_version(current, journal)
                continue

            logger.error(
                "agent_process_exited version=%s return_code=%s",
                current,
                return_code,
            )
            return return_code if return_code != 0 else 1

        return 0

    def _prepare_runtime(self) -> None:
        self.runtime_root.mkdir(parents=True, exist_ok=True)
        self.versions_dir.mkdir(parents=True, exist_ok=True)

    def _ensure_current_version(self) -> str:
        selected = self._read_pointer(self.current_path)
        if selected:
            self._validated_version_dir(selected)
            return selected

        version = self._install_seed_wheel()
        self._atomic_write_text(self.current_path, version)
        logger.info("seed_agent_selected version=%s", version)
        return version

    def _install_seed_wheel(self) -> str:
        if not self.seed_wheel.is_file():
            raise BootstrapError(f"Seed wheel does not exist: {self.seed_wheel}")
        version = self._wheel_version(self.seed_wheel)
        if not _SAFE_VERSION.fullmatch(version):
            raise BootstrapError("Seed wheel version is not filesystem-safe")

        target = self.versions_dir / version
        digest = self._sha256_file(self.seed_wheel)
        if target.exists():
            marker = self._read_json(target / "install.json")
            if (
                marker.get("version") == version
                and marker.get("checksum_sha256") == digest
            ):
                return version
            raise BootstrapError(
                f"Seed version directory has unexpected contents: {target}"
            )

        temporary = Path(
            tempfile.mkdtemp(prefix=f".seed-{version}.", dir=self.versions_dir)
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
                    str(self.seed_wheel),
                ],
                capture_output=True,
                text=True,
                timeout=120,
                check=False,
            )
            if completed.returncode != 0:
                detail = (completed.stderr or completed.stdout or "pip failed")[-2000:]
                raise BootstrapError(f"Cannot install seed wheel: {detail}")
            self._atomic_write_json(
                temporary / "install.json",
                {
                    "package_name": EXPECTED_PACKAGE,
                    "version": version,
                    "checksum_sha256": digest,
                    "installed_at": self._utc_now(),
                    "seed": True,
                },
            )
            os.replace(temporary, target)
            self._fsync_directory(self.versions_dir)
        finally:
            if temporary.exists():
                shutil.rmtree(temporary, ignore_errors=True)
        return version

    def _select_attempted_version(
        self,
        current: str,
        journal: dict[str, Any],
    ) -> str:
        attempted = str(journal.get("attempted_version") or "")
        previous = str(journal.get("previous_version") or "")
        if current == attempted and previous:
            # Recover a power loss after the current pointer was swapped but
            # before the journal advanced from restart_requested to booting.
            self._validated_version_dir(previous)
        elif previous != current:
            raise BootstrapError(
                "Update journal previous version does not match selected version"
            )
        else:
            self._validated_version_dir(attempted)
            self._atomic_write_text(self.previous_path, current)
            self._atomic_write_text(self.current_path, attempted)
        journal.update(
            {
                "status": "booting",
                "phase": "boot",
                "running_version": attempted,
                "boot_started_at": self._utc_now(),
            }
        )
        self._atomic_write_json(self.journal_path, journal)
        logger.info(
            "agent_version_selected previous=%s attempted=%s",
            previous,
            attempted,
        )
        return attempted

    def _rollback_candidate(
        self,
        *,
        attempted: str,
        journal: dict[str, Any],
        failure_phase: str,
        detail: str,
    ) -> str:
        previous = str(journal.get("previous_version") or "")
        self._validated_version_dir(previous)
        if previous == attempted:
            raise BootstrapError("Candidate and rollback versions are identical")

        self._atomic_write_text(self.current_path, previous)
        error = f"Agent {attempted} failed {failure_phase}: {detail}"
        journal.update(
            {
                "status": "rollback_booting",
                "phase": failure_phase,
                "running_version": previous,
                "rolled_back": True,
                "error": error[-2000:],
                "rollback_started_at": self._utc_now(),
            }
        )
        self._atomic_write_json(self.journal_path, journal)
        logger.warning(
            "agent_version_rollback attempted=%s restored=%s phase=%s",
            attempted,
            previous,
            failure_phase,
        )
        return previous

    def _launch(self, version: str) -> subprocess.Popen:
        version_dir = self._validated_version_dir(version)
        self.ready_path.unlink(missing_ok=True)
        self._fsync_directory(self.runtime_root)
        environment = dict(os.environ)
        environment.update(
            {
                "PYTHONPATH": str(version_dir),
                "PYTHONNOUSERSITE": "1",
                "OPSGRID_BOOTSTRAP_MANAGED": "true",
                "OPSGRID_REQUIRE_BOOT_HEALTH": "true",
                "OPSGRID_BOOTSTRAP_VERSION": BOOTSTRAP_VERSION,
                "OPSGRID_RUNNING_VERSION": version,
                "OPSGRID_RUNTIME_ROOT": str(self.runtime_root),
                "OPSGRID_BOOTSTRAP_READY_FILE": str(self.ready_path),
            }
        )
        logger.info("agent_process_starting version=%s", version)
        self._child = subprocess.Popen(
            [sys.executable, "-m", "opsgrid_agent.main"],
            cwd=self.runtime_root,
            env=environment,
        )
        return self._child

    def _wait_until_ready(
        self,
        process: subprocess.Popen,
        version: str,
    ) -> tuple[bool, str, str]:
        deadline = time.monotonic() + self.ready_timeout_seconds
        while time.monotonic() < deadline and not self._stopping:
            return_code = process.poll()
            if return_code is not None:
                return False, "process_exit", f"return code {return_code}"
            ready = self._read_json(self.ready_path)
            if (
                ready.get("agent_version") == version
                and ready.get("pid") == process.pid
            ):
                logger.info("agent_boot_healthy version=%s pid=%s", version, process.pid)
                return True, "healthy", ""
            time.sleep(self.poll_interval_seconds)
        if self._stopping:
            return False, "shutdown", "bootstrap is stopping"
        return (
            False,
            "health_timeout",
            f"no healthy marker within {self.ready_timeout_seconds} seconds",
        )

    def _archive_finished_update(self) -> None:
        journal = self._read_json(self.journal_path)
        if not journal:
            return
        if journal.get("status") == "switch_requested":
            # The old process may have crashed after staging but before its
            # command offset commit. Let it consume the command again.
            return
        if journal.get("status") not in {"completed", "rolled_back"}:
            raise BootstrapError(
                "Agent reported healthy before publishing its terminal update ack"
            )
        journal["archived_at"] = self._utc_now()
        self._atomic_write_json(self.last_update_path, journal)
        self.journal_path.unlink(missing_ok=True)
        self._fsync_directory(self.runtime_root)

    def _validated_version_dir(self, version: str) -> Path:
        if not _SAFE_VERSION.fullmatch(version):
            raise BootstrapError(f"Unsafe selected version: {version!r}")
        path = (self.versions_dir / version).resolve()
        if path.parent != self.versions_dir:
            raise BootstrapError("Selected version escapes the versions directory")
        marker = self._read_json(path / "install.json")
        if marker.get("version") != version:
            raise BootstrapError(f"Selected version is not installed: {version}")
        return path

    @staticmethod
    def _wheel_version(path: Path) -> str:
        try:
            with zipfile.ZipFile(path) as archive:
                metadata_paths = [
                    name
                    for name in archive.namelist()
                    if name.endswith(".dist-info/METADATA")
                ]
                if len(metadata_paths) != 1:
                    raise BootstrapError("Seed wheel metadata is ambiguous")
                metadata = BytesParser().parsebytes(archive.read(metadata_paths[0]))
        except zipfile.BadZipFile as exc:
            raise BootstrapError("Seed artifact is not a wheel") from exc
        package_name = _NORMALIZE_NAME.sub(
            "-",
            str(metadata.get("Name") or ""),
        ).lower()
        if package_name != EXPECTED_PACKAGE:
            raise BootstrapError("Seed wheel package name is invalid")
        version = str(metadata.get("Version") or "")
        if not version:
            raise BootstrapError("Seed wheel version is missing")
        return version

    def _install_signal_handlers(self) -> None:
        for signum in (signal.SIGINT, signal.SIGTERM):
            signal.signal(signum, self._handle_signal)

    def _handle_signal(self, signum, _frame) -> None:
        logger.info("bootstrap_shutdown_requested signal=%s", signum)
        self._stopping = True
        if self._child and self._child.poll() is None:
            self._child.terminate()

    @staticmethod
    def _terminate(process: subprocess.Popen) -> None:
        if process.poll() is not None:
            return
        process.terminate()
        try:
            process.wait(timeout=10)
        except subprocess.TimeoutExpired:
            process.kill()
            process.wait(timeout=5)

    @staticmethod
    def _read_pointer(path: Path) -> str:
        if not path.exists():
            return ""
        try:
            return path.read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise BootstrapError(f"Cannot read version pointer {path}: {exc}") from exc

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any]:
        if not path.exists():
            return {}
        try:
            value = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise BootstrapError(f"Cannot read state file {path}: {exc}") from exc
        if not isinstance(value, dict):
            raise BootstrapError(f"State file is not an object: {path}")
        return value

    @classmethod
    def _atomic_write_text(cls, path: Path, value: str) -> None:
        cls._atomic_write_bytes(path, f"{value}\n".encode("utf-8"))

    @classmethod
    def _atomic_write_json(cls, path: Path, value: dict[str, Any]) -> None:
        payload = (
            json.dumps(value, sort_keys=True, indent=2, default=str) + "\n"
        ).encode("utf-8")
        cls._atomic_write_bytes(path, payload)

    @classmethod
    def _atomic_write_bytes(cls, path: Path, payload: bytes) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        descriptor, temp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp",
        )
        temporary = Path(temp_name)
        try:
            with os.fdopen(descriptor, "wb") as handle:
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, path)
            cls._fsync_directory(path.parent)
        finally:
            temporary.unlink(missing_ok=True)

    @staticmethod
    def _sha256_file(path: Path) -> str:
        digest = hashlib.sha256()
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
        return digest.hexdigest()

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


def _resolve_seed_wheel() -> Path:
    explicit = os.getenv("OPSGRID_SEED_WHEEL")
    if explicit:
        return Path(explicit)
    pattern = os.getenv(
        "OPSGRID_SEED_WHEEL_GLOB",
        "/opt/opsgrid-agent/seed/*.whl",
    )
    matches = sorted(glob.glob(pattern))
    if len(matches) != 1:
        raise BootstrapError(
            f"Expected exactly one seed wheel matching {pattern!r}; found {len(matches)}"
        )
    return Path(matches[0])


def main() -> int:
    runtime_root = os.getenv(
        "OPSGRID_RUNTIME_ROOT",
        "/var/lib/opsgrid-agent/runtime",
    )
    try:
        bootstrap = AgentBootstrap(
            runtime_root=runtime_root,
            seed_wheel=_resolve_seed_wheel(),
            ready_timeout_seconds=int(
                os.getenv("OPSGRID_BOOT_READY_TIMEOUT_SECONDS", "90")
            ),
        )
        return bootstrap.run()
    except Exception as exc:
        logger.exception("bootstrap_failed error=%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
