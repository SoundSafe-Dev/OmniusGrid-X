"""
Cloud Strategic Engine API - Macro-simulations and what-if scenarios
Handles strategic decisions like scheduling, long-term optimization
"""

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Any, Optional
from dataclasses import dataclass
import structlog

from app.core.config import settings
from app.services.cloud_gateway import cloud_gateway

logger = structlog.get_logger()


@dataclass
class StrategicRecommendation:
    """Recommendation from cloud strategic engine"""
    recommendation_id: str
    asset_id: Optional[str]  # None for fleet-wide
    recommendation_type: str  # 'schedule_change', 'parameter_tuning', 'maintenance_window'
    priority: int  # 1-5, 1 being highest
    description: str
    expected_impact: Dict[str, Any]  # e.g., {'oee_improvement': 0.05, 'cost_reduction': 1000}
    confidence: float
    simulation_basis: str  # Description of cloud simulation that generated this
    valid_until: datetime
    requires_approval: bool
    #: FS-434. `simulation_basis` is the provenance field, and for the demo seeds it read
    #: "Fleet OEE rollup + maintenance-window scheduler (14 days)" — a real-sounding
    #: derivation over the reader's own fleet, beside `confidence: 0.88`. The only tell
    #: that none of it was computed was an id beginning "demo-rec-", which no screen shows.
    #:
    #: A provenance field that lies is worse than no provenance field: it is the thing a
    #: careful reader checks. This makes the claim falsifiable in one boolean.
    simulated: bool = False


