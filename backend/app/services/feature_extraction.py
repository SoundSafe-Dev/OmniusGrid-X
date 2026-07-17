"""
Feature Vector Extraction Service for Cloud Egress
Implements data thinning - sends aggregated features instead of raw telemetry
"""

import asyncio
import json
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.database import AsyncSessionLocal
from app.services.cloud_gateway import cloud_gateway

logger = structlog.get_logger()


@dataclass
class FeatureVector:
    """Structured feature vector for ML inference"""
    asset_id: str
    timestamp: datetime
    features: Dict[str, float]
    packml_state: str
    derived_metrics: Dict[str, Any]
    window_seconds: int


class FeatureExtractor:
    """
    Extracts feature vectors from raw telemetry for cloud egress.
    
    Instead of sending 1000+ raw points/sec, we compute:
    - Rolling statistics (mean, std, min, max)
    - State transition frequencies
    - Derived efficiency metrics
    - Anomaly scores
    """
    
    def __init__(self, window_seconds: int = 60):
        self.window_seconds = window_seconds
        self._last_extraction: Dict[str, datetime] = {}
    
    async def extract_features(self, asset_id: str) -> Optional[FeatureVector]:
        """Extract feature vector for an asset over the time window"""
        now = datetime.now(timezone.utc)
        window_start = now - timedelta(seconds=self.window_seconds)
        
        async with AsyncSessionLocal() as session:
            # Get telemetry statistics
            stats = await self._get_telemetry_stats(session, asset_id, window_start, now)
            
            # Get current PackML state
            state_result = await session.execute(
                text(f"""
                    SELECT current_packml_state, last_seen
                    FROM assets
                    WHERE id = '{asset_id}'
                """)
            )
            row = state_result.fetchone()
            if not row:
                return None
            
            packml_state = row[0]
            last_seen = row[1]
            
            # Get state transition count
            transitions = await self._get_state_transitions(session, asset_id, window_start, now)
            
            # Compute derived metrics
            derived = self._compute_derived_metrics(stats, transitions)
            
            # Build feature vector
            features = {
                # Temperature features
                'temp_nozzle_mean': stats.get('temp_nozzle', {}).get('mean', 0),
                'temp_nozzle_std': stats.get('temp_nozzle', {}).get('std', 0),
                'temp_bed_mean': stats.get('temp_bed', {}).get('mean', 0),
                
                # Performance features
                'print_speed_mean': stats.get('print_speed', {}).get('mean', 0),
                'progress_velocity': derived.get('progress_velocity', 0),
                
                # Efficiency features
                'execute_time_ratio': derived.get('execute_ratio', 0),
                'alarm_frequency': derived.get('alarm_frequency', 0),
                
                # Quality features
                'temp_stability_score': derived.get('temp_stability', 0),
                'state_transition_count': transitions,
            }
            
            vector = FeatureVector(
                asset_id=asset_id,
                timestamp=now,
                features=features,
                packml_state=packml_state,
                derived_metrics=derived,
                window_seconds=self.window_seconds
            )
            
            self._last_extraction[asset_id] = now
            return vector
    
    async def _get_telemetry_stats(
        self, 
        session: AsyncSession, 
        asset_id: str, 
        start: datetime, 
        end: datetime
    ) -> Dict[str, Dict[str, float]]:
        """Get aggregated telemetry statistics"""
        result = await session.execute(
            text(f"""
                SELECT 
                    metric_name,
                    avg(value) as mean,
                    stddev_samp(value) as std,
                    min(value) as min_val,
                    max(value) as max_val,
                    count(*) as sample_count
                FROM telemetry
                WHERE asset_id = '{asset_id}'
                  AND time >= '{start.isoformat()}'
                  AND time <= '{end.isoformat()}'
                GROUP BY metric_name
            """)
        )
        
        stats = {}
        for row in result:
            stats[row[0]] = {
                'mean': float(row[1]) if row[1] else 0,
                'std': float(row[2]) if row[2] else 0,
                'min': float(row[3]) if row[3] else 0,
                'max': float(row[4]) if row[4] else 0,
                'count': int(row[5]) if row[5] else 0,
            }
        
        return stats
    
    async def _get_state_transitions(
        self,
        session: AsyncSession,
        asset_id: str,
        start: datetime,
        end: datetime
    ) -> int:
        """Count PackML state transitions in window"""
        result = await session.execute(
            text(f"""
                SELECT count(*)
                FROM packml_states
                WHERE asset_id = '{asset_id}'
                  AND state_entered_at >= '{start.isoformat()}'
                  AND state_entered_at <= '{end.isoformat()}'
            """)
        )
        return int(result.scalar() or 0)
    
    def _compute_derived_metrics(
        self, 
        stats: Dict, 
        transitions: int
    ) -> Dict[str, Any]:
        """Compute derived efficiency and quality metrics"""
        derived = {}
        
        # Temperature stability (inverse of std dev normalized)
        temp_std = stats.get('temp_nozzle', {}).get('std', 0)
        derived['temp_stability'] = max(0, 1 - (temp_std / 10))  # Score 0-1
        
        # Progress velocity (if available)
        progress_stats = stats.get('progress', {})
        if progress_stats.get('count', 0) > 1:
            derived['progress_velocity'] = (
                progress_stats.get('max', 0) - progress_stats.get('min', 0)
            ) / self.window_seconds
        else:
            derived['progress_velocity'] = 0
        
        # State transition frequency (transitions per minute)
        derived['transition_frequency'] = transitions / (self.window_seconds / 60)
        
        return derived
    
    def to_cloud_format(self, vector: FeatureVector) -> Dict:
        """Convert to cloud-optimized format for egress"""
        return {
            'type': 'feature_vector',
            'asset_id': vector.asset_id,
            'timestamp': vector.timestamp.isoformat(),
            'packml_state': vector.packml_state,
            'window_seconds': vector.window_seconds,
            'features': vector.features,
            'derived_metrics': vector.derived_metrics,
            'version': '1.0',
        }


