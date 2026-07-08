-- Intake Cross-Correlation Schema Updates
-- Adds fields to IntakeItem and SessionDataSource to support
-- multi-page PDF/DOCX parsing, image text extraction, and cross-file correlation.

-- IntakeItem: store shared keys, document structure metadata, and actual processing time
ALTER TABLE intake_items
ADD COLUMN IF NOT EXISTS shared_keys JSON DEFAULT '[]',
ADD COLUMN IF NOT EXISTS structure_metadata JSON DEFAULT '{}',
ADD COLUMN IF NOT EXISTS processing_time_seconds INTEGER;

-- SessionDataSource: same fields for session-based cross-file correlation
ALTER TABLE session_data_sources
ADD COLUMN IF NOT EXISTS shared_keys JSON DEFAULT '[]',
ADD COLUMN IF NOT EXISTS structure_metadata JSON DEFAULT '{}';

-- Indexes for faster shared-key lookups during cross-file correlation
CREATE INDEX IF NOT EXISTS idx_intake_items_shared_keys ON intake_items USING GIN (shared_keys);
CREATE INDEX IF NOT EXISTS idx_session_data_sources_shared_keys ON session_data_sources USING GIN (shared_keys);

-- Comment on new columns
COMMENT ON COLUMN intake_items.shared_keys IS 'Normalized shared keys (asset_id, date, order_number, etc.) extracted from filename, metadata, and content for cross-file correlation';
COMMENT ON COLUMN intake_items.structure_metadata IS 'Document structure info (page_count, section_count, tables, headers) for PDF/DOCX/image parsing';
COMMENT ON COLUMN intake_items.processing_time_seconds IS 'Actual time in seconds taken to parse and process the file (for estimation calibration)';

COMMENT ON COLUMN session_data_sources.shared_keys IS 'Normalized shared keys for cross-file correlation within analysis sessions';
COMMENT ON COLUMN session_data_sources.structure_metadata IS 'Document structure info for session data sources';
