-- Migration 028: Durable command dispatch and acknowledgement state

BEGIN;

-- Keep the production table aligned with app.db.models.Command. Some of these
-- columns already exist in ORM-created development databases.
ALTER TABLE commands
    ADD COLUMN IF NOT EXISTS priority VARCHAR(20) NOT NULL DEFAULT 'normal',
    ADD COLUMN IF NOT EXISTS completed_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS error_message TEXT,
    ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

-- Dispatch ownership is represented by a row lock, while these fields make
-- retry and timeout decisions reconstructable after any process restart.
ALTER TABLE commands
    ADD COLUMN IF NOT EXISTS timeout_seconds INTEGER NOT NULL DEFAULT 60,
    ADD COLUMN IF NOT EXISTS dispatch_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS next_dispatch_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    ADD COLUMN IF NOT EXISTS dispatched_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS deadline_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS last_dispatch_error TEXT;

UPDATE commands
SET next_dispatch_at = COALESCE(next_dispatch_at, issued_at, NOW())
WHERE status = 'pending';

-- Existing executing rows predate durable deadlines. Give them a bounded
-- acknowledgement window so deployment of this migration cannot strand them.
UPDATE commands
SET dispatched_at = COALESCE(dispatched_at, executed_at, issued_at, NOW()),
    deadline_at = COALESCE(
        deadline_at,
        COALESCE(dispatched_at, executed_at, issued_at, NOW())
            + make_interval(secs => timeout_seconds)
    )
WHERE status = 'executing';

DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_commands_timeout_seconds_positive'
          AND conrelid = 'commands'::regclass
    ) THEN
        ALTER TABLE commands
            ADD CONSTRAINT ck_commands_timeout_seconds_positive
            CHECK (timeout_seconds > 0);
    END IF;

    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_commands_dispatch_attempts_nonnegative'
          AND conrelid = 'commands'::regclass
    ) THEN
        ALTER TABLE commands
            ADD CONSTRAINT ck_commands_dispatch_attempts_nonnegative
            CHECK (dispatch_attempts >= 0);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_commands_dispatch_ready
    ON commands (organization_id, next_dispatch_at, issued_at)
    WHERE status = 'pending';

CREATE INDEX IF NOT EXISTS idx_commands_ack_deadline
    ON commands (organization_id, deadline_at)
    WHERE status = 'executing' AND deadline_at IS NOT NULL;

COMMIT;
