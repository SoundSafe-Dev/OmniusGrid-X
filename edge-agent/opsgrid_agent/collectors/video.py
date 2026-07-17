"""Video frame-metric collector (Phase B, task 14).

Captures frames from a camera/MJPEG/RTSP stream (or synthesizes demo frames) and
emits *frame-metric telemetry* — not raw video — so visual monitoring data rides
the normal quality→buffer→ingest→Telemetry path like any other metric:

    frame_brightness   mean luminance 0..255
    frame_contrast     luminance std-dev
    motion_score       normalized mean |frame - prev| (0..1)
    frames_analyzed    running counter

The raw stream itself is NOT proxied through telemetry; the frontend camera pane
(task B15) connects to the stream_url from the asset's media_config directly.

Config:
    asset_id (str):        Asset the readings belong to (required)
    source (str):          "stream" (OpenCV VideoCapture) or "simulate" (default)
    stream_url (str):      capture URL when source="stream"
    poll_interval (float): seconds between analyzed frames (default 10)

Frame analysis is pure numpy (unit-tested); OpenCV is only needed for the
"stream" source and is imported lazily with graceful degradation — matching the
other driver-dependent collectors.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import asyncio

import numpy as np
import structlog

from .base import BaseCollector

logger = structlog.get_logger()

try:
    import cv2 as _cv2
    _CV2_AVAILABLE = True
    _CV2_IMPORT_ERROR: Optional[str] = None
except Exception as exc:  # pragma: no cover - exercised only without the driver
    _cv2 = None  # type: ignore
    _CV2_AVAILABLE = False
    _CV2_IMPORT_ERROR = str(exc)


def extract_frame_metrics(
    frame: "np.ndarray", prev_frame: Optional["np.ndarray"] = None
) -> Dict[str, float]:
    """Pure analysis: grayscale frame (+ optional previous) -> metric dict."""
    if frame.size == 0:
        return {"frame_brightness": 0.0, "frame_contrast": 0.0, "motion_score": 0.0}
    gray = frame.astype(np.float64)
    if gray.ndim == 3:  # collapse color to luminance
        gray = gray.mean(axis=2)

    brightness = float(gray.mean())
    contrast = float(gray.std())

    motion = 0.0
    if prev_frame is not None and prev_frame.size == frame.size:
        prev = prev_frame.astype(np.float64)
        if prev.ndim == 3:
            prev = prev.mean(axis=2)
        motion = float(np.abs(gray - prev).mean() / 255.0)

    return {
        "frame_brightness": round(brightness, 2),
        "frame_contrast": round(contrast, 2),
        "motion_score": round(motion, 4),
    }


def synthesize_frame(tick: int, size: int = 64) -> "np.ndarray":
    """Demo frame: mid-gray background + a bright square that moves each tick."""
    frame = np.full((size, size), 110.0)
    pos = (tick * 7) % (size - 16)
    frame[pos:pos + 16, pos:pos + 16] = 240.0
    return frame


class VideoFrameCollector(BaseCollector):
    """Collector emitting frame-metric telemetry from a camera or demo frames."""

    # Defaults to a synthetic source -> BaseCollector enforces explicit config
    # under EDGE_REQUIRE_EXPLICIT_SOURCES (no silent demo frames).
    has_synthetic_default = True

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.source = config.get("source", "simulate")
        self.stream_url = config.get("stream_url")
        self.poll_interval = float(config.get("poll_interval", 10))
        self._poll_task: Optional[asyncio.Task] = None
        self._capture = None
        self._prev_frame: Optional[np.ndarray] = None
        self._frames_analyzed = 0
        self._tick = 0

    async def start(self) -> None:
        await super().start()
        if self.source == "stream":
            if not _CV2_AVAILABLE:
                self._running = False
                logger.error("video_driver_missing", asset_id=self.asset_id,
                             error=_CV2_IMPORT_ERROR, hint="pip install opencv-python")
                return
            if not self.stream_url:
                self._running = False
                logger.error("video_no_stream_url", asset_id=self.asset_id)
                return
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("video_collector_started", asset_id=self.asset_id, source=self.source)

    async def stop(self) -> None:
        await super().stop()
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        if self._capture is not None:  # pragma: no cover - needs a live stream
            try:
                self._capture.release()
            except Exception:
                pass
        logger.info("video_collector_stopped", asset_id=self.asset_id)

    def _grab_frame(self) -> Optional["np.ndarray"]:
        """Blocking frame grab (runs in a worker thread)."""
        if self.source == "stream":  # pragma: no cover - needs a live stream
            if self._capture is None:
                self._capture = _cv2.VideoCapture(self.stream_url)  # type: ignore[union-attr]
            ok, frame = self._capture.read()
            if not ok:
                # Drop the handle so we reconnect on the next poll.
                try:
                    self._capture.release()
                finally:
                    self._capture = None
                return None
            return frame
        return synthesize_frame(self._tick)

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                frame = await asyncio.to_thread(self._grab_frame)
                if frame is not None:
                    metrics = extract_frame_metrics(frame, self._prev_frame)
                    self._prev_frame = frame
                    self._frames_analyzed += 1
                    self._tick += 1
                    payload = {**metrics, "frames_analyzed": self._frames_analyzed}
                    if self.source == "simulate":
                        # Stamp synthetic data so it can never masquerade as a
                        # real camera downstream.
                        payload["simulated"] = True
                    await self.emit({
                        "asset_id": self.asset_id,
                        "collector_type": "video",
                        "timestamp_edge": datetime.now(timezone.utc).isoformat(),
                        "topic": "telemetry",
                        "payload": payload,
                    })
                else:
                    logger.warning("video_frame_unavailable", asset_id=self.asset_id)
            except Exception as exc:
                logger.error("video_capture_failed", asset_id=self.asset_id, error=str(exc))
            await asyncio.sleep(self.poll_interval)