class CloudStrategicEngine:
    """
    Interface to cloud strategic engine.
    
    Responsibilities:
    - Receives recommendations from cloud (via secure gateway)
    - Presents strategic recommendations (not real-time commands)
    - Handles fleet-wide optimization (not per-asset control)
    - Requires operator approval for implementation
    
    Note: Cloud engine NEVER sends direct commands. It sends recommendations
    that are reviewed and approved by local operators.
    """
    
    def __init__(self):
        self.pending_recommendations: List[StrategicRecommendation] = []
        self.implemented_recommendations: List[StrategicRecommendation] = []
        self._running = False
    
    async def start(self):
        """Start the strategic engine interface"""
        logger.info("strategic_engine_starting")
        self._running = True
        
        # Start listening for cloud recommendations
        asyncio.create_task(self._recommendation_listener())

    def load_demo_recommendations(self) -> int:
        """Seed a few strategic recommendations for the offline demo.

        The cloud recommendation listener never connects offline, so the
        Strategic Engine page — and its approve/reject workflow — would be empty.
        Called from the API lifespan when ALLOW_DEV_TOKEN is set. Only seeds when
        the pending queue is empty, so it never duplicates real cloud recs.
        """
        if self.pending_recommendations:
            return 0
        now = datetime.now(timezone.utc)
        demos = [
            StrategicRecommendation(
                recommendation_id="demo-rec-1",
                asset_id=None,
                recommendation_type="maintenance_window",
                priority=1,
                description=(
                    "Shift CNC Mill #1 preventive maintenance to the Sunday "
                    "02:00–06:00 low-demand window to avoid a mid-week stop."
                ),
                expected_impact={"oee_improvement": 0.06, "cost_reduction": 4200},
                confidence=0.88,
                simulation_basis="Demo seed — not computed from this deployment's data. Stands in for: Fleet OEE rollup + maintenance-window scheduler (14 days)",
                simulated=True,
                valid_until=now + timedelta(days=7),
                requires_approval=True,
            ),
            StrategicRecommendation(
                recommendation_id="demo-rec-2",
                asset_id=None,
                recommendation_type="schedule_change",
                priority=2,
                description=(
                    "Rebalance line load away from the Machining Center during "
                    "the 14:00–18:00 peak to cut the acoustic-anomaly rate."
                ),
                expected_impact={"oee_improvement": 0.03, "throughput_gain": 0.04},
                confidence=0.79,
                simulation_basis="Demo seed — not computed from this deployment's data. Stands in for: Bottleneck analysis on seeded telemetry",
                simulated=True,
                valid_until=now + timedelta(days=5),
                requires_approval=True,
            ),
            StrategicRecommendation(
                recommendation_id="demo-rec-3",
                asset_id=None,
                recommendation_type="parameter_tuning",
                priority=3,
                description=(
                    "Lower Conveyor #1 target speed by 8% during high-vibration "
                    "periods to extend bearing RUL."
                ),
                expected_impact={"rul_extension_days": 45, "cost_reduction": 1500},
                confidence=0.72,
                simulation_basis="Demo seed — not computed from this deployment's data. Stands in for: Vibration-degradation slope + RUL model",
                simulated=True,
                valid_until=now + timedelta(days=10),
                requires_approval=True,
            ),
        ]
        self.pending_recommendations.extend(demos)
        logger.info("strategic_engine_demo_recommendations_loaded", count=len(demos))
        return len(demos)

    async def _recommendation_listener(self):
        """Listen for recommendations from cloud via secure gateway"""
        # In practice, this would subscribe to a topic from cloud gateway
        # For now, placeholder that checks periodically
        while self._running:
            await asyncio.sleep(60)
            # Check for new recommendations from cloud
            # This would come from cloud_gateway inbound queue
    
    async def receive_recommendation(self, recommendation: Dict):
        """
        Receive a recommendation from cloud strategic engine.
        Called by cloud gateway when new recommendation arrives.
        """
        try:
            rec = StrategicRecommendation(
                recommendation_id=recommendation['id'],
                asset_id=recommendation.get('asset_id'),
                recommendation_type=recommendation['type'],
                priority=recommendation['priority'],
                description=recommendation['description'],
                expected_impact=recommendation.get('expected_impact', {}),
                confidence=recommendation['confidence'],
                simulation_basis=recommendation.get('simulation_basis', ''),
                # STATED, not defaulted (FS-434). `False` is the strongest claim this model
                # makes — "a real cloud engine computed this" — so it has to be written at
                # the construction site rather than inherited from a dataclass default. The
                # payload wins if the cloud says otherwise; a cloud engine running its own
                # simulation is a thing that can happen and the reader should be told.
                simulated=bool(recommendation.get('simulated', False)),
                # fromisoformat on a tz-less ISO string yields a NAIVE datetime;
                # the expiry check below is aware (FS-96), so coerce naive->UTC.
                valid_until=(
                    lambda v: v if v.tzinfo else v.replace(tzinfo=timezone.utc)
                )(datetime.fromisoformat(recommendation['valid_until'])),
                requires_approval=recommendation.get('requires_approval', True)
            )
            
            # Filter expired recommendations
            if rec.valid_until < datetime.now(timezone.utc):
                logger.info("recommendation_expired", 
                           rec_id=rec.recommendation_id)
                return
            
            self.pending_recommendations.append(rec)
            
            logger.info("recommendation_received",
                       rec_id=rec.recommendation_id,
                       type=rec.recommendation_type,
                       priority=rec.priority)
            
            # If high priority, could alert operators immediately
            if rec.priority <= 2:
                await self._alert_high_priority(rec)
                
        except Exception as e:
            logger.error("recommendation_parse_failed", error=str(e))
    
    async def _alert_high_priority(self, rec: StrategicRecommendation):
        """Alert operators to high-priority recommendation"""
        # Could integrate with notification system
        logger.warning("high_priority_recommendation",
                      rec_id=rec.recommendation_id,
                      description=rec.description)
    
    async def approve_recommendation(self, rec_id: str, 
                                     operator_id: str,
                                     notes: Optional[str] = None) -> bool:
        """Operator approves a recommendation for implementation"""
        rec = self._find_recommendation(rec_id)
        if not rec:
            logger.error("recommendation_not_found", rec_id=rec_id)
            return False
        
        # Move to implemented
        self.pending_recommendations.remove(rec)
        self.implemented_recommendations.append(rec)
        
        # Report approval to cloud
        await cloud_gateway.queue_discrete_event(
            'recommendation_approved',
            {
                'recommendation_id': rec_id,
                'operator_id': operator_id,
                'approved_at': datetime.now(timezone.utc).isoformat(),
                'notes': notes,
            }
        )
        
        logger.info("recommendation_approved",
                   rec_id=rec_id,
                   operator_id=operator_id)
        
        return True
    
    async def reject_recommendation(self, rec_id: str,
                                    operator_id: str,
                                    reason: str) -> bool:
        """Operator rejects a recommendation"""
        rec = self._find_recommendation(rec_id)
        if not rec:
            return False
        
        self.pending_recommendations.remove(rec)
        
        # Report rejection to cloud
        await cloud_gateway.queue_discrete_event(
            'recommendation_rejected',
            {
                'recommendation_id': rec_id,
                'operator_id': operator_id,
                'rejected_at': datetime.now(timezone.utc).isoformat(),
                'reason': reason,
            }
        )
        
        logger.info("recommendation_rejected",
                   rec_id=rec_id,
                   reason=reason)
        
        return True
    
    def _find_recommendation(self, rec_id: str) -> Optional[StrategicRecommendation]:
        """Find recommendation by ID"""
        for rec in self.pending_recommendations:
            if rec.recommendation_id == rec_id:
                return rec
        return None
    
    def get_pending_recommendations(self, 
                                   min_priority: Optional[int] = None) -> List[StrategicRecommendation]:
        """Get list of pending recommendations"""
        recs = self.pending_recommendations
        
        # Filter expired
        now = datetime.now(timezone.utc)
        recs = [r for r in recs if r.valid_until > now]
        
        if min_priority:
            recs = [r for r in recs if r.priority <= min_priority]
        
        # Sort by priority
        return sorted(recs, key=lambda r: r.priority)
    
    def get_recommendation_history(self, 
                                   asset_id: Optional[str] = None,
                                   limit: int = 50) -> List[StrategicRecommendation]:
        """Get history of implemented recommendations"""
        recs = self.implemented_recommendations
        
        if asset_id:
            recs = [r for r in recs if r.asset_id == asset_id]
        
        return recs[-limit:]
    
    async def stop(self):
        """Stop the engine"""
        logger.info("strategic_engine_stopping")
        self._running = False


# Global instance
strategic_engine = CloudStrategicEngine()
