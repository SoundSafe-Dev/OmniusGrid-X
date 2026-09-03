-- 078: shipments has one composite index and two other filter shapes in real use (FS-891).
--
-- 043_organization_id_indexes.sql gave shipments (organization_id, created_at DESC), which
-- serves the plain tenant-scoped list ordered by recency. `api/transportation.py` has two
-- other access patterns that index does not cover:
--
--   * The shipments list (:762) filters `organization_id` AND, when given, `status` —
--     narrowing by status after the org predicate is a filter step with no index to use.
--   * The driver panel (:92-93) filters `driver_id IN (...)` and
--     `status NOT IN (<terminal statuses>)`, ordered by `scheduled_pickup DESC` — a
--     per-driver "what are they on right now" query with no index on driver_id at all.
CREATE INDEX IF NOT EXISTS ix_shipments_org_status_created
    ON shipments (organization_id, status, created_at DESC);

CREATE INDEX IF NOT EXISTS ix_shipments_driver_scheduled
    ON shipments (driver_id, scheduled_pickup DESC);
