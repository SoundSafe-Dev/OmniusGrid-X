"""Guard (FS-96, edge half): no naive ``datetime.utcnow()`` calls in the agent.

The naive-vs-aware TypeError class is nastier on the edge than in the backend:
both instances found here were swallowed by defensive except-blocks and became
SILENT data loss (backfill lag reported as 0; collector readings dropped before
forward). Aware ``datetime.now(timezone.utc)`` everywhere, with naive-input
coercion at ISO-parse boundaries.
"""

import re
from pathlib import Path

AGENT_ROOT = Path(__file__).resolve().parents[1] / "opsgrid_agent"

_NAIVE_CALL = re.compile(r"datetime\.utcnow\s*\(")


def test_no_naive_utcnow_calls_in_agent():
    offenders = []
    for path in sorted(AGENT_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if _NAIVE_CALL.search(line):
                offenders.append(f"{path.relative_to(AGENT_ROOT.parent)}:{lineno}")
    assert not offenders, (
        "naive datetime.utcnow() calls found — use datetime.now(timezone.utc):\n  "
        + "\n  ".join(offenders)
    )
