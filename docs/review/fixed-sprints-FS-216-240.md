# Next 25 fixed-sprints — FS-216..240 (Hamad's lane)

Branch: `hamad/converged-pre-main`. Written 2026-07-24. Sprint letters **AN..AR**.
Mix: **product depth first**, ERP integrity in-lane. Other lanes PARKED.

## Context

FS-191..215 landed the dashboard fix + rebuild, the `get_db`→`get_tenant_db` sweep,
migrations 044/045, the tenant-isolation suite on real Postgres, Redis, the worker
health/metrics endpoint and its observability half. `main` is promoted and
tree-identical to converged on both remotes.

Baselines: 120 backend test files, 32 frontend test files vs 33 pages, 48
migrations, 66 mounted routers, 716 backend + 108 frontend tests green.

Planning this batch surfaced one finding that outranks the requested ordering.

---

## FS-216 is a live cross-tenant vulnerability — it goes first

`alarms` is **not** RLS-protected (absent from `011`/`033`) and `Alarm`
(`app/db/models.py:229`) has **no `organization_id`** — tenancy exists only if a
query joins `assets`. So `get_tenant_db`'s GUC does nothing for this table, and
5 of 6 endpoints in `app/api/alarms.py` never join:

| Endpoint | Line | Exposure |
|---|---|---|
| `GET /alarms/` | 35 | lists **every organization's** alarms |
| `GET /alarms/{id}` | 109 | read any org's alarm by id |
| `POST /{id}/acknowledge` | 128 | **mutate** any org's alarm |
| `POST /{id}/clear` | 156 | **mutate** any org's alarm |
| `POST /acknowledge-all` | 180 | **bulk mutate across all orgs** |
| `GET /alarms/active` | 69 | joins `assets` — but only `if organization_id:`, and that is a **client-supplied optional query param** (`:61`). Omit it and the filter disappears. |

This is strictly worse than the dashboard bug. That one leaked *nothing* — RLS
filtered every row and tiles rendered zeros. This one **returns and writes other
tenants' data**, and the one endpoint whose author clearly knew a join was needed
still trusts the client for the org id — the tenant-trust shape already fixed in
yard and dashboard.

Also `acknowledged_by` is never populated: `user_id: UUID = None,  # Would come
from auth dependency` (`:123`, `:176`). Every acknowledgement writes NULL, so the
audit trail of who cleared an alarm is empty — and `acknowledged_by` is the column
already carrying a String(36)-vs-uuid note in the model.

**Sequencing consequence:** the alarm-rules build (FS-218..220) writes to this same
table. Building rules on an unscoped table would multiply the leak, so FS-216/217
are prerequisites, not neighbours.

---

## Sprint AN — Alarms: close the leak, then make them real (FS-216..220)

- **FS-216 — Fix the cross-tenant alarm leak.** Scope all 6 endpoints by
  organization. **Delete the client-supplied `organization_id` param** on
  `/active`; derive from the authenticated user (`get_tenant_org_id`, the
  `exports.py` pattern). Populate `acknowledged_by` from the real auth dependency.
  Test-first on real Postgres: org B must get 404 on org A's alarm id for **read
  and both write paths**, and `acknowledge-all` must not touch org A's rows.
  Extend the FS-201 guard so an RLS-unprotected table queried without an org
  predicate fails CI — the guard currently only catches `get_db` misuse.

- **FS-217 — Migration 049: `alarms.organization_id` + RLS.** Add the column,
  backfill from `assets`, `NOT NULL`, index `(organization_id, occurred_at DESC)`,
  then `ENABLE`/`FORCE ROW LEVEL SECURITY` with the standard
  `app.current_org_id` policy. This makes FS-216 defence-in-depth rather than the
  only barrier. Same treatment for any sibling table the audit finds scoped only
  by `asset_id` (check `operations`, `telemetry`).

