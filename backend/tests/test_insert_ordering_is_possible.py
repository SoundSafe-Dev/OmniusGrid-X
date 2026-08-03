"""The ORM must be able to order a parent insert before its child (FS-408).

WHAT BROKE. `scripts/seed_demo_data.py` — the path `docs/DEMO.md` tells operators to run —
died on a foreign key against a fresh database, inserting `erp_data_mappings` while
`integration_configurations` had no matching row.

TWO CAUSES, and the second is the one worth guarding.

1. SQLAlchemy's unit of work builds its insert ordering from `relationship()`, not from raw
   ForeignKey columns, and 62 of the 69 FK-carrying models here declare only the column. So
   for most of this schema it genuinely cannot order a parent before a child in one flush.
   The seed's answer is `session_replication_role = replica` for the load, which is fine —
   but it set it and then COMMITTED on the next line, which returns the connection to the
   pool and resets it. Measured `replica` after the SET and `origin` after the commit: the
   protection was gone before a single row was written.

2. `dock_doors <-> yard_trailers` and `yard_trailers <-> shipments` are mutually dependent
   FKs. SQLAlchemy cannot topologically sort a cycle; it warns, DISCARDS those constraints
   from the ordering, and says the warning "may raise an error in a future release".
   Discarding them also drags the cycle members' *other* edges out of the sort — which is why
   `dock_doors` sorted ahead of `organizations`, a table it references.

WHY NO TEST CAUGHT ANY OF IT. **SQLite does not enforce foreign keys by default.** Every
in-memory test in this suite inserts in whatever order it likes and passes. The class is
structurally invisible below a real Postgres, which is exactly why it needs a static guard
rather than a behavioural one.
"""

from __future__ import annotations

import warnings

from sqlalchemy import inspect

from app.db.models import Base
from app.db import insight_models, shop_floor_models  # noqa: F401  (register the tables)


def test_the_table_graph_has_no_unresolvable_cycles():
    """`sorted_tables` must not warn.

    A cycle silently degrades ordering for tables that are not even part of it, and the
    warning is documented to become an error in a future SQLAlchemy. The remedy is
    `use_alter=True` on one side of each mutual pair, which changes nothing about the
    resulting schema — the migration chain is the real schema — and only affects metadata
    ordering and `create_all`, which this suite uses everywhere.
    """
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        list(Base.metadata.sorted_tables)

    cycles = [str(w.message) for w in caught if "cycle" in str(w.message).lower()]
    assert not cycles, (
        "the FK graph has an unresolvable cycle, so table ordering is degraded for every "
        "table involved AND for the tables they reference. Mark one side of each mutual "
        "pair use_alter=True:\n  " + "\n  ".join(cycles)
    )


def test_a_parent_table_sorts_before_a_table_that_references_it():
    """Directly checks the property the cycle was breaking.

    Written as a sweep rather than against one pair, because the failure was not local: the
    cycle was between yard tables and the visible symptom was `organizations` sorting late.
    """
    order = {table.name: i for i, table in enumerate(Base.metadata.sorted_tables)}
    inversions = []
    for table in Base.metadata.sorted_tables:
        for column in table.columns:
            for fk in column.foreign_keys:
                parent = fk.column.table.name
                if parent == table.name:
                    continue  # self-reference, always a cycle and always fine
                # A constraint marked use_alter is deliberately outside the ordering.
                if fk.constraint is not None and fk.constraint.use_alter:
                    continue
                if order.get(parent, -1) > order[table.name]:
                    inversions.append(f"{table.name}.{column.name} -> {parent}")
    assert not inversions, (
        "these tables sort BEFORE a table they reference, so any flush creating both in one "
        "go can emit the child first — which is a foreign key violation on Postgres and "
        "silently fine on SQLite, where FKs are off by default:\n  " + "\n  ".join(inversions)
    )


def test_the_models_without_a_relationship_are_counted_not_forgotten():
    """A ratchet on the real underlying weakness.

    Every model here with an FK column and no `relationship()` is a parent/child pair the
    unit of work cannot order. That is a large number and fixing it is a project, not a
    sprint — but it must not GROW silently, because each new one is another way to write the
    seed bug. Lower this as relationships are added; never raise it.
    """
    without = sorted(
        mapper.class_.__name__
        for mapper in Base.registry.mappers
        if any(c.foreign_keys for c in mapper.class_.__table__.columns)
        and not list(inspect(mapper.class_).relationships)
    )
    #: Measured 2026-08-03.
    assert len(without) <= 62, (
        f"{len(without)} models carry an FK column with no relationship() for the unit of "
        f"work to order by, up from 62. Each one is a parent that can be inserted after its "
        f"child in a single flush — a foreign key violation on Postgres that SQLite cannot "
        f"see:\n  {without}"
    )
