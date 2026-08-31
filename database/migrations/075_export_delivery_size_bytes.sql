-- =============================================================================
-- Migration 075: export_delivery_jobs.size_bytes (per-tenant storage quota)
-- =============================================================================
-- FS-842's storage quota has to sum every object a tenant owns, and there are
-- three producers: compliance reports (`compliance_report_jobs.file_size`), RAG
-- documents (`rag_documents.size_bytes`, migration 074) and exports — which
-- recorded no size at all. The processor uploads from a local path and threw the
-- size away, so a tenant's export footprint was recoverable only by listing the
-- bucket.
--
-- THAT GAP MATTERED MORE THAN THE MISSING COLUMN. A storage quota that silently
-- omits one of three producers is a quota that lies: it reports a tenant inside
-- its limit while the largest single artefact class is uncounted, and the way a
-- tenant would exceed it is by generating exports. Better no quota than one that
-- under-reports the thing most likely to blow it.
--
-- Backfills to 0 rather than NULL, for the reason migration 074 gives: an
-- existing row's real size is only in the object store, and reading 0 for
-- pre-migration rows undercounts (permissive) rather than blocking every tenant
-- on an unknown. New rows carry the true size.

BEGIN;

ALTER TABLE export_delivery_jobs
    ADD COLUMN IF NOT EXISTS size_bytes BIGINT NOT NULL DEFAULT 0;

-- init_db() may have created the column from ORM metadata already; make the
-- default match either way, the same reconciliation pattern as 043/044.
ALTER TABLE export_delivery_jobs
    ALTER COLUMN size_bytes SET DEFAULT 0;

-- The quota sums by organisation, so that is the access path.
CREATE INDEX IF NOT EXISTS idx_export_delivery_jobs_org_size
    ON export_delivery_jobs (organization_id)
    INCLUDE (size_bytes);

COMMIT;
