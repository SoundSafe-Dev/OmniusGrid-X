#!/usr/bin/env python3
"""Ratchet the API contract suite: conformance may improve, never regress.

WHY A RATCHET AND NOT A PASS/FAIL GATE.

The contract suite drives all 451 documented operations with generated input. 299 of
them conform; 152 do not, and the bulk of those are one behaviour — generated input
reaching Postgres unvalidated and surfacing as a 500 (64 DataError, 32 IntegrityError)
where the contract promises a 4xx. Fixing that is per-endpoint work spread across
every lane, so demanding a fully green suite today would mean either leaving the job
advisory (which is how it stayed unable to finish for weeks, killed at six hours with
`continue-on-error` hiding it) or blocking every build until unrelated work lands.

A ratchet gives the third option, and it is the same instrument `--cov-fail-under=54`
already uses in this repo: pin the measured number, fail the build if it drops. From
today a new route that does not conform, or a change that breaks one that did, fails
CI — while the existing 152 are burned down deliberately. The number only moves up.

RAISE IT when you fix operations. Do NOT lower it to make a build pass: a lowered
ratchet is indistinguishable from no ratchet, and the whole point is that the number
cannot drift down quietly.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: Measured 2026-07-30 against a migrated TimescaleDB, after the problem+json content
#: type (304 operations) and the 405/401 header fixes landed. Runtime ~8 minutes.
#:
#: THE MARGIN IS DELIBERATE AND MEASURED. Four consecutive runs scored 294, 296, 297
#: and 300 conforming operations with no code change — including two with
#: `derandomize=True` and one against a freshly migrated database, so the spread is
#: not hypothesis's seed and not accumulated DB state. A handful of operations are
#: genuinely timing-dependent (health endpoints that report a dependency's state,
#: mostly). Pinning the ratchet at the best observed score would fail roughly half of
#: all builds for no reason, and a gate that cries wolf is a gate somebody disables —
#: which is exactly how its predecessor ended up advisory and killed at six hours.
#:
#: So the floor sits below the observed minimum of 294. It still catches a real
#: regression: losing 5+ operations means something structural broke. Tightening it
#: requires making those endpoints deterministic FIRST, not simply raising the number
#: and hoping.
BASELINE_PASSING = 290

#: Total operations the schema documents, checked so a collapse in collection cannot
#: pass the ratchet by making "passing" small and "total" equally small.
EXPECTED_TOTAL = 451

#: How far total may drift before the run is treated as untrustworthy. Routes get
#: added legitimately; a 10% swing means something structural changed.
TOTAL_TOLERANCE = 0.10


def read_counts(report: Path) -> tuple[int, int]:
    root = ET.parse(report).getroot()
    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        raise SystemExit(f"{report}: no <testsuite> element; the run produced no report")
    total = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0))
    errors = int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))
    return total - failures - errors - skipped, total


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("report", type=Path, help="junit-xml written by pytest")
    parser.add_argument("--baseline", type=int, default=BASELINE_PASSING)
    args = parser.parse_args()

    if not args.report.exists():
        print(f"FAIL: {args.report} does not exist — the suite did not run to completion.")
        return 1

    passing, total = read_counts(args.report)

    # A suite that collected almost nothing would otherwise sail past the ratchet.
    if abs(total - EXPECTED_TOTAL) > EXPECTED_TOTAL * TOTAL_TOLERANCE:
        print(
            f"FAIL: collected {total} operations, expected about {EXPECTED_TOTAL}.\n"
            "The ratchet compares a count, so a collapse in collection would look like\n"
            "a pass. Check that the schema still loads and the server started."
        )
        return 1

    print(f"contract conformance: {passing}/{total} operations (ratchet: {args.baseline})")

    if passing < args.baseline:
        print(
            f"\nFAIL: conformance dropped by {args.baseline - passing}.\n"
            f"  was {args.baseline}, now {passing}\n\n"
            "An operation that used to conform to the OpenAPI schema no longer does, or a\n"
            "new one landed that never did. The generated TypeScript SDK is built from that\n"
            "schema, so a drop here is a client that will be wrong at runtime.\n\n"
            "Fix the endpoint, or document the response it actually returns. Do NOT lower\n"
            "BASELINE_PASSING in scripts/contract_ratchet.py to make this pass."
        )
        return 1

    if passing > args.baseline:
        print(
            f"\n{passing - args.baseline} more operation(s) conform than the ratchet expects.\n"
            f"Raise BASELINE_PASSING to {passing} in scripts/contract_ratchet.py to lock the gain in."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
