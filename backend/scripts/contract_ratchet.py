#!/usr/bin/env python3
"""Ratchet the API contract suite: conformance may improve, never regress.

WHY A RATCHET AND NOT A PASS/FAIL GATE.

The contract suite drives all 451 documented operations with generated input. ~360 of
them conform. The rest are dominated by one behaviour — generated input reaching
Postgres unvalidated and surfacing as a 500 where the contract promises a 4xx — which
is per-endpoint work spread across every lane, so demanding a fully green suite would
mean either leaving the job advisory (which is how it stayed unable to finish for
weeks, killed at six hours with `continue-on-error` hiding it) or blocking every build
until unrelated work lands.

A ratchet gives the third option, and it is the same instrument `--cov-fail-under=54`
already uses in this repo: pin the measured number, fail the build if it drops. From
today a new route that does not conform, or a change that breaks one that did, fails
CI — while the rest are burned down deliberately. The number only moves up.

Note that ~37 of the remainder CANNOT pass without a deliberate policy change (Pydantic
strict mode, typed path converters); see docs/engineering/api-contract-gate.md. The
practical ceiling is around 412, not 451.

RAISE IT when you fix operations. Do NOT lower it to make a build pass: a lowered
ratchet is indistinguishable from no ratchet, and the whole point is that the number
cannot drift down quietly.
"""

from __future__ import annotations

import argparse
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

#: RAISED 2026-07-31 to 350, in three steps, each only after a fix cleared the noise:
#:   * documenting the status codes the error envelope emits (400/405 globally, 503 on
#:     the eleven routers that raise it) -> 327, 331 from a band of 294-303;
#:   * typing 23 path params as UUID instead of str -> 348 and 348;
#:   * declaring the real content type on nine export/metrics routes, plus five more
#:     UUID path params -> 360 and 359.
#:
#: The UUID pair (348, 348) was IDENTICAL, which is itself a result: several of the 14
#: flapping operations were flapping because malformed ids left different rows behind
#: on different runs. Fixing the type removed the variance as well as the 500s. The
#: floor keeps its 9-point margin anyway — a couple of close runs are not yet evidence
#: that the spread is gone.
#:
#: THE MARGIN IS DELIBERATE AND MEASURED. Ten pre-fix runs scored 294, 296, 297, 297,
#: 297, 298, 299, 300, 302 and 303 with no code change — `derandomize=True` did not
#: remove the spread and neither did a freshly migrated database. Fourteen operations
#: flip verdict between runs; they are named in docs/engineering/api-contract-gate.md,
#: and four of them read live Postgres statistics that the suite itself perturbs.
#:
#: Pinning at the best observed score would fail roughly half of all builds, and a gate
#: that cries wolf is a gate somebody disables — exactly how its predecessor ended up
#: advisory and killed at six hours. So the floor sits 9 below the observed minimum of
#: 359: wide enough to absorb the measured spread, tight enough that losing a handful
#: of operations still fails the build.
#:
#: RAISED AGAIN 2026-07-31 to 360 (FS-259), after bounding the input that was reaching
#: the database unvalidated:
#:
#:   pre-fix   363, 367   (spread 4)
#:   post-fix  369, 370   (spread 1)
#:
#: The two ranges are DISJOINT — every post-fix run beat every pre-fix run — and the gain
#: over the pre-fix minimum is 6, larger than the pre-fix spread of 4, which is this
#: file's stated standard for moving the number. All of the movement is in `ServerError`
#: (47/43 -> 41/40); `AcceptedNegativeData`, `UnsupportedMethodResponse`,
#: `RejectedPositiveData` and `UndefinedStatusCode` are IDENTICAL across all four runs.
#: That last fact is what rules out a lucky draw: a gain from noise would have moved the
#: other checks too.
#:
#: What was fixed, and why it was fixed as a class. Schemathesis found ONE of thirteen
#: identical unbounded `skip` declarations — the only one it happened to draw a value
#: above 2**63-1 for. Fixing that endpoint alone would have raised this number by luck,
#: so `MAX_OFFSET` bounds all sixteen offset parameters at the Postgres bigint ceiling
#: (`app/core/pagination.py`), and `tests/test_generated_input_cannot_five_hundred.py`
#: fails if a new one lands unbounded. Also: `upcoming` on `/maintenance/schedules`
#: (added to `now`, so a large value was an `OverflowError` past year 9999), and two
#: non-UUID path ids reaching UUID columns.
#:
#: The 9-point margin is KEPT even though the post-fix spread measured 1. Two runs are
#: not evidence that a spread of 9 has become a spread of 1 — the same caution the
#: previous raise recorded, for the same reason.
#:
#: Raise it when a fix clears the noise, as this one did. Never lower it.
#: RE-BASELINED 2026-08-06 AFTER FS-307, with both configurations measured on the same
#: database, same seed, back to back:
#:
#:     as the owning SUPERUSER (the old gate)   397 / 470
#:     as omniusgrid_contract (NOSUPERUSER)     392 / 470
#:
#: The gate had been running as a superuser, which bypasses FORCE ROW LEVEL SECURITY, so
#: every previous number was measured with tenant isolation switched off. The cost of turning
#: it on is **five operations**, and `ServerError` rises 17 -> 23.
#:
#: The six that fail only under the restricted role are the point of the exercise — they were
#: passing because RLS was off:
#:     GET  /api/v1/audit/logs                                  (fixed, FS-503)
#:     GET  /api/v1/audit/verify                                (fixed, FS-503)
#:     GET  /api/v1/model-monitoring/{data-,}drift/history/{id}
#:     GET  /api/v1/model-monitoring/performance/history/{id}
#:     POST /api/v1/compliance/reports/schedules
#:
#: 380, not 392. This is ONE run at the new configuration, and the spread recorded above is
#: up to 9 operations with no code change; a floor set at the measurement would fail on
#: variance. 380 leaves 12 of headroom and still catches a regression of 13 — where the old
#: 360 would have sat through a loss of 32.
#:
#: Raise it when a fix clears the noise. Never lower it.
BASELINE_PASSING = 380

#: Total operations the schema documents, checked so a collapse in collection cannot
#: pass the ratchet by making "passing" small and "total" equally small.
#: 452 measured 2026-07-31 across four runs; was recorded as 451.
EXPECTED_TOTAL = 452

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
