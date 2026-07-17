# `hridyansh/integration` PR Split Plan

## Summary

`hridyansh/integration` is too large to review safely as one PR. Treat the
current branch as the staging/source branch and split it into stacked review
branches. Each branch should compile and run its focused tests independently.

Do not merge the full integration branch directly.

## Recommended Stack

1. **Tenant/RBAC Core**
   - Tenant context/dependency changes.
   - Tenant isolation middleware and tests.
   - RBAC/rate-limit middleware.
   - Auth/user-context hardening.
   - Security docs and focused backend tests.
   - Reason: this creates the base security contract for the remaining work.

2. **SSO/Tenant Provisioning**
   - Keycloak/SSO config.
   - Token-to-tenant mapping.
   - JIT user provisioning.
   - SSO tests.
   - Stack after Tenant/RBAC Core because it depends on tenant/user-context
     behavior being settled.

3. **Compliance Reports**
   - Compliance report API/service/worker/scheduler.
   - Compliance report migrations.
   - Signed download links and email delivery.
   - Compliance report tests and runbooks.
   - Stack after tenant/SSO primitives so report access is tenant-safe.

4. **Exports**
   - Export API.
   - Export processor/delivery.
   - Bulk processor paths used by exports.
   - Export templates and scheduled deliveries.
   - Export tests.
   - Keep separate from Compliance Reports unless a very small shared signed URL
     base PR is required.

5. **Error Triage**
   - Error tracking middleware/service/API.
   - Error Triage frontend/admin page.
   - Prometheus alert updates.
   - Error triage runbook and tests.
   - Reason: cohesive observability feature that should review independently.

6. **Profiling + Operational Middleware**
   - Profiling middleware.
   - WebSocket fallback/polling adjustments.
   - Feature flags.
   - Operational tests.
   - Reason: operational behavior can be reviewed without mixing product APIs.

7. **Edge Agent Resilience/Telemetry**
   - Edge-agent resilience primitives.
   - Collector retry/backoff behavior.
   - Metrics additions.
   - Docker/requirements updates.
   - Edge-focused tests.
   - Reason: edge runtime changes should stay isolated from backend API review.

8. **Database/Migrations Cleanup**
   - Final migration ordering.
   - `backend/app/db/models.py` drift reconciliation.
   - Migration documentation/runbooks.
   - Compatibility fixes found during splitting.
   - Prefer per-feature migrations in earlier PRs; reserve this PR for
     cross-feature cleanup only.

## Split Rules

- Keep generated files out of every PR (`.DS_Store`, `__pycache__`,
  `node_modules`, Vite caches, and similar local artifacts).
- Each PR should have a short, reviewable diff and focused tests.
- Preserve stack order where a later feature depends on tenant/RBAC or schema
  behavior from an earlier PR.
- Do not mix frontend, backend API, migrations, and edge-agent runtime changes
  unless they are necessary for one cohesive feature.
- If a PR introduces a migration, include either a migration test or a clear
  upgrade-path note.

## Current Package Rename Verification

Branch checked: `hridyansh/package-renaming-fix`.

Verification command:

```bash
git grep -n "omniusgrid_agent" hridyansh/package-renaming-fix -- edge-agent collectors
```

Result: no matches. The requested `opsgrid_agent` package rename verification is
clean for `edge-agent/` and `collectors/`.
