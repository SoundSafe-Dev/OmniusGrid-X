"""FS-63: the shipped real-capture config examples must stay valid.

Loads the audio/video entries from config/poc_collectors.yml, validates them
through the collector config schema, and exercises both collectors' capture →
feature-extraction paths in simulate mode (the hardware-free path), proving a
config-file-driven boot works. Device/stream modes need real hardware and are
covered by docs/edge/SENSOR_CAPTURE.md's cutover checklist instead.

Run: python -m unittest tests.test_sensor_capture_config   (from edge-agent/)
"""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import yaml

from opsgrid_agent.collectors.audio import AudioFeatureCollector, extract_audio_features
from opsgrid_agent.collectors.video import VideoFrameCollector, extract_frame_metrics
from opsgrid_agent.config_schema import validate_entries

CONFIG = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                      "config", "poc_collectors.yml")


def _entries(collector_type):
    with open(CONFIG) as f:
        doc = yaml.safe_load(f)
    return [c for c in doc["collectors"] if c["collector_type"] == collector_type]


class SensorCaptureConfigTest(unittest.TestCase):
    def test_examples_exist_and_validate(self):
        with open(CONFIG) as f:
            doc = yaml.safe_load(f)
        validated = validate_entries(doc["collectors"])
        # validate_entries normalizes collector_type -> type (alias)
        types = {c.get("type") or c.get("collector_type") for c in validated}
        self.assertIn("audio", types, "no audio example in poc_collectors.yml")
        self.assertIn("video", types, "no video example in poc_collectors.yml")

    def test_audio_boots_from_config_in_simulate(self):
        entry = _entries("audio")[0]
        cfg = {**entry["config"], "source": "simulate", "asset_id": entry["asset_id"]}
        collector = AudioFeatureCollector(cfg)
        samples, synthetic = collector._capture()
        self.assertTrue(synthetic, "simulate mode must report itself as synthetic")
        features = extract_audio_features(samples, collector.sample_rate)
        self.assertIn("audio_rms", features)
        self.assertIn("audio_peak_hz", features)
        # the example ships tuned for real capture but must run simulated
        self.assertGreater(features["audio_rms"], 0)

    def test_video_boots_from_config_in_simulate(self):
        entry = _entries("video")[0]
        cfg = {**entry["config"], "source": "simulate", "asset_id": entry["asset_id"]}
        cfg.pop("stream_url", None)
        collector = VideoFrameCollector(cfg)
        frame, synthetic = collector._grab_frame()
        self.assertTrue(synthetic, "simulate mode must report itself as synthetic")
        self.assertIsNotNone(frame)
        metrics = extract_frame_metrics(frame, None)
        self.assertIn("frame_brightness", metrics)
        self.assertIn("motion_score", metrics)
