"""Cloud model training for the MLOps registry.

Trains the two v1 model families the edge consumes — an anomaly-scoring
autoencoder and an OEE-forecast regressor — over the 8-feature vector that
``services/feature_extraction.py`` emits and ``services/tactical_engine.py``
feeds at inference.

Each model bakes its own standardization (mean/std buffers) so the exported
TorchScript accepts **raw** ``(N, 8)`` inputs; consumers only supply the eight
features in ``FEATURE_ORDER``. Training returns TorchScript ``.pt`` bytes ready
for the registry (``services/model_registry_store.py``).
"""

from __future__ import annotations

import io
from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog
import torch
from torch import nn

logger = structlog.get_logger()

# Must match tactical_engine._vector_to_tensor ordering exactly — the edge
# feeds features in this order, and feature_extraction emits these keys.
FEATURE_ORDER = (
    "temp_nozzle_mean",
    "temp_nozzle_std",
    "temp_bed_mean",
    "print_speed_mean",
    "progress_velocity",
    "execute_time_ratio",
    "temp_stability_score",
    "state_transition_count",
)
INPUT_DIM = len(FEATURE_ORDER)
MIN_TRAINING_SAMPLES = 10


@dataclass
class TrainedModel:
    scripted_bytes: bytes
    metrics: dict[str, float]
    feature_contract: dict[str, Any]
    sample_count: int


class _Standardizer(nn.Module):
    """Applies ``(x - mean) / std`` with buffers baked into the exported model."""

    def __init__(self, mean: torch.Tensor, std: torch.Tensor) -> None:
        super().__init__()
        self.register_buffer("mean", mean)
        self.register_buffer("std", std)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return (x - self.mean) / self.std


class AnomalyAutoencoder(nn.Module):
    """Reconstruction autoencoder; ``forward`` returns a per-row anomaly score."""

    def __init__(self, mean: torch.Tensor, std: torch.Tensor) -> None:
        super().__init__()
        self.standardize = _Standardizer(mean, std)
        self.encoder = nn.Sequential(
            nn.Linear(INPUT_DIM, 5), nn.ReLU(), nn.Linear(5, 3)
        )
        self.decoder = nn.Sequential(
            nn.Linear(3, 5), nn.ReLU(), nn.Linear(5, INPUT_DIM)
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        z = self.standardize(x)
        recon = self.decoder(self.encoder(z))
        return ((z - recon) ** 2).mean(dim=1, keepdim=True)


class OEEForecaster(nn.Module):
    """Regressor; ``forward`` returns a per-row OEE prediction."""

    def __init__(self, mean: torch.Tensor, std: torch.Tensor) -> None:
        super().__init__()
        self.standardize = _Standardizer(mean, std)
        self.net = nn.Sequential(nn.Linear(INPUT_DIM, 8), nn.ReLU(), nn.Linear(8, 1))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        return self.net(self.standardize(x))


def feature_contract() -> dict[str, Any]:
    """The input contract stored in the registry and honored by consumers."""
    return {
        "feature_order": list(FEATURE_ORDER),
        "input_dim": INPUT_DIM,
        "normalization": "standardized_internal",
    }


def _validate_features(features: np.ndarray) -> None:
    if features.ndim != 2 or features.shape[1] != INPUT_DIM:
        raise ValueError(
            f"features must be shape (N, {INPUT_DIM}); got {features.shape}"
        )
    if features.shape[0] < MIN_TRAINING_SAMPLES:
        raise ValueError(
            f"need at least {MIN_TRAINING_SAMPLES} samples; got {features.shape[0]}"
        )


def _standardization_params(features: np.ndarray) -> tuple[torch.Tensor, torch.Tensor]:
    mean = features.mean(axis=0)
    std = features.std(axis=0)
    # Guard constant features (std == 0) against divide-by-zero.
    std = np.where(std < 1e-6, 1.0, std)
    return (
        torch.tensor(mean, dtype=torch.float32),
        torch.tensor(std, dtype=torch.float32),
    )


def _export_torchscript(module: nn.Module) -> bytes:
    module.eval()
    scripted = torch.jit.script(module)
    buffer = io.BytesIO()
    torch.jit.save(scripted, buffer)
    return buffer.getvalue()


def train_anomaly_model(
    features: np.ndarray, *, epochs: int = 50, seed: int = 0
) -> TrainedModel:
    """Train the anomaly autoencoder on ``(N, 8)`` feature rows."""
    features = np.asarray(features, dtype=np.float32)
    _validate_features(features)
    torch.manual_seed(seed)

    mean, std = _standardization_params(features)
    model = AnomalyAutoencoder(mean, std)
    x = torch.tensor(features, dtype=torch.float32)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)

    model.train()
    final_loss = 0.0
    for _ in range(epochs):
        optimizer.zero_grad()
        loss = model(x).mean()  # score == reconstruction error
        loss.backward()
        optimizer.step()
        final_loss = float(loss.item())

    logger.info(
        "model_trained", family="anomaly", samples=int(features.shape[0]),
        reconstruction_loss=final_loss,
    )
    return TrainedModel(
        scripted_bytes=_export_torchscript(model),
        metrics={"reconstruction_loss": final_loss},
        feature_contract=feature_contract(),
        sample_count=int(features.shape[0]),
    )


def train_oee_model(
    features: np.ndarray, labels: np.ndarray, *, epochs: int = 100, seed: int = 0
) -> TrainedModel:
    """Train the OEE-forecast regressor on ``(N, 8)`` features + ``(N,)`` labels."""
    features = np.asarray(features, dtype=np.float32)
    _validate_features(features)
    labels = np.asarray(labels, dtype=np.float32).reshape(-1, 1)
    if labels.shape[0] != features.shape[0]:
        raise ValueError("features and labels must have the same length")
    torch.manual_seed(seed)

    mean, std = _standardization_params(features)
    model = OEEForecaster(mean, std)
    x = torch.tensor(features, dtype=torch.float32)
    y = torch.tensor(labels, dtype=torch.float32)
    optimizer = torch.optim.Adam(model.parameters(), lr=1e-2)
    loss_fn = nn.MSELoss()

    model.train()
    final_loss = 0.0
    for _ in range(epochs):
        optimizer.zero_grad()
        loss = loss_fn(model(x), y)
        loss.backward()
        optimizer.step()
        final_loss = float(loss.item())

    logger.info(
        "model_trained", family="oee_forecast", samples=int(features.shape[0]),
        mse=final_loss,
    )
    return TrainedModel(
        scripted_bytes=_export_torchscript(model),
        metrics={"mse": final_loss},
        feature_contract=feature_contract(),
        sample_count=int(features.shape[0]),
    )
