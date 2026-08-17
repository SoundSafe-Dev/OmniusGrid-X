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
import os
import socket
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
#: MEASURED AGAIN 2026-08-08, and the floor STAYS AT 380 for a reason worth writing down.
#:
#:     with Postgres + Redis + a reachable broker    402 / 471
#:     with Postgres + Redis, broker absent          387 / 471   (2026-08-07)
#:
#: 402 is the highest this gate has ever scored, and it is the first run where all three
#: dependencies were actually present — the broker step (FS-259b) is `continue-on-error` and
#: REMOVES ITS OWN CONTAINER if the advertised address does not verify, because a half-working
#: broker hangs the app and collects 1 operation instead of 452. That fail-safe is right, and
#: it is also why this number cannot become the floor.
#:
#: THE FLOOR MUST SURVIVE THE WORST LEGITIMATE CONFIGURATION, and the worst legitimate
#: configuration is a degraded broker step: 387, minus the measured spread of 9, is 378. The
#: floor is already 380. **Raising it to anything near 402 would fail every build in which the
#: broker did not come up** — which is precisely how this job's predecessor became advisory
#: and got killed at six hours.
#:
#: RESOLVED 2026-08-11 (FS-654) — with TWO floors, and the run decides which one applies by
#: MEASURING rather than by being told.
#:
#: The impasse was that one number had to serve two configurations, so it had to serve the
#: worse one, and a healthy run spent 22 operations of headroom to protect a degraded run that
#: might never happen. Two floors end that:
#:
#:     BASELINE_WITH_BROKER    393   = 402 measured, less the 9-operation spread
#:     BASELINE_WITHOUT_BROKER 380   unchanged; the floor this gate has held since 2026-08-07
#:
#: WHY THE RATCHET PROBES THE BROKER ITSELF rather than accepting a `--broker` flag from the
#: workflow. A flag is a claim, and the lower floor is the one somebody would want on a red
#: build — "the broker must have been down" is unfalsifiable after the fact and costs 13
#: operations of protection. So this script opens a TCP connection to the same address the app
#: was given and reports what it finds. Lying to it requires taking the broker down, which is
#: the condition the lower floor describes.
#:
#: The probe runs AFTER the suite, which is the right order and worth stating: the question is
#: not "was a broker configured" but "was one reachable while the operations were collected".
#: A broker that died mid-run scores like a broker that was never there, and the floor should
#: follow the score. The remaining gap — a broker that comes back between the last request and
#: the probe — leaves the run held to the HIGHER floor, which fails safe.
#:
#: `--broker none` states there is no broker to probe, for a laptop run. It selects the lower
#: floor and says so; it cannot select the higher one.
#:
#: What the 402 run found, which is the point of running it: `ServerError` is down to 14, and
#: not one of the 14 is a defect in this lane. Six are the pg_stat_statements limitation
#: recorded below, four are RAG (vector store unreachable in this harness), two are CORRECT
#: 503s charged to the API because schemathesis counts any 5xx, one is an unhandled
#: PermissionError on a missing OTA artifact directory, and **one is a response model that has
#: never been able to serialise its own handler's output** — see FS-608.
#:
#: Raise it when a fix clears the noise. Never lower it.
#:
#: RAISED 380 -> 436 on 2026-08-14. A full run measured **445 of 546 conforming** with no
#: broker, so the floor moves to 445 less the same 9-operation spread the other floor allows
#: for generation variance. The gain is mostly arithmetic rather than earned — the
#: correlation-engine merge added ~90 operations and most of them conform — which is exactly
#: why the floor has to move WITH the surface: 380 against 546 would let 65 operations
#: regress unnoticed.
#:
#: THAT RUN ONLY HAPPENED BECAUSE THE SUITE STOPPED HANGING. `case.call_and_validate()` had
#: no request timeout, so one unresponsive operation stopped the whole job — no junit XML, no
#: count, and this script then reading "collected 1 operations" and blaming the schema. An
#: earlier attempt sat for over an hour having used one minute of CPU in the last ten. With a
#: 30-second per-request timeout the same surface finishes in 14:41.
#:
#: What this run found: 72 server errors, 18 undocumented status codes and 2 schema
#: violations across 101 non-conforming operations — and **not one of them on the newly
#: merged `/api/v1/correlation/evidence` or `/correlation/operations` routes**. The
#: correlation names in the failure list belong to `registries/correlations` and
#: `nlp/correlation/query`, both of which predate the merge.
#: RAISED 436 -> 438 the same day, and this movement was EARNED rather than arithmetic:
#: FS-724/725 fixed two of the eight operations that answered a bare `internal server error`
#: (a shop-floor write whose asset id reached Postgres, and a timezone validator that caught
#: one of three exception types), and a re-run measured **447**, up from 445. Two fixes, two
#: operations, confirmed by measurement rather than assumed from the diff.
#:
#: Still below `BASELINE_WITH_BROKER` (440), as the doc guard requires.
#:
#: RAISED 438 -> 447 on 2026-08-17 (FS-738), and the gain was a SIDE EFFECT rather than a
#: target. FS-736/737 closed the foreign-key tenancy class: a request naming another
#: tenant's row used to reach Postgres and surface as a 500, and now answers a declared
#: 404. Two runs, same throwaway database, no broker:
#:
#:     run 1   456 conforming   33 operations returning 5xx
#:     run 2   458 conforming   31 operations returning 5xx
#:
#: Both beat the previous measurement of 447 by more than the 2-operation spread between
#: them, which is this file's standard for moving a floor. The spread is ALSO evidence in
#: itself: `AcceptedNegativeData` (33), `UnsupportedMethodResponse` (22),
#: `RejectedPositiveData` (2) and `UndefinedStatusCode` (1) are identical across both runs,
#: so all the movement is in `ServerError` — the known flapping set, not noise everywhere.
#:
#: A BROKER WAS THEN MADE REACHABLE AND MEASURED TWICE MORE, because raising this floor
#: alone pushed it above `BASELINE_WITH_BROKER` and the doc guard refused — correctly, and
#: for the reason recorded below it. This file has met that before and its answer stands:
#: take the run rather than raise by arithmetic. All four:
#:
#:     no broker   456, 458    (5xx: 33, 31)
#:     broker      454, 457    (5xx: 35, 32)
#:
#: THE TWO CONFIGURATIONS NO LONGER SEPARATE. The ranges overlap, the broker side is
#: marginally WORSE rather than better, and every non-`ServerError` check is identical
#: across all four runs — `AcceptedNegativeData` 33, `UnsupportedMethodResponse` 22,
#: `RejectedPositiveData` 2, `UndefinedStatusCode` 1. The note further down predicted this
#: in as many words: very little of the API now blocks on the broker.
#:
#: So both floors are set from the POOLED minimum of 454, less the same 9-operation spread
#: this file has always allowed: 445. That raises the broker-less floor 438 -> 445 and the
#: broker floor 440 -> 445, and it stops asserting a difference the measurement does not
#: show. Not pinned at 454: a gate that fails on its own documented spread is a gate
#: somebody disables.
BASELINE_WITHOUT_BROKER = 445

