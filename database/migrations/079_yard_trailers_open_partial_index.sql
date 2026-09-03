-- 079: partial index for "trailers still in the yard" (FS-892).
--
-- `api/yard.py:833-840`'s live-detention query filters
-- `check_in_at IS NOT NULL AND check_out_at IS NULL` plus organization_id — the same
-- "find the open row" shape `060_shop_floor_events.sql` already indexed for
-- `labor_entries` (open clock-ins) and `downtime_events` (open outages), in both cases
-- as a partial index on the organization plus the open-row predicate. Migration 043 gave
-- yard_trailers (organization_id, check_in_at DESC), which orders the org's full history;
-- it does not narrow to the currently-checked-in subset, which is what this query, and
-- the detention banner polling it, actually need.
CREATE INDEX IF NOT EXISTS ix_yard_trailers_org_open
    ON yard_trailers (organization_id)
    WHERE check_in_at IS NOT NULL AND check_out_at IS NULL;
