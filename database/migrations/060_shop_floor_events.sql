-- 060_shop_floor_events.sql
--
-- The four shop-floor events, and an explicit ledger of what each one reached (FS-405).
--
-- WHAT WAS MISSING. The platform could read an ERP — inbound sync, webhooks, correlation
-- over the result — and could not record a single thing that happens on the floor. There
-- was no part issue, no labour entry, no quality event and no downtime event in the schema,
-- and `ERPConnectorBase` exposes `fetch_data`, `subscribe_to_events` and `health_check` with
-- NO WRITE METHOD AT ALL. Every ERP tie-in was one-directional.
--
-- THE LEDGER IS THE POINT, not the four event tables.
--
-- "Issuing a part ties into inventory, purchasing and accounting" is three claims about
-- three systems, and each can independently succeed, fail, be queued, or have no integration
-- at all. A boolean `synced` column would collapse those into one bit and the bit would lie:
-- this repository has spent its whole life finding places where an absent side effect was
-- reported as a completed one — an alert that was logged instead of dispatched and still
-- returned an identifier, a collector "restart" that was a bare return with a hardcoded
-- timestamp, a compliance report stating four figures it never computed.
--
-- So `system_of_record_postings` carries ONE ROW PER (event, target system), each with its
-- own status and its own reason. An event is not "posted"; it is posted to inventory,
-- queued for accounting, and awaiting a human for purchasing — and the API can say exactly
-- that.
--
-- MANUAL IS A FIRST-CLASS OUTCOME, not a failure. Plenty of real shops have no API for
-- purchasing, and the correct behaviour is to tell someone — the analog path. A posting in
-- `manual_required` carries the instruction to hand over, so "nobody was told" is
-- distinguishable from "the integration is down", which are different problems with
-- different fixes. `pending` means we have not tried yet; `failed` means we tried and it
-- did not work; `not_applicable` means this shop does not route this event there and
-- someone decided that on purpose.
--
-- TENANCY. Every table carries organization_id with a FORCE RLS policy, matching 055-058.
-- FORCE matters here more than usual: these tables carry labour hours and part costs, and
-- the application connects as the table owner in several deployments, so without FORCE the
-- policy would read as protection while the only connection that matters bypassed it.

BEGIN;