#: The floor for a run where a broker was reachable. 402 measured 2026-08-08, less the same
#: 9-operation spread the lower floor allows for. Never lower it either — and note that this
#: one catches a regression of 10 where the shared floor caught 22.
#:
#: RAISED 393 -> 440 on 2026-08-14, from a run with a broker genuinely reachable:
#: **449 of 546**, less the same 9-operation spread.
#:
#: It was briefly left at 393 while the lower floor moved to 436, which
#: `test_the_contract_gate_doc_matches_the_gate.py` refused — correctly: a run that reaches
#: MORE operations because a dependency was present cannot be held to a lower bar than one
#: that could not reach them. Rather than raise it by arithmetic, the run was taken.
#:
#: AND THE MEASUREMENT CORRECTED THE REASONING. The note here previously said a reachable
#: broker turns "~20 correct 503s" into 2xx, inherited from the era when this gate's own
#: documentation put the broker-dependent set at that size. Measured today it is worth
#: **four** operations: 449 with a broker against 445 without. The gap between the two floors
#: is therefore small, and that is a fact about the API — very little of it now blocks on the
#: broker — rather than a mistake in either number.
BASELINE_WITH_BROKER = 445

#: Kept as the name the CLI default and older callers use: the floor that holds when nothing
#: is known about the broker.
BASELINE_PASSING = BASELINE_WITHOUT_BROKER

