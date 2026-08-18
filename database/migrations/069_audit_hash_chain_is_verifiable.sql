-- Make the audit hash chain verifiable (FS-743).
--
-- THE DEFECT. Tamper-evidence was written but could never be checked. Migration 009's
-- trigger computed:
--
--     calculate_audit_hash(previous_hash, to_jsonb(NEW))
--
-- `to_jsonb(NEW)` is the WHOLE row -- including `hash_chain` itself. At BEFORE INSERT the
-- column holds whatever the writer set ('pending', or ''), and after the trigger it holds
-- the digest. So the hashed input contains a value that the stored row no longer has, and
-- **no verifier can ever reproduce it** -- not the API, not another SQL query, not a
-- forensic tool. `GET /api/v1/audit/verify` recomputed over a sorted 10-field subset in
-- Python, which is a second, different algorithm; it reported every row as tampered on any
-- non-empty table, and no test asserted otherwise.
--
-- An integrity control that always reports a violation is indistinguishable from one that
-- never reports anything: both are ignored within a week.
--
-- THE FIX, in two parts.
--
-- 1. Exclude the digest from its own input: `to_jsonb(NEW) - 'hash_chain'`. The stored row
--    can then be re-hashed identically at any later time, which is the entire property the
--    control needs.
--
-- 2. Chain PER ORGANISATION, explicitly. The old trigger's "previous hash" SELECT runs
--    under the caller's row-level security, so it already saw only rows visible to that
--    tenant -- a per-visible-set chain by accident, which is unverifiable because the
--    visible set at verify time need not equal the one at insert time. Making it
--    `WHERE organization_id IS NOT DISTINCT FROM NEW.organization_id` states the intent:
--    each tenant owns a chain they can verify for themselves, under the same RLS that
--    protects their rows. The alternative -- one global chain via SECURITY DEFINER -- would
--    be unverifiable by any tenant-scoped reader, which is every reader this API has.
--
-- WHY A VERSION COLUMN. Rows written before this migration were hashed by the old
-- algorithm. They cannot be verified by the new one, and calling them "tampered" would be
-- false: nothing altered them, they were never verifiable. `hash_version` lets the verifier
-- say the true thing -- rows at version 1 are reported as unverifiable-by-construction and
-- counted separately, rather than being folded into a violation count they did not earn.

ALTER TABLE audit_logs
    ADD COLUMN IF NOT EXISTS hash_version SMALLINT NOT NULL DEFAULT 1;

-- New rows are version 2. Existing rows keep the 1 the DEFAULT gave them above.
ALTER TABLE audit_logs
    ALTER COLUMN hash_version SET DEFAULT 2;

COMMENT ON COLUMN audit_logs.hash_version IS
    'Hash-chain algorithm version. 1 = pre-FS-743, hashed to_jsonb(NEW) including '
    'hash_chain itself and therefore unverifiable by construction. 2 = hashes '
    'to_jsonb(NEW) - ''hash_chain'', chained per organization_id.';

-- The digest function is unchanged and still takes (previous_hash, payload); only the
-- payload the trigger hands it changes. Kept as its own function so the verifier can call
-- exactly the same code path rather than reimplementing it -- the reimplementation is what
-- broke last time.
CREATE OR REPLACE FUNCTION calculate_audit_hash(
    p_previous_hash VARCHAR,
    p_log_data JSONB
) RETURNS VARCHAR AS $$
DECLARE
    combined TEXT;
BEGIN
    combined := COALESCE(p_previous_hash, '') || jsonb_pretty(p_log_data);
    RETURN encode(digest(combined::bytea, 'sha256'), 'hex');
END;
$$ LANGUAGE plpgsql;

CREATE OR REPLACE FUNCTION audit_log_hash_chain_trigger()
RETURNS TRIGGER AS $$
DECLARE
    previous_hash VARCHAR;
BEGIN
    -- The immediately preceding row IN THE SAME ORGANISATION'S CHAIN.
    -- `IS NOT DISTINCT FROM` rather than `=` so the untenanted rows (organization_id is
    -- nullable -- ON DELETE SET NULL) form their own chain instead of silently matching
    -- nothing and every one of them starting a fresh chain from ''.
    SELECT hash_chain INTO previous_hash
    FROM audit_logs
    WHERE organization_id IS NOT DISTINCT FROM NEW.organization_id
      AND hash_version = 2
    ORDER BY timestamp DESC, id DESC
    LIMIT 1;

    NEW.hash_version = 2;
    NEW.hash_chain = calculate_audit_hash(previous_hash, to_jsonb(NEW) - 'hash_chain');

    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_hash_chain_trigger ON audit_logs;
CREATE TRIGGER audit_log_hash_chain_trigger
    BEFORE INSERT ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION audit_log_hash_chain_trigger();

-- Verification, expressed once, in SQL, over the SAME function the trigger uses.
--
-- The Python endpoint calls this instead of recomputing the digest itself. That is the
-- whole lesson of the defect: two implementations of one hash drifted, and nothing noticed
-- because the only thing that would have noticed was a test nobody wrote.
--
-- THE KNOWN FRAGILITY, stated rather than discovered later. `to_jsonb(a)` covers EVERY
-- column, which is what tamper-evidence wants -- a column added tomorrow is integrity-
-- protected the day it exists, with no list to remember to update. The cost is that adding
-- a column changes the payload of rows already written (they gain the key with a NULL), so
-- their stored digests stop reproducing. The remedy is to bump `hash_version` to 3 in the
-- same migration that alters the table, which moves the old rows into the same
-- "unverifiable by construction, and honest about it" bucket as version 1 rather than
-- reporting them as tampered. `test_the_audit_chain_survives_its_own_schema.py` fails the
-- build if the column set changes without that bump.
CREATE OR REPLACE FUNCTION verify_audit_hash_chain()
RETURNS TABLE (
    log_id UUID,
    log_timestamp TIMESTAMPTZ,
    expected_hash VARCHAR,
    actual_hash VARCHAR
) AS $$
    WITH chained AS (
        SELECT
            a.id,
            a.timestamp,
            a.hash_chain,
            to_jsonb(a) - 'hash_chain' AS payload,
            LAG(a.hash_chain) OVER (
                PARTITION BY a.organization_id
                ORDER BY a.timestamp, a.id
            ) AS previous_hash
        FROM audit_logs a
        WHERE a.hash_version = 2
    )
    SELECT
        c.id,
        c.timestamp,
        calculate_audit_hash(c.previous_hash, c.payload)::VARCHAR,
        c.hash_chain::VARCHAR
    FROM chained c
    WHERE calculate_audit_hash(c.previous_hash, c.payload) IS DISTINCT FROM c.hash_chain
    ORDER BY c.timestamp, c.id;
$$ LANGUAGE sql STABLE;
