# Runbook: suspected tenant-isolation breach

One organisation may have seen another's data. **This is a SEV-1 the moment it is suspected**,
not once it is confirmed — the statutory clocks in
[incident-response-plan.md](incident-response-plan.md) start at *discovery*, and GDPR Art. 33
gives 72 hours from there.

There is no alert for this. It arrives as a customer saying "why can I see an asset that isn't
ours", or as an engineer noticing a query returning too many rows. Treat both identically.

## Do not start by looking at the code

The instinct is to read the endpoint. Start instead by establishing **whether the isolation
mechanism was on at all**, because the failure modes are ranked and the first one is by far the
most common.

### 1. Is the production role bypassing RLS entirely?

```sql
SELECT rolname, rolsuper, rolbypassrls FROM pg_roles WHERE rolname = current_user;
```

If `rolbypassrls` or `rolsuper` is true, **every RLS policy in the schema is decorative** and
the tenant model rests entirely on application-level scoping. This is a known open question —
`docs/engineering/api-contract-gate.md` records it as unanswered — and it is the single
highest-value thing to check first, because it changes what every subsequent step means.

### 2. Was the GUC set on the session that ran the query?

Tenancy is enforced by `app.current_org_id`, set per request by `get_tenant_db`
(`app/core/tenant.py`). A session that uses a plain `get_db` has **no GUC**, so:

- on a `FORCE ROW LEVEL SECURITY` table (30 of them) it reads **zero rows and raises no
  error**;
- on a table with RLS but not FORCE, and a role that owns it, it reads **everything**.

Both are silent. The second is the breach.

`backend/tests/test_tenant_session_guard.py` keeps the register of routes that legitimately
use `get_db` on an RLS table — `auth.py` has 7, deliberately, because login cannot know the
tenant until it has authenticated. **That file's header records the exact incident this
runbook exists for**: the first MFA check read `user_mfa` (FORCE RLS) on an untenanted
session, matched zero rows for every user, and login stopped enforcing the second factor while
returning 200. Zero rows read as "no MFA configured".

So: when a table returns nothing it should have returned, suspect the GUC before the data.

### 3. Which rows, and who read them

```sql
-- Rows visible without a tenant context on the table in question:
SET LOCAL app.current_org_id = '';
SELECT count(*) FROM <table>;

-- Whether the policy exists and is FORCEd:
SELECT relname, relrowsecurity, relforcerowsecurity
FROM pg_class WHERE relname = '<table>';
SELECT * FROM pg_policies WHERE tablename = '<table>';
```

## Establishing scope — what was actually read

This is the part the notification deadline turns on, and it is where the audit log earns its
existence.

```sql
SELECT organization_id, user_id, action, resource_type, resource_id, created_at
FROM audit_logs
WHERE created_at > now() - interval '30 days'
ORDER BY created_at DESC;
```

**Two limits on that query, both important, and both better known now than at hour 70.**

The audit middleware captures **18 hardcoded route templates out of ~546 operations**
(OG-AU-001). So the absence of an audit row is *not* evidence that nothing was read. Say so in
the incident record rather than implying coverage the log does not have.

And check the chain is intact before quoting it as evidence:

```
GET /api/v1/audit/verify
```

Rows written before migration 069 are reported as `unverifiable-by-construction` and counted
separately — that is not tampering, it is an algorithm change, and the endpoint distinguishes
them. Do not read `hash_version = 1` rows as evidence of interference.

## Containment

Ranked by how much they cost, cheapest first:

1. **Revoke the affected sessions.** Rotating `JWT_SECRET_KEY` invalidates *every* live session
   platform-wide — a total logout, but instant and complete. There is no `kid` or key ring
   (OG-SC-005), so partial revocation is not available.
2. **Disable the specific route** if the exposure is one endpoint. Faster than a rollback and
   far more targeted.
3. **Scale the backend to zero** only if data is actively flowing to the wrong tenant and you
   cannot narrow it. This is a full outage, and it is the right call when the alternative is
   continuing to leak.

**Do not delete the audit rows**, and do not "clean up" the data the wrong tenant saw. Both
destroy the evidence the 72-hour filing needs, and deleting audit rows breaks the per-tenant
hash chain — see [storage-exhaustion.md](storage-exhaustion.md).

## Verification

A breach is closed when you can demonstrate isolation, not when the report stops:

```bash
pytest backend/tests/test_tenant_isolation_rls.py \
       backend/tests/test_a_tenant_reference_is_refused_realdb.py \
       backend/tests/test_tenant_session_guard.py -v
```

If the cause was a `get_db` on an RLS table, the fix is `get_tenant_db` **and** an entry
removed from that register — not one or the other. If the cause was `rolbypassrls`, no
application test can prove the fix; re-run the role query above.

## After the incident

- The 72-hour clock is real and starts at discovery. Who files, and where, is
  🔲 **unassigned** — see [incident-response-plan.md](incident-response-plan.md) §7.
- If the audit log could not establish scope, that is the finding, and it is OG-AU-001's
  remediation: 18 of 546 operations is not coverage.
- Add the shape to `test_tenant_isolation_api.py`. Every entry in it is there because
  something like this happened once.
