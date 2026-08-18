"""Telemetry timestamping + clock-skew correction (task 21).

Edge devices frequently lack NTP and drift; a wrong edge clock corrupts
time-series ordering and every downstream time-window calc. Rather than trust
the edge clock blindly, the agent samples the server's clock (from the ``Date``
of enrollment/heartbeat responses) and maintains an EWMA of the offset
``server - edge``. Timestamps are corrected by that offset before forward, and
the raw edge time is preserved alongside for audit.

THE PARAGRAPH ABOVE WAS FALSE FOR THE LIFE OF THIS FILE (FS-760). `correct()` had no
callers anywhere in the agent. The offset was computed, smoothed, logged when it exceeded
five seconds, and used for two things — request-signature freshness and judging whether a
replayed command had expired — and **never applied to a single telemetry timestamp**. Every
reading this system has ingested carries the edge device's raw clock, and the docstring said
otherwise, which is worse than saying nothing: a reader checking whether time was handled
found a paragraph asserting it was.

TIME QUALITY IS THE OTHER HALF, and it is the half that matters more in a DDIL deployment.
The estimator can only sample while the cloud is reachable. During an outage the offset is
carried forward and the device keeps drifting, uncorrected and unmeasured — and an air-gapped
deployment never samples at all. Correcting silently in those states would be worse than not
correcting, because a corrected-looking timestamp invites trust it has not earned. So every
reading now carries what its time is actually worth:

    synced     a sample within the freshness window; the offset is current
    holdover   calibrated once, but the last sample is stale — drift is accumulating
               uncorrected since then, and how much is unknowable from here
    unsynced   never calibrated. The correction is zero and the edge clock is whatever
               the device says. The honest answer for air-gapped.

The estimator is pure and clock-injected so it is deterministic under test.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


class ClockSkewEstimator:
    """Exponentially-weighted estimate of ``server_time - edge_time``."""

    #: How long a sample stays fresh before the estimate is `holdover` rather than `synced`
    #: (FS-760). Four heartbeat intervals at the 30-second default: long enough that a
    #: couple of missed heartbeats on a flaky link do not flap the label, short enough that
    #: a genuine outage is reflected in the data within a couple of minutes.
    DEFAULT_FRESHNESS_SECONDS = 120.0

    def __init__(self, alpha: float = 0.2,
                 freshness_seconds: float = DEFAULT_FRESHNESS_SECONDS):
        # alpha weights the newest sample; 0.2 smooths jitter while tracking drift.
        self.alpha = alpha
        self.freshness_seconds = freshness_seconds
        self._offset_seconds: Optional[float] = None
        self._samples = 0
        #: When the last sample landed, in EDGE time. Deliberately edge time and not
        #: corrected time: this is only ever compared against `datetime.now()` on the same
        #: clock, so a drifting device still measures the interval correctly.
        self._last_observed_at: Optional[datetime] = None

    @property
    def offset_seconds(self) -> float:
        """Best current estimate of the correction to add to edge time (0 until sampled)."""
        return self._offset_seconds or 0.0

    @property
    def calibrated(self) -> bool:
        return self._offset_seconds is not None

    @property
    def last_observed_at(self) -> Optional[datetime]:
        return self._last_observed_at

    def quality(self, now: Optional[datetime] = None) -> str:
        """What this estimate is worth right now: synced, holdover or unsynced."""
        if self._offset_seconds is None or self._last_observed_at is None:
            return "unsynced"
        reference = now or datetime.now(timezone.utc)
        age = (reference - self._last_observed_at).total_seconds()
        return "synced" if age <= self.freshness_seconds else "holdover"

    def observe(self, edge_time: datetime, server_time: datetime) -> float:
        """Fold a new (edge, server) observation into the offset estimate."""
        sample = (server_time - edge_time).total_seconds()
        self._last_observed_at = edge_time
        if self._offset_seconds is None:
            self._offset_seconds = sample
        else:
            self._offset_seconds = (
                self.alpha * sample + (1 - self.alpha) * self._offset_seconds
            )
        self._samples += 1
        if abs(sample) > 5:
            logger.warning("clock_skew_detected", sample_seconds=round(sample, 3))
        return self._offset_seconds

    def correct(self, edge_time: datetime) -> datetime:
        """Apply the current offset to an edge timestamp."""
        if self._offset_seconds is None:
            return edge_time
        return edge_time + timedelta(seconds=self._offset_seconds)


def parse_http_date(value: str) -> Optional[datetime]:
    """Parse an RFC 7231 HTTP ``Date`` header to aware UTC, or ``None``."""
    from email.utils import parsedate_to_datetime

    try:
        dt = parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None
    if dt is None:
        return None
    return dt.astimezone(timezone.utc) if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