#: Total operations the schema documents, checked so a collapse in collection cannot
#: pass the ratchet by making "passing" small and "total" equally small.
#: 452 measured 2026-07-31 across four runs; was recorded as 451.
#:
#: **546 measured 2026-08-14**, read straight from `app.openapi()`. The correlation-engine
#: merge added ~90 operations, and this file's own drift check then made the gate fail
#: OUTRIGHT: |546 - 452| = 94 against a 45-operation tolerance, printing "check that the
#: schema still loads and the server started" — which is the opposite of what happened.
#: Nothing collapsed; the API grew by a fifth and the denominator was left behind.
#:
#: THE DENOMINATOR IS RE-BASELINED, THE FLOORS ARE NOT. `BASELINE_WITHOUT_BROKER` and
#: `BASELINE_WITH_BROKER` are counts of PASSING operations and only ever rise, so they stay
#: exactly as measured — a floor of 380 against 546 is looser than it was against 452, and
#: the honest fix for that is the next full gate run raising it, not a number written here
#: from a guess. Re-measure both on the next run that completes.
EXPECTED_TOTAL = 546

#: How far total may drift before the run is treated as untrustworthy. Routes get
#: added legitimately; a 10% swing means something structural changed.
TOTAL_TOLERANCE = 0.10


def broker_is_reachable(address: str, timeout: float = 3.0) -> bool:
    """Open a TCP connection to the bootstrap address the app was given.

    Deliberately a connect and nothing more. A Kafka handshake would be a better proof of a
    *working* broker, and it would also introduce a client library and a second way for this
    check to hang — the failure mode that made the CI step fail-safe in the first place. What
    is being distinguished here is "something is listening" from "nothing is", which is the
    difference between the two floors.
    """
    host, _, port = address.rpartition(":")
    if not host or not port.isdigit():
        return False
    try:
        with socket.create_connection((host, int(port)), timeout=timeout):
            return True
    except OSError:
        return False


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
    parser.add_argument(
        "--baseline",
        type=int,
        default=None,
        help="override the floor entirely; skips the broker probe",
    )
    parser.add_argument(
        "--broker",
        default=None,
        help=(
            "bootstrap address to probe, or 'none' to declare there is no broker. "
            "Defaults to $REDPANDA_URL. A run with no broker is held to the lower floor."
        ),
    )
    args = parser.parse_args()

    if not args.report.exists():
        print(f"FAIL: {args.report} does not exist — the suite did not run to completion.")
        return 1

    passing, total = read_counts(args.report)

    if args.baseline is not None:
        baseline, why = args.baseline, "explicitly overridden"
    else:
        address = args.broker or os.environ.get("REDPANDA_URL", "")
        if address and address != "none" and broker_is_reachable(address):
            baseline = BASELINE_WITH_BROKER
            why = f"a broker answered at {address}"
        else:
            baseline = BASELINE_WITHOUT_BROKER
            why = (
                f"no broker answered at {address}" if address and address != "none"
                else "no broker address to probe"
            )

    # A suite that collected almost nothing would otherwise sail past the ratchet.
    if abs(total - EXPECTED_TOTAL) > EXPECTED_TOTAL * TOTAL_TOLERANCE:
        print(
            f"FAIL: collected {total} operations, expected about {EXPECTED_TOTAL}.\n"
            "The ratchet compares a count, so a collapse in collection would look like\n"
            "a pass. Check that the schema still loads and the server started."
        )
        return 1

    print(
        f"contract conformance: {passing}/{total} operations "
        f"(ratchet: {baseline} — {why})"
    )

    if passing < baseline:
        print(
            f"\nFAIL: conformance dropped by {baseline - passing}.\n"
            f"  floor {baseline} ({why}), now {passing}\n\n"
            "An operation that used to conform to the OpenAPI schema no longer does, or a\n"
            "new one landed that never did. The generated TypeScript SDK is built from that\n"
            "schema, so a drop here is a client that will be wrong at runtime.\n\n"
            "Fix the endpoint, or document the response it actually returns. Do NOT lower\n"
            "BASELINE_WITH_BROKER or BASELINE_WITHOUT_BROKER in scripts/contract_ratchet.py\n"
            "to make this pass. If the broker was the problem, fix the broker — this run was\n"
            "already held to the floor that matches what it found."
        )
        return 1

    if passing > baseline:
        print(
            f"\n{passing - baseline} more operation(s) conform than the ratchet expects.\n"
            f"Raise the floor for this configuration ({why}) to {passing} in\n"
            "scripts/contract_ratchet.py to lock the gain in."
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
