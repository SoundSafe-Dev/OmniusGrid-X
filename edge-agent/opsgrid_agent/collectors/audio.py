"""Audio feature collector (Phase B, task 12).

Captures audio from a device (or synthesizes a demo signal) and emits *feature
telemetry* — not raw audio — so acoustic condition data rides the normal
quality→buffer→ingest→Telemetry path and is consumable by downstream analytics
(anomaly, health index, correlation) like any other metric:

    audio_rms        overall level (0..1 for normalized input)
    audio_peak_hz    dominant frequency
    audio_band_low   energy fraction  < 300 Hz    (rumble / imbalance)
    audio_band_mid   energy fraction 300–2000 Hz  (normal operation)
    audio_band_high  energy fraction  > 2000 Hz   (bearing wear / friction)

Config:
    asset_id (str):          Asset the readings belong to (required)
    source (str):            "device" (microphone via sounddevice) or
                             "simulate" (synthetic signal; the demo default)
    sample_rate (int):       Hz (default 16000)
    frame_seconds (float):   capture window per reading (default 1.0)
    poll_interval (float):   seconds between readings (default 10)
    simulate_freq_hz (float): tone frequency for simulate mode (default 900)

The DSP is pure (numpy) and unit-tested; the capture backend is optional and the
collector degrades gracefully (parks with a log) when sounddevice is absent —
matching the other driver-dependent collectors.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import asyncio
import math

import numpy as np
import structlog

from .base import BaseCollector

logger = structlog.get_logger()

try:
    import sounddevice as _sounddevice
    _SD_AVAILABLE = True
    _SD_IMPORT_ERROR: Optional[str] = None
except Exception as exc:  # pragma: no cover - exercised only without the driver
    _sounddevice = None  # type: ignore
    _SD_AVAILABLE = False
    _SD_IMPORT_ERROR = str(exc)

BAND_LOW_HZ = 300.0
BAND_HIGH_HZ = 2000.0


def extract_audio_features(samples: "np.ndarray", sample_rate: int) -> Dict[str, float]:
    """Pure DSP: samples -> feature dict (RMS, peak Hz, band energy fractions)."""
    if samples.size == 0:
        return {
            "audio_rms": 0.0, "audio_peak_hz": 0.0,
            "audio_band_low": 0.0, "audio_band_mid": 0.0, "audio_band_high": 0.0,
        }
    x = samples.astype(np.float64)
    rms = float(np.sqrt(np.mean(x ** 2)))

    spectrum = np.abs(np.fft.rfft(x))
    freqs = np.fft.rfftfreq(x.size, d=1.0 / sample_rate)
    # Ignore DC when finding the dominant frequency.
    if spectrum.size > 1:
        peak_idx = int(np.argmax(spectrum[1:])) + 1
        peak_hz = float(freqs[peak_idx])
    else:  # pragma: no cover - degenerate single-bin case
        peak_hz = 0.0

    power = spectrum ** 2
    total = float(np.sum(power[1:])) or 1.0
    low = float(np.sum(power[(freqs > 0) & (freqs < BAND_LOW_HZ)]))
    mid = float(np.sum(power[(freqs >= BAND_LOW_HZ) & (freqs <= BAND_HIGH_HZ)]))
    high = float(np.sum(power[freqs > BAND_HIGH_HZ]))

    return {
        "audio_rms": round(rms, 6),
        "audio_peak_hz": round(peak_hz, 1),
        "audio_band_low": round(low / total, 4),
        "audio_band_mid": round(mid / total, 4),
        "audio_band_high": round(high / total, 4),
    }


def synthesize_frame(sample_rate: int, seconds: float, freq_hz: float, tick: int = 0) -> "np.ndarray":
    """Demo signal: a tone + drifting harmonics + noise, deterministic per tick."""
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    rng = np.random.default_rng(tick)  # deterministic per tick, varies over time
    drift = 1.0 + 0.02 * math.sin(tick / 7.0)
    signal = (
        0.5 * np.sin(2 * np.pi * freq_hz * drift * t)
        + 0.15 * np.sin(2 * np.pi * 2 * freq_hz * drift * t)
        + 0.05 * rng.standard_normal(t.size)
    )
    return signal.astype(np.float32)


class AudioFeatureCollector(BaseCollector):
    """Collector emitting audio feature telemetry from a mic or demo signal."""

    # Defaults to a synthetic source -> BaseCollector enforces explicit config
    # under EDGE_REQUIRE_EXPLICIT_SOURCES (no silent demo tones).
    has_synthetic_default = True
    known_sources = ("device", "simulate")

    def __init__(self, config: Dict[str, Any]):
        super().__init__(config)
        self.source = config.get("source", "simulate")
        self.sample_rate = int(config.get("sample_rate", 16000))
        self.frame_seconds = float(config.get("frame_seconds", 1.0))
        self.poll_interval = float(config.get("poll_interval", 10))
        self.simulate_freq_hz = float(config.get("simulate_freq_hz", 900))
        self._poll_task: Optional[asyncio.Task] = None
        self._tick = 0

    async def start(self) -> None:
        await super().start()
        if self.source == "device" and not _SD_AVAILABLE:
            self._running = False
            logger.error("audio_driver_missing", asset_id=self.asset_id,
                         error=_SD_IMPORT_ERROR, hint="pip install sounddevice")
            return
        self._poll_task = asyncio.create_task(self._poll_loop())
        logger.info("audio_collector_started", asset_id=self.asset_id,
                    source=self.source, sample_rate=self.sample_rate)

    async def stop(self) -> None:
        await super().stop()
        if self._poll_task:
            self._poll_task.cancel()
            try:
                await self._poll_task
            except asyncio.CancelledError:
                pass
        logger.info("audio_collector_stopped", asset_id=self.asset_id)

    def _capture(self) -> "tuple[np.ndarray, bool]":
        """Blocking capture of one frame (runs in a worker thread).

        Returns (samples, synthetic). The flag is the CAPTURE's own account of what it
        did, so the provenance stamp downstream cannot disagree with it (FS-457).
        """
        if self.source == "device":
            frames = int(self.sample_rate * self.frame_seconds)
            recording = _sounddevice.rec(  # type: ignore[union-attr]
                frames, samplerate=self.sample_rate, channels=1, dtype="float32"
            )
            _sounddevice.wait()  # type: ignore[union-attr]
            return recording.reshape(-1), False
        return (synthesize_frame(self.sample_rate, self.frame_seconds,
                                 self.simulate_freq_hz, self._tick), True)

    async def _poll_loop(self) -> None:
        while self._running:
            try:
                samples, synthetic = await asyncio.to_thread(self._capture)
                features = extract_audio_features(samples, self.sample_rate)
                if synthetic:
                    # Stamp synthetic data so it can never masquerade as a real
                    # microphone downstream.
                    #
                    # THE STAMP COMES FROM `_capture`, not from re-reading `self.source`
                    # here (FS-457). It used to be `if self.source == "simulate"`, while
                    # `_capture` synthesized whenever the source was not "device" — two
                    # conditions that are not complements. Any other value, including a
                    # typo like "mic" or "alsa", produced synthetic audio with NO stamp,
                    # which is the one outcome the stamp exists to prevent.
                    features["simulated"] = True
                self._tick += 1
                await self.emit({
                    "asset_id": self.asset_id,
                    "collector_type": "audio",
                    "timestamp_edge": datetime.now(timezone.utc).isoformat(),
                    "topic": "telemetry",
                    "payload": features,
                })
            except Exception as exc:
                self.record_failure("audio_capture_failed", error=str(exc))
            await asyncio.sleep(self.poll_interval)
