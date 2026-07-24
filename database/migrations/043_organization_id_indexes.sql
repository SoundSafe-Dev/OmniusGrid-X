-- 043: organization_id indexes for tenant-scoped tables.
--
-- Row-Level Security (011/033) rewrites EVERY query against these tables to
-- carry `organization_id = current_setting('app.current_org_id')`, so
-- organization_id is a predicate on every read — yet 27 base tables that carry
-- it had no index leading with it, forcing a sequential scan per tenant query.
-- The gap was found by introspecting the migrated schema (60 org-scoped tables,
-- only 32 indexed); a guard test now keeps it closed
-- (test_schema_parity.test_org_scoped_tables_have_org_index).
--
-- Each index is composite `(organization_id, <time> DESC)` rather than a bare
-- (organization_id): the leading column serves the RLS predicate, and the
-- trailing time column also serves the overwhelmingly common
-- "this org's rows, most-recent first" list/range queries (the full scans the
-- audit flagged in kpi.py / fleet_health.py) without a second index.
--
-- Plain CREATE INDEX (matching 031): correct and instant on a fresh chain.
-- Adopting this on a large EXISTING database will hold a write-blocking lock for
-- the build; an operator may prefer to pre-build each one CONCURRENTLY by hand
-- before applying this migration (then IF NOT EXISTS makes these no-ops).

-- Logistics / yard / transportation ---------------------------------------
CREATE INDEX IF NOT EXISTS ix_yard_trailers_org_checkin
    ON yard_trailers (organization_id, check_in_at DESC);
CREATE INDEX IF NOT EXISTS ix_dock_doors_org_created
    ON dock_doors (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_dock_appointments_org_created
    ON dock_appointments (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_yard_checkpoints_org_created
    ON yard_checkpoints (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_yard_moves_org_created
    ON yard_moves (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_carriers_org_created
    ON carriers (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_drivers_org_created
    ON drivers (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_driver_wait_times_org_checkin
    ON driver_wait_times (organization_id, check_in_at DESC);
CREATE INDEX IF NOT EXISTS ix_shipments_org_created
    ON shipments (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_routes_org_created
    ON routes (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_load_plans_org_created
    ON load_plans (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_freight_charges_org_created
    ON freight_charges (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_load_quality_logs_org_created
    ON load_quality_logs (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_truck_asset_correlations_org_created
    ON truck_asset_correlations (organization_id, created_at DESC);

-- Fleet telemetry (GeoTab) -------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_geotab_diagnostics_org_created
    ON geotab_diagnostics (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_geotab_exceptions_org_ts
    ON geotab_exceptions (organization_id, timestamp DESC);
CREATE INDEX IF NOT EXISTS ix_geotab_trips_org_start
    ON geotab_trips (organization_id, start_time DESC);
CREATE INDEX IF NOT EXISTS ix_geofence_alerts_org_created
    ON geofence_alerts (organization_id, created_at DESC);

-- Fleet maintenance --------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_maintenance_schedules_org_created
    ON maintenance_schedules (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_repair_orders_org_created
    ON repair_orders (organization_id, created_at DESC);

-- Correlation AI / intake --------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_analysis_sessions_org_created
    ON analysis_sessions (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_intake_items_org_created
    ON intake_items (organization_id, created_at DESC);

-- Platform (OTA / errors / exports / core) ---------------------------------
CREATE INDEX IF NOT EXISTS ix_agent_rollout_events_org_created
    ON agent_rollout_events (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_error_events_org_last_seen
    ON error_events (organization_id, last_seen DESC);
CREATE INDEX IF NOT EXISTS ix_export_delivery_jobs_org_created
    ON export_delivery_jobs (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_users_org_created
    ON users (organization_id, created_at DESC);
CREATE INDEX IF NOT EXISTS ix_workcells_org_created
    ON workcells (organization_id, created_at DESC);
