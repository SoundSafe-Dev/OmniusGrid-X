"""SQLite Store-and-Forward Buffer for Edge Resilience"""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .encryption import BufferCipher
from .priority import DEFAULT_PRIORITY, NEVER_SHED_ABOVE, priority_for
from typing import List, Dict, Any, Optional
from dataclasses import dataclass, asdict
import structlog

logger = structlog.get_logger()


@dataclass
class BufferedMessage:
    """Message stored in local buffer for store-and-forward"""
    id: Optional[int] = None
    timestamp_edge: str = ""
    asset_id: str = ""
    topic: str = ""
    payload: str = ""
    sequence_num: int = 0
    retry_count: int = 0
    created_at: Optional[str] = None
    priority: int = DEFAULT_PRIORITY


class StoreForwardBuffer:
    """
    SQLite-based store-and-forward buffer for edge resilience.
    
    Handles:
    - Local message buffering during network outages
    - Automatic backfill when connection restored
    - Configurable retention policies
    - Timestamp preservation (edge-time, not server-time)
    """
    
    def __init__(
        self,
        buffer_path: str = "/var/lib/opsgrid-agent/buffer.db",
        retention_hours: int = 24,
        max_size_mb: int = 1000,
        cipher: Optional["BufferCipher"] = None,
    ):
        self.buffer_path = Path(buffer_path)
        self.retention_hours = retention_hours
        self.max_size_mb = max_size_mb
        self._lock = asyncio.Lock()
        # PAYLOADS ARE ENCRYPTED AT REST WHEN A KEY IS CONFIGURED (FS-749). Constructed
        # here rather than passed in by every caller so a buffer cannot be created without
        # one; with no key it is a pass-through, and with BUFFER_ENCRYPTION_REQUIRED=true
        # its constructor raises instead of quietly writing cleartext to a disk that may
        # walk out of the building.
        self.cipher = cipher if cipher is not None else BufferCipher()
        # A PER-BUFFER LOSS LEDGER (FS-753). Losses were counted only into global
        # Prometheus counters, which cannot be reconciled against a single buffer — so
        # `get_stats()` had no `dropped` key at all, and `main.py`'s
        # `stats.get('dropped', 0)` meant the heartbeat reported **zero dropped, always**,
        # for as long as the field had existed.
        #
        # It is also what makes a conservation law checkable:
        #     produced == sent + still_buffered + dead_lettered + dropped + expired
        # Without a per-instance count there is no way to assert that a DDIL scenario lost
        # nothing, only that some global counter moved.
        self.losses = {"dropped": 0, "expired": 0, "dead_lettered": 0}
        
        # Ensure directory exists
        self.buffer_path.parent.mkdir(parents=True, exist_ok=True)

        # Initialize database (quarantining a corrupt file rather than crashing)
        self._init_db_with_recovery()

    def _init_db_with_recovery(self):
        """Initialize the DB; quarantine-and-recreate on corruption.

        A power-cut mid-write can corrupt SQLite. Telemetry buffering must come
        back up: the corrupt file is moved aside (kept for forensics/possible
        manual salvage) and a fresh buffer is created — losing the buffered
        backlog is preferable to an agent that can never start again.
        """
        try:
            self._init_db()
            with sqlite3.connect(self.buffer_path) as conn:
                result = conn.execute("PRAGMA integrity_check").fetchone()
            if result and result[0] != "ok":
                raise sqlite3.DatabaseError(f"integrity_check: {result[0]}")
        except sqlite3.DatabaseError as e:
            quarantine = self.buffer_path.with_suffix(
                f".corrupt-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            )
            logger.error(
                "buffer_corrupt_quarantining",
                path=str(self.buffer_path), quarantine=str(quarantine), error=str(e),
            )
            # Move the WAL/SHM sidecars WITH the main file: a leftover -wal
            # would be replayed into the fresh database on first connect
            # (recreating the corruption), and the forensic copy needs its WAL
            # to be complete anyway.
            for suffix in ("", "-wal", "-shm"):
                side = Path(str(self.buffer_path) + suffix)
                if not side.exists():
                    continue
                try:
                    side.rename(Path(str(quarantine) + suffix))
                except OSError:
                    side.unlink(missing_ok=True)
            self._init_db()

    def _init_db(self):
        """Initialize SQLite database with required tables"""
        with sqlite3.connect(self.buffer_path) as conn:
            # WAL survives crashes far better than the default rollback journal,
            # and busy_timeout prevents spurious 'database is locked' failures
            # between the async worker tasks sharing this file.
            conn.execute("PRAGMA journal_mode=WAL")
            conn.execute("PRAGMA busy_timeout=5000")
            conn.execute("""
                CREATE TABLE IF NOT EXISTS messages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_edge TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    sequence_num INTEGER NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
                    priority INTEGER NOT NULL DEFAULT 3
                )
            """)

            # A buffer written by an agent from before FS-754 has no `priority`
            # column, and an agent in the field is routinely older than the release
            # that adds one. ADD COLUMN with a default backfills every existing row to
            # tier 3 in place, which is the right answer: those rows were classified by
            # nothing, so they are process data until a new reading says otherwise.
            existing = {r[1] for r in conn.execute("PRAGMA table_info(messages)")}
            if "priority" not in existing:
                conn.execute(
                    "ALTER TABLE messages ADD COLUMN priority INTEGER NOT NULL DEFAULT 3"
                )

            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_created_at 
                ON messages(created_at)
            """)

            # The drain order (FS-754). Without this index every batch fetch sorts the
            # whole table, and the backlog this runs against is measured in hundreds of
            # thousands of rows — the ordering would be correct and unusably slow, which
            # for an emergency stop is the same defect wearing a different hat.
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_priority
                ON messages(priority ASC, timestamp_edge ASC)
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_asset
                ON messages(asset_id, timestamp_edge)
            """)

            # Dead-letter table for messages that exhausted their retries, so
            # they leave the active table (freeing it) but stay observable /
            # retainable instead of being stranded forever.
            conn.execute("""
                CREATE TABLE IF NOT EXISTS dead_letters (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp_edge TEXT NOT NULL,
                    asset_id TEXT NOT NULL,
                    topic TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    sequence_num INTEGER NOT NULL,
                    retry_count INTEGER DEFAULT 0,
                    created_at TEXT,
                    died_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)

            conn.commit()
        
        logger.info(
            "buffer_initialized",
            path=str(self.buffer_path),
            retention_hours=self.retention_hours
        )
    
    async def store(
        self,
        timestamp_edge: datetime,
        asset_id: str,
        topic: str,
        payload: Dict[str, Any],
        sequence_num: int = 0
    ) -> bool:
        """Store a message in the local buffer"""
        async with self._lock:
            try:
                self._insert_row(timestamp_edge, asset_id, topic, payload, sequence_num)

                logger.debug(
                    "message_buffered",
                    asset_id=asset_id,
                    topic=topic,
                    timestamp=timestamp_edge.isoformat()
                )
                return True
                
            except sqlite3.Error as e:
                logger.error(
                    "buffer_store_failed",
                    asset_id=asset_id,
                    error=str(e)
                )
                # SQLITE_FULL ("database or disk is full") only: reclaim space
                # by pruning the oldest rows, then retry ONCE so the newest
                # reading survives. Deliberately NOT matching generic
                # "disk I/O error" (bad sector / fsync failure) — pruning there
                # would destroy backlog without recovering anything.
                if "full" in str(e).lower():
                    try:
                        self._prune_oldest_sync(500)
                        self._insert_row(timestamp_edge, asset_id, topic,
                                         payload, sequence_num)
                        logger.warning("buffer_store_recovered_after_prune",
                                       asset_id=asset_id)
                        return True
                    except sqlite3.Error as retry_err:
                        logger.error("buffer_store_retry_failed",
                                     asset_id=asset_id, error=str(retry_err))
                return False

    def _insert_row(self, timestamp_edge: datetime, asset_id: str, topic: str,
                    payload: Dict[str, Any], sequence_num: int) -> None:
        with sqlite3.connect(self.buffer_path) as conn:
            conn.execute(
                """
                INSERT INTO messages
                (timestamp_edge, asset_id, topic, payload, sequence_num, priority)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (timestamp_edge.isoformat(), asset_id, topic,
                 self.cipher.encrypt(json.dumps(payload)), sequence_num,
                 priority_for(topic, payload)),
            )
            conn.commit()

    def _prune_oldest_sync(self, rows: int) -> int:
        """Delete the N oldest buffered rows, and return how many went.

        Cheapest-first (FS-754): `ORDER BY priority DESC, created_at ASC`, so tier-5
        debug is discarded before a tier-1 emergency stop that has been waiting longer.
        The old ordering was age alone, which on a disk-full event threw away exactly
        the readings the buffer exists to preserve.

        No VACUUM here: freeing internal pages is enough for the retry INSERT
        to succeed, while VACUUM needs the database's size in FREE disk space —
        unavailable by definition in the disk-full condition this recovers
        from — and would block the event loop rewriting the whole file. Space
        reclamation stays with the hourly enforce_size_limit cycle.

        THESE ARE COUNTED (FS-504). This returned None and its caller discarded the number,
        so up to 500 UNDELIVERED readings disappeared per disk-full event with nothing
        recording it. The buffer's whole purpose is that a reading survives the uplink being
        down; this is the one path where it does not, and it was the one path with no counter.

        `test_every_buffer_loss_is_counted.py` allowlisted it, with the reason "emergency
        space reclamation; the hourly path counts the steady state". That was **false**:
        `enforce_size_limit` counts `cursor.rowcount` — rows ITS OWN delete removed — so rows
        this method already deleted are gone from the table and can never appear in that
        count. The allowlist entry is deleted rather than reworded.
        """
        with sqlite3.connect(self.buffer_path) as conn:
            cursor = conn.execute(
                "DELETE FROM messages WHERE id IN "
                "(SELECT id FROM messages ORDER BY priority DESC, created_at ASC "
                " LIMIT ?)",
                (rows,),
            )
            pruned = cursor.rowcount or 0
            conn.commit()

        if pruned:
            # Imported here rather than at module scope: the buffer is imported by nearly
            # everything, and a top-level metrics import makes a cycle easy to introduce.
            from .. import metrics

            metrics.record_dropped(pruned)
            self.losses['dropped'] += pruned
            logger.warning(
                "buffer_pruned_for_space",
                pruned=pruned,
                note="undelivered readings discarded to recover from a full disk",
            )
        return pruned

    async def store_message(self, message: Dict[str, Any]) -> bool:
        """Adapter for coordinator message dicts -> store()."""
        raw_ts = message.get("timestamp_edge") or message.get("timestamp")
        if raw_ts is None:
            timestamp_edge = datetime.now(timezone.utc)
        elif isinstance(raw_ts, datetime):
            timestamp_edge = raw_ts
        else:
            ts_str = str(raw_ts).replace("Z", "+00:00")
            timestamp_edge = datetime.fromisoformat(ts_str)
            if timestamp_edge.tzinfo:
                # Convert to UTC *before* dropping the tzinfo. A bare
                # replace(tzinfo=None) on a non-UTC aware time (e.g. +05:00)
                # keeps the local wall-clock reading, which _age_seconds then
                # re-interprets as UTC — corrupting stored edge-time and
                # backfill-lag by the offset. astimezone() moves the instant to
                # UTC first so the naive value it stores is genuinely UTC.
                timestamp_edge = timestamp_edge.astimezone(timezone.utc).replace(
                    tzinfo=None
                )

        asset_id = message.get("asset_id", "unknown")
        payload = message.get("payload", {})
        if not isinstance(payload, dict):
            payload = {"value": payload}

        topic = message.get("topic") or f"telemetry.{asset_id}"
        sequence_num = message.get("sequence_num", 0)

        return await self.store(
            timestamp_edge=timestamp_edge,
            asset_id=asset_id,
            topic=topic,
            payload=payload,
            sequence_num=sequence_num,
        )
    
    async def get_pending_messages(
        self,
        batch_size: int = 1000,
        max_retry: int = 5
    ) -> List[BufferedMessage]:
        """Retrieve pending messages for backfill"""
        async with self._lock:
            with sqlite3.connect(self.buffer_path) as conn:
                conn.row_factory = sqlite3.Row
                cursor = conn.execute(
                    """
                    SELECT * FROM messages 
                    WHERE retry_count < ?
                    ORDER BY priority ASC, timestamp_edge ASC
                    LIMIT ?
                    """,
                    (max_retry, batch_size)
                )
                
                rows = cursor.fetchall()
                
                messages = []
                for row in rows:
                    messages.append(BufferedMessage(
                        id=row['id'],
                        timestamp_edge=row['timestamp_edge'],
                        asset_id=row['asset_id'],
                        topic=row['topic'],
                        payload=self.cipher.decrypt(row['payload']),
                        sequence_num=row['sequence_num'],
                        retry_count=row['retry_count'],
                        created_at=row['created_at'],
                        priority=row['priority'],
                    ))
                
                return messages
    
    async def mark_sent(self, message_ids: List[int]) -> bool:
        """Mark messages as successfully sent (remove from buffer)"""
        if not message_ids:
            return True
        
        async with self._lock:
            try:
                with sqlite3.connect(self.buffer_path) as conn:
                    placeholders = ','.join('?' * len(message_ids))
                    conn.execute(
                        f"DELETE FROM messages WHERE id IN ({placeholders})",
                        message_ids
                    )
                    conn.commit()
                
                logger.debug(
                    "messages_sent_and_removed",
                    count=len(message_ids)
                )
                return True
                
            except sqlite3.Error as e:
                logger.error(
                    "mark_sent_failed",
                    error=str(e)
                )
                return False
    
    async def increment_retry(self, message_ids: List[int]) -> bool:
        """Increment retry count for failed messages"""
        if not message_ids:
            return True
        
        async with self._lock:
            try:
                with sqlite3.connect(self.buffer_path) as conn:
                    placeholders = ','.join('?' * len(message_ids))
                    conn.execute(
                        f"""
                        UPDATE messages 
                        SET retry_count = retry_count + 1 
                        WHERE id IN ({placeholders})
                        """,
                        message_ids
                    )
                    conn.commit()
                return True
            except sqlite3.Error as e:
                logger.error("increment_retry_failed", error=str(e))
                return False
    
    async def reset_retry_counts(self) -> int:
        """Clear every row's retry counter, and return how many were cleared (FS-757).

        CALLED WHEN THE UPLINK IS REBUILT, not on a schedule. `retry_count` records failures
        against a producer that no longer exists — a broker that was rejecting, a connection
        that was half-open, a certificate that had expired. Carrying those counts across a
        reconnect means the new link inherits the old one's verdict, and rows that failed
        five times against the dead producer are excluded from the very first drain the new
        one performs.

        That was the mechanism behind FS-753's stranded-backlog finding: five failures
        against a broker that is reachable but rejecting is an utterly ordinary degraded
        reconnect, and it permanently hid rows from `get_pending_messages`. Resetting on a
        genuine link-level event is the narrowest fix that removes it — the counter still
        does its job WITHIN one link's lifetime, which is where a poison message shows up.
        """
        async with self._lock:
            try:
                with sqlite3.connect(self.buffer_path) as conn:
                    cursor = conn.execute(
                        "UPDATE messages SET retry_count = 0 WHERE retry_count > 0"
                    )
                    cleared = cursor.rowcount or 0
                    conn.commit()
                if cleared:
                    logger.info(
                        "retry_counts_reset",
                        rows=cleared,
                        note="a new uplink does not inherit the old one's failures",
                    )
                return cleared
            except sqlite3.Error as e:
                logger.error("retry_reset_failed", error=str(e))
                return 0

    async def cleanup_old_messages(self) -> int:
        """Remove messages older than retention policy"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.retention_hours)

        async with self._lock:
            try:
                with sqlite3.connect(self.buffer_path) as conn:
                    # created_at is written by SQLite's CURRENT_TIMESTAMP as
                    # "YYYY-MM-DD HH:MM:SS" (space separator, no offset), while
                    # cutoff.isoformat() is "YYYY-MM-DDTHH:MM:SS+00:00" (T +
                    # offset). A raw string "<" compares the space (0x20)
                    # against the "T" (0x54), so every row sharing the cutoff's
                    # calendar date sorted as older and got deleted regardless
                    # of its time-of-day — silently wiping fresh telemetry under
                    # short retentions. datetime() normalizes both operands to
                    # UTC "YYYY-MM-DD HH:MM:SS" so the comparison is by instant.
                    cursor = conn.execute(
                        "DELETE FROM messages "
                        "WHERE datetime(created_at) < datetime(?)",
                        (cutoff.isoformat(),)
                    )
                    conn.commit()
                    deleted = cursor.rowcount
                    self.losses['expired'] += deleted
                
                if deleted > 0:
                    # WARNING, not info (FS-458). Rows in `messages` are UNDELIVERED —
                    # `mark_sent` removes them on success — so every row counted here
                    # is telemetry that was captured and then destroyed without reaching
                    # the cloud. The other two loss paths in this file already warn.
                    logger.warning(
                        "old_messages_cleaned",
                        deleted=deleted,
                        retention_hours=self.retention_hours
                    )
                return deleted
                
            except sqlite3.Error as e:
                logger.error("cleanup_failed", error=str(e))
                return 0
    
    async def move_exhausted_to_dead_letter(self, max_retry: int = 5) -> int:
        """Move retry-exhausted messages to the dead-letter table.

        Messages with ``retry_count >= max_retry`` are excluded from
        ``get_pending_messages`` and would otherwise accumulate forever. Moving
        them frees the active table and keeps them observable/retainable.
        Returns the number moved.
        """
        async with self._lock:
            try:
                with sqlite3.connect(self.buffer_path) as conn:
                    cursor = conn.execute(
                        """
                        INSERT INTO dead_letters
                            (timestamp_edge, asset_id, topic, payload,
                             sequence_num, retry_count, created_at)
                        SELECT timestamp_edge, asset_id, topic, payload,
                               sequence_num, retry_count, created_at
                        FROM messages WHERE retry_count >= ?
                        """,
                        (max_retry,),
                    )
                    moved = cursor.rowcount
                    self.losses['dead_lettered'] += moved
                    conn.execute(
                        "DELETE FROM messages WHERE retry_count >= ?", (max_retry,)
                    )
                    conn.commit()

                if moved > 0:
                    logger.warning(
                        "messages_dead_lettered", count=moved, max_retry=max_retry
                    )
                return moved
            except sqlite3.Error as e:
                logger.error("dead_letter_move_failed", error=str(e))
                return 0

    def _on_disk_bytes(self, *, checkpoint: bool = False) -> int:
        """Everything this buffer occupies on disk, not just the main database file.

        FOUND BY THE FS-754 SHED SCENARIO. Both size measurements read
        `buffer_path.stat().st_size` alone. In WAL mode — which this buffer enables at
        init — freshly written rows live in `buffer.db-wal` until a checkpoint folds them
        in, so the main file stayed at 4 KB while 2 MB of readings sat beside it. The
        consequences were both directions of wrong: `enforce_size_limit` never fired until
        SQLite happened to auto-checkpoint, so the buffer could exceed its configured cap,
        and `get_stats()["size_mb"]` under-reported the disk a field device was actually
        using — the number an operator sizes a partition from.

        This is the same blind spot that let the buffer-encryption test pass for the wrong
        reason (FS-749): reading only `buffer.db` and finding nothing proves nothing when
        the content is in the sidecar.

        `checkpoint=True` truncates the WAL first, so the caller that is about to act on
        the number gets one that is both accurate and stable. Read-only callers pass False
        rather than mutate files on a metrics path.
        """
        if checkpoint:
            try:
                with sqlite3.connect(self.buffer_path) as conn:
                    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            except sqlite3.Error as e:
                # Not fatal: the sum below is still closer to the truth than the main
                # file alone, it is just measured against an un-truncated WAL.
                logger.warning("buffer_checkpoint_failed", error=str(e))

        total = 0
        for suffix in ("", "-wal", "-shm"):
            candidate = Path(f"{self.buffer_path}{suffix}")
            if candidate.exists():
                total += candidate.stat().st_size
        return total

    async def enforce_size_limit(self, max_size_mb: Optional[int] = None) -> int:
        """Prune the oldest messages until the DB is under the size limit.

        The buffer is a bounded ring. It sheds by PRIORITY first and age second
        (FS-754): tier-5 diagnostics die before tier-4 vibration, which dies before an
        alarm. It used to shed strictly by ``created_at``, which meant a full buffer
        discarded the oldest emergency stop to keep the newest debug line.

        It does NOT refuse to shed tiers 1-3 once the cheap rows are gone. Refusing
        would mean the buffer stays over its cap and the next *incoming* reading fails
        to store — trading a stale safety record for a live one, which is the worse
        trade. Instead it logs `buffer_shed_protected_tier` at WARNING, so the one case
        that should never be routine is visible rather than silent.

        Returns the number pruned. Followed by a VACUUM to reclaim the space.
        """
        limit_mb = max_size_mb if max_size_mb is not None else self.max_size_mb
        if not limit_mb:
            return 0

        total_pruned = 0
        async with self._lock:
            try:
                while (self._on_disk_bytes(checkpoint=True)
                       / (1024 * 1024)) > limit_mb:
                    with sqlite3.connect(self.buffer_path) as conn:
                        # Selected before deleting rather than DELETE..RETURNING so the
                        # protected-tier count is available on every SQLite this agent
                        # runs on, including the 3.34 shipped by older distributions.
                        victims = conn.execute(
                            """
                            SELECT id, priority FROM messages
                            ORDER BY priority DESC, created_at ASC, id ASC
                            LIMIT 500
                            """
                        ).fetchall()
                        if not victims:
                            break  # nothing left to prune
                        conn.executemany(
                            "DELETE FROM messages WHERE id = ?",
                            [(row[0],) for row in victims],
                        )
                        pruned = len(victims)
                        conn.commit()
                    total_pruned += pruned
                    self.losses['dropped'] += pruned
                    protected = sum(1 for row in victims
                                    if row[1] <= NEVER_SHED_ABOVE)
                    if protected:
                        logger.warning(
                            "buffer_shed_protected_tier",
                            count=protected,
                            note="safety/operational data discarded for space; "
                                 "the cheap tiers were already gone",
                        )
                    # VACUUM to actually reclaim disk so the next size check is real
                    # (DELETE alone does not shrink the SQLite file).
                    with sqlite3.connect(self.buffer_path) as conn:
                        conn.execute("VACUUM")
                        conn.commit()
            except sqlite3.Error as e:
                logger.error("enforce_size_limit_failed", error=str(e))

        if total_pruned:
            logger.warning(
                "buffer_size_limit_pruned", pruned=total_pruned, limit_mb=limit_mb
            )
        return total_pruned

    async def get_stats(self) -> Dict[str, Any]:
        """Get buffer statistics"""
        async with self._lock:
            with sqlite3.connect(self.buffer_path) as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM messages")
                total = cursor.fetchone()[0]
                
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM messages WHERE retry_count > 0"
                )
                failed = cursor.fetchone()[0]
                
                cursor = conn.execute(
                    "SELECT MIN(timestamp_edge), MAX(timestamp_edge) FROM messages"
                )
                oldest, newest = cursor.fetchone()

                cursor = conn.execute("SELECT COUNT(*) FROM dead_letters")
                dead_lettered = cursor.fetchone()[0]

                # Get file size
                size_bytes = self._on_disk_bytes()

                return {
                    "total_messages": total,
                    "failed_messages": failed,
                    "dead_lettered": dead_lettered,
                    "oldest_message": oldest,
                    "newest_message": newest,
                    "backfill_lag_seconds": self._age_seconds(oldest),
                    "size_mb": round(size_bytes / (1024 * 1024), 2),
                    "retention_hours": self.retention_hours,
                    # FS-753. `main.py` has always read `stats.get('dropped', 0)` for the
                    # heartbeat, and this dict has never had the key — so every heartbeat
                    # since the field was added reported zero dropped regardless of how
                    # many rows the size limiter had pruned. The default made it silent.
                    "dropped": self.losses["dropped"],
                    "expired": self.losses["expired"],
                }

    @staticmethod
    def _age_seconds(timestamp_edge: Optional[str]) -> float:
        """Seconds between the given edge timestamp and now (0.0 if unknown)."""
        if not timestamp_edge:
            return 0.0
        try:
            ts = datetime.fromisoformat(timestamp_edge)
            if ts.tzinfo is None:
                # Buffered edge timestamps are naive-UTC ISO strings; coerce so
                # the aware `now` subtraction (FS-96 sweep) can't raise (a raise
                # here was swallowed below and silently reported lag=0).
                ts = ts.replace(tzinfo=timezone.utc)
            return max(0.0, (datetime.now(timezone.utc) - ts).total_seconds())
        except (ValueError, TypeError):
            return 0.0
    
    async def vacuum(self):
        """Compact database file"""
        async with self._lock:
            with sqlite3.connect(self.buffer_path) as conn:
                conn.execute("VACUUM")
                conn.commit()
            logger.info("buffer_vacuum_completed")
