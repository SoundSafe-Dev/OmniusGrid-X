-- 040_metadata_column_rename.sql
--
-- Schema-drift fix (converged): the ORM maps these tables' JSON blob to the
-- attribute/column ``meta_data`` (renamed from ``metadata`` to avoid clashing
-- with SQLAlchemy's reserved ``Base.metadata``), but the migrations created the
-- column as ``metadata``. On a migrations-built database the app 500s with
-- "column <t>.meta_data does not exist (HINT: perhaps you meant metadata)" on
-- every read of these tables. SQLite dev (create_all) already used meta_data, so
-- this stayed latent until the real migration chain was exercised.
--
-- Idempotent + adoption-safe: each rename only fires when the old column exists
-- and the new one does not, so it is a no-op on create_all-built / already-fixed
-- databases.

DO $$
DECLARE t text;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'alarms', 'api_keys', 'consent_records', 'data_residency_tags',
        'operations', 'packml_states', 'security_assets'
    ]
    LOOP
        IF EXISTS (SELECT 1 FROM information_schema.columns
                   WHERE table_name = t AND column_name = 'metadata')
           AND NOT EXISTS (SELECT 1 FROM information_schema.columns
                           WHERE table_name = t AND column_name = 'meta_data') THEN
            EXECUTE format('ALTER TABLE %I RENAME COLUMN metadata TO meta_data', t);
        END IF;
    END LOOP;
END $$;

-- integration_configurations never got the column under either name.
ALTER TABLE integration_configurations
    ADD COLUMN IF NOT EXISTS meta_data JSONB DEFAULT '{}'::jsonb;
