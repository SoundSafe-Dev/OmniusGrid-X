"""SQLite Store-and-Forward Buffer for Edge Resilience"""

import asyncio
import json
import sqlite3
from datetime import datetime, timedelta
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
        
        # Initialize database
        self._init_db()
    
    def _init_db(self):
        """Initialize SQLite database with required tables"""
        with sqlite3.connect(self.buffer_path) as conn:
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
                with sqlite3.connect(self.buffer_path) as conn:
                    conn.execute(
                        """
                        INSERT INTO messages 
                        (timestamp_edge, asset_id, topic, payload, sequence_num)
                        VALUES (?, ?, ?, ?, ?)
                        """,
                        (
                            timestamp_edge.isoformat(),
                            asset_id,
                            topic,
                            json.dumps(payload),
                            sequence_num
                        )
                    )
                    conn.commit()
                
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
                return False
    
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
        cutoff = datetime.utcnow() - timedelta(hours=self.retention_hours)
        
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
            now = datetime.now(ts.tzinfo) if ts.tzinfo else datetime.utcnow()
            return max(0.0, (now - ts).total_seconds())
        except (ValueError, TypeError):
            return 0.0
    
    async def vacuum(self):
        """Compact database file"""
        async with self._lock:
            with sqlite3.connect(self.buffer_path) as conn:
                conn.execute("VACUUM")
                conn.commit()
            logger.info("buffer_vacuum_completed")
