"""Progress-tracked background jobs for evidence correlation work.

The evidence engine must not hold an API request open while it parses several
workbooks or computes a large join.  This module supplies a small async job
contract backed by Redis when available and an explicit in-process development
fallback otherwise.  Worker deployments can run the same executor from a
dedicated process because job state is serializable.
"""

from __future__ import annotations

import asyncio
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

import structlog

from app.core.config import settings
from app.core.http_metrics import CORRELATION_JOB_STORE_DEGRADED

try:  # Tests and lightweight local installs may not include redis.
    import redis.asyncio as redis
except ImportError:  # pragma: no cover - exercised only in minimal installs
    redis = None

logger = structlog.get_logger()

JOB_KEY_PREFIX = "correlation_job:"
TERMINAL_STATES = {"completed", "failed", "cancelled"}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class CorrelationJobCancelled(Exception):
    """Raised by an executor when an operator cancels the work."""


class CorrelationJobManager:
    """Redis-first correlation job state with a safe local fallback."""

    def __init__(self) -> None:
        self._client = None
        self._redis_unavailable = not settings.CORRELATION_JOB_USE_REDIS or redis is None
        self._memory: Dict[str, Dict[str, Any]] = {}
        self._memory_lock = asyncio.Lock()

    async def _redis_client(self):
        if self._redis_unavailable:
            return None
        if self._client is None:
            self._client = redis.from_url(settings.REDIS_URL, decode_responses=True)
        try:
            await self._client.ping()
            return self._client
        except Exception as exc:  # local dev can operate without a broker
            self._redis_unavailable = True
            CORRELATION_JOB_STORE_DEGRADED.inc()
            logger.warning("correlation_job_redis_unavailable", error=str(exc))
            return None

    async def _save(self, job: Dict[str, Any]) -> None:
        job["updated_at"] = _now()
        client = await self._redis_client()
        if client is not None:
            await client.set(
                f"{JOB_KEY_PREFIX}{job['job_id']}",
                json.dumps(job, default=str),
                ex=settings.CORRELATION_JOB_TTL_SECONDS,
            )
            return
        async with self._memory_lock:
            self._memory[job["job_id"]] = dict(job)

    async def get(self, job_id: str) -> Optional[Dict[str, Any]]:
        client = await self._redis_client()
        if client is not None:
            raw = await client.get(f"{JOB_KEY_PREFIX}{job_id}")
            return json.loads(raw) if raw else None
        async with self._memory_lock:
            job = self._memory.get(job_id)
            return dict(job) if job else None

    async def create(
        self,
        job_type: str,
        *,
        organization_id: Any,
        actor_id: Any,
        input_summary: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        job = {
            "job_id": str(uuid.uuid4()),
            "type": job_type,
            "status": "pending",
            "stage": "queued",
            "progress": 0.0,
            "processed": 0,
            "total": 0,
            "organization_id": str(organization_id),
            "actor_id": str(actor_id),
            "input_summary": input_summary or {},
            "result": None,
            "error": None,
            "created_at": _now(),
            "updated_at": _now(),
        }
        await self._save(job)
        return job

    async def update(
        self,
        job_id: str,
        *,
        stage: Optional[str] = None,
        progress: Optional[float] = None,
        processed: Optional[int] = None,
        total: Optional[int] = None,
        result: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        job = await self.get(job_id)
        if job is None:
            return None
        if job["status"] in TERMINAL_STATES:
            return job
        if stage is not None:
            job["stage"] = stage
        if progress is not None:
            job["progress"] = max(0.0, min(100.0, round(float(progress), 1)))
        if processed is not None:
            job["processed"] = max(0, int(processed))
        if total is not None:
            job["total"] = max(0, int(total))
        if result is not None:
            job["result"] = result
        await self._save(job)
        return job

    async def cancel(
        self,
        job_id: str,
        *,
        organization_id: Any,
        actor_id: Optional[Any] = None,
    ) -> Optional[Dict[str, Any]]:
        job = await self.get(job_id)
        if job is None or job.get("organization_id") != str(organization_id):
            return None
        # Evidence jobs inherit the source-intake visibility of their creator.
        # An explicit future sharing policy can pass no actor_id; API routes for
        # private intake work always supply it.
        if actor_id is not None and job.get("actor_id") != str(actor_id):
            return None
        if job["status"] in TERMINAL_STATES:
            return job
        job.update({"status": "cancelled", "stage": "cancelled", "progress": 100.0})
        await self._save(job)
        return job

    async def cancellation_requested(self, job_id: str) -> bool:
        job = await self.get(job_id)
        return bool(job and job.get("status") == "cancelled")

    async def run(
        self,
        job_id: str,
        executor: Callable[[Callable[..., Awaitable[Optional[Dict[str, Any]]]]], Awaitable[Dict[str, Any]]],
    ) -> None:
        """Run an async executor and persist controlled progress/result state."""
        job = await self.get(job_id)
        if job is None or job.get("status") == "cancelled":
            return
        job.update({"status": "running", "stage": "starting", "progress": 1.0})
        await self._save(job)

        async def report(**updates: Any) -> Optional[Dict[str, Any]]:
            if await self.cancellation_requested(job_id):
                raise CorrelationJobCancelled()
            return await self.update(job_id, **updates)

        try:
            result = await executor(report)
            job = await self.get(job_id)
            if job is None or job.get("status") == "cancelled":
                return
            job.update({
                "status": "completed",
                "stage": "completed",
                "progress": 100.0,
                "result": result,
                "error": None,
            })
            await self._save(job)
        except CorrelationJobCancelled:
            # cancel() has already persisted the canonical terminal state.
            logger.info("correlation_job_cancelled", job_id=job_id)
        except Exception as exc:  # executor errors should be observable, not lost
            logger.exception("correlation_job_failed", job_id=job_id, error=str(exc))
            job = await self.get(job_id)
            if job and job.get("status") != "cancelled":
                job.update({
                    "status": "failed",
                    "stage": "failed",
                    "progress": 100.0,
                    "error": str(exc)[:2000],
                })
                await self._save(job)


correlation_jobs = CorrelationJobManager()
