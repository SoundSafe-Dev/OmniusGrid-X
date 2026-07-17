"""Telemetry timestamping + clock-skew correction (task 21).

Edge devices frequently lack NTP and drift; a wrong edge clock corrupts
time-series ordering and every downstream time-window calc. Rather than trust
the edge clock blindly, the agent samples the server's clock (from the ``Date``
of enrollment/heartbeat responses) and maintains an EWMA of the offset
``server - edge``. Timestamps are corrected by that offset before forward, and
the raw edge time is preserved alongside for audit.

The estimator is pure and clock-injected so it is deterministic under test.
"""

from datetime import datetime, timedelta, timezone
from typing import Optional

import structlog

logger = structlog.get_logger()


class ClockSkewEstimator:
    """Exponentially-weighted estimate of ``server_time - edge_time``."""

    def __init__(self, alpha: float = 0.2):
        # alpha weights the newest sample; 0.2 smooths jitter while tracking drift.
        self.alpha = alpha
        self._offset_seconds: Optional[float] = None
        self._samples = 0

    @property
    def offset_seconds(self) -> float:
        """Best current estimate of the correction to add to edge time (0 until sampled)."""
        return self._offset_seconds or 0.0

    @property
    def calibrated(self) -> bool:
        return self._offset_seconds is not None

    def observe(self, edge_time: datetime, server_time: datetime) -> float:
        """Fold a new (edge, server) observation into the offset estimate."""
        sample = (server_time - edge_time).total_seconds()
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
