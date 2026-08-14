-- =============================================================================
-- Migration 044: rag_documents.size_bytes (per-tenant ingest quota)
-- =============================================================================
-- The per-org max-total-bytes quota needs the stored size of each blob. Nothing
-- recorded it before: the API knew the upload length and threw it away after
-- the S3 put, so a total could only be recovered by listing the object store.
--
-- Backfills to 0 rather than NULL: an existing row's real size is only in
-- SeaweedFS, and a quota that reads 0 for pre-migration documents undercounts
-- (permissive) instead of blocking every tenant on an unknown. New rows always
-- carry the true size.

BEGIN;

ALTER TABLE rag_documents
    ADD COLUMN IF NOT EXISTS size_bytes BIGINT NOT NULL DEFAULT 0;

-- init_db() may have created the column from ORM metadata already; make the
-- default match either way, same reconciliation pattern as migration 043.
ALTER TABLE rag_documents
    ALTER COLUMN size_bytes SET DEFAULT 0;

-- Quota reads are COUNT(*) + SUM(size_bytes) per org, plus a created_at window
-- for the rate limit. idx_rag_documents_org_created already covers the ordering;
-- this makes the aggregate an index-only scan.
CREATE INDEX IF NOT EXISTS idx_rag_documents_org_quota
    ON rag_documents(organization_id) INCLUDE (size_bytes, created_at);

COMMIT;
