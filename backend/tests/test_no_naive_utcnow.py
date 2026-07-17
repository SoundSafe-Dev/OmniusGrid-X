"""Guard (FS-97): no naive ``datetime.utcnow()`` calls in backend app code.

``datetime.utcnow()`` returns a NAIVE datetime. Postgres ``TIMESTAMPTZ`` values
come back timezone-AWARE, so any arithmetic or comparison between the two raises
``TypeError: can't subtract offset-naive and offset-aware datetimes`` — a bug
class that stays invisible on SQLite (all-naive) and only detonates on a real
database (it 500'd yard/detention-alerts and maintenance/statistics). The
FS-96/97 sweep replaced every call with ``datetime.now(timezone.utc)``; this
test keeps the codebase swept.

Deliberately NOT banned: bare ``default=datetime.utcnow`` column-default
references (no call parentheses) — changing ORM write defaults is a separate,
riskier migration of stored-value semantics and is tracked independently.
"""

from __future__ import annotations

import re
from pathlib import Path

APP_ROOT = Path(__file__).resolve().parents[1] / "app"

_NAIVE_CALL = re.compile(r"datetime\.utcnow\s*\(")


def test_no_naive_utcnow_calls_in_app():
    offenders = []
    for path in sorted(APP_ROOT.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if _NAIVE_CALL.search(line):
                offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{lineno}")
    assert not offenders, (
        "naive datetime.utcnow() calls found — use datetime.now(timezone.utc) "
        "(aware); naive-vs-timestamptz arithmetic 500s on real Postgres:\n  "
        + "\n  ".join(offenders)
    )
