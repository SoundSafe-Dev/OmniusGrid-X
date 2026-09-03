-- 076: index assets.name, and give the leading-wildcard search something to use.
--
-- `assets` carries ten indexes (001/024) and none on `name`, while `api/assets.py`
-- orders every list call by `Asset.name` and, when a search term is given, filters with
-- `Asset.name.ilike('%search%')` (FS-888). A leading wildcard cannot use a plain btree
-- index at all — the pattern could start anywhere in the string — so that filter has
-- always been a sequential scan on the largest table in the product, and grepping every
-- prior migration for `pg_trgm` returns nothing: nothing here could have served it even
-- if an index existed.
--
-- pg_trgm's GIN index is what makes `ilike '%x%'` plannable, matching the pattern
-- 043_organization_id_indexes.sql set for tenant-scoped composites and 004's guarded
-- extension creation for an optional contrib module. Unlike pg_stat_statements,
-- pg_trgm needs no preload — it is a normal contrib extension — but the create is still
-- guarded, because a hosted Postgres can restrict extension installation to a superuser
-- and this repository does not control every environment it runs in.
DO $$
BEGIN
    CREATE EXTENSION IF NOT EXISTS pg_trgm;
EXCEPTION WHEN OTHERS THEN
    RAISE NOTICE 'pg_trgm unavailable (needs a superuser or an allow-listed extension): %', SQLERRM;
END $$;

-- The ORDER BY case: every list call sorts by name within an organisation, so the
-- leading column serves both the RLS predicate (rule set out in 043) and the sort.
-- Plain CREATE INDEX, matching 043: correct and instant on a fresh chain.
CREATE INDEX IF NOT EXISTS ix_assets_org_name
    ON assets (organization_id, name);

-- The ILIKE '%...%' case, guarded the same way as the extension it depends on: a
-- restricted environment without pg_trgm gets the ORDER BY index above and a slow
-- search, not a broken migration.
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'pg_trgm') THEN
        CREATE INDEX IF NOT EXISTS ix_assets_name_trgm
            ON assets USING gin (name gin_trgm_ops);
    ELSE
        RAISE NOTICE 'pg_trgm not installed; skipping ix_assets_name_trgm (search stays a sequential scan)';
    END IF;
END $$;