- **FS-218 — `AlarmRule` model + CRUD.** No such model exists today. Fields:
  metric, comparator, threshold, duration/hysteresis, severity, target assets (or
  asset-type/workcell selector), enabled, `organization_id` + RLS **from the first
  migration**. `require_operator_or_admin` on writes. Full `response_model`
  coverage (feeds FS-240).

- **FS-219 — Evaluate rules in the ingestion path.** Severity is currently
  whatever the edge sends: `severity=data.get('severity', 'medium')`
  (`workers/ingestion.py:465`). Alarms only exist as discrete events the edge
  emits — **nothing evaluates telemetry**, so "alert when temperature > 80 for
  5 min" is unexpressible. Hook `_process_telemetry` (`:225`), not `_process_alarm`
  — that is the real work. Needs per-(rule, asset) breach-window state that
  survives restarts and does not re-fire on every message; use Redis (deployed in
  FS-196) with a documented degraded mode. Emit `opsgrid_alarm_rule_*` metrics via
  the FS-213 worker endpoint and `beat()` on evaluation.

- **FS-220 — Alarm rules UI + tests.** Management page (list/create/edit/enable),
  wired to the FS-218 API, reusing `Card`/`Badge`/`Tooltip` and `opsgrid-*` tokens
  — no raw Tailwind colours. Page-level `jest-axe`. Makes the FS-193 dashboard
  alarm widgets meaningful for the first time.

## Sprint AO — Users, orgs & roles (FS-221..225)

- **FS-221 — User CRUD.** Only 2 GETs exist on `auth.py` (`:449`, `:474`), which is
  why `pages/admin/AdminPages.tsx:16` hardcodes `USER_MGMT_ENABLED = false`. Add
  create / update / deactivate / role-change, `require_admin` + tenant-scoped.
  Deactivate, never hard-delete (FK integrity + audit).
- **FS-222 — Role model worth enforcing.** `User.role` is a bare
  `String(50), default="operator"` (`db/models.py:637`) with no constraint —
  a typo'd role silently grants nothing. Enumerate roles, add a CHECK constraint,
  centralise the permission matrix, and resolve the **super-admin** role that
  `data_retention.router` is blocked on.
- **FS-223 — Organization management.** Org CRUD + settings, super-admin only.
  Also fix `ORGANIZATION_ID: "dev-org"` hardcoded at
  `base/edge-agent-statefulset.yaml:62,64` (carry-forward FS-184).
- **FS-224 — Enable the admin UI.** Flip `USER_MGMT_ENABLED`, build the user list
  / invite / role-change / deactivate flows against FS-221. Use the accessible
  dialog primitives — no native `confirm()`.
- **FS-225 — Tests + audit trail.** Real-DB tests that a non-admin cannot reach any
  of it and that an admin of org A cannot touch org B's users. Write
  role-changes and deactivations to the audit log — `AuditLogs.tsx` is currently an
  empty shell (FS-181), so give it real rows to show.

## Sprint AP — The deployed-but-dead class (FS-226..230)

- **FS-226 — Tracing is deployed and dead.** `base/otel-collector.yaml` ships the
  collector **and jaeger**, and it is in `base/kustomization.yaml:25`. `base` also
  ships `default-deny-all` with `podSelector: {}` — so both are covered by it and
  **neither has any NetworkPolicy**. Nothing can reach the collector, it cannot
  reach jaeger, the UI is unreachable. The backend deployment does not even set an
  OTLP endpoint, so it exports nothing regardless. Add the policies both
  directions, wire `OTEL_EXPORTER_OTLP_ENDPOINT`, add matrix cases to
  `tests/k8s/netpol-probe.yaml`.
- **FS-227 — A guard for the whole class.** FS-226 is the third instance of "policy
  exists but does not cover it" (after S3 egress and prometheus→worker :9109). Add
  a blocking check: every Deployment/StatefulSet in a namespace carrying
  `default-deny-all` must be selected by at least one ingress **and** one egress
  policy, or CI fails naming the workload. Cheap, and it ends the class.
