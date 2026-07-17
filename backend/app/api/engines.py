"""API routes for AI Engine management"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
from uuid import UUID
from typing import Dict, Any
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.auth import get_current_active_user
from app.services.tactical_engine import tactical_engine
from app.services.strategic_engine import strategic_engine, StrategicRecommendation
from app.services.mlops_pipeline import mlops_pipeline
from app.services.cloud_gateway import cloud_gateway
from app.db.database import get_db
from app.models.domain_interaction import CorrelationScenario
from app.services.correlation_ai_engine import correlation_ai_engine

from app.middleware.rbac import require_admin, require_operator_or_admin

router = APIRouter(dependencies=[Depends(get_current_active_user)])


# Pydantic models
class TacticalDecisionResponse(BaseModel):
    asset_id: str
    action_type: str
    parameters: dict
    confidence: float
    latency_ms: float
    model_version: str


class StrategicRecommendationResponse(BaseModel):
    recommendation_id: str
    asset_id: Optional[str]
    type: str
    priority: int
    description: str
    expected_impact: dict
    confidence: float
    valid_until: str
    requires_approval: bool


class ModelStatusResponse(BaseModel):
    current_model: str
    cached_models: List[str]
    poll_interval_seconds: int


# Tactical Engine Routes (Local Inference)
@router.get("/tactical/status")
async def get_tactical_status():
    """Get status of local tactical inference engine"""
    return {
        "model_loaded": tactical_engine.model is not None,
        "model_version": tactical_engine.model_version,
        "max_latency_target_ms": tactical_engine._max_latency_ms,
        "safety_thresholds": tactical_engine.safety_thresholds,
    }


@router.post("/tactical/infer", dependencies=[Depends(require_operator_or_admin)])
async def run_tactical_inference(asset_id: str, feature_vector: dict):
    """
    Run manual inference on tactical engine.
    Normally this happens automatically; this is for testing/debugging.
    """
    vector = {
        'asset_id': asset_id,
        'features': feature_vector,
        'timestamp': datetime.now(timezone.utc).isoformat(),
    }
    
    decision = await tactical_engine.infer(vector)
    
    if not decision:
        raise HTTPException(status_code=500, detail="Inference failed")
    
    return {
        'asset_id': decision.asset_id,
        'action_type': decision.action_type,
        'parameters': decision.parameters,
        'confidence': decision.confidence,
        'latency_ms': decision.latency_ms,
        'model_version': decision.model_version,
        'reasoning': decision.reasoning,
    }


# Strategic Engine Routes (Cloud Recommendations)
@router.get("/strategic/recommendations", response_model=List[StrategicRecommendationResponse])
async def get_strategic_recommendations(min_priority: Optional[int] = None):
    """Get pending recommendations from cloud strategic engine"""
    recs = strategic_engine.get_pending_recommendations(min_priority)
    
    return [
        {
            'recommendation_id': r.recommendation_id,
            'asset_id': r.asset_id,
            'type': r.recommendation_type,
            'priority': r.priority,
            'description': r.description,
            'expected_impact': r.expected_impact,
            'confidence': r.confidence,
            'valid_until': r.valid_until.isoformat(),
            'requires_approval': r.requires_approval,
        }
        for r in recs
    ]


@router.post("/strategic/recommendations/{rec_id}/approve", dependencies=[Depends(require_operator_or_admin)])
async def approve_recommendation(rec_id: str, operator_id: str, notes: Optional[str] = None):
    """Approve a strategic recommendation for implementation"""
    success = await strategic_engine.approve_recommendation(rec_id, operator_id, notes)
    
    if not success:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    
    return {"message": "Recommendation approved", "rec_id": rec_id}


@router.post("/strategic/recommendations/{rec_id}/reject", dependencies=[Depends(require_operator_or_admin)])
async def reject_recommendation(rec_id: str, operator_id: str, reason: str):
    """Reject a strategic recommendation"""
    success = await strategic_engine.reject_recommendation(rec_id, operator_id, reason)
    
    if not success:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    
    return {"message": "Recommendation rejected", "rec_id": rec_id}


# MLOps Pipeline Routes
@router.get("/mlops/status", response_model=ModelStatusResponse)
async def get_mlops_status():
    """Get MLOps pipeline status"""
    status = mlops_pipeline.get_status()
    return {
        'current_model': status['current_model'],
        'cached_models': status['cached_models'],
        'poll_interval_seconds': status['poll_interval_seconds'],
    }


@router.post("/mlops/deploy/{version}", dependencies=[Depends(require_admin)])
async def manual_deploy_model(version: str):
    """Manually trigger deployment of specific model version"""
    success = await mlops_pipeline.manual_deploy(version)
    
    if not success:
        raise HTTPException(status_code=400, detail="Deployment failed")
    
    return {"message": f"Model {version} deployed", "version": version}


@router.post("/mlops/rollback", dependencies=[Depends(require_admin)])
async def rollback_model():
    """Rollback to previous model version"""
    success = await mlops_pipeline.rollback()
    
    if not success:
        raise HTTPException(status_code=400, detail="Rollback failed")
    
    return {"message": "Model rolled back to previous version"}


# Cloud Gateway Routes
@router.get("/cloud/status")
async def get_cloud_gateway_status():
    """Get cloud gateway connection status"""
    return cloud_gateway.get_stats()


@router.post("/cloud/flush", dependencies=[Depends(require_admin)])
async def force_cloud_flush():
    """Force immediate flush of queued data to cloud"""
    await cloud_gateway._flush_batch()
    return {"message": "Flush initiated"}


# Correlation AI Engine Routes
@router.post("/correlation/analyze", dependencies=[Depends(require_operator_or_admin)])
async def analyze_correlation(
    scenario: CorrelationScenario,
    db: AsyncSession = Depends(get_db)
):
    """Run AI correlation analysis on a scenario"""
    try:
        result = await correlation_ai_engine.analyze_scenario(scenario, db)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/correlation/scenarios")
async def list_scenarios(
    limit: int = 50,
    offset: int = 0,
    db: AsyncSession = Depends(get_db)
):
    """List generated correlation scenarios"""
    try:
        scenarios = await correlation_ai_engine.list_scenarios(limit, offset, db)
        return {
            "total": len(scenarios),
            "limit": limit,
            "offset": offset,
            "scenarios": scenarios
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/correlation/generate", dependencies=[Depends(require_operator_or_admin)])
async def generate_synthetic_scenarios(
    count: int = 100,
    db: AsyncSession = Depends(get_db)
):
    """Generate synthetic correlation scenarios for training"""
    try:
        scenarios = await correlation_ai_engine.generate_synthetic_scenarios(count, db)
        return {
            "message": f"Generated {len(scenarios)} synthetic scenarios",
            "count": len(scenarios),
            "scenarios": scenarios[:10]  # Return first 10 as preview
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
