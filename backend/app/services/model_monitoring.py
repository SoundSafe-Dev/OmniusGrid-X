"""Model Monitoring Service for Drift Detection and Performance Tracking

TIMESTAMPS ARE TIMEZONE-AWARE, like the other 483 datetime constructions in this
codebase. This module used bare `datetime.now()` in nine places — the only naive island
in `app/` — which made its ISO strings carry no offset while every other endpoint emits
`+00:00`.

Internally that was consistent: the drift and performance histories are in-memory, both
sides of every comparison were naive, and nothing raised. The hazard was at the boundary.
`new Date("2026-07-28T02:15:00")` is parsed by JavaScript as LOCAL time while
`new Date("2026-07-28T02:15:00+00:00")` is UTC, so the same instant would have rendered
hours apart depending on which endpoint it came from. No frontend consumes these routes
today, which is the only reason it never showed.
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
from scipy import stats
import numpy as np
import structlog

logger = structlog.get_logger()


class ModelDriftDetector:
    """
    Detect model drift using statistical methods.
    
    Uses Kolmogorov-Smirnov test for data drift detection.
    """
    
    def __init__(self, model_id: str, threshold: float = 0.05):
        self.model_id = model_id
        self.threshold = threshold
        self.reference_data: List[float] = []
        self.current_data: List[float] = []
        self.drift_history: List[Dict[str, Any]] = []
    
    def set_reference_data(self, data: List[float]) -> None:
        """
        Set reference data for drift detection.
        
        Args:
            data: Reference data points
        """
        self.reference_data = data
        logger.info(
            "reference_data_set",
            model_id=self.model_id,
            sample_size=len(data)
        )
    
    def add_current_data(self, data: List[float]) -> None:
        """
        Add current data for drift detection.
        
        Args:
            data: Current data points
        """
        self.current_data.extend(data)
        # Keep only last 1000 points
        if len(self.current_data) > 1000:
            self.current_data = self.current_data[-1000:]
    
    def detect_drift(self) -> Dict[str, Any]:
        """
        Detect drift using Kolmogorov-Smirnov test.
        
        Returns:
            Dictionary with drift detection results
        """
        if len(self.reference_data) < 30 or len(self.current_data) < 30:
            return {
                "model_id": self.model_id,
                "drift_detected": False,
                "reason": "Insufficient data",
                "p_value": None,
                "ks_statistic": None,
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
        
        # Perform KS test
        ks_statistic, p_value = stats.ks_2samp(
            self.reference_data,
            self.current_data
        )
        
        drift_detected = p_value < self.threshold
        
        result = {
            "model_id": self.model_id,
            "drift_detected": drift_detected,
            "p_value": p_value,
            "ks_statistic": ks_statistic,
            "threshold": self.threshold,
            "reference_size": len(self.reference_data),
            "current_size": len(self.current_data),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if drift_detected:
            logger.warning(
                "model_drift_detected",
                model_id=self.model_id,
                p_value=p_value,
                ks_statistic=ks_statistic
            )
            self.drift_history.append(result)
        
        return result
    
    def get_drift_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get drift detection history.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            List of drift detection results
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [
            drift for drift in self.drift_history
            if datetime.fromisoformat(drift["timestamp"]) > cutoff
        ]
    
    def reset(self) -> None:
        """Reset all data and history."""
        self.reference_data.clear()
        self.current_data.clear()
        self.drift_history.clear()
        
        logger.info("drift_detector_reset", model_id=self.model_id)


class DataDriftMonitor:
    """
    Monitor data drift using Population Stability Index (PSI).
    """
    
    def __init__(self, model_id: str, psi_threshold: float = 0.2):
        self.model_id = model_id
        self.psi_threshold = psi_threshold
        self.reference_distribution: Dict[str, List[float]] = {}
        self.current_distribution: Dict[str, List[float]] = {}
        self.psi_history: List[Dict[str, Any]] = []
    
    def set_reference_distribution(self, feature_name: str, data: List[float]) -> None:
        """
        Set reference distribution for a feature.
        
        Args:
            feature_name: Name of the feature
            data: Reference data points
        """
        self.reference_distribution[feature_name] = data
        logger.info(
            "reference_distribution_set",
            model_id=self.model_id,
            feature_name=feature_name,
            sample_size=len(data)
        )
    
    def add_current_distribution(self, feature_name: str, data: List[float]) -> None:
        """
        Add current distribution for a feature.
        
        Args:
            feature_name: Name of the feature
            data: Current data points
        """
        if feature_name not in self.current_distribution:
            self.current_distribution[feature_name] = []
        
        self.current_distribution[feature_name].extend(data)
        # Keep only last 1000 points
        if len(self.current_distribution[feature_name]) > 1000:
            self.current_distribution[feature_name] = self.current_distribution[feature_name][-1000:]
    
    def calculate_psi(self, expected: List[float], actual: List[float], bins: int = 10) -> float:
        """
        Calculate Population Stability Index (PSI).
        
        Args:
            expected: Expected (reference) distribution
            actual: Actual (current) distribution
            bins: Number of bins for histogram
            
        Returns:
            PSI value
        """
        # Create bins
        min_val = min(min(expected), min(actual))
        max_val = max(max(expected), max(actual))
        bin_edges = np.linspace(min_val, max_val, bins + 1)
        
        # Calculate histograms
        expected_hist, _ = np.histogram(expected, bins=bin_edges)
        actual_hist, _ = np.histogram(actual, bins=bin_edges)
        
        # Avoid division by zero
        expected_hist = expected_hist + 1e-10
        actual_hist = actual_hist + 1e-10
        
        # Normalize
        expected_pct = expected_hist / expected_hist.sum()
        actual_pct = actual_hist / actual_hist.sum()
        
        # Calculate PSI
        psi = np.sum((expected_pct - actual_pct) * np.log(expected_pct / actual_pct))
        
        return psi
    
    def detect_data_drift(self) -> Dict[str, Any]:
        """
        Detect data drift using PSI.
        
        Returns:
            Dictionary with drift detection results
        """
        drift_results = {}
        
        for feature_name in self.reference_distribution:
            if feature_name not in self.current_distribution:
                continue
            
            if len(self.reference_distribution[feature_name]) < 30 or len(self.current_distribution[feature_name]) < 30:
                drift_results[feature_name] = {
                    "drift_detected": False,
                    "reason": "Insufficient data",
                    "psi": None
                }
                continue
            
            psi = self.calculate_psi(
                self.reference_distribution[feature_name],
                self.current_distribution[feature_name]
            )
            
            drift_detected = psi > self.psi_threshold
            
            drift_results[feature_name] = {
                "drift_detected": drift_detected,
                "psi": psi,
                "threshold": self.psi_threshold,
                "reference_size": len(self.reference_distribution[feature_name]),
                "current_size": len(self.current_distribution[feature_name])
            }
            
            if drift_detected:
                logger.warning(
                    "data_drift_detected",
                    model_id=self.model_id,
                    feature_name=feature_name,
                    psi=psi
                )
        
        result = {
            "model_id": self.model_id,
            "features": drift_results,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        self.psi_history.append(result)
        
        return result
    
    def get_psi_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get PSI history.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            List of PSI results
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [
            psi for psi in self.psi_history
            if datetime.fromisoformat(psi["timestamp"]) > cutoff
        ]
    
    def reset(self) -> None:
        """Reset all distributions and history."""
        self.reference_distribution.clear()
        self.current_distribution.clear()
        self.psi_history.clear()
        
        logger.info("data_drift_monitor_reset", model_id=self.model_id)


class ModelPerformanceTracker:
    """
    Track model performance metrics.
    """
    
    def __init__(self, model_id: str):
        self.model_id = model_id
        self.predictions: List[Dict[str, Any]] = []
        self.performance_history: List[Dict[str, Any]] = []
    
    def add_prediction(
        self,
        prediction: float,
        actual: Optional[float] = None,
        latency_ms: Optional[float] = None
    ) -> None:
        """
        Add a prediction result.
        
        Args:
            prediction: Predicted value
            actual: Actual value (if available)
            latency_ms: Prediction latency in milliseconds
        """
        self.predictions.append({
            "prediction": prediction,
            "actual": actual,
            "latency_ms": latency_ms,
            "timestamp": datetime.now(timezone.utc).isoformat()
        })
        
        # Keep only last 1000 predictions
        if len(self.predictions) > 1000:
            self.predictions = self.predictions[-1000:]
    
    def calculate_metrics(self) -> Dict[str, Any]:
        """
        Calculate performance metrics.
        
        Returns:
            Dictionary with performance metrics
        """
        if not self.predictions:
            return {
                "model_id": self.model_id,
                "error": "No predictions available"
            }
        
        # Calculate accuracy (if actual values available)
        predictions_with_actual = [p for p in self.predictions if p["actual"] is not None]
        
        metrics = {
            "model_id": self.model_id,
            "total_predictions": len(self.predictions),
            "predictions_with_actual": len(predictions_with_actual),
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        if predictions_with_actual:
            predictions = np.array([p["prediction"] for p in predictions_with_actual])
            actuals = np.array([p["actual"] for p in predictions_with_actual])
            
            # Mean Absolute Error
            mae = np.mean(np.abs(predictions - actuals))
            
            # Mean Squared Error
            mse = np.mean((predictions - actuals) ** 2)
            
            # Root Mean Squared Error
            rmse = np.sqrt(mse)
            
            # R-squared
            ss_res = np.sum((actuals - predictions) ** 2)
            ss_tot = np.sum((actuals - np.mean(actuals)) ** 2)
            r_squared = 1 - (ss_res / ss_tot) if ss_tot > 0 else 0
            
            metrics.update({
                "mae": mae,
                "mse": mse,
                "rmse": rmse,
                "r_squared": r_squared
            })
        
        # Calculate latency metrics
        latencies = [p["latency_ms"] for p in self.predictions if p["latency_ms"] is not None]
        
        if latencies:
            metrics.update({
                "avg_latency_ms": np.mean(latencies),
                "p50_latency_ms": np.percentile(latencies, 50),
                "p95_latency_ms": np.percentile(latencies, 95),
                "p99_latency_ms": np.percentile(latencies, 99),
                "max_latency_ms": np.max(latencies)
            })
        
        self.performance_history.append(metrics)
        
        return metrics
    
    def get_performance_history(self, hours: int = 24) -> List[Dict[str, Any]]:
        """
        Get performance history.
        
        Args:
            hours: Number of hours to look back
            
        Returns:
            List of performance metrics
        """
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        return [
            perf for perf in self.performance_history
            if datetime.fromisoformat(perf["timestamp"]) > cutoff
        ]
    
    def reset(self) -> None:
        """Reset all predictions and history."""
        self.predictions.clear()
        self.performance_history.clear()
        
        logger.info("performance_tracker_reset", model_id=self.model_id)


class ModelMonitoringService:
    """
    Comprehensive model monitoring service.
    """
    
    def __init__(self):
        self.drift_detectors: Dict[str, ModelDriftDetector] = {}
        self.data_drift_monitors: Dict[str, DataDriftMonitor] = {}
        self.performance_trackers: Dict[str, ModelPerformanceTracker] = {}
    
    def get_or_create_drift_detector(self, model_id: str) -> ModelDriftDetector:
        """Get or create drift detector for a model."""
        if model_id not in self.drift_detectors:
            self.drift_detectors[model_id] = ModelDriftDetector(model_id)
        return self.drift_detectors[model_id]
    
    def get_or_create_data_drift_monitor(self, model_id: str) -> DataDriftMonitor:
        """Get or create data drift monitor for a model."""
        if model_id not in self.data_drift_monitors:
            self.data_drift_monitors[model_id] = DataDriftMonitor(model_id)
        return self.data_drift_monitors[model_id]
    
    def get_or_create_performance_tracker(self, model_id: str) -> ModelPerformanceTracker:
        """Get or create performance tracker for a model."""
        if model_id not in self.performance_trackers:
            self.performance_trackers[model_id] = ModelPerformanceTracker(model_id)
        return self.performance_trackers[model_id]
    
    def get_model_summary(self, model_id: str) -> Dict[str, Any]:
        """
        Get comprehensive monitoring summary for a model.
        
        Args:
            model_id: Model ID
            
        Returns:
            Dictionary with all monitoring data
        """
        summary = {
            "model_id": model_id,
            "timestamp": datetime.now(timezone.utc).isoformat()
        }
        
        # Drift detection
        if model_id in self.drift_detectors:
            summary["model_drift"] = self.drift_detectors[model_id].detect_drift()
        
        # Data drift
        if model_id in self.data_drift_monitors:
            summary["data_drift"] = self.data_drift_monitors[model_id].detect_data_drift()
        
        # Performance
        if model_id in self.performance_trackers:
            summary["performance"] = self.performance_trackers[model_id].calculate_metrics()
        
        return summary


# Global model monitoring service instance
model_monitoring_service = ModelMonitoringService()
