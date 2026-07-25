"""Model Monitoring API Routes"""

from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel

from app.api.auth import get_current_active_user

try:
    from app.services.model_monitoring import model_monitoring_service
except ImportError:  # pragma: no cover - exercised only when scipy is absent
    model_monitoring_service = None


def require_monitoring_service():
    """Return the monitoring service, or 503 if its dependencies are missing.

    Without this, a failed import left model_monitoring_service as None and all
    14 call sites below raised AttributeError, which the routes' broad
    `except Exception` turned into an opaque 500 — 'Failed to retrieve model
    summary: NoneType object has no attribute ...'. That is exactly what
    happened in practice: app/services/model_monitoring.py needs scipy for its
    KS test and scipy was never in requirements.txt, so every /model-monitoring
    endpoint 500'd against a real deployment.

    503 matches the convention already used for optional infrastructure
    (redis-backed feature flags, pg_stat_statements diagnostics) and the
    real-DB endpoint smoke treats it as an acceptable degradation.
    """
    if model_monitoring_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=(
                "model monitoring is unavailable: the service could not be "
                "imported (scipy is required for drift detection)"
            ),
        )
    return model_monitoring_service


# Currently unmounted (MLOps model-drift surface). Auth-gated defensively so it
# is safe if ever wired up. Owner: MLOps lane.
router = APIRouter(dependencies=[Depends(get_current_active_user)])


class DriftDetectionRequest(BaseModel):
    model_id: str
    reference_data: List[float]
    current_data: List[float]


class DataDriftRequest(BaseModel):
    model_id: str
    feature_name: str
    reference_data: List[float]
    current_data: List[float]


class PredictionRequest(BaseModel):
    model_id: str
    prediction: float
    actual: Optional[float] = None
    latency_ms: Optional[float] = None


@router.post("/drift/detect")
async def detect_model_drift(request: DriftDetectionRequest):
    """
    Detect model drift using Kolmogorov-Smirnov test.
    """
    try:
        detector = require_monitoring_service().get_or_create_drift_detector(request.model_id)
        detector.set_reference_data(request.reference_data)
        detector.add_current_data(request.current_data)
        
        result = detector.detect_drift()
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to detect model drift: {str(e)}"
        )


@router.get("/drift/history/{model_id}")
async def get_drift_history(model_id: str, hours: int = 24):
    """
    Get drift detection history for a model.
    """
    try:
        detector = require_monitoring_service().get_or_create_drift_detector(model_id)
        history = detector.get_drift_history(hours)
        
        return {
            "model_id": model_id,
            "history": history,
            "count": len(history)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve drift history: {str(e)}"
        )


@router.post("/data-drift/detect")
async def detect_data_drift(request: DataDriftRequest):
    """
    Detect data drift using Population Stability Index (PSI).
    """
    try:
        monitor = require_monitoring_service().get_or_create_data_drift_monitor(request.model_id)
        monitor.set_reference_distribution(request.feature_name, request.reference_data)
        monitor.add_current_distribution(request.feature_name, request.current_data)
        
        result = monitor.detect_data_drift()
        return result
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to detect data drift: {str(e)}"
        )


@router.get("/data-drift/history/{model_id}")
async def get_psi_history(model_id: str, hours: int = 24):
    """
    Get PSI history for a model.
    """
    try:
        monitor = require_monitoring_service().get_or_create_data_drift_monitor(model_id)
        history = monitor.get_psi_history(hours)
        
        return {
            "model_id": model_id,
            "history": history,
            "count": len(history)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve PSI history: {str(e)}"
        )


@router.post("/performance/prediction")
async def add_prediction(request: PredictionRequest):
    """
    Add a prediction result for performance tracking.
    """
    try:
        tracker = require_monitoring_service().get_or_create_performance_tracker(request.model_id)
        tracker.add_prediction(
            prediction=request.prediction,
            actual=request.actual,
            latency_ms=request.latency_ms
        )
        
        return {"message": "Prediction added successfully"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to add prediction: {str(e)}"
        )


@router.get("/performance/metrics/{model_id}")
async def get_performance_metrics(model_id: str):
    """
    Get performance metrics for a model.
    """
    try:
        tracker = require_monitoring_service().get_or_create_performance_tracker(model_id)
        metrics = tracker.calculate_metrics()
        
        return metrics
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to calculate performance metrics: {str(e)}"
        )


@router.get("/performance/history/{model_id}")
async def get_performance_history(model_id: str, hours: int = 24):
    """
    Get performance history for a model.
    """
    try:
        tracker = require_monitoring_service().get_or_create_performance_tracker(model_id)
        history = tracker.get_performance_history(hours)
        
        return {
            "model_id": model_id,
            "history": history,
            "count": len(history)
        }
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve performance history: {str(e)}"
        )


@router.get("/summary/{model_id}")
async def get_model_summary(model_id: str):
    """
    Get comprehensive monitoring summary for a model.
    """
    try:
        summary = require_monitoring_service().get_model_summary(model_id)
        return summary
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to retrieve model summary: {str(e)}"
        )


@router.post("/reset/{model_id}")
async def reset_model_monitoring(model_id: str):
    """
    Reset all monitoring data for a model.
    """
    try:
        if model_id in require_monitoring_service().drift_detectors:
            require_monitoring_service().drift_detectors[model_id].reset()
        
        if model_id in require_monitoring_service().data_drift_monitors:
            require_monitoring_service().data_drift_monitors[model_id].reset()
        
        if model_id in require_monitoring_service().performance_trackers:
            require_monitoring_service().performance_trackers[model_id].reset()
        
        return {"message": f"Model monitoring reset for {model_id}"}
        
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Failed to reset model monitoring: {str(e)}"
        )
