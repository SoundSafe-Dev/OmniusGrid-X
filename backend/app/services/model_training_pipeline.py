"""Dataset assembly + training orchestration for the cloud MLOps registry.

Ties the pure trainers in ``services/model_training.py`` to real tenant data
and the artifact store: assemble an ``(N, 8)`` feature matrix (+ an OEE label)
from ``telemetry``, train, persist the TorchScript artifact, and record the
``ModelTrainingRun`` / ``ModelRegistryEntry`` rows.

The 8 features mirror ``feature_extraction`` / ``tactical_engine`` exactly. The
OEE label is a telemetry-derived proxy (Availability x Performance x Quality)
so training has no dependency on the OEE calculator's storage; it swaps for the
real OEE once that path converges. The caller owns the transaction and MUST
have ``app.current_org_id`` set to ``organization_id`` (RLS WITH CHECK).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Mapping, Sequence
from uuid import UUID

import numpy as np
import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ModelRegistryEntry, ModelTrainingRun
from app.services import model_registry_store as store
from app.services import model_training as mt

logger = structlog.get_logger()

TRAINABLE_MODELS = ("anomaly", "oee_forecast")
DEFAULT_BUCKET_SECONDS = 3600
DEFAULT_WINDOW_DAYS = 7
NOMINAL_PRINT_SPEED = 100.0  # OEE performance-proxy denominator

_FEATURE_SQL = text(
    """
    SELECT
        t.asset_id AS asset_id,
        time_bucket(make_interval(secs => :bucket_seconds), t.time) AS bucket,
        avg(t.value) FILTER (WHERE t.metric_name = 'temp_nozzle') AS temp_nozzle_mean,
        stddev_samp(t.value) FILTER (WHERE t.metric_name = 'temp_nozzle') AS temp_nozzle_std,
        avg(t.value) FILTER (WHERE t.metric_name = 'temp_bed') AS temp_bed_mean,
        avg(t.value) FILTER (WHERE t.metric_name = 'print_speed') AS print_speed_mean,
        max(t.value) FILTER (WHERE t.metric_name = 'progress') AS progress_max,
        min(t.value) FILTER (WHERE t.metric_name = 'progress') AS progress_min,
        count(*) FILTER (WHERE t.packml_state = 'Execute')::float
            / NULLIF(count(*), 0) AS execute_ratio
    FROM telemetry t
    JOIN assets a ON a.id = t.asset_id
    WHERE a.organization_id = :org_id
      AND t.time >= :start AND t.time < :end
    GROUP BY t.asset_id, bucket
    HAVING count(*) > 0
    ORDER BY t.asset_id, bucket
    """
)

_TRANSITION_SQL = text(
    """
    SELECT p.asset_id AS asset_id,
           time_bucket(make_interval(secs => :bucket_seconds), p.state_entered_at) AS bucket,
           count(*) AS transitions
    FROM packml_states p
    JOIN assets a ON a.id = p.asset_id
    WHERE a.organization_id = :org_id
      AND p.state_entered_at >= :start AND p.state_entered_at < :end
    GROUP BY p.asset_id, bucket
    """
)


def _f(value: Any) -> float:
    return float(value) if value is not None else 0.0


def _clamp01(value: float) -> float:
    return min(max(value, 0.0), 1.0)


def rows_to_dataset(
    feature_rows: Sequence[Mapping[str, Any]],
    transitions: Mapping[tuple[Any, Any], int],
    bucket_seconds: int,
) -> tuple[np.ndarray, np.ndarray]:
    """Turn aggregated telemetry rows into ``(N, 8)`` features + ``(N,)`` labels.

    Pure/DB-free so it can be unit-tested. Feature order matches
    ``model_training.FEATURE_ORDER``.
    """
    features: list[list[float]] = []
    labels: list[float] = []
    for row in feature_rows:
        temp_nozzle_std = _f(row.get("temp_nozzle_std"))
        print_speed_mean = _f(row.get("print_speed_mean"))
        execute_ratio = _f(row.get("execute_ratio"))
        progress_velocity = (
            _f(row.get("progress_max")) - _f(row.get("progress_min"))
        ) / bucket_seconds
        temp_stability = max(0.0, 1.0 - temp_nozzle_std / 10.0)
        transition_count = float(
            transitions.get((row.get("asset_id"), row.get("bucket")), 0)
        )
        features.append(
            [
                _f(row.get("temp_nozzle_mean")),
                temp_nozzle_std,
                _f(row.get("temp_bed_mean")),
                print_speed_mean,
                progress_velocity,
                execute_ratio,
                temp_stability,
                transition_count,
            ]
        )
        # OEE proxy = Availability x Performance x Quality.
        availability = _clamp01(execute_ratio)
        performance = _clamp01(print_speed_mean / NOMINAL_PRINT_SPEED)
        quality = _clamp01(temp_stability)
        labels.append(availability * performance * quality)

    feature_arr = np.asarray(features, dtype=np.float32).reshape(-1, mt.INPUT_DIM)
    label_arr = np.asarray(labels, dtype=np.float32)
    return feature_arr, label_arr


async def assemble_feature_dataset(
    session: AsyncSession,
    organization_id: UUID,
    *,
    window_start: datetime,
    window_end: datetime,
    bucket_seconds: int = DEFAULT_BUCKET_SECONDS,
) -> tuple[np.ndarray, np.ndarray]:
    params = {
        "bucket_seconds": bucket_seconds,
        "org_id": str(organization_id),
        "start": window_start,
        "end": window_end,
    }
    feature_rows = (await session.execute(_FEATURE_SQL, params)).mappings().all()
    transition_rows = (await session.execute(_TRANSITION_SQL, params)).mappings().all()
    transitions = {
        (r["asset_id"], r["bucket"]): int(r["transitions"]) for r in transition_rows
    }
    return rows_to_dataset(feature_rows, transitions, bucket_seconds)


async def train_and_register(
    session: AsyncSession,
    organization_id: UUID,
    model_name: str,
    *,
    created_by: UUID | None = None,
    window_start: datetime | None = None,
    window_end: datetime | None = None,
    bucket_seconds: int = DEFAULT_BUCKET_SECONDS,
    seed: int = 0,
) -> ModelTrainingRun:
    """Assemble → train → store → register. Records a run either way.

    Returns the ``ModelTrainingRun`` (``status`` ``succeeded``/``failed``;
    ``produced_model_id`` set on success). Only invalid arguments raise; data or
    training failures are recorded on the run so a worker can keep going. Caller
    commits.
    """
    if model_name not in TRAINABLE_MODELS:
        raise ValueError(f"Unknown model_name {model_name!r}")

    now = datetime.now(timezone.utc)
    window_end = window_end or now
    window_start = window_start or (window_end - timedelta(days=DEFAULT_WINDOW_DAYS))

    run = ModelTrainingRun(
        organization_id=organization_id,
        model_name=model_name,
        status="running",
        params={
            "bucket_seconds": bucket_seconds,
            "seed": seed,
            "oee_label": "telemetry_proxy",
        },
        dataset_window_start=window_start,
        dataset_window_end=window_end,
        created_by=created_by,
        started_at=now,
    )
    session.add(run)
    await session.flush()

    try:
        features, labels = await assemble_feature_dataset(
            session,
            organization_id,
            window_start=window_start,
            window_end=window_end,
            bucket_seconds=bucket_seconds,
        )
        run.sample_count = int(features.shape[0])
        if features.shape[0] < mt.MIN_TRAINING_SAMPLES:
            raise ValueError(
                f"insufficient training data: {features.shape[0]} samples "
                f"(need >= {mt.MIN_TRAINING_SAMPLES})"
            )

        if model_name == "anomaly":
            trained = mt.train_anomaly_model(features, seed=seed)
        else:
            trained = mt.train_oee_model(features, labels, seed=seed)

        version = now.strftime("%Y%m%d%H%M%S")
        stored = store.store_model_artifact(
            organization_id, model_name, version, trained.scripted_bytes
        )
        entry = ModelRegistryEntry(
            organization_id=organization_id,
            name=model_name,
            version=version,
            framework="torchscript",
            artifact_storage_key=stored.storage_key,
            checksum_sha256=stored.checksum_sha256,
            feature_contract=trained.feature_contract,
            metrics=trained.metrics,
            training_run_id=run.id,
            status="draft",
            created_by=created_by,
        )
        session.add(entry)
        await session.flush()

        run.status = "succeeded"
        run.produced_model_id = entry.id
        run.metrics = trained.metrics
        logger.info(
            "training_run_succeeded",
            run_id=str(run.id), model=model_name, version=version,
            samples=run.sample_count,
        )
    except Exception as exc:  # noqa: BLE001 — record failure, keep the worker alive
        run.status = "failed"
        run.error = str(exc)
        logger.error(
            "training_run_failed", run_id=str(run.id), model=model_name, error=str(exc)
        )

    run.completed_at = datetime.now(timezone.utc)
    await session.flush()
    return run
