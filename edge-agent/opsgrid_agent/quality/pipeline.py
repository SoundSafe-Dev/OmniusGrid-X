"""Quality pipeline: orchestration, flagging, and quarantine (task 10).

Wires the stages in a fixed order and reduces their flags to a single action:

    validate envelope -> per-metric [scale -> normalize unit -> range check]
    -> deadband gate -> decide FORWARD / QUARANTINE / DROP

The pipeline is per-collector (it owns a :class:`DeadbandFilter` whose state is
per asset+metric). It mutates a copy of the reading — scaled/normalized values
replace raw ones, and a ``quality`` block records the flags — so the caller can
forward the cleaned reading and route quarantined ones elsewhere.
"""

import copy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog

from . import units
from .config import QualityConfig
from .deadband import DeadbandFilter
from .flags import QualityAction, QualityFlag
from .transforms import apply_linear
from .validation import check_numeric, validate_envelope

logger = structlog.get_logger()

# Flags that mean the reading is untrustworthy (as opposed to merely filtered).
_INVALID_FLAGS = frozenset(
    {
        QualityFlag.MISSING_FIELD,
        QualityFlag.BAD_TIMESTAMP,
        QualityFlag.NON_FINITE,
        QualityFlag.OUT_OF_RANGE,
    }
)


@dataclass
class QualityResult:
    """Outcome of running one reading through the pipeline."""

    action: QualityAction
    reading: Dict[str, Any]
    flags: List[QualityFlag] = field(default_factory=list)

    @property
    def forwarded(self) -> bool:
        return self.action == QualityAction.FORWARD


class QualityPipeline:
    """Per-collector data-quality processor."""

    def __init__(self, config: QualityConfig):
        self.config = config
        self._deadband = DeadbandFilter()
        self._has_deadband = any(
            r.deadband is not None
            or r.deadband_percent is not None
            or r.min_interval_seconds is not None
            or r.max_interval_seconds is not None
            for r in config.metrics.values()
        )

    def process(self, reading: Dict[str, Any], now: Optional[datetime] = None) -> QualityResult:
        """Validate, transform, and gate a reading; return the decided action."""
        if not self.config.enabled:
            return QualityResult(QualityAction.FORWARD, reading)

        now = now or datetime.now(timezone.utc)
        out = copy.deepcopy(reading)
        flags: List[QualityFlag] = list(validate_envelope(out, now, self.config.staleness_seconds))

        payload: Dict[str, Any] = out.get("payload") if isinstance(out.get("payload"), dict) else {}
        asset_id = str(out.get("asset_id", ""))
        ts = now.timestamp()
        any_gate_forward = False

        for src_key, rule in self.config.metrics.items():
            if src_key not in payload:
                continue
            raw = payload[src_key]
            if isinstance(raw, bool) or not isinstance(raw, (int, float)):
                continue  # non-numeric configured field: leave as-is

            # 1) scale (task 7)
            value = apply_linear(
                float(raw), rule.gain, rule.offset, rule.clamp_min, rule.clamp_max
            )

            # 2) normalize unit (task 9)
            if rule.unit:
                conv = units.to_canonical(value, rule.unit)
                if conv is None:
                    flags.append(QualityFlag.UNKNOWN_UNIT)
                else:
                    value = conv[0]

            # 3) range / finiteness check (task 6, in canonical units)
            checked, mflags = check_numeric(value, rule.min, rule.max)
            flags.extend(mflags)
            if checked is not None:
                value = checked

            # write the cleaned value back (rename if requested)
            dest_key = rule.rename_to or src_key
            payload[dest_key] = value
            if rule.rename_to and rule.rename_to != src_key:
                payload.pop(src_key, None)

            # 4) deadband / rate-limit gate (task 8)
            has_gate = (
                rule.deadband is not None
                or rule.deadband_percent is not None
                or rule.min_interval_seconds is not None
                or rule.max_interval_seconds is not None
            )
            if has_gate:
                if self._deadband.should_forward(
                    asset_id,
                    dest_key,
                    value,
                    ts,
                    rule.deadband,
                    rule.deadband_percent,
                    rule.min_interval_seconds,
                    rule.max_interval_seconds,
                ):
                    any_gate_forward = True

        out["payload"] = payload

        # Decide the action. Invalidity wins over rate-limiting.
        invalid = [f for f in flags if f in _INVALID_FLAGS]
        if invalid and self.config.quarantine_on_invalid:
            action = QualityAction.QUARANTINE
        elif self._has_deadband and not any_gate_forward and not invalid:
            action = QualityAction.DROP
        else:
            action = QualityAction.FORWARD

        # Attach the quality block (deduped, stable order) for downstream visibility.
        seen: Dict[str, None] = {}
        for f in flags:
            seen.setdefault(f.value, None)
        out["quality"] = {"flags": list(seen.keys()), "action": action.value}

        return QualityResult(action, out, list(flags))
