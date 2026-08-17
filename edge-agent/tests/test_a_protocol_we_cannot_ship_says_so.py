"""A protocol whose driver is not in the image must not be listed as if it were (FS-738).

THE GAP IS PACKAGING, NOT PROTOCOL. The DNP3 collector is written, hardened by the same
sweeps as every other collector — one `ReconnectPolicy`, aware-UTC timestamps, counted
failures — and tested against a fake master. It has never spoken to a real outstation,
because `dnp3_python` publishes **cp38–cp310 linux wheels only**:

    requirements.txt   dnp3-python==0.2.3b3; sys_platform == "linux"
                                             and python_version < "3.11"
    Dockerfile         FROM python:3.11-slim
    pyproject.toml     requires-python = ">=3.11"

The marker and the image do not overlap, so **the driver is absent from every image we
build**. Live DNP3 sites: zero, by construction rather than by accident.

WHY A TEST RATHER THAN A COMMENT. The comment already existed in `requirements.txt` and
was accurate, and the protocol was still listed beside MQTT and Modbus in the architecture
diagram with nothing to distinguish it. Two facts in two files drift the moment one is
edited: the day someone finds a py3.11 wheel, the caveat has to come OUT of the docs, and
nothing would have told them where it was. This pairs the two directions —

  * a driver excluded from the image, listed without a caveat, fails here;
  * a caveat left in the docs after the driver becomes installable ALSO fails here.

The second is the one that rots quietly, and it is the reason this is not simply a lint
for the word "DNP3".
"""

from __future__ import annotations

import pathlib
import re

import pytest

AGENT = pathlib.Path(__file__).resolve().parents[1]
REPO = AGENT.parent
REQUIREMENTS = AGENT / "requirements.txt"
DOCKERFILE = AGENT / "Dockerfile"
README = REPO / "README.md"

#: Protocol -> the distribution its collector imports at runtime. Only protocols whose
#: driver is a THIRD-PARTY wheel belong here; the rest are pure-python or vendored.
DRIVER_FOR = {"DNP3": "dnp3-python"}

#: The phrase the documentation must carry beside a protocol we cannot currently ship.
#: Short and searchable on purpose — the day the wheel exists, `grep` finds every site.
CAVEAT = "not field-proven"


def _image_python() -> tuple[int, int]:
    """The interpreter the agent image actually runs."""
    match = re.search(r"^FROM python:(\d+)\.(\d+)", DOCKERFILE.read_text(), re.M)
    assert match, f"no `FROM python:X.Y` in {DOCKERFILE}; this check cannot be evaluated"
    return int(match.group(1)), int(match.group(2))


def _pin_for(distribution: str) -> str | None:
    for line in REQUIREMENTS.read_text().splitlines():
        if line.strip().startswith(distribution):
            return line
    return None


def _excluded_from_image(pin: str, python: tuple[int, int]) -> bool:
    """Does this pin's marker exclude it at the image's Python version?

    Deliberately narrow: it understands `python_version < "X.Y"`, which is the marker in
    use. An unrecognised marker returns False — "we could not prove it is excluded" — so
    this check can never invent a gap it has not demonstrated.
    """
    match = re.search(r'python_version\s*<\s*"(\d+)\.(\d+)"', pin)
    if not match:
        return False
    return python >= (int(match.group(1)), int(match.group(2)))


class TestTheMeasurementIsReal:
    def test_the_image_python_is_readable(self):
        major, minor = _image_python()
        assert (major, minor) >= (3, 8), f"implausible image python {major}.{minor}"

    def test_the_dnp3_pin_is_still_there(self):
        """If the pin is deleted rather than fixed, every assertion below passes over
        nothing — and the protocol would still be listed in the diagram."""
        assert _pin_for("dnp3-python") is not None, (
            "no dnp3-python line in requirements.txt. If the dependency was removed, the "
            "collector and its documentation entries should go with it."
        )


@pytest.mark.parametrize("protocol,distribution", sorted(DRIVER_FOR.items()))
class TestTheDocumentationMatchesWhatShips:
    def test_a_protocol_we_cannot_ship_carries_the_caveat(
        self, protocol: str, distribution: str
    ):
        pin = _pin_for(distribution)
        if pin is None or not _excluded_from_image(pin, _image_python()):
            pytest.skip(f"{distribution} is installable on the image python")
        text = README.read_text()
        assert CAVEAT in text, (
            f"{protocol}'s driver ({distribution}) is excluded from the agent image by its "
            f"own marker, so no deployment can run it — and the README does not say "
            f"{CAVEAT!r} anywhere. A protocol listed beside MQTT and Modbus reads as "
            f"equally deployable."
        )
        # The caveat has to be NEAR the protocol, not merely present somewhere in a long
        # file. Proximity is a weak test on its own (rule 206) — it is a floor here, with
        # the pairing above carrying the real weight.
        window = 600
        positions = [m.start() for m in re.finditer(protocol, text)]
        assert positions, f"{protocol} is not mentioned in the README at all"
        assert any(
            CAVEAT in text[max(0, p - window): p + window] for p in positions
        ), (
            f"the README mentions {protocol} {len(positions)} time(s) and none is within "
            f"{window} characters of {CAVEAT!r}. The caveat exists but a reader scanning "
            f"the protocol list will not meet it."
        )

    def test_the_caveat_is_removed_once_the_driver_ships(
        self, protocol: str, distribution: str
    ):
        """THE DIRECTION THAT ROTS QUIETLY. When a py3.11 wheel lands and the marker comes
        off, a stale 'not field-proven' understates the product — and nobody re-reads the
        docs on a dependency bump."""
        pin = _pin_for(distribution)
        if pin is not None and _excluded_from_image(pin, _image_python()):
            pytest.skip(f"{distribution} is still excluded from the image")
        text = README.read_text()
        positions = [m.start() for m in re.finditer(protocol, text)]
        stale = [
            p for p in positions if CAVEAT in text[max(0, p - 600): p + 600]
        ]
        assert not stale, (
            f"{distribution} is now installable on the image python, and the README still "
            f"describes {protocol} as {CAVEAT!r}. Remove the caveat — and the entry in "
            f"`DRIVER_FOR` above, which exists only while the gap does."
        )
