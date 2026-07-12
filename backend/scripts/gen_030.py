"""Regenerate 030_orm_backfill_tables.sql from the (now dialect-aware) ORM.

Same generation approach as the original FS-24 version — CreateTable compiled
against the postgresql dialect — but the ORM's UUIDString now renders native
UUID on Postgres, which fixes the 28 varchar->uuid cross-type FKs that made
the original 030 unappliable on a migrations-built database.

FKs referencing tables in this set are emitted as trailing ALTER TABLE ... ADD
CONSTRAINT (named, guarded) to break the dock_doors<->shipments<->yard_trailers
cycle; FKs referencing PRE-EXISTING tables (001 etc.) stay inline.
"""

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")

from sqlalchemy.dialects import postgresql
from sqlalchemy.schema import CreateTable, CreateIndex, AddConstraint, ForeignKeyConstraint

from app.db import models  # noqa: F401 - registers all tables on Base
from app.db import logistics_models, notification_models, edge_fleet_models  # noqa: F401
from app.db.models import Base

TABLES = [
    "yard_trailers", "dock_doors", "carriers", "shipments", "routes",
    "analysis_sessions", "intake_items", "geotab_diagnostics",
    "yard_checkpoints", "drivers", "load_plans", "freight_charges",
    "truck_asset_correlations", "load_quality_logs", "session_data_sources",
    "session_messages", "yard_moves", "driver_wait_times",
    "dock_appointments", "geotab_trips", "geotab_exceptions",
]

dialect = postgresql.dialect()
in_set = set(TABLES)

out = []
deferred = []  # (table, ForeignKeyConstraint) for intra-set FKs

for name in TABLES:
    table = Base.metadata.tables[name]
    # Split FKs: intra-set -> deferred ALTERs (cycle-safe); external -> inline.
    intra = [
        c for c in table.constraints
        if isinstance(c, ForeignKeyConstraint)
        and list(c.elements)[0].column.table.name in in_set
    ]
    for c in intra:
        table.constraints.discard(c)
        deferred.append((name, c))
    ddl = str(CreateTable(table).compile(dialect=dialect)).strip()
    ddl = ddl.replace("CREATE TABLE", "CREATE TABLE IF NOT EXISTS", 1)
    out.append(ddl + ";")
    for idx in table.indexes:
        iddl = str(CreateIndex(idx).compile(dialect=dialect)).strip()
        iddl = iddl.replace("CREATE INDEX", "CREATE INDEX IF NOT EXISTS", 1)
        iddl = iddl.replace("CREATE UNIQUE INDEX", "CREATE UNIQUE INDEX IF NOT EXISTS", 1)
        out.append(iddl + ";")

alters = []
for tname, c in deferred:
    el = list(c.elements)[0]
    src_cols = ", ".join(col.name for col in c.columns)
    tgt = el.column
    cname = f"fk_{tname}_{src_cols.replace(', ', '_')}"
    alters.append(
        f"""DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM pg_constraint WHERE conname = '{cname}') THEN
        ALTER TABLE {tname} ADD CONSTRAINT {cname}
            FOREIGN KEY ({src_cols}) REFERENCES {tgt.table.name} ({tgt.name});
    END IF;
END $$;"""
    )

header = """-- 030_orm_backfill_tables.sql (FS-24, regenerated FS-56)
-- Backfills the 21 tables that previously existed ONLY via SQLAlchemy
-- create_all() (yard, transportation, geotab, analysis-session, intake), so the
-- SQL migration path builds a complete schema without depending on the API
-- process having run init_db() first.
--
-- Generated from the ORM metadata (postgresql dialect) by
-- backend/scripts/gen_030.py. FS-56 regeneration: UUIDString now renders
-- native UUID on Postgres, fixing the 28 varchar->uuid cross-type FKs that
-- made the original file unappliable on a migrations-built database (it
-- failed at the first FK to organizations). Intra-set FKs are emitted as
-- trailing guarded ALTERs to break the dock_doors<->shipments<->yard_trailers
-- cycle. All statements are IF NOT EXISTS / guarded, so this is safe to run
-- on a database already built via init_db().
--
-- NOTE: a pre-FS-56 database built via create_all (VARCHAR ids) must run
-- 032_uuid_consolidation.sql (applied after this) to converge.
"""

dest = Path(__file__).resolve().parents[2] / "database" / "migrations" / "030_orm_backfill_tables.sql"
dest.write_text(header + "\n" + "\n\n".join(out) + "\n\n" + "\n\n".join(alters) + "\n")
print(f"wrote {dest} ({len(out)} DDL statements, {len(alters)} deferred FKs)")
