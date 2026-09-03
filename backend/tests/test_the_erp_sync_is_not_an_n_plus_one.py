"""An ERP sync issues one query per entity type, not one per record (FS-881).

THE DEFECT. `_run_sync` ran `SELECT ERPEntity` per record, nested inside the
per-entity-type loop — so a 10,000-row SAP sync was 10,000 round trips, each holding one of
the ten pooled connections a process has (FS-839) for the whole duration of the sync. The
ids come from the records themselves and are all known before the loop starts, so there was
never a reason to ask one at a time.

WHAT BATCHING INTRODUCES, and why this file exists rather than just a query count: the
per-record SELECT saw the session's pending state on each pass. A batched pre-fetch runs
once, before any insert, so **a record whose id appears twice in the same payload** would
miss its own predecessor and insert a duplicate — a unique-constraint violation that only
shows up on a real database, with a payload nobody controls. The fix registers each created
row in the same map the pre-fetch filled; this pins that.

Keyed on `(entity_type, entity_id)` throughout, because `entity_id` alone is not unique
across types — two ERP objects can legitimately share an id, and matching on it alone would
have one overwrite the other.
"""
from __future__ import annotations

import ast
import pathlib

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _sync_source() -> ast.AST:
    """The sync handler, isolated by AST rather than line number."""
    tree = ast.parse((APP / "api/erp_integrations.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)) and "sync" in node.name:
            body = ast.unparse(node)
            if "ERPEntity" in body and "fetch_data" in body:
                return node
    raise AssertionError("the ERP sync handler moved; this guard is blind")


class TestTheQueryIsOutsideTheRecordLoop:
    def test_no_execute_inside_the_per_record_loop(self):
        """THE DEFECT ITSELF. A `db.execute` whose nearest enclosing loop iterates records
        is a query per record — which is what makes it grow with the payload rather than
        with the number of entity types."""
        handler = _sync_source()
        offenders = []
        for node in ast.walk(handler):
            if not isinstance(node, ast.For):
                continue
            target = ast.unparse(node.target)
            if "record" not in target:
                continue
            body = ast.unparse(node)
            # A nested loop's own executes are its business; this asks about THIS loop.
            if "db.execute" in body:
                offenders.append(target)
        assert not offenders, (
            f"a query runs inside the per-record loop ({offenders}), so the sync issues "
            f"one round trip per record. A 10,000-row payload is 10,000 queries, each "
            f"holding one of ten pooled connections for the length of the sync."
        )

    def test_the_batch_prefetch_uses_in(self):
        """The replacement: one query per entity type, bounded by the batch the connector
        returned rather than by the table."""
        body = ast.unparse(_sync_source())
        assert ".in_(" in body, (
            "the batched pre-fetch is gone, so either the N+1 is back or the ids are no "
            "longer being looked up at all"
        )

    def test_it_still_matches_on_entity_type(self):
        """`entity_id` is not unique across types. Matching on it alone would let two ERP
        objects that legitimately share an id overwrite one another."""
        body = ast.unparse(_sync_source())
        assert "ERPEntity.entity_type == etype" in body, (
            "the lookup no longer constrains entity_type, so records of different types "
            "sharing an id will collide"
        )


class TestADuplicateIdInOnePayloadDoesNotInsertTwice:
    """The failure batching introduces, and the reason a query count alone is not enough.

    The per-record SELECT observed the session's pending state on every pass. A pre-fetch
    runs ONCE, before any insert — so without registering created rows, a payload carrying
    the same id twice inserts it twice and violates the unique constraint. On a real
    database, from a payload nobody controls.
    """

    def test_created_rows_are_registered_for_later_records(self):
        body = ast.unparse(_sync_source())
        assert "existing_by_id[eid] = created" in body, (
            "a row created in this batch is not registered in the pre-fetch map, so a "
            "second record with the same id later in the SAME payload will insert a "
            "duplicate rather than update it"
        )

    def test_the_map_is_consulted_rather_than_the_database(self):
        body = ast.unparse(_sync_source())
        assert "existing_by_id.get(eid)" in body, (
            "the loop no longer reads the pre-fetched map, so it is either querying again "
            "or not checking for an existing row at all"
        )


class TestTheIdsAreComputedOnce:
    def test_extract_entity_id_is_not_called_twice_per_record(self):
        """`extract_entity_id` is called once per record to build the batch, and the loop
        reuses the result. Calling it again inside the loop would risk the two disagreeing
        — it takes the index, so a different enumeration would produce a different id for
        a record with no natural key."""
        body = ast.unparse(_sync_source())
        assert body.count("extract_entity_id(") == 1, (
            f"extract_entity_id is called {body.count('extract_entity_id(')} times. It "
            f"takes the record's INDEX as a fallback id, so two call sites can disagree "
            f"about the same record and the pre-fetch would miss it."
        )
