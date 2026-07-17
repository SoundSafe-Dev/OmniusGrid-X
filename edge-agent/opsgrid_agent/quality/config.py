"""Configuration models for the edge data-quality pipeline.

A collector opts into quality processing by adding a ``quality`` block to its
``config``. The block is per-metric: each key in ``metrics`` names a field in the
reading payload and carries its transform/range/unit/deadband rules. Fields not
listed pass through untouched, so enabling quality on a collector is incremental.

Example (inside a collector entry's ``config``)::

    quality:
      staleness_seconds: 300
      quarantine_on_invalid: true
      metrics:
        temperature:
          unit: degF            # normalize degF -> canonical degC
          min: -40
          max: 250
          deadband: 0.5         # suppress changes smaller than 0.5 (canonical)
          min_interval_seconds: 1
          max_interval_seconds: 60
        pressure_raw:
          rename_to: pressure
          gain: 0.01            # scaled = raw * gain + offset
          offset: 0.0
          unit: psi
"""

from typing import Dict, Optional

from pydantic import BaseModel, ConfigDict, Field


class MetricQualityRule(BaseModel):
    """Quality rules for a single payload metric."""

    model_config = ConfigDict(extra="forbid")

    # --- scaling (task 7): applied first, on the raw value ---
    gain: float = 1.0
    offset: float = 0.0
    clamp_min: Optional[float] = None
    clamp_max: Optional[float] = None
    rename_to: Optional[str] = None  # emit under a different key after scaling

    # --- unit normalization (task 9) ---
    unit: Optional[str] = None  # source unit; converted to the dimension canonical

    # --- range validation (task 6), evaluated in canonical units ---
    min: Optional[float] = None
    max: Optional[float] = None

    # --- deadband / rate-limit (task 8) ---
    deadband: Optional[float] = None            # absolute change threshold
    deadband_percent: Optional[float] = None    # relative change threshold (0-100)
    min_interval_seconds: Optional[float] = None
    max_interval_seconds: Optional[float] = None  # heartbeat: force-emit after this


class QualityConfig(BaseModel):
    """Top-level quality block for one collector."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    staleness_seconds: Optional[float] = None
    quarantine_on_invalid: bool = True
    metrics: Dict[str, MetricQualityRule] = Field(default_factory=dict)
