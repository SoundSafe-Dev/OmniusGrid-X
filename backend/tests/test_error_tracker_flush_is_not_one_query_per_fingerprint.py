"""error_tracker's flush issues two statements per batch, not two per fingerprint (FS-882).

THE DEFECT. `_flush_once` ran one `_UPSERT_EVENT` per fingerprint, and inside that loop
one `_UPSERT_BUCKET` per hour bucket that fingerprint touched — so a flush cost
`fingerprints + sum(hour buckets)` round trips. Both grow with error DIVERSITY, which is
exactly what widens during an incident: a single root cause fanning out across routes and
status codes produces more fingerprints, not more occurrences of one. The mechanism meant
to survive an incident got slower at the moment an incident made it matter.

THE FIX. Both statements are still per-batch, not per-row: the pending dict is flattened
into two parameter lists (one row per fingerprint for the event upsert, one row per
fingerprint-hour for the bucket upsert) and each list is handed to `session.execute` in
one call — SQLAlchemy's executemany path, which lets the driver pipeline every row of a
statement inside a single await rather than issuing one await per row.
"""
from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _flush_source() -> ast.AST:
    """`_flush_once`, isolated by AST rather than line number. Matched by exact name —
    rule 296: a substring match on a name is a bet that nothing else in the file could
    also match it, and that bet is never worth taking."""
    tree = ast.parse((APP / "services/error_tracker.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "_flush_once":
            return node
    raise AssertionError("_flush_once moved or was renamed; this guard is blind")


class TestTheUpsertsAreOutsideThePerFingerprintLoop:
    def test_no_execute_inside_a_loop_over_the_batch(self):
        """THE DEFECT ITSELF. A `session.execute` whose nearest enclosing loop iterates
        `batch.items()` (or a bucket dict nested inside that iteration) is a query per
        fingerprint or per hour bucket."""
        handler = _flush_source()
        offenders = []
        for node in ast.walk(handler):
            if not isinstance(node, ast.For):
                continue
            iterable = ast.unparse(node.iter)
            if "batch" not in iterable and "bucket_counts" not in iterable:
                continue
            body = ast.unparse(node)
            if "session.execute" in body:
                offenders.append(iterable)
        assert not offenders, (
            f"a query runs inside a loop over the batch ({offenders}), so the flush costs "
            f"one round trip per fingerprint or per hour bucket — exactly the shape that "
            f"grows fastest during an incident."
        )

    def test_exactly_two_executes_per_flush(self):
        """The replacement: one executemany call for events, one for buckets — regardless
        of how many fingerprints or hours are in the batch."""
        body = ast.unparse(_flush_source())
        assert body.count("session.execute(") == 2, (
            f"expected exactly 2 session.execute calls (one batched upsert for events, "
            f"one for buckets); found {body.count('session.execute(')}. A flush that "
            f"issues more than two is back to querying per row."
        )

    def test_both_upserts_are_passed_a_list_not_a_single_dict(self):
        """`session.execute(stmt, [{...}, {...}])` is executemany; `session.execute(stmt,
        {...})` is one row. The batching only works if the parameter is a list built once
        from the whole batch."""
        body = ast.unparse(_flush_source())
        assert "event_params" in body and "bucket_params" in body, (
            "the flush no longer builds a parameter list per statement — either the "
            "per-fingerprint loop is back, or the batching was removed some other way"
        )
