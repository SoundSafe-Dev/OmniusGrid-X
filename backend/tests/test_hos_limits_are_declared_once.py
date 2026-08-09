"""The federal hours-of-service limits are written once (FS-475).

49 CFR 395 sets the driving limits for property-carrying drivers. They are law: they do not
vary by deployment and this platform has no opinion about them. What it had was three copies.

    services/transportation_management.py   all four, as class attributes
    api/transportation.py                   two of them, re-declared at module level
    api/fleet_logistics.py                  reached them through the compliance class

**Two copies fed different answers about the same driver.** `api/transportation.py` computes
hours REMAINING — what a dispatcher reads before assigning a load. The compliance service
decides VIOLATIONS — what a compliance officer reads afterwards. Edit one and not the other,
and the platform tells the dispatcher a driver has two hours left while telling the officer
that same driver is in breach. Both numbers look authoritative and neither says which is
stale.

WHY IT SURVIVED REVIEW, which is the part worth keeping. The duplicate carried a reason:
*"Kept beside the serializer that needs them rather than imported from the compliance service,
which would drag its session dependencies into this module."* That was true — and already
being ignored, since `fleet_logistics` imports the same class for the same purpose. **A
justified duplicate is harder to spot than an unjustified one**, because the comment answers
the question a reviewer was about to ask.

The answer was a module with no imports. A constant cannot drag a session dependency if it
lives somewhere that has none.

WHAT THIS ASSERTS. That the numbers are declared once and that every access path resolves to
that declaration — not that the values are right. They are federal law; if they change, they
change in `hos_limits.py` and everywhere follows.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

from app.core import hos_limits

APP = Path(__file__).resolve().parent.parent / "app"

LIMITS = (
    "MAX_DRIVE_HOURS_DAY",
    "MAX_ON_DUTY_HOURS_DAY",
    "MAX_CYCLE_HOURS",
    "REQUIRED_REST_HOURS",
)


def _literal_assignments(name: str) -> list[str]:
    """Files assigning `name` to a bare number, other than the one place it belongs."""
    found = []
    for path in sorted(APP.rglob("*.py")):
        if path.name == "hos_limits.py":
            continue
        try:
            tree = ast.parse(path.read_text())
        except SyntaxError:  # pragma: no cover
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.Assign) or not isinstance(node.value, ast.Constant):
                continue
            if not isinstance(node.value.value, (int, float)):
                continue
            for target in node.targets:
                if getattr(target, "id", None) == name or getattr(target, "attr", None) == name:
                    found.append(f"{path.relative_to(APP.parent)}:{node.lineno}")
    return found


class TestTheSweepCanSeeItsSubject:
    def test_the_module_declares_all_four(self):
        for name in LIMITS:
            assert hasattr(hos_limits, name), f"{name} is not in hos_limits"

    def test_the_walk_reads_the_app(self):
        assert len(list(APP.rglob("*.py"))) > 100, "the module walk is broken"


@pytest.mark.parametrize("name", LIMITS)
def test_the_limit_is_assigned_a_literal_in_exactly_one_place(name: str):
    duplicates = _literal_assignments(name)
    assert not duplicates, (
        f"{name} is assigned a literal number outside `app/core/hos_limits.py`, at "
        f"{duplicates}. Two copies of a federal limit can disagree, and when they do one "
        f"surface tells a dispatcher a driver may keep driving while another records the "
        f"same driver as in breach."
    )


class TestEveryAccessPathResolvesToTheOneDeclaration:
    """Importing the name is not enough — it has to be the same value."""

    def test_the_api_module_uses_it(self):
        from app.api import transportation

        assert transportation.MAX_DRIVE_HOURS_DAY is hos_limits.MAX_DRIVE_HOURS_DAY
        assert transportation.MAX_ON_DUTY_HOURS_DAY is hos_limits.MAX_ON_DUTY_HOURS_DAY

    def test_the_compliance_class_uses_it(self):
        """`fleet_logistics` reaches these through `HOSComplianceMonitor`, so the class
        attributes have to be the module's values rather than a second set that happens to
        match today."""
        from app.services.transportation_management import HOSComplianceMonitor

        for name in LIMITS:
            assert getattr(HOSComplianceMonitor, name) is getattr(hos_limits, name), (
                f"HOSComplianceMonitor.{name} is not the value from hos_limits, so the two "
                f"can drift apart while both look correct"
            )

    def test_the_remaining_hours_and_the_violation_check_agree(self):
        """The specific pair that mattered. Same driver, same limit, two surfaces."""
        from app.api import transportation
        from app.services.transportation_management import HOSComplianceMonitor

        assert (
            transportation.MAX_DRIVE_HOURS_DAY == HOSComplianceMonitor.MAX_DRIVE_HOURS_DAY
        ), (
            "the module computing hours REMAINING and the service deciding VIOLATIONS "
            "disagree about the daily driving limit"
        )


class TestTheValuesAreTheFederalOnes:
    """A guard against a well-meaning edit. These are 49 CFR 395, not tuning."""

    @pytest.mark.parametrize(
        "name,expected",
        [
            ("MAX_DRIVE_HOURS_DAY", 11.0),
            ("MAX_ON_DUTY_HOURS_DAY", 14.0),
            ("MAX_CYCLE_HOURS", 70.0),
            ("REQUIRED_REST_HOURS", 10.0),
        ],
    )
    def test_the_limit(self, name: str, expected: float):
        assert getattr(hos_limits, name) == expected, (
            f"{name} is no longer {expected}. These are federal limits, not defaults — if "
            f"the regulation changed, update the citation in hos_limits.py with it."
        )

    def test_each_one_cites_its_regulation(self):
        source = (APP / "core" / "hos_limits.py").read_text()
        for name in LIMITS:
            block = source.split(name)[0].rsplit("#:", 1)[-1]
            assert re.search(r"49 CFR 395", block), (
                f"{name} has no citation. A number that is law should say which law, or "
                f"the next reader has no way to check it."
            )
