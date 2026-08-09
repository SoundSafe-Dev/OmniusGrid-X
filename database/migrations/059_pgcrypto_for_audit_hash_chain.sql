-- 059: create the pgcrypto extension the audit hash chain has always needed.
--
-- THE AUDIT TRAIL RECORDED NOTHING on any database built from these migrations.
--
-- 009_audit_logs.sql installs a trigger on every INSERT into audit_logs which calls
-- calculate_audit_hash(), and that function's body is:
--
--     RETURN encode(digest(combined::bytea, 'sha256'), 'hex');
--
-- digest() comes from pgcrypto. No migration ever created the extension, so the
-- trigger raised on every insert:
--
--     asyncpg.exceptions.UndefinedFunctionError:
--     function digest(bytea, unknown) does not exist
--
-- and app/services/audit.py catches it deliberately — "never fail the audited
-- operation" — logs `audit_log_write_failed`, and lets the request through. So every
-- audited action succeeded, every audit row was rejected, and the only trace was an
-- ERROR log line nobody was reading. Verified against a freshly migrated database: a
-- INSERT into audit_logs fails and `SELECT count(*)` returns 0.
--
-- WHY NOBODY NOTICED: tests/conftest.py:91 runs
-- `CREATE EXTENSION IF NOT EXISTS pgcrypto;` when it builds a test container. The
-- real-DB suite therefore had a working audit trail while a real deployment did not,
-- which is the exact shape of a test harness compensating for a missing migration —
-- the tests were not wrong about the code, they were wrong about the database.
-- tests/test_schema_extensions_come_from_migrations.py now fails if a migration
-- depends on an extension that only conftest creates.
--
-- Idempotent, and safe to apply to a database where audit rows already exist: the
-- trigger computes hash_chain for NEW rows only. Rows written BEFORE this migration
-- do not exist to backfill — they were never inserted.

CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- Prove the dependency is satisfied rather than assuming it. A missing pgcrypto here
-- is better as a failed migration than as an audit trail that quietly discards rows.
DO $$
BEGIN
    PERFORM encode(digest('migration-059-probe'::bytea, 'sha256'), 'hex');
EXCEPTION WHEN undefined_function THEN
    RAISE EXCEPTION 'pgcrypto is not usable after CREATE EXTENSION; audit_logs '
                    'inserts will fail (009_audit_logs.sql calls digest())';
END $$;
