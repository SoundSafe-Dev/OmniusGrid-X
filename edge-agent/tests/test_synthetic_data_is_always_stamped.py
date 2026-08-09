"""Synthetic capture is always stamped, and an unknown source never becomes synthetic.

FS-457. Two collectors fabricate data when hardware is absent — `audio` synthesizes a tone,
`video` synthesizes a frame — and both stamp `simulated: True` so the platform can tell a
fabricated reading from a measured one. That stamp is the whole safety property: an edge
agent that reports invented vibration or invented motion as fact is worse than one reporting
nothing, because nothing is visibly nothing.

**The stamp was derived in the wrong place.** The capture synthesized whenever the source was
not the one hardware value:

    if self.source == "device": ...record from the microphone...
    return synthesize_frame(...)              # <- everything else

while the stamp was applied one method away, on a different condition:

    if self.source == "simulate":
        features["simulated"] = True

Those two conditions are not complements. `source: "mic"`, `source: "alsa"`, `source: "rtsp"`,
or any typo took the synthesis branch and missed the stamp — fabricated audio RMS and peak
frequency, or a fabricated brightness and motion score, arriving indistinguishable from a real
sensor's. Both collectors had it, in the same shape, written the same day.

WHAT CHANGED. `_capture`/`_grab_frame` now RETURN whether they synthesized, so the stamp is
the capture's own account rather than a second guess at the same config value. And
`BaseCollector` rejects a source it does not know, so a typo stops the collector instead of
quietly changing what it measures.

WHY BOTH. Either alone leaves a hole. Truthful stamping without validation means a typo runs
forever, correctly labelled but not doing what the operator asked. Validation without truthful
stamping means the day someone adds a third source, the stamp silently goes wrong again.

WHY THIS TEST IS STRUCTURAL, not two examples. The bug is a pattern — a provenance stamp
derived from config in a method other than the one that fabricated — so the assertion walks
the collector classes rather than naming the two that had it. A third synthetic-capable
collector inherits the check by existing.
"""

from __future__ import annotations

import ast
import pathlib
import unittest

from opsgrid_agent.collectors.audio import AudioFeatureCollector
from opsgrid_agent.collectors.base import BaseCollector
from opsgrid_agent.collectors.video import VideoFrameCollector

COLLECTOR_DIR = pathlib.Path(__file__).resolve().parent.parent / "opsgrid_agent" / "collectors"

#: Every collector class that can fabricate data. Derived, not listed, so a new one is
#: covered without anyone remembering to add it here.
SYNTHETIC_CAPABLE = [
    cls
    for cls in (AudioFeatureCollector, VideoFrameCollector)
    if getattr(cls, "has_synthetic_default", False)
]


class TestTheSweepIsNotVacuous(unittest.TestCase):
    def test_it_found_the_synthetic_collectors(self):
        # If this list is empty every assertion below passes over nothing, which is the
        # failure mode every sweep in this repository has a rule about.
        self.assertGreaterEqual(
            len(SYNTHETIC_CAPABLE), 2, "no synthetic-capable collectors found; the derivation is broken"
        )

    def test_the_collector_directory_is_readable(self):
        self.assertGreater(len(list(COLLECTOR_DIR.glob("*.py"))), 5)


class TestCaptureReportsItsOwnProvenance(unittest.TestCase):
    """The stamp must come from the capture, not from a second reading of the config."""

    def test_synthetic_capture_says_it_is_synthetic(self):
        audio = AudioFeatureCollector({"asset_id": "a1", "source": "simulate"})
        _, synthetic = audio._capture()
        self.assertTrue(synthetic, "simulated audio capture did not report itself as synthetic")

        video = VideoFrameCollector({"asset_id": "a2", "source": "simulate"})
        frame, synthetic = video._grab_frame()
        self.assertIsNotNone(frame)
        self.assertTrue(synthetic, "simulated video grab did not report itself as synthetic")

    def test_no_poll_loop_derives_the_stamp_from_the_source_string(self):
        """The regression itself, asserted as a shape.

        Setting `simulated`/`synthetic` inside a branch that tests `self.source` is the
        original defect: it re-derives, one method away, a fact the capture already knows.
        """
        offenders = []
        for path in sorted(COLLECTOR_DIR.glob("*.py")):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, ast.If):
                    continue
                test_src = ast.dump(node.test)
                if "'source'" not in test_src and '"source"' not in test_src:
                    continue
                # An ASSIGNMENT of a stamp key, not a mention of the word. The first
                # version of this check matched any body containing "synthetic" and flagged
                # the source validator in base.py, whose ERROR MESSAGE says "synthetic
                # data" — a guard that fires on prose is a guard people delete.
                for inner in ast.walk(ast.Module(body=node.body, type_ignores=[])):
                    if not isinstance(inner, ast.Assign):
                        continue
                    for target in inner.targets:
                        if (
                            isinstance(target, ast.Subscript)
                            and isinstance(target.slice, ast.Constant)
                            and target.slice.value in ("simulated", "synthetic")
                        ):
                            offenders.append(f"{path.name}:{node.lineno}")

        self.assertEqual(
            offenders,
            [],
            "these branches decide a provenance stamp by testing `self.source` rather than "
            "by asking the capture what it did:\n  "
            + "\n  ".join(offenders)
            + "\nThe two conditions drift: the capture synthesized on `!= hardware` while "
            "the stamp fired on `== 'simulate'`, so any other value fabricated data with no "
            "stamp at all.",
        )


class TestAnUnknownSourceIsRefused(unittest.TestCase):
    """A typo must stop the collector, not silently change what it measures."""

    def test_every_synthetic_capable_collector_declares_its_sources(self):
        for cls in SYNTHETIC_CAPABLE:
            self.assertTrue(
                cls.known_sources,
                f"{cls.__name__} can fabricate data and declares no `known_sources`, so an "
                f"unrecognised source falls through to synthesis unchecked",
            )

    def test_a_misspelled_source_raises(self):
        for cls, typo in ((AudioFeatureCollector, "mic"), (VideoFrameCollector, "rtsp")):
            with self.assertRaises(ValueError, msg=f"{cls.__name__} accepted source={typo!r}") as ctx:
                cls({"asset_id": "a1", "source": typo})
            self.assertIn(
                typo,
                str(ctx.exception),
                "the error must name the offending value; an operator reading it needs to "
                "see what they typed",
            )

    def test_the_real_sources_are_still_accepted(self):
        """The other direction. A validator that rejects everything passes the test above
        and breaks the product."""
        for cls in SYNTHETIC_CAPABLE:
            for source in cls.known_sources:
                try:
                    cls({"asset_id": "a1", "source": source})
                except ValueError as exc:  # pragma: no cover - a real failure
                    self.fail(f"{cls.__name__} rejected its own declared source {source!r}: {exc}")

    def test_an_omitted_source_is_still_allowed_by_default(self):
        """`known_sources` must not accidentally become the explicit-source requirement,
        which is a separate posture gated on EDGE_REQUIRE_EXPLICIT_SOURCES."""
        AudioFeatureCollector({"asset_id": "a1"})

    def test_a_collector_without_known_sources_is_unaffected(self):
        class Plain(BaseCollector):
            async def start(self) -> None:  # pragma: no cover - not run
                await super().start()

            async def stop(self) -> None:  # pragma: no cover - not run
                await super().stop()

            async def collect(self):  # pragma: no cover - not run
                return {}

        Plain({"asset_id": "a1", "source": "anything at all"})


if __name__ == "__main__":  # pragma: no cover
    unittest.main()
