"""Tests for the video frame-metric collector (Phase B, task 14)."""

import asyncio
import unittest

import numpy as np

from opsgrid_agent.collectors.video import (
    VideoFrameCollector,
    extract_frame_metrics,
    synthesize_frame,
)


class ExtractFrameMetricsTest(unittest.TestCase):
    def test_brightness_and_contrast(self):
        dark = np.full((32, 32), 10.0)
        bright = np.full((32, 32), 240.0)
        self.assertEqual(extract_frame_metrics(dark)["frame_brightness"], 10.0)
        self.assertEqual(extract_frame_metrics(bright)["frame_brightness"], 240.0)
        # Uniform frames have zero contrast.
        self.assertEqual(extract_frame_metrics(bright)["frame_contrast"], 0.0)

    def test_motion_zero_for_identical_frames(self):
        frame = synthesize_frame(0)
        m = extract_frame_metrics(frame, frame)
        self.assertEqual(m["motion_score"], 0.0)

    def test_motion_positive_when_content_moves(self):
        a = synthesize_frame(0)
        b = synthesize_frame(1)  # square moved
        m = extract_frame_metrics(b, a)
        self.assertGreater(m["motion_score"], 0.0)

    def test_color_frames_collapse_to_luminance(self):
        color = np.full((16, 16, 3), 120.0)
        self.assertEqual(extract_frame_metrics(color)["frame_brightness"], 120.0)

    def test_empty_frame(self):
        m = extract_frame_metrics(np.array([]))
        self.assertEqual(m["frame_brightness"], 0.0)


class CollectorTest(unittest.TestCase):
    def test_simulate_mode_emits_frame_metrics(self):
        async def run():
            collector = VideoFrameCollector({
                "asset_id": "asset-7",
                "source": "simulate",
                "poll_interval": 0.05,
            })
            received = []
            collector.add_data_handler(received.append)
            await collector.start()
            await asyncio.sleep(0.18)
            await collector.stop()
            return received

        received = asyncio.run(run())
        self.assertGreaterEqual(len(received), 2)
        first, second = received[0], received[1]
        self.assertEqual(first["collector_type"], "video")
        for key in ("frame_brightness", "frame_contrast", "motion_score", "frames_analyzed"):
            self.assertIn(key, first["payload"])
        # First frame has no previous -> zero motion; second sees the square move.
        self.assertEqual(first["payload"]["motion_score"], 0.0)
        self.assertGreater(second["payload"]["motion_score"], 0.0)
        self.assertEqual(second["payload"]["frames_analyzed"], 2)


if __name__ == "__main__":
    unittest.main()
