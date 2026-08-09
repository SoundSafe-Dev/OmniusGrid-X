-- 053: assets.maintenance_mode
--
-- THE COLUMN THE FEATURE WAS BUILT AROUND AND NOBODY ADDED.
--
-- `POST /admin/assets/{id}/maintenance` writes `assets.maintenance_mode`, and
-- `TacticalEngine._is_maintenance_mode` reads it to decide whether a control command may
-- be dispatched. The column has never existed in this schema, so:
--
--   * the endpoint raised UndefinedColumnError and returned 500 on every call, while
--     `assetsApi.setMaintenanceMode` in the frontend called it in earnest;
--   * the reader caught the error and failed SAFE -- returning True, "in maintenance" --
--     which suppresses every command for every asset. Its comment already anticipated
--     this ("the query can also error on deployments where assets.maintenance_mode
--     doesn't exist"), so the read side was written defensively against a schema that
--     was never completed.
--
-- Failing safe made the gap survivable and invisible. Nothing in the product could put a
-- machine into maintenance, and the message returned to whoever tried said "Game-
-- theoretic engine commands are blocked."
--
-- DEFAULT FALSE, NOT NULL: a nullable flag would reintroduce the ambiguity this codebase
-- has spent a lot of effort removing -- NULL would coerce to "not in maintenance" through
-- `bool(row[0])` and read as a decision nobody made.
ALTER TABLE assets
    ADD COLUMN IF NOT EXISTS maintenance_mode BOOLEAN NOT NULL DEFAULT FALSE;

COMMENT ON COLUMN assets.maintenance_mode IS
    'Operator override: when true, TacticalEngine suppresses control commands for this asset.';

CREATE INDEX IF NOT EXISTS idx_assets_maintenance_mode
    ON assets (organization_id)
    WHERE maintenance_mode;
