"""SQLite Store-and-Forward Buffer for Edge Resilience"""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
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
        max_size_mb: int = 1000
    ):
        self.buffer_path = Path(buffer_path)
        self.retention_hours = retention_hours
        self.max_size_mb = max_size_mb
        self._lock = asyncio.Lock()
        
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
                    created_at TEXT DEFAULT CURRENT_TIMESTAMP
                )
            """)
            
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_messages_created_at 
                ON messages(created_at)
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
                (timestamp_edge, asset_id, topic, payload, sequence_num)
                VALUES (?, ?, ?, ?, ?)
                """,
                (timestamp_edge.isoformat(), asset_id, topic,
                 json.dumps(payload), sequence_num),
            )
            conn.commit()

    def _prune_oldest_sync(self, rows: int) -> None:
        """Delete the N oldest buffered rows.

        No VACUUM here: freeing internal pages is enough for the retry INSERT
        to succeed, while VACUUM needs the database's size in FREE disk space —
        unavailable by definition in the disk-full condition this recovers
        from — and would block the event loop rewriting the whole file. Space
        reclamation stays with the hourly enforce_size_limit cycle.
        """
        with sqlite3.connect(self.buffer_path) as conn:
            conn.execute(
                "DELETE FROM messages WHERE id IN "
                "(SELECT id FROM messages ORDER BY created_at ASC LIMIT ?)",
                (rows,),
            )
            conn.commit()

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
                timestamp_edge = timestamp_edge.replace(tzinfo=None)

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
                    ORDER BY timestamp_edge ASC
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
                        payload=row['payload'],
                        sequence_num=row['sequence_num'],
                        retry_count=row['retry_count'],
                        created_at=row['created_at']
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
    
    async def cleanup_old_messages(self) -> int:
        """Remove messages older than retention policy"""
        cutoff = datetime.now(timezone.utc) - timedelta(hours=self.retention_hours)
        
        async with self._lock:
            try:
                with sqlite3.connect(self.buffer_path) as conn:
                    cursor = conn.execute(
                        "DELETE FROM messages WHERE created_at < ?",
                        (cutoff.isoformat(),)
                    )
                    conn.commit()
                    deleted = cursor.rowcount
                
                if deleted > 0:
                    logger.info(
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

    async def enforce_size_limit(self, max_size_mb: Optional[int] = None) -> int:
        """Prune the oldest messages until the DB is under the size limit.

        The buffer is a bounded ring: when the on-disk size exceeds the cap we
        drop the oldest messages (by ``created_at``) so newest data survives.
        Returns the number pruned. Followed by a VACUUM to reclaim the space.
        """
        limit_mb = max_size_mb if max_size_mb is not None else self.max_size_mb
        if not limit_mb:
            return 0

        total_pruned = 0
        async with self._lock:
            try:
                while (self.buffer_path.stat().st_size / (1024 * 1024)) > limit_mb:
                    with sqlite3.connect(self.buffer_path) as conn:
                        cursor = conn.execute(
                            """
                            DELETE FROM messages WHERE id IN (
                                SELECT id FROM messages
                                ORDER BY created_at ASC, id ASC LIMIT 500
                            )
                            """
                        )
                        pruned = cursor.rowcount
                        conn.commit()
                    if pruned == 0:
                        break  # nothing left to prune
                    total_pruned += pruned
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
                size_bytes = self.buffer_path.stat().st_size if self.buffer_path.exists() else 0

                return {
                    "total_messages": total,
                    "failed_messages": failed,
                    "dead_lettered": dead_lettered,
                    "oldest_message": oldest,
                    "newest_message": newest,
                    "backfill_lag_seconds": self._age_seconds(oldest),
                    "size_mb": round(size_bytes / (1024 * 1024), 2),
                    "retention_hours": self.retention_hours
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
