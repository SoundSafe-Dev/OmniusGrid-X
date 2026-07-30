-- =============================================================================
-- Migration 043: RAG document registry (async ingestion status + work queue)
-- =============================================================================
-- One row per (organization_id, doc_id). Doubles as the indexing work queue:
-- the worker claims status='queued' rows with FOR UPDATE SKIP LOCKED.
-- Deliberately a PLAIN table, not a hypertable — TimescaleDB requires every
-- UNIQUE constraint on a hypertable to include the partitioning column, which
-- would break the one-row-per-document invariant this design depends on.

BEGIN;

CREATE TABLE IF NOT EXISTS rag_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    doc_id TEXT NOT NULL,
    uploaded_by UUID,
    filename VARCHAR(255) NOT NULL,
    s3_key TEXT NOT NULL,
    kind VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    num_blocks INTEGER NOT NULL DEFAULT 0,
    num_chunks INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    CONSTRAINT ck_rag_documents_status
        CHECK (status IN ('queued', 'indexing', 'indexed', 'skipped', 'failed')),
    CONSTRAINT ck_rag_documents_kind
        CHECK (kind IN ('pdf', 'docx', 'markdown', 'csv', 'image', 'text', 'unsupported')),
    CONSTRAINT uq_rag_documents_org_doc UNIQUE (organization_id, doc_id),
    CONSTRAINT fk_rag_documents_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_rag_documents_uploaded_by
        FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
);

-- init_db() may have created this table from ORM metadata before migrations
-- run. Reconcile defaults, constraints, and FK actions so both bootstrap paths
-- produce the same schema.
ALTER TABLE rag_documents
    ALTER COLUMN status SET DEFAULT 'queued',
    ALTER COLUMN attempts SET DEFAULT 0,
    ALTER COLUMN num_blocks SET DEFAULT 0,
    ALTER COLUMN num_chunks SET DEFAULT 0,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN updated_at SET DEFAULT NOW();

ALTER TABLE rag_documents
    DROP CONSTRAINT IF EXISTS ck_rag_documents_status,
    DROP CONSTRAINT IF EXISTS ck_rag_documents_kind;

ALTER TABLE rag_documents
    ADD CONSTRAINT ck_rag_documents_status
        CHECK (status IN ('queued', 'indexing', 'indexed', 'skipped', 'failed')),
    ADD CONSTRAINT ck_rag_documents_kind
        CHECK (kind IN ('pdf', 'docx', 'markdown', 'csv', 'image', 'text', 'unsupported'));

DO $$
DECLARE
    fk_name TEXT;
BEGIN
    FOR fk_name IN
        SELECT constraint_name
        FROM information_schema.key_column_usage
        WHERE table_schema = current_schema()
          AND table_name = 'rag_documents'
          AND column_name IN ('organization_id', 'uploaded_by')
          AND position_in_unique_constraint IS NOT NULL
    LOOP
        EXECUTE format('ALTER TABLE rag_documents DROP CONSTRAINT %I', fk_name);
    END LOOP;
END
$$;

ALTER TABLE rag_documents
    ADD CONSTRAINT fk_rag_documents_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_rag_documents_uploaded_by
        FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL;

-- The unique constraint may be absent on an ORM-created table.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_rag_documents_org_doc'
          AND conrelid = 'rag_documents'::regclass
    ) THEN
        ALTER TABLE rag_documents
            ADD CONSTRAINT uq_rag_documents_org_doc
            UNIQUE (organization_id, doc_id);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_rag_documents_org_created
    ON rag_documents(organization_id, created_at DESC);

-- Partial indexes sized to the queue rather than the table: the claimable and
-- in-flight states are a small minority of rows.
CREATE INDEX IF NOT EXISTS idx_rag_documents_claimable
    ON rag_documents(organization_id, created_at) WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS idx_rag_documents_stale
    ON rag_documents(updated_at) WHERE status = 'indexing';

ALTER TABLE rag_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_documents FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON rag_documents;
CREATE POLICY tenant_isolation ON rag_documents
    FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

COMMIT;
