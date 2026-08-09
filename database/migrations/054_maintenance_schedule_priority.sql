-- Maintenance schedules: persist the priority the UI has always collected.
--
-- `MaintenancePanel` offers Low / Normal / High / Urgent on the create form and renders
-- a coloured priority badge on every row. Neither end of that worked:
--
--   * `create_schedule` never read `priority` — the table has no such column — so the
--     technician's choice was accepted by the form and discarded by the handler;
--   * `_schedule_out` never emitted one, so the frontend adapter substituted the literal
--     'medium' — a value that is not even in the declared union
--     ('low' | 'normal' | 'high' | 'urgent'). Every schedule displayed the same made-up
--     priority regardless of what was selected.
--
-- Same shape as 053_assets_maintenance_mode: a field the product collects and displays,
-- with nowhere to live. NOT NULL with a default so existing rows land on 'normal' rather
-- than NULL — a nullable column would put the ambiguity straight back, since the reader
-- would have to decide what a missing priority means.
ALTER TABLE maintenance_schedules
    ADD COLUMN IF NOT EXISTS priority VARCHAR(20) NOT NULL DEFAULT 'normal';

COMMENT ON COLUMN maintenance_schedules.priority IS
    'low | normal | high | urgent — set by the operator when scheduling. Defaults to normal.';

-- The panel sorts and filters attention by priority; urgent work is the query that matters.
CREATE INDEX IF NOT EXISTS idx_maintenance_schedules_priority
    ON maintenance_schedules (organization_id, priority)
    WHERE status IN ('scheduled', 'overdue');
