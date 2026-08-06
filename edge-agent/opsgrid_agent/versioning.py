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
    timestamp: str | None = None,
) -> dict[str, Any]:
    """The Kafka agent-status heartbeat: which build is running on which assets.

    NARROWED (FS-466). This used to also carry `git_sha`, `collector_status` and
    `buffer_depth`, and the cloud read none of them — `_process_agent_heartbeat` updates
    `Asset.agent_version / agent_config_hash / agent_build_id / last_seen` and nothing else.

    Device HEALTH travels the other heartbeat, `POST /api/v1/edge/heartbeat`, which reports
    `buffer_pending`, `dead_lettered`, `dropped` and `active_collectors`; the backend
    persists those on `edge_agent_status` and publishes per-agent `edge_agent_*` gauges.
    That path has a consumer, so it is the one that keeps the health fields.

    Two paths carrying the same facts under two names (`buffer_depth` / `buffer_pending`)
    is the condition that produced six aliases in FS-435. This one now answers exactly one
    question — what is running where — and the caller no longer computes buffer stats and
    collector status on every beat to fill fields nobody reads.
    """
    return {
        "message_type": "agent_heartbeat",
        "agent_id": agent_id,
        "organization_id": organization_id,
        "asset_ids": asset_ids,
        "agent_version": manifest["agent_version"],
        "config_hash": config_hash,
        "build_id": manifest.get("build_id"),
        "timestamp": timestamp or _utc_now(),
    }


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
        tmp_path = Path(tmp.name)
    tmp_path.replace(state_path)
