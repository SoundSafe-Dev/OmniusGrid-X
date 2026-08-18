"""Somewhere for an alarm to go when the cloud is unreachable (FS-755).

THE DEFECT. `LocalAlertingEngine` fires, and three things happen: a Prometheus counter
increments, a warning is logged, and the alert is appended to an in-memory list capped at
1,000 entries. That is the complete set of consequences.

None of them is an action during the outage the local engine exists for:

  * The counter is scraped over the network. In a DDIL scenario the scraper is on the far
    side of the link that is down, so the alarm increments a number nobody can read.
  * The log line goes to stdout, which in Kubernetes is collected over the same network,
    and on a bare gateway is a ring buffer.
  * The in-memory list is lost on restart — and a process restart is one of the more likely
    things to happen during the conditions that produced the alarm.

And the alert was never queued for uplink either. `analytics/pipeline.py` discarded the
return value of `alerting_tracker.record`, so when the link DID come back, the alert event
never travelled: only the raw reading did, leaving the backend to re-derive the breach if it
happened to hold the same rule. It did not know the edge had decided anything.

WHAT THIS ADDS: a durable local sink. An alarm is written to SQLite on the device before
anything else is attempted, so it survives a restart, a power cut and an indefinite outage,
and can be read back by an operator standing in front of the machine over `/alerts` on the
agent's own HTTP server — which is reachable when nothing else is.

WHY `synchronous=FULL` AND NOT THE BUFFER'S DEFAULT. The store-and-forward buffer runs at
SQLite's default durability because it handles millions of readings and losing the last few
milliseconds of vibration data to a power cut costs nothing. This table handles alarms at
human rates. Losing the last commit is the entire failure this file exists to prevent, so
every write goes to the platter before `record` returns. The cost is a few milliseconds per
alarm, which is affordable precisely because alarms are rare.

Kept in a SEPARATE database from the buffer, deliberately: the buffer is a bounded ring that
sheds rows to stay under a size cap, and an alarm record must not be shed to make room for
telemetry. Uplink is a separate concern — `coordinator` also queues the alarm as a tier-1
buffer message (see `opsgrid_agent/buffer/priority.py`), so it is both kept locally and sent
first when the link returns. Two sinks, because they answer two different questions.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import structlog

logger = structlog.get_logger()

#: How long a recorded alarm stays on the device. Long enough that a technician arriving the
#: next shift still sees what tripped; short enough to bound the file on a gateway with a
#: small partition.
DEFAULT_RETENTION_DAYS = 30


class LocalAlertSink:
    """Durable, restart-surviving local storage for alarms raised on the edge."""

    def __init__(
        self,
        path: str | Path,
        *,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self.path = Path(path)
        self.retention_days = retention_days
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.path)
        conn.execute("PRAGMA journal_mode=WAL")
        # See the module docstring: durability is the product here, not a tuning knob.
        conn.execute("PRAGMA synchronous=FULL")
        conn.execute("PRAGMA busy_timeout=5000")
        return conn

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS local_alerts (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    rule_id TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    metric_name TEXT NOT NULL,
                    value REAL,
                    threshold REAL,
                    condition TEXT,
                    severity TEXT NOT NULL,
                    message TEXT,
                    triggered_at TEXT NOT NULL,
                    recorded_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    uplink_queued INTEGER NOT NULL DEFAULT 0,
                    raw TEXT
                )
                """
            )
            conn.execute(
                "CREATE INDEX IF NOT EXISTS idx_local_alerts_triggered_at "
                "ON local_alerts(triggered_at DESC)"
            )
            conn.commit()

    def record(self, alert: Dict[str, Any]) -> Optional[int]:
        """Persist one alarm. Returns its row id, or None if the write failed.

        NEVER RAISES. This is called from the collector message path, and an alarm sink
        that can take down data collection is a worse failure than the one it prevents.
        A failed write is logged at error and counted by the caller.
        """
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    """
                    INSERT INTO local_alerts
                        (rule_id, asset_id, metric_name, value, threshold, condition,
                         severity, message, triggered_at, raw)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        str(alert.get("rule_id", "")),
                        str(alert.get("asset_id", "")),
                        str(alert.get("metric_name", "")),
                        _as_float(alert.get("value")),
                        _as_float(alert.get("threshold")),
                        str(alert.get("condition", "")),
                        str(alert.get("severity", "")),
                        str(alert.get("message", "")),
                        str(alert.get("timestamp") or _now_iso()),
                        json.dumps(alert, default=str),
                    ),
                )
                conn.commit()
                return cursor.lastrowid
        except (sqlite3.Error, OSError, TypeError, ValueError) as e:
            logger.error(
                "local_alert_write_failed",
                rule_id=alert.get("rule_id"),
                error=str(e),
                note="the alarm exists only in memory and will not survive a restart",
            )
            return None

    def mark_uplink_queued(self, alert_id: int) -> None:
        """Record that this alarm also reached the store-and-forward buffer.

        Deliberately separate from `record`: the local write must succeed on its own, and
        knowing WHICH alarms never got queued is how you tell "the link was down" (queued,
        undelivered) from "the alarm never left this box at all" (not queued).
        """
        try:
            with self._connect() as conn:
                conn.execute(
                    "UPDATE local_alerts SET uplink_queued = 1 WHERE id = ?", (alert_id,)
                )
                conn.commit()
        except sqlite3.Error as e:
            logger.error("local_alert_mark_failed", alert_id=alert_id, error=str(e))

    def recent(self, *, hours: int = 24, limit: int = 200) -> List[Dict[str, Any]]:
        """The most recent alarms, newest first — what `/alerts` serves."""
        cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
        try:
            with self._connect() as conn:
                conn.row_factory = sqlite3.Row
                rows = conn.execute(
                    """
                    SELECT id, rule_id, asset_id, metric_name, value, threshold,
                           condition, severity, message, triggered_at, uplink_queued
                    FROM local_alerts
                    WHERE triggered_at >= ?
                    ORDER BY triggered_at DESC, id DESC
                    LIMIT ?
                    """,
                    (cutoff, limit),
                ).fetchall()
            return [dict(row) for row in rows]
        except sqlite3.Error as e:
            logger.error("local_alert_read_failed", error=str(e))
            return []

    def count(self) -> int:
        try:
            with self._connect() as conn:
                return conn.execute("SELECT COUNT(*) FROM local_alerts").fetchone()[0]
        except sqlite3.Error:
            return 0

    def prune(self) -> int:
        """Drop alarms past the retention window. Returns how many went."""
        cutoff = (
            datetime.now(timezone.utc) - timedelta(days=self.retention_days)
        ).isoformat()
        try:
            with self._connect() as conn:
                cursor = conn.execute(
                    "DELETE FROM local_alerts WHERE triggered_at < ?", (cutoff,)
                )
                removed = cursor.rowcount or 0
                conn.commit()
            if removed:
                logger.info("local_alerts_pruned", removed=removed,
                            retention_days=self.retention_days)
            return removed
        except sqlite3.Error as e:
            logger.error("local_alert_prune_failed", error=str(e))
            return 0


def _as_float(value: Any) -> Optional[float]:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
