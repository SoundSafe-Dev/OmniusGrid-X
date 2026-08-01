#!/usr/bin/env python3
"""Make the contract gate's score readable between runs (FS-264).

`contract_ratchet.py` answers one question — did conformance drop below the floor — and
answers it well. But it prints a single number into a log nobody opens unless the build is
red, and the floor sits 8-9 points below the observed minimum. **A regression of five
operations is therefore completely invisible** until a sixth arrives and the build fails,
by which point the change that caused it is several commits back.

WHY A PER-CHECK BREAKDOWN AND NOT JUST THE TOTAL. This is the lesson of 2026-07-31, and it
is the reason this script exists at all. Six defects were fixed and verified individually
that day, and conformance went 369/370 -> 368/370 — no movement. The total said the work
was worthless. The categories said otherwise:

    ServerError            41/40 -> 40/38     (the fixes landing)
    AcceptedNegativeData   25    -> 27        (two of them moving SIDEWAYS)

An endpoint that 500s never reaches the negative-data check; once it works, schemathesis
mutates the body and gets a 2xx instead. So a fix can move an operation from one failing
bucket to another rather than to passing, and **a trend of the total alone reports that as
nothing happening.** Anyone watching only the headline would have concluded that restoring a
feature which had never worked since the day it was written achieved nothing.

Emits GitHub-flavoured markdown to `$GITHUB_STEP_SUMMARY` when it exists (so every run
shows its own numbers in the Actions UI), and to stdout otherwise.

Usage:  python scripts/contract_summary.py contract-report.xml
        python scripts/contract_summary.py contract-report.xml --previous old-report.xml
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import xml.etree.ElementTree as ET
from collections import Counter
from pathlib import Path

# The checks schemathesis reports, in the order a reader should care about them:
# real defects first, policy disagreements last. Anything unrecognised is surfaced
# rather than dropped — an unknown check is exactly the thing worth noticing.
CHECKS = (
    "ServerError",
    "UndefinedStatusCode",
    "UndefinedContentType",
    "RejectedPositiveData",
    "AcceptedNegativeData",
    "UnsupportedMethodResponse",
)

#: Which checks are defects rather than the documented strictness-policy disagreements.
#: See docs/engineering/api-contract-gate.md — the last two encode a policy this API has
#: deliberately not adopted, so counting them as debt overstates the work remaining.
POLICY_CHECKS = {"AcceptedNegativeData", "UnsupportedMethodResponse"}


def read(report: Path) -> tuple[int, int, Counter, list[str]]:
    root = ET.parse(report).getroot()
    suite = root.find("testsuite") if root.tag == "testsuites" else root
    if suite is None:
        raise SystemExit(f"{report}: no <testsuite> element")
    total = int(suite.get("tests", 0))
    failures = int(suite.get("failures", 0)) + int(suite.get("errors", 0))
    skipped = int(suite.get("skipped", 0))

    counts: Counter = Counter()
    server_errors: list[str] = []
    for case in suite.iter("testcase"):
        failure = case.find("failure")
        if failure is None:
            continue
        text = (failure.get("message") or "") + (failure.text or "")
        matched = [c for c in CHECKS if c in text]
        for check in matched:
            counts[check] += 1
        if not matched:
            counts["(unrecognised)"] += 1
        if "ServerError" in matched:
            name = re.search(r"\[(.+)\]$", case.get("name", ""))
            server_errors.append(name.group(1) if name else case.get("name", ""))
    return total - failures - skipped, total, counts, sorted(server_errors)


def _undeclared_line() -> str:
    """How many routes declare no `response_model`, and how close that is to its ratchet.

    Deliberately reported NEXT TO conformance rather than in its own job: schemathesis can
    only check what a route declares, so a conformance score is a statement about the
    declared surface only. Read alone, it rises when routes are declared AND when routes
    are deleted, and those are not the same news.
    """
    try:
        sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
        from tests._route_tree import http_routes  # noqa: F401  (import check)
        from tests.test_response_model_coverage_ratchet import (
            MAX_UNDECLARED,
            _undeclared,
        )

        undeclared = len(_undeclared())
    except Exception as exc:  # pragma: no cover - the app may not import here
        return f"_Undeclared-route count unavailable ({type(exc).__name__})._"

    slack = MAX_UNDECLARED - undeclared
    note = (
        f" — {slack} below its ratchet, so that many could regress unnoticed"
        if slack > 0
        else " — at its ratchet"
    )
    return f"**{undeclared}** routes declare no `response_model` (max {MAX_UNDECLARED}){note}."


def _delta(now: int, before: int | None) -> str:
    if before is None:
        return ""
    diff = now - before
    if diff == 0:
        return " (=)"
    return f" ({diff:+d})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("report", type=Path)
    ap.add_argument("--previous", type=Path, help="a prior report, to show movement")
    ap.add_argument("--baseline", type=int, default=None,
                    help="the ratchet floor; read from contract_ratchet.py if omitted")
    args = ap.parse_args()

    if not args.report.exists():
        print(f"no report at {args.report} — the suite did not run to completion.")
        return 0  # never fail the build; contract_ratchet.py is the gate

    passing, total, counts, server_errors = read(args.report)

    baseline = args.baseline
    if baseline is None:
        try:
            sys.path.insert(0, str(Path(__file__).resolve().parent))
            from contract_ratchet import BASELINE_PASSING

            baseline = BASELINE_PASSING
        except Exception:
            baseline = 0

    prev_counts: Counter | None = None
    prev_passing: int | None = None
    if args.previous and args.previous.exists():
        prev_passing, _, prev_counts, _ = read(args.previous)

    headroom = passing - baseline
    lines = [
        "## API contract conformance",
        "",
        f"**{passing} / {total}** operations conform"
        f"{_delta(passing, prev_passing)} · floor **{baseline}** · "
        f"headroom **{headroom}**",
        "",
    ]
    # The headroom is the point. The ratchet only fires when it goes negative, so a
    # shrinking headroom is the early warning the floor cannot give.
    if headroom < 0:
        # The ratchet fails this run anyway; say what happened rather than reporting a
        # negative count of headroom, which reads as nonsense in the one case a reader
        # is most likely to be looking at the summary.
        lines.append(
            f"> ❌ **{-headroom} operation(s) below the floor** — the ratchet fails this "
            "run. If the operation count also collapsed, the suite did not complete and "
            "the conformance figure is meaningless; check that before chasing endpoints."
        )
        lines.append("")
    elif headroom <= 3:
        lines.append(
            f"> ⚠️ Only {headroom} operation(s) above the floor. The next regression "
            "fails the build — look now rather than after it does."
        )
        lines.append("")

    lines += ["| check | count | | ", "|---|---:|---|"]
    for check in list(CHECKS) + ["(unrecognised)"]:
        n = counts.get(check, 0)
        if not n and check == "(unrecognised)":
            continue
        kind = "policy, not a defect" if check in POLICY_CHECKS else "defect"
        lines.append(f"| `{check}` | {n}{_delta(n, (prev_counts or {}).get(check))} | {kind} |")

    lines += [
        "",
        "`ServerError` is the number to watch: it is the only bucket that is entirely "
        "defects. A fix can move an operation from it into `AcceptedNegativeData` rather "
        "than to passing — an endpoint that 500s never reaches the negative-data check — "
        "so **the total can stay flat while real work lands.**",
    ]

    # The other half of what this gate is for. Conformance can only be checked on what is
    # DECLARED, so an undeclared route is one schemathesis validates nothing about — the
    # two numbers have to be read together or a rising conformance score can simply mean
    # a shrinking surface. Best-effort: the app may not import in every context.
    declared_line = _undeclared_line()
    if declared_line:
        lines += ["", declared_line]

    if server_errors:
        lines += ["", "<details><summary>Operations returning 5xx</summary>", ""]
        lines += [f"- `{op}`" for op in server_errors]
        lines += ["", "</details>"]

    out = "\n".join(lines)
    summary = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary:
        with open(summary, "a", encoding="utf-8") as fh:
            fh.write(out + "\n")
    print(out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
