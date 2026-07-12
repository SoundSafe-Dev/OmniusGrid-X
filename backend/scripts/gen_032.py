"""Generate 032_uuid_consolidation.sql from the ORM (FS-56).

Converts a pre-FS-55 database whose UUID id columns were created as
VARCHAR(36) (any DB built via Base.metadata.create_all, including initdb-era
dev volumes that the API's startup init_db() backfilled) to the native UUID
types the ORM and the migration chain now agree on.

The column list is generated from the ORM — every Column whose type is
UUIDString — so there are no name heuristics that could sweep in legitimate
string ids (audit_logs.resource_id, geotab device ids, edge agent_id,
logistics' plain String(36) columns all stay untouched because their ORM type
is String, not UUIDString).

Structure of the emitted SQL (every statement idempotent/resumable under
migrate.py's autocommit-per-statement execution):
  1. one DO block: dynamically drop every FK constraint that references or
     originates from a still-VARCHAR conversion column (auto-generated names
     on create_all DBs make static drops impossible)
  2. one DO block per table: ALTER COLUMN ... TYPE uuid USING NULLIF(col,'')::uuid
     for each listed column, guarded on information_schema data_type
  3. guarded ADD CONSTRAINT for every ORM FK between UUIDString columns,
     with explicit deterministic names
"""

import os
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
# postgres placeholder (never connects): StringListColumn shapes itself from
# settings.DATABASE_URL at import time — sqlite here would emit JSON where
# postgres deployments use ARRAY.
os.environ.setdefault("DATABASE_URL", "postgresql+asyncpg://gen:gen@localhost/gen")

from app.db import models  # noqa: F401
from app.db import logistics_models, notification_models, edge_fleet_models  # noqa: F401
from app.db.models import Base, UUIDString

cols = defaultdict(list)          # table -> [column, ...]
fks = []                          # (table, col, ref_table, ref_col)

for table in Base.metadata.sorted_tables:
    for col in table.columns:
        if isinstance(col.type, UUIDString):
            cols[table.name].append(col.name)
            for fk in col.foreign_keys:
                fks.append((table.name, col.name, fk.column.table.name,
                            fk.column.name, fk.ondelete))

pairs = sorted((t, c) for t, cs in cols.items() for c in cs)
pairs_sql = ",\n            ".join(f"('{t}', '{c}')" for t, c in pairs)

drop_block = f"""-- 1. Drop every FK touching a still-VARCHAR conversion column (both
--    directions), so the type changes below aren't blocked. Constraint names
--    on create_all-built databases are auto-generated, hence the dynamic loop.
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT DISTINCT con.conname, src.relname AS table_name
        FROM pg_constraint con
        JOIN pg_class src ON src.oid = con.conrelid
        JOIN pg_class tgt ON tgt.oid = con.confrelid
        JOIN pg_namespace ns ON ns.oid = src.relnamespace
        JOIN unnest(con.conkey) WITH ORDINALITY AS sk(attnum, ord) ON TRUE
        JOIN pg_attribute sa ON sa.attrelid = src.oid AND sa.attnum = sk.attnum
        JOIN unnest(con.confkey) WITH ORDINALITY AS tk(attnum, ord)
            ON tk.ord = sk.ord
        JOIN pg_attribute ta ON ta.attrelid = tgt.oid AND ta.attnum = tk.attnum
        WHERE con.contype = 'f'
          AND ns.nspname = 'public'
          AND (
            (src.relname, sa.attname) IN (
            {pairs_sql}
            )
            OR (tgt.relname, ta.attname) IN (
            {pairs_sql}
            )
          )
          AND EXISTS (
            SELECT 1 FROM information_schema.columns ic
            WHERE ic.table_schema = 'public'
              AND ic.data_type = 'character varying'
              AND (
                (ic.table_name = src.relname AND ic.column_name = sa.attname)
                OR (ic.table_name = tgt.relname AND ic.column_name = ta.attname)
              )
          )
    LOOP
        EXECUTE format('ALTER TABLE %I DROP CONSTRAINT %I', r.table_name, r.conname);
    END LOOP;
END $$;"""

convert_blocks = []
for tname in sorted(cols):
    stmts = []
    for cname in cols[tname]:
        stmts.append(f"""    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema = 'public' AND table_name = '{tname}'
          AND column_name = '{cname}' AND data_type = 'character varying'
    ) THEN
        ALTER TABLE {tname} ALTER COLUMN {cname} TYPE uuid USING NULLIF({cname}, '')::uuid;
    END IF;""")
    body = "\n".join(stmts)
    convert_blocks.append(f"""-- {tname}
DO $$
BEGIN
    IF to_regclass('public.{tname}') IS NOT NULL THEN
{body}
    END IF;
END $$;""")

readd_blocks = []
seen = set()
for tname, cname, rtable, rcol, ondelete in sorted(fks, key=lambda t: (t[0], t[1])):
    conname = f"fk_{tname}_{cname}"
    if conname in seen:
        continue
    seen.add(conname)
    od = f" ON DELETE {ondelete}" if ondelete else ""
    readd_blocks.append(f"""DO $$
BEGIN
    IF to_regclass('public.{tname}') IS NOT NULL
       AND to_regclass('public.{rtable}') IS NOT NULL
       AND NOT EXISTS (
        SELECT 1 FROM pg_constraint con
        JOIN pg_class src ON src.oid = con.conrelid
        JOIN unnest(con.conkey) AS k(attnum) ON TRUE
        JOIN pg_attribute a ON a.attrelid = src.oid AND a.attnum = k.attnum
        WHERE con.contype = 'f' AND src.relname = '{tname}' AND a.attname = '{cname}'
    ) THEN
        ALTER TABLE {tname} ADD CONSTRAINT {conname}
            FOREIGN KEY ({cname}) REFERENCES {rtable} ({rcol}){od};
    END IF;
END $$;""")

