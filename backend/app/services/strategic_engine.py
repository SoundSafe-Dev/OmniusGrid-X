"""
Cloud Strategic Engine API - Macro-simulations and what-if scenarios
Handles strategic decisions like scheduling, long-term optimization
"""

import asyncio
from datetime import datetime, timedelta
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
                valid_until=datetime.fromisoformat(recommendation['valid_until']),
                requires_approval=recommendation.get('requires_approval', True)
            )
            
            # Filter expired recommendations
            if rec.valid_until < datetime.utcnow():
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
                'approved_at': datetime.utcnow().isoformat(),
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
                'rejected_at': datetime.utcnow().isoformat(),
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
        now = datetime.utcnow()
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