- **FS-228 — Harden otel + jaeger.** Zero limits, zero `securityContext`, zero
  probes today. Add limits, `allowPrivilegeEscalation: false`, drop ALL caps, and
  probes. As decided in FS-214, do **not** force `runAsNonRoot`/read-only rootfs on
  images that cannot be run here to prove it — record that as explicit debt.
- **FS-229 — The missing alerts (carry-forward FS-213).** TLS/cert expiry,
  auth brute-force, WebSocket drop rate. promtool unit tests for each, and
  mutation-test every guard (removing the fix must fail a test **by name**) — the
  practice that caught a falsely-passing test in the worker alert suite.
- **FS-230 — `overlays/dr`.** `docs/deployment/dr-datacenter-outage.md` is
  unexecutable: no DR manifests exist. Build the overlay so the runbook can be
  followed, even before there is a second cluster to run it in.

## Sprint AQ — ERP & data honesty (FS-231..235)

In-lane per decision. The theme: code that **reports success for work it did not
do** is worse than code that fails, because nothing surfaces it.

- **FS-231 — `erp_correlation_patterns.py:458` lies.** The comment says "This would
  call the correlation registry integration to create the actual registry item";
  the loop then appends `item["item_code"]` to `created_ids` and logs
  `sap_registry_items_created` with a count. **Nothing is created.** Either wire the
  real integration or raise `NotImplementedError` — the one unacceptable option is
  the current success log. Audit the file for siblings.
- **FS-232 — `erp_database_replication.py` no-ops.** Bare `pass` at `:396`, `:416`.
  Make each either functional or loudly unavailable; no silent success.
- **FS-233 — GeoTab is 36 `random.*` calls.** No live client. Most serious part:
  **DOT-regulated HOS numbers are fabricated**. Gate behind an explicit
  `simulated: true` in every response and a startup warning, or implement the
  client. Never present fabricated compliance data as measured.
- **FS-234 — Finish OEE.** FS-192 made it *honest* (`availability_only: true` at
  `dashboard.py:226,241`) but performance and quality are still uncomputed, so
  every OEE number is Availability. Compute both from `Telemetry` (cycle-time vs
  ideal, good-vs-total counts) and drop the flag where genuinely computed.
- **FS-235 — A honesty guard.** A test that fails when a service logs a
  `*_created` / `*_synced` / `*_sent` success event on a path that performed no
  write — pattern-based, seeded with the FS-231..233 cases so they cannot return.

## Sprint AR — Proof & contract (FS-236..240)

- **FS-236 — Flip `api-contract` to blocking (carry-forward FS-188).**
  `quality-gates.yml:41` still says advisory, "ready to flip pending one green
  run", both blockers fixed. ~400 property-checked operations, near-zero cost.
- **FS-237 — Quarantine with an expiry.** `ci-cd.yml:103-108` still ignores 3 files
  and deselects 3 tests. The code is HARSH's lane — do not fix it here — but give
  the quarantine a named marker and a test that **fails once the expiry passes**,
  so it cannot silently become permanent.
- **FS-238 — Test the real client path.** `frontend/src/test/setup.ts:9` does
  `vi.stubEnv('VITE_USE_MOCK','true')`, so **every** unit and Playwright test runs
  against mocks and all **201** `USE_MOCK` references can drift from the real API
  undetected. Add real-mode tests (MSW against the OpenAPI schema), starting with
  the dashboard and the FS-220 alarm-rules page.
- **FS-239 — An e2e that actually authenticates.** `frontend/e2e/smoke.spec.ts` has
  3 tests; they assert the login page *renders* and that a protected route
  redirects — nothing ever logs in. Add: login → dashboard shows populated data →
  asset detail → acknowledge alarm → export. This is the test that would have
  caught both the empty dashboard **and** FS-216.
- **FS-240 — Coverage thresholds + contract polish.** No thresholds exist in either
  suite, and `frontend/vitest.config.ts:25` narrows coverage `include` to 3 paths,
  so the number is decorative. Widen it, set a real baseline both sides, ratchet.
  Push `response_model` past **186/406 (46%)** and adopt the generated SDK, which
  still has **zero importers** (carry-forward FS-187/189).

