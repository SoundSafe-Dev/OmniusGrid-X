"""Unit tests for the cloud model training service.

The load-bearing check: each trained model exports to TorchScript ``.pt`` bytes
that ``torch.jit.load`` accepts and runs at ``(1, 8)`` — exactly what the edge
MLOps client (``mlops_pipeline._validate_model``) does on download. Pure
compute; no DB.
"""

from __future__ import annotations

import io

import numpy as np
import pytest
import torch

from app.services import model_training as mt


def _features(n: int = 50, seed: int = 1) -> np.ndarray:
    rng = np.random.RandomState(seed)
    return (rng.rand(n, mt.INPUT_DIM) * 100.0).astype(np.float32)


def _load(scripted_bytes: bytes):
    return torch.jit.load(io.BytesIO(scripted_bytes))


def _infer(model, x: torch.Tensor) -> torch.Tensor:
    # Mirror mlops_pipeline._validate_model: inference under no_grad.
    with torch.no_grad():
        return model(x)


class TestAnomalyModel:
    def test_exports_loadable_torchscript_at_contract_shape(self):
        result = mt.train_anomaly_model(_features(), epochs=5)
        model = _load(result.scripted_bytes)
        # The exact contract mlops_pipeline._validate_model exercises:
        out = _infer(model, torch.randn(1, mt.INPUT_DIM))
        assert tuple(out.shape) == (1, 1)
        # Batch inference + non-negative reconstruction-error score.
        batch = _infer(model, torch.randn(5, mt.INPUT_DIM))
        assert tuple(batch.shape) == (5, 1)
        assert float(batch.min()) >= 0.0

    def test_metrics_and_sample_count(self):
        result = mt.train_anomaly_model(_features(30), epochs=5)
        assert "reconstruction_loss" in result.metrics
        assert result.sample_count == 30

    def test_deterministic_with_seed(self):
        feats = _features()
        a = _load(mt.train_anomaly_model(feats, epochs=5, seed=7).scripted_bytes)
        b = _load(mt.train_anomaly_model(feats, epochs=5, seed=7).scripted_bytes)
        probe = torch.randn(4, mt.INPUT_DIM)
        assert torch.allclose(_infer(a, probe), _infer(b, probe))


class TestOEEModel:
    def test_exports_loadable_torchscript_at_contract_shape(self):
        feats = _features()
        labels = np.random.RandomState(2).rand(feats.shape[0]).astype(np.float32)
        result = mt.train_oee_model(feats, labels, epochs=5)
        model = _load(result.scripted_bytes)
        out = _infer(model, torch.randn(1, mt.INPUT_DIM))
        assert tuple(out.shape) == (1, 1)
        assert "mse" in result.metrics

    def test_label_length_mismatch_rejected(self):
        with pytest.raises(ValueError):
            mt.train_oee_model(_features(20), np.zeros(19, dtype=np.float32), epochs=1)


class TestValidation:
    def test_wrong_feature_width_rejected(self):
        with pytest.raises(ValueError):
            mt.train_anomaly_model(np.zeros((20, 7), dtype=np.float32), epochs=1)

    def test_too_few_samples_rejected(self):
        with pytest.raises(ValueError):
            mt.train_anomaly_model(_features(mt.MIN_TRAINING_SAMPLES - 1), epochs=1)


class TestFeatureContract:
    def test_contract_lists_eight_features_in_order(self):
        contract = mt.feature_contract()
        assert contract["input_dim"] == 8
        assert contract["feature_order"] == list(mt.FEATURE_ORDER)
        # Matches tactical_engine._vector_to_tensor ordering.
        assert contract["feature_order"][0] == "temp_nozzle_mean"
        assert contract["feature_order"][-1] == "state_transition_count"
