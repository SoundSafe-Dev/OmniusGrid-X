"""Guard (FS-97): no naive ``datetime.utcnow()`` calls in backend app code.

``datetime.utcnow()`` returns a NAIVE datetime. Postgres ``TIMESTAMPTZ`` values
come back timezone-AWARE, so any arithmetic or comparison between the two raises
``TypeError: can't subtract offset-naive and offset-aware datetimes`` — a bug
class that stays invisible on SQLite (all-naive) and only detonates on a real
database (it 500'd yard/detention-alerts and maintenance/statistics). The
FS-96/97 sweep replaced every call with ``datetime.now(timezone.utc)``; this
test keeps the codebase swept.

Also banned (FS-156): bare ``default=datetime.utcnow`` / ``onupdate=`` column
defaults. SQLAlchemy calls that reference at flush time, so it wrote the same
NAIVE value into ``TIMESTAMPTZ`` columns — correct only when the DB session
happens to run in UTC, and Python-3.12-deprecated besides. The ~151 model
defaults were swapped to the aware ``app.core.datetime_utils.utcnow``. The
metadata test below is the real guard: it *calls* every column default and
fails on any that returns a naive datetime, however it was spelled.
"""

from __future__ import annotations

import re
from datetime import datetime
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


def test_no_naive_utcnow_default_references_in_models():
    """Source-level: the bare reference form must not come back either."""
    db_root = APP_ROOT / "db"
    ref = re.compile(r"(default|onupdate)\s*=\s*datetime\.utcnow\b")
    offenders = []
    for path in sorted(db_root.rglob("*.py")):
        if "__pycache__" in path.parts:
            continue
        for lineno, line in enumerate(path.read_text().splitlines(), 1):
            if ref.search(line):
                offenders.append(f"{path.relative_to(APP_ROOT.parent)}:{lineno}")
    assert not offenders, (
        "naive datetime.utcnow column defaults found — use the aware "
        "app.core.datetime_utils.utcnow:\n  " + "\n  ".join(offenders)
    )


def test_all_column_datetime_defaults_are_aware():
    """Runtime: call every ORM column default/onupdate; none may be naive.

    Dialect-independent and spelling-independent — this is what actually
    protects the write path. Importing app.db.models registers every table on
    the shared Base metadata (the other model modules import from it).
    """
    import app.db.models  # noqa: F401 — registers all tables on Base.metadata
    import app.db.logistics_models  # noqa: F401
    import app.db.notification_models  # noqa: F401
    import app.db.edge_fleet_models  # noqa: F401
    from app.db.models import Base

    naive = []
    for table in Base.metadata.tables.values():
        for col in table.columns:
            for kind, spec in (("default", col.default), ("onupdate", col.onupdate)):
                if spec is None or not getattr(spec, "is_callable", False):
                    continue
                try:
                    value = spec.arg.__wrapped__() if hasattr(spec.arg, "__wrapped__") else spec.arg({})
                except TypeError:
                    value = spec.arg()
                if isinstance(value, datetime) and value.tzinfo is None:
                    naive.append(f"{table.name}.{col.name} ({kind})")
    assert not naive, (
        "column datetime defaults returning NAIVE values (write naive into "
        "TIMESTAMPTZ — wrong unless the DB session is UTC):\n  " + "\n  ".join(naive)
    )
