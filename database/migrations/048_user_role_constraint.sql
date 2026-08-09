-- 048_user_role_constraint.sql
--
-- Constrain users.role to the application's actual vocabulary (FS-222).
--
-- WHY: `role` was VARCHAR(50) with no constraint and a Python-side default of
-- 'operator'. A typo ('Admin', 'opperator', a stale value from an SSO mapping)
-- stored happily and then matched none of the require_* dependencies, so the user
-- silently had NO permissions. The mistake surfaced later, as "this account can't
-- do anything", instead of at the point it was made.
--
-- Fail-closed is the right default for an authorization column, but only if the
-- bad value cannot be written in the first place. That is what this adds.
--
-- The vocabulary is app/core/roles.py; test_role_vocabulary_parity.py asserts the
-- two agree so this constraint cannot drift from the code that reads it.
--
-- Idempotent: guarded on the constraint not already existing.

-- ---------------------------------------------------------------------------
-- 1. Repair any existing out-of-vocabulary rows BEFORE constraining.
-- ---------------------------------------------------------------------------
-- Case-only mistakes are recoverable without guessing intent, so normalise them.
-- Anything else is NOT silently rewritten: downgrading an unrecognised role to
-- 'viewer' could revoke access someone depends on, and upgrading it could grant
-- access they never had. Those rows are reported and the migration stops.
DO $$
DECLARE
  bad_count INTEGER;
  bad_sample TEXT;
BEGIN
  IF to_regclass('public.users') IS NULL THEN
    RETURN;
  END IF;

  UPDATE users
     SET role = lower(role)
   WHERE role IS NOT NULL
     AND role <> lower(role)
     AND lower(role) IN ('viewer', 'operator', 'admin');

  -- A NULL role is as unusable as a typo'd one: it matches no dependency. The
  -- column has a Python-side default but no DB default, so a raw INSERT could
  -- leave it NULL. Treat those as the documented default rather than blocking.
  UPDATE users SET role = 'operator' WHERE role IS NULL;

  SELECT count(*), min(role) INTO bad_count, bad_sample
    FROM users
   WHERE role NOT IN ('viewer', 'operator', 'admin');

  IF bad_count > 0 THEN
    RAISE EXCEPTION
      'users.role holds % row(s) outside the vocabulary (e.g. %). Decide each one '
      'deliberately — this migration will not guess whether to grant or revoke '
      'access. Update them, then re-run.',
      bad_count, bad_sample;
  END IF;
END $$;

-- ---------------------------------------------------------------------------
-- 2. The constraint, plus a real default so a raw INSERT cannot omit it.
-- ---------------------------------------------------------------------------
DO $$
BEGIN
  IF to_regclass('public.users') IS NOT NULL
     AND NOT EXISTS (
       SELECT 1 FROM pg_constraint WHERE conname = 'ck_users_role'
     )
  THEN
    ALTER TABLE users
      ADD CONSTRAINT ck_users_role
      CHECK (role IN ('viewer', 'operator', 'admin'));
  END IF;
END $$;

-- Mirrors the model default. Without it a raw INSERT (a fixture, a script, an SSO
-- provisioning path) writes NULL and the account is unusable — the same class of
-- gap migration 044 closed for created_at/updated_at.
ALTER TABLE users ALTER COLUMN role SET DEFAULT 'operator';
ALTER TABLE users ALTER COLUMN role SET NOT NULL;
