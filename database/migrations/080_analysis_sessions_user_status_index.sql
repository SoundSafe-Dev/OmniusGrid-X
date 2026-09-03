-- 080: analysis_sessions.user_id has no index; most of its own routes filter by it (FS-893).
--
-- Migration 043 gave analysis_sessions (organization_id, created_at DESC) for the
-- tenant-scoped list. `api/analysis_sessions.py`'s OWN routes almost never use that
-- predicate: every session is fetched, listed, or deleted by
-- `AnalysisSession.user_id == current_user.id` — more call sites than any other
-- predicate in the file — several additionally filtering `status`. That column has no
-- index at all.
CREATE INDEX IF NOT EXISTS ix_analysis_sessions_user_status
    ON analysis_sessions (user_id, status);
