"""Agent version, config hash, local state, and heartbeat helpers."""

from __future__ import annotations

import hashlib
import json
import os
from datetime import datetime, timezone
from pathlib import Path
from tempfile import NamedTemporaryFile
from typing import Any

from opsgrid_agent import __version__


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def normalized_config(config: Any) -> str:
    """Return a stable JSON representation for hashing."""
    return json.dumps(config or {}, sort_keys=True, separators=(",", ":"), default=str)


def compute_config_hash(config: Any) -> str:
    return hashlib.sha256(normalized_config(config).encode("utf-8")).hexdigest()


def build_manifest(
    supported_collectors: list[str],
    *,
    version: str = __version__,
    build_id: str | None = None,
    git_sha: str | None = None,
    build_time: str | None = None,
) -> dict[str, Any]:
    return {
        "agent_version": version,
        "build_id": build_id or os.getenv("AGENT_BUILD_ID", "dev"),
        "git_sha": git_sha or os.getenv("AGENT_GIT_SHA"),
        "build_time": build_time or os.getenv("AGENT_BUILD_TIME"),
        "supported_collectors": sorted(supported_collectors),
    }


def asset_ids_from_collectors(collectors: list[dict[str, Any]]) -> list[str]:
    ids = []
    for collector in collectors or []:
        asset_id = collector.get("asset_id")
        if asset_id and asset_id not in ids:
            ids.append(asset_id)
    return ids


def build_heartbeat_payload(
    *,
    agent_id: str,
    organization_id: str,
    asset_ids: list[str],
    manifest: dict[str, Any],
    config_hash: str,
    collector_status: dict[str, Any],
    update_status: dict[str, Any] | None = None,
    timestamp: str | None = None,
) -> dict[str, Any]:
    """The Kafka agent-status heartbeat: which build is running on which assets.

    MERGE NOTE 2026-08-08 — two designs met here and BOTH are kept, deliberately.

    FS-466 narrowed this payload to eight fields, because `git_sha`, `collector_status` and
    `buffer_depth` were sent on every beat and the cloud read none of them:
    `_process_agent_heartbeat` updated `Asset.agent_version / agent_config_hash /
    agent_build_id / last_seen` and nothing else. Device HEALTH travels the other heartbeat,
    `POST /api/v1/edge/heartbeat`, which the backend persists on `edge_agent_status` and
    publishes as per-agent `edge_agent_*` gauges — that path has consumers, so it kept the
    health fields.

    Hridyansh's OTA work (2026-07-23..27) re-widens it and adds `agent_update`, and his
    `_process_agent_heartbeat` DOES consume `collector_status` — so that field now has a
    reader and the FS-466 argument no longer applies to it.

    `git_sha` and `buffer_depth` are GONE AGAIN, and the guard is why. Recording them as
    deliberately-unread was the first attempt; `test_heartbeat_contract_is_fully_read`
    rejects that outright — *"the last three exemptions here were closed by DELETING the
    fields, because the agent was computing them on every beat for nobody. Prefer that to
    writing a reason."* These are two of that three. Buffer depth already travels the HTTP
    heartbeat as `buffer_pending`, where it is persisted and gauged and alerted on; build
    identity already travels here as `build_id`, which the cloud does write.

    THIS IS NOT HIS WORK BEING DROPPED. `collector_status` stays, because he added a reader
    for it — that is the entire difference between the three fields FS-466 removed. The
    feature is kept; the two fields nobody consumes are not.
    """
    payload = {
        "message_type": "agent_heartbeat",
        "agent_id": agent_id,
        "organization_id": organization_id,
        "asset_ids": asset_ids,
        "agent_version": manifest["agent_version"],
        "config_hash": config_hash,
        "build_id": manifest.get("build_id"),
        "collector_status": collector_status,
        "timestamp": timestamp or _utc_now(),
    }
    if update_status:
        payload["agent_update"] = update_status
    return payload


def load_agent_state(path: str | Path) -> dict[str, Any]:
    state_path = Path(path)
    if not state_path.exists():
        return {}
    return json.loads(state_path.read_text(encoding="utf-8"))


def persist_agent_state(path: str | Path, state: dict[str, Any]) -> None:
    state_path = Path(path)
    state_path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(state, sort_keys=True, indent=2, default=str)
    with NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=state_path.parent,
        delete=False,
    ) as tmp:
        tmp.write(payload)
        tmp.write("\n")
        tmp.flush()
        os.fsync(tmp.fileno())
        tmp_path = Path(tmp.name)
    tmp_path.replace(state_path)
    try:
        directory_fd = os.open(state_path.parent, os.O_RDONLY)
    except OSError:
        return
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
