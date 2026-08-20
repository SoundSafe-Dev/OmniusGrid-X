"""Importing a collector must not require its optional driver (FS-767).

`requirements-dev.txt` states this as fact and builds CI around it:

    The industrial protocol driver libraries ... are FAKED in the tests via sys.modules, so
    they are intentionally NOT installed here — this keeps CI fast and avoids native-lib
    install issues (e.g. snap7's libsnap7, opencv). **The collectors import their drivers
    lazily**, so importing them without the drivers is exercised on purpose.

`screen_scraper.py` did not. It imported `cv2`, `numpy` and `pytesseract` at module scope, and
`collectors/coordinator.py` imports `screen_scraper` at module scope — so **importing the
coordinator required the entire OCR stack**, in a suite that deliberately does not install it.

Nothing noticed for as long as no test imported the coordinator. When one did, the edge suite
failed at COLLECTION with `ModuleNotFoundError: No module named 'cv2'`, and a pytest marker
cannot save you there: deselection happens after the module is imported.

RUN IN A SUBPROCESS, NOT BY PATCHING `sys.modules`. The first version purged `opsgrid_agent.*`
and re-imported in-process, which re-registered the Prometheus collectors and failed with
"Duplicated timeseries in CollectorRegistry" — a harness artifact reported as a product
defect. A fresh interpreter is also the honest simulation: CI does not re-import, it imports
once, in a process where the driver was never installed.
"""

from __future__ import annotations

import subprocess
import sys
import textwrap

import pytest

#: Drivers a deployment may legitimately lack. Each is optional for a reason: a native library
#: that is awkward to install, or a capability an image does not carry — the UBI9/FIPS edge
#: image has no tesseract binary at all (FS-761).
OPTIONAL_DRIVERS = ["cv2", "pytesseract", "pylogix", "snap7", "BAC0", "can"]

#: `coordinator` matters most: it imports every collector, so it is the single place where
#: one eager import breaks everything downstream of it.
MUST_IMPORT_BARE = [
    "opsgrid_agent.collectors.coordinator",
    "opsgrid_agent.collectors.screen_scraper",
    "opsgrid_agent.main",
]

BLOCKER = """
import builtins, sys
BLOCKED = {blocked!r}
_real = builtins.__import__
def _guard(name, *a, **k):
    if name.split('.')[0] in BLOCKED:
        raise ImportError("No module named %r (simulated)" % name.split('.')[0])
    return _real(name, *a, **k)
builtins.__import__ = _guard
"""


def _import_in_clean_process(module: str, blocked: list[str]) -> subprocess.CompletedProcess:
    script = textwrap.dedent(BLOCKER).format(blocked=blocked) + f"import {module}\nprint('ok')\n"
    return subprocess.run(
        [sys.executable, "-c", script],
        capture_output=True,
        text=True,
        timeout=120,
    )


class TestTheSweepIsReal:
    def test_the_blocker_actually_blocks(self):
        """Vacuity. If the guard does not bite, every assertion below passes on any machine
        that simply has the drivers installed — which is every developer machine, and is
        exactly where this defect hid for as long as it did."""
        result = _import_in_clean_process("cv2", ["cv2"])
        assert result.returncode != 0, "the import guard did not block a blocked module"
        assert "simulated" in result.stderr


@pytest.mark.parametrize("module", MUST_IMPORT_BARE)
class TestImportingWithoutDrivers:
    def test_it_imports_with_no_optional_driver_at_all(self, module):
        result = _import_in_clean_process(module, OPTIONAL_DRIVERS)
        assert result.returncode == 0, (
            f"{module} cannot be imported without its optional drivers:\n"
            f"{result.stderr[-1200:]}"
        )

    def test_it_imports_when_only_the_ocr_stack_is_missing(self, module):
        """The case CI actually runs: the protocol drivers are faked into `sys.modules` by
        the suite, and opencv is simply not installed."""
        result = _import_in_clean_process(module, ["cv2", "pytesseract"])
        assert (
            result.returncode == 0
        ), f"{module} needs the OCR stack to import:\n{result.stderr[-1200:]}"


class TestLazyDoesNotMeanSilent:
    def test_using_the_collector_without_its_driver_names_the_fix(self):
        """A collector that cannot work has to say so, with a message naming the remedy. The
        alternative is an OCR collector that imports cleanly and then produces nothing —
        the quiet-failure class this repository has a rule about."""
        script = textwrap.dedent(BLOCKER).format(blocked=["cv2", "pytesseract"]) + textwrap.dedent(
            """
            from opsgrid_agent.collectors import screen_scraper
            try:
                screen_scraper._imaging()
            except ImportError as exc:
                assert 'opencv-python' in str(exc), str(exc)
                print('ok')
            else:
                raise AssertionError('_imaging() succeeded with the OCR stack blocked')
            """
        )
        result = subprocess.run(
            [sys.executable, "-c", script], capture_output=True, text=True, timeout=120
        )
        assert result.returncode == 0, result.stderr[-800:]
