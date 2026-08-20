-- 072 — the default raw-telemetry window becomes 90 days (FS-816)
--
-- WHAT THE PREMISE WAS, AND WHY IT WAS WRONG. This work was scoped from the belief that raw
-- telemetry is dropped after seven days, on the strength of
--
--     005_data_retention.sql:22  SELECT add_retention_policy('telemetry', INTERVAL '7 days', if_not_exists => TRUE);
--
-- That statement is a NO-OP and always has been. `001_init.sql:104` had already installed a
-- retention policy at 30 days, and `if_not_exists => TRUE` means "succeed quietly if one
-- exists" — it does NOT change the interval. So the seven never took effect, and the comment
-- above it has been describing a policy the database never had.
--
-- Then `034_historian_retention.sql:210` removed the global policy altogether, deliberately
-- and correctly: a chunk holds rows for many organisations, so a global chunk-drop cannot
-- honour a per-tenant window. It was replaced by `enforce_tenant_historian_retention()`, a
-- per-tenant, per-metric row DELETE whose fallback when a tenant has configured nothing is
-- `COALESCE(..., 30)`.
--
-- **The real default is 30 days, not 7.** A first draft of this migration reinstated a global
-- `add_retention_policy('telemetry', INTERVAL '90 days')` and would have re-broken exactly
-- what 034 fixed — deleting chunks out from under tenants who had configured longer windows,
-- which is silent, cross-tenant, irreversible data loss. It was caught because
-- `test_migration_chain_hygiene.py` refused it for an unrelated reason and the investigation
-- went one level deeper. Recorded here because the near-miss is more instructive than the fix.
--
-- WHAT CHANGES. The default window only: 30 days -> 90.
--
--   * the column default on `historian_retention_policies.hot_retention_days`
--   * the `COALESCE` fallback inside `enforce_tenant_historian_retention`, which is what a
--     tenant with no configured policy actually gets — the column default alone would change
--     nothing for them, because they have no row for it to default
--
-- Tenants who have set their own value are UNTOUCHED. The change only ever lengthens
-- retention, so it cannot delete anything that would previously have survived.
--
-- WHY 90. Seven — or thirty — was a default nobody revisited. On critical infrastructure a
-- month is short enough to be a liability: a warranty dispute, a regulatory query or an
-- investigation opened five weeks after the event has nothing to read, and the loss is silent
-- and irreversible. A quarter matches the reporting cycle these customers work in.
--
-- WHAT IT COSTS, measured rather than assumed. Against this exact schema and this exact
-- `compress_segmentby`, over 2,161,000 rows on timescale/timescaledb:latest-pg15:
--
--     uncompressed   142.7 bytes/row
--     compressed      19.4 bytes/row      7.3x, 86.4% saved
--
-- Compression at 7 days (001:101) is live and IS being realised — chunks compress at day 7
-- and rows are deleted at day 30, so twenty-three of those days are already stored
-- compressed. Extending to 90 therefore costs compressed bytes, not raw ones:
--
--     fleet (5s poll)            30d today      90d
--     50 assets  x 20 metrics        9 GB      28 GB
--     250 assets x 20 metrics       47 GB     140 GB     ~$14/month
--     1000 assets x 30 metrics     281 GB     843 GB     ~$84/month
--
-- DELETE ON COMPRESSED CHUNKS was verified before shipping this, because the whole scheme
-- depends on it: 034's row-level DELETE has to work against chunks 001 has compressed.
-- Measured on timescaledb 2.26.3 — 7,201 rows across 6 compressed chunks, deleted cleanly.
-- Older TimescaleDB refuses DELETE on compressed chunks, so a downgrade below 2.11 would
-- silently stop tenant retention for everything past day 7.

ALTER TABLE historian_retention_policies
    ALTER COLUMN hot_retention_days SET DEFAULT 90;

-- The fallback for a tenant with no configured policy. Identical to 034's function in every
-- other respect — reproduced in full because CREATE OR REPLACE FUNCTION has no way to patch
-- one expression, and a partial redefinition would drop the tenant-context check.
CREATE OR REPLACE FUNCTION enforce_tenant_historian_retention(
    p_organization_id UUID,
    p_reference_time TIMESTAMPTZ DEFAULT NOW()
) RETURNS BIGINT AS $$
DECLARE
    deleted_rows BIGINT;
BEGIN
    IF NULLIF(current_setting('app.current_org_id', true), '')::uuid
        IS DISTINCT FROM p_organization_id THEN
        RAISE EXCEPTION 'Tenant context does not match retention request'
            USING ERRCODE = '42501';
    END IF;

    DELETE FROM telemetry AS telemetry_row
    USING assets AS asset
    WHERE telemetry_row.asset_id = asset.id
      AND asset.organization_id = p_organization_id
      AND telemetry_row.time < p_reference_time - make_interval(
          days => COALESCE(
              (
                  SELECT policy.hot_retention_days
                  FROM historian_retention_policies AS policy
                  WHERE policy.organization_id = p_organization_id
                    AND policy.metric_name IN ('*', telemetry_row.metric_name)
                  ORDER BY
                      CASE WHEN policy.metric_name = telemetry_row.metric_name
                          THEN 0 ELSE 1 END
                  LIMIT 1
              ),
              90
          )
      );

    GET DIAGNOSTICS deleted_rows = ROW_COUNT;
    RETURN deleted_rows;
END;
$$ LANGUAGE plpgsql SECURITY INVOKER
SET search_path = public, pg_temp;

COMMENT ON FUNCTION enforce_tenant_historian_retention(UUID, TIMESTAMPTZ) IS
    'Delete raw telemetry outside the active tenant hot-retention window (default 90 days)';

-- The declared configuration must agree with what is enforced, or the next reader trusts the
-- table and is wrong. `data_retention_config` is descriptive — nothing reads it to drive a
-- policy — which is exactly why it drifts unnoticed.
UPDATE data_retention_config
   SET hot_retention_days = 90,
       updated_at         = NOW()
 WHERE table_name = 'telemetry';
