-- 061_insight_activations.sql
--
-- Turn a correlation-AI recommendation into work that actually happened (FS-406).
--
-- WHAT WAS MISSING. An analysis session ends with a list under "Recommended Actions", and
-- in the UI each line carries a green tick. Nothing behind that tick had run. The single
-- affordance for acting on a recommendation was an "Auto-integrate" checkbox that fired a
-- background job whose result the user never saw: it could create nothing at all and the
-- screen would look identical. So the most load-bearing claim the product makes — that an
-- insight becomes a dispatched task in the Kanban and in the ERP — was the least evidenced
-- thing in the system.
--
-- THIS TABLE IS THAT EVIDENCE. One row per recommendation a person chose to act on, holding
-- the link to the Kanban task it created, and joined to `system_of_record_postings` (060)
-- for every external system the action has to reach. Activation therefore reuses the same
-- ledger a part issue uses, deliberately: a dispatch to an ERP is the same kind of claim
-- whether a machinist or an analysis session started it, and it deserves the same proof.
--
-- THREE VERBS, KEPT SEPARATE, BECAUSE THEY ARE THREE DIFFERENT FACTS.
--
--   issue      a person activated this recommendation; a task exists and the postings the
--              action needs have been created. NOTHING IS DONE YET.
--   confirm    the work is finished AND every posting carries evidence — an external
--              reference from the far system, or a human's acknowledgement that they did
--              the analog step. A confirmation records the snapshot it was granted on.
--   reject     a person decided not to act, WITH a reason. Rejection is data: a
--              recommendation that keeps being rejected is a bad recommendation, and that
--              is only learnable if the reason is stored rather than the row deleted.
--
-- WHY CONFIRMATION CANNOT BE A BOOLEAN SOMEONE SETS. `validation` holds what was true at the
-- moment of confirming: the task status, and the status of each posting with its reference.
-- The service refuses to confirm while any posting still lacks evidence, and the CHECK below
-- refuses a confirmed row without a snapshot, so "confirmed" can always be re-read as a
-- claim about specific systems rather than as somebody having clicked a button.
--
-- ONE ACTIVATION PER RECOMMENDATION. `action_fingerprint` is derived from the message and
-- the action's position and text, and is unique per organisation. Double-clicking Activate,
-- or a retry after a timeout, updates nothing and creates nothing — without this, a flaky
-- connection turns one recommendation into two work orders and two ERP postings, which is
-- the failure mode that makes operators stop trusting the button.

BEGIN;

CREATE TABLE IF NOT EXISTS insight_activations (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id     UUID        NOT NULL REFERENCES organizations(id) ON DELETE CASCADE,

    -- Where the recommendation came from. Nullable because an insight can also arrive from
    -- a correlation alert or a strategic recommendation, and losing the activation because
    -- the session was archived would destroy the audit trail for work that really happened.
    session_id          UUID        REFERENCES analysis_sessions(id) ON DELETE SET NULL,
    message_id          UUID        REFERENCES session_messages(id) ON DELETE SET NULL,
    -- analysis_session | correlation_alert | strategic_recommendation | manual
    source              VARCHAR(40) NOT NULL DEFAULT 'analysis_session',
    -- Position within that message's `actions` array. Kept so the UI can mark the exact
    -- line as activated instead of guessing by title.
    action_index        INTEGER,
    -- sha256 over (source, session, message, index, title). See the header.
    action_fingerprint  VARCHAR(64) NOT NULL,

    title               VARCHAR(500) NOT NULL,
    description         TEXT,
    -- The correlation domain, e.g. MAINTENANCE, QUALITY_CONTROL. Drives which systems of
    -- record the activation has to reach.
    domain              VARCHAR(100),
    priority            VARCHAR(20) NOT NULL DEFAULT 'medium',

    -- The Kanban task this became. NULL only if task creation failed, which is a state the
    -- API reports rather than hides.
    task_id             UUID        REFERENCES tasks(id) ON DELETE SET NULL,

    -- issued | confirmed | rejected | cancelled
    status              VARCHAR(20) NOT NULL DEFAULT 'issued',

    issued_by           UUID        REFERENCES users(id) ON DELETE SET NULL,
    issued_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    confirmed_by        UUID        REFERENCES users(id) ON DELETE SET NULL,
    confirmed_at        TIMESTAMPTZ,
    rejected_by         UUID        REFERENCES users(id) ON DELETE SET NULL,
    rejected_at         TIMESTAMPTZ,
    rejection_reason    TEXT,

    -- The snapshot confirmation was granted on. Not a summary — the actual per-posting
    -- statuses and references, so a later reader can check the confirmation instead of
    -- trusting it.
    validation          JSONB,
    meta_data           JSONB       NOT NULL DEFAULT '{}'::jsonb,

    created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),

    CONSTRAINT ck_activation_status CHECK (
        status IN ('issued', 'confirmed', 'rejected', 'cancelled')
    ),
    -- A confirmation without its evidence snapshot is just an assertion.
    CONSTRAINT ck_confirmed_has_validation CHECK (
        status <> 'confirmed' OR (confirmed_at IS NOT NULL AND validation IS NOT NULL)
    ),
    -- A rejection without a reason teaches nobody anything.
    CONSTRAINT ck_rejected_has_reason CHECK (
        status <> 'rejected' OR (rejected_at IS NOT NULL AND rejection_reason IS NOT NULL)
    )
);

-- The idempotency guarantee. Per organisation, because two tenants can legitimately act on
-- textually identical recommendations.
CREATE UNIQUE INDEX IF NOT EXISTS ux_activation_fingerprint
    ON insight_activations (organization_id, action_fingerprint);
CREATE INDEX IF NOT EXISTS ix_activation_session
    ON insight_activations (session_id) WHERE session_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_activation_outstanding
    ON insight_activations (organization_id, status) WHERE status = 'issued';

-- ------------------------------------------------------------------------------------ RLS
ALTER TABLE insight_activations ENABLE ROW LEVEL SECURITY;
ALTER TABLE insight_activations FORCE ROW LEVEL SECURITY;
DROP POLICY IF EXISTS insight_activations_tenant_isolation ON insight_activations;
CREATE POLICY insight_activations_tenant_isolation ON insight_activations USING (
    organization_id = NULLIF(current_setting('app.current_org_id', true), '')::uuid
);

COMMIT;
