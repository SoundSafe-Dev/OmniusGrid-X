"""Tests for the audio feature collector (Phase B, task 12)."""

import asyncio
import unittest

import numpy as np

from opsgrid_agent.collectors.audio import (
    AudioFeatureCollector,
    extract_audio_features,
    synthesize_frame,
)


def sine(freq_hz: float, sample_rate: int = 16000, seconds: float = 1.0, amp: float = 1.0):
    t = np.arange(int(sample_rate * seconds)) / sample_rate
    return (amp * np.sin(2 * np.pi * freq_hz * t)).astype(np.float64)


class ExtractFeaturesTest(unittest.TestCase):
    def test_pure_tone_peak_and_rms(self):
        x = sine(1000.0, amp=1.0)
        f = extract_audio_features(x, 16000)
        # sine RMS = amp/sqrt(2); FFT peak at the tone frequency
        self.assertAlmostEqual(f["audio_rms"], 1 / np.sqrt(2), places=3)
        self.assertAlmostEqual(f["audio_peak_hz"], 1000.0, delta=2.0)

    def test_band_energy_concentrates_where_the_tone_is(self):
        low = extract_audio_features(sine(100.0), 16000)
        mid = extract_audio_features(sine(1000.0), 16000)
        high = extract_audio_features(sine(4000.0), 16000)
        self.assertGreater(low["audio_band_low"], 0.95)
        self.assertGreater(mid["audio_band_mid"], 0.95)
        self.assertGreater(high["audio_band_high"], 0.95)

    def test_empty_frame_is_all_zero(self):
        f = extract_audio_features(np.array([]), 16000)
        self.assertEqual(f["audio_rms"], 0.0)
        self.assertEqual(f["audio_peak_hz"], 0.0)

    def test_synthesized_demo_frame_has_expected_peak(self):
        x = synthesize_frame(16000, 1.0, 900.0, tick=3)
        f = extract_audio_features(x, 16000)
        self.assertAlmostEqual(f["audio_peak_hz"], 900.0, delta=40.0)  # drift ±2%
        self.assertGreater(f["audio_rms"], 0.1)


class CollectorTest(unittest.TestCase):
    def test_simulate_mode_emits_feature_payload(self):
        async def run():
            collector = AudioFeatureCollector({
                "asset_id": "asset-6",
                "source": "simulate",
                "sample_rate": 8000,
                "frame_seconds": 0.25,
                "poll_interval": 0.05,
            })
            received = []
            collector.add_data_handler(received.append)
            await collector.start()
            await asyncio.sleep(0.15)
            await collector.stop()
            return received

        received = asyncio.run(run())
        self.assertGreaterEqual(len(received), 1)
        msg = received[0]
        self.assertEqual(msg["asset_id"], "asset-6")
        self.assertEqual(msg["collector_type"], "audio")
        for key in ("audio_rms", "audio_peak_hz", "audio_band_low",
                    "audio_band_mid", "audio_band_high"):
            self.assertIn(key, msg["payload"])


if __name__ == "__main__":
    unittest.main()