-- ---------------------------------------------------------------------------- part issues
CREATE TABLE IF NOT EXISTS part_issues (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID         NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    part_number         VARCHAR(100) NOT NULL,
    description         TEXT,
    quantity            NUMERIC NOT NULL,
    unit_of_measure     VARCHAR(20) NOT NULL DEFAULT 'each',
    -- Where it went. All optional: a part can be issued to a machine, to a work order, or
    -- to neither (consumables), and forcing one would make the honest cases unrecordable.
    asset_id            UUID         REFERENCES assets(id) ON DELETE SET NULL,
    work_order_ref      VARCHAR(100),
    -- What it cost. NULL means not known at issue time, which is normal — costing often
    -- resolves later in the ERP. It is deliberately not defaulted to 0: "free" and
    -- "not yet priced" are different, and 0 in an accounting feed is a claim.
    unit_cost           NUMERIC,
    currency            VARCHAR(3),
    issued_by           UUID         REFERENCES users(id) ON DELETE SET NULL,
    issued_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    reason              VARCHAR(50) NOT NULL DEFAULT 'production',
    notes               TEXT,
    meta_data           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_part_issues_org_issued  ON part_issues (organization_id, issued_at DESC);
CREATE INDEX IF NOT EXISTS ix_part_issues_part        ON part_issues (organization_id, part_number);

-- -------------------------------------------------------------------------- labour entries
CREATE TABLE IF NOT EXISTS labor_entries (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID         NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    user_id             UUID         REFERENCES users(id) ON DELETE SET NULL,
    -- Who, when the operator is not a platform user. A shop floor has staff without logins.
    operator_ref        VARCHAR(100),
    asset_id            UUID         REFERENCES assets(id) ON DELETE SET NULL,
    work_order_ref      VARCHAR(100),
    clock_in_at         TIMESTAMPTZ NOT NULL,
    -- NULL while the clock is still running. The open entry is the whole point of a time
    -- clock, so it must be representable.
    clock_out_at        TIMESTAMPTZ,
    -- Derived on clock-out and stored, because the accounting feed needs a fixed number and
    -- recomputing from timestamps later would silently change historical postings.
    duration_minutes    NUMERIC,
    labor_category      VARCHAR(50) NOT NULL DEFAULT 'direct',
    notes               TEXT,
    meta_data           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_labor_entries_org_in    ON labor_entries (organization_id, clock_in_at DESC);
-- Finding the open entry for a person is the hot query on every clock-out.
CREATE INDEX IF NOT EXISTS ix_labor_entries_open      ON labor_entries (organization_id, user_id)
    WHERE clock_out_at IS NULL;

-- -------------------------------------------------------------------------- quality events
CREATE TABLE IF NOT EXISTS quality_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID         NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    asset_id            UUID         REFERENCES assets(id) ON DELETE SET NULL,
    work_order_ref      VARCHAR(100),
    part_number         VARCHAR(100),
    event_type          VARCHAR(50) NOT NULL DEFAULT 'defect',
    severity            VARCHAR(20) NOT NULL DEFAULT 'minor',
    description         TEXT NOT NULL,
    quantity_affected   NUMERIC,
    disposition         VARCHAR(50),
    -- Scrap is what makes this an inventory AND an accounting event rather than only a
    -- quality one; it is nullable because the disposition is often decided later.
    scrap_quantity      NUMERIC,
    reported_by         UUID         REFERENCES users(id) ON DELETE SET NULL,
    occurred_at         TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    resolved_at         TIMESTAMPTZ,
    meta_data           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_quality_events_org_time ON quality_events (organization_id, occurred_at DESC);
CREATE INDEX IF NOT EXISTS ix_quality_events_asset    ON quality_events (organization_id, asset_id);

-- ------------------------------------------------------------------------- downtime events
CREATE TABLE IF NOT EXISTS downtime_events (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID         NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    asset_id            UUID         NOT NULL REFERENCES assets(id) ON DELETE CASCADE,
    -- planned | unplanned | changeover | maintenance
    downtime_type       VARCHAR(30) NOT NULL DEFAULT 'unplanned',
    reason_code         VARCHAR(50),
    description         TEXT,
    started_at          TIMESTAMPTZ NOT NULL,
    -- NULL while the machine is still down. Same reasoning as an open labour entry: the
    -- in-progress state is the one an operator most needs to see.
    ended_at            TIMESTAMPTZ,
    duration_minutes    NUMERIC,
    maintenance_ref     VARCHAR(100),
    reported_by         UUID         REFERENCES users(id) ON DELETE SET NULL,
    meta_data           JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_downtime_events_org_start ON downtime_events (organization_id, started_at DESC);
CREATE INDEX IF NOT EXISTS ix_downtime_events_open      ON downtime_events (organization_id, asset_id)
    WHERE ended_at IS NULL;

-- --------------------------------------------------------------- the fan-out ledger itself
CREATE TABLE IF NOT EXISTS system_of_record_postings (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID         NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,
    -- part_issue | labor_entry | quality_event | downtime_event
    event_type          VARCHAR(30) NOT NULL,
    -- No FK: it points at one of four tables depending on event_type.
    event_id            UUID NOT NULL,
    -- inventory | purchasing | accounting | production | quality | scheduling | maintenance
    target_system       VARCHAR(30) NOT NULL,
    -- pending | posted | failed | manual_required | not_applicable
    status              VARCHAR(20) NOT NULL DEFAULT 'pending',
    -- Which integration carried it, when one did. NULL for manual and not_applicable.
    integration_id      UUID         REFERENCES integration_configurations(id) ON DELETE SET NULL,
    -- The identifier the far system gave back. This is the ONLY evidence that a posting
    -- really landed, which is why a posting cannot be 'posted' without one (see the CHECK).
    external_ref        VARCHAR(200),
    -- For manual_required: what a human has to be told, and whether they were.
    instruction         TEXT,
    acknowledged_by     UUID         REFERENCES users(id) ON DELETE SET NULL,
    acknowledged_at     TIMESTAMPTZ,
    attempts            INTEGER NOT NULL DEFAULT 0,
    last_error          TEXT,
    posted_at           TIMESTAMPTZ,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- A POSTING CANNOT CLAIM SUCCESS WITHOUT EVIDENCE. Enforced in the schema rather than in
    -- the service, because this is the exact lie the ledger exists to prevent and a
    -- constraint holds against every writer, including the ones nobody has written yet.
    CONSTRAINT ck_posted_has_evidence CHECK (
        status <> 'posted' OR (external_ref IS NOT NULL AND posted_at IS NOT NULL)
    ),
    -- And a manual posting cannot exist without something to tell the human.
    CONSTRAINT ck_manual_has_instruction CHECK (
        status <> 'manual_required' OR instruction IS NOT NULL
    ),
    CONSTRAINT ck_posting_status CHECK (
        status IN ('pending', 'posted', 'failed', 'manual_required', 'not_applicable')
    )
);
-- One posting per (event, target). A retry updates the row; it does not add a second claim.
CREATE UNIQUE INDEX IF NOT EXISTS ux_posting_event_target
    ON system_of_record_postings (event_type, event_id, target_system);
CREATE INDEX IF NOT EXISTS ix_posting_outstanding
    ON system_of_record_postings (organization_id, status)
    WHERE status IN ('pending', 'failed', 'manual_required');

-- ------------------------------------------------------------------------------------ RLS
DO $$
DECLARE t TEXT;
BEGIN
    FOREACH t IN ARRAY ARRAY[
        'part_issues', 'labor_entries', 'quality_events', 'downtime_events',
        'system_of_record_postings'
    ] LOOP
        EXECUTE format('ALTER TABLE %I ENABLE ROW LEVEL SECURITY', t);
        EXECUTE format('ALTER TABLE %I FORCE ROW LEVEL SECURITY', t);
        EXECUTE format('DROP POLICY IF EXISTS %I ON %I', t || '_tenant_isolation', t);
        EXECUTE format(
            'CREATE POLICY %I ON %I USING '
            '(organization_id = NULLIF(current_setting(''app.current_org_id'', true), '''')::uuid)',
            t || '_tenant_isolation', t
        );
    END LOOP;
END $$;

COMMIT;
