"""Validation schema for edge-agent collector configuration.

Validates the *envelope* of each collector entry (asset_id, known collector
type, enabled flag, config dict) — not the per-type inner `config`, whose keys
vary by protocol and are the collector's own responsibility.

Accepts both field spellings so the two existing config paths keep working:
- the env `COLLECTORS` JSON uses `type`
- `config/poc_collectors.yml` uses `collector_type`

Kept independent of the coordinator (no import of collector modules or drivers)
so config validation is cheap and rename-agnostic. ``SUPPORTED_COLLECTOR_TYPES``
mirrors ``UnifiedCollectorCoordinator.SUPPORTED_COLLECTORS`` — keep them in sync.
"""

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Single source of truth for valid collector types. Mirrors the coordinator's
# SUPPORTED_COLLECTORS keys (edge-agent/opsgrid_agent/collectors/coordinator.py).
SUPPORTED_COLLECTOR_TYPES = (
    "bambu_mqtt",
    "mqtt",
    "qidi_screen",
    "sovol_screen",
    "orca_file",
    "opcua",
    "modbus",
    "ethernet_ip",
    "profinet",
    "bacnet",
    "can_bus",
    "http_rest",
    "snmp",
    "sparkplug_b",
    "dnp3",
)


class PackMLConfig(BaseModel):
    """Optional state -> PackML mapping for a collector.

    Lives inside a collector entry's ``config`` under the ``packml`` key so it
    threads to the coordinator adapter untouched. ``asset_type`` selects the base
    mapping table; ``state_key`` names the payload field holding the raw state;
    ``mappings`` overrides/extends the base table.
    """

    model_config = ConfigDict(extra="forbid")

    asset_type: str
    state_key: str = "state"
    mappings: Dict[str, str] = Field(default_factory=dict)


class CollectorEntry(BaseModel):
    """One collector configuration entry (envelope-validated)."""

    model_config = ConfigDict(populate_by_name=True)

    asset_id: str
    # Accept `type` (env JSON) or `collector_type` (YAML); serialize as `type`
    # to match EdgeAgent._initialize_collectors.
    collector_type: str = Field(alias="type")
    enabled: bool = True
    config: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("collector_type")
    @classmethod
    def _known_type(cls, v: str) -> str:
        if v not in SUPPORTED_COLLECTOR_TYPES:
            raise ValueError(
                f"unknown collector_type '{v}'; "
                f"expected one of {', '.join(SUPPORTED_COLLECTOR_TYPES)}"
            )
        return v

    def packml(self) -> Optional[PackMLConfig]:
        """Parse the optional ``config.packml`` block, if present."""
        raw = self.config.get("packml")
        return PackMLConfig.model_validate(raw) if raw else None


class AgentConfig(BaseModel):
    """Top-level collector config document."""

    collectors: List[CollectorEntry] = Field(default_factory=list)


def validate_entries(raw: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Validate a raw collector list, skipping (not raising on) bad entries.

    Returns normalized dicts keyed with ``type`` (via alias) so callers can hand
    them straight to ``EdgeAgent._initialize_collectors``. Invalid entries are
    dropped; the caller is expected to log them.
    """
    normalized: List[Dict[str, Any]] = []
    for entry in raw:
        ce = CollectorEntry.model_validate(entry)
        normalized.append(ce.model_dump(by_alias=True))
    return normalized
