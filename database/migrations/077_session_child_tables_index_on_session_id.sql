-- 077: index session_data_sources.session_id and session_messages.session_id (FS-889).
--
-- Both tables (030_orm_backfill_tables.sql) carry a FOREIGN KEY on session_id but no
-- index leading with it. The only index touching either table is a GIN on
-- `shared_keys::jsonb` (021/033) — unrelated to this join. That join key is exactly
-- what FS-887 registered as HARSH's N+1 (`api/analysis_sessions.py:494-504`, 2 SELECTs
-- per session): even after that query count is collapsed, each of those SELECTs
-- filtering on session_id is a sequential scan on both tables until this exists.
CREATE INDEX IF NOT EXISTS ix_session_data_sources_session_id
    ON session_data_sources (session_id);

CREATE INDEX IF NOT EXISTS ix_session_messages_session_id
    ON session_messages (session_id);
