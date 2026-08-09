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


def test_every_model_can_be_ordered_against_its_parents():
    """ZERO models carry an FK column with no `relationship()` for the unit of work.

    This was a ratchet at 62, lowered one edge at a time as each missing one actually bit
    something, and finally closed in a sweep once foreign keys were enforced everywhere and
    the remaining ones could be added with the suite as proof.

    It is an equality, not a ceiling. A single model without an edge is a parent that can be
    flushed after its child, which real Postgres refuses and SQLite accepts — the defect that
    made `scripts/seed_demo_data.py` fail on every fresh database it had ever met.

    TWO CATEGORIES ARE LEGITIMATELY EXEMPT and are asserted below rather than allowed here:
    self-references, and the two mutually dependent pairs whose DDL is already broken with
    `use_alter`. A mapper relationship on both sides of a mutual pair is a unit-of-work cycle,
    which is a flush-time error rather than a sort warning.
    """
    without = sorted(
        mapper.class_.__name__
        for mapper in Base.registry.mappers
        if any(c.foreign_keys for c in mapper.class_.__table__.columns)
        and not list(inspect(mapper.class_).relationships)
    )
    assert without == [], (
        f"{len(without)} models carry an FK column with no relationship() for the unit of "
        f"work to order by. Each is a parent that can be inserted after its child in a "
        f"single flush — a foreign key violation on Postgres:\n  {without}"
    )


def test_the_mutually_dependent_pairs_are_not_given_mapper_relationships():
    """The exemption, pinned so nobody closes it by "finishing the job".

    `dock_doors <-> yard_trailers` and `yard_trailers <-> shipments` are genuine mutual
    references — a trailer knows its door and a door knows its current trailer. Their DDL is
    ordered with `use_alter`. Adding relationships on both sides would put the cycle back at
    the mapper layer, where it is a CircularDependencyError at flush rather than a warning at
    sort.
    """
    from sqlalchemy.orm import configure_mappers

    configure_mappers()
    for child, parent in (("DockDoor", "YardTrailer"), ("Shipment", "YardTrailer")):
        cls = next(m.class_ for m in Base.registry.mappers if m.class_.__name__ == child)
        targets = {r.mapper.class_.__name__ for r in inspect(cls).relationships}
        assert parent not in targets, (
            f"{child} now has a mapper relationship to {parent}, which is one half of a "
            f"mutual pair. The other half exists, so this is a unit-of-work cycle."
        )




def test_foreign_keys_are_enforced_for_sqlite():
    """The enforcement is on, globally, and cannot be quietly switched off (FS-410).

    It began as a per-module opt-in, which protects the files that remembered to opt in —
    the set least likely to need it. It is now a `connect` listener in conftest, so every
    SQLite engine in the suite gets it, and this asserts the behaviour rather than the
    presence of the code: a dangling foreign key must be REFUSED.

    Cost of getting here: 76 tests at the first measurement, then 39 once eleven missing
    `relationship()` edges were added at the model level, then zero. Nothing found along the
    way was a test bug — every one was an insert order or an orphan row that real Postgres
    would have rejected all along.
    """
    import asyncio
    import uuid

    from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

    from app.db.shop_floor_models import SystemOfRecordPosting
    from tests._sqlite import create_all

    async def _dangling_reference_is_refused() -> bool:
        # A PLAIN engine, deliberately — NOT `tests._sqlite.sqlite_engine`, which sets the
        # pragma itself. Using the helper here would prove only that the helper works, and
        # the first version of this test did exactly that: flipping conftest's listener to
        # OFF left it passing. The subject is the GLOBAL enforcement, so the engine has to be
        # one that has done nothing to earn it.
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        await create_all(engine, Base.metadata, [SystemOfRecordPosting.__table__])
        try:
            async with async_sessionmaker(engine)() as session:
                session.add(SystemOfRecordPosting(
                    id=str(uuid.uuid4()),
                    # An organisation that does not exist.
                    organization_id=str(uuid.uuid4()),
                    event_type="part_issue", event_id=str(uuid.uuid4()),
                    target_system="inventory", status="pending", attempts=0,
                ))
                try:
                    await session.commit()
                    return False
                except Exception:
                    return True
        finally:
            await engine.dispose()

    assert asyncio.get_event_loop_policy().new_event_loop().run_until_complete(
        _dangling_reference_is_refused()
    ), (
        "SQLite accepted a row pointing at an organisation that does not exist, so foreign "
        "keys are not being enforced. Every in-memory test in this suite is then free to "
        "insert children before parents and pass, which is how the demo seed shipped broken."
    )