---

## PARKED — other lanes

- **HARSH:** kanban RLS-write-on-read, `/kanban/rules/premade` 500,
  `/nlp/correlation/intake/{id}` 500, the 3 collection-failing scenario-builder
  files (FS-237 only quarantines them), `correlation_ai_engine.py` (3,594 LOC, zero
  tests, `gemma-4-placeholder`, silent `_simulate_analysis()` fallback),
  `CorrelationAIPane.tsx`, all of `components/kanban/`.
- **Hridyansh:** OTA rollout internals, edge command dispatch transport. **Note the
  overlap:** a `hridyansh/integration-erp` branch exists; FS-231..233 are ERP by
  decision, so coordinate before starting AQ to avoid duplicate work.
- **htreinen:** RAG — `rag_eval` excluded from the default run, the 5 items in
  `docs/rag_ingestion_followups.md`, `/rag/documents` returning a raw SeaweedFS
  error instead of 503. **Also owes a rebase**: `backup/feature/RAG-Compliance-Doc-Pipeline`
  is the last ref still carrying the scrubbed contact email.

## Blocked on a real deployment (not scheduled)

FS-198 CNPG cutover (what makes PITR real), FS-199 load/failover drills and
measured RTO/RPO — `docs/runbooks/rto-rpo-checklist.md` is still `[DURATION]`
placeholders. **FS-200** key rotation is still OUTSTANDING, but its history purge is
no longer blocked on unknowns: the contact-email scrub proved the procedure
(filter-repo + `--force-with-lease` + tree-equality verification against a bundle),
so `HAMAD_IDE.pem` can follow the same steps in one coordinated window.

## Not folded in (tracked)

FS-154 DR script bodies, FS-181 `AuditLogs.tsx` / `UserAppPlaceholder.tsx` (FS-225
gives the former real data), FS-182 edge backoff jitter, FS-185 collector tests.
i18n is scaffolded with **0** `useTranslation` call sites against ~560 hardcoded
strings — a dedicated extraction effort, not a sprint item.

## Sequencing

**FS-216 first and alone** — it is a live cross-tenant read *and write* leak, and
FS-217..220 all touch the same table. FS-217 before FS-218 so the new rules table
inherits a correct tenancy pattern instead of copying a broken one.

AO next: user/org CRUD unblocks the admin persona and gives FS-225's audit log real
rows. AP third — FS-227's guard is what stops the deployed-but-dead class
recurring, so it should land before more infra is added. AQ before AR: fix what the
system misreports before writing tests that pin the current behaviour. AR last, and
FS-239 validates AN + AO end to end.

## Verification

- **FS-216/217:** `cd backend && venv/bin/python -m pytest tests/test_tenant_isolation_api.py tests/test_realdb_endpoint_smoke.py -q` on testcontainers (`TESTCONTAINERS_RYUK_DISABLED=true` under colima). Org B gets 404 on org A's alarm for read **and** both writes; `acknowledge-all` leaves org A's rows untouched; `acknowledged_by` non-NULL.
- **FS-218/219:** rule CRUD covered on real Postgres; an ingestion test that a breach shorter than `duration` does **not** fire and one longer does, exactly once (no re-fire per message).
- **FS-226/227:** `./tests/k8s/simulate-netpols.py` green with the new otel/jaeger rows; the FS-227 guard must **fail** when a policy is deleted (mutation-tested).
- **FS-229:** `promtool check rules` + `promtool test rules`, each new alert mutation-tested.
- **FS-231..235:** the honesty guard fails on the pre-fix code and passes after.
- **FS-236..240:** `api-contract` green twice before flipping; `npx tsc --noEmit && npx vitest run && npm run e2e`.
- **Every sprint:** full backend suite + all k8s gates; push to **both** remotes; no `Co-Authored-By` trailers.
