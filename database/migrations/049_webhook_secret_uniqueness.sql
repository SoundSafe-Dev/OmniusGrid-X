-- 049: every ERP integration must have its own inbound webhook secret.
--
-- WHY THIS IS ENFORCED IN THE DATABASE AND NOT IN THE APPLICATION.
--
-- The inbound webhook path carries only the erp_type:
--
--     POST /api/v1/erp/webhooks/sap
--
-- Nothing in the URL or headers names the organisation, so the route resolves the
-- tenant by trying each active integration of that erp_type and accepting the one
-- whose webhook_secret verifies the request's exact bytes. That is sound -- the
-- signature is the evidence -- but it depends on the secret being UNIQUE. If two
-- integrations share one, both verify and attribution becomes "whichever was tried
-- first": one tenant's business events silently filed against another tenant's
-- integration.
--
-- The application cannot check this. `integration_configurations` is RLS-protected,
-- so a create request running with app.current_org_id set to its own organisation
-- CANNOT SEE another tenant's rows to compare against -- which is exactly the
-- property we normally want. A unique index is enforced at the storage layer
-- regardless of RLS, so it constrains rows the inserting session is not allowed to
-- read. That makes it the only correct place for this rule.
--
-- It also leaks nothing: a collision surfaces as a constraint violation, which the
-- API turns into "this webhook secret is already in use" without revealing whose.
--
-- ON INDEXING THE VALUE ITSELF. The index stores the secret in plaintext, which adds
-- no exposure: it is already stored in plaintext in the `configuration` JSON column.
-- Hashing it would need pgcrypto and would buy nothing while that remains true.
-- Encrypting the column is a separate, larger change; if it happens, this index moves
-- to the ciphertext or to a stored fingerprint.

DO $$
DECLARE
    duplicate_count integer;
    duplicate_detail text;
BEGIN
    IF to_regclass('public.integration_configurations') IS NULL THEN
        RAISE NOTICE '049: integration_configurations does not exist; nothing to do';
        RETURN;
    END IF;

    -- Report collisions BEFORE attempting the index, so a failure is legible.
    -- Creating the index on colliding data raises a bare "could not create unique
    -- index" that names neither the rule nor the rows.
    SELECT count(*), string_agg(DISTINCT left(secret, 6) || '…', ', ')
      INTO duplicate_count, duplicate_detail
      FROM (
        SELECT configuration->>'webhook_secret' AS secret
          FROM integration_configurations
         WHERE integration_type = 'erp'
           AND configuration->>'webhook_secret' IS NOT NULL
           AND configuration->>'webhook_secret' <> ''
         GROUP BY 1
        HAVING count(*) > 1
      ) AS collisions;

    IF COALESCE(duplicate_count, 0) > 0 THEN
        -- Deliberately fatal. Silently skipping would leave the ambiguity in place
        -- while the migration reported success, and a shared secret means webhook
        -- events are already being attributed to an arbitrary tenant.
        RAISE EXCEPTION
            '049: % webhook secret(s) are shared by more than one ERP integration '
            '(prefixes: %). Inbound webhooks for those integrations are attributed '
            'to whichever row is tried first. Give each integration a distinct '
            'configuration.webhook_secret, then re-run this migration.',
            duplicate_count, duplicate_detail;
    END IF;

    -- Partial: only ERP integrations that actually have a secret. Integrations with
    -- no webhook secret configured are legitimate (polling only) and must not
    -- collide with each other on NULL.
    CREATE UNIQUE INDEX IF NOT EXISTS uq_erp_integration_webhook_secret
        ON integration_configurations ((configuration->>'webhook_secret'))
     WHERE integration_type = 'erp'
       AND configuration->>'webhook_secret' IS NOT NULL
       AND configuration->>'webhook_secret' <> '';

    RAISE NOTICE '049: webhook secret uniqueness enforced';
END $$;
