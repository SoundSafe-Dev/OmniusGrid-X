"""Data shedding and prioritization for ingestion workers"""

import time
from datetime import datetime, timezone
from typing import Dict, Optional, Tuple
from dataclasses import dataclass

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()


@dataclass
class PriorityConfig:
    """Configuration for data shedding priorities"""
    priority: int  # 1 = highest (never drop), 10 = lowest (drop first)
    max_age_seconds: int  # How old data can be before dropping
    sample_rate: float  # 1.0 = keep all, 0.1 = keep 10%


class DataSheddingManager:
    """
    Manages intelligent data shedding during system overload.
    
    Priority Tiers:
    1. CRITICAL: PackML state changes (never drop)
    2. HIGH: Alarms, errors, safety events
    3. MEDIUM: Telemetry at 1Hz (temperatures, positions)
    4. LOW: High-frequency telemetry (10Hz+ vibration data)
    5. LOWEST: Debug/verbose logging
    """
    
    def __init__(self):
        self._priorities: Dict[str, PriorityConfig] = {
            # Critical - never shed
            "packml_state": PriorityConfig(priority=1, max_age_seconds=300, sample_rate=1.0),
            "alarm": PriorityConfig(priority=1, max_age_seconds=300, sample_rate=1.0),
            "emergency_stop": PriorityConfig(priority=1, max_age_seconds=300, sample_rate=1.0),
            
            # High - shed only under extreme pressure
            "job_status": PriorityConfig(priority=2, max_age_seconds=60, sample_rate=1.0),
            "operator_action": PriorityConfig(priority=2, max_age_seconds=60, sample_rate=1.0),
            
            # Medium - standard telemetry
            "temp_nozzle": PriorityConfig(priority=3, max_age_seconds=30, sample_rate=1.0),
            "temp_bed": PriorityConfig(priority=3, max_age_seconds=30, sample_rate=1.0),
            "progress": PriorityConfig(priority=3, max_age_seconds=30, sample_rate=1.0),
            "position": PriorityConfig(priority=3, max_age_seconds=30, sample_rate=1.0),
            
            # Low - high frequency, can be downsampled
            "vibration": PriorityConfig(priority=4, max_age_seconds=10, sample_rate=0.1),
            "current": PriorityConfig(priority=4, max_age_seconds=10, sample_rate=0.1),
            "voltage": PriorityConfig(priority=4, max_age_seconds=10, sample_rate=0.1),
            "acceleration": PriorityConfig(priority=4, max_age_seconds=10, sample_rate=0.1),
            
            # Lowest - verbose/debug data
            "debug": PriorityConfig(priority=5, max_age_seconds=5, sample_rate=0.01),
            "verbose": PriorityConfig(priority=5, max_age_seconds=5, sample_rate=0.01),
        }
        
        self._load_shedding_active = False
        self._shedding_level = 0  # 0 = none, 1 = light, 2 = medium, 3 = heavy
        self._message_count = 0
        self._dropped_count = 0
        self._last_reset = datetime.now(timezone.utc)
        self._tenant_priorities: Dict[Tuple[str, str], PriorityConfig] = {}
        self._tenant_policy_refresh: Dict[str, float] = {}
        self._policy_cache_seconds = 60.0

    async def refresh_tenant_policies(
        self,
        db: AsyncSession,
        organization_id: str,
        *,
        force: bool = False,
    ) -> None:
        """Refresh one tenant's metric shedding overrides from the database."""
        organization_id = str(organization_id)
        now = time.monotonic()
        refreshed_at = self._tenant_policy_refresh.get(organization_id, 0.0)
        if not force and now - refreshed_at < self._policy_cache_seconds:
            return

        result = await db.execute(
            text(
                """
                SELECT metric_name, ingestion_priority,
                       ingestion_sample_rate, max_ingest_age_seconds
                FROM historian_retention_policies
                WHERE organization_id = :organization_id
                """
            ),
            {"organization_id": organization_id},
        )
        rows = result.mappings().all()

        self._tenant_priorities = {
            key: value
            for key, value in self._tenant_priorities.items()
            if key[0] != organization_id
        }
        for row in rows:
            self._tenant_priorities[(organization_id, row["metric_name"])] = (
                PriorityConfig(
                    priority=int(row["ingestion_priority"]),
                    max_age_seconds=int(row["max_ingest_age_seconds"]),
                    sample_rate=float(row["ingestion_sample_rate"]),
                )
            )
        self._tenant_policy_refresh[organization_id] = now

    def invalidate_tenant_policies(self, organization_id: str) -> None:
        """Force the next ingestion message to reload this tenant's policies."""
        self._tenant_policy_refresh.pop(str(organization_id), None)

    def _priority_for(
        self,
        metric_name: str,
        organization_id: Optional[str],
    ) -> PriorityConfig:
        base = self._priorities.get(
            metric_name,
            PriorityConfig(priority=3, max_age_seconds=30, sample_rate=1.0),
        )
        if organization_id is None or base.priority == 1:
            return base

        tenant_id = str(organization_id)
        return self._tenant_priorities.get(
            (tenant_id, metric_name),
            self._tenant_priorities.get((tenant_id, "*"), base),
        )

    def should_shed(
        self,
        metric_name: str,
        timestamp: datetime,
        organization_id: Optional[str] = None,
    ) -> bool:
        """
        Determine if a message should be shed based on priority and system load.
        
        Returns True if message should be dropped.
        """
        self._message_count += 1
        config = self._priority_for(metric_name, organization_id)
        
        # Priority 1 (critical) never shed
        if config.priority == 1:
            return False
        
        # Check if data is too old
        now = datetime.now(timezone.utc) if timestamp.tzinfo else datetime.now(timezone.utc)
        age = (now - timestamp).total_seconds()
        if age > config.max_age_seconds:
            logger.debug("shedding_stale_data", metric=metric_name, age_seconds=age)
            self._dropped_count += 1
            return True
        
        # If no load shedding active, keep everything
        if not self._load_shedding_active:
            return False
        
        # Apply shedding based on level and priority
        if self._shedding_level >= 3:  # Heavy shedding
            # Drop everything except priority 1
            if config.priority >= 2:
                self._dropped_count += 1
                return True
        
        elif self._shedding_level >= 2:  # Medium shedding
            # Drop priority 4+ and apply sample rates to 3
            if config.priority >= 4:
                self._dropped_count += 1
                return True
            if config.priority == 3:
                # Apply stricter sampling
                import random
                if random.random() > (config.sample_rate * 0.5):
                    self._dropped_count += 1
                    return True
        
        elif self._shedding_level >= 1:  # Light shedding
            # Apply configured sample rates to priority 4+
            if config.priority >= 4:
                import random
                if random.random() > config.sample_rate:
                    self._dropped_count += 1
                    return True
        
        return False
    
    def update_load_status(self, 
                          db_lag_seconds: float,
                          queue_depth: int,
                          memory_usage_percent: float):
        """Update shedding level based on system metrics"""
        # Calculate load score
        load_score = 0
        
        if db_lag_seconds > 10:
            load_score += 2
        elif db_lag_seconds > 5:
            load_score += 1
        
        if queue_depth > 50000:
            load_score += 2
        elif queue_depth > 10000:
            load_score += 1
        
        if memory_usage_percent > 90:
            load_score += 2
        elif memory_usage_percent > 75:
            load_score += 1
        
        # Set shedding level
        old_level = self._shedding_level
        
        if load_score >= 4:
            self._shedding_level = 3  # Heavy
            self._load_shedding_active = True
        elif load_score >= 3:
            self._shedding_level = 2  # Medium
            self._load_shedding_active = True
        elif load_score >= 2:
            self._shedding_level = 1  # Light
            self._load_shedding_active = True
        else:
            self._shedding_level = 0  # None
            self._load_shedding_active = False
        
        # Log state change
        if old_level != self._shedding_level:
            levels = ["none", "light", "medium", "heavy"]
            logger.warning(
                "load_shedding_level_changed",
                from_level=levels[old_level],
                to_level=levels[self._shedding_level],
                db_lag=db_lag_seconds,
                queue_depth=queue_depth,
                memory_percent=memory_usage_percent
            )
    
    def get_stats(self) -> Dict:
        """Get shedding statistics"""
        now = datetime.now(timezone.utc)
        window_seconds = (now - self._last_reset).total_seconds()
        
        return {
            "shedding_active": self._load_shedding_active,
            "shedding_level": self._shedding_level,
            "messages_processed": self._message_count,
            "messages_dropped": self._dropped_count,
            "drop_rate": (
                self._dropped_count / max(self._message_count, 1) * 100
            ),
            "window_seconds": window_seconds,
        }
    
    def reset_stats(self):
        """Reset counters"""
        self._message_count = 0
        self._dropped_count = 0
        self._last_reset = datetime.now(timezone.utc)


# Global instance for ingestion workers
data_shedder = DataSheddingManager()