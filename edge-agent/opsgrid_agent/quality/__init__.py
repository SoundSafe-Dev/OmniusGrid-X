"""Edge data-quality layer.

Sits between a collector's emitted reading and the store-and-forward buffer,
turning raw protocol payloads into validated, engineering-unit, canonical, and
change-filtered telemetry before it ever leaves the edge. Producing clean data
here means every downstream consumer (cloud historian, training pipeline,
dashboards) sees one trustworthy shape instead of per-protocol quirks.

Composition (see :mod:`.pipeline`):

    validate -> scale -> normalize units -> deadband/rate-limit -> flag/quarantine

Each stage is independent and individually testable; the pipeline wires them in
a fixed order and attaches a ``quality`` block to the reading envelope.
"""

from .flags import QualityFlag, QualityAction
from .pipeline import QualityPipeline, QualityResult
from .config import QualityConfig, MetricQualityRule

__all__ = [
    "QualityFlag",
    "QualityAction",
    "QualityPipeline",
    "QualityResult",
    "QualityConfig",
    "MetricQualityRule",
]