class EgressScheduler:
    """
    Schedules feature vector extraction and cloud egress.
    Runs continuously to thin data before sending to cloud.
    """
    
    def __init__(self, interval_seconds: int = 60):
        self.interval = interval_seconds
        self.extractor = FeatureExtractor(window_seconds=interval_seconds)
        self._running = False
        self._assets: List[str] = []
    
    async def start(self):
        """Start the egress scheduler"""
        logger.info("egress_scheduler_starting", interval=self.interval)
        self._running = True
        
        # Load active assets
        await self._refresh_assets()
        
        while self._running:
            try:
                await self._process_egress_cycle()
                await asyncio.sleep(self.interval)
            except Exception as e:
                logger.error("egress_cycle_failed", error=str(e))
                await asyncio.sleep(10)  # Short retry on error
    
    async def _process_egress_cycle(self):
        """Process one egress cycle for all assets"""
        # Refresh asset list periodically
        if len(self._assets) == 0:
            await self._refresh_assets()
        
        for asset_id in self._assets:
            try:
                # Extract feature vector
                vector = await self.extractor.extract_features(asset_id)
                if not vector:
                    continue
                
                # Convert to cloud format
                cloud_data = self.extractor.to_cloud_format(vector)
                
                # Queue for egress (cloud gateway will batch and send)
                await cloud_gateway.queue_feature_vector(cloud_data)
                
                logger.debug(
                    "feature_vector_queued",
                    asset_id=asset_id,
                    features_count=len(vector.features)
                )
                
            except Exception as e:
                logger.error(
                    "asset_egress_failed",
                    asset_id=asset_id,
                    error=str(e)
                )
    
    async def _refresh_assets(self):
        """Refresh list of active assets"""
        async with AsyncSessionLocal() as session:
            result = await session.execute(
                text("""
                    SELECT id FROM assets 
                    WHERE is_active = true
                """)
            )
            self._assets = [row[0] for row in result]
            logger.info("assets_refreshed", count=len(self._assets))
    
    async def stop(self):
        """Stop the scheduler"""
        logger.info("egress_scheduler_stopping")
        self._running = False


# Global instances
feature_extractor = FeatureExtractor()
egress_scheduler = EgressScheduler()
