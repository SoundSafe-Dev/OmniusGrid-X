#!/usr/bin/env python3
"""Fail CI when a pytest exclusion is missing an active quarantine marker.

Every ``--ignore`` or ``--deselect`` in a workflow must be immediately
preceded by a marker in this form::

    # TEST_QUARANTINE --ignore=tests/test_example.py owner=team expires=2026-09-01 reason=temporary parser migration

This is deliberately a small standard-library check so it can run before the
test suite itself.  A temporary exclusion must be visible, owned, and time
bounded; otherwise it can silently become permanent green CI debt.
"""

from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path
from typing import List, Optional


PYTEST_EXCLUSION = re.compile(r"(?P<argument>--(?:ignore|deselect)(?:=|\s+)[^\s\\]+)")
MARKER = re.compile(
    r"^\s*#\s*TEST_QUARANTINE\s+(?P<argument>--(?:ignore|deselect)(?:=|\s+)[^\s\\]+)"
    r"\s+owner=(?P<owner>[^\s]+)\s+expires=(?P<expiry>\d{4}-\d{2}-\d{2})"
    r"\s+reason=(?P<reason>.+?)\s*$"
)


def _normalise(argument: str) -> str:
    """Make ``--deselect foo`` and ``--deselect=foo`` compare identically."""
    option, value = re.split(r"(?:=|\s+)", argument, maxsplit=1)
    return f"{option}={value}"


def check(workflow: Path, *, today: Optional[date] = None) -> List[str]:
    """Return actionable errors for unregistered, stale, or expired exclusions."""
    today = today or date.today()
    lines = workflow.read_text().splitlines()
    errors: List[str] = []
    markers: dict[str, tuple[int, date]] = {}
    exclusions: dict[str, int] = {}

    for line_number, raw_line in enumerate(lines, start=1):
        marker = MARKER.match(raw_line)
        if marker:
            argument = _normalise(marker.group("argument"))
            try:
                expiry = date.fromisoformat(marker.group("expiry"))
            except ValueError:
                errors.append(f"{workflow}:{line_number}: invalid TEST_QUARANTINE expiry")
                continue
            if not marker.group("owner") or not marker.group("reason").strip():
                errors.append(f"{workflow}:{line_number}: TEST_QUARANTINE needs owner and reason")
            markers[argument] = (line_number, expiry)
            continue

        if raw_line.lstrip().startswith("#"):
            continue
        for exclusion in PYTEST_EXCLUSION.finditer(raw_line):
            argument = _normalise(exclusion.group("argument"))
            exclusions[argument] = line_number

    for argument, line_number in sorted(exclusions.items()):
        marker = markers.get(argument)
        if marker is None:
            errors.append(
                f"{workflow}:{line_number}: {argument} requires a preceding TEST_QUARANTINE marker"
            )
            continue
        marker_line, expiry = marker
        if marker_line != line_number - 1:
            errors.append(
                f"{workflow}:{line_number}: TEST_QUARANTINE for {argument} must be immediately preceding"
            )
        if expiry < today:
            errors.append(
                f"{workflow}:{marker_line}: TEST_QUARANTINE for {argument} expired on {expiry.isoformat()}"
            )

    for argument, (line_number, _expiry) in sorted(markers.items()):
        if argument not in exclusions:
            errors.append(
                f"{workflow}:{line_number}: TEST_QUARANTINE for {argument} has no matching pytest exclusion"
            )

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "workflow",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[2] / ".github/workflows/ci-cd.yml",
    )
    args = parser.parse_args()
    errors = check(args.workflow)
    if errors:
        print("Test quarantine policy failed:", file=sys.stderr)
        print("\n".join(f"- {error}" for error in errors), file=sys.stderr)
        return 1
    print(f"Test quarantine policy passed: {args.workflow}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
