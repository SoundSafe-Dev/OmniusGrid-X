-- 047_alarm_rules.sql
--
-- Server-side alarm rules (FS-218).
--
-- WHY: alarm severity was whatever the edge agent sent —
-- `severity=data.get('severity', 'medium')` in app/workers/ingestion.py — and
-- alarms only ever existed as discrete events the edge chose to emit. NOTHING
-- evaluated telemetry, so an operator could not express "alert when temperature
-- exceeds 80 for 5 minutes". This table is where that intent lives; FS-219
-- evaluates it in the ingestion path.
--
-- TENANCY IS BUILT IN, NOT ADDED LATER. `alarms` shipped without an
-- organization_id or an RLS policy and needed migration 046 to retrofit both
-- after five endpoints had already leaked across tenants. A new tenant-scoped
-- table gets the column, the FK, the index and FORCE RLS in its first migration
-- so that class cannot repeat here.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + guarded policy creation.

CREATE TABLE IF NOT EXISTS alarm_rules (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    name VARCHAR(255) NOT NULL,
    description TEXT,

    -- What to watch. metric_name matches telemetry.metric_name.
    metric_name VARCHAR(255) NOT NULL,
    comparator VARCHAR(4) NOT NULL,
    threshold DOUBLE PRECISION NOT NULL,

    -- How long the breach must persist before the alarm is raised. 0 = fire on
    -- the first breaching sample. This is what makes a rule express "for 5 min"
    -- rather than "right now", and it is why evaluation needs per-(rule, asset)
    -- state rather than being a pure function of one reading.
    duration_seconds INTEGER NOT NULL DEFAULT 0,

    -- Clear band. The value must return past `threshold` by this much before the
    -- breach is considered over, so a metric sitting exactly on the threshold
    -- does not flap between firing and clearing on sensor noise. Expressed in
    -- the metric's own units.
    hysteresis DOUBLE PRECISION NOT NULL DEFAULT 0,

    severity VARCHAR(20) NOT NULL,
    -- Code stamped onto alarms this rule raises, so they can be grouped and so a
    -- rule's alarms are distinguishable from edge-emitted ones.
    alarm_code VARCHAR(100) NOT NULL,
    message_template TEXT,

    -- Targeting, most specific wins. All three NULL = every asset in the org.
    -- Kept as nullable columns rather than a selector JSON blob so the FKs (and
    -- therefore the cascade behaviour) are real.
    asset_id UUID REFERENCES assets(id) ON DELETE CASCADE,
    asset_type_id UUID REFERENCES asset_types(id) ON DELETE CASCADE,
    workcell_id UUID REFERENCES workcells(id) ON DELETE CASCADE,

    is_enabled BOOLEAN NOT NULL DEFAULT TRUE,

    created_by UUID REFERENCES users(id) ON DELETE SET NULL,
    -- Server defaults per migration 044: without them a raw-SQL insert writes
    -- NULL and the row disappears from every time-ordered query.
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    -- Comparators are a closed set; a typo would otherwise create a rule that
    -- silently never matches.
    CONSTRAINT ck_alarm_rules_comparator
        CHECK (comparator IN ('gt', 'gte', 'lt', 'lte', 'eq', 'ne')),
    -- Same severity vocabulary as `alarms`, so a rule cannot raise an alarm the
    -- alarms table would reject.
    CONSTRAINT ck_alarm_rules_severity
        CHECK (severity IN ('critical', 'high', 'medium', 'low', 'info')),
    CONSTRAINT ck_alarm_rules_duration_nonnegative
        CHECK (duration_seconds >= 0),
    CONSTRAINT ck_alarm_rules_hysteresis_nonnegative
        CHECK (hysteresis >= 0)
);

-- The evaluator's hot path: for one org, every enabled rule watching one metric.
-- Ingestion runs this per telemetry message, so it must not table-scan.
CREATE INDEX IF NOT EXISTS idx_alarm_rules_org_metric_enabled
    ON alarm_rules (organization_id, metric_name, is_enabled);

-- Management list view.
CREATE INDEX IF NOT EXISTS idx_alarm_rules_org_created
    ON alarm_rules (organization_id, created_at DESC);

-- ---------------------------------------------------------------------------
-- RLS from the start.
-- ---------------------------------------------------------------------------
-- FORCE as well as ENABLE: without FORCE the table owner (the application role
-- in most deployments) bypasses the policy, which is what made the `alarms` gap
-- invisible for so long.
DO $$
BEGIN
  IF to_regclass('public.alarm_rules') IS NOT NULL THEN
    ALTER TABLE alarm_rules ENABLE ROW LEVEL SECURITY;
    ALTER TABLE alarm_rules FORCE  ROW LEVEL SECURITY;
    DROP POLICY IF EXISTS tenant_isolation ON alarm_rules;
    CREATE POLICY tenant_isolation ON alarm_rules
      FOR ALL
      USING      (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid)
      WITH CHECK (organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid);
  END IF;
END $$;