header = f"""-- 032_uuid_consolidation.sql (FS-56)
-- Converts VARCHAR(36) UUID columns to native uuid on databases built via
-- SQLAlchemy create_all before FS-55 made UUIDString dialect-aware. Fresh
-- migrations-built databases are already native (001..029 always were; 030
-- was regenerated) — every block here is guarded, so on such databases this
-- file is a no-op.
--
-- Generated by backend/scripts/gen_032.py from the ORM: {len(pairs)} columns
-- across {len(cols)} tables; {len(seen)} FKs re-added with explicit names.
-- Values are str(uuid4()) so the ::uuid cast is lossless; a non-UUID value
-- aborts that table's DO block (transactional) without corrupting data.
-- Idempotent/resumable: every block re-checks information_schema/pg_constraint.
"""

view_block = """-- 1b. Views over conversion tables block ALTER COLUMN TYPE. Save their
--     definitions, drop them, and recreate at the end (section 4). Runs only
--     when a conversion is actually pending.
DO $$
DECLARE
    r RECORD;
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = 'public' AND c.data_type = 'character varying'
          AND (c.table_name, c.column_name) IN (
            """ + pairs_sql + """
          )
    ) AND NOT EXISTS (
        -- reverse conversions (section 2b) also need dependent views gone
        SELECT 1 FROM information_schema.columns c
        WHERE c.table_schema = 'public' AND c.data_type = 'uuid'
          AND (c.table_name, c.column_name) IN (
            ('audit_logs', 'resource_id'), ('data_residency_tags', 'record_id')
          )
    ) THEN
        RETURN;  -- nothing to convert; leave views alone
    END IF;
    CREATE TABLE IF NOT EXISTS _uuid_consolidation_saved_views (
        viewname text PRIMARY KEY,
        definition text NOT NULL
    );
    FOR r IN
        SELECT DISTINCT v.viewname
        FROM pg_views v
        WHERE v.schemaname = 'public'
          AND EXISTS (
            SELECT 1 FROM information_schema.view_column_usage u
            WHERE u.view_schema = 'public' AND u.view_name = v.viewname
              AND u.table_schema = 'public'
              AND (u.table_name, u.column_name) IN (
                """ + pairs_sql + """
              )
          )
    LOOP
        INSERT INTO _uuid_consolidation_saved_views (viewname, definition)
        VALUES (r.viewname, pg_get_viewdef(('public.' || quote_ident(r.viewname))::regclass, true))
        ON CONFLICT (viewname) DO NOTHING;
        EXECUTE format('DROP VIEW IF EXISTS %I CASCADE', r.viewname);
    END LOOP;
END $$;"""

recreate_block = """-- 4. Recreate the views dropped in 1b (two passes for inter-view deps)
DO $$
DECLARE
    r RECORD;
    pass INT;
BEGIN
    IF to_regclass('public._uuid_consolidation_saved_views') IS NULL THEN
        RETURN;
    END IF;
    FOR pass IN 1..2 LOOP
        FOR r IN SELECT viewname, definition FROM _uuid_consolidation_saved_views LOOP
            BEGIN
                EXECUTE format('CREATE OR REPLACE VIEW %I AS %s', r.viewname, r.definition);
                DELETE FROM _uuid_consolidation_saved_views WHERE viewname = r.viewname;
            EXCEPTION WHEN OTHERS THEN
                IF pass = 2 THEN
                    RAISE WARNING 'could not recreate view %: %', r.viewname, SQLERRM;
                END IF;
            END;
        END LOOP;
    END LOOP;
    IF NOT EXISTS (SELECT 1 FROM _uuid_consolidation_saved_views) THEN
        DROP TABLE _uuid_consolidation_saved_views;
    END IF;
END $$;"""

reverse_block = """-- 2b. Reverse conversions: columns the ORM deliberately types as String
--    (polymorphic ids) that pre-FS-56 migration DDL created as uuid.
DO $$
BEGIN
    IF to_regclass('public.audit_logs') IS NOT NULL AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='audit_logs'
          AND column_name='resource_id' AND data_type='uuid'
    ) THEN
        ALTER TABLE audit_logs ALTER COLUMN resource_id TYPE VARCHAR(36) USING resource_id::text;
    END IF;
    IF to_regclass('public.data_residency_tags') IS NOT NULL AND EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_schema='public' AND table_name='data_residency_tags'
          AND column_name='record_id' AND data_type='uuid'
    ) THEN
        ALTER TABLE data_residency_tags ALTER COLUMN record_id TYPE VARCHAR(36) USING record_id::text;
    END IF;
END $$;"""

dest = Path(__file__).resolve().parents[2] / "database" / "migrations" / "032_uuid_consolidation.sql"
dest.write_text(
    header + "\n" + drop_block + "\n\n" + view_block + "\n\n"
    + "-- 2. Type conversions (guarded per column)\n\n"
    + "\n\n".join(convert_blocks)
    + "\n\n" + reverse_block
    + "\n\n-- 3. Re-add FKs with explicit names\n\n"
    + "\n\n".join(readd_blocks)
    + "\n\n" + recreate_block + "\n"
)
print(f"wrote {dest}: {len(pairs)} columns / {len(cols)} tables / {len(seen)} FKs")
