-- 039_user_profile_columns.sql
--
-- Schema-drift fix: the ORM ``User`` model (backend/app/db/models.py) declares
-- department / priorities / user_context / user_goals, but no migration ever
-- added them to the users table (001 created users without them). On a
-- migrations-built database (production + the testcontainers CI schema) every
-- authenticated request 500s, because the auth dependency loads the User row and
-- SELECTs those columns ("column users.department does not exist").
--
-- SQLite dev (create_all) already had them, which is why this stayed latent until
-- the schema was exercised through the real migration chain. Idempotent so it is
-- safe on databases that were adopted via --baseline after a create_all build.

ALTER TABLE users ADD COLUMN IF NOT EXISTS department VARCHAR(100);
ALTER TABLE users ADD COLUMN IF NOT EXISTS priorities JSONB DEFAULT '[]'::jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS user_context JSONB DEFAULT '{}'::jsonb;
ALTER TABLE users ADD COLUMN IF NOT EXISTS user_goals JSONB DEFAULT '[]'::jsonb;
