-- 063: the sync row remembers whether correlation ran (FS-562)
--
-- THE SERVER ALREADY KNEW AND THE ANSWER DID NOT SURVIVE THE REQUEST. `correlate_synced_records`
-- returns `routed: false` with a reason when no transformer is registered for an
-- (erp_type, entity_type) pair, and the sync route puts it in the POST response — which is
-- read once and gone. The page an operator actually watches polls `GET /sync-status`, built
-- from this table, and this table had nowhere to put it.
--
-- So the correlations tab shows "No correlations" in two situations that mean opposite things:
--
--   * the vendor's records were analysed and nothing anomalous was found, and
--   * no analyzer exists for this vendor's field names, so nothing was ever looked at.
--
-- The first is a result. The second is a gap, and presenting it as the first is the same
-- defect class as a failed read rendering as an empty list — a **verdict computed from
-- emptiness**, one layer further back.
--
-- NULL is a third state and it is the right default: rows written before this migration
-- record no correlation attempt either way, and claiming `false` for them would invent a
-- skip that may never have happened. The UI reads null as "not recorded".

ALTER TABLE erp_sync_status
  ADD COLUMN IF NOT EXISTS correlation_routed BOOLEAN;

ALTER TABLE erp_sync_status
  ADD COLUMN IF NOT EXISTS correlation_reason TEXT;

COMMENT ON COLUMN erp_sync_status.correlation_routed IS
  'Whether a correlation route existed for this (erp_type, entity_type) on the last sync. '
  'NULL means no correlation was attempted or the sync predates FS-562.';
COMMENT ON COLUMN erp_sync_status.correlation_reason IS
  'Why correlation produced nothing, when it produced nothing. NULL when it ran normally.';
