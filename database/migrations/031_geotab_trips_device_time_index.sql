-- 031: composite index for latest-trip-per-device lookups.
-- The location webhook and the fleet map both run
--   WHERE device_id = ? [AND status='active'] ORDER BY start_time DESC LIMIT 1;
-- the existing single-column device_id index leaves a per-query sort over the
-- device's whole trip history.
CREATE INDEX IF NOT EXISTS ix_geotab_trips_device_start
    ON geotab_trips (device_id, start_time DESC);
