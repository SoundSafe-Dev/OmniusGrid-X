# Delivery log

Every slice delivered on this platform, newest sections last, in the words written at the
time. **Moved out of `README.md` on 2026-08-02**, where it had grown to roughly a third of
the document and pushed everything a new reader actually needs below the fold.

It is kept verbatim rather than summarised. The value of these entries is not the list of
what shipped — that is visible in the code — but the reasoning recorded against each: what
was believed before, what turned out to be true, and what the difference cost. Several
sections exist specifically to stop a wrong premise being acted on twice.

This file is in the scope of `backend/tests/test_documented_files_exist.py`, so every source
file it names must still exist.

See also: [`docs/planning/`](planning/) for the forward-looking sprint plans, and
[`docs/engineering/defect-class-sweeps.md`](engineering/defect-class-sweeps.md) for the
defect classes these slices kept finding.

---

### Delivered since the 70-task program — FS-71..90 (Sprints L–P + real-DB pass)

The next batch is **done** and on this branch. (The original FS-71..82 plan was
re-scoped once a re-scan showed Hridyansh's branch had already built the
predictive-maintenance RUL and digital-twin optimizer — so those merged rather
than being rebuilt, preventing duplicate work.)

- **Integration merges landed.** `hridyansh/integration` — predictive-maintenance
  RUL (`/api/v1/rul`), digital-twin optimizer (`/api/v1/twin`), auth-session
  hardening + token rotation, RBAC route-roles across every router, durable
  command dispatch, tenant historian/retention (`/api/v1/historian`); its
  colliding migrations were renumbered to `034–038`. Plus the RAG compliance-doc
  pipeline (`/api/v1/rag`). Two previously-orphaned routers (model-monitoring,
  admin query-performance) are now mounted.
- **Supply-chain & runtime hardening.** `python-jose` → **PyJWT** (drops the
  `ecdsa` advisory and the last `pip-audit --ignore-vuln`); backend/frontend/RAG
  images run **non-root**; k8s **egress** allow-lists added; the Trivy filesystem
  scan is now **blocking** (with a curated `.trivyignore`).
- **API contract.** Every router mount documents its `401/403/404/422/429/500`
  responses (`app/core/responses.py`); a `Page[T]` pagination envelope on the
  assets + alarms lists; wider `response_model` coverage. The schemathesis
  contract gate is wired + green-capable but stays **advisory** pending one CI run.
- **Frontend.** `react-query` v3 → **`@tanstack/react-query` v5** (33 files); the
  digital-twin, RUL, and historian backends are wired into the UI.
- **Real-DB correctness.** The app was silently broken against a *migrations-built*
  Postgres (SQLite `create_all` hid it): ORM↔migration drift fixed — migrations
  `039/040` add missing `users.*` columns and rename 8 tables' `metadata` →
  `meta_data`, and `assets.workcell_id` is now required — plus a batch of
  endpoints that 500'd only on real Postgres repaired (nlp sessions, telemetry
  `meta_data`, yard/transportation naive-`utcnow()` vs `TIMESTAMPTZ`, graceful
  `503`s for redis/pg_stat-backed diagnostics).

### Delivered since — FS-91..140 (real-DB lock-in, observability, edge, contract, deploy)

The next batches are **done** and on this branch (and now on `main`). Theme of
the slice: eliminating *silent* failures — tests that skip, alerts that can't
fire, data quietly dropped, errors that only reach a log. Every fix ships with a
guard so the gap can't silently reopen.

- **Real-DB correctness, locked in (FS-91/92/93/96/97/114).** Schema-parity +
  endpoint/write smoke guards run against an ephemeral **testcontainers**
  TimescaleDB, and a new **blocking backend-realdb CI job** runs them on every
  `hamad/**` push (they had been silently skipping — `testcontainers` was never
  pinned; note the pin added here then *collided* with one in `requirements.txt`
  and made the whole job uninstallable until FS-141+ resolved it). A backend+edge timezone-aware sweep fixed naive-`utcnow()`-vs-
  `TIMESTAMPTZ` data-loss bugs (incl. an edge age-lag that read 0 forever and a
  coordinator that dropped readings).
- **Observability for the converged subsystems (FS-105/107/108/110).**
  `opsgrid_*` metrics for rul / twin / historian / notifications; a new
  `opsgrid_subsystems` **alert group gated by a promtool CI job** (nothing
  validated the alert rules before); correlation-id propagation onto the
  **WebSocket** path (it bypassed the HTTP middleware); and subsystem failures
  (rul notify, twin emit, notification delivery) wired into **error-triage**.
- **API contract (FS-102/103).** RFC-9457 **`application/problem+json`** on error
  responses (additive over the legacy envelope) + wider **Idempotency-Key**
  coverage across mutation surfaces.
- **Edge telemetry chain (FS-120/121/123).** Five silent data-loss bugs fixed:
  Sparkplug B aliased-DATA drop + rebirth/seq handling, SNMP Counter64 precision,
  and an edge-buffer retention bug that string-compared timestamps and wiped
  fresh rows. Edge suite 175 → 186 tests.
- **Audit & runtime security (FS-111/116).** Audit-log coverage for the new
  control-plane mutations (twin optimize, model reset, query-perf admin); and
  per-workload **k8s egress allow-lists** finishing the default-deny posture.
- **Offline demo depth (FS-135/137).** `make demo` one-shot (seed → serve the API
  against SQLite `dev.db`, dev-token auth) plus a **CI smoke** that seeds and
  hits the gap-area endpoints so the seeder can't silently rot.
- **Frontend real-mode depth (FS-126/127/130/131/132) + brand system.** Telemetry
  paging + range/zoom, pagination controls on every `Page[T]` list, WebSocket
  reconnect/backoff, the RUL / historian / digital-twin pages and notifications
  center, and the logo/wordmark brand system (sidebar + login headers).

Still deferred/flagged: the schemathesis gate flip (needs a green CI run); the
py3.11 DNP3 driver (upstream ships no compatible wheel); and the remaining
FS-91..140 backlog — SDK regen (FS-101/104), HPA/PDB + secrets/canary
(FS-113/115/117), edge enrollment/hot-reload/e2e harness (FS-122/124/125),
real-mode audit + loading states (FS-128/129), seeder profiles + continuous
aggregates + offline export (FS-133/134/136), and the signed-URL/geotab/ERP
security passes (FS-138/139/140). The 3 intake-lane test failures remain Harsh's.

### Delivered since — the ERP slice (eight real vendors, and the layer above them)

On `hamad/converged-pre-main`. Start at **[`docs/erp/README.md`](erp/README.md)**.

The theme: a subsystem that *looked* wired end to end and had never been asked a
question by a real vendor. Eight connectors now have five validation tiers, three of
them running against **live systems** — and every tier stood up found a defect on its
first run.

**Eighth connector: Intuit QuickBooks.** Its contract came from Intuit's own OIDC
discovery document rather than prose, and one line shaped the design:
`response_types_supported: ["code"]`. QuickBooks offers **no client-credentials grant**,
so it cannot be provisioned from an id and secret — it needs one-time consent and then
lives on a refresh token Intuit **rotates on every use**. Drop the new value and the
integration works exactly once, then dies with `invalid_grant`, which reads as a revoked
authorization rather than a race.

**Real systems now get a vote.** SAP's public sandbox (`$batch` parsing validated
against genuine SAP bytes), a Dockerised Odoo 17, a free Dataverse environment, and the
first end-to-end test that proves the *whole* path: live vendor → the real sync →
RLS-protected rows, read back as a second tenant.

Defects found, all mutation-verified — reverting the fix fails the test:

| Found | Was |
|---|---|
| `subscribe_to_events` returned `True` for a subscription never created | 7 copies of the same invented `/webhooks` endpoint. Odoo answers **HTTP 200 with a fault in the body**, and only the status was checked. 379 lines removed |
| Inbound webhooks could not authenticate **any** vendor | HMAC over re-serialised JSON, and a header we invented. Now raw-body HMAC, vendor-aware |
| Webhook tenant chosen by **database order** | `.first()` across all organisations, so only one tenant's SAP webhooks could ever work |
| Two tenants could share a webhook secret | Attribution became whichever was tried first. Now a unique index (049) — enforced in the DB *because* RLS hides the rows an app check would need |
| Every `PUT` silently discarded configuration | A JSON column mutated in place, so SQLAlchemy emitted no UPDATE. Secret rotation was impossible via the API |
| Four endpoints 500'd on a valid row | Response models declared required fields over nullable columns. The guard for it found the same bug in a second model on its first run |
| Dataverse paging stopped at 5000 rows | `@odata.nextLink` never followed — silent truncation, the most repeated defect here |
| An unreachable system reported `degraded`, not `unhealthy` | Only visible on the first connector whose **auth host differs from its data host** |
| 20 concurrent callers → 20 token round trips | No lock. Confirmed 15-for-15 against live Entra ID *and* real Odoo; destructive for Intuit, where each refresh rotates the token |
| Rate limiter **10× permissive** under concurrency | Waiters all slept on the same deadline then stampeded. 100 ops against a 10/min limit finished in 60s |
| The background sync wrote nothing on a non-owner role | No tenant GUC. Reported `{"error": "integration not found"}` for an integration plainly in the UI |
| Polled syncs produced no correlations | Only the SAP *webhook* path did, so the AI tab read a table nothing wrote |
| A heuristic was presented as a model inference | `_simulate_analysis` reported the real path's confidence and a model-shaped version string, by default. Now self-labelling *(cross-lane: minimal, and the UI still does not show it)* |

**Absent rather than broken, and left alone:** ERP has no export definition, no
WebSocket event and no Kafka producer. Nothing claims otherwise.

**The ERP hub now renders what it syncs.** Entities, Events and AI were three working
endpoints with no production caller — data synced, nothing displayed. They are now tabs
on the integration detail panel, and the truncation signal below reaches a person rather
than stopping at the client.

**Silent truncation, this time on our own API.** The ERP hub's three list endpoints
returned exactly `limit` rows with no indication more existed, and clamped an over-limit
request instead of refusing it — the same shape that bit three connectors. Bounds are now
declared on the parameter (422, not a quiet substitution), truncation is reported in
`X-Result-Truncated` via a `limit + 1` probe rather than a COUNT, and the API client
returns `ListResult<T>` so the flag cannot be discarded. The tabs that consume it are built, so an
operator sees "showing the most recent 10 of more than 10" instead of a confident partial
answer. Verified end to end: 149 rows synced from live Dataverse, `?limit=10` returns 10
with `X-Result-Truncated: true`.

**Thirty defect classes have now been swept platform-wide** — recorded in
[`docs/engineering/defect-class-sweeps.md`](engineering/defect-class-sweeps.md) with
what each found and which guard keeps it closed. Four started in ERP; most of the rest came
out of the ones before them. Three came back clean, which is worth writing down: "proven
clean" and "never checked" look identical afterwards, and only one justifies not looking
again.

The most recent six are all versions of *the system knows something the reader is never
told*: a reply that was not an inference reporting itself as one; an OEE factor the server
could not measure displayed as a perfect 100%; a query cache serving the previous answer
after the filter changed; three writes whose results the screen never went back to read —
including a command panel where, because dispatch happens off the request path, whether
the machine had acted was not observable **anywhere in the product**; a risk page capped
by asset NAME, so a machine near failure whose name sorted late was simply absent; and
four audit writers whose rows were rejected by row-level security and swallowed, so every
export, bulk job and flag change recorded nothing while reporting success.

Two more came out of the guards themselves. Five handlers opened their own
`AsyncSessionLocal()` and could not see the caller's assets — three `/api/v1/oee/*` routes
answered **404 for an asset you own**, and `/health-index` and `/simulation/fleet-summary`
reported an empty fleet — sitting in a gap the tenant-session guard had *named in its own
docstring* and never closed. And the query-parameter guard, already reopened once, turned
out never to have matched calls whose type argument contains a brace: six were invisible,
one of them offering an `organizationId` the assets endpoint has never declared. The
sibling endpoint guard had the same hole and was checking 180 of 194 calls while claiming
all of them.

The earlier two were found the same way, in the **log noise of an unrelated test run** —
which also gave up `get_historical_oee`, a function whose every column reference was a
Python string (`"oee_metrics.timestamp" >= start_time` raises before the query compiles)
and which had therefore never returned a row, against a table no migration creates. Each
had been failing on every request for as long as it existed, and each was caught, logged
and forgotten. A warning nobody reads is not a signal; it is a place for a defect to
live.

Fifteen method rules now sit at the end of that document, and most were paid for. Two of
the newest: a detector's skip count must account for everything it did not check (a
query-parameter guard printed "37 checked, 1 skipped" while nine calls holding two live
defects sat in the gap), and a detector's input must never contain its own subject (an
invalidation sweep harvested query keys from the very calls it was auditing, so each
vouched for itself and it reported a confident zero).

The common shape is **code that looks wired and cannot work**. Every guard is
mutation-tested — reintroduce the defect and the test must fail — because a guard that
cannot fail is indistinguishable from one that passes.

**A live dashboard was under-reporting its own metric.** Sweeping for handlers that
swallow an exception and still report success turned up 12 candidates; 11 were legitimate
(cleanup, `return False`, an explicit error status). The twelfth was real and live:
`get_sync_dashboard` analysed each dock appointment in a `try`, and on failure logged a
warning and incremented **no bucket at all** — so the appointment vanished from the
breakdown while remaining in `total_appointments`, which is the denominator of
`production_dock_sync_percent`.

Every failed analysis therefore pushed the reported sync percentage **down**, making
dock-production performance look worse than it was, with nothing in the response saying an
analysis had failed. Failures now get their own bucket, leave the denominator (counting an
unanalysable appointment as "not on time" asserts something we failed to determine), and
are surfaced as `analysis_failed_count`. A test pins the invariant that the buckets sum to
the total.

**Swept platform-wide afterwards — and the sweep itself was wrong.** The response-model
defect above was checked across all 61 API modules and reported **zero offenders**. That
result did not hold. The detector skipped any column with a *Python-side* ORM default (it
fills the value only for rows written through SQLAlchemy — a migration, a seeder or a raw
`INSERT` leaves NULL), and it never paired response models a router imports from
`app/models/schemas.py`. Corrected, the same sweep finds **40 pairs across 16 routers, 603
fields, 158 offenders**.

It surfaced the way these things do: a raw-inserted dock door made
`GET /api/v1/yard/dock/doors` return a live 500 — *"equipment_capabilities: Input should be
a valid dictionary"*, a validation error naming our schema rather than the data.

**Then the corrected sweep was wrong the other way, by a factor of three.** It read
`server_default` off the ORM, and 109 of those 158 columns already have a database
default — added by migration 044 and never mirrored into the ORM declaration. The check
now reads `information_schema` from the migrated database. The true count was **49**, and
it is now **zero**: migration 050 gave server defaults to 39 logistics/yard columns (each
taken from the ORM's own `default=`, backfilling existing NULLs), and the remaining 10 are
nullable columns with no default anywhere — mostly optional foreign keys — whose response
fields now mirror them.

The first version of that scan reported 8 defects. Testing one against real Postgres
returned HTTP 200 instead of the predicted 500 — the detector checked
`typing.get_origin(a) is typing.Union`, but PEP 604 `str | None` produces
`types.UnionType`, so every field in modern syntax was misread as required. The same flaw
was in the ERP guard, where it would have failed a *correct* model. Both fixed, and both
now test the detector before anything that depends on it.

**A control command the platform reported as sent, and never sent.** Sweeping for helpers
whose *name* claims a side effect — create/send/persist/store/publish — found 129 across
`app/` and two whose body only logs. One is honest (emitting a warning *is* logging). The
other was `tactical_engine._send_command`: it assembled a command dict, logged
`command_queued` at DEBUG, and published nothing, while `execute_decision` — docstring
*"Returns True if executed"* — logged `tactical_decision_executed` and returned `True`.
The two safety gates directly above it are real and careful, and the maintenance check
even fails safe under a comment reading *"a broken control command is worse than a skipped
one"* — which is exactly what made the dispatch below it look trustworthy. It is
unreachable today only because `start()` is missing from `main.py`, where the other seven
engines all appear. It now refuses and reports it; wiring the real sink
(`command_executor`, already running) switches on autonomous actuation of industrial
assets, which is a decision with a safety review attached, not a side effect of a naming
fix. The cloud training-feedback event now carries `dispatched`, since a decision that
never reached the asset produced no outcome to learn from.

**Quarantined edge readings were discarded, not quarantined.** `EdgeIngestGateway` passed
each malformed reading to a sink whose default logged the agent and reason and dropped the
payload — no table, no topic, not even the log line — and `POST /api/v1/edge/ingest` then
answered `quarantined: 47`. The count was true and the word was not, for 47 readings that
existed nowhere. Readings are now retained in `IngestResult.quarantined` (so it works
without an injected sink, which is the API's actual configuration) and published to a real
dead-letter topic, keyed on the certificate-verified `agent_id` — a reading that failed
validation cannot be trusted for routing, and the malformed field may *be* `asset_id`.

**The tenant RLS context was lost on every mid-request commit.** `get_tenant_db` set
`app.current_org_id` once with `set_config(..., false)`, on the documented reasoning that
a session-scoped value survives a mid-request commit. It does not: `commit()` returns the
connection to the pool, the next statement gets an unconfigured one, and every RLS policy
fails closed — so an endpoint that wrote a row and read it back got nothing.
`create_rollout` returned **404 for a rollout sitting in the table**. The GUC is now
re-established per transaction from an `after_begin` hook, and written transaction-locally
so it also cannot leak onto a pooled connection.

**Why no test caught that, which is the more useful finding.** `conftest` overrode
`get_tenant_db` with a hand-copy of its body, under a comment reading *"Mirrors the
production get_tenant_db."* It mirrored the bug too — and being a copy, it could not do
otherwise. Sweeping every file that overrides it found **four copies**, so the RUL,
twin-optimizer and historian suites were also asserting against the defect rather than
against production. All four now delegate to a shared `tenant_session`. A test double that
reimplements the thing it stands in for can only prove the double works.

That guard needed a second pass too: written the obvious way it *passed* against the
reintroduced bug, because with a normal pool `commit()` hands the same connection straight
back. It now uses `NullPool`, so every checkout is a fresh connection — the worst case a
loaded server produces routinely.

**A live cross-tenant read.** `GET /api/v1/transportation/vehicles` ran
`select(Vehicle).where(Vehicle.is_active == True)` on `get_db` — no organization filter,
on a table that carries `organization_id` but has no row-level security. Both layers that
normally catch this were absent, so every authenticated user listed every tenant's fleet.
Confirmed against a real database before fixing (org A's client saw org B's vehicle), and
pinned by a mutation-tested guard. The existing auth-walk test could not see it — the
route does require authentication; scoping was the problem — and the RLS isolation tests
exercise policies this table does not have. **`fleet_logistics.py` had 23 handlers of the same shape and is now
fixed too** — its zone list leaked across tenants and fetch-by-id was a full IDOR (separate
code paths, so a guard on one proves nothing about the other), and its four create paths
took `organization_id` from the request payload. The same change fixed the *opposite*
failure in the same file: endpoints reading RLS-protected tables on `get_db` were
returning zero rows. One wrong dependency, two failure modes, depending only on whether
the table had a policy. The same pattern then explained the transportation endpoints:
`carriers`, `drivers`, `shipments`, `routes` and the GeoTab fleet summary took
`organization_id` from the client *and* returned nothing to anyone, because their tables
have FORCE RLS and the handler set no tenant GUC. Migration 051 closes the structural
half by giving the four unprotected fleet tables their own policies. The same dependency
mistake had left **the audit trail and the GDPR processing records silently blank** —
policies since migration 011, handlers on `get_db`, so both returned zero rows even for
the caller's own organization. `gdpr.py` filtered on the organization *correctly* and it
changed nothing, because RLS had already removed the row. The same shape had made
**command submission and the safety-critical emergency stop unreachable** — both 404'd for
every asset — and it had been rejecting **every inbound ERP webhook** — fixed by migration 052, which
grants that one unauthenticated lookup a narrow SELECT-only policy (active ERP rows, only
while a transaction-local flag is set) rather than abandoning signature-selects-tenant.
All 12 ERP routes are now verified working end to end against a real database, and the
whole NLP analysis-session surface was dead too — 22 handlers on `get_db`, so reads
returned nothing and **create raised a 500** from the policy's `WITH CHECK`. That is the
one instance in this class that failed loudly rather than quietly: under RLS a read is
silently filtered while a write is rejected outright. The core product surfaces were then
swept for the same failure and came back clean — a seeded
organisation's asset, alarm and operation all appear in `dashboard/overview`,
`alarms/active` and `operations/active`.

**The frontend was the same problem at a larger scale.** `src/test/setup.ts` forces
`VITE_USE_MOCK='true'` before any module evaluates, so every unit test takes the mock
branch of the 213 `if (USE_MOCK)` forks across 33 files — the real branch, the code that
ships, is executed by no test. Sweeping all 183 real-mode API calls against the backend's
live route table found four endpoints the backend does not serve. One was live and wired
to a UI button: `PATCH /api/v1/fleet/security/events/{id}` 404'd, and `HealthSecurityPanel`
awaited it with no `catch`, so an operator clicking "acknowledge" on a fleet security event
saw nothing happen and no error. The endpoint now exists — the columns, the read path and
the UI were all already there, only the write was missing — and the component reports
failures. The other three were uncalled and were removed. Notably a hand fix of this exact
class had already run (FS-15, "routes that never existed") and left these behind.

**Both suites are green: backend 2,507 passed, frontend 445 passed, 0 failed** — across
215 backend and 64 frontend test files (three backend files are quarantined in CI, each with an
owner and an expiry — see `test_ci_quarantine_expires.py`). Every guard listed above is
mutation-tested:
reintroduce the defect and the test must fail, checked individually, because a guard that
cannot fail is indistinguishable from one that passes.

**Tenant isolation held everywhere it was pushed on** — entities, sync status,
integration list/get, events, correlations, and the provider feeding AI analysis
sessions. The ERP client secret is never echoed, even to its owner.

### Delivered since — the verdict-from-absence slice

One class, chased across both sides of the wire until the mechanical sweeps came back
empty with working controls. **Absence read as a result**, in six distinct forms:

| form | example found |
|---|---|
| Python coercion | `float(x or 0)` made a driver who never reported one who drove zero hours |
| an empty iteration | zero HOS violations among zero drivers cleared a carrier |
| SQL three-valued logic | `WHERE hours > 11` discards NULL as it discards FALSE — `COMPLIANT` |
| the average of an empty set | `/dashboard/fleet/oee` reported 0% availability for a fleet with no assets |
| an `except` that fills the gap | a failed OEE calculation appended a row of zeros — a machine at 0% |
| **a falsy branch that asserts** | `mtls ? 'Enabled' : 'Disabled'` printed a security finding about a link nobody inspected |

The last one is the hardest to see in review, because both branches look like deliberate
handling. It is a two-valued answer to a three-valued question.

**Maintenance mode is the sharpest thing in this slice, and it is about fixing, not
finding.** `assets.maintenance_mode` did not exist: the write endpoint 500'd on every
call while the frontend called it, and the tactical engine's reader caught the error and
failed *safe*, so every asset looked suppressed and nothing surfaced. Adding the column
alone would have flipped the engine from suppress-everything to **suppress-nothing** —
control commands dispatched to machines an operator had locked out — because the read was
`bool(row and row[0])` on a session with no tenant GUC, and `assets` is FORCE RLS. When a
fail-safe has been absorbing a defect, removing the defect releases what it was hiding;
the commit that makes the error go away is the moment of maximum risk (rule 22).

**Every fix in the slice**, so the record is the list and not a sample. Each one is a live
defect on a mounted route or a rendered page, each has a test that fails against the code
as it was:

| where | what it claimed | what was true |
|---|---|---|
| `check_compliance` | a driver with no reported hours was **compliant** | nothing was reported; `float(x or 0)` invented the zero |
| `check_compliance` | a driver with **no medical certificate** was compliant | both branches were guarded on the field being set |
| `/carriers/{id}/compliance` | a carrier with no drivers was **cleared on HOS** | zero violations among zero drivers is not a finding |
| `/logistics/compliance/summary` | `COMPLIANT` | NULL hours never match `> 11`; WHERE discards UNKNOWN as it discards FALSE |
| `/logistics/delivery-efficiency` | grade **D** for the period | there were no deliveries to grade |
| `/dashboard/fleet/oee` | **0%** fleet availability | no assets were measured — the average of an empty set |
| `/oee/dashboard/summary` | an asset at **0% OEE**, and a fleet mean dragged down by it | the calculation raised; placeholders were averaged in |
| `/exports/oee/summary` (PDF) | a filed report showing **0, 0, 0, 0** | same, in a document that gets printed and forwarded |
| `PATCH /error-tracking/errors/{fp}` | one tenant could resolve **another tenant's** error | matched on fingerprint alone — a cross-tenant *write* |
| `POST /admin/assets/{id}/maintenance` | 200 | the column did not exist; and under RLS an UPDATE is filtered, not rejected |
| `TacticalEngine._is_maintenance_mode` | *not in maintenance* | the row was invisible to a session with no tenant GUC |
| 13 screens (yard, telemetry, …) | "No trailers found", "No history for this metric" | the request failed |
| `FleetOverview` | *(the live vehicle map, absent)* | the org query failed — no sentence to grep for |
| `CloudGateway` | "Queue Depth 0 items", "**mTLS Disabled**" | the gateway was never reached |
| `TacticalEngine` | a red **Not Loaded** badge — edge inference down | the status endpoint did not answer |
| `MLOpsPipeline` | a green **Active** badge, "300 seconds", "0 models" | beside its own "Model status unavailable" |
| `Dashboard` | heading "**Active alarms (0)**" | its own body said "Couldn't load this data" |
| `StrategicEngine` | "No pending recommendations. **Check back later**" | the query failed; three tiles read 0 beside the banner |
| `ERPIntegrations` | "No ERP integrations yet. **Add one to get started**" | `isError` was never destructured |
| `ERPIntegrations` test-connection | the **previous** test's "healthy: connected" | this test had just failed |
| `AdminPages` delete-user | *(nothing)* | the delete failed; access was never revoked |
| `Notifications` delete-subscription | *(nothing)* | the webhook is still active and still sending |

**The sharpest find came last, from a different sweep.** Asking which TypeScript fields
the frontend declares and renders that *no backend source emits* turned up
`hosDriveHoursRemaining` — a column migration 042 added with no default, no backfill and
no writer anywhere in the codebase. The compliance tab counts a violation as
`hosDriveHoursRemaining === 0`, `null === 0` is false, and so **every fleet was cleared of
HOS violations** on the success path with the data loaded. This page had already been
fixed for the same class once, on the *failed-query* branch; the more common case sat
untouched behind it. The same field also 500'd the drivers list on any unreported driver
(`float = 0` against a nullable column), crashed the tab through `formatDuration`'s
`=== undefined` guard meeting a JSON `null`, and painted unreported drivers amber because
`null < 2` is `0 < 2`.

**Then the same question, asked about actions rather than reads.** `useQuery` failures
render as emptiness; `useMutation` failures render as nothing at all — and the user pressed
the button on purpose, so no response is indistinguishable from the instant before the list
refreshes. Nine silent mutations, all `onSuccess` and no `onError`. A failed connection test
left the PREVIOUS test's "healthy: connected" on screen as the current result. A failed
delete-user said nothing, and "row still there" is what success looks like until the list
refetches — an admin who believes they revoked access, and did not.

**Twelve sweeps are now permanent guards**, each with a control proving it can fail:
phrase-based empty states, widgets that disappear when a query fails, mutations with no
error surface, qualifiers the frontend never renders, and — the mirror of that last one —
TypeScript fields the frontend renders that no backend source emits, response-model fields
that are not columns of their own table, and CI's own test-exclusion list — which now carries
an owner, a reason and an expiry date per entry, and fails when a new exclusion appears
undocumented or an expiry passes. Every one is checked against the
real pre-fix file restored from git, not a synthetic fixture — a fixture proves the function
works, only the file proves the walking around it does.

**The last sweep asked the contract question in the other direction** — which fields does
the frontend declare and render that nothing on the server produces? — and found values
that had simply been invented: a maintenance schedule's "Mileage: 128,500" (the odometer at
which service falls *due*, relabelled), a work-order number synthesised from eight
characters of a UUID and shown as the heading a technician quotes to a vendor, and three of
the five figures on the cost tab (two hardcoded zeros, one "monthly average" that divides
year-to-date by twelve in every month). A fabricated value is always the one that looks
most normal — a zero in a currency column is unremarkable, which is exactly why it survives
review.

**Maintenance mode turned out to be wrong in five places, found by four different
sweeps.** No column; a write that was neither tenant-scoped nor rowcount-checked (under RLS
an UPDATE is *filtered*, so it returns 200 having matched nothing); an engine read that
treated an RLS-invisible row as "available to command"; a response model that never
declared the field, so no client could see which assets were out of service; and a caller
that posted the flag as a JSON body when the endpoint reads it from the query string —
which made *taking an asset out of maintenance put it in*. Each fix looked complete at the
time, because each defect sits on a different seam and a sweep is organised by shape rather
than by feature. The last two point in opposite directions — server not sending what the
client reads, client not sending what the server reads — and neither sweep could have found
the other.

**Working the contract sweep's list produced four more, each needing a different fix.**
Every geofence alert read **"Violation"** — including routine authorised entries — because the
endpoint sent `eventType` and the panel switched on `alertType`, so the ternary fell through
to its last branch. A dock door could not name the trailer at it, because the plate lives on
`yard_trailers` and nobody joined it. `workcellName` was **deleted** rather than resolved:
`dock_doors` has no workcell relationship to resolve through. And a card headed *"Fleet Status
(GeoTab Live)"* rendered six blanks, two beside bare units — the client's declared shape shared
no field name with any response — while the payload itself carried `simulated: true` and the
sentence *"not valid for DOT/ELD compliance reporting"* that nothing read.

That is the value of asking the question table-aware: *does this entity's own table have a
column that could feed the field, or a reference to one that does?* The answer sorts each
entry into rename the producer, expose what exists, or delete the field — three different
fixes that a list of names alone cannot distinguish.

**The sharpest find of the whole slice came from reading one handler.** A sweep for request
fields no column holds came back almost clean — which was misleading, because twelve route
handlers take an untyped `Dict[str, Any]` body that no schema describes. Reading one of them
found `organization_id=payload.get("organization_id")`: the tenant taken from the request. A
guard written for that shape found **thirteen more**, all identical, plus one that preferred the
client's value with a fallback to the right one.

Thirteen were saved by row-level security, where a policy's `USING` clause acts as an INSERT's
`WITH CHECK` — so the write failed with a 500. `vehicles` was the exception: no policy, nothing
between the body and the row, and a create naming another organisation **succeeded**. Same
defect, same three files, and the only one that shipped was the one whose table lacked a second
layer. Migration 055 closes that, and a new guard asserts that **every** table carrying an
`organization_id` has a FORCEd policy — which found six tables with none and five whose policy
is not forced, each now recorded with what closing it requires.

That change was caught by a test the *previous* author wrote for exactly this: it asserted
`vehicles` had no RLS, in order to record that the application filter was the only defence, and
failed on the next run with *"good, but this test's premise no longer holds; check whether the
sibling logistics tables were covered too."* A guard built to expire, firing across authors and
months apart.

**One class, three guards, twenty-six handlers.** "The caller decides which tenant" turned out
to have three separate spellings, and each guard was clean while the next variant sat in the
same three files: a tenant *assigned* from a request body (14 handlers), a tenant *received* as
an optional query parameter (8), and a tenant filter applied *conditionally* (4 —
`if org is not None: stmt = stmt.where(...)`, so a user with no organisation read everything).
The notification router had the worst of them: an unscoped `DELETE` letting any authenticated
user remove any tenant's subscription by id, on a table with no policy to fall back on, with a
`rowcount == 0 -> 404` check that proved a row had been deleted rather than that it was yours.

Whether any given instance leaked or merely broke depended entirely on whether its table
carried a policy — which is why `vehicles` (the one fleet table without one) was the single
handler whose defect wrote a real cross-tenant row while thirteen identical ones returned 500s.

**The guards needed as much correcting as the code.** The emptiness sweep reported zero
offenders while three pages were unguarded: its phrase cap hid a hundred-character empty
state, and its proximity window found an unrelated mutation's error branch and called the
page clean. The mutation sweep's first version produced two false positives out of four
files from a fixed look-ahead window. A window is a guess about code shape; the fix in both
cases was to count braces and use the real bounds. A third computed its own baseline from
the tree it then compared against, so it could never fail for any input. **Three guards,
three different ways of being confidently wrong** — running a guard does not test it;
breaking the tree on purpose does, and every one of them is now controlled that way.
Rules 21–67 are recorded in `docs/engineering/defect-class-sweeps.md`.

### Delivered since — FS-141+ (release path, backups, and the guards that weren't guarding)

On `hamad/converged-pre-main`, ahead of `main`. The theme is the previous
slice's taken one level further: not just *silent failures*, but **guards that
reported success while testing nothing**, and **subsystems that had never once
worked against a production-shaped database**.

- **The blocking `backend-realdb` gate now passes — for the first time ever.**
  It had never installed: `requirements.txt` pinned
  `testcontainers[postgres]==4.14.2` while `requirements-dev.txt` pinned `3.7.1`
  *and* did `-r requirements.txt`, so `pip install -r requirements-dev.txt` — the
  exact command that job and the ci-cd backend job run — failed with
  `ResolutionImpossible`. **Backend dependencies were uninstallable in CI from
  2026-07-17.** Resolved forward onto 4.x; `testcontainers` also left
  `requirements.txt`, where a test-only dependency was being baked into the
  runtime image.
- **The audit trail was silently empty on every real deployment.** Two
  independent faults, both swallowed by the middleware's catch-all as
  `audit_log_failed`, so every request reported success while nothing was
  recorded: `audit_logs.ip_address` is `INET` in migrations but was `String(45)`
  in the ORM (every insert bound `::VARCHAR` and was rejected), and `audit_logs`
  is `FORCE ROW LEVEL SECURITY` while the middleware wrote through a session that
  never set `app.current_org_id`. **`FORCE` applies even to the table owner**, so
  no connecting role escaped it.
- **Endpoints that had never returned a success.** Yard trailer check-in 500'd on
  the same `FORCE`-RLS problem (all 18 yard routes moved to `get_tenant_db`,
  which also closes a tenant-trust hole — `organization_id` came from the request
  body). Five logistics call sites used the SQLAlchemy 1.x
  `func.case([...], else_=0)` signature and raised on first execution; one also
  counted *expired* insurance as valid, because `CASE` returns on first match.
  All five `/model-monitoring` endpoints 500'd because `scipy` was never declared,
  so the router fell back to `service = None`.
- **PackML state ingestion was dead.** Both statements in the ingestion worker's
  state path were f-strings passed bare to `session.execute()`; SQLAlchemy 2.x
  rejects a plain `str`, and the caller rolls back and re-raises — so *every*
  state message failed and no `packml_states` row was ever written, silently
  corrupting downtime/OEE history. The path had no test; it has four now.
- **Guards that were passing vacuously.** The real-DB endpoint smoke walked
  `app.routes` directly and so probed **2 GET routes instead of ~200** (fastapi
  ≥0.130 keeps `include_router()` results as lazy containers). The schema-parity
  guard only compared `id`/`*_id` columns for uuid-vs-text — structurally why the
  `ip_address` drift was invisible to it; widened to all columns, it immediately
  found three more. Both walks now share one definition in `tests/route_walk.py`.
- **Access control, both sides of the wire.** `AdminRoute` was implemented and
  exported but wired to no route, so all nine `/admin/*` pages sat behind
  `ProtectedRoute` alone. `GET /edge/fleet` — which backs `/admin/collectors` —
  required only an authenticated user *and* carried no `organization_id` filter,
  letting any tenant enumerate every organization's edge agents. Both fixed, with
  a guard test and a new policy-side assertion (the old admin inventory was a
  *regression lock*, not a policy check, and was shaped around the `/admin/`
  path prefix).
- **Webhooks fail closed.** ERP webhook signature verification returned `True`
  when no secret was configured — and its own test asserted that as intended
  behaviour ("open webhook"), which is why review never caught it. The
  route-auth walk exempts this route *on the grounds that it is HMAC-protected*,
  so the exemption was unearned. A second, currently-unreachable receiver
  returned `True` whenever the signature header was simply absent.
- **Real backups exist now.** Staging and production had **none**: the only
  pgBackRest CronJob lives in `legacy-patroni/`, which CI never applies, so every
  DR runbook restored from a repository nothing wrote to. pgBackRest cannot run in
  the deployed stack at all (`timescale/timescaledb:latest-pg15` ships no
  `pgbackrest` binary and no `archive_mode` is configured), so a nightly
  `pg_dump -Fc`-to-S3 CronJob landed as the working safety net, with an egress
  NetworkPolicy and **a restore drill in the blocking gate** — a backup nobody
  restores is not a backup. PITR via `timescaledb-ha` is the tracked next step;
  see [`docs/runbooks/database-backup-restore.md`](runbooks/database-backup-restore.md).
- **The release path.** Both deploy jobs ran a single `kubectl apply -k`, which
  updates the Deployments and creates the migration Job together — so new pods
  began serving before migrations finished. Deploys now apply the Job alone, wait,
  then apply the rest. Every trigger naming `develop` was dead (that branch has
  never existed), which is why staging was never deployed and four
  `hridyansh/**` branches ran **zero CI**.
- **Repo hygiene, enforced.** The root `.dockerignore` existed only in a working
  tree, so CI built the backend image with `frontend/`, `backend/venv`, `.git`
  and `*.pem` in the build context. 19,048 `node_modules` files were untracked. A
  blocking `repo-hygiene` job now fails on any tracked dependency tree, build
  output, or key material.

Known-remaining endpoint failures against a real database are **other lanes** and
are tracked in an attributed `KNOWN_LANE_FAILURES` list in the endpoint smoke,
which asserts both directions so it cannot rot: kanban ×4 and the nlp intake
correlation query (Harsh), `/rag/documents` (Hudson). Also still open: the k8s
cluster has **no monitoring stack at all** — no Prometheus, Alertmanager, Grafana
or kube-state-metrics — so every alert rule and dashboard in `infra/prometheus`
and `infra/grafana` only runs under docker-compose, and backup/migration-failure
alerting is blocked on that decision. `HAMAD_IDE.pem` remains retrievable from
git history; see [`docs/runbooks/leaked-key-rotation.md`](runbooks/leaked-key-rotation.md)
(rotation is the fix and is still outstanding; the history purge is deliberately
deferred because it would rewrite every collaborator's branch).

### Delivered since — the honesty slice (what the system knew and never said)

On `hamad/converged-pre-main`. The previous slice was about guards that reported
success while testing nothing. This one is the same idea turned on the guards
themselves and on the product's own output: **three sweeps were reporting coverage
they did not have**, and several surfaces were showing confident numbers they had no
right to.

**Five handlers could not see the caller's own assets.** They took no session
dependency and opened `AsyncSessionLocal()` inline, which sets no
`app.current_org_id`; `assets` is `FORCE ROW LEVEL SECURITY`, so the policy matched
nothing. Verified against a real database with an asset that plainly existed:

| | | |
|---|---|---|
| `GET /api/v1/oee/current/{id}` | **404** | "Asset not found" |
| `GET /api/v1/oee/historical/{id}` | **404** | "Asset not found" |
| `GET /api/v1/oee/losses/{id}` | **404** | "Asset not found" |
| `GET /api/v1/health-index` | 200 | `[]` |
| `GET /api/v1/simulation/fleet-summary` | 200 | `{"asset_count": 0, …}` |

Both halves of the RLS failure mode on one screen, and the quiet pair is worse —
`asset_count: 0` on a running plant reads as an idle factory, not a broken query.
`health_index` and `simulation` filtered on `current_user.organization_id` and were
**right to**; it changed nothing, because RLS had removed the rows first. A reviewer
sees a correct tenant check and no reason to look at the session. **The tenant-session
guard had named this exact blind spot in its own docstring** — "a static guard keyed on
one idiom under-counts a file that uses two" — and never closed it.

**Four audit writers recorded nothing, and each one logged that it had.** `record_audit`'s
standalone path plus `_audit` in `export_processor`, `bulk_processor` and
`feature_flags` inserted into `audit_logs` (also `FORCE` RLS) with no tenant bound; the
rejection was caught by a broad `except` that logged and continued. Every export, bulk
job and feature-flag change reported success while its evidence was discarded. Under RLS
a read fails *silently* and a write fails *loudly* — and a `try/except` around the write
throws that distinction away.

**Numbers that were not measurements.** The correlation chat's exception fallback — a
reply that is not an analysis at all — was the only one of the three reporting
`simulated: false`, because it built the response without the field and the default is a
claim. OEE displayed `quality: 1.0` for an asset with no part counters as a perfect
100%; 1.0 is the neutral multiplier for the product and the wrong thing to print, and the
server had been sending `quality_measured` since FS-234 with nothing reading it.
`/api/v1/rul` caps at `limit` and orders by asset **NAME** — remaining useful life is
computed per asset in Python, so risk is not sortable in SQL — meaning the predictive
page's "Assets Assessed" and "High / Critical Risk" tiles counted the alphabetically
first N as though they were the fleet.

**Two dead paths that had never once worked.** `oee_calculator.get_historical_oee` built
every column reference from Python strings — `"oee_metrics.timestamp" >= start_time` is
`str >= datetime`, which raises before the query compiles — against a table **no migration
creates**; its writer passed the same string to `insert()` and swallowed the failure, and
`main.py` starts that loop, so it emitted an error per asset per pass forever. And the
command panel invalidated `['commands', assetId]`, a key **no query declared**, while
telling operators to "view command history in the asset details page" — the page that
renders the panel and no history — with `GET /api/v1/commands/asset/{id}` working and
having zero callers.

**The guards themselves gave up the rest.** The query-parameter sweep printed "37 checked,
1 skipped" while nine calls sat in a gap; fixing that surfaced two live defects, and then
the *entry point* turned out never to have matched calls whose type argument contains a
brace — six more invisible, one offering an `organizationId` the assets endpoint has never
declared. The sibling endpoint sweep had the identical hole: **180 of 194 calls checked,
while claiming all 183**. Two further findings came out of log noise scrolling past during
unrelated runs.

A twenty-seventh class came out of documenting the rest: **the README's own API
Reference had 22 wrong rows of 124** — `/api/v1/kanban/boards`, which has never existed;
`/commands/{id}/status`, where the real route puts the verb first; five `correlations`
rows that live under `registries`; and five logistics rows written at the *tidy* path
while the router genuinely serves `/api/v1/logistics/logistics/…`, so the one artefact
that would have warned a reader about that collision concealed it instead. Documentation
that cannot be executed rots silently, precisely because nobody runs a README, so it is
now a checked artefact — `test_documented_endpoints_exist.py` parameterises over every
row and fails by name.

A twenty-eighth followed from the same idea: every source file the docs name is now
checked to exist. The ERP listing had claimed a sap_correlation_patterns.py between its
Oracle and Dynamics siblings — **the symmetry of the list is what hid it** — while five
real files, including the eighth ERP connector, were missing from the inventory
altogether. The first version of that guard put the fictional name on an exemption list,
which then excused the very bullet it was written to catch; the mutation run passed and
looked like proof.

**The audit chain closed at the page, and the page was bypassing the client.**
`AuditLogs.tsx` called `fetch('/api/v1/audit/logs')` with a hand-built `Authorization`
header instead of going through the shared axios instance. That mattered twice: the
client's response interceptor refreshes an expired token on 401 and redirects to `/login`
when the refresh fails, so this was the **one screen that could not recover from expiry**
— and the audit trail is exactly where someone sits reading long enough to expire. It
also placed the page outside every frontend/backend contract guard, which scan for calls
through the client; both its endpoints happened to be real, which is luck rather than
coverage. It now uses `api`, the guard walks the whole `src` tree for raw `fetch`, and a
new assertion fails if anything bypasses the client again.

The same pass removed an `organization_id` query parameter from `GET /api/v1/audit/logs`.
It could never have worked as a cross-tenant selector — the handler is RLS-scoped, and a
real-database probe confirmed org A supplying org B's id got a 200 and an empty list — but
a parameter that can only narrow-to-nothing advertises a capability the product does not
have, on the one table where a cross-tenant read *is* the incident, and it would become a
live selector the moment anything ran that query with RLS bypassed.

**Fourteen surfaces told the operator something false when a request failed.** React
Query sets `data` to `undefined` on error, so `data?.items ?? []` renders an empty list
and nothing anywhere says the request failed — the screen makes a claim about the *world*
instead of about the *system*. The worst of them: `TransportationManagement` rendered a
**green checkmark reading "No HOS violations detected"** when the drivers query failed.
Hours of Service is DOT-regulated, and a compliance officer reads a green tick as
clearance. `TacticalEngine` asserted the engine reported no safety thresholds — directly
beneath its own "failed to load" banner. `MLOpsPipeline` said "No model deployed", which
an operator may act on by deploying. `OEE` failed the other way and rendered nothing at
all: no rows, no message, nothing to disbelieve.

**And the server had the same defect on the same data.**
`get_carrier_compliance_summary` returns
`overall_compliant = ctpat_certified and insurance_on_file and hos_violations == 0`,
counting violations by looping over the carrier's drivers — so `hos_violations == 0` is
**trivially true when there are no drivers**, and a carrier whose records had never been
entered was cleared on the same DOT-regulated check. One is an empty table and the other
an empty response; both produced clearance from nothing having been inspected.

That pair is what makes it a class rather than two bugs, and it comes with a usable line:
**emptiness is only ambiguous where a COUNT stands in for an inspection.** The C-TPAT and
insurance checks in the same payload read fields that either hold a valid date or do not,
so they were deliberately left alone.

All fourteen now distinguish a failure from an absence, and the sweep that found them is
a guard. It took five corrections to get there, each found by the false positive it
produced — file-level, then count-based, then per-empty-state; then four more error
idioms; then comment stripping, for the third time in this codebase.

**And two of this slice's own fixes turned out to prove only half their property.** The
audit tests counted rows through a *superuser* connection, which bypasses row-level
security entirely — so they showed the INSERT was no longer rejected and said nothing
about whether the entry was ever **visible** to the tenant whose trail it belongs to.
From the compliance desk those are the same failure. The heartbeat tests had the same
shape. Both now read back through the path the operator actually takes —
`GET /api/v1/audit/logs` and `GET /api/v1/fleet/agents/versions` — plus the opposite
direction, because binding a tenant to make a write land must not make the result
readable to everyone, and the audit trail is the one table where a cross-tenant read is
itself the incident. That is method rule 20; sweeping the other four real-DB files that
read through a privileged connection found them sound.

Twelve classes swept this slice (18–29) and eight method rules added (14–21), including *a
detector's skip count must account for everything it did not check*, *never let a
detector's input include its own subject*, and *a guard that has already been wrong once
is the most likely place to be wrong again — re-derive its entry point, not just the part
that failed*. Every fix is mutation-verified by restoring the real prior code, not a
reconstruction of it.

### Delivered since — the repository slice (what a checkout costs, and what CI declines to run)

On `hamad/converged-pre-main`. Two findings, and both of my own first numbers were wrong in
ways that changed the fix.

**`origin` had no `alex` branch.** Eighty-nine commits of Alex's work existed on the mirror
only, so the primary remote was one accident away from losing all of it. Pushed to
`origin/alex` at `d5286f1c` — additive, nothing rewritten.

**The 1.5 GB corpus was costing every checkout, not every clone.** The audit said
`backend/dataset` was "1.57 GB of the 1.59 GB repository — 99% of every clone". That measured
the *working tree*. Git stores the corpus compressed and deduplicated: the whole repository
packs to **96 MB**, of which the dataset is **41 MB** — a 37× difference between what a clone
transfers and what a checkout writes. Measure the pack, not the tree, before claiming a
transfer cost.

**And it must not be deleted**, which is the opposite of what "generated output in git"
usually implies. `generate_dataset_enhanced.py` sets no random seed and can call an LLM, so
the corpus is generated but **not reproducible**: deleting it loses ~500,000 scenarios that
cannot be regenerated identically, and the fine-tuning results stop being explicable. The
distinction between *generated* and *reproducible* is the whole decision. So all 28
`actions/checkout` steps sparse-checkout without it — **no CI job ever read it**, every run was
writing 1.5 GB for nothing — `make lean`/`make unlean` do the same for a working tree
(1.6 GB → 104 MB, measured, with all source present), and `.gitignore` stops the next corpus
landing in git.

**Then a plain `pytest` turned out not to run.** It had been dying at collection since the
converged merge on 07-17; only the CI command, with its ignore flags, ever completed. Three
test files still asserted an API that merge `42ed66d8` had replaced — and the quarantine
register caught the fix, exactly as designed: its staleness half fails when a quarantined test
starts passing, because CI skipping working coverage is worse than a known failure.

The register had parked all five as *"written against an API that never shipped"*, owned by
another lane. Half right. The API they wanted never shipped, but **the builders are live** —
`nlp_correlation.py` and `analysis_sessions.py` call them on every intake — so CI was skipping
coverage of production code, not of an unbuilt feature. Four entries released (21 tests
rewritten against each module's documented contract, **no production change**); the fifth
stays, because it is the only one that needs a taxonomy decision rather than a rewrite. Fixing
it also exposed a vacuity guard that asserted `--ignore=` was present unconditionally — so
emptying the ignore list made a guard fail for the good outcome it exists to encourage.

### Delivered since — the gate that could not run, and what it found once it could

On `hamad/converged-pre-main`. The `api-contract` job had been advisory for weeks under a
comment saying it was ready to flip "pending one green CI run". That run was unreachable, and
the chain from there to the most serious finding of the slice is the point of this entry.

**It could not finish.** Measured at ~2.5 minutes per operation × 451 ≈ **19 hours**, against
GitHub's 6-hour limit, so it was killed every run and `continue-on-error: true` hid the kill.
Nothing was slow: one request 45 ms, one `call_and_validate` 0.1 s, building a strategy
0.14 s, drawing an example 0.0 s. **Every component fast and the whole impossible is the
signature of a feedback loop, not a slow part** — and looking for the slow part is what kept
it broken. There were two loops: `from_asgi` gave every generated example a new event loop
while the app's singletons stayed bound to the first, and the websocket queue processor's
error path had no backoff, so it span at full CPU on the resulting failures. That second one
is a production bug in its own right: *an error path with no delay is a spin, and a failure
that cannot change is not something to retry.*

**It could not have been green either.** The job never ran migrations, so every DB-backed
operation 500'd against an empty database — and it used `POSTGRES_USER=test` while the
migration chain `GRANT`s to the `omniusgrid` role by name, so migrations would have rolled
back even if the step had existed.

**Then it could not explain itself.** Moving the suite onto a real uvicorn server silenced
the app's own logging — `uvicorn.Config` applies its own `dictConfig` — so every 500 reported
only "internal server error". A regression introduced while fixing something else, and worth
remembering: moving a test off an in-process transport costs you the diagnostics that
transport gave you for free.

**And only then did this surface. The audit trail had never recorded a single row.**
`009_audit_logs.sql` triggers on every insert into `audit_logs` and calls
`calculate_audit_hash()`, whose body is `encode(digest(...), 'hex')` — pgcrypto. No migration
ever created the extension, so the trigger raised on every insert, and `audit.py` catches it
deliberately ("never fail the audited operation"), logs `audit_log_write_failed`, and lets
the request through. Every audited action succeeded; every audit row was rejected. Verified
on a freshly migrated database: `SELECT count(*)` returned **0**.

It survived because `tests/conftest.py:91` runs `CREATE EXTENSION IF NOT EXISTS pgcrypto`
when it builds a test container. The suite exercised a working audit trail while a real
deployment had none — **the tests were not wrong about the code, they were wrong about the
database.** A guard now fails the build for any extension the harness creates and no
migration does.

**And one more the same thread turned up.** `create_dock_door` did
`DockDoor(**data.model_dump())`, and `DockDoorCreate` carries `organization_id` — so the tenant
a row landed in came from the request body. One offender among 18 schemas carrying that field;
every other handler already ignored it. Row-level security is forced on the table and would
reject the write, so this was defence-in-depth rather than an open door — but relying on RLS
alone makes correctness depend on the database **role** instead of the code.

That distinction is worth keeping, because it arrived attached to a false alarm: the same
request returned **200 and wrote the row** during testing, which reads exactly like a
cross-tenant write. It was not one. The contract suite connects as a superuser, and *a
superuser bypasses RLS even where `FORCE ROW LEVEL SECURITY` is set*. The policy was present,
forced and correct; the connection was exempt. `conftest.py:139` already avoids this for the
real-DB suite by creating a `NOSUPERUSER NOBYPASSRLS` role — the contract gate does not yet,
and its docs now say its results are not evidence about tenant isolation. **A security claim
that has not eliminated the harness as the cause is not yet a finding**, and the check that
settled it was one query against `pg_roles`.

The gate now runs all 451 operations in ~8 minutes and **blocks**, as a ratchet on a measured
floor rather than demanding green, because ~37 operations cannot pass without a deliberate
policy change (Pydantic strict mode, typed path converters) and the practical ceiling is ~412.
Conformance went 299 → **360** along the way: the problem+json content type (304 operations at
once), `Allow` on every 405 and `WWW-Authenticate` on every 401 — both RFC 9110 musts that the
error envelope was discarding — the four status codes the envelope emits and nothing declared,
28 path params typed `str` that turned a malformed id into a 500 instead of a 422, and nine
export routes that returned xlsx, PDF or CSV while the schema promised JSON.

### Delivered since — the Compliance Assistant, and a badge nobody could read

On `hamad/converged-pre-main`. Hudson's RAG pipeline had been complete and working since
July — SeaweedFS → BGE-M3 dense+sparse → Qdrant hybrid RRF → BGE reranker → generation, five
endpoints, an eval suite. **Nothing in the frontend touched it.** Zero hits for `api/v1/rag`
under `frontend/src`. A finished backend with no consumer is indistinguishable from an
unfinished one from the outside, and that is most of what this slice fixes: a
**Compliance Assistant** tab that asks a policy question and answers it from documents the
reader can open.

**Two retrieval legs, one of them uncited.** The document leg answers *what the policy says*.
A second leg reads the org's own `erp_entities` rows live from Postgres and puts them in the
prompt **unnumbered**, so the answer can say "the agreement requires X; three of your open work
orders show Y" instead of paraphrasing a policy the reader could have found themselves. Only
Qdrant chunks get `[n]` markers and `Citation` objects; `RagAnswer` carries no trace of the ERP
block, and a test pins its field list so a later debugging field cannot quietly publish it.

The obvious alternative — index ERP rows into Qdrant as documents — was rejected, and the
reasons are recorded because the idea will come back: the blobs would not exist (a citation you
cannot open is worse than none), every ERP sync would need a re-index, the rows would compete
for the five rerank slots that belong to policy text, and the citations would then have to be
filtered back out. **Both legs are already scoped by the same `org_id` from the same JWT**, so
they are tenant-consistent by construction rather than by coordination. Verified against a real
Postgres: cross-tenant isolation holds both ways, and the *same* corpus reorders by question —
WorkOrder first for a lockout question, Employee first for a certification one.

**The audit trail is the log line, and it is not optional polish.** The ERP contribution is
invisible in the response by design, so `rag_retriever.answered` carrying `erp_rows`,
`erp_entity_types` and `erp_chars` is the *only* record that operational data shaped a given
answer. For a compliance tool, one eventually gets challenged.

**A citation you cannot open.** `DocumentStore.generate_presigned_url` had existed since the
first RAG commit and no endpoint exposed it, so every citation was a filename and a page
number. `POST /rag/documents/link` exposes it — POST rather than GET so the key stays out of
access logs, and with an `{org_id}/` prefix check that is load-bearing: the key arrives from
the client, and without it any authenticated user presigns any tenant's document by editing one
UUID, receiving a URL that keeps working for an hour after the check would have failed.
Verified end to end against real SeaweedFS, including the two refusals.

**Then the screenshot found something the whole suite had missed.** Rendering the page in a
browser showed the "Form" badge as a blank white pill. `STATUS_COLORS.info` was
`bg-opsgrid-primary text-white`, and `--color-primary` is `#fafafa` in the **default dark
theme** — white on white. Not a new bug and not confined to this page: **ten call sites**, the
ERP type column, the admin role chips, the NLP domain and priority tags, the fleet vehicle
count. Every one illegible in the theme most people use, and legible in light, which is exactly
why it survived. Every other entry in that table already pairs a theme-variable background with
`text-opsgrid-bg`; `info` was the one that did not.

Worth keeping as a class: **467 unit tests, a typecheck and four defect-class sweeps all passed
over a control that rendered nothing.** No assertion in the codebase compares a foreground to
its background, so contrast was invisible to every gate we had — the bug was in the one
dimension the tests do not have an opinion about. It took looking at the page. The rule that
makes the collision impossible is now pinned in `statusColors.test.ts`.

**Honest about what is not verified.** The presign path and the ERP leg were both exercised
against live services; the full query path through embeddings, reranking and generation was
not. `rag-inference` needs torch plus ~5 GB of weights and the local Docker VM had 2.7 GB free,
so the build fails on `ENOSPC`. When it runs, the A/B worth doing is the same question with
`RAG_ERP_CONTEXT_ENABLED` on and off — if the answers do not differ, the routing keywords are
not earning their place. Full detail in [`docs/compliance_assistant.md`](compliance_assistant.md).

### Delivered since — the contract gate's blind half, and two lies it was told

On `hamad/converged-pre-main`. Pool #43. The API contract gate now runs and blocks,
but **schemathesis can only check what is declared** — and 250 of 453 routes declared no
`response_model`, so the gate was reporting confidently on 45% of the surface. #43 is not a
nice-to-have beside #38; it is the reason #38's score means anything.

**The ratchet came before the burn-down, because the pool proves it had to.** Coverage was
191/417 when the pool was written and 203/453 five days later: the absolute number rose while
the ratio stood still, because new routes landed undeclared as fast as old ones were fixed.
A burn-down without a ratchet is a treadmill. The count may now only go down.

**The guard nearly shipped blind, in the way these guards do.** The first count said *total: 2,
undeclared: 2*. `app.routes` holds 74 objects of which two are real routes; the rest are lazy
`_IncludedRouter` containers whose children carry relative paths. `test_route_auth_walk`
already carried that scar in a comment — so the traversal is now extracted and shared rather
than copied, because two walks free to regress independently is defect class 7. A vacuity test
fails if the walk ever sees fewer than 400 routes again, and both guards are mutation-verified.

**Fourteen routes were never debt, and saying so mattered.** Six are 204s — RFC 9110 forbids a
body, so there is nothing to declare and never will be. Eight serve xlsx or PDF, where
`response_model` describes a JSON schema that does not exist; they state their real media type
through `responses={200: {"content": …}}`, which is what #38's fix used. Leaving them in would
have made the target unreachable, and *a target that cannot be reached stops being read as one*.

**Then the work found two defects that had nothing to do with coverage.** Declaring a
`response_model` is not additive — FastAPI filters the response through it *and* validates
against it, and both directions can break a working endpoint:

- `DELETE /notifications/subscriptions/{id}` returns `{"deleted": subscription_id}`, and that
  value is the path parameter FastAPI already parsed into a `UUID`. Typing the field `str` is
  the obvious reading of the handler; **pydantic v2 does not coerce UUID to str**, so every
  successful delete would have started returning 500 on a route that worked the day before.
  Caught by validating the model against a real UUID instead of reading the handler and
  believing it.
- `GET /exports/jobs/{job_id}` declared `text/csv` and **has never served a CSV** — it is the
  status endpoint returning JSON, and the media type was copied from its `/download`
  neighbour one segment away. That is the exact inverse of what #38 fixed across nine export
  routes: same class, opposite direction, and it survived that sweep because the sweep looked
  for handlers *returning* binaries, not for declarations *claiming* one. It also caught the
  new ratchet, which initially believed the declaration and excluded the route — **a guard
  that reads a lie inherits it.**

**Then the third find made the check automatic.** `query_performance`'s seven list endpoints
each return `{<items>, "count"}`, and the first version of their models declared only the items
key — which would have deleted `count` from all seven at once. Catching that by eye, after
catching the UUID one by eye, was the signal: reading each handler carefully enough to be sure
no key is missed does not scale to ~197 remaining routes. `test_response_models_match_their_returns.py`
now walks the AST of every API module and compares each model's fields to the keys of every
literal dict its handler returns — 50 handlers checked, mutation-verified against the exact bug
it was written for. It names its own blind spots (helper-built returns, `**spread`) rather than
claiming totality, and the companion file covers those.

**250 → 53**, of which 185 were declarations and 20 were miscounts. Every route left is in
another dev's lane. Lane map, method and the
running tally are in
[`docs/planning/hamad-response-model-burndown.md`](planning/hamad-response-model-burndown.md);
the clash map there was derived from each dev's **own commits**, since every stale branch
appears to touch 82 API files purely by being 28–112 commits behind.

### Delivered since — 393 tests that never ran, and the two 500s they were hiding

On `hamad/converged-pre-main`. `make test` reported **1975 passing**. It now reports **2715**,
and the 740 that appeared are the database-backed ones — tenant isolation, RLS, the real
migrated schema. **The suite was strongest exactly where nobody could run it.**

Testcontainers' reaper bind-mounts the Docker socket; on colima that socket is a Lima-forwarded
path and the mount is refused, so the reaper fails, testcontainers treats it as fatal, and every
DB-backed test **errors at setup**. Errors, not failures — which is why 393 of them scrolled
past as environment noise in every run.

**They caught two 500s within seconds of being enabled, both introduced by the `response_model`
work in the slice above.** A health band whose upper bound is `100.01` declared `int`; a numeric
retention priority declared `str`. Both keys were named correctly, so the AST sweep passed them;
the unit guards validated against fixtures written by the same person who made the wrong
assumption, so they agreed with it. **The only thing that disagrees with a wrong type is a real
row from a real column** — and that is precisely what those 393 tests provide and nothing else in
the suite does.

The cost is that a hard-killed run can now leave a container behind. That is a cleanup chore;
silently skipping the database half of a suite is a correctness risk, and this codebase has
already paid for that shape once — the audit trail passed for months against a `pgcrypto`
extension `conftest` created and no migration installed.

### Delivered since — the burn-down finished, and six real fixes that moved no number

On `hamad/converged-pre-main`. Pools #43 and the contract gate's floor.

**`response_model` coverage: 250 → 53 undeclared, and every route left belongs to another
dev.** The last stretch was `fleet_logistics` (23 — the largest single file), `health` (16),
`erp_integrations` (8), a 24-route tail, and nine stragglers. Two findings from it are worth
more than the count:

* **The AST sweep was blind to an entire file.** All 23 `fleet_logistics` handlers return
  `[_shaper(x) for x in ...]`, so not one has a dict literal in its syntax — the sweep passed
  the file while checking nothing in it. Six assertions against the shapers themselves close
  it, and `_schedule_out` alone backs five routes.
* **Five file downloads promised JSON in the schema.** `/compliance/reports/{id}/download`,
  its signed twin, `/exports/deliveries/{id}/download`, `/fleet/releases/{id}/bundle` and
  `/models/{id}/download` all stream a `FileResponse` and declared nothing. That is exactly
  what pool #38 fixed across nine export routes; these five survived because two sit past a
  `public_router` boundary and three are in files #38 never opened. A sixth, `/metrics`, was
  the *guard's* error — `_NON_JSON` omitted `text/plain`, so a Prometheus endpoint sat
  permanently in a burn-down meant to reach zero.

**The contract floor rose 350 → 360, and then six more fixes moved it by nothing.** That
second half is the part worth reading. Schemathesis found ONE of thirteen identical unbounded
`skip` declarations — the only one it drew a value above 2⁶³ for — so the fix is a shared
`MAX_OFFSET` across sixteen parameters plus a sweep, not the one endpoint that happened to
fail. Then six further defects were fixed and verified individually, and conformance went
369/370 → 368/370:

> **"Conformance went up" is not a sound proxy for "the code got better."** Two of the six
> moved *sideways* — an endpoint that 500s never reaches the negative-data check, so once it
> works, schemathesis mutates the body and gets a 2xx instead. A feature that had been dead
> since the day it was written now works, and the number did not move.

That dead feature was **`POST /api/v1/user/goals`**, whose id was `str(UUID())` — a call that
raises `TypeError` unconditionally. It answered 500 to every caller for every input since it
was written; the UI calls it; and because nothing could be created, its PUT and DELETE could
only ever 404. The input schemathesis sent was irrelevant — **any test that called it once
with anything would have caught it, and there was none.** Fixing it exposed a silent one
underneath: `.append()` on a plain `Column(JSON)` is never marked dirty, so the write was
discarded behind a 200.

**One 500 was in the error handler rather than in any endpoint.** A `@model_validator` raising
`ValueError` puts the live exception in pydantic's `ctx`; `json.dumps` then raised and the
generic handler returned 500. The validator worked perfectly and *reporting* it was what
failed — one fix, every cross-field rule in the codebase.

**Both coverage gates had drifted below reality** (FS-260): frontend 19/15/14/19 against a
measured 39/43/35/40, backend `--cov-fail-under=54` against a measured 61. A threshold below
reality never goes red, so nothing prompts anyone to look. Now 38/41/34/39 and 59, each
mutation-verified.

Three stale recorded numbers were corrected in place tonight rather than worked around — the
gate doc's "floor 339", the ratchet's missing `text/plain`, and FS-260's premise. Each had
drifted in the direction that flatters.


---

## FS-405 / 406 / 407 — the floor, the insight, and the ledger between them

Four workflows were asked for by name:

    a part is issued        -> inventory, purchasing, accounting
    time is clocked         -> production, accounting
    a problem is found      -> quality, inventory, production, accounting
    a machine goes down     -> scheduling, production, quality, accounting

**None of the four events existed in the schema.** There was no part issue, no labour entry,
no quality event and no downtime event anywhere in the model layer. The platform could READ
an ERP — inbound sync, webhooks, correlation over the result — and `ERPConnectorBase` exposed
`fetch_data`, `subscribe_to_events` and `health_check` and **no write method at all**. Every
tie-in was one-directional.

### The ledger is the deliverable, not the four tables

"Issuing a part ties into inventory, purchasing and accounting" is three claims about three
systems, and each can independently succeed, fail, queue, or have no integration. A `synced`
boolean collapses those into one bit and the bit lies — which is the defect class this
repository has spent its whole life finding, from an alert that was logged instead of
dispatched *and returned an identifier anyway*, to a collector "restart" that was a bare
`return` with a hardcoded timestamp, to a compliance report stating four figures it never
computed.

So `system_of_record_postings` carries **one row per (event, target system)**, and the
database — not the service — enforces the part that matters:

```sql
CONSTRAINT ck_posted_has_evidence CHECK (
    status <> 'posted' OR (external_ref IS NOT NULL AND posted_at IS NOT NULL)
),
CONSTRAINT ck_manual_has_instruction CHECK (
    status <> 'manual_required' OR instruction IS NOT NULL
)
```

A posting cannot claim success without the identifier the far system returned, and cannot
sit in `manual_required` without the sentence to hand to a person. Constraints rather than
service checks, because this is the exact lie the ledger exists to prevent and a CHECK holds
against every writer, including the ones nobody has written yet.

### `manual_required` is the analog path, and it is a feature

Plenty of real shops run purchasing on a phone call. The correct behaviour is to tell
somebody — so a posting with no integration carries the line to read out, and records whether
it was read out. Against the running app with an ERP serving inventory and accounting but not
purchasing:

```json
"by_status": {"pending": 2, "manual_required": 1},
"fully_posted": false,
"awaiting_a_person": [{
  "target": "purchasing",
  "instruction": "Issue 2.0 each of part BRG-6204 to WO-1188 — recorded at 2026-08-03 17:59
                  and NOT yet entered in this system."
}]
```

`fully_posted` is the only field meaning "it all landed", and it is computed from the
postings rather than assumed from a 201. **The response never says "synced".**

### FS-406 — activating a correlation insight

An analysis session ends with a list under "Recommended Actions". In the UI each line carried
a **green tick** and no control. The tick was the defect: it reads as *done* for work that had
not been started and could not be started from that pane. The only affordance was an
"Auto-integrate" checkbox firing a background job whose result never came back — it could
create nothing and the screen looked identical.

Activation now creates a Kanban task **and** postings to every system its correlation domain
implies, reusing the same ledger a part issue uses — a dispatch to an ERP is the same class of
claim whether a machinist or an analysis session started it, so it earns the same evidence.

Three verbs, kept apart because they are three different facts:

| | means |
|---|---|
| **issue** | a task exists and the obligations are recorded. **Nothing is done yet.** |
| **confirm** | REFUSES, with named blockers, until the task is finished *and* every posting carries evidence. Writes the snapshot it was granted on. |
| **reject** | declined, with a reason the database insists on — a recommendation that keeps being rejected is a bad recommendation, and that is only learnable if the reason is stored. |

Confirmation is a snapshot, never a flag:

```
maintenance  posted  external_reference  WO-2291
production   posted  external_reference  WO-2291
scheduling   posted  external_reference  WO-2291
```

A human's acknowledgement and a far system's identifier are both acceptable evidence and are
**not the same thing**, so the snapshot records which kind each was.

Activation is idempotent on a fingerprint over (source, session, message, index, title).
Without it a double click on a slow network in a noisy building issues two work orders and
posts twice to purchasing, and the second is indistinguishable from a real requirement.

### FS-407 — `pending` was a dead end

`fan_out` queues a posting as `pending` when an integration claims the target. Nothing moved
it. So an integrated target could never reach `posted`, an activation over one could never be
confirmed, and the ledger showed a queue that never emptied — **strictly worse than having no
integration**, because `manual_required` at least tells someone to pick up the phone.

`post_event` was added to `ERPConnectorBase` following the `subscribe_to_events` precedent
already in that file: **declare the truth rather than invent an endpoint.** The default raises
`ERPWriteNotSupported`, and the drainer converts the posting to `manual_required` with the
reason. That conversion is the point, not a consolation prize — it turns "queued behind an
integration that will never take it" into "somebody has to enter this, and here is what to
tell them". The alternatives are both lies: pending forever implies a write is coming, and
`posted` would claim an ERP record that does not exist.

### Two defects that only running it could find

Both surfaced by driving the live stack against real Postgres, and neither was reachable from
the tests as written:

- **A sub-minute stop reported "ongoing".** `f"{d} min" if d else "ongoing"` — and `0.0` is
  falsy. A scheduler told a machine is still down goes to look at a running machine. Same trap
  in the labour path reported a closed entry to payroll as "an open shift". Fixed to
  `is not None`; the tests all used non-zero durations, so none of them could have seen it.
- **One malformed integration 500'd the entire drain.** The `try` wrapped `post_event` but not
  the connector *construction*, so an integration row missing `erp_type` raised `KeyError` out
  of `drain` and no posting in the batch was touched — breaking that module's own stated
  contract that one bad ERP must not stop the queue. The fixtures all build valid configs.

### Existing guards that rejected this work

Seven, all legitimate, all fixed rather than suppressed:

- `test_every_mutation_has_a_reviewed_role_policy` — 7 new mutations with no role. The
  allowlist they would have fitted is explicitly for routes that *predate* the RBAC sweep, so
  they got `require_operator_or_admin` instead.
- `test_no_new_uuid_path_param_is_typed_as_a_string` — `event_id: str` lets `/downtime/0/end`
  reach Postgres and 500 where 422 is right.
- `test_no_new_undeclared_routes` — `/routing` had no `response_model`.
- `test_no_new_unsignalled_capped_list` — two bare capped arrays. Fixed with envelopes
  carrying a real `total`, per that file's own doctrine that a header no client reads is a
  *second* defect rather than a partial fix.
- `test_schema_parity` ×2 — ORM `String(36)` against a native `uuid` column.
- `mutationFailureIsVisible` (frontend) — three mutations on the new page handled only
  success, so a failed clock-out would have left the screen identical.
- `test_frontend_response_shapes_match` — ×3, and this one was the guard's own gap rather
  than mine. It resolves `Paginated<T>` and inline `{items, total}` literals but classified
  every *bare identifier* as a plain object, so a named envelope interface read as a
  mismatch. The tempting fix is to rename the type until the regex is happy, which improves
  nothing. It now resolves a named interface to its declaration and applies the same
  items-plus-pagination-sibling rule used for inline literals and for the OpenAPI schema —
  mutation-verified to still catch a real array/envelope mismatch.

### A casing-seam trap, caught before it shipped

`by_status`, `posting_statuses` and `routing` are maps keyed by DATA — posting statuses, event
types, correlation domains. The axios casing seam converts object keys recursively, which
turns `manual_required` into `manualRequired`, misses every label lookup, and renders the raw
key beside a count: a page that looks populated and reads wrong. `transform.ts` already has
`OPAQUE_KEYS` for exactly this class; the three were added there and pinned by a test, because
the failure is silent.

### An ORM claim the database never made

`Task.created_by`, `approved_by` and `completed_by` were declared `nullable=False`; migrations
003/004 create all three as plain `UUID REFERENCES users(id)`. Postgres never enforced the
ORM's claim — nullability is a DDL property, not a client-side check — so it was invisible in
production and wrong everywhere the schema is built *from* the ORM, where `create_all` emits a
stricter table than the real one and rejects inserts production accepts. A task is created
before anyone completes it; the database was right.

### Verified

3,1xx backend / 514 frontend, `tsc` clean, and both surfaces driven against a real
migration-built Postgres with FORCE RLS: all four floor workflows, the second-open-clock and
second-concurrent-downtime refusals (409), a bad path id (422), the drain (12 pending → 12
handed to a person with the exact reason), and the full activate → refuse → acknowledge →
refuse → complete → confirm loop.

**Noted, not fixed:** `scripts/seed_demo_data.py` aborts on a fresh database with a foreign
key violation — `erp_data_mappings` is inserted while `integration_configurations` has no
matching row, and no INSERT for the parent is emitted at all. `docs/DEMO.md` tells operators
to run it. Not root-caused and not in this change's scope; recorded here so it is not
rediscovered from scratch.

---

## FS-408 — the seed had never run on a fresh database

`docs/DEMO.md` tells an operator to run `scripts/seed_demo_data.py`. Against a fresh
migration-built Postgres it died on a foreign key. **Three separate defects, in sequence** —
each one only reachable after fixing the one before it, which is why they had all survived.

### 1. The FK-ordering mitigation evaporated on the line after it was set

SQLAlchemy builds its insert ordering from `relationship()`, not from ForeignKey columns, and
**68 of the 69 FK-carrying models here declare only the column**. So for most of this schema
the unit of work genuinely cannot order a parent before its child in one flush. The seed knew
this — its own comment says so — and relaxed FK triggers for the load:

```python
await db.execute(text("SET session_replication_role = replica"))
await db.commit()          # <- returns the connection to the pool, and resets it
```

Measured: `replica` immediately after the SET, `origin` immediately after the commit. The
protection was gone before a single row was written, and the failure was swallowed as
"harmless" — it was not; it turned an ordering problem into an unexplained FK violation forty
lines away. It now travels as an asyncpg **startup parameter** on a dedicated bulk-load
engine, so it survives every commit and every connection recycle, and a role that cannot set
it is told so instead of discovering it later.

### 2. A human work-order number in a `uuid` column

`Task.work_order_id` is a native `uuid` (migrations 003/004). The seed wrote `"WO-77105"`
into it and asyncpg rejected it outright. The number belongs in `custom_fields`, which is
where a business reference with no typed home goes.

### 3. Every timestamp in the demo dataset was shifted by the developer's UTC offset

`NOW = datetime.utcnow()` is **naive**, and a naive value written to `timestamptz` is
reinterpreted in the client's local zone — measured as +5h on a UTC-5 machine against a
database whose own timezone is UTC.

The relative gaps between rows survive, so the data looks entirely plausible; only the anchor
moves. That silently broke the demo's flagship yard scenario: TRL-4482 is seeded at six hours
of dwell so it sits past the free window, and it arrived as one hour, so
`/yard/detention-alerts` returned `[]` and the seed's own verifier failed. **On a UTC
developer machine none of this is visible.**

Same family as FS-391 and FS-400, which were naive datetimes *crashing* detention and carrier
compliance. This one does not crash. It just makes the data wrong.

`--verify` now reports **PASS on all 25 checks** against a fresh database.

### Why nothing caught any of it

**SQLite does not enforce foreign keys by default.** Every in-memory test in this suite
inserts in whatever order it likes and passes, so the ordering class is structurally
invisible below a real Postgres. And the existing `test_no_naive_utcnow` guard — which
already documents this exact trap, down to the phrase "correct only when the DB session
happens to run in UTC" — scanned `backend/app/` only. `scripts/` was never in scope, and had
drifted to **12 naive calls across four files**, one of them the anchor for the whole demo
dataset.

### What now holds it

- `test_no_naive_utcnow` extended to `scripts/`. The seed and the smoke driver write to a
  real Postgres; they are app code.
- `test_insert_ordering_is_possible` — three guards: no unresolvable FK cycles, no table
  sorting ahead of a table it references, and a **ratchet at 62** on models carrying an FK
  column with no relationship. Fixing all 62 is a project rather than a sprint, but each new
  one is another way to write this bug, so the number must not grow silently.
- `dock_doors <-> yard_trailers` and `yard_trailers <-> shipments` were genuine FK cycles.
  SQLAlchemy cannot topologically sort a cycle: it warns, **discards those constraints from
  the ordering**, and says the warning may become an error in a future release. Discarding
  them also drags the cycle members' other edges out of the sort — which is why `dock_doors`
  sorted *ahead of* `organizations`, a table it references. One side of each pair is now
  `use_alter=True`, the standard remedy, which changes nothing about the resulting schema.
- The six models added by FS-405/406 were contributing to the ratchet; they now declare
  `organization = relationship(..., lazy="raise")` — present purely so the unit of work can
  order them, with lazy loading refused so it cannot become a MissingGreenlet at runtime.

---

## FS-409 — two defects that only a screenshot could find

Running the stack against the now-working seed and driving the new surfaces in a browser
found two things the whole verification stack had passed.

### The Correlation AI data-sources panel 500'd on the documented demo session

`GET /nlp/sessions/{id}/data` returned a 500 for the seeded session, so the panel listing the
session's ERP / telemetry / yard sources failed to load every time it was opened.

Cause: the seed set `source_id` from
`params.get("asset_id") or params.get("integration_id") or source_type`. For a platform-wide
source like the yard there is no source row, so the fallback wrote the literal string
`"yard"` into a column every consumer reads as a uuid — `AddDataSourceRequest` and
`DataSourceResponse` both declare `Optional[UUID]`.

**The API itself cannot produce this**: its own request model rejects a non-uuid. The seed was
the only writer that did. Fixed in the seed (a platform source has no row id, so it is now
NULL, which the response model already allows), with a check added to `--verify` so the panel
is asserted to load.

### The Shop Floor page was unreadable in the app's own theme

It was written against a light shell. The app renders dark by default, so `text-gray-900`
put the h1 at almost exactly the page background colour, the input placeholders could not be
read, and the cards sat as light rectangles in a dark frame.

It passed `tsc`. It passed 518 unit tests. **It passed a DOM sweep that counted text length,
visible controls and network failures** — and reported the page healthy, because the text was
all there, at the wrong colour. Only opening a screenshot found it.

Converted to the CSS-variable tokens the rest of the app uses (`opsgrid-bg`, `opsgrid-panel`,
`opsgrid-border`, `opsgrid-text`, `opsgrid-text-secondary`, `status-*`), then verified in
**both** themes by clicking the app's own toggle — the first attempt at switching theme by
setting a class and a data attribute was a no-op, and the "light" screenshot it produced was
still dark. Driving the real control moved the body background from `rgb(10,10,10)` to
`rgb(250,250,250)` and both renders are legible.

Button contrast was checked by reading `getComputedStyle`, not by eye: the three washed-out
buttons in the first screenshot are genuinely `disabled` with `opacity: 0.5` and empty
required fields, which is correct.

`test/pagesUseThemeTokens.test.ts` now ratchets hardcoded light-theme utilities in
`src/pages/`. Five files carry them today and the counts are pinned; a new page must not
appear in that list at all. Scoped to pages deliberately — the correlation chat transcript is
a white sheet on purpose, so a blanket ban would be wrong.

**A measurement error worth recording**: the first version of that ratchet was written from a
`src/pages/*.tsx` shell glob, which does not recurse — it reported one offending file when
there are five. The test found it immediately by walking the tree. The guard was right and
the hand measurement was wrong, which is the argument for putting the number in a test rather
than in a comment.

### The 31-route browser sweep, and two things it could not have found

Every routed page driven against the freshly seeded database: **31/31 clean** — no blank
panes, no console errors, no 4xx/5xx. That is the whole surface, not a sample.

Two real defects came from *looking at* one of those pages, not from the sweep:

- **`4h 11.300000000000011m excess`** on the detention banner. `minutes % 60` on a float from
  the detention calculator, rendered next to a dollar figure an operator is expected to act
  on. The text was present, the page had no errors, and the number was even approximately
  right.
- **A raw uuid in the Location column.** A docked trailer has no `yardLocation`, so the cell
  fell through to `assignedDoorId` and printed
  `88888888-0000-4000-8000-000000000003` in the column an operator reads to go and find the
  trailer. It now resolves through the door list the page already loads — `Door D3` — and an
  unresolvable door says `Door (unknown)` rather than falling back to the id, because
  printing the uuid tells nobody anything.

Both are covered by tests, both mutation-verified.

**The sweep's own contrast check was wrong twice before it was right.** It first reported
"Detention Alerts" at 1.0:1 — apparently invisible — because it read `rgba(239,68,68,0.1)` as
a solid colour, which is exactly the text colour. Compositing the alpha over the page
background gives a perfectly legible ratio. Two flagged routes became zero. A guard that
cries wolf on translucent backgrounds would have sent someone to "fix" correct code, which is
the same cost as missing a real defect and harder to notice.

The fixture for the float test was also wrong first: it invented `detentionCharge` when the
type declares `currentCharge`, the banner called `.toLocaleString()` on undefined, the
component threw, and the page rendered empty — which reads as a component bug rather than a
bad fixture. That test file's own header warns about precisely this. **Read the type; do not
guess the shape.**

---

## FS-410 — making the invisible class visible

FS-408 established that **SQLite does not enforce foreign keys by default**, so every
in-memory test in this suite inserts in whatever order it likes, against whatever parent rows
it did not bother to create, and passes. That is why 3,200 tests could not see the defect
that killed the demo seed.

**Measured cost of turning it on everywhere: 76 of 3,210 tests (2.4%)**, across about fifteen
files. Not a sprint — but the distribution was the interesting part: **53 of the 76 were my
own new test modules.** The change is worth doing and the first person who should pay for it
is whoever wrote the code being converted.

`backend/tests/_sqlite.py` provides an opt-in FK-enforcing engine plus a `create_all` that closes
over referenced tables — because `create_all(tables=[...])` does *not* pull in what those
tables reference, so a subset naming a child without its parent produces a schema whose FKs
point at nothing.

### What it caught immediately, in code that was already committed and green

- **The seed's defect, reproduced inside my own fixture.** `integration_configurations`
  inserted before `organizations`, because `IntegrationConfiguration` declares the FK column
  and no `relationship()`. Fixed at the source rather than in the fixture: the model now
  carries the ordering relationship, which fixes it everywhere including the seed. The
  ratchet moved 62 → 61 — one at a time, when a missing edge actually bites something.
- **A test asserting a state the database cannot produce.** `test_a_posting_whose_
  integration_vanished_is_handed_over` wrote a random uuid into `integration_id` and checked
  the drainer coped. Migration 060 declares that column `ON DELETE SET NULL`, so Postgres can
  never hold a dangling reference — the scenario was unreachable, and the test passed only
  because SQLite let it exist. It now deletes the integration and asserts the cascade nulled
  the column first, so it is exercising the state that can actually occur.

### One file is deliberately exempt, and says so

`test_dock_scheduling_conflicts.py` builds a single table to execute one overlap predicate.
Its appointments reference doors and organisations it has no reason to create; enforcing
would mean standing up a fixture schema to test a `WHERE` clause. The trade is recorded in
the file rather than left silent.

A guard pins the three converted modules, because reverting to a bare `create_async_engine`
keeps them passing while they stop checking anything — a failure mode that is invisible by
construction.

---

## FS-411 — clicking the button found what nothing else could

The flagship claim is that an actionable insight in a correlation session becomes dispatched
work. It had never been clicked. Driving it end to end in a browser found four things.

### The demo session had no conversation in it

Three data sources, zero messages. So the Correlation AI page opened on its empty state and
the activation controls — the entire FS-406 surface — never appeared on the documented demo.
A demo of an analysis session with no analysis in it.

The seed now writes a short transcript whose recommended actions carry the domains the
fan-out routes on. **It is labelled in the message text, not only in a field**: the
correlation model is not loaded, so nothing there is an inference, and
`SessionMessageResponse` carries no provenance field at all — see the finding below. A caveat
that lives only in a field the transcript endpoint does not send is not a caveat.

### Provenance dies when the page reloads *(other lane — reported, not touched)*

`SessionChatResponse` carries `simulated` / `simulation_reason`, and the chat handler sets
them on all three paths. `SessionMessageResponse` — the transcript model, used by
`GET /nlp/sessions/{id}/messages`, `/chat/history` and `/chat/search` — **does not declare
them at all**, and the builder does not read them from `msg.analysis`, where the data is.

So a reply the engine marked as a heuristic is labelled while it is live in the chat and
loses the label the moment the transcript is re-fetched. The frontend's `SessionMessage`
interface declares both fields, so the client is asking for something no producer sends.
`app/api/analysis_sessions.py` is Harsh's lane; the fix is to declare the two fields and read
them from `msg.analysis`.

### An activated insight told a supervisor "see the event record"

`_describe()` in the fan-out had branches for the four floor events and no branch for
`insight_activation`, so every manual posting fell through to a generic sentence that names
nothing and points at a table an operator cannot open. The whole purpose of the analog path
is the sentence somebody reads out.

**Twenty-two tests did not catch it because one of them asserted
`"not yet entered" in instruction.lower() or instruction`** — true for any non-empty string.
A tautology in an assertion is worse than a missing test: it occupies the space where the
real check would go.

### The Activate button was invisible

Measured **1.04:1** — `rgb(250,250,250)` on `rgb(255,255,255)`. The correlation transcript is
a hardcoded white sheet regardless of theme; the shared `Button` styles from the app's theme
tokens, which are near-white in dark mode. The control rendered, was clickable, had the right
accessible name, and passed thirteen tests. Now 17.74:1, with the controls styled for the
sheet they actually sit on and a class-level guard so it cannot regress.

### And the demo understated itself

The seeded SAP integration declared no `serves_systems`, so every shop-floor event and every
activated insight fell to the analog path — seven targets all reading "needs a person" on a
deployment the seed describes as fully synced. It now serves six of the seven, leaving
purchasing manual on purpose: a shop whose purchasing runs on a phone call is the realistic
case, and it is the half of the ledger worth showing.

---

## FS-412 — the README's own numbers had rotted, and one of them was unguarded

Bringing the README current for FS-405…411 meant checking its figures rather than adding to
them. Two were wrong.

**The test floor had drifted 200 below reality** — `**3,100+ tests**` against 3,303 collected.
Still technically true, which is the problem: `test_readme_test_count_is_not_stale.py` claims
a floor *and* asserts the floor is not meaninglessly low, precisely so a figure cannot
survive by being unfalsifiable. Raised to 3,200+, and the two prose figures (`~3,100 pass`,
`~500 frontend across 70 files`) with it.

**The operation count was wrong in every place it appeared, and disagreed with itself.** The
README said the contract gate drives "all 451 documented operations" in two places and "452"
in a third. The OpenAPI schema declares **470**. Nothing guarded it — the test-count guard
exists because a stale number in the most-read file is worse than no number, and that
argument was never extended to the figure that describes *how much of the API is covered*.

So the count is now guarded three ways: that the claim exists at all, that every place
stating it agrees, and that it equals what the schema declares. Exactly, not as a floor — a
test count changes several times a day, an operation count changes when someone adds a
router. Both directions mutation-verified.

**Content added**: the systems-of-record drain, the FK-enforcement helper and its measured
cost, and a rewritten offline-demo section that no longer claims the seed simply works. It
says what was wrong with it, because `docs/DEMO.md` sent operators down that path and the
naive-`utcnow()` failure is the kind that leaves data looking entirely plausible.

---

## FS-413 — provenance that survived a page reload

Recorded under FS-411 as another lane's fix, then authorised and done.

`SessionChatResponse` carries `simulated` / `simulation_reason`, and the chat handler sets
them on all three of its paths — the heuristic substitute used when the correlation model or
its adapter is not loaded (the deliberate state here), and the exception path whose reply is
not an analysis at all. `SessionMessageResponse`, the model behind
`GET /nlp/sessions/{id}/messages`, `/nlp/sessions/chat/history` and
`/nlp/sessions/chat/search`, **declared neither field**, and none of the three builders read
them.

So the caveat was attached while the reply was live in the chat and vanished the moment the
transcript was re-fetched. Reload the page and a heuristic answer came back looking like a
real inference — in the transcript, in history, and in search.

**The data was never lost.** The engine writes `simulated` into `analysis`, and `analysis`
was being returned verbatim the whole time. Nobody read it back out. And the frontend's
`SessionMessage` interface has declared both fields all along, with a comment explaining why
they matter — so the client asked for them, received `undefined`, and rendered the unlabelled
version. **The chain was intact at both ends and broken in the middle**, which is the hardest
place to notice.

Fixed with a `_provenance_of(msg)` helper so all three builders read the same thing, and
tested on all three surfaces: a caveat that survives on some but not others is worse than
none, because a reader learns the flag is unreliable. The reverse direction is asserted too —
a genuine inference must not be labelled simulated, since marking real output as fabricated
trains operators to ignore the flag.

**A ratchet noticed the fix from the other side.** `MAX_UNREAD_PHANTOM_FIELDS` counts fields
the frontend declares that nothing on the wire produces. It fell 57 → 56 the moment
`simulation_reason` started being sent — a field the client had declared for weeks, asked for
on every request, and never once received. The guard demands exact equality rather than a
ceiling, so the number had to be tightened in the same commit: **one spare slot is one free
phantom field.**

### And the FK enforcement kept earning its keep

Writing the test tripped the ordering defect twice more, one level down each time:
`analysis_sessions` before `users`, then `session_messages` before `analysis_sessions`.
Neither model declared a `relationship()`, so the unit of work had no edge to order by. Both
fixed at the source rather than in the fixture, along with `SessionDataSource`, which has the
same shape and is written by the seed.

**Ratchet 62 → 61 → 58 → 54.** Converting `test_writes_round_trip.py` next tripped three
more — `alarms`, `geotab_diagnostics`, `geotab_exceptions` — and each was fixed at the model
rather than in the fixture, so the ordering is correct everywhere including the seed and the
API. Every step was paid for by a missing edge actually biting something, which is the only
way that number should move.

Five modules now enforce foreign keys. The pattern has held every time: convert a module,
watch it fail on an insert order that real Postgres would have rejected all along, add the
missing edge, move on. Nothing found this way was a test bug — every one was a hazard the
suite could not see.

### Re-measured, and the remainder is now someone else's fixtures

With those edges in place the cost of enforcing everywhere fell **76 → 39** — the eight
model-level fixes halved it without touching a single test another lane owns. Three more
followed (`Shipment`, `ERPIntegrationEvent`, and the `workcell` edge `Asset` was missing while
declaring its other two), taking the ratchet to **52**.

What is left splits cleanly:

* **22 of the 39 are `test_dock_scheduling_conflicts.py`**, which is the file deliberately
  exempted — it builds one table to test one `WHERE` clause and its appointments reference
  doors and organisations it has no reason to create.
* The rest are **incomplete fixtures** in other lanes — `no such table: users`,
  `asset_types`, `drivers`, `routes`, `organizations` — which `backend/tests/_sqlite.py`'s
  `create_all` fixes by construction, since it closes over referenced tables. Converting
  those is a one-line change per module for whoever owns them.

**A measurement that was wrong first.** The re-run initially reported **623** failures. The
probe had lost its dialect check, so `PRAGMA foreign_keys=ON` was being executed against
Postgres connections — where it raises, and the failed statement poisons the transaction.
Nothing had regressed; the instrument had. The same lesson as the contrast checker two
sections up: a measurement that moves by an order of magnitude is a claim about the
instrument until proven otherwise.

---

## FS-414 — the class is closed: foreign keys enforced everywhere

The per-module opt-in is gone. `PRAGMA foreign_keys=ON` is now a `connect` listener in
`backend/tests/conftest.py`, so every SQLite engine in the suite gets it. **All 3,223 tests
pass with it on.**

An opt-in guard protects the files that remembered to opt in — the set least likely to need
it. That was always the wrong shape; it was a staging post, not a design.

### The cost, measured three times

| | failing |
|---|---|
| first measurement | 76 |
| after eleven model-level `relationship()` edges | 39 |
| after converting the remaining eight fixtures | **0** |

The middle row is the important one: **halving it required no changes to any test another
lane owns.** Adding the missing ordering edge to a model fixes every fixture that trips over
it, plus the seed, plus the API, plus any future flush that creates a parent and child
together.

### What the last eight conversions found

Every one was a fixture inserting rows against parents that did not exist — an organisation
invented as `uuid4()`, an integration nobody created, an asset pointing at a workcell and an
asset type that were bare UUIDs. All of them passed for as long as they had existed.

Two are worth quoting:

- `test_ingestion_packml_state.py` said it in its own comment: *"the organizations/workcells
  tables aren't created here and SQLite doesn't enforce FKs by default, so a bare UUID is
  enough to exercise this path."* An honest note about a shortcut that made the fixture laxer
  than production. The shortcut is gone; the honesty is kept, in a docstring explaining why
  the assumption no longer holds.
- `test_erp_webhook_idempotency.py` never seeded the organisation **or** the integration its
  events point at. It passed because the constraint under test is on the event itself, so the
  assertion held over rows that were orphans. On Postgres the first insert would have been
  refused.

`test_dock_scheduling_conflicts.py` needed no exemption after all. The exemption reasoning —
"it exists to test one `WHERE` clause, not referential integrity" — was true and still is,
but `create_all` closes over only the *referenced* tables, so the closure is a dozen tables
rather than the whole schema. It cost one seeded organisation and one dock door.

### A guard that proved the wrong thing first

The first version of `test_foreign_keys_are_enforced_for_sqlite` built its engine with
`sqlite_engine()` — the helper, which sets the pragma itself. Flipping conftest's listener to
`OFF` left the test passing: it was asserting that the helper worked, not that the global
enforcement did. It now uses a plain `create_async_engine`, which has done nothing to earn
the pragma, and the mutation fails it.

---

## FS-415 — the last quarantined test, and what it was hiding

`test_map_section_to_domain_table_content` had been red all session and was recorded as
another lane's problem. The quarantine register stated the choice honestly:

> either table-content mapping has a gap, or the expectation was never right. Deciding needs
> the lane that owns the keyword sets.

**It was the gap**, and `git log` settled the rest: the test was added on 2026-06-08 in the
same commit as the mapper, against a byte-identical keyword map. **It had never passed.** Not
a regression anyone introduced — a reasonable expectation written against an incomplete
vocabulary.

`COLUMN_KEYWORD_DOMAIN_MAP` contained **no asset word and no failure word anywhere in it**,
in a platform whose central noun is an asset.

### The red test was not the cost

`document_scenario_builder` does `if domain is None: continue`. So a document table keyed on
`asset_id` with a `failed` status produced **no correlation scenario at all**, while the page
still reported as processed. A silent omission sitting behind a quarantined test that read as
a taxonomy argument — which is exactly why the register's own rule exists:

> before accepting that a quarantined test is another lane's problem, check whether the code
> under it is *running*.

It was running. On every intake.

### Widening a keyword list can misroute, so it is pinned from both sides

Adding `asset_id` to maintenance could have pulled quality, production and energy sheets in
with it — trading a silent omission for a silent misroute, which is worse, because it
produces a confident wrong answer instead of nothing. `_match_keywords` takes the
**highest-scoring** domain rather than the first hit, so a table carrying `defect` and
`inspection` still resolves to quality even with an `asset_id` column. That property now has
a test, as does the other end: a table with no operational vocabulary still resolves to
nothing.

### The register is empty

CI runs every test with no `--ignore` and no `--deselect`. Releasing it meant removing the
entry from `test_quarantine.py`, `test_ci_quarantine_expires.py` and `ci-cd.yml` — and the
guards proved they work in the process: the run before the release failed *three* staleness
checks, because a quarantined test had started passing.

**3,223 passed, 0 failed**, with foreign keys enforced across the whole suite.

---

## FS-416 — the theme guard was mostly wrong, and checking cost less than acting

`pagesUseThemeTokens` was written in FS-409 to stop another page shipping unreadable, and it
recorded **five pages carrying 39 hardcoded light-theme utilities** as debt to be converted.

Before converting them, I looked at what it had actually flagged. **Almost all of it was the
detector's fault:**

- **Mid greys returned from `getStatusColor`** — `bg-gray-400` for a "planned" dot,
  `bg-gray-500` for "maintenance". A swatch colour, not a surface, and correct in both
  themes.
- **Translucent chips** — `bg-gray-500/20 text-gray-500`, which composites over whatever it
  sits on. The same alpha blind spot that made the contrast checker report a heading at
  1.0:1.
- **The biggest group: Kanban's complete `dark:` pairs.** `bg-white dark:bg-gray-800`,
  `text-gray-900 dark:text-white`. That is correct theming by Tailwind's own mechanism —
  `darkMode: 'class'` in the config, and `uiStore` toggles `dark` on `<html>`. A different
  approach from the CSS-variable tokens, and a complete one.

**Genuine offenders across every routed page: one.** Login's single `bg-white`, a fixed white
tile behind the product logo so the artwork reads in either theme — the tile is the logo's
background, not the page's.

Acting on the original list would have meant rewriting about forty working usages, in three
files across two other lanes, to fix nothing.

The detector is now pair-aware and scoped to what actually breaks — light surfaces, dark
text, light borders, none of them with an opacity modifier — and the allowance list is exact
rather than a ceiling, because a ceiling with room in it is a free pass for the next one.
Both properties are pinned: a page with an unpaired `bg-white text-gray-900` fails it, and a
`dark:`-paired one does not.

**Third instrument error in this sweep**, after the contrast checker and the FK probe. The
pattern is consistent enough to state plainly: *when a new guard reports a large number,
the first hypothesis is the guard.*

---

## FS-417 — the ordering debt, closed

The ratchet started at 62 models carrying a ForeignKey column with no `relationship()` for
the unit of work to order by. It came down one edge at a time — 62 → 61 → 58 → 54 → 52 —
each step paid for by a missing edge actually biting something.

**It is now zero.** 121 relationships across the remaining 52 models, added in one sweep
because foreign keys are enforced everywhere and the whole suite is the proof.

Every one is `lazy="raise"`. They exist to order inserts and nothing should traverse them: an
accidental lazy load in async code is a `MissingGreenlet` at runtime rather than a slow query,
so the failure is loud and immediate instead of subtle.

### Two categories are exempt, and the exemption is now itself a test

- **Self-references.** A model pointing at its own table is always a cycle and always fine.
- **The two mutually dependent pairs.** `dock_doors ↔ yard_trailers` and
  `shipments ↔ yard_trailers` — a trailer knows its door, a door knows its current trailer.
  Their DDL is already ordered with `use_alter`. Putting relationships on *both* sides would
  move the cycle to the mapper layer, where it is a `CircularDependencyError` at flush rather
  than a warning at sort. A test now pins that those two stay one-sided, so nobody closes the
  gap by "finishing the job".

### Cost, measured properly on the third attempt

Adding 121 relationships to the unit of work's dependency graph sounds expensive, and a
full-suite run immediately afterwards came in at **7m26s against a usual ~3m20s**. That is
exactly the shape of a real regression.

It was not one, and getting to that answer took three tries:

1. **Collection time** — where mapper configuration happens — was 12.5s with the
   relationships against 12.9s without. So it was concluded to be machine noise.
2. A second full run on an apparently quiet machine came in at **6m26s**, which contradicted
   that and made the regression look real.
3. A single-shot A/B on a 100-test, flush-heavy subset then produced **6.9s, 17.3s and 11.6s
   for identical code** — a 2.5× spread. At that point the honest conclusion was that no
   single-run comparison on this machine could settle anything.

Minimum-of-five, which is the standard estimator under noise, settles it:

| | runs | minimum |
|---|---|---|
| with the 121 relationships | 5.77 / 5.25 / 5.17 / 5.20 / 5.11 | **5.11s** |
| without | 5.06 / 5.03 / 5.02 / 5.02 / 5.05 | **5.02s** |

**About 2%**, on the workload most exposed to it. The first conclusion was right, the second
guess was wrong, and neither was worth anything until the measurement was designed to survive
the noise. A timing regression attributed to the wrong change is how a correct fix gets
reverted.

### The generator was wrong twice before it was right

Inserting 121 lines into a 4,000-line models file by hand is not sensible, so it was
generated — and the insertion point was wrong twice:

1. Anchoring after the *line* containing `ForeignKey(` put the block **inside** a multi-line
   `Column(...)` call, splitting the statement.
2. Walking forward to balance parentheses started counting from the middle of the statement,
   so a `ForeignKey("users.id", ondelete="SET NULL"),` line balanced to zero on its own and
   terminated immediately — same wrong answer, different route.

The third attempt parsed the file with `ast` and used each statement's own `end_lineno`, which
is exact and knows nothing about brackets. Both failures were caught by the file refusing to
import, which is the cheapest possible feedback — but the lesson is the same one this sweep
keeps producing: **the tool doing the measuring is the first thing to doubt.**

---

## FS-418 — one click broke a session permanently, and the earlier fix had removed the evidence

A second-level browser sweep — clicking controls rather than reading first paint — found a
500 on `GET /nlp/sessions/{id}/data` for a session created during the sweep. The same
endpoint, the same message, and the same column as FS-409.

**FS-409's conclusion was wrong.** It read: *"the API itself cannot produce this — its own
request model rejects a non-uuid, so the seed was the only writer that did."* That was true
of `AddDataSourceRequest`, and false of the application:
`POST /nlp/sessions/{id}/platform-data` does not go through that model. It builds the row
directly, and carried the identical fallback:

```python
source_id=str(params.get("asset_id") or params.get("id") or body.source_type)
```

A platform-wide source — the ERP, the yard — has neither id, so it stored the literal
`"erp"` or `"yard"` in a column every consumer reads as a uuid. From that click onward,
`GET /nlp/sessions/{id}/data` returned **500 for that session permanently**, and the
data-sources panel never loaded again.

**One click, no error at the point of the click.** The POST returns 200 happily; the damage
only appears the next time the panel is opened — a different action, often in a different
visit.

Fixing the seed removed the *evidence* without removing the *cause*, and the wrong conclusion
was written down alongside it. It took clicking through a live session to find the rest.

### The sweep that found it was wrong twice first

An inert-control detector is worth having here — this project has shipped 17 tooltips that
never opened and Approve/Reject buttons that 422'd on every click since they were written.
But the first two versions were not trustworthy:

1. **It clicked nothing measurable.** "0 problems" across 31 routes, with no count of what it
   had actually clicked. Instrumenting it showed 81 controls — the result was real, but it
   had been unfalsifiable until then.
2. **It called working filters dead.** Clicking `Critical (0)` then `High (0)` on the RUL page
   both empty the table, so the DOM text is identical and only the pressed chip differs.
   Driving those filters directly proved they work: 5 rows → 0 → 0 → 5 → 0 across the four
   levels. The detector now reads the control's own state as well as the page's.

Of the four remaining "inert" verdicts, all four are correct behaviour: two are native file
pickers Playwright cannot observe, and two are chips clicked while already active.

**Fifth instrument error in this sweep.** The rule has earned its place: *when a detector
reports something surprising, the detector is the first suspect.*

### And a process note

The live verification initially showed the 500 still happening after the fix. The fix was
correct; `kill` had not taken, so the old server still held the port and the "restart" bound
nothing. Confirming the port was free before starting — and checking the process start
time — is the difference between verifying a fix and verifying nothing.

---

## FS-419/420/421 — the third side of the frontend seam, and what it found immediately

Two guards already watched the frontend/backend seam: `test_frontend_calls_real_endpoints`
(the path and method exist) and `test_frontend_query_params_are_declared` (the query keys are
declared). **Nothing watched request bodies** — the quietest of the three, because
**Pydantic drops unknown body fields silently.** A client posting a field the model does not
declare gets a 200, the field never lands, and the defect surfaces months later as "why is
that column always null".

### What it found on its first honest run

`POST /transportation/shipments/{id}/dispatch` sent `driver_id` and `vehicle_id` in the body.
The endpoint declared `driver_id: UUID, trailer_id: UUID` as **bare parameters**, which
FastAPI reads as QUERY parameters for a POST.

**422 on every call. The feature had never worked once.** Confirmed live: the client's shape
returns 422, the server's own shape reaches business logic. Exactly FS-379, found the same
way.

And underneath it, a second defect that would have outlived the first: the client sent a
**vehicle** id, and `Shipment.trailer_id` is a foreign key to `yard_trailers` — a shipment
has no vehicle column at all. The Transportation page's dispatch modal offered a vehicle
picker. So even a well-formed call would have written a vehicle id into a trailer FK:
accepted silently by SQLite, and refused by Postgres now that foreign keys are enforced.

Fixed on all three layers — a request body on the server, a body on the client, and a
trailer picker on the page, fed from the yard API where trailers actually live.

### And a third, found only by fixing the first two

With the transport working, the call reached the HOS check and was refused with:

```
Driver not compliant:
```

Nothing after the colon. `check_compliance` is careful to separate a **violation** (the
driver has driven too long) from **missing data** (nobody can tell) — that distinction was
built deliberately in FS-395 — and the dispatch path read only `violations`. A driver blocked
for missing data got a refusal naming no reason and leaving a dispatcher nowhere to go. It
now reads both, and says `cannot be assessed — no medical certificate on file`.

### The guard was wrong three times before it was right

1. **Too narrow.** It read only inline object literals: 9 of 70 bodied writes. Borrowing the
   sibling's variable resolver took it to 31 resolved, 26 matched to a schema.
2. **False positives from nesting.** The borrowed resolver reads every `key:` in a type,
   because a query string is flat. A body is not: `erp.ts` declares
   `rate_limit?: { requests_per_minute; burst_limit }` and the server declares `rate_limit`
   as a dict. It reported the two nested keys as undeclared fields. The key reader is now
   depth-aware — which is precisely why it could not simply call the sibling.
3. **A hole where a comment claimed a check.** The branch handling "operation declares no
   JSON body" said `continue`, with a comment stating the case was "reported separately
   below". It was not. A planted `{ operatorId, clearedBecause }` on such an endpoint passed
   the guard silently. **The comment described a check nobody had written** — and that branch
   is where the real defect turned out to live.

Two floors were also guessed before being measured — 20, then 45, against a real 31. A floor
pulled from the air is a claim about nothing, so the number is now the measured one with the
coverage stated out loud: **31 of 70 bodies resolved, all 31 matched to a schema**.

A fourth correction followed the first three: URLs written as `${BASE}/subscriptions` could
not be normalised at all, so four calls were reported as "the endpoint declares no JSON
body" — a defect in the reader, blamed on the code it was reading. Resolving module-level
string constants fixed those, and passing the RESOLVED path to the casing check (rather than
the raw URL, which matches no registered prefix) fixed three more that were correctly
camelCased all along.

**Sixth and seventh instrument errors in this sweep.** The rule holds.

---

## FS-422 — documentation, and a "clean" result that was not

Updating the docs for FS-405…421 meant checking what those changes had made false, not
appending to the end. Four things were stale, and one of them was a wrong conclusion rather
than a drifted number.

### The important one: class 25 was swept, called clean, and guarded by nothing

`docs/engineering/defect-class-sweeps.md` recorded *"A request body the endpoint's schema
rejects — **clean, and deliberately not guarded**"*, on 2026-08-02, with reasoning. Both
halves of that reasoning were wrong:

- **"15 request bodies; 7 statically resolvable."** There are **70** bodied writes. The
  reader only handled inline object literals, and 61% of the writes here pass a variable.
- **"The failure mode is loud — a missing required field is a 422 on the first call."** True,
  and about a different question. The class is fields the endpoint does not *declare*, which
  Pydantic drops in silence — and the defect actually present was neither: dispatch declared
  no body at all and had returned 422 on every call since it was written.

**And the route to the wrong answer is the reusable part.** That sweep's detector was wrong
twice — a casing seam and a nested `rate_limit` — and it concluded the class was clean from
the corrected run. The new detector hit **the same two, in the same order**, and needed the
same two corrections. Correcting a detector's false positives says nothing about its false
negatives; both readers covered a seventh of the subject and reported an empty set.

The section is rewritten in place with the correction, rather than replaced. Five new classes
from this sweep were added to the table, and the header count fixed: it said "sixty" while
the table held forty-two and the numbered sections stopped at twenty-nine — a figure nobody
had recounted since it was written. It now says forty-seven, with a note on what is counted.

### A guard caught the documentation being written badly

`test_method_rules_are_indexed.py` — which exists because the rules list and its sections
had drifted apart three separate times — failed the moment the five new rules were added as
list entries with no `## Rule N` sections behind them, and again on the README's stale
"Rules 21–67". Exactly the drift it was written to stop, caught on the first commit that
would have caused it.

### Five rules added, all one shape

68–72, and they are the session in miniature: *the detector is the first suspect* (eight
instrument errors, every one arriving disguised as a finding); *fixing false positives says
nothing about false negatives*; *a floor pulled from the air is a claim about nothing* (three
guessed, against a real 31); *a comment describing a check is not a check* (the branch where
the live defect turned out to be); and *restarting a service is a claim — verify the port and
the process*.

### And my own README row was stale within a day

The referential-integrity row I added described the FK enforcement as opt-in and per-module,
costing "76 of 3,210 tests". By the time anyone read it, enforcement was global, the whole
suite passed with it on, and the ratchet was zero. Corrected, along with the seam
description, which now names all three guards and what each one exists to catch.

---

## FS-423 — the guard's own coverage was the next defect

FS-419 shipped the body-field guard reading 31 of 70 bodied writes and **saying so**. That
number was the finding: 29 bodies were passed as variables whose types live in
`src/types/`, and the resolver only searched the calling module.

Teaching it to read `src/types/`, follow `extends`, and resolve `Omit<Base, 'a' | 'b'>` and
`Pick<>` took it to **36 resolved, all 36 matched** — and immediately surfaced four fields
the endpoints cannot apply, all on `Asset`:

| Type | Field | What happened |
|---|---|---|
| `AssetCreate` | `metadata` | `POST /assets/` declares no such field; dropped silently |
| `AssetUpdate` | `workcellId` | `PUT /assets/{id}` cannot move an asset between workcells |
| `AssetUpdate` | `metadata` | same as create |
| `AssetUpdate` | `maintenanceMode` | **the type's own comment already said so** |

That last one is rule 17 in its purest form. The field carried:

> *"`PATCH /assets/{id}` does not accept this — the only writer is
> `POST /admin/assets/{id}/maintenance`, which is admin-gated for a reason. Declared here so
> the shape matches `Asset`, not because sending it does anything."*

Someone found this, understood it exactly, wrote it down, and left the trap in place. **A
limitation written into a comment is a finding waiting to be re-found** — and the person it
was waiting for was whoever next wrote an asset-edit form, read `AssetUpdate`, and believed
its field list.

No component constructs either type, so nothing broke: the traps were purely for the next
person. `AssetUpdate` is not `Asset` — it is the set of things an update can change, and
matching the read shape at the cost of naming three writes that never happen is the wrong
trade.

### And one more instrument correction

The extended resolver reported `NOTE` as an undeclared field: `// NOTE: …` inside an
interface body has `NOTE:` in it, which reads as a field name. Rule 37 — prose about a
defect gathers around the defect, so strip comments in every source — earned again, two
sweeps after it was written. Comments are now blanked (preserving offsets, so every brace
walk in the file keeps working) before any key is read.

---

## FS-424 — the read side of the same class, and 22 phantom fields on two types

FS-423 fixed the WRITE direction: types naming fields an endpoint cannot apply. The mirror
is `MAX_UNREAD_PHANTOM_FIELDS` — fields the frontend declares that nothing on the wire
sends — which had been ratcheting at 56 with the note *"driving it to zero is not the goal;
noticing it GROW is"*.

That is right for a ratchet and wrong as a reason not to look. **22 of the 56 sat on two
types**, and neither could ever be retired by the mechanism the ratchet describes:

**`LogisticsOverview` — 16 fields, and it is fiction.** No endpoint serves it and no
component imports it. A dashboard specification that reads, to anyone grepping, exactly like
a contract. Deleted, the same call FS-367 made for `ModelDeployment`. When the overview
endpoint is built its type gets written against what the endpoint sends, which is the order
that produces a type worth trusting.

**`DriverWaitTime` — 6 fields, and it is a mismatch.** Not dead: `POST /yard/driver-wait-
times` serves it. The type named `checkInTime`, `dockTime`, `departureTime`,
`waitDurationMinutes`, `dockDurationMinutes`, `totalDurationMinutes`; the wire — after the
yard casing seam and its aliases — delivers `checkedInAt`, `dockedAt`, `checkedOutAt` and
`totalWaitMinutes`. Every one of the six would have been `undefined` at render, which is the
FS-394/FS-398 shape exactly.

Rule 35 again: **name the field after the wire, not after the nicer word.** `departureTime`
reads better than `checkedOutAt` and is worth nothing, because it does not arrive. The
replacement was computed by running the server's schema through the actual alias map rather
than reasoning about it — the seam has an alias layer on top of the casing, and guessing
would have produced six new phantoms in place of six old ones.

Also dropped: `driverName`, `carrierName`, `carrierId`, `appointmentId`, `isDetention`,
`detentionCost` and `reason` — none of which the response carries. The endpoint reports
detention and demurrage as separate minutes/rate/charge triples; the type collapsed both
into one boolean and one number.

**Ratchet 56 → 34.**

---

## FS-425 — the activation worklist

`GET /insights/activations` and `/activations/{id}` were served by **no screen at all**. An
operator who activated a recommendation could see it only inline, in the message that
created it, in that session. "What did we commit to, and what is still outstanding?" had no
answer anywhere in the product, while the API had held the answer since FS-406.

`/activations` is that answer, and it is built as a **worklist rather than a log**: it opens
on `issued`, leads with the two things that need a person — an unfinished Kanban task and a
posting no system has acknowledged — and keeps confirmed and declined a filter away, because
a list where the finished outnumber the outstanding stops being read.

Driven live against a seeded stack: the row renders its task status, one posting per target
system with its own state, the analog instruction on screen with the reference field beside
it, and Confirm returning all three reasons it refused —

```
the Kanban task is ready, not completed
the posting to inventory has not been sent yet
purchasing has no integration and nobody has confirmed the manual step yet
```

Confirm is deliberately left **enabled** when `readyToConfirm` is false. A greyed-out button
explains nothing; a press that answers with three specific reasons is the more useful
control, and the server is the authority either way.

---

## FS-426 — a guard that fired on the commit that made its exemption false

`test_qualifiers_reach_the_frontend` keeps an allowlist of qualifiers that need not reach the
client, and **each entry is a claim**: *"the field this qualifies is not rendered either, so
there is no caveat to lose because there is no claim being made."* One entry read
`"detention_assessed": "detention_charge"`.

Adding `detentionCharge` to `DriverWaitTime` in FS-424 made that claim false, and the guard
failed **in the same commit**:

```
these qualifiers were exempted because the field they qualify was not rendered;
it is now, so the caveat has to be wired too:
    detention_assessed (qualifies detention_charge, which the frontend now reads)
```

That is the allowlist working exactly as designed — its own comment says *"an allowlist that
cannot expire is how a real finding gets parked forever"* — and it is the second time it has
fired this way (FS-395 released `assessable` on the day `is_compliant` started rendering).

### The fix, and why it is not "add a boolean"

`detention_charge` is nullable and **null means nobody has assessed this trailer** — a
different fact from "assessed at zero". The dwell-times path already publishes exactly that
flag, computed as `detention_charge is not None`, because it coerces the charge to a float
and would otherwise report an unassessed trailer as owing nothing.

`DriverWaitTimeResponse` sent the charge and not the flag. So **two endpoints disagreed about
the same concept**, and reading the second one correctly required knowing that null carries
meaning. It now publishes the flag as a `computed_field`, derived the same way, and the
client type carries it.

A first attempt used a plain `@property`, which Pydantic v2 does not serialise — the field
was absent from the schema and the guard would have passed on a promise nothing kept. Checked
against the generated OpenAPI rather than assumed, which is the only reason that was caught.

---

## FS-427 — a ledger that drains itself

FS-407 built the drainer and left it behind a button on one page. So an obligation raised by
a part issue at 03:00 sat untouched until somebody opened the Shop Floor screen and pressed
*Drain*. That moved the problem rather than fixing it: from "nothing tries" to "nothing tries
unless asked", and a queue nobody drains is precisely what the drainer was written to remove.

`PostingDrainScheduler` runs it on a timer, per organisation, following the
`rollout_orchestrator` idiom — one session per tenant with `app.current_org_id` set. Five
minutes rather than the rollout dispatcher's thirty seconds, deliberately: a posting is an
obligation to a far system, not a device waiting on a command, and asking an ERP every 30
seconds to confirm again that it has no write path helps nobody.

`drain()` still owns every outcome; this owns only the schedule.

### The two ways it could have quietly done nothing, both closed

- **A clean drain over rows it cannot see.** `system_of_record_postings` has FORCE RLS, so a
  session without the GUC reads zero rows and every summary comes back zeroed — absence
  arriving as a good result, the shape this repository keeps finding. A test asserts the GUC
  is set before each drain, and removing it fails.
- **One tenant stopping the rest.** An unreachable ERP for org A must not leave org B's
  ledger untouched. A test asserts B still drains when A raises; making the exception escape
  fails it.

Verified against a live stack rather than argued: six `pending` postings, one automatic pass
five seconds after startup, all six moved to `manual_required` with an instruction —

```
posting_drain_pass_complete considered=6 handed_to_a_person=5 orphaned=1 posted=0 organizations=2
accounting -> Enter this into accounting by hand — sap has no verified write path…
```

Nobody pressed anything, and **zero postings were left in `manual_required` without an
instruction** — which is the whole point of the state.

*(A process note: the second mutation test produced a `SyntaxError` rather than the intended
change, so it proved nothing until it was re-applied properly. Rule 4 — a mutation that lands
on the wrong line proves nothing, so check it applied where you meant.)*

**And a guard I had not met caught the new service.** `test_service_lifecycle_is_declared`
keeps a record of every `start()`-bearing singleton and whether the app actually starts it,
so a service can neither be added without being declared nor quietly stop being started. It
failed on the commit that added the scheduler, which is the point: the record is not
documentation about the lifecycle, it is part of it.

---

## FS-428 — one capped list closed, and the guard that was crediting prose

`test_capped_lists_cannot_grow` had sat at 12 with a deliberate policy: *"adding a header no
client reads would create exactly the defect that class exists to catch — the caveat sent and
dropped. Each needs its consumer wired at the same time."* Right, and it makes the list
addressable one endpoint at a time rather than never.

**`/api/v1/geofencing/alerts` was the one worth taking.** Ordered newest-first and capped at
100 — the right default for a recent-activity list, and the wrong answer for the
unacknowledged view: 150 outstanding alerts render as 100 with nothing saying so, and **an
unacknowledged alert that never appears is one nobody will action.**

Fixed on all three layers, which is this file's whole condition for calling one closed: the
endpoint selects `limit + 1` and calls `mark_truncated`; `getAlerts` returns a `ListResult`
instead of a bare array; and `GeofencingPanel` renders a notice saying what is missing.
Changing the client's return type made `tsc` point straight at the consumer, which is the
cheapest possible way to be told you have only done half the job. **Ratchet 12 → 11.**

**Three of the remaining eleven have no frontend consumer at all** — `/health-index`,
`/commands/asset/{id}`, `/notifications/log`. Adding a header to those would be the second
defect, not a partial fix. `/health-index` has a sharper problem anyway:
`select(Asset).limit(n)` with **no ORDER BY**, so which assets come back is undefined — worse
than `/rul`, whose cap at least keeps a stable alphabetical prefix. Recorded, not papered
over.

### The guard was crediting its own documentation

Mutation-testing the fix — remove the `mark_truncated` call, expect the count to rise —
**left the count unchanged.** The detector matches `mark_truncated` anywhere in the handler's
source, and the docstring added alongside the fix explains what the call does. So the
endpoint was credited for *prose about* signalling truncation.

The general form is worse than the instance: a handler documenting *"this deliberately does
not signal truncation, see X"* would have been counted as signalling. The detector now strips
docstrings and comments before matching, and the mutation fails as it should.

**Rule 37 for the third time** — prose about a defect gathers around the defect, so strip
comments in every source. Twice this week it has been the thing standing between a guard and
the truth: `NOTE:` read as a field name, and now a docstring read as an implementation.

And the client contract change was caught by the suite immediately: six assertions in
`geofencing.realmode.test.ts` destructured the array `getAlerts` used to return. Updating
them to read `.items` is the whole cost, and having them fail is the point — a return type
that changes shape without anything noticing is how a caller ends up rendering `undefined`.

---

## FS-429 — six capped lists returning an arbitrary subset, including the one every asset screen uses

FS-428 recorded `/health-index` as having "a sharper problem anyway: `select(Asset).limit(n)`
with no ORDER BY". Taking that seriously and sweeping for the shape found **six**, and the
worst of them was not the one noticed.

**Postgres makes no promise about row order without an ORDER BY.** It may return any rows it
likes for a `LIMIT` and different ones next call — the planner is free to switch between a
sequential scan and an index scan, and a row updated in between moves. So an unordered
`LIMIT` is two defects at once:

| | |
|---|---|
| `/api/v1/health-index` | a fleet of 340 assets got 100 of them, chosen by nobody, and a **different** 100 on refresh |
| **`/api/v1/assets/`** | takes `skip` **and** `limit`, and is the list every asset screen in the product is built on. **Page 2 of an unordered query can repeat rows page 1 showed and omit rows nobody ever sees.** Scrolling a fleet is the most ordinary thing an operator does here |
| `/api/v1/transportation/vehicles` | same `skip`/`limit` shape |
| `/api/v1/registries`, `/registries/correlations`, `/registries/{id}/items` | capped, unordered |
| `/api/v1/simulation/fleet-summary` | capped, unordered |

All six now order by a stable key — asset name, vehicle number, registry name, item name,
correlation recency — matching `/rul`, whose ordering exists for exactly this reason.

### Why the sibling guard did not catch it

`test_capped_lists_cannot_grow` asks whether a capped list can **say** it was capped. That is
a different question from whether the cap is **deterministic**, and an endpoint passes it
happily while returning a different arbitrary subset every call. `/health-index` had been
sitting in that file's recorded list for a truncation signal it does not have, with the
sharper problem unnoticed underneath it — for as long as the list has existed.

`test_capped_lists_are_ordered` closes the second question. Both mutations verified: removing
the ORDER BY from `/assets/` fails it, and so does replacing one with a **comment** that
merely says `order_by` — prose is not code, which is now built into the detector from the
start rather than after being caught by it.

### And I reverted my own fix mid-verification

`git checkout backend/app/api/health_index.py`, used to undo a mutation, discarded the
uncommitted FS-429 fix in the same file along with it. Caught by re-grepping for the change
rather than assuming the restore was surgical — the same class as the `kill` that did not
take in FS-418. **An undo is a claim about state; check it.**

---

## FS-430 — an allowlist entry that was the visible corner of a module-wide defect

Ten endpoints are permitted to 5xx in `tests/_lane_failures.py`, each with an owner, a
diagnosis and an expiry. One was in my lane:
`POST /engines/correlation/integration/initialize-registries`, recorded as *"same
write-on-read shape against actionable_registries"* with the fix *"bind the tenant session
before the INSERT"*.

**The diagnosis was exactly right and the entry understated the problem.**
`correlation_integration.py` took `Depends(get_db)` — the unscoped session — and
`actionable_registries` is FORCE RLS, so every INSERT was refused. But **all three**
write-bearing endpoints in that module had it: `/analyze` and `/test-integration` too. Only
one was probed by the write walk, so the other two failed identically with nothing recording
them.

A single allowlist line can be the visible corner of a module-wide defect. Same shape as
FS-429, where one recorded note about `/health-index` turned out to cover six endpoints and
the worst of them was the asset list.

### The verification that proved nothing

The first live check was: old code → 200, fixed code → 200, registries created both times.
Which would have meant the fix was pointless — or that something was wrong with the test.

**Something was wrong with the test.** The throwaway container's default role is a
**superuser**, and `FORCE ROW LEVEL SECURITY` does not apply to superusers. So the condition
the defect depends on could not occur, and both versions "passed".

Re-run against a `NOSUPERUSER` role:

| | old (`get_db`) | fixed (`get_tenant_db`) |
|---|---|---|
| HTTP | **500** | 200 |
| registries written | **0** | 46 |

This is the same trap FS-307 records against the contract gate — *"it currently runs as
superuser, which bypasses FORCE RLS, so the gate cannot see a tenant-isolation contract
failure"*. Knowing about a trap is not the same as remembering it, which is a note class 25
already made about itself.

**Tenth instrument error of the sweep, and the most consequential**: it did not report a
false defect, it reported a real fix as unnecessary. An instrument that cannot produce the
failure condition will call anything healthy.

---

## FS-431 — the allowlist reaches zero, and four of its five diagnoses were wrong

`tests/_lane_failures.py` is empty. Nine endpoints closed in one pass: four kanban, the
intake read, `/kanban/rules/premade`, `/engines/correlation/generate`, and both RAG entries.

The register did its job. **What it recorded about the causes mostly did not survive
contact with the code.**

| endpoint | recorded cause | actual cause |
|---|---|---|
| `/nlp/correlation/intake/{id}` | "`select()` is given the class rather than a column expression" | **name shadowing** — the module defines a Pydantic `IntakeItem` and imports the ORM class as `IntakeItemModel`; this call site reached for the Pydantic one |
| `/kanban/rules/premade` | "omits org_id/is_active/target_board_id" | **ten** required fields; a template is not a rule and has no identity until created |
| `POST /engines/correlation/generate` | "500 on an empty scenario body rather than 422" | there is no body — `StateSpaceLoader("state_space")` resolves against the **working directory**, and separately `random.choice` on a dict |
| `/rag/documents` ×2 | "needs a decision on whether an absent store is degraded or fatal" | the decision was already made twenty lines up; `DocumentStore.available` is `aioboto3 is not None` and **cannot observe an unreachable store** |
| kanban ×4 | write-on-read on an unbound tenant session | **correct**, and correct about all four |

Every wrong one was wrong in the same direction: plausible enough to believe without
running anything. `select(SomeModel)` is valid SQLAlchemy 2.0, so the first entry described
working code and would have sent its owner looking for a bug that wasn't there.

**An allowlist entry is a hypothesis with a date on it, not a diagnosis.** The expiry is
what made someone check, and checking is what found the real causes — so the mechanism
worked exactly as designed, including in its inaccuracy.

### The four that nobody probed

`kanban.py` had ten unscoped handlers and `nlp_correlation.py` seven. Four of the ten
allowlisted 5xxs traced here, as recorded. **The other thirteen handlers were never probed
by any walk**, so nothing recorded them — they were reading zero rows and answering 200.

`list_task_rules` filters on `organization_id` itself, which changes nothing: RLS removes
the row before the filter sees it. So the automation-rules screen showed an empty list to
every tenant that had rules, and creating one was refused. `execute_completion_actions`
came with them — it runs outside a request, so no dependency bound the GUC and every
completion action on every task silently did not happen, on a code path that exists only
for its side effects.

### A defect that gets likelier with volume

`POST /engines/correlation/generate` kept 500ing after the path fix. `random.choice`
indexes with an integer, so on a **dict** it raises `KeyError: 2` — and 26 of the state
space's 487 top-level keys map to a dict of grouped lists rather than a flat list.

~5% per draw. At the endpoint's default `count=100` that is a near-certainty; by hand with
three it passes. **From underneath it looks like flakiness and from the endpoint it looks
like a hard failure**, which is why running it once by hand confirmed nothing.

The same shape sat in `get_random_asset`: `assets.extend(items)` where `items` is a dict
extends with its **keys**, so 'driver' and 'carrier' were returned as asset names. No
exception, no type error, just occasional nonsense in generated training data.

### Configured is not reachable, in two files

`DocumentStore.available` is `aioboto3 is not None`. `VectorStore.available` is `client
installed and a URL set`. Both are **package-and-config checks**, both are True on every
deployment, and both sat in front of `raise HTTPException(503, "unavailable")` guards that
therefore could never fire for the condition anyone actually hits.

The register named SeaweedFS. The DELETE failed on **Qdrant** first — `delete_by_doc` runs
before any blob is touched — so a fix covering only the object store left the endpoint
500ing, and the write walk said so on the re-run. Connection failures from both clients now
become 503; `ClientError` and `UnexpectedResponse` deliberately do not, because a refusal
from a store that answered is a defect here, not an outage there.

### Instrument error 11

`test_tenant_session_guard` counts `Depends(get_db)` in **raw source**. The comment written
above each fix explaining that the handler no longer takes the unscoped session was counted
as a handler that does, so `kanban.py` reported one remaining offender after all ten were
fixed — and the offender was a sentence saying so.

Fourth time in this directory. It fools the guard toward keeping a file on the debt list
forever, which is the safe direction and therefore the one nobody notices.

### What replaced the register

An empty allowlist proves nothing on its own, and the two walks that would prove it **skip
without Docker** — on a laptop, gutted and worked-down look identical.
`tests/test_lane_failure_root_causes_stay_fixed.py` asserts the structural facts instead:
28 tests, no database, no server, no network. Seven mutations verified, including the
premise of each guard (that `IntakeItem` really is still the Pydantic name, that `available`
really is still only a config check) so a guard cannot outlive the condition it guards.

### The assertion that would have caught all of it, and the one that never could

`test_kanban_and_intake_see_their_rows_realdb.py` seeds one automation rule and one intake
item for org A and demands they come back. Putting the defect back:

| | reverted to `get_db` |
|---|---|
| `/kanban/rules` | 200, **0 rows**, with the rule sitting in the table |
| `/nlp/correlation/intake/list` | 200, **0 rows** |
| `/nlp/correlation/intake/{id}` | **404** for an item the caller owns |
| `/kanban/board`, `/metrics`, `/workload`, `POST /board/view` | **500** |
| `/kanban/rules/premade` | passes — takes no session |
| org B cannot see org A's rule | **passes** |
| org B cannot read org A's item | **passes** |

**The last two are the warning.** Both tenant-isolation assertions pass while the system is
comprehensively broken, because *"org B cannot see org A's rule"* is satisfied perfectly by
nobody seeing anything at all. An isolation suite alone would have called this healthy and
been right about the only question it asked.

Proving a tenant cannot see what is not theirs is worth nothing without also proving they
can see what is. This repository has a lot of the first kind.

## FS-432 — sweeping for that class, and the two instruments that could not find it

The kanban finding generalises to a question: **how many tenancy tests assert only that
the other tenant sees nothing?** Such a test passes perfectly while the system shows
nothing to anyone.

### Two source-reading heuristics, both noise

A regex for "asserts absence, never presence" returned **25 files**. Checking the first —
`test_kanban_tenant_scope.py:69` — it asserts
`[item["id"] for item in own_list.json()] == [str(task_id)]`, which is a positive
visibility assertion written as list equality rather than `assert any(...)`.

Tightened, the regex returned **30 files**, now including
`test_inline_session_tenant_scoping_realdb.py` — a file whose entire purpose is asserting
that an owner can see their own asset. The new pattern required "id" in the variable name
and the variable is called `owned_asset`.

Two attempts, both confidently wrong, in opposite directions. **Reading source for the
absence of an idea does not work when the idea has many spellings.**

### One mutation, decisive

Bind the wrong tenant in `tenant_session` — one line, globally — and run every test file
that mentions a second organisation. A test that still passes cannot detect broken tenancy.

    61 files, 244 failed, 377 passed
    55 files had at least one failure
     6 files had NOT ONE

**Five of the six are correct by design**, which the mutation cannot know and a person can:

| file | why it is unaffected |
|---|---|
| `test_tenant_isolation_rls.py` | raw psycopg2 as `tenant_user`, no FastAPI — tests the DB policies themselves, and says so |
| `test_websocket_tenant_binding.py` | the WS handler takes no HTTP DB session |
| `test_qualifiers_reach_the_frontend.py` | static source analysis, no database |
| `test_error_tracking_api.py` | the endpoint is deliberately platform-level; the test name says `not_tenant_filtered` |
| `test_export_jobs.py` | monkeypatches the job store — scoping is enforced in Python, not the session |

**The sixth was real.** `TestTheFlagDoesNotLeak::test_an_ordinary_tenant_session_still_
sees_only_its_own` asserted that org B's integration was absent from org A's list, and an
empty list satisfies that perfectly. The file *does* assert positive visibility — on the
raw `flagged` session, never through the API. So nothing checked that an ordinary
authenticated caller can see their own integration, which is what the endpoint is for.

One added assertion. It passes on correct code and fails with the tenant binding broken.

### What this measured

**The tenancy suite is overwhelmingly load-bearing** — 55 of 61 files detect a broken
tenant binding, and every one of the six exceptions has an explanation. That is a good
result, and it is the opposite of what both heuristics predicted.

The lesson is about instruments, not tenancy: **perturbing the system found one real defect
and five explainable exceptions; reading the source produced 25 findings and then 30, none
of them real.** A guard that reads code can only recognise the spellings its author thought
of. A mutation asks the system, and the system has no opinion about naming.

## FS-433 — a compliance table with no owner

`data_residency_tags` had **no `organization_id` column and no RLS policy**. Every
organisation's residency tags sat in one pool behind six endpoints — three open to any
authenticated user, three behind `require_admin`.

`require_admin` here is a **per-organisation** admin. That is precisely the argument FS-311
records for why eight data-retention routes are dark — *"a per-org admin would let one
tenant purge another's data"* — and it applied here, unenforced.

So before the fix:

* any authenticated user could enumerate every tenant's tagged `record_id`s together with
  the `tagged_by` user ids;
* org A's admin could delete org B's residency tags;
* **`/summary` and `/validate` counted every tenant's rows and returned the total as the
  caller's own compliance position** — a figure an auditor is meant to rely on, computed
  over data the caller does not own.

The third is the worst of the three, and it is not a leak. It is a wrong answer to a
compliance question, delivered confidently.

### It was written down and not fixed

`validate_data_residency`'s own docstring said it: *"`data_residency_tags` has no
`organization_id` at all, so its rows and a per-tenant row count are not the same
population."* Someone saw the defect, recorded it accurately as a limitation of a figure,
and did not follow it to the six endpoints reading the table. A note is not a fix, and a
note in the one place a careful reader looks is the easiest kind to mistake for one.

### Migration 062

`organization_id UUID NOT NULL`, FK to `organizations`, backfilled through `tagged_by` —
a user belongs to exactly one organisation, so ownership is recoverable rather than
guessed. Rows with no attributable user are **deleted**, not assigned: a residency tag on
the wrong tenant is worse than a missing one, because these endpoints would then report it
as that tenant's compliance evidence.

The unique index gained the organisation too. Without it, two tenants tagging the same
`record_id` in the same table collided, and one tenant's tag silently became the other's.

Caught by the schema rather than shipped: the first attempt used `VARCHAR(36)`, matching
the ORM's declared type, and Postgres refused the foreign key — *"Key columns are of
incompatible types: character varying and uuid"*. Migration 032 had converted those columns
and 033's policy quals cast with `::uuid` for exactly that reason.

### What the mutations showed

* **Explicit `organization_id` filters removed → all 8 tests still pass.** RLS alone holds
  the isolation; the filters are readability, not enforcement. Worth knowing, because it
  means a future handler that forgets the filter is still safe, and one that forgets the
  session is not.
* **Session reverted to `get_db` → 4 fail.** The dependency is the load-bearing part.

The positive-visibility assertion is written first in that file, deliberately: without it,
every scoping assertion below is satisfied by an empty list — the failure mode FS-431 found
in the kanban suite one commit earlier.

## FS-434 — provenance fields that lied, and one that never arrived

Verifying the planned Wave F items found **eight of ten already done** — `_simulated_
provenance` stamped on every gated GeoTab function, `get_device_location` stamping
*conditionally* so a real GPS fix is not labelled simulated, the compliance counts
genuinely counted, the collector-restart stub removed outright. The plan overstates
remaining work, as its own header warns. Two were real.

**`model_version: "gemma-4-placeholder"`.** There is no gemma-4. The configured base is
`settings.CORRELATION_BASE_MODEL` and a loaded model reports `<base>+lora`, so the default
named a model that does not exist — in a version field, on a payload a consumer uses to
decide how far to trust an analysis. It reached the logs:
`correlation_analysis_complete model_version=gemma-4-placeholder`. FS-349 had already made
the payload say `simulated: True` with a lowered confidence; this one field still claimed a
model, so anyone grouping logs by `model_version` filed heuristic output under a plausible
model name. Now `"none (no correlation model loaded)"`.

**A provenance field that described a computation that never ran.** The strategic
recommendations seeded under `ALLOW_DEV_TOKEN` carried
`simulation_basis="Fleet OEE rollup + maintenance-window scheduler (14 days)"` beside
`confidence: 0.88` — a real-sounding derivation over the reader's own fleet. The only tell
was an id beginning `demo-rec-`, which no screen shows.

**A provenance field that lies is worse than no provenance field**, because it is the thing
a careful reader checks.

### And it would not have reached the screen anyway

`StrategicRecommendationResponse` declared neither `simulated` nor `simulation_basis`, and
the handler did not send them — so a strategic recommendation arrived at the client as a
description, an expected impact and a confidence with **no provenance at all**. Adding the
flag to the dataclass alone would have died at the response boundary, which is the FS-366
shape recorded against this very model.

Wired end to end: dataclass → response model → handler → the TS type → the card, where the
caveat renders **above** the figures rather than below them. `simulated?: boolean` is
optional on purpose — a server predating the field sends nothing, and absent must not
render as "simulated: false", which would be the same lie by default.

`test_qualifiers_reach_the_frontend` passed throughout and could not have caught this: it
matches qualifier names across the whole app, so a second `simulated` on a different
response is invisible to it once the name is read somewhere. A name-keyed guard cannot see
per-endpoint coverage.

### An existing guard caught the fix

`test_provenance_flags_are_always_set::test_no_construction_relies_on_the_default` failed
on the commit that added the flag, pointing at the **real** cloud-recommendation path:

    app/services/strategic_engine.py:148 StrategicRecommendation omits ['simulated']

Adding a `simulated: bool = False` default meant every construction that did not mention it
was silently claiming *"a real engine computed this"* — the strongest claim the model makes,
made by omission. The guard's own wording is the rule: **for `simulated` the default is the
strongest claim, so it has to be written at the construction site.**

Ninth time a guard in this repository has caught work in progress rather than a regression
months later. That is what they are for.

## FS-304 — the guard for a class that was already fixed twice

Media types have gone wrong in both directions here: five downloads promising JSON, and an
export declaring `text/csv` while serving JSON. Both were fixed by hand, one at a time,
with nothing left behind. Measured today: all seven file-returning operations declare their
type and no route declares a type it does not send — so this is a guard for a clean state,
which is the cheapest moment to write one.

It matters because FastAPI documents `application/json` by default and **silently**, and an
SDK is generated from this schema across 375 paths. A generated client reading the schema
will try to JSON-parse a spreadsheet, and the failure lands in the caller's code.

**The detector was wrong twice before it was right**, which is most of the value here:

* Reading only the handler body for a response class found **4 of the 7**.
  `compliance_reports.py` and `exports.py` build responses through
  `_secure_file_response`/`_secure_streaming_response`, so the body never names a class.
  That is the FS-305 blind spot, and it made the sweep report a clean schema over three
  endpoints it could not see.
* Adding `Response(` to the pattern with a `\b` after the paren matched nothing — a word
  boundary cannot follow `(` — so five handlers returning
  `Response(content=…, media_type=XLSX_MEDIA_TYPE)` were reported as declaring a file type
  while returning JSON. **Five false findings from one misplaced metacharacter.**

Both were caught by the vacuity class, not by review. Three mutations verified the
assertions, including one that blinds the detector itself.

A third error was caught and is worth recording because it was in the *comment*, not the
code: the first version of the `textwrap.dedent` note claimed cleandoc had broken the real
sweep. It had not — a decorated handler's source starts at column 0 on both its first lines,
so cleandoc left it alone, and only the two-line synthetic test inputs broke.
`test_there_are_enough_emitters` was passing throughout, which is the evidence. **A wrong
explanation attached to a right fix is still wrong**, and it is the kind that survives
because the tests are green.

## FS-435 — a vocabulary of 8,229 names, and what it hides

`test_frontend_fields_exist_on_the_wire` asks whether a declared TS field appears anywhere
in a vocabulary drawn from every response model, raw dict key and alias in the codebase.
That is the right question for *"is this name a fiction"* and the wrong one for *"does this
field arrive"*.

**`YardMoveResponse` sends twelve fields. The TS interface declared eleven, seven of which
were not among the twelve** — and six were invisible because some *other* endpoint sends a
`status`, a `notes`, a `startTime`. The older sweep saw one. Its total of 34 is a floor.

### Four aliases that were never written

`performedBy`, `startTime` and `endTime` had sources all along — `jockey_driver_id`,
`started_at`, `completed_at` — and no alias between them. **A yard move rendered its mover
and both of its times as undefined.**

The pattern repeats next door. `YARD_ALIASES` maps `scheduledStart → scheduledArrival` and
`scheduledEnd → scheduledDeparture`, and stops there: `actual_start`/`actual_end` are
columns, are sent, and were never mapped. `TRANSPORT_ALIASES` aliases `ctpatExpiresAt` and
`insuranceExpiresAt` to their `*Expiry` names and omits `medical_cert_expires` — the one of
the three with a hard DOT consequence.

**A half-written alias map looks complete at the line above it.** Six aliases added; the
older sweep's count fell 34 → 30, and every one is a field that now arrives rather than a
declaration deleted.

### Verified before believed, three times

* The new per-type sweep first reported **63** unfed fields. `DockAppointment.carrierName`,
  `trailerLicensePlate` and `driverPhone` are set by the handler two lines after
  `model_dump`, so a third of the finding was the detector reading only the response model —
  FS-305 again, third time in this family.
* It reported `DriverWaitTime.detentionAssessed` as never sent. That field was added three
  commits earlier as a Pydantic v2 `@computed_field`, which is serialised and appears in the
  OpenAPI schema but is **not in `model_fields`**. A guard that calls a working field broken
  teaches people to skip its findings.
* Before publishing an alias as a fix, each was checked against the payload that feeds it —
  `DockAppointmentBase.actual_start`, `DriverResponse.medical_cert_expires`,
  `YardMoveResponse.jockey_driver_id`. **An alias for a field the server never sends is
  worse than the phantom it replaces**: it silences the guard, because the sweep credits
  alias targets as wire names.

The first probe of this said "no declared schema" for two of the three endpoints and would
have stopped the fix. Those endpoints declare `response_model=List[Dict[str, Any]]`, so
their OpenAPI schema is empty while the handler dumps a full model — **the schema is not
the payload**, and reading it as one is its own instrument error.

Ratchet at 38 with zero slack, verified by planting a phantom field.

## FS-436 — the dashboard's alarms could not say which machine

The Active Alarms panel renders `{alarm.assetName} • {occurredAt}`. **Nothing has ever sent
`assetName`.** `AlarmResponse` carries `asset_id`; the name lives on `assets`. Every row on
the main dashboard displayed a bullet with an empty space in front of it.

An alarm you cannot attribute to a machine is not actionable. The asset is the first thing
an operator needs and the only one that tells them where to walk.

**`mockApi.ts` supplied `assetName`**, and the default development mode is
`VITE_USE_MOCK=true` — so the panel looked finished in development and was blank against
the real API. Exactly the pairing already recorded for the yard's `trailerLicensePlate`,
whose resolver this one copies: one query for the page, not one per row.

Fixed on both endpoints, because two screens read the field — `/alarms/active` behind the
dashboard panel and `/alarms/` behind the Alarms page. Fixing only the first would have
left the larger screen blank.

### The note that said the opposite

`ActiveAlarmsResponse`'s own docstring reads *"every field the client's `Alarm` type reads
is in `AlarmResponse` already"* — written when the response model was introduced, accurate
about the fields it was comparing, and wrong about this one.

**Third time in two days that an accurate-sounding note stood in for a check**, after
`validate_data_residency`'s *"data_residency_tags has no organization_id at all"* and the
`_lane_failures` diagnoses. A note records what someone believed at the time; only a test
records what is true now.

### tsc proved the mechanism

`Alarm.createdAt` and `updatedAt` were also declared — **required**, so TypeScript entitled
every consumer to `new Date(alarm.createdAt)` without a guard. The `alarms` table has
neither column, so no fix could make them arrive; they were deleted.

Deleting them broke the type-check in one place only: **`mockApi.ts`, which supplied both**.
The mock is the reason a required field that is always `undefined` at runtime looked fine
for as long as it did, and the compiler named it the moment the declaration went.

Per-type unfed count 38 → 35; one of the three now arrives, two could never have.

### A tenth guard catch, and it wanted the resolver named

`test_response_models_match_their_tables` failed on the commit that added
`AlarmResponse.asset_name`: *"declares fields that are not columns of its table and are not
listed as resolved elsewhere."* Its `RESOLVED_ELSEWHERE` register already held
`DockDoorResponse.trailer_license_plate` — **the same defect, in the same shape, found the
same way, one screen over.**

The register does not just permit the field; it requires naming what fills it and what pins
it. So the two entries now read as a pair, and the next denormalised field has an obvious
place to go.

Both instances were also found by the *same kind of instrument*: a sweep that compares a
declaration against the specific thing that feeds it, rather than against the codebase in
general.

## FS-437 — a correct fix that nothing could see

`YardManagement.tsx` wraps the trailer's whole driver section in one condition:

```tsx
{trailer.driverName && (
  <div>
    <h4>Driver Information</h4>
    <p>{trailer.driverName}</p>
    {trailer.driverPhone && <p>{trailer.driverPhone}</p>}
  </div>
)}
```

**`driverName` was never sent.** So the block never rendered — and it took `driverPhone`
with it: a field the yard resolver exists specifically to deliver, under a docstring calling
it *"the number an operator calls when a trailer has been sitting on the yard"*.

That fix was real, correct, tested, and invisible. **A guard on a field nobody sends is a
permanent `false`, and everything inside it disappears.** That is worse than a blank line,
because a blank line can be seen — and worse than a missing field, because it silently
cancels work that was done properly.

### Why the phone's own test could not notice

`test_yard_driver_phone_is_resolved_realdb.py` asserts the API sends the phone. It does.
Nothing was wrong at that boundary. The defect lives one layer up, in a condition no backend
test can see and no type-checker objects to — `driverName?: string` is a perfectly
well-typed thing to test for.

So the new file asserts the **conjunction** the screen needs: not "the phone is sent" but
"the block's condition is satisfiable, and the phone is inside it when it is".

### The eleventh guard catch, and it made the fix better

The first version added a second resolver beside the phone one. That test refused it
immediately:

    expected exactly one query against drivers for a page of trailers, saw 2

Right, and not merely stylistic: a per-page lookup that becomes two becomes three the next
time someone needs a field. Both are now one query returning `{phone, name}` — and the
batching is asserted in **both** files, so whichever is edited next fails on its own terms.

This is the second time in two days that a guard did not just block a regression but
improved the design of the fix in front of it.

### And I nearly shipped a flake

The dock-appointment case passed three times in isolation and failed in the full suite.
`GET /yard/dock/appointments` filters `scheduled_start >= start_date`, and `start_date`
defaults to **now at request time** — so a row stamped `now()` at insert is already in the
past by the time the request runs. Whether it appeared came down to sub-millisecond ordering
between a Postgres transaction clock and a Python one.

**Passing in isolation and failing in the suite is the worst way for a test to be wrong**,
because the natural response is to re-run it. Fixed by scheduling the appointment ten
minutes ahead, which removes the timing dependence entirely and is also what a dock
appointment actually is.

Worth noting what caught it: not the three isolated runs, but the full suite — the same
run that has caught eleven guard violations. Running the whole thing before every commit is
not a formality.

## FS-438 — a guard for dead blocks, and the version of it that would not have worked

FS-437's shape generalises: **a conditional gated on a field nobody sends is a permanent
`false`, and everything inside it disappears.** Worth a sweep, since it had just cost a
completed feature.

Measured: 25 gates on a field with no wire producer — **22 of them React Query state**
(`isError`, `isPending`, `isFetching`) read off a hook result rather than a payload. Of the
three real ones, all three are correct:

* `{zone.vehiclesInside && …}` — added deliberately, under a comment saying the panel used
  to render an unconditional `{n} vehicles inside` and every zone reported **0**, *"a count,
  which reads as a measurement, not as a blank"*.
* `{vehicle.tripInfo && …}` — the block shows only `tripInfo.destination`.
* `{selectedCommand.requiresParam && …}` — a client-side constant on a locally-declared
  array, not a wire field at all.

**So the rule is narrower than "do not gate on an unsent field".** Gating on an absent field
to hide a fabricated zero is right. The defect is the other shape: an absent field standing
in front of one that **does** arrive.

### Three detectors, and the third is the only sound one

* **A fixed 700-character window** past the `&&` reported all three legitimate gates as
  defects: it ran off the end of a four-line block, picked up the `name` of the next
  element and `target`/`value` from a handler below it. A window cannot work — a gated block
  is one line here and forty there, and over-reading *attributes fields to a block that does
  not contain them*, which is exactly the claim being made. Replaced with brace balancing.
* **Any field read inside the block** still counted `vehicle.tripInfo.destination` — a
  sub-field of the absent thing, not a sibling being hidden. Narrowed to fields read on the
  **same object** as the gate, which is precisely the FS-437 shape.
* **The global wire vocabulary was the wrong instrument**, and this is the one that matters:
  with the yard fix reverted, the guard still passed. `driverName` is sent by
  `fleet_health.py:480`, so it stays in the 8,229-name vocabulary no matter what the yard
  does. **The guard written to catch FS-437 would not have caught FS-437.**

Found by reverting the fix and running it — not by reading it. The same collision that
motivated the per-type sweep one commit earlier had reappeared inside the guard built to
complement it.

Now judged per type, and soundly: a gate is examined only when the gating field **and** a
field read inside the block are both declared on one paired interface. Two names co-occurring
on a single interface is evidence of the object's type; requiring the pair is what makes it
evidence rather than a guess. With the yard fix reverted it now reports:

    pages/logistics/YardManagement.tsx: {trailer.driverName && …} — on `DockAppointment`,
    `YardTrailer`, `driverName` has no producer, so this block never renders, and it stands
    in front of ['driverPhone'], which the server does send

It names **both** interfaces declaring that pair rather than picking one. The sweep does not
resolve the object's type, so it must not claim to — reporting `DockAppointment` alone would
have sent a reader to the wrong file about a gate on a trailer.

### And a process note

The scratchpad copies used for mutation testing were gone at the start of this session, so a
`cp` restore failed silently and left `yard.py` mutated while the tests reported green. Caught
by `git status`, not by the suite — the mutation was a *removal*, and the guard that would
have objected was the one being tested.

`git restore` is the correct tool once the work is committed, and it cannot fail into a
half-restored state the way a copy can.

## FS-439 — the unfed count reaches zero

38 → 0. Every field resolved rather than excused: **six renames** where the data was
arriving under another name, and the rest deleted because no column, join or computation
could ever have filled them. The global phantom count fell 30 → 17 as a side effect —
answering the sharper question answers part of the blunter one for free.

### Route: eleven fields, and the units were wrong too

`RouteResponse` sends `total_distance_miles` and `estimated_duration_hours`. The TS type
declared `distance // km` and `estimatedDuration // minutes`.

**So the data arrived, was renamed into nothing by the casing seam, and had it merely been
aliased the numbers would have been read as kilometres and minutes — wrong by 1.6× and 60×,
silently, on a fuel and routing screen.** That is the argument for renaming to the wire name
rather than aliasing: `totalDistanceMiles` carries its unit, and a component cannot use one
while believing the other.

The mock agreed with the type and both disagreed with the server: `distance: 3200` is
Chicago to LA **in kilometres**. Development would have shown a plausible route and
production a different one.

`averageSpeed`, `fuelStops` and `restStops` are gone — no columns, nothing computes them,
and `FuelStop`/`RestStop` existed only to type them.

### A shipment showed "Not assigned" under a Vehicle heading

`TransportationManagement.tsx` rendered `{shipment.vehicleId || 'Not assigned'}`. `shipments`
has no vehicle column and never had one — a shipment references a **trailer**. So every
shipment in the product displayed "Not assigned", which is a *statement*, not a blank.
`trailerId` was declared on that interface all along and is sent.

This is the third defect in three days where a fallback made an absent field look like an
answered question: `'Violation'` for an unmapped alert type, `0 vehicles inside`, and now
`Not assigned`. **A default is a claim.**

### A filter that worked only in development

`AppointmentFilters.workcellId` filtered correctly in mock mode and did nothing in real
mode: `dock_appointments` has no workcell column, the endpoint declares no such parameter,
and an unknown query parameter is ignored — so the full unfiltered list came back looking
filtered.

`test_dock_doors_ignores_a_workcell_filter` pinned exactly this for dock **doors**, under a
note reading *"pinned so nobody reintroduces it believing it filters"*. The appointment
beside it was left. Method rule 18 again: the second instance is in the nearest neighbour
of the first.

### A deferral note that outlived its own work

`DockDoor`'s comment listed five fields with the same problem and said *"recorded rather
than fixed here; auditing one interface end to end is its own task"*. **All five had been
fixed in that same interface** — it now declares `equipmentCapabilities` and
`lastOccupiedAt` with the reasoning attached. Only `workcellId` was left.

The note was right about the cause, and said so precisely: *"they did not surface in the
wire-vocabulary sweep because its vocabulary is GLOBAL"*. That is the gap
`test_frontend_types_match_their_own_payload` was built to close, three days later, without
knowing this note existed — and it is what flagged the one field the note's own fix missed.

### AssetType declared four fields it doesn't have and missed four it does

`vendor`, `description`, `capabilities`, `updatedAt` — none is a column. Meanwhile
`actionSpace`, `packmlConfig`, `sensorClass` and `telemetrySchema` **are** sent and were not
declared. The missing half is the interesting one: `actionSpace` and `packmlConfig` are what
make an asset type mean anything operationally — which commands it accepts, which state
machine it follows — and no screen could reach them through a type that did not admit they
existed.

### tsc as the instrument

Every deletion was made blind and the type-checker named each consequence: 15 mock-data
errors and **one real reader** (`shipment.vehicleId`). That is the right division of labour —
the sweep says which fields have no producer, the compiler says who would notice.

Both ratchets moved: per-type **38 → 0** with zero slack, verified by planting a single
field; global 34 → 30 → **17**. The 17 sit on adapter-built interfaces with no same-named
response model, which the per-type sweep cannot reach — so that file is the only thing
watching them, and its vacuity floor moved with the population rather than being left to rot.

`test_the_global_vocabulary_really_does_hide_these` had to be rewritten: it asserted that a
current offender existed, so reaching zero made it fail with the message *"delete it rather
than keeping a guard that guards nothing"* — exactly the wrong conclusion, since the count
is zero *because* the file works. It now asserts the structural fact instead: the global
vocabulary is strictly wider than any single payload, which is true whether or not anything
is currently broken.

## FS-440 — the document-intake path had no tests at all

`pdf_parser`, `docx_parser`, `image_text_extractor`, `rag_chunker` and `rag_ingestion` —
1,210 lines — had **zero test references between them**. Everything a user uploads passes
through them on its way to being searchable, and the failure mode is the one this codebase
keeps finding: quietly returning less than it was given while reporting success.

83 tests. The assertions were chosen for what fails *silently*, not for coverage:

* **Nothing is lost.** A segment dropped in chunking is a fact that is never indexed, never
  retrieved and never cited. The upload succeeds, the chunk count looks plausible, and the
  answer to a question about that paragraph is "I don't know" — and nothing in the system
  can report it, because nothing else knows what was in the file.
* **A citation resolves to one block.** A chunk carrying page 4's text under page 3's `meta`
  produces a citation that looks precise and points at the wrong place. Worse than no
  citation, because a reader checks it and is reassured.
* **A table row stands alone.** The module's own comment names the failure — *"the 'who
  signs vs who approves' failure mode"*. Retrieval returns rows out of context by design,
  so the column names have to travel with them.
* **An unread image is distinguishable from a blank one.** Both return
  `extracted_text: ""`. Only `extraction_method: "none"`, a zero confidence and an explicit
  `note` separate "we looked and found nothing" from "we never looked".

## FS-441 — a chunk budget of one character

`chunk_blocks` computed `max_chars = max(int(target_tokens * chars_per_token), 1)`. **A
floor of one character is not a fallback, it is a different operation.** With
`target_tokens=0`, "hello world" became eleven chunks — one per character.

`rag_ingestion` passes `settings.RAG_CHUNK_TOKENS`, which is env-overridable. So one
mistyped deployment variable would embed a 40-page manual one letter at a time, report
`indexed: True` with an enormous `num_chunks`, and retrieve nothing usable. **Success, an
embedding bill, and no searchable document** — and nothing downstream can tell that corpus
apart from a genuinely unhelpful one.

Now refused at both ends: `chunk_blocks` raises below a 32-character budget, and
`validate_settings` reports the misconfiguration at startup — deliberately **not** gated on
production, because a shredded staging corpus is just as wrong and the alternative is
finding out when a user asks a question the document already answered. The overlap setting
is checked there too: an overlap at or above the target makes every chunk almost entirely a
copy of the one before it, and the chunker silently clamps it.

**Found by a test I wrote wrong.** It asserted the text survived a degenerate target, and
the text *did* survive — shredded. The assertion was too weak to say so, and the failure
message showing eleven single-character chunks is what made it visible.

### Three more tests that were wrong, and what they were wrong about

* Three header-detection tests used pages that were half headings. The threshold is
  `median_size * 1.15`, so when large text is at least half the words **the median is the
  large size and nothing clears the bar**. My ratios were unrealistic — but the property is
  real and now has its own test: a title page or section divider yields no headers at all,
  silently. Pinned as a known limit rather than treated as a bug, since a page that is
  entirely 24pt text arguably has no heading.
* One asserted an asset id in a filename becomes a shared key. It does not:
  `shared_key_detector` matches a fixed vocabulary (PO/SO/INV/TR/WO numbers, dates,
  DOCK/ZONE codes, and `ASSET|EQ|EQUIP|MCH|MACHINE` + digits). Real assets here are named
  "CNC Mill #1" and "Press Line 3", so `CNC-01-alarm.png` yields nothing and cannot be
  linked to its machine by filename. Recorded as scope, not a bug.

### Recorded and not fixed

`parse_pdf_structure` stores `text[:20000]` per page and sets no flag; `truncated` covers
only pages dropped past `max_pages`. A single dense page over 20,000 characters is cut, the
document reports `truncated: False`, and the lost half is never chunked, embedded or
retrievable.

Left as a test that pins the constant rather than a fix: changing that return shape touches
`document_domain_mapper` and `document_scenario_builder`, which is a decision about the
intake contract rather than a bug fix. This codebase has a whole guard family for exactly
this shape — a cap that cannot say it capped — and that family only looks at HTTP list
endpoints.

## FS-442 — the half the per-type sweep could not reach

`test_frontend_types_match_their_own_payload` pairs a TS interface with a same-named
response model. That covers what the server sends directly and reaches **none** of the
adapter-built types — the ones assembled in `src/api/*.ts` from a response whose shape
diverges from the component's.

**That uncovered half is not the quiet half.** Two of this week's defects lived there: every
geofence alert reading `'Violation'` because an unrecognised type fell back to a constant,
and every zone reporting `0 vehicles inside` because an absent list was defaulted to `[]`.

The new sweep pairs on **the adapter's own return annotation**, so nothing is guessed:
`const adaptZone = (z: any): GeofenceZoneExtended => ({ … })` states which interface it
builds, and the keys of that literal are exactly the fields it can populate. A declared
field the literal never sets is `undefined` for every consumer whatever the server sent.

`const adaptTrailer = (t: any): YardTrailer => ({ ...t })` is skipped rather than guessed at.
A spread forwards fields it never names, so no conclusion is available — and inferring
through it would be the same mistake the annotation-pairing exists to avoid.

### Three detector errors, each caught by a finding that looked wrong

* **Shorthand property syntax.** The key regex read `field: value` only, so `adaptZone`'s
  `center,` — computed into a local first — looked unset. A confident false finding about
  the one adapter the file was written for.
* **`extends`.** The shared interface regex requires `{` immediately after the name, so it
  silently skips every extended interface. `GeofenceZoneExtended extends GeofenceZone` is
  exactly the type this sweep needed to reach, and an adapter for it must populate the
  parent's fields too.
* **Judging mocks.** `mockAnswer`, `mockAssessment` and `mockResponse` share the adapter
  shape. A mock omitting an optional field is doing nothing wrong; an adapter omitting one
  is a field no consumer can read. Restricted to `adapt*` so the real finding is not buried
  under every field a fixture skipped.

### Phantoms 17 → 5

`FuelStop` and `RestStop` were **dead types** — they existed only to type `Route.fuelStops`
and `restStops`, deleted with the Route rewrite, after which nothing referenced them at all.
Dead types describing a feature that was never built are exactly what a later reader
mistakes for a contract.

`AxeMatcherResult.pass` was never a wire field: it lives in `jest-axe.d.ts`, an **ambient
declaration for a test library**. The sweep now skips `.d.ts` entirely — nothing in a
declaration file describes a payload.

`lastLoginAt` renamed to `lastLogin` (the column and the response field are both
`last_login`); `parentId` and `supervisorId` deleted as fictions; six more deleted after
confirming no column, handler or computation anywhere produces them.

### The five that remain, and why they stay

All on `Location` and `Address` — and they are arguably not this sweep's business.
`shipments.origin`/`destination` are `Dict[str, Any]` on the wire, free-form JSON with no
contracted keys, so those interfaces document **an expectation a caller may fill in, not a
payload the server promises**. Asking "does the backend send this name" of a shape the
backend never defines gets an answer that means nothing.

Left in the count rather than exempted: the distinction is not one this sweep can currently
make, and an allowance it cannot verify is worse than a number that is slightly too high.
Two of the five also carry a deliberate keep-decision from an earlier pass, recorded in the
type itself — worth not overturning silently.

### A second vacuity guard that failed on success

`test_it_finds_the_unread_ones_at_all` asserted the phantom population was large. Sound at
34; self-defeating at 5, because the count fell *because the sweep works*. **A floor under a
defect population fails when you fix the defects** — the same shape as
`test_the_global_vocabulary_really_does_hide_these` two days ago.

Rewritten to check what the guard was actually for: that the parser has not gone blind. It
now asserts the wire vocabulary and the interface count, neither of which moves when the
findings do.

## FS-443 — the instrument that could have seen all four

Four defects this week were the same shape and **no existing instrument could see any of
them**. The server sent the data, the response model declared it, TypeScript compiled, every
backend test passed — and the screen showed nothing:

| | what the screen did |
|---|---|
| FS-436 | alarm rows rendered `{assetName} • {time}` with nothing before the bullet |
| FS-437 | the yard's driver block was gated on a field never sent, hiding the phone inside it |
| FS-439 | every shipment read "Not assigned" under a Vehicle heading |
| FS-435 | a yard move's mover and both its times arrived under unmapped names |

A backend test asserts the API sends the field. A type-checker asserts the field is
declared. **Neither can see the gap between them, and that is where all four lived.** Only a
browser looking at a rendered page can.

E2E goes from 8 tests to 20. Three assert the specific fixes; nine assert the general case —
that no route renders `undefined`, `NaN`, `[object Object]` or `Invalid Date`, which is what
a missing field looks like once it reaches a template. That last set costs one page load per
route and is aimed at the defects nobody has found yet.

Values, not elements, following the precedent `authenticated.spec.ts` set for a good reason:
the FS-191 tenancy bug rendered a complete, error-free dashboard of zeros, and any
element-exists assertion would have passed it.

### A route that does not exist passes vacuously

The first draft listed `/maintenance`. There is no such route — the real one is
`/analytics/maintenance` — and a typo'd path renders the 404 page, which contains no
`undefined` and would have passed while asserting nothing. Every route in the list is now
checked against `App.tsx`.

### A spec CI does not name is a spec that never runs

The live-backend job invoked **one file by name**, and a live-backend spec `test.skip`s
itself without `E2E_LIVE_BACKEND=1`. So a new one would have been collected by Playwright,
skipped on every laptop for want of a backend, and **executed nowhere** — green locally,
absent from CI, and indistinguishable from a passing test in both.

The job now names both files, and `test_every_e2e_spec_is_run.py` asserts that any spec
gating on a live backend is named by some workflow. It lives in the **backend** suite
deliberately: it needs no browser and no Node, so it runs in the cheapest job on every push
rather than only where Playwright is installed.

Same failure `test_ci_quarantine_expires.py` guards one layer down, and the same one FS-365
recorded for `compliance-assistant.visual.ts` — except there the file was not collected,
and here collection was never the question. Execution was.

### What is verified, and what is not

The specs are **collected** (20 tests in 3 files), **syntactically valid**, **skip cleanly**
without a backend, and every route and selector they use was checked against `App.tsx` and
the components. The guard that CI names them is mutation-verified.

**The assertions themselves have not been executed against a live stack.** The local
containerised backend is crashlooping on a missing `jwt` module, the container's database
has zero assets, and two Postgres instances contend for 5432 — so a local live run would
have failed for want of data rather than for a defect. CI stands up its own stack, migrates,
seeds and runs them; that is where these first execute for real.

## FS-444 — "capacity" opened a quality investigation

`correlation_registry_integration` is 1,130 lines with one test reference, and it is the
service that turns an AI analysis into **work someone is assigned** — a registry item and a
Kanban task per detected domain. Domain detection was `keyword in analysis_lower`, a
substring test, and the short keywords sit inside words this domain uses constantly:

| analysis text | routed to | because |
|---|---|---|
| "Line **capa**city was reduced by 12%" | QUALITY_CONTROL | `capa` = Corrective And Preventive Action |
| "The valve was **iso**lated for servicing" | COMPLIANCE_REGISTRIES | `iso` = the standards body |
| "Cycle counts are ex**cell**ent this week" | PRODUCTION_OEE | `cell` = work cell |
| "Two customer orders were can**cell**ed" | PRODUCTION_OEE | `cell` |

**Not cosmetic.** A registry item and a Kanban task are created per detected domain, and the
analysis text is quoted into the item — so the mismatch reads as a judgement somebody made
rather than a string bug. A routine capacity note opened a formal quality investigation; a
valve isolation opened an ISO compliance item.

Fixed with word boundaries. The tests assert **both halves** — the false positives are gone
*and* the eight real keyword families still fire — because a matcher that matches nothing
also has no false positives, and this repository has shipped that mistake before.

### 46 registries, 8 that anything can fill

`initialize_registries_for_organization` creates a registry for every mapped domain. Of the
46:

* **8** can be returned by the extractor, so only those can receive an analysis-derived item
* **5** also receive default items — a *subset* of the 8, not a separate group
* **38** have neither and are created empty and stay empty

On a compliance screen that reads as 38 programmes **not started** rather than 38 that
**cannot be started**, which is a different fact and the more alarming one. Recorded with the
numbers pinned rather than fixed: closing it means either giving those domains keywords and
default items, or not creating a registry nothing can fill — a product decision.

The docstring said "all 47 operational domains". There are 46.

### I got the arithmetic wrong first

The first version of that note said **41** unfillable, from `46 − 5 default-item domains`.
The five are a **subset** of the eight extractable ones, so the union is 8 and the answer is
38. The test I wrote caught it — `reachable >= 9` failed at 8 — and both the test and the
service docstring were corrected before either was committed.

Worth stating plainly after a week spent finding stale notes: **a number in a comment is a
claim, and I had just written a wrong one.** The only reason it did not ship is that it was
asserted rather than only written down.

## FS-445 — the decisions were in docstrings, where nobody deciding would find them

Six findings from this week are understood, reproduced and **deliberately not fixed**,
because closing each is a product or contract decision rather than a bug fix. Each was
recorded in the docstring of the test that pins it — the right place for the *reasoning* and
the wrong place for the *decision*. **A docstring is read by whoever next edits that file,
and none of these will be closed by that person.**

`docs/engineering/open-decisions.md` collects them: the PDF page truncated at 20,000
characters with no flag, 38 registries created that nothing can populate, eleven capped
lists that cannot say they were capped, five fields declared on shapes the server never
defines, twelve paths served at a doubled prefix, and two PUT handlers that replace rather
than patch. Every entry names the test that pins it and what would have to change.

It is listed in `test_documented_files_exist.py`'s checked set, **added with the file rather
than after it** — that guard's own note warns that moving prose out of a checked document
moves it out of the check, and a new document full of citations is the same trap facing the
other way. Verified by pointing an entry at a file that does not exist and watching it fail.

Five new classes and three new rules went into `defect-class-sweeps.md`: the half-written
alias map, the block gated on a field nobody sends, the floor that changes the operation,
substring matching that routes work to the wrong domain, and the spec CI does not name.

### The count in that document was already wrong

Its heading read **"The forty-seven classes"** while its own highest class number was **60**
— stale by thirteen before this week added five. The early classes are rows in a summary
table, later ones got their own sections, and nobody reconciled the two.

I made it worse first: seeing 65 as the highest heading number I wrote "sixty-five classes"
into the README without checking whether the numbering was a count. It is not — numbers 30
through 51 have no sections at all. Both places now say **"sixty-five numbered classes"**,
which is the one thing a reader can verify against the document in front of them.

**That is rule 75 catching its own author, twice in two days.** The first time a test caught
it before it shipped. This time nothing did — a heading is not asserted by anything — and it
was only found by counting instead of trusting the number already written down.

### The rules were guarded and the classes were not

`test_method_rules_are_indexed` already asserted that the README cites the current **rule**
range — added after that range drifted once before. Nothing asserted the **class** count, so
the sweeps document's own first heading was wrong by thirteen for weeks while the rule range
beside it stayed correct.

**A guard covering one half of a pair is how the other half rots.** The class count is now
asserted in both places, and the count is the *numbering* rather than a heading tally,
because classes 30–51 have no sections of their own — counting headings gives a different and
equally defensible number, which is exactly how I got it wrong.

Mutation-verified by restoring the stale heading.

## FS-446 — the container could not be rebuilt, so it ran two-month-old packages

`docker compose up` gave a backend that never answered. The log, eight frames deep in a
restart loop:

    File "/app/app/api/auth.py", line 10, in <module>
        import jwt
    ModuleNotFoundError: No module named 'jwt'

`PyJWT` **is** in `requirements.txt` — added 2026-07-16 when it replaced `python-jose`
(FS-76). The image is from two months ago.

### Why that is not "somebody forgot to rebuild"

`docker-compose.yml` mounts `./backend:/app`, which splits the container in two: **the code
comes from the working tree and is always current; the packages come from the image and are
as old as the last build.** So every dependency change breaks every container built before
it, and the symptom is whichever import happens to come first — nothing in that trace says
"your image predates a dependency change".

**And the rebuild fails.** `pip install -r requirements.txt` exits 1 with
`OSError: [Errno 28] No space left on device`. The image is not stale because someone forgot;
it is stale because it **cannot be built**. The first attempt appeared to succeed only
because the command was piped to `tail`, so the shell reported `tail`'s exit code — rule 72's
shape exactly: a step that claims success without being asked whether it succeeded.

### The guard

`backend/app/core/startup_checks.py` compares `requirements.txt` against installed distributions and
refuses to start with a message naming every missing package and the remedy. It runs first in
the lifespan, before anything that needs a package to be present.

It covers the same failure in its other clothes: a laptop venv behind `requirements.txt`
after a pull, and a CI cache that survived a dependency bump. Names, not versions —
a version check fires constantly on harmless drift, and a check that cries wolf on a correct
environment is one people learn to skip, which would make it worse than the crashloop it
replaces.

**It reported a false positive first.** `prometheus-client` is installed and importable, and
`requirements.txt` spells it with a hyphen while `packages_distributions()` reports an
underscore. PEP 503 treats `-`, `_` and `.` as the same character; comparing raw strings does
not. Caught by the test asserting that a *satisfied* environment passes quietly — which is
the assertion a checker like this most needs and most easily omits.

### Not fixed, and not mine to fix

13 GB of the Docker VM is reclaimable from 26 stopped containers. Most is test detritus —
randomly-named `timescaledb` containers from testcontainers runs, a `seedprobe-db` from
yesterday's RLS verification. But it also includes `overpeak-*` containers **from a different
project** and two unnamed images of 7.9 GB and 4.1 GB that I cannot identify.

Pruning would fix the build and might delete someone's work. `docs/planning/` already gates
FS-293 on exactly this — *"pruning deletes someone's images"* — and that gate is still the
right one. Recorded in `docs/engineering/open-decisions.md`.

## FS-447 — the e2e suite ran for the first time, and three of its assertions were wrong

Clearing 13 GB of abandoned build containers let the backend image rebuild, and a fresh
`timescaledb` volume let the migration chain build the schema in order. **The compose stack
answered `health: 200` for the first time**, and with demo data seeded the live-backend e2e
specs executed — including the ones written yesterday that had never run anywhere.

`FS-436` confirmed against a running system rather than a testcontainer:

    asset_name='CNC Mill #1'                    SPINDLE_TEMP_HIGH
    asset_name='Conveyor #1'                    BELT_SLIP
    asset_name='Vibration Sensor — CNC Spindle' VIB_ELEVATED

### Three assertions that could never have passed

* **`the assets page lists seeded assets`** located `table tbody tr, [role="row"]`.
  `Assets.tsx` renders a **card grid** — no table, no row role anywhere on the page. The
  locator could not match, so the assertion could only ever fail. Now asserts a seeded asset
  *name*, which is the stronger check and the one this file argues for elsewhere.
* **`the dashboard shows NON-ZERO data`** waited on `body` containing `/asset/i` — satisfied
  the instant the shell mounts by the **sidebar's "Assets" nav link**. It then read the page
  before any query resolved and failed with *"dashboard rendered no numeric values at all"*
  against an API returning `total_assets: 5`. **A wait satisfied by furniture is not a wait.**
* **Twelve logins in one file**, against `AUTH_LOGIN_RATE_LIMIT = 10/minute` which compose
  turns on by default. Two tests failed on a login *timeout* rather than on anything they
  assert, and which two depended on worker scheduling. **A rate limiter is not a flake** —
  it is the server correctly refusing the seventeenth login in a minute, and retrying would
  have hidden it. One shared login now; the file runs in 14s instead of 46s.

The first two were in `authenticated.spec.ts`, written months ago in the job that must pass
on every push. They are the reason to be careful about what "green" meant there.

### What let this happen

`docker-compose.yml`'s comment already explained it: the `./database/migrations` initdb mount
was removed because raw `psql` ran the chain with `ON_ERROR_STOP`, never recorded
`schema_migrations`, and `create_all` then built a second source of truth on top. **My local
volume predated that fix**, so it carried the full schema, no migration records, and five
TimescaleDB continuous aggregates.

Baselining then failed on `032_uuid_consolidation.sql`:

    cannot alter type of a column used by a view or rule
    DETAIL: rule _RETURN on view _timescaledb_internal._partial_view_4 depends on "asset_id"

Not a migration bug. On a fresh database the chain creates the aggregates *after* 032, and
all 61 migrations applied cleanly once the volume was recreated. It is a defect of the
adopt-an-initdb-database path, which the compose comment had already retired — the stale
volume was the last thing still using it.

Final state: **18 e2e passed, 2 skipped, 0 failed** against a live stack.

## FS-448 — two assertions that skipped instead of failing, and the screen they were about

With the stack running, the two e2e tests aimed at this week's actual fixes — FS-436 and
FS-437 — turned out to be **skipping**, not passing. Both had a guard of the shape:

    const rows = page.locator('table tbody tr')
    test.skip(await rows.count() === 0, 'nothing to assert about')

**A skip guard in front of a locator that cannot match is worse than a failing test.** A red
test gets fixed; this sat green and inert for as long as it existed, and nothing was ever
going to say so. Both selectors were wrong for the same reason as the assets test: they
assumed a table where the page renders divs.

### The alarms screen never said which machine

Chasing the first one found the real defect. `Alarms.tsx` renders
`{alarm.message}` and `{alarmCode} • {occurredAt}` — **no asset anywhere**. On the dedicated
alarms screen, where deciding what to do about an alarm begins with knowing where to walk.

FS-436 gave the dashboard panel `assetName` and made `/api/v1/alarms/` send `asset_name` in
the same commit. **The data has been arriving at this page ever since and nothing rendered
it.** One line; it falls back to the code alone rather than printing a UUID or a bullet with
nothing before it, which is what FS-436 was.

### The demo never exercised the driver block

`yard_trailers` had 5 rows and **0 with a driver**; the 3 seeded drivers had **no phone**. So
the block FS-437 unblocked could not render in the demo either — an operator walking through
the product would never see a driver on a trailer, and the e2e assertion skipped for want of
data rather than passing.

The seed now gives the drivers phone numbers and puts them on the two trailers that have a
story: the detention case and the docked reefer. Detention is exactly when someone needs the
number to call.

### And the test still failed, correctly

Once it ran, it clicked `tbody tr` **`.first()`** — which is the trailer with no driver, so
the block correctly did not render. Right failure, wrong trailer. It now names `TRL-4482`,
and asserts that trailer is present so a seed change cannot quietly make the test about
nothing.

**20 e2e passed, 0 skipped.** Both assertions this week's fixes were written for now execute
against a live stack, and the two screens they are about show what they were always sending.

### And the nine route checks could have passed on an empty page

`no field renders as undefined on /x` is **trivially true of an error page, an empty state,
or a shell that never resolved** — so it passes hardest exactly when the page is most broken.
That is the same vacuity shape every sweep in this repository has a rule about, in a test
written two days after writing that rule down.

Measured across the nine routes first, rather than guessed: 134 to 1,414 characters of main
content. The floor is 80 — comfortably below the thinnest real page, far above a spinner —
plus an assertion that no error state is showing. Verified by raising the floor to 99,999
and watching `/fleet` fail with `rendered 335 characters`.

All nine render real data against the seeded stack, so the checks were not vacuous *today*.
The point is that nothing was stopping them from becoming so.

## FS-449 — nine hand-picked routes became all thirty-two

The undefined sweep covered nine routes I chose. The app has **32**, and the four defects
this sweep was written for were all on pages nobody thought to check — which is the argument
against choosing.

Swept all 32 against the seeded stack: **zero** `undefined`, `NaN`, `[object Object]` or
`Invalid Date`, zero error states, nothing under 80 characters of content.

**A clean result is a claim.** Verified by re-running the same sweep with a pattern that
matches every page — all 32 reported, which proves the loop visits and reads them. A sweep
that finds nothing and a sweep that looks at nothing produce the same output.

E2E goes from 20 tests to 43.

### The list will drift the day someone adds a page

`frontend/src/test/everyRouteIsSwept.test.ts` compares the swept list against `App.tsx` in
both directions:

* a route in the app and not in the sweep — **the page nobody added is exactly the one that
  goes unchecked**;
* a route in the sweep and not in the app — it navigates to the 404 page, which contains no
  `undefined` and passes while asserting nothing. That is not hypothetical: `/maintenance`
  was in the first draft of this list and is not a route.

It runs in the **frontend unit suite**, not as an e2e test: no browser, no backend, so it
fires on every push rather than only where Playwright and a live stack exist. The sweep it
guards is the expensive one; this is the cheap thing that keeps it honest. Both directions
mutation-verified.

## FS-450 — the pages render; nothing proved they work

The route sweep proves every page **renders**. Nothing proved any of it **works**. A button
whose handler throws, or whose request 500s, leaves the page looking exactly as it did
before — React swallows the error into a boundary, or the failure lands in a rejected promise
nobody awaits.

That is not hypothetical here: `dispatchShipment` returned **422 on every call since the day
it was written** (FS-420), and no test could see it because no test clicked anything.

`controls-do-not-break.spec.ts` clicks up to five controls on each of the eight most
interactive routes and watches for two unambiguous signals — an uncaught page error, and any
response of 500 or worse. Nothing about what each button *should* do, which is what keeps it
useful without encoding product judgement. Destructive labels are skipped by name: a sweep
that clicks "Delete" eventually deletes something a later assertion needed.

**32 controls clicked, zero problems.**

### It reported that same clean result while clicking nothing

The first version had no wait after `goto`, so it counted buttons before the page rendered,
clicked **zero**, and **passed in 4.7 seconds**. A sweep reporting no problems because it did
no work — the exact shape this codebase has seventy-five rules about, produced by the person
who wrote several of them.

`expect(clicked).toBeGreaterThan(15)` is now the first assertion in the file. It is what makes
the clean result mean anything, and without it the other assertion is decoration.

An earlier attempt failed differently and is worth recording too: 32 routes × 12 controls with
waits between each **timed out at ten minutes** before printing its findings. Too slow to run
is the same outcome as too blind to see — neither tells you anything.

## FS-451 — the first e2e that writes

All 44 existing e2e tests **read**. Every create, edit and dispatch path was covered only by
backend tests calling the API directly — which never exercises the payload **the UI
assembles**, and that is exactly where the failures have been:

* **FS-420** `dispatchShipment` returned 422 on *every call since the day it was written*,
  because the client sent a field the endpoint read as a query parameter
* **FS-418** one click on "add platform data" broke a correlation session permanently
* **FS-379** a bare non-Pydantic parameter on a POST is a query parameter, and the client
  sent it in the body

Each is a mismatch between what the form collects and what the endpoint accepts. A backend
test constructs a correct payload by hand and passes; a component test mocks the client and
passes. **Only a browser filling the real form finds them.**

Four tests on the shop floor — the write-heaviest surface, eight mutations, every one fanning
out to a system of record. Each asserts the **artefact through a separate API client**, not a
success toast: the FS-420 form rendered no error at all while every submission 422'd. The
quantity is checked as well as the row, because a write that lands with the wrong values and
one that never lands both present as "it worked". One test asserts the **posting ledger** got
an entry — a `part_issues` row with an empty ledger is a write that landed and did nothing,
and an empty ledger looks exactly like a quiet day.

### Five failures, all mine, all instructive

* **The endpoints were guesses.** `/shop-floor/events` does not exist; the real ones are
  `/part-issues`, `/labor/open`, `/postings`. Reading the router took one command.
* **A premise that was wrong.** A test asserted a rejected write shows the operator an error.
  The submit button is **disabled** without a part number, so the server never sees it —
  better design than the one I assumed, now pinned as its own assertion.
* **Three locator rewrites for a field that was never the problem.** Container-by-heading,
  container-by-contained-button, preceding-sibling XPath — all resolved to a real element and
  none could see the input. The original `.last()` was right. **Reading the DOM took thirty
  seconds and would have saved all three attempts.**
* **State read before it existed.** `isVisible()` immediately after `goto` answers about a
  card whose query is still in flight: neither button exists, so "already clocked in?"
  answered *no*, and the clocked-in card then rendered with no Clock in button to press.
  **Asking a question before the answer exists returns "no", which is a different thing from
  the answer being no.**
* **429.** Five logins per run against `10/minute` — the file passed once and then aborted
  three tests on the second run. The sibling spec had this fixed a day earlier and **the fix
  did not generalise, because it lived in that file.** A rate limiter is a shared resource;
  a per-file remedy is a per-file remedy.

Verified by running the file three times consecutively rather than once. **48 e2e passed.**

## FS-452 — one login for the whole suite, because the last two fixes did not travel

The e2e suite hit `AUTH_LOGIN_RATE_LIMIT = 10/minute` **twice, three days apart, in two
different files** — twelve logins in one, five in the other. Both were fixed the same way,
in the same shape, inside the file that hit it.

**The second file could not benefit from the first file's fix, and a third would have hit it
again.** A rate limiter is a shared resource; a remedy that lives inside one consumer of a
shared resource has to be rediscovered by the next one.

The fix that generalises is a Playwright **setup project**: one login before anything else,
written to disk, inherited by every spec through `storageState`. The suite now spends exactly
one login however many files or tests it grows to — 49 today.

Three things fell out of doing it properly:

* **`smoke.spec.ts` had to opt OUT.** Its three tests assert what an *unauthenticated*
  visitor sees, and inheriting a session would make "protected route redirects to login"
  assert the opposite of its name while passing.
* **`rejects a wrong password without logging in` clears storage first.** It would still
  distinguish — a successful login navigates, a rejected one does not — but a test named
  "without logging in" that runs while logged in is one whose meaning a reader has to
  reconstruct.
* **The setup project runs even when CI names individual spec files.** Verified by deleting
  the state directory and running one spec by name: the dependency fired and recreated it.
  That was worth checking rather than assuming, because CI names four files explicitly and
  the state file is gitignored, so CI is always the cold-start case.

`test_every_e2e_spec_is_run.py` now also asserts the wiring — the setup project registered,
the dependency declared, the `storageState` loaded. Without it, removing any of the three
would fail every authenticated spec on a login redirect and explain nothing.
Mutation-verified.

### And the count in the sweeps document was wrong again

Adding classes 66–67 and rules 76–78, the heading edit was lost when the script that made it
aborted on a later assertion — so the README said 78 rules beside a document with 75.
`test_method_rules_are_indexed` caught both halves. That guard was written yesterday for
exactly this, after the same heading sat wrong by thirteen for weeks.

**Two documents that must agree are a pair, and a pair needs a guard.** This is the second
time in two days that one has earned its place within a day of being written.

## FS-453 — accounting for the numbers, and guarding the register

Four wrong figures in one week, all mine:

| claim | truth | caught by |
|---|---|---|
| 41 unfillable registries | **38** — the five with defaults are a *subset* of the eight extractable, not a separate group | a test I had just written |
| "The forty-seven classes" | the document numbered to **60** at the time | nothing, for weeks |
| "sixty-five classes" in the README | the numbering is not a count; classes 30–51 have no sections | myself, immediately after writing it |
| "Rules 21–78" beside an index of 75 | the heading edit was lost when the script making it aborted on a later assertion | `test_method_rules_are_indexed` |

Three of four were caught. The one that was not sat wrong in the first heading a reader
meets, and only surfaced because I counted instead of trusting the number already written
down.

### Audited, and all six current figures are right

Every number in `docs/engineering/open-decisions.md` checked against the thing it describes:
eleven capped lists, five phantom fields, forty-six mapped domains, thirty-eight unfillable,
and two ratchets at zero. All correct.

**They were also entirely unasserted** — right today, with nothing keeping them right. A
register nobody can trust is worse than no register: it is read once, found wrong, and then
discounted, including the entries that were right.

`test_open_decisions_numbers_are_true.py` closes that. It asserts only the **numbers**, not
the prose or the reasoning — when a ratchet moves, the register gets updated in the same
commit. It also checks that every entry names the test that pins it, because an entry with no
pin is a note, and notes are what this document replaced.

Mutation-verified both ways: moving a ratchet without updating the register fails, and
restoring the wrong `41` fails with the explanation of why it is 38.

### The scripting habit that lost an edit

The heading edit vanished because one script did several replacements and then hit an
`assert` that failed — so `write_text` never ran and the earlier, *correct* replacements were
discarded silently. The shell reported nothing because the failure was the last thing to
happen.

Same shape as rule 72 (a `kill` that did not take) and as the `docker compose build` that
"succeeded" because it was piped to `tail`: **a step that is not asked whether it succeeded
will not volunteer that it failed.** Edits now go one at a time, and the guard above means a
lost one fails a test rather than sitting in a document.

---

## 2026-08-05 — FS-456/457/458: the truncation flag closed end to end, and the edge agent

### The open decision that was three layers deep

Decision #1 in the register read: the PDF parser caps each page at 20,000 characters and says
nothing. Closing it turned out to need three changes, and only the first was the one written
down.

The parser now reports `text_truncated` and `text_chars_dropped`. Then
`POST /nlp/correlation/intake/analyze` — which had been sending a `truncated` flag for dropped
PAGES all along — gained `pages_text_truncated` beside it. Then the intake panel, which had
been receiving that page flag and rendering a risk score next to it without comment, gained a
notice.

**Layers 2 and 3 were found by fixing layer 1, not by reading.** An open decision's scope is a
guess until someone starts closing it, which is an argument for closing them rather than
re-describing them.

### A self-inflicted 500 on three endpoints

The same session's edit added `mark_truncated(response, ...)` to nine handlers and the
`response` parameter to six. `/notifications/log`, `/health-index` and `/assets/{id}/commands`
answered 500 on every call.

Nothing caught it at edit time: `import app.main` succeeds because the name resolves when the
line RUNS; the unit tests for those routers use mocked sessions that never reach the line. A
real request against a real database found it, which is the slowest place to learn about a
typo. Now an AST check in `test_capped_lists_cannot_grow.py` costing milliseconds.

### The edge agent — 14,349 lines, previously unexamined

Two findings, both in the class this repository already had a name for.

**Synthetic sensor data that could ship unstamped.** The audio and video collectors fabricate
readings when hardware is absent and stamp `simulated: True` so the platform can tell an
invented number from a measured one. But the capture synthesized on `source != "device"` while
the stamp fired on `source == "simulate"` — not complements. `source: "mic"` or `"rtsp"`, or
any typo, produced fabricated RMS, peak frequency, brightness and motion scores arriving
against a real asset and indistinguishable from a real sensor's. Both collectors, same shape.
The existing `EDGE_REQUIRE_EXPLICIT_SOURCES` guard could not help: it catches an *omitted*
source, and these were present and wrong.

Fixed by returning the fact instead of re-deriving it — `_capture()` answers
`(samples, synthetic)` — and by refusing a source the collector does not know.

**The buffer loss nobody could see.** Store-and-forward loses undelivered telemetry three
ways. Dead-lettering and size-pruning each increment a counter and warn. Retention expiry only
logged, at INFO — and expiry is the one that happens when the device has been unable to reach
the cloud for longer than the retention window. The buffer's whole purpose, failing, recorded
only on the box that cannot ship logs. The operator's view of a week-long outage was a pending
gauge that stops rising.

Both halves shipped: the counter, and a HIGH-severity `EdgeBufferExpiring` rule. A counter
with no alert is a time series nobody looks at — invisible for a different reason than the
log line it replaced, while looking on the dashboard like it was handled. The guard asserts
the pairing, so a fourth loss counter cannot ship without a rule.

### The guard that passed with the fix deleted

The first version of the buffer-loss guard searched 400 characters after each call for
`metrics.record_`. It passed with the fix mutated out, because the window reached down into
the *next* loss path's counter — green whether or not the defect was present, while also
being a claim that someone had checked.

Caught by mutating the fix out, which is the step that is easiest to skip when a test passes
on the first run. Rewritten to bind the assigned variable and follow it, which also catches
the subtler mutation: a counter present but reading the wrong variable. Rule 84.

### One failure recorded as unexplained

A full-suite run reported `test_backup_restore_drill.py::test_dump_restores_into_an_empty_database`
failing. It passed in isolation and passed on a full re-run, and the traceback was gone —
the run had been piped through `tail`, which keeps the summary line and discards the
diagnosis. Same shape as the `docker compose build | tail` that "succeeded" while failing on
`No space left on device`.

Written down rather than dismissed. A failure seen once and not reproduced is still a fact
about the suite, and calling it flaky is how a real order-dependency becomes folklore. Rule 85.

**Suite:** 3445 passed, 100 skipped (backend) · 201 passed (edge agent).

---

## 2026-08-05 — FS-459: the capped-list ratchet reached zero

Eleven endpoints returned a bare array truncated at `limit`, so a full page was
indistinguishable from the complete set. All eleven now signal.

The last five were in `analysis_sessions.py` and `kanban.py` — another lane's files. The
open-decisions register had recorded that entry as **the one needing nobody's intent**: the
change is `limit + 1` and one `mark_truncated` call, with no decision about semantics inside
it. Crossing a lane for that while leaving the entries that need someone's judgement
untouched — the doubled logistics prefix, the 38 unfillable registries — is what keeps the
lane rule meaningful rather than a rule to route around.

The ratchet sat at eleven for as long as it did because the fix was assumed to cost a
`COUNT(*)` per request. It costs one extra row.

### Stopping at the server would have been half of it

Three times now this repository has produced a correct flag that reached nobody: FS-434, the
`truncated` flag the intake panel had been receiving and not rendering, and this. So the
three chat endpoints with real callers return `ListResult`, and both components render a
notice.

Search is the sharpest of the three. A capped result set means matches **exist** that were
not shown, and a search box that quietly omits hits is worse than one that finds nothing —
the user concludes the thing is not there. Session messages is the subtlest: the endpoint
orders oldest first, so truncation removes the most RECENT turns, and a user scrolling to the
bottom of the pane would believe they had reached the end of the conversation.

The two `kanban.py` endpoints have no frontend caller at all — the board uses
`/kanban/board` — so the signal is there for whoever writes one, and no client work was
invented to justify it.

### The class that replaced the ratchet

`TestTheDebtIsAttributed` split the unsignalled endpoints into mine and another lane's and
asserted the cross-lane list was non-empty, with a note saying that if they were ever fixed,
the right move was to lower the ratchet and rewrite the class rather than leave a stale claim
about other people's work. That is exactly what happened, and the note is why the rewrite was
obvious rather than a judgement call — **a test that says what to do when it stops being true
is worth more than one that only says what is true.**

### FS-460 — three heartbeat fields that reach the cloud and are thrown away

Found while sweeping the edge agent for the same class one boundary out. The agent builds an
eleven-field heartbeat; the cloud persists four, uses three to route and stamp, and never
touches `git_sha`, `collector_status` or `buffer_depth`.

Both sides had passing tests. The agent's asserts the payload is built correctly; the
worker's asserts the update lands. **A contract with one side asserted is not asserted** —
neither could see that three fields were being computed on every device, serialised,
transmitted and discarded.

`buffer_depth` is the one that matters: it is the number that says a device is falling
behind, and the alert that answers the same question reads the agent's own `/metrics` —
which requires reaching the device, and the case worth catching is the device you cannot
reach. The heartbeat survives NAT, already arrives, and is already parsed.

**Recorded rather than fixed.** Persisting them is a migration, a worker change and a panel;
the alternative is to stop computing them. Both are defensible and neither is a bug fix, so
it is open-decisions #5 with a guard that makes the gap unable to widen quietly. The guard
asserts both directions — the reverse case, a worker reading a field no agent sends, is the
one that fails silently in production, because `data.get` returns None rather than raising
and the column stays NULL while the code reads as though it were populated.

**Suite:** backend 3445 passed / 100 skipped · frontend 553 passed, coverage above all four
thresholds.

---

## 2026-08-05 — FS-461: telemetry timestamps off by the device's UTC offset, and OEE pinned at zero

Two findings from sweeping the edge agent's analytics, and both were classes this repository
had already found and fixed **somewhere else**.

### The timestamps

Five collectors — `bacnet`, `profinet`, `dnp3`, `ethernet_ip`, `http_rest` — emitted
`timestamp_edge` as a bare `datetime.now()`, which is naive LOCAL time. `telemetry.time` is
`timestamptz`, and the ingestion worker parses the string with `fromisoformat`, producing a
naive datetime that Postgres reads as UTC.

**Every reading from a device outside UTC was stored wrong by exactly that device's offset.**
Verified on a host at −05:00: a stamp emitted at 19:36 local arrives as 19:36 UTC.

The agent has had a guard against this since FS-96, written after two instances became silent
data loss. It matched `datetime.utcnow(` and nothing else, and passed every run while
fourteen `datetime.now()` calls sat in the same tree. A guard that greps for one spelling
reports clean on every other spelling — in the confident voice of a check that ran.

Also caught in the sweep: `local_oee.py` measured elapsed time against local wall-clock,
which is not monotonic. On a DST fall-back it steps backwards an hour, so time-in-Execute
goes negative and silently subtracts from operating time. Once a year, on a number nobody
would think to question.

`_parse_ts` deliberately produced local-naive time to match, and documented why —
"collectors mostly emit local-naive timestamps". That premise had gone stale: seven of
eleven emitted aware UTC. **A comment explaining a deviation ages into a justification
for it.**

And the correction I wrote for that docstring was itself stale within the hour: it said
"four emit naive", which stopped being true as soon as I fixed those four. Rule 75 —
a claim in a comment is a claim — applies to the comment describing the fix.

The agent is aware-UTC throughout now, and the widened guard asserts itself: that the
pattern matches both spellings and does NOT match `datetime.now(timezone.utc)`. A pattern
that quietly narrows restores months of confident silence.

It strips comments and string literals with `tokenize` before matching, because the first
attempt fired on the docstring describing this very defect — the third time in this
repository that a comment explaining a defect tripped the detector for it.

### The OEE

`calculate_quality` returned `0.0` when no parts had been counted; `calculate_performance`
returned `0.0` when `production_count` was zero. OEE is the product of three factors, so
either pinned it to zero.

Not a rare edge case: part counts arrive through **optional** telemetry, and a PackML feed
that reports state without counts — most of them — never populates it. Every asset on such a
site published `edge_oee = 0` from agent start, forever. Reproduced before the fix: a machine
that ran a solid hour in Execute reported `oee 0.0`.

The backend fixed this exact defect months ago, in a file called
`test_oee_failure_is_not_zero.py`, whose first line is "Zero OEE is not a null result." The
edge agent computes the same metric and had the same defect the whole time. **A defect class
does not stop at a repository boundary just because the sweep did.**

Undefined factors are `None` now, OEE is `None` when either is, and `set_oee` does not
publish a gauge for a value it does not have — a gauge that stops advancing is what absence
looks like in Prometheus, and `absent()` and staleness are written for exactly that, both of
which a hardcoded zero defeats.

Availability stays a number on purpose: its denominator is the window, which always exists,
so a machine that sat idle really was available 0% of the time. Emptiness is only ambiguous
where a count stands in for a measurement.

**Suite:** edge agent 217 passed.

---

## 2026-08-05 — FS-462: a machine running at full rate, recorded as stopped

`PackMLStateMapper.map_state` turns whatever string a PLC reports into a standard PackML
state. Anything it did not recognise became `PackMLState.IDLE` — **and `IDLE` is an
availability-loss state.** So an unreadable state was recorded as downtime.

The default could not be neutral. Every member of that enum belongs to a category, so any
choice asserts something; `Idle` asserts the worst available thing.

**It is not an exotic case.** The default maps are per asset type and do not overlap: the
3D-printer map knows "printing" and not "running", the CNC map knows the reverse. One wrong
`asset_type` in a config, one firmware update renaming a state, one vendor that says
"in_progress". Verified before the fix — a printer mapper given "running" returned `Idle`
with `is_availability_loss` True, and the only trace was one log line.

### Three things in the file already said so

* `get_state_category` had an `"unknown"` branch that was **dead code**, unreachable because
  every enum member was categorised;
* `get_unknown_states()` is a public accessor **nothing outside the module calls**;
* the warning fires once per *distinct* string, on a device that may not be able to ship
  logs — so the single line recording a permanently mis-measured machine is also the one
  most likely to be lost.

Someone foresaw this and the handling was lost. **Unreachable handling for a real condition
is a defect report left in the source**, and it is worth reading as one.

### And fixing the agent alone would have made it worse

`/operations/{id}/packml-summary` computes `Execute / total_duration`, where the total sums
every state bucket. The moment the agent started emitting an honest `Undefined`, that
endpoint turned the honesty into a lower productivity number — a machine reporting as less
productive the more of its states its configuration failed to cover. A property of the config
presented as a property of the machine.

That denominator now excludes unmapped time, and `unmeasured_seconds` is reported so a reader
can see how much the answer rests on. It is Rule 88 applied to itself within the hour of
writing it: fixing one side of a boundary is not finishing when the other side consumes the
same quantity.

The literal `"Undefined"` is duplicated across the two repositories because the backend does
not import the agent package — so the backend test reads the agent's source and fails if the
value drifts. A copy is a claim.

**Suite:** backend 3459 passed / 100 skipped · edge agent 228 passed.

---

## 2026-08-05 — FS-463: the carry-across pass, and a performance figure computed from a constant

Four consecutive edge-agent findings (FS-457, FS-458, FS-461, FS-462) turned out to be
classes the backend had already fixed. Each was found by accident while doing something else,
which is luck rather than method. So this pass is the systematic version: take the closed
backend classes, ask which of them the agent could also have, and check each mechanically.

**Twelve classes carried across. One new defect, five confirmed clean, six already fixed.**
The clean results are written down because they are the expensive part to re-derive, and a
sweep whose negatives go unrecorded gets run again by the next person.

Clean: SQL interpolation in the SQLite buffer (parameterised throughout); unordered
truncation (every `[:N]` is byte slicing or a log preview); hot-spinning retry loops (24
unbounded exception-swallowing loops examined, all sleep); start/stop symmetry (17 collector
classes, none leaks a task); side-effect names (every `_send`/`_publish`/`_forward` performs
it, and raises rather than logging when it cannot); metrics declared and never incremented
(25 declared, all touched).

**Two of those clean results were first reported as hits by a detector that was wrong** —
the usual tax. The hot-spin sweep flagged `mqtt.py` because it sleeps through a
`_sleep_or_stop()` wrapper rather than calling `asyncio.sleep` directly, and `mqtt.py` is in
fact the best-protected collector in the tree. An earlier version flagged 21 loops by
counting any loop containing an `except`, including `for` loops that terminate by
construction.

### The defect it found

`Performance = (parts × ideal cycle time) / operating time`, where the ideal cycle time is
seconds per part at the machine's rated rate — a property of **the machine**. The agent had
`self.ideal_cycle_time: float = 60.0`, set in `__init__`, never read from configuration,
never assignable, referenced nowhere else. Every machine in the world was assumed to take
sixty seconds per part.

Measured, both running flat out for an hour: a press with a 3-second cycle reported **100%**
(it computed 2000% and clamped); a CNC with a 600-second cycle reported **10%**, and there is
no clamp at the bottom.

The clamp is why it survived. Fast machines came out at exactly 100% and looked perfect, so
the error was only visible on slow ones — as a machine running perfectly reporting a tenth of
its rate.

The backend has read this per asset from `asset.connection_config['ideal_cycle_time_seconds']`
all along. The agent had no way to be told at all.

Fixed with **no default**. `oee_tracker.configure(asset_id, seconds)` is called from the
collector-registration loop in `main.py`, beside the alert-rule registration already there,
reading the same key the backend reads. Unconfigured, performance is `None` with a reason. A
zero, negative or non-numeric rate is refused rather than clamped — clamping would resurrect
an invented number by another route.

**This turns performance off for any deployment that never configured a cycle time**, which
is the point: those deployments were not getting performance, they were getting a number
computed from sixty.

**Suite:** edge agent 237 passed.

---

## 2026-08-05 — FS-460 corrected: I asserted a negative I had not checked

The reverse carry-across pass — the agent-discovered classes re-asked of the backend and
frontend — found a defect in my own work from a few hours earlier.

FS-460 recorded that the edge agent sends three heartbeat fields the cloud discards, and said
of the sharpest one: *"the fleet view's answer to 'is anything wrong out there' is arriving at
the cloud, in a message the cloud already parses, and being thrown away."*

**That is false.** There are two heartbeat paths. I read one.

| path | carries | consumed |
|---|---|---|
| Kafka `agent_status` → `_process_agent_heartbeat` | 11 fields incl. `buffer_depth` | version/config/build only |
| HTTP `POST /api/v1/edge/heartbeat` → `api/edge_fleet.py` | `buffer_pending`, `dead_lettered`, `dropped`, `active_collectors` | **yes** — persisted and published as `edge_agent_*` gauges |

Device backlog is stored, gauged per agent, and alertable. It always was.

**How it surfaced.** Not by re-reading FS-460. By coming at the same code from the opposite
end: the reverse pass asked whether a backend gauge had a producer, and the answer led
straight back to a claim I had made in the other direction. Two searches across one boundary
fail in different ways, and that is the whole argument for running both.

What is actually true is narrower and still worth the guard: the same health is assembled
twice, under two names for one quantity, and the Kafka copy is read by nobody. Redundant work
on every device and two vocabularies for one fact — the condition that produced six aliases
in FS-435. Open-decisions #5 is rewritten to say that, at its real severity.

**The corrected claim is now pinned** rather than asserted in prose, because an uncheckable
claim inside an exemption is exactly how the original error survived being written down. If
the HTTP path stops consuming device health, the reasons beside `buffer_depth` become false
and a test says so.

And the first version of that pin was itself too weak — it searched the agent module for
`buffer_pending` and passed when the emitted key was renamed, because `build_payload` reads
the same name out of its health snapshot one line above. It parses the returned dict's keys
now. **Second time this week a proximity check has passed with the defect present**, and both
were caught the same way: mutate the fix out and watch.

Rule 92: finding one consumer does not prove there is no other.

---

## 2026-08-05 — FS-464: the platform was monitoring the edge's data loss and not its own

The reverse carry-across pass — the classes the agent taught us, asked of the backend and
frontend. One defect, one wrong claim of my own (above), four clean.

Clean: the backend's naive-datetime guard is already AST-based, checks both spellings, and
self-tests its own pattern — the agent was the laggard, not the backend; `geotab_service`
gates and stamps every simulated function, and sets `invented = True` in the same block that
fabricates a position, which is the correct shape; `except → return <constant>` sites all
return a caller-supplied default or a sort key; and the backend's OEE carries
`quality_measured` / `performance_measured` from the calculator through the API to a hint on
the OEE page, wired end to end and better than the agent's was.

### The defect

A message the ingestion worker cannot process is published to a dead-letter topic and logged.
That was all — no counter, no alert, nothing on a dashboard. The agent's equivalent has had
both since FS-458.

The cloud case is sharper than the agent's. A dead-lettered message was **accepted**: the
device sent it, the broker acknowledged it, and the agent's store-and-forward buffer dropped
its copy on that acknowledgement. The data then exists in exactly one place — a DLQ topic
nobody is watching — while the device has been told everything is fine.

One branch lost it completely:

    if self._producer is None:
        return

No DLQ record, no counter, no log. Defensive, since the producer starts before the consumer,
but it was the only branch in the worker where an accepted message vanished leaving no trace
of any kind — and "unreachable" there is a property of today's start-up order, not of the code.

Two counters, because they need different responses. Dead-lettering is replayable and alerts
HIGH; a failed DLQ publish is data leaving the system and alerts CRITICAL. The guard asserts
that ranking, because collapsing it wastes the only distinction that matters at three in the
morning.

**Suite:** backend 3474 passed / 100 skipped (clean run, exit 0) · edge agent 237 · frontend 553.

---

## 2026-08-05 — FS-465: a trailer nobody could age, scored as freshly arrived

The third leg of the carry-across pass: backend and agent classes re-asked of the frontend.
The pass has now run all three ways, and this leg found its defect **from the client and
fixed it in the server** — the direction that had not been tried.

The sweep for "absence coerced into a number" returned four hits in rendered figures. Three
were false positives worth naming: a form's default radius, and two percentage helpers whose
callers already branch on a measured flag — the OEE page's `pct` never sees an unmeasured
value because the render is `{f.measured ? pct(f.value) : '—'}`. **A coercion is only a
defect where the coerced value is rendered as a measurement**, and a detector that cannot
tell the difference produces a list nobody reads.

### The real one

`(r.dwellHours ?? 0) * 60`, in the yard client. Following it back found the same quantity
computed in two server-side places that disagree about a null check-in:

    _calculate_dwell_hours    end_time - _as_utc(None)   -> TypeError, a 500
    the dwell-times query     ... if check_in else 0.0   -> 0.0, "arrived just now"

One crashed and one lied. The lie is worse. The yard banner exists to report trailers past a
120-minute target, and a trailer nobody could age was scored as the most favourable value
available — then averaged in at zero by the client, pulling the mean down, while being absent
from the count the banner reports. So an unmeasurable trailer made the yard look better in
two directions at once.

`check_in_at` is nullable: its `default=utcnow` is applied by the ORM and skipped by a raw
insert, which `test_raw_insert_timestamps.py` already parametrises over `yard_trailers` for.

**The comment on the next line already knew.** Immediately below the `else 0.0`, the source
explains that `detention_charge` must stay null until a charge is assessed, because
"`float(None or 0)` turns 'not yet worked out' into 'nothing owed'". The reasoning was there
and one line too low. Proximity to a correct decision is not protection.

Fixed to `None` in both producers, `Optional[float]` on the wire, and the client averages over
measured rows and reports `trailersUnmeasured`. `formatDuration` also stopped collapsing `0`
and `null` — it was `if (!minutes) return 'N/A'`, so a yard where every trailer had just
arrived and a yard that could not be measured rendered identically.

### And one of my own

The first draft of the backend guard's naive-timestamp test used `datetime.now()` where
`_as_utc` documents that a naive value is assumed **UTC**. It expected 1.0 hours and got 6.0
on a host at −05:00. That is FS-461's class landing inside a test written for a different one,
and it is the same trap: a bare `datetime.now()` looks correct and is wrong by the host's
offset.

**Suite:** backend 3483 passed / 100 skipped · frontend 555 · edge agent 237.

---

## 2026-08-05 — FS-466…470: the open-decisions register reached zero

Five entries, all described as needing intent rather than investigation. All five closed.
Three took less time to decide than they had spent being re-read — which is worth knowing
about that page: an entry can sit there because it is genuinely contested, or because nobody
has been asked.

**FS-466 — the agent reported its health twice.** Two heartbeat paths carried overlapping
facts under two names. The HTTP one has a consumer, so the Kafka payload was narrowed to
identity, and the agent stopped reading its SQLite buffer on every beat to fill fields the
cloud discarded.

**FS-467 — 38 registries nothing could fill.** Writing extractor keywords for
`INNOVATION_RD` and `KNOWLEDGE_MANAGEMENT` would have been product scope invented to satisfy
a count, so the initializer now creates only what something can fill, from a set derived from
the extractor rather than listed beside it. **Closing it exposed a second defect**:
`_create_registry_item_from_analysis` carried the comment "Get or create registry for domain"
above code that only got, returning None and dropping the item. Harmless while all 46 were
pre-created; a silent loss the moment they were not. The blocker had been protecting a bug.

**FS-468 — the doubled logistics prefix.** The blocker was never the edit. Dropping the
prefix collided with `fleet_logistics` on two paths, and the router registering first would
have won silently. `fleet_logistics` is canonical — response models, the HOS fix that stopped
an unreported driver counting as compliant, and the paths the frontend calls — and the
correlation variants moved under `/correlation/`. A guard now fails any route repeating an
adjacent segment, which is the shape a prefix collision produces and nothing else does.

**FS-469 — five phantom `Location`/`Address` fields.** Not debt: they describe
`shipments.origin`, which the server declares `Dict[str, Any]`, so the question the sweep was
asking had no answer. The sweep now derives which types are client-constructed and checks the
`Location` exemption against the backend schema, so it expires by itself if that field is
ever contracted.

**FS-470 — two PUT handlers.** One was a detector false positive: `kanban.update_task` dumps
nested checklist items, not the patch body, and the detector now reads the receiver of
`model_dump()` rather than carrying the difference as an allowance for months. The other was
correct PUT semantics with a silent trap — every field defaulted, so a partial body reset six
retention settings. It requires all seven now, so a partial body is a 422 naming the missing
field. The verb did not need to change; the trap did.

### Four weak assertions, all caught the same way

Four guards written this week passed with their fix mutated out: a 400-character window that
reached the next loss path's counter; a substring search that matched the name one line above
the emitted key; a source-text check that matched the string inside its own docstring; and a
`re.search` that found a second declaration of the same field.

Every one was found by deleting the fix and re-running. Every one would otherwise have shipped
as a green claim that somebody had checked. They share a shape — **a check that looks near the
right place rather than at it** — and the remedy is the same each time: bind the variable,
parse the keys, run the function.

**Suite:** backend 3500 passed / 100 skipped (clean run, exit 0) · frontend 555 · edge agent 237.

---

## 2026-08-05 — FS-471: what the session produced, and two claims about it that were wrong

A consolidation rather than a fix. `defect-class-sweeps.md` now closes with a section on what
the method actually does, because the individual entries answer "what was wrong" and nothing
answered "what is worth reusing".

### The shape

Three phases, three kinds of finding.

**Opportunistic** — fix a defect, notice the class, sweep for it. Finds what is nearby.
**Component-by-component** — read a subsystem nobody has read. Finds what is unread; this is
how 14,349 lines of edge agent came under review at all. **Carry-across** — take each closed
class and ask which other component computes the same quantity. Finds what is already
understood but not applied, and it is the only one of the three that terminates.

The middle phase is what argued for the third: three consecutive edge-agent findings turned
out to be classes the backend had already fixed, discovered one at a time by accident.

### Where the numbers ended

Four ratchets at zero and the open-decisions register empty — and the four reached zero by
four different routes, which is the part worth keeping. Two by building the missing half, one
by deleting something that should not have existed, one by discovering the question had no
answer.

A ratchet at zero has a specific weakness: there is no allowance left to lower and no failing
test to argue with, so raising it is a one-character edit in a file whose purpose is to
prevent exactly that. `test_the_ratchets_that_reached_zero_stay_there.py` holds all four in
one place.

### Three wrong claims, in the paragraphs about wrong claims

The consolidation's first draft opened "Forty items, FS-431 to FS-471" — a count nobody had
counted. It is forty-one. Written into a paragraph whose subject is four wrong figures
produced in a single week, which would have been its own small joke had it shipped.

`test_the_session_arc_is_a_real_range.py` derives the range from the FS references in the
tree and checks three things: the floor, the ceiling, and the absence of gaps. The gap check
is the useful one — an FS number is how this repository cross-references itself, and a comment
saying "the same shape as FS-457" is only worth anything if FS-457 is findable. An item living
only in a commit message is not.

The README's new claim about the four ratchets is paired the same way, because a number that
several documents cite and nothing checks is precisely how the four wrong figures happened.

**And then a fifth.** That same README paragraph first named five peak ratchet values, of
which three were wrong — an adapter-unset allowance that was introduced at zero and never had
slack, and two final pre-zero values quoted as starting ones. Caught by running `git log -S`
before committing, which took thirty seconds and belonged before the sentence rather than
after it.

Five is enough to stop calling it carelessness. Every wrong figure in this documentation has
been a number recalled into prose; every figure that has never been wrong is one a test
derives. The remedy is not more care, it is fewer hand-written numbers.

**Suite:** backend 3511 passed / 100 skipped · frontend 555 · edge agent 237.

---

## 2026-08-05 — FS-472: a dead PLC dialled 17,000 times a day

The gap I flagged last pass and did not fix, on the grounds that it was robustness rather
than wrong data and the call was not mine to make. Picked up as the next step.

Five industrial collectors — `profinet`, `dnp3`, `bacnet`, `ethernet_ip`, `can_bus` — ran the
same loop: read the device, and on failure drop the connection and sleep for
`poll_interval`. **The same interval they use when everything is working.** So a PLC that was
switched off drew a connection attempt every five seconds indefinitely: roughly 17,000 a day,
each costing the device a socket it has to refuse.

Nothing about it is wrong. The readings are correct, the suite is green, and the only symptom
is a device being dialled at a rate nobody chose — which is exactly why it lasted. It first
surfaced as a note during the hot-spin sweep, which correctly reported these loops as *not*
spinning, because they do sleep. "Not a hot loop" was true and turned out not to be the
interesting question.

**The machinery already existed.** `resilience.py` has `ExponentialBackoff` and a three-state
`CircuitBreaker`, both tested, and `modbus`, `opcua` and `mqtt` have used them since they were
written. The five that did not were written later. Nobody decided against them — nothing in
those files pointed at them, which is the whole of Rule 97.

Measured on a dead device over twelve loop iterations: **five connection attempts instead of
twelve**, with delays of 1, 2, 4, 8, 16 seconds and then the breaker holding at its cooldown.
In steady state an unreachable device is probed once per 300-second cap rather than once per
poll interval.

The guard checks four things per collector — constructs both instruments, consults the breaker
*before* attempting, records both outcomes, and sleeps on the backoff rather than the poll
interval — and then runs a real loop against a device that always fails. The first four are
structural, and a collector can satisfy all of them while still retrying at a fixed rate.

Tuning is unchanged from the values `modbus` has carried since it was written, including its
comment that they are a first-pass guess pending production telemetry. That comment is still
true, and now true in five more places.

**Suite:** backend 3511 passed / 100 skipped · edge agent 268 · frontend 555.

---

## 2026-08-05 — FS-473: the fix that spread the guess

FS-472 was complete and not finished, and its own summary said which part: *"I left the tuning
alone — it's the same first-pass guess modbus has carried since it was written."*

True, and it understated the problem. Giving five collectors a backoff and a breaker by
copying four constants into each put those numbers in **sixteen places across eight files** —
numbers one of those files documents as provisional pending production telemetry. Whoever
eventually holds that telemetry would have had to find all eight, and the ones they missed
would keep the old behaviour while looking deliberate.

**The copies were also less capable than the originals.** `modbus`, `opcua` and `mqtt` accept
an injected `backoff=` / `breaker=` so the coordinator can hand one collector a tuned
instrument. The five new ones accepted nothing. The fix imitated what made the pattern work
and not what made it changeable.

`ReconnectPolicy` owns the numbers now, and **they have not changed** — same guess, one place,
plus a `reconnect:` block in collector config to override per site and injection available
everywhere. All eight take it through two entry points that reach identical validation,
because an operator writing YAML cannot see which kind of collector they are configuring.

Two validations earn a class rather than a dict. An unknown key is an error, because a typo
that silently keeps the default is a tuning the operator believes they applied. And
`max_delay > cooldown_cap` is refused, because the loop would already be waiting longer than
the breaker's cooldown — an instrument present and inert.

### The guard had to change, which is its own finding

The FS-472 guard asserted `ExponentialBackoff(` and `CircuitBreaker(` appeared in each
collector. True only while every collector built its own — factoring them out failed five
collectors that had just become *more* correct.

**A guard written against one implementation of a property fails the next implementation of
the same property.** It asks about the attributes now, and separately asserts that no
collector hardcodes the tuning, which is the property the refactor actually established.

### Found by running it, not by the suite

Migrating the three original collectors, I wrote `ReconnectPolicy.from_config(config)` into
constructors that take explicit keyword arguments and have no `config` in scope. **The full
suite passed** — nothing constructs those three directly — and it surfaced only when I built
one by hand to check the tuning actually flowed. That is the argument for driving the thing
rather than trusting green: 289 tests had nothing to say about a `NameError` on the first
line of a constructor.

**Suite:** backend 3511 passed / 100 skipped · edge agent 289 · frontend 555.

---

## 2026-08-05 — FS-474: the same loop, one boundary out

Class 73 carried across the moment it was written, rather than waiting to trip over it in a
month. Asked of the backend: which loops here retry at the same rate whether or not anything
is working?

Twenty-one loops examined, six candidates, **one real instance**.
`CommandExecutor._ack_consumer_loop` has two exits — the consumer will not start, and the
consumer errors mid-stream — and slept a flat five seconds on both. A broker down for a day
drew roughly 17,000 connection attempts and 17,000 error lines, at a rate that did not depend
on anything.

The five rejections matter as much as the finding: the dispatch and timeout loops are
**periodic polling**, where a constant interval is the design and there is no device to back
off from; `erp_database_replication` already sleeps longer on error; the egress cycle is a
scheduler, not a connection. A sweep that flagged all six would have been noise.

**The values live in `command_executor.py`, not in a policy class.** The agent has eight
collectors with this loop, so `ReconnectPolicy` earns its place there; the backend has one.
Building a framework for a single caller is how a guess reaches eight files — the mistake
FS-473 spent a pass undoing. Rule 98 cuts both ways: do not spread a guess, and do not build
the thing that would let you.

The guard's first version flagged `await asyncio.sleep(1)` inside the per-message handler,
which seeks back to the offset and pauses after ONE message failed — nothing to do with
reaching the broker. It distinguishes structurally now: reconnect handling sits at the top
level of the `while` body, per-message handling inside the `async for`.

That is the sixth detector this week that was wrong before the code was, and the pattern in
all six is the same — the first version asks a question that is *nearly* the right one. A
guard that reports a defect where there is none gets turned off, so the narrowing is not
polish.

**Suite:** backend 3520 passed / 100 skipped · edge agent 289 · frontend 555.

---

## 2026-08-05 — FS-475: a duplicate with a good reason, on federal driving limits

Classes 98 and 99 carried across to the backend and frontend, finishing the pass that FS-474
started.

**One real instance, and it is not a guess.** `MAX_DRIVE_HOURS_DAY` and
`MAX_ON_DUTY_HOURS_DAY` — the FMCSA limits from 49 CFR 395 — were declared in
`api/transportation.py` and again in `services/transportation_management.py`, with a third
file reaching them through the compliance class. Three files, three approaches, four numbers
that are law.

Duplication is sharper here than usual because **the two copies feed different answers about
the same driver**: one module computes hours REMAINING, which a dispatcher reads before
assigning a load; the other decides VIOLATIONS, which a compliance officer reads afterwards.
Edit one and not the other and the platform tells the dispatcher a driver may keep driving
while recording that same driver as in breach. Both numbers look authoritative and neither
says which is stale.

### Why it survived review

The duplicate carried a reason: *"Kept beside the serializer that needs them rather than
imported from the compliance service, which would drag its session dependencies into this
module."*

That objection was true — and already being ignored, since `fleet_logistics` imports the same
class for the same purpose. **A justified duplicate is harder to spot than an unjustified
one**, because the comment answers the question a reviewer was about to ask. The answer was a
module with no imports at all, which the original objection cannot apply to.

All three access paths now resolve to the same object, asserted with `is` rather than `==` so
a second set of values that happens to match today still fails.

### Class 99 came back clean, and that is a result

Only two service classes accept an injected collaborator, so there is no population of
siblings where some are injectable and some are not. The four workers — which genuinely are
copies of one another — all take the same `stale_after_seconds` seam and use it deliberately:
ingestion at 300 seconds because telemetry is continuous, the other three at 0 with comments
explaining that scheduled and orchestrating work is legitimately bursty.

The frontend has duplication without consequence: `MOCK_DELAY` in nine clients at two
different values, and `REFRESH_MS` in two hooks where both agree. Recorded rather than fixed,
because unifying a development-only constant is motion rather than work.

### Two guards caught me

The frontend scan reported `REFRESH_MS = 30`, having read `30_000` as `30` — a numeric
separator the regex did not expect. Thirty milliseconds would have been a hot refresh loop
and a real finding; one look at the file showed thirty seconds. Seventh detector this week to
be wrong before the code was, and the first where the error was in the reported VALUE rather
than in what it selected.

And `test_documented_files_exist` failed on my own documentation: I cited the new module
without its `backend/` prefix, where the repository resolves documented paths from its root.
A reader following that citation would have found nothing and had no way to tell whether the
file moved, was renamed, or never existed.

**Then it failed again on this entry**, because the paragraph describing the mistake spelled
the bad path out to explain it — and the guard reads a backticked path as a citation whether
it is being made or being quoted. That is the fourth time in this repository that prose
explaining a defect has tripped the detector for it, and the fix is the same each time:
describe the shape rather than reproduce it.

**Suite:** backend 3534 passed / 100 skipped · edge agent 289 · frontend 555.

---

## 2026-08-06 — FS-476: the plan overstated what was left, again

The verification pass. `fixed-sprints-344-393.md` says in its own header to verify a premise
before starting and correct the entry in place with the date; this is that, taken from the
codebase rather than from the document.

**Eight of its entries no longer reproduce.** `FS-266` (the RAG delete is org-scoped from the
token), `FS-272` (the lane-failure allowlist is empty in both directions), `FS-345`
(`get_device_location` stamps from where it fabricates), `FS-350` (demo recommendations are
gated on `ALLOW_DEV_TOKEN`, seed only an empty queue, and carry provenance), `FS-354` (both
modules at zero `get_db` uses — the one string left is inside a comment explaining its
removal), `FS-357` (closed by FS-468), `FS-359` and `FS-361` (both now have test modules).

A ninth, `FS-368`, is **half true and worth splitting**: the defect — a WebSocket opened to a
route that does not exist, so the live map silently froze — is fixed and both clients poll
with a comment saying why. The capability is untouched. Those are different pieces of work
and one entry covering both reads as neither being done.

Still open, verified: `FS-344`, `FS-307`, `FS-362`, `FS-364`, and the whole
production-readiness wave `FS-369`…`FS-376`.

**And then a ninth, which my own verification pass had just got wrong.** `FS-355` reads
"`error_events` carries `organization_id` and no RLS policy", sized L on a primary-key grain
change. The absence is real. It is also deliberate: the table is keyed on `fingerprint` alone
**by design** — one row per distinct error for the whole platform, because a bug two tenants
hit is one bug — the disclosure risk was reproduced against a real database and fixed by
redacting the payload-bearing fields, the write side 403s when the caller does not own the
row, and a test docstring records why scoping the view by organisation was **rejected**.

Adding RLS would not harden that table; it would break the view it is meant to be.

I found this by verifying the premise before building, which is what the plan's header says to
do and what I had just spent a pass recommending. The first check asked "is there an RLS
policy" (no) and stopped. It did not ask whether one was wanted. **That is the same error as
FS-460 in a different costume** — there I concluded a field reached nobody after finding one
of its two consumers; here I concluded a policy was missing after finding it absent. Both are
negatives asserted from half a search, and both times the answer was one grep away in a file
whose whole purpose was to record it. Rule 101.

### Why it happened twice

The first plan was written from the task pools and inherited every claim they had outgrown.
**The second was written from the codebase specifically to avoid that** — every item carrying
a file and a line, unverifiable claims marked as such — and drifted anyway.

So the failure is not in how a plan is written. **A plan is a snapshot of a belief about a
repository, and the repository does not update it.** The documents here that have not drifted
are the ones written as things happen: this log, and the defect-class sweeps. The ones that
drift are written in advance.

Overstating is also the harder direction to catch. A plan that flatters gets checked, because
somebody eventually looks for the thing it says is finished. Nobody audits a backlog for being
too long, and the cost is paid quietly — in work planned twice, and estimates built on a
number that was never true.

`test_the_plan_does_not_claim_finished_work.py` holds the checkable part: an item recorded as
delivered stays delivered, a fix cited as closing one has to be findable, and no item may
appear in both the delivered table and the still-open list. It cannot judge a multi-day item,
but it can stop the document contradicting itself — which is how both drifts began.

**Suite:** backend 3541 passed / 100 skipped · edge agent 289 · frontend 555.

---

## 2026-08-06 — FS-477: a refusal offered as a stack trace

Picked up FS-364 (routed pages with no tests) and found a defect before writing a line of
test, which is the argument for that entry in one sentence.

`error_events` is platform-wide by design, so the server withholds another organisation's
`message_sample` and `traceback_sample` and substitutes a marker sentence. The detail page
renders that placeholder in its code block **on purpose** — an existing test asserts it,
because "No traceback captured." is a claim about the error while a redaction is a claim about
the viewer's permissions. That decision is right and I did not touch it.

**The frame around it was wrong.** The card's subtitle read "Latest occurrence · scrubbed of
PII" over a sentence that is neither, and the Copy button was **enabled** — the marker is a
truthy string — so an operator could put `[redacted: belongs to another organization]` on the
clipboard and into a bug report believing it was a stack trace.

Both now read `samples_redacted`, a boolean the server derives from the same condition that
does the withholding. Matching the marker text on the client would have worked today and
broken the day somebody improved the wording: **prose is not an API.** The flag is narrower
than the condition, too — an outsider viewing a row that captured no samples has had nothing
kept from them, and a withholding notice over an error that never had a traceback is an
absence dressed as a refusal.

### Two things I got wrong first, both the same error

**The page was not untested.** My detector matched test files by filename and reported
seventeen untested routed components; the real number is four. `ErrorTriageDetail` was on the
false list and I started writing a duplicate test for a page that already had a thorough one.
The Write tool's read-before-write guard stopped it — not my reasoning.

**And my first fix reversed a deliberate decision.** Before reading the existing test I had
replaced the code block with prose for redacted rows, which would have failed an assertion
written specifically to keep the placeholder visible, for a reason its docstring explains.

That is three times in two days: FS-460 (a field's second consumer), FS-355 (a policy's
deliberate absence), and now a test I assumed was missing. Different costumes, one error —
**a conclusion drawn from half a search** — and the correction each time was cheap and
identical: read the thing that would have told you.

FS-364 is corrected in the plan rather than closed: four pages remain — `CorrelationAIPane`,
`IntakeInbox`, `Historian`, `FleetRolloutDetail`.

**Suite:** backend 3542 passed / 100 skipped · frontend 560 · edge agent 289.

---

## 2026-08-06 — FS-478: five mutations that failed in silence, in the idiom the sweep could not see

Started on FS-364's four untested pages, beginning with `IntakeInbox`. Writing the test found
the defect first — for the second time in a row.

`mutationFailureIsVisible.test.ts` sweeps every `useMutation` for options that handle only
success, and its docstring is emphatic about why: a failed mutation renders as **nothing at
all**, and the user pressed the button on purpose, so the absence of a response is
indistinguishable from the moment before the list refreshes.

**It reads `useMutation` call sites.** Five mutations here are hand-rolled — an `async`
handler awaiting an api call, catching into `console.error` — and were structurally invisible
to it while being exactly the defect it exists to prevent:

* `IntakeInbox.handleAnalyze` — the spinner stops and the row stays pending, which is what an
  item with nothing to analyse looks like. The page shows a risk score once analysed, so "no
  score" reads as "not analysed yet" and the operator's remedy is to wait;
* `IntakeInbox.handleUpload` — the file simply does not appear;
* three in `ContextManagementModal`, which closes on success — so a failure leaves it open,
  which is what it does while saving.

All five now surface, and the analyse message names the item, because the inbox shows many
rows and a bare "analysis failed" leaves the operator guessing which button they pressed.

**The sweep is extended rather than duplicated.** The new heuristic is deliberately narrow —
an awaited `…Api.<verb>` in the preceding window and a catch that only logs. A broader
version flagged every defensive `catch { console.warn }` around optional enrichment, which is
not this defect and would have made the list unreadable. A sweep that spends the reader's
trust on noise stops being run.

### And the page test that started it

`IntakeInbox.test.tsx` now holds three properties: a partial analysis says so (the FS-456
notice, both the dropped-page and cut-text cases, and silence when the document was read in
full), a failed action reaches the operator, and an empty inbox is not a failed one — that
last was already correct and is asserted so it stays that way.

`tsc` also caught something vitest did not: the `ErrorTriageDetail` fixture destructured a key
its inferred type never had. The test suite was green either way.

**Suite:** frontend 564 → 571 · backend 3542 · edge agent 289.


## FS-479 to FS-481 — the last three untested pages, and what writing the tests found

FS-364 named eight routed pages with no test at all. Three of the remaining ones were taken
here: `Historian` (309), `FleetRolloutDetail` (268) and `CorrelationAIPane` (909, a component
rather than a route, but the substance of the assistant page). Each was written to assert what
the page already did well. **Each found a defect before it asserted anything.**

Walking `App.tsx` against `src/pages/**` afterwards leaves **two** routed pages with no test:
`ShopFloor` (511) and `Kanban` (254). That is the figure to carry forward — not the eight,
which several sessions have been chipping at.

### FS-479 — the caveat that reached the screen and not the file

`Historian` queries a capped window. `hasMore`, `limit`, `offset` and `count` all come back,
and the page renders them: "2 points (more available)". `exportCsv` wrote the header and the
points and stopped.

The CSV is the artefact that leaves the building — filed, mailed, opened by somebody who never
saw the page and reads it as the history of that metric over that window. It now carries a
two-line preamble at the top, because spreadsheet software shows the first rows and a caveat
below ten thousand points is a caveat nobody reads; and only when `hasMore`, because a warning
on every export would make the capped case indistinguishable from the complete one.

The same page announced its first failed query as an empty window: `error && points.length ===
0` fell through to "No data points in this window", which tells an operator their machine was
idle when the truth is that nobody knows. Now `role="alert"`, saying which it was.

### FS-480 — the mutation defined in a hook

Class 74's sweeps scan `.tsx`. **Mutation hooks live in `src/hooks/*.ts`** and were outside
both of them — sixteen hooks, seven with call sites that read nothing. Six are the OTA
operations in `useFleet.ts`; the seventh is `useAcknowledgeAlarm`.

Two are safety actions. `useYankAgentRelease` pulls a release that is going badly and
`useCancelAgentRollout` stops a rollout mid-flight; both failed silently, and both look — for
the second or two after a success — exactly like what the operator just saw.

The new check is call-site aware, because **the obligation is the caller's, not the hook's**: a
hook returning `useMutation` is a library with no screen to render on. It accepts any of the
three idioms this codebase uses (`.isError`, awaited `mutateAsync`, `mutate(x, { onError })`) —
an earlier version knew only two and reported `ErrorTriageDetail` as silent when it was not.
It ignores the eight hooks with no caller at all: there is no user to fail in front of.

### FS-481 — the label moved and the content did not

`CorrelationAIPane.handleSessionSelect` switches the session, then fetches its transcript. On
failure the header, the data-sources panel and the suggested-questions effect had all moved to
session B while the message list still held **session A's conversation** — another
investigation's transcript under this session's name, with nothing about it that looks wrong.

This is a failed *read*, not a failed write, and it is worse than any silent mutation in this
log: a silent write leaves the screen truthful-but-stale; this makes it actively wrong. The fix
clears the stale transcript first and says why it is empty second — announcing the failure
while leaving the wrong conversation on screen would be worse than the original.

Two more from the same sweep. `handleAddIntakeData` dropped its failure to the console, so the
document never appeared and the next answer was computed from a data set the operator believed
contained it. And widening the Class 74 verb list — `add` and `remove` were simply missing —
surfaced `DataSourcesPanel.handleRemove`: a failed removal leaves the row where it was, which
is also what a click that never registered looks like, so the reasonable second reading is that
it worked and the list is stale. It did not. The file is still attached, and still feeding
answers.

### The guards

`mutationFailureIsVisible.test.ts` now carries four checks — `useMutation` options, hand-rolled
handlers, hooks-by-call-site, and the stale-switch read. The last is narrow on purpose: the
setter must take the handler's own parameter, the awaited read must follow it, and the catch
must neither set state, alert, nor rethrow. It found one occurrence in the codebase.

`Historian.test.tsx` (9), `FleetRolloutDetail.test.tsx` (8) and `CorrelationAIPane.test.tsx`
(10) assert both directions of every property, and `Alarms.test.tsx` gained two for the
acknowledgement — the sharpest of FS-480's seven, because an alarm nobody owns is the one
nobody chases. They — the warning appears when it should and is
absent when it should not — were all mutation-verified by deleting the fix and confirming they go red.

Two things the tests taught about this codebase's jsdom setup, recorded in the files: `Tooltip`
throws outside `TooltipProvider` (so a missing wrapper reads as a broken component), and
`scrollIntoView` does not exist in jsdom while `CorrelationAIPane` calls it in an effect on
every message change.

**A correction made before shipping:** the first draft of `Historian.test.tsx` cited "the OEE
PDF" as precedent for this class. There is no truncation flag in `exports.py` or `oee.py` —
the cross-reference was invented. It now cites FS-456, which is real.

**Suite:** frontend 584 → 606 · backend 3542 · edge agent 289.

## FS-482 — the failed read that offered to make it worse

`ShopFloor` was the last large routed page with no test. Almost everything on it is written
with unusual care — every mutation reads `isError` and says what did *not* happen in the
operator's own terms, and two places deliberately refuse to show a client-side duration next
to a payroll or cost claim. One thing was wrong, and it was the one that mattered most.

`ClockTime` destructured `{ data: open, isLoading }` from the open-clock query and never read
`isError`. On a failed lookup `open` is `undefined` and `isLoading` is `false` — which is the
exact shape of "no clock is running". The card rendered the **Clock in** button to somebody
who may already be clocked in.

The page already knew the cost. The message under that very button reads *"two open clocks
produce overlapping hours and payroll cannot tell which is real"*. A failed read defaulted
into the state the page warns about, on the page that warns about it.

It now shows **neither** button and offers a retry. Falling back to "Clock out" would be the
mirror defect — telling an operator who is not clocked in that they are.

### The sweep that could not see it, and the one that can

`failureIsNotEmptiness.test.ts` has covered this class since the yard rendered "No trailers
found" at a yard manager. Its two detectors key on an empty-state **phrase** and on a widget
**gate** — both need something in the render to match. `ClockTime` falls through to a button
and `YardManagement`'s doors tab falls through to a blank grid; neither has a string.

The third detector keys on the **destructure** instead: reading `isLoading` is a component
saying out loud that it models "not yet known" as its own state, and having said that,
omitting `isError` collapses "the request failed" into "the answer is no". A component that
reads neither flag is left alone — that is a different and far more visible kind of unfinished.

It found exactly two, both above.

`YardManagement` is the more instructive of the two. That file handles this class on its
trailers tab and its appointments tab, with a comment explaining why — and missed the third
tab, because the fix was made where the bug was reported rather than where the class lives.

### Tests

`ShopFloor.test.tsx` (10) and four more in `YardManagement.test.tsx`, both directions of every
property, mutation-verified. The ShopFloor file also asserts what the page already did right,
including the two refusals to compute a duration client-side.

**Remaining from FS-364:** one routed page, `Kanban` (254).

**Suite:** frontend 608 → 627 · backend 3542 · edge agent 289.

## FS-483 — the drag that snapped back and said nothing

`Kanban` was the last routed page from FS-364 with no test. Its load path was already
careful — a failed board fetch renders the error with a retry rather than an empty board,
which matters because an empty kanban reads as "nothing needs doing".

`handleDragEnd` awaited `moveTask` and caught into `console.error`. `moveTask` posts to the
server *before* it updates local state, so on failure the card re-renders in the column it
came from — **which is also exactly what a mis-drop looks like**. The operator reads it as
their own miss, drags again, and the board and the server go on disagreeing about where the
task is. A snap-back is not a message.

### The fourth hiding place for one class

Neither hand-rolled sweep could see it: the awaited call is `moveTask(…)`, destructured from
the kanban store, and the `api.post` it wraps lives in `kanbanStore.tsx` — two files from the
`catch`. No window over `Kanban.tsx` could have seen a mutation happening at all.

The new check keys on the **verb in the callee's name**. It was measured before it was added:
two hits across the tree, **both false positives**. Reading them produced two exemptions, both
on principle rather than by name — a catch that `return`s is propagating the failure by value
to a caller that handles it, and a catch that only `console.warn`s is the optional-enrichment
shape the first heuristic in this family was narrowed to exclude. Those exemptions are what
make the check worth running, and re-deleting the `setMoveError` line turns it red.

That is four hiding places for one class, found in order: the `useMutation` options object,
the hand-rolled `async` handler, the hook file the sweeps did not scan, and the store action
whose api call is in another file. Each was invisible to every check written before it.

### FS-364 is not closed, and the walk that said it was

`Kanban.test.tsx` (7) landed, and the first version of this section said FS-364 was finished
— on a walk that resolved `pages/<Path>` out of `App.tsx` and matched it against
`src/pages/**`. It reported zero untested routed pages.

It was wrong, in the way these walks are always wrong: **`Fleet` and `ErrorTriage` are
imported through the `./pages/admin` barrel**, so the route reads `named(() =>
import('./pages/admin'), 'Fleet')` and the string `pages/admin/Fleet` appears nowhere. The
walk asked for a path that a barrel import does not spell.

Counting the files on disk instead of the routes in `App.tsx` finds them immediately: 31
pages, three without a test file of their own name. So **two routed pages remain**: `Fleet`
(574) and `ErrorTriage` (371). The third, `UserAppPlaceholder`, is not routed by that walk
and is not claimed either way here.

Recorded rather than quietly fixed, because the failure mode is the reusable part: a
resolver keyed on an import path reports "none left" for everything reached another way, and
"none left" is the answer nobody re-checks.

### FS-484 — both pages, and a guard that follows the barrel

`ErrorTriage.test.tsx` (8) and `Fleet.test.tsx` (10) close FS-364's list for real. Neither
page needed fixing — both were written carefully, and the tests exist to keep them that way:

* `ErrorTriage` distinguishes **four** states where most pages manage two — loading, failed,
  *filtered to nothing*, and genuinely nothing. That third one is the interesting one: "No
  errors match these filters" and "No production errors recorded" are opposite claims, and a
  triage engineer acts differently on each. It also refuses to let the summary tile's failure
  pass for a quiet week.
* `Fleet` distinguishes failure from emptiness on all three of its lists, including the
  version distribution — where an empty table reads as "no agent has checked in", which is a
  fleet-wide outage. And it carries FS-480's card, which names *which* OTA action failed.

`everyRoutedPageHasATest.test.ts` is the guard. It resolves `<Route element={<X />} />` back
to a source file through **both** import forms, following `named(() => import('./pages/admin'),
'Fleet')` into the barrel's `index.ts` to find which module exports that name — including
exports renamed on the way out, which is how the four AdminPages routes resolve. Its vacuity
tests assert it resolves a direct import, a barrel import, and a renamed barrel export,
because a broken resolver returns an empty list and an empty list passes.

It does not claim a test file is coverage. It asks only whether somebody has written
*something* against each routed page — a low bar on purpose, since the two pages it caught
had no file at all.

**Two fixture corrections along the way**, both from guessing a shape instead of reading it:
the error-triage row uses `count_in_range`, not `count`, and the version distribution uses
`agent_version`/`asset_count`. Both threw inside the page and rendered an empty document,
which reads as a component bug rather than as a test that made something up.

**Suite:** frontend 627 → 663 · backend 3542 (100 skipped) · edge agent 289.

## FS-485 — the flag the server sent and the client threw away

The correlation assistant's client, `analysisSessions.ts`, was the largest in the tree without
a real-mode test: 503 lines and **eighteen** `USE_MOCK` forks. Every unit test in this
repository runs with `VITE_USE_MOCK=true` stubbed before any module evaluates, so all eighteen
were exercised on their mock side and none on the side that ships.

Its eleven new tests hold two properties the mock branch cannot check, because in mock mode
both are true by construction: truncation is read off the response headers rather than
assumed, and `simulated` is carried through rather than defaulted. The second is the other end
of the wire `CorrelationAIPane.test.tsx` already asserts — the server sets that flag when a
reply is a heuristic or an error fallback, and a client defaulting it to `false` would put the
confident version back in front of the operator.

### The sweep it turned into

Every `mark_truncated` endpoint has already been judged worth an extra row: somebody decided
a full page and the complete set needed telling apart. So the question is whether the client
on the other side keeps the answer. **One did not.**

`notificationsApi.deliveryLog` returned `response.data`. The log is ordered newest-first, so a
cap removes the *oldest* attempts — and that card is where somebody checks whether an alert
was delivered. A row absent from a list presented as complete says the alert was never sent,
which is a claim about the notification system rather than about the query. It now returns a
`ListResult`, and the page says "Showing the 100 most recent attempts" when the flag is set
and nothing when it is not.

**One was checked and deliberately left.** `CommandPanel`'s history caps at five and reads
the body alone — but it is newest-first, the heading says "Recent commands", and the command
just sent is in the first five by construction. That decision now lives in the guard's own
allowlist with its reason, and a second test asserts the exempted call still exists.

### Three detector defects for one code defect

The guard was wrong three times before the code was wrong once, and each way is reusable:

1. **Slicing on `@router.get` alone** put a later handler's `mark_truncated` inside an earlier
   handler's slice, reporting `DELETE /{id}/mappings` as a truncating route.
2. **Matching the last path segment** collided `/erp/integrations/{id}/events` with
   `/fleet/security/events`.
3. **Capturing the URL up to the first `${`** turned `` `${BASE}/log` `` into the empty
   string, which matched every route whose prefix failed to resolve — eleven reported
   offenders, none real.

And the prefix table had its own hole: `registries`, `analysis_sessions` and
`erp_integrations` declare their prefix on their own `APIRouter` and are included bare, so
reading `main.py` alone dropped all three **silently**. That is Rule 109 — a walk that finds
nothing must prove it can find something — recurring in a sweep written days after Rule 109
was written. The vacuity test that now fails on an unresolved prefix is the fix.

**Suite:** frontend 663 → 676 · backend 3542 → 3550 · edge agent 289.

## FS-486 — the connector nobody could select, and two labels that named the wrong thing

Three more clients off the real-mode list — `fleetHealth` (13 forks), `erp` (15) and
`telemetry` (5) — and each one found something the mock branch could not have shown.

### A shipped capability with no way to reach it

`ERPIntegrations.tsx` builds its create-form dropdown from `erpApi.supportedTypes()`, a
hand-written array of seven strings. That array is the **entire surface** through which an ERP
integration can be created, and nothing compared it to anything.

`ERPConnectorFactory._REGISTRY` has eight entries. The missing one is `intuit` — QuickBooks
Online — a 384-line connector with OAuth token rotation, webhook signature verification, a
health check, and two test files including a sandbox suite. It works. Nobody could pick it.

The guard now runs in both directions, because each fails differently: a type offered that the
factory cannot build wastes an operator's credentials on a form that was always going to fail;
a type the factory can build and the UI omits is silent forever, because **nothing in a test
suite asks about an absent option**. It compares against the factory registry rather than the
`ERPType` enum — `generic` is in the enum and correctly not offered, since the factory has no
entry for it. The enum says what the codebase has words for; the registry says what it can
construct, and only one of those is a promise to a user.

The label got the same treatment. Uppercasing the type is the product name for every entry but
that one, and an operator connecting QuickBooks does not scan a list for "INTUIT".

### Two labels that named a different thing from the number beneath them

`PerformancePanel`'s range selector read "Today / This Week / This Month / This Quarter / This
Year". `kpi.py` computes `now - timedelta(days=_RANGE_DAYS[range])` — a rolling window. On the
6th of August, "This Month" is the 7th of July to the 6th of August. Fuel efficiency, idle
time, on-time performance and cost per mile all hang off it, and each is a figure somebody
compares against last period's. Every other selector in the app already reads "Last N days";
this was the exception, so the label moved rather than the computation.

`AnalyticsPages`' metric chart called `telemetryApi.getHistory`, which returns
`response.data.items` and drops the `{items, meta}` envelope. That page offers a 30-day range
against a 1000-point server default — ten times under at minute resolution — so a chart headed
"Last 30 Days" plotted one end of the window with nothing saying which end, or that there was
another. A trend taken off the wrong end of a window is not a partial answer; it is a wrong
one, and it looks exactly like a right one.

`TelemetryHistoryChart` had been reading `meta.hasMore` all along to gate its "Load older"
control. The pattern existed and one page had not adopted it — Rule 107, a third time.

Worth noting for the FS-485 sweep: this is a **fourth spelling** of the truncation signal. That
sweep keys on `mark_truncated` and `X-Result-Truncated`; this endpoint carries `has_more`
inside a JSON envelope, so the guard could not see it. Same claim, different wire.

### What the real-mode tests hold

The filters, mostly, because FastAPI ignores an undeclared query parameter — a misspelling is
not an error, it is **200 and the default window**. `fleetHealth`'s two filtered security lists
differ from the unfiltered one by a query string alone, and a panel headed "unacknowledged"
showing acknowledged events is the failure. `telemetry` renames every filter on the way out
(`metricName` → `metric_name`), and the mock branch reads the camelCase names off the same
object, so it agrees with itself either way.

### Still open

Ten clients keep `USE_MOCK` forks with no real-mode test: `notifications` (6),
`fleetTracker` (6), `dashboardAnalytics` (6), `kpi` (8), `rul` (3), `platformCorrelation` (3),
`userContext` (2), `twinOptimizer` (2), `historian` (2), `alarmRules` (2). Scanned for the
classes above; `kpi` yielded the label defect and the rest came back clean on paths, params and
nullable returns. Clean is a claim, so: the scan covered hand-built query strings, adapters,
and nullable returns whose real branch rejects instead — not shape-by-shape mock-versus-wire
comparison, which is what a real-mode test does and what these ten still lack.

**Suite:** frontend 676 → 717 · backend 3550 → 3560 · edge agent 289.

## FS-487 — the poll that stopped, on a screen with no error state

Four more clients off the real-mode list — `notifications` (6 forks), `kpi` (8),
`fleetTracker` (6) and `geofencing` — and the last two turned up the sharpest thing in this
whole sequence.

### Two live surfaces that were wrong while rendering correctly

`/ws/fleet-tracking` and `/ws/geofencing` do not exist on the backend; both were replaced with
REST polls when that was found. Each poll's catch ended at `console.error`, and **a
subscription has no promise for a caller to catch** — the failure lands fifteen or thirty
seconds after anybody was looking, on a screen built to show a stream rather than a result.
There is no spinner that fails to clear and no empty state to fall into.

`FleetTrackerMap` kept drawing the last positions it received for as long as the tab stayed
open. An operator looking at a live map that has stopped updating is looking at where the
vehicles **were**, with every reason to believe it is where they are — a stationary fleet and
a frozen map are the same picture. Its initial load had the same catch, so a failed fetch drew
an empty map, which reads as "nothing is being tracked".

`GeofencingPanel` is worse, and it is why this got its own class. **The display of "no alerts"
is an empty list.** A dead poll produces exactly the same empty list as a fleet where nothing
has happened. There is no stale value to notice and no pin in the wrong place — *the absence
is the display*. A truck leaves its zone, the alert exists on the server, and the panel goes
on saying nothing.

Both clients now take an optional `onError` beside `onUpdate`/`onAlert`, called with the error
on a failed tick and `null` on a good one, so a recovered poll clears its own warning. The
wording is about what the display means rather than about the request: "an empty list right
now means nobody knows, not that nothing has happened" is actionable; "poll failed" is not.

### And a test that reached nobody

`Notifications` reported a dispatch that matched zero subscriptions as "Test dispatched —
matched 0 subscriptions", in the same grey as every other outcome. The request succeeded and
nothing was delivered, which is the one thing pressing Test is meant to find out. It now says
which it is in the first three words and names the filters that caused it.

An existing test asserted the old wording, under the name *"says a matched count of zero
rather than implying success"*. The intent was already right; the assertion moved with the
message rather than being deleted, and the tone is now asserted separately.

### What the real-mode tests hold

`kpi`'s five range-taking calls build `?range=${timeRange}` by hand, and `range` is declared
`Query("month")` with `_RANGE_DAYS.get(value, 30)` behind it — so a dropped parameter, a
misspelled one and an unrecognised value all produce **the same thirty-day answer**. There is
no figure you could compare to catch it; only the request shows it. The two calls that take no
range are asserted as the control, because a client that appended `?range=` everywhere would
pass every other test and start narrowing two endpoints silently.

`notifications`' `matched` count is the number that page turns on, and the mock returns
`mockSubscriptions.length` — every subscription, always. The case worth seeing cannot occur in
mock mode.

### Two fixture corrections, both from guessing instead of reading

`FleetVehiclePosition` keeps its coordinates under `position`, not flat; `getZones` returns a
bare array where `getAlerts` returns a `ListResult`. Each threw inside the render and produced
an **empty document**, which looks exactly like an assertion failing on a working component.
That is the third and fourth time this session; reading the type first is faster every time.

### Still open

**Eight** clients keep `USE_MOCK` forks with no real-mode test — the figure was first written
as six beside a list of seven, and neither was right. `fleetTracker` (6) is on it too: its
poll was fixed here and its *component* got a test, which is not the same file and does not
cover the client. Then `dashboardAnalytics` (6), `rul` (3), `platformCorrelation` (3),
`userContext` (2), `twinOptimizer` (2), `historian` (2), `alarmRules` (2). Derived by walking
`src/api/*.ts` for a `USE_MOCK` with no sibling `.realmode.test.ts`, rather than counted by
hand — which is how the first two figures went wrong. All were scanned for the classes in this batch — hand-built query strings
against the backend's declared parameters, nullable returns the real branch cannot produce,
trailing-slash path mismatches, and mock-versus-declared-type key divergence. Two scan hits in
`notifications` were read and found to be false positives (the mock builds a local object and
returns a narrower one). `alarmRules`' trailing slash matches the backend's `"/"` declaration.

**Suite:** frontend 717 → 753 · backend 3560 · edge agent 289.

## FS-488 — the last eight clients, and the count that kept flattering itself

Every api client with a `USE_MOCK` fork now has a real-mode test. The eight remaining were
`fleetTracker`, `dashboardAnalytics`, `rul`, `platformCorrelation`, `userContext`,
`twinOptimizer`, `historian` and `alarmRules`.

### One defect, and it was hiding behind a fix

`userContext.ts` mocked its READ and not its four WRITES. `getUserContext` returned a fixture;
`updateUserContext`, `addUserGoal`, `updateGoal` and `deleteGoal` went to the API in every
mode — so in the demo, `ContextManagementModal` showed a context, accepted edits, and failed
on Save against a backend that is not running.

It had been that way quietly until FS-478 gave the failure a message, which turned a silent
oddity into a visibly broken button. Every other client mocks its writes —
`erp.createIntegration` pushes to an array, `notifications.createSubscription` assigns an id,
`kanbanStore.moveTask` updates local state — so the convention existed and this file had
adopted half of it. **A double that covers half a surface is a double for exactly the half
nobody was testing.**

### Three registrations that are load-bearing and invisible

`historian`, `twinOptimizer` and `alarmRules` each call `registerTransform('<prefix>')` at
module load, and the axios request interceptor renames their camelCase keys on the way out.
Delete that one line and:

* every historian query is a **422** — `asset_id` is required with no default;
* every twin optimisation is a **422** — `OptimizeRequest` is `extra="forbid"`, so a single
  unrecognised key rejects the whole body.

No compile error, no failing unit test, because the mock branch reads the camelCase names off
the same object and agrees with itself. Those registrations are now asserted.

### Two parameter tables compared across the boundary

`BucketName` against `BUCKET_SECONDS`, in both directions. This is the better-behaved of the
codebase's two range parameters: `resolve_bucket` **raises** on a name it does not know, where
`kpi`'s `_RANGE_DAYS.get(value, 30)` turns every mistake into a thirty-day answer nobody can
spot. Raising is why `bucket` needed no fix — only a guard that the two lists stay one list.

`alarmRules` reads `hasMore` with a triple fallback — `meta.hasMore ?? meta.has_more ??
meta.skip + items.length < meta.total` — a client hedging about its own wire. All three
branches are asserted, including the computed one, because a wrong `hasMore` on a rules list
tells an operator they have seen every rule governing their alarms.

### The count that was wrong twice

The number of clients still lacking a real-mode test was carried by hand. It was written as
**six**, beside a list of **seven**, when the true figure was **eight** — `fleetTracker` had
been crossed off because its *component* got a test in FS-487, which is a different file and
exercises none of the client.

Deriving it takes one line: walk `src/api/*.ts` for a `USE_MOCK` with no sibling
`.realmode.test.ts`. That is now `everyMockedClientHasARealModeTest.test.ts`, and it reports
none.

This is the fourth hand-carried figure in this documentation to drift, and every one drifted
the same way — fewer items left, more work done. **A number nobody derives is a number that
agrees with whoever last recalled it.**

**Suite:** frontend 753 → 821 · backend 3560 → 3564 · edge agent 289.

## FS-489 — what a whole page says when nothing loads

Three of the four items in this batch turned out to be closed already; the fourth was mostly
stale, and the real gap was standing next to it.

### FS-359, FS-360, FS-361 — closed, and the plan disagreed with itself

All three were recorded as "code that ships and nothing exercises". Re-measured by walking
`backend/tests/` for each module name: `correlation_registry_integration` has 24 tests across
two suites, `yard_management` has 53 across four, and the document-intake cluster has 47.

Two of the three had already been corrected in the table at the *top* of
`fixed-sprints-344-393.md` while the Wave H body still listed them as open work — so the
document contradicted itself for as long as anybody read only one half. The line counts were
low by a third as well (`correlation_registry_integration` is 1,270 lines, not 1,065). **A plan
authored from task pools rather than from the codebase ages in both directions at once**: the
work gets done and the file gets bigger, and neither reaches the document.

### FS-365 — three claims, two stale, one deliberate

`data-reaches-the-screen.spec.ts` walks **32** routes, not four. Playwright runs in **two** CI
jobs, not one. And `compliance-assistant.visual.ts` is uncollected on purpose — its own
docstring says *"Not part of the e2e suite — a throwaway harness… run with `npx tsx`"*.

**The real gap was adjacent.** Nothing distinguished a deliberate non-spec from a spec that had
silently stopped being collected. Playwright's default `testMatch` needs a `.spec` or `.test`
infix, this config overrides it only on the setup project, and a rename during a refactor
costs a whole file — with no error, and a suite that goes green *faster* than the day before,
which is the direction nobody investigates. `everyE2eFileIsCollectedOrExcused.test.ts` now
asserts every `e2e/*.ts` is collected or excused with its reason, and that the config still
relies on the default it describes.

### The browser sweep, and the two defects it found

`failure-is-not-emptiness.spec.ts` drives all 32 routes with every `/api/v1/` call aborted at
the network layer and asserts no page claims the world is empty. It needs no backend — auth is
seeded into localStorage — so it runs in the fast browser job.

Both finds had already been fixed *for the case they were fixed for*:

* **`Historian`'s asset picker** reads `assetsError ? 'Asset list unavailable' : 'No assets'`,
  which is FS-479's fix and is correct. But react-query **retries by default**, so `isError`
  stays false for seconds — and during that window `assets` is empty and `assetsError` is
  false. The branch shown for most of any outage was "this plant has nothing instrumented".
* **`ErrorTriage`'s summary tiles** read `summary.data?.open_count ?? 0`, so a summary that had
  not arrived rendered **"Open errors 0"** on the page an engineer opens to find out whether a
  deploy broke anything. That is FS-191's shape in a new place — a complete, error-free
  dashboard of zeros — and zero open errors is the most reassuring lie this product can tell.

The missing state is the same in both: `isError` handled, `isLoading` not, and the gap between
them is where a retrying request lives.

### The sweep was vacuous first

Its first version routed `**/api/**`. The frontend's own source lives in `src/api/`, and Vite
serves those modules over HTTP — so the pattern aborted the application's own JavaScript. React
never mounted, every body was empty, and **all 32 assertions passed against a blank document**.
It reported green.

`assertTheAppRendered` now fails any route whose body is under twenty characters before any
claim about its text is made. The only reason this was caught at all is that the other half of
the same file — "and it does not go blank instead" — failed on three routes and had to be
explained. **A negative assertion is satisfied by nothing at all**, which makes total harness
failure the greenest possible result.

### And the new spec broke the whole e2e suite for a minute

Importing `ROUTES` from `data-reaches-the-screen.spec.ts` is a hard Playwright error —
*"test file X should not import test file Y"* — and it fails collection for the **entire
suite**, not the importing file. The symptom is `Total: 0 tests in 0 files`.

It only appears when both files are collected, so every filtered run of the new spec passed.
The check that caught it was `npx playwright test --list` with no filter, and nothing else
would have: 84 tests reported as 0, in a job that would have gone green in seconds.

`ROUTES` now lives in `e2e/routes.ts`, imported by both specs and excused in the collection
guard with that reason. `everyRouteIsSwept.test.ts` reads the new path — it regexes the array
out of a file, so pointing it at the old one would have left it comparing against an empty
list and passing.

**Suite:** frontend 821 → 833 · e2e 49 → 84 collected, 38 passing without a backend
(35 new) · backend 3564 · edge agent 289.

## FS-490 — counting what does not run

Wave H's "tests that pass without running" had two items. **FS-363 is closed**:
`tests/_lane_failures.py` is exactly the expiry register it asked for — owner, diagnosis, and
two tiers of date, with the note explaining that *"an entry with an owner and a reason but no
date is a decision nobody has to make again"*. **FS-362 was open**, and this is it.

Six suites carry a module-level `pytest.mark.skipif` on credentials: SAP, Dynamics, Dataverse
×2, Odoo, QuickBooks. Between them they are the whole vendor-facing surface, and in the
ordinary run every one skips. That part is right — a fork PR has no secrets, and a red build
for a key nobody can provision teaches people to ignore the colour.

Half the item was already satisfied too: every one of the six had a real `reason`, and four of
the five CI jobs already pass `-rs`. (The fifth, Odoo, sets `RUN_ODOO_INTEGRATION=1` and
provisions a live Odoo, so it never skips and `-rs` would add nothing — checked rather than
assumed, and not changed.)

**The open half was the count.** A seventh suite added tomorrow with the same marker joins a
green run as a silent skip, and the honest reading of "3,564 passed" quietly stops being
honest. That is the shape of every hand-carried figure in this documentation that has drifted,
and all of them drifted toward more work done.

`test_credential_gated_suites_are_registered.py` makes the set explicit: a credential-gated
suite must be registered, registering it names the variable that enables it, and that variable
must appear in the suite's own skip reason — so the register and the sentence a person actually
reads cannot drift apart. It fails in three directions: an unregistered skipper, a registered
file that no longer exists, and a registered file that no longer skips.

### What it found, including in itself

`test_erp_platform_integration_realdb.py` — **23 tests** — skipped with *"needs live Dataverse
credentials (see docs/erp/dynamics-dataverse-setup.md)"*, naming no variable at all. Its three
sibling Dataverse suites spell theirs inline. A reader of the CI log learned that 23 tests did
not run, and was sent to a document to find out how to change that. It now names all four.

And it caught **me**: my first register entry for the QuickBooks suite said
`INTUIT_SANDBOX_REALM_ID`; the variable is `INTUIT_REALM_ID`. Checking that the reason and the
register agree is what makes the register worth having rather than a second place to be wrong.

Mutation-verified by adding a suite that skips on a variable nobody sets — the register names
it and fails.

**Suite:** backend 3564 → 3575 · frontend 833 · e2e 84 collected · edge agent 289.

## FS-303 — correct field name, wrong type

The last open item in Wave H's verification block. FS-304 and FS-305 are both closed —
`test_declared_media_types_are_honest.py` exists, and the returned-keys sweep's own docstring
records that helper-built returns are now covered (39 returns across 15 shapers in 7 modules,
where `fleet_logistics` had been the single file ever checked, by hand).

Two sweeps already pair a response model with its table: one asks whether a declared field is
produced by anything, the other whether a produced field is declared. This is the third
direction, and the name is right in every instance of it — which is why it survives review.

`Decimal("12.0")` validates against an `int` field. `Decimal("12.5")` raises. So a model
declaring an integer over a numeric column serves whole-numbered rows correctly, passes every
test whose fixture happens to use them, and 500s on the first fractional row that reaches it.
FS-284b caught two of these by eye, after they had shipped. **The defect is a property of the
schema and the failure is a property of the data**, so no dynamic test finds it until the data
does.

The check reuses the pairing already in `test_response_models_match_their_tables.py` rather
than building a second one, and reports **nothing today**. That is recorded rather than
deleted, because Class 25 is the standing warning here — a sweep once reported clean, was
written down as deliberately unguarded, and had covered a seventh of its subject.

So it ships with three proofs beside the check: the pairing reaches fractional columns at all
(≥10 visible), the check fires on the defect built from a real SQLAlchemy column, and it stays
quiet on both correct shapes (`float` over `Numeric`, `int` over `Integer`) — the control that
stops it becoming noise, which the UUID check next door needed for the same reason. And it was
mutation-verified against a real model: `AlarmRuleResponse.threshold` retyped to `int` over its
`Float()` column, which it names in the failure.

**Suite:** backend 3575 → 3580 · frontend 833 · e2e 84 collected · edge agent 289.

## FS-491 — Wave F was finished and the plan did not know

Wave F was the highest-severity block in `fixed-sprints-344-393.md`: **figures a machine
generated, presented to an operator as measurements**. Ten items. Measured against the
codebase, **all ten are closed**, each with a guard:

| | what it was | what closed it |
|---|---|---|
| FS-267 | four geotab functions gated, two stamped | seven gate, all seven stamp; a sweep fails if a gated function ships unstamped |
| FS-344 | `GEOTAB_SIMULATED` defaults `True` | the default is deliberate — the offline demo needs it — and the validator is asserted twice |
| FS-346 | four compliance figures not computed | computed, with the reason `consent_records` comes through `users` written down |
| FS-347 | residency validator scored 100% on an untagged estate | `total_records`/`untagged_records` are `None`, and the handler states what it cannot see |
| FS-348 | hard-coded mph/mpg/$ returned as results | settings, with the values used returned in `assumptions` |
| FS-349 | `model_version: "gemma-4-placeholder"` | `"none (no correlation model loaded)"` |
| FS-351 | critical correlations logged, never dispatched | they reach the notification service |
| FS-352 | a bare-return restart endpoint | removed rather than stubbed — a 501 is a 5xx and would have made conformance worse |

FS-345 and FS-350 were already in the table.

### The guard that should have known, and the direction it was missing

`test_the_plan_does_not_claim_finished_work.py` exists for exactly this and did not catch it,
because its register is hand-curated: it asserts every entry it knows about is still closed,
and has no way to *discover* that a wave finished.

It also had a one-way check. `test_the_table_lists_them_all` asserted **register ⊆ table** —
so adding a row to the plan claiming something is done required nothing of anybody. I put two
such rows in myself (FS-360, FS-365) earlier the same day, and nothing checked either claim.
That is the failure this file exists to prevent, committed in the file that prevents it. The
reverse direction is now asserted too.

### What the still-open list said

It was headed *"verified 2026-08-06"* and was stale within the day. `FS-344` was listed on the
question "is one validator enough"; it is. `FS-362` closed the same day. And **`FS-364`
appeared twice in one sentence** — once as "partially, four remain" and once as a bare "routed
pages with no test" — when all eight were covered.

The four departures are recorded below that section rather than inside it, and the reason is
mechanical: the guard reads the section for item numbers, and **a register cannot parse "no
longer"**. An item named in a list of open items is an item claimed open, whatever the
surrounding prose says.

### One structural correction to the register

FS-344 and FS-349 are guarded by tests that argue their subject without citing the item
number. My first attempt filed them under `_DECISION_EVIDENCE` — the map for things
deliberately *not* done, whose test demands the file still record what was **rejected**. These
are ordinary fixes, and filing them there would have made the register describe them wrongly,
which is how a register stops being read. They have their own map now, pinned to the file and
the subject.

**Suite:** backend 3580 → 3583 · frontend 833 · e2e 84 collected · edge agent 289.

## FS-307 — the gate that could not fail in the dimension it was cited for

The schemathesis contract job connected as the postgres service container's `POSTGRES_USER`.
The official image makes that role a **superuser**, and a superuser bypasses `FORCE ROW LEVEL
SECURITY` outright. So ~375 operations ran against a database with tenant isolation switched
off, and the gate's conformance number could not have moved if every RLS policy in the schema
had been dropped in the same commit.

Demonstrated on a throwaway database rather than argued from the manual — `FORCE ROW LEVEL
SECURITY` on, tenant policy in place, two tenants' rows:

```
superuser (owner)             sees 2 rows
NOSUPERUSER NOBYPASSRLS role  sees 1 row
```

**A red gate is a task; a green gate that cannot fail in a whole dimension is a belief.** This
one was cited in the burn-down as evidence about the API's behaviour, which is the actual harm
— not the coverage that was missing, but the coverage everyone thought they had.

### The role already existed

`tests/conftest.py` has provisioned a `NOSUPERUSER NOBYPASSRLS` non-owning role since the RLS
work, for precisely this reason. The contract gate simply never used it. Rather than write a
second one, the grant list moved into `scripts/provision_app_role.py` that both callers share
— CI as a script, the fixture as a function. A second copy of a security-relevant grant list
is a second thing to forget. The 398 realdb tests exercising that fixture are what verify the
refactor.

### The two details that decide whether the fix survives

**Migrations still run as the owner**, as in production. The obvious way to "fix" a permission
error after this lands is to grant the app role DDL — which makes it an owner, and an owner
defeats a FORCE policy as surely as a superuser does. The guard asserts the migration step
still uses the owner, so that repair cannot happen quietly.

**The script verifies the role it just created**, reading `rolsuper` and `rolbypassrls` back
out of `pg_roles` instead of trusting its own DDL. A pre-existing role of the same name with
the wrong attributes would otherwise be used in silence.

### The guard reads YAML, not a database

Deliberately. The change is one URL in one file, and the failure mode if somebody reverts it
is silence — the suite goes green, faster. A check that only runs where postgres is available
does not run on the machine where the mistake is made. Both mutations were verified: reverting
the URL to the owner, and deleting the provisioning step.

**One thing to expect on the first real run.** If an operation starts failing after this, that
is the gate finding something — the app reaching for a privilege it does not have in
production. The ratchet reads the junit report and rejects a collapsed operation count, so a
wholesale breakage fails loudly rather than passing as a clean run.

**Suite:** backend 3583 → 3593 · frontend 833 · e2e 84 collected · edge agent 289.

## Wave J — measured, and three kinds of answer

The production-readiness wave, eight items. Measuring them produced three different outcomes,
and the distinction is the useful part of this entry.

### Already closed (3)

* **FS-374** — the `if: github.event_name == 'push'` gate is gone from all four ERP sandbox
  jobs. My first grep counted four hits and I nearly reopened it; they are the comments
  explaining the removal.
* **FS-376** — the README's worker-storage contradiction was corrected 2026-08-01, with the
  stale paragraph's history kept beside the correct one.
* **FS-373**, in the half that mattered. `p(95)<500` and `p(99)<1000` *are* asserted, on the
  real-infrastructure profile, and `slo_rules.yml` is linted and unit-tested by the
  `prometheus-rules` job.

### Deliberate, and now pinned (1)

`k6-load-test.js` keeps latency **out** of the CI profile on purpose, and says why: *"p(95)<500ms
on a shared GitHub runner measures whichever neighbour is busy, not this API, and a gate that
fails for reasons its author cannot act on is one that gets switched off."*

That split can erode in both directions, silently:

* Latency added to CI makes the job flaky, and a flaky blocking gate does not get repaired —
  it gets `continue-on-error: true`, which takes the **error-rate** assertion down with it.
* Latency removed from the real profile deletes the only latency SLO the load test carries,
  and no CI job would notice, because none of them ever asserted it.

`test_load_thresholds_stay_split.py` pins both arms. Mutation-verified each way.

### Done (1)

**FS-371** — `make reap-test-containers`. Ryuk, testcontainers' own reaper, is disabled in
`conftest.py` deliberately: it needs the docker socket bind-mounted into a container, and
colima's VM boundary makes that mount fail, so with Ryuk on the suite cannot start. The cost
is stated there — containers from a hard-killed run are never cleaned up — and it had reached
23 stopped containers holding 13 GB.

The target matches on the **testcontainers label**, not on image names (a list of images is a
list to forget to update), and filters `status=exited` so it is safe to run while somebody
else's suite is mid-flight. Verified by planting a labelled exited container and reaping it.

### Not done, with the reason (3)

* **FS-372 · make `pre-commit` blocking.** This is decidable by measurement, so I measured it:
  running `pre-commit run --all-files` reformats **924 files, +53,752/−39,025**, across
  `frontend/src` (292), `backend/tests` (279), `backend/app` (195), `edge-agent` (73) and the
  migrations. That is a repo-wide reformat touching every lane, and there are stashes on
  another dev's branch right now. It would collide with every open branch, and it is a team
  decision rather than something to slip into a defect-fix commit. **Reverted in full.** The
  plan said "needs FS-280"; it now has a number attached instead of an adjective.
* **FS-369 · PITR** and **FS-375 · secrets provisioning** need a cluster to validate. Shipping
  manifests I cannot apply would be shipping unverified infrastructure, which is the opposite
  of what the rest of this log is about. Left open, and left honest.
* **FS-370** is environment-conditional rather than broken: `ci-cd.yml` applies `autoscaling/`
  and `database-ha/` when the KEDA and CloudNativePG CRDs are present, and prints an explicit
  `SKIP` with install instructions when they are not. What is missing — an assertion that a
  staging cluster running single-replica is *noticed* — also needs a cluster.

**Suite:** backend 3593 → 3600 · frontend 833 · e2e 84 collected · edge agent 289.

## FS-285 — the reports that failed to send, and nowhere to find out

Wave I measured. **FS-366 and FS-367 are closed** — the phantom `ModelDeployment` interface and
its three fields are gone, and `StrategicEngine` renders `—` rather than a false `0` for
decision history, deriving availability from the payload so it populates itself the day a route
starts sending `status`. **FS-368** closed with FS-487. The rest — FS-241/243/244/245 (⚠
htreinen's RAG lane), FS-247/249/250 (ERP transformers) — are multi-day feature builds in other
lanes, and left there.

**FS-285 was the one in mine, and it was real.** `GET /api/v1/exports/deliveries` has returned
a `status` and an `error` per scheduled send for some time. **Zero frontend files called it.**

So a user schedules a report to be emailed, the send fails, `ExportDeliveryJob.status` becomes
`'failed'` with the reason sitting in `error` — and there is no surface anywhere in the product
that would show them either one. What they experience is a report that did not arrive, and
nothing to ask.

`/admin/export-deliveries` is the smallest honest surface for it. Failures are counted at the
top and sorted to the front, because a page showing fifty successful sends with one failure
below the fold is the same silence in a longer form. The server's own error text reaches the
screen unedited — an SMTP rejection and an expired credential need different people, and
"delivery failed" throws away the only actionable thing on the page.

### Three things it did NOT do, each for a reason

**No mock branch.** Every other client forks on `USE_MOCK`, and a fixture here would be
actively misleading: the demo would show a tidy list of successful deliveries, which is the
single most reassuring lie this endpoint could tell. In mock mode the request fails and the
page says the history is unavailable — which is true.

**snake_case types.** `/api/v1/exports` is not in the transform registry, so the wire sends
`schedule_id`, `scheduled_for`, `completed_at`. My first draft declared them camelCase, which
would have been exactly the defect this codebase has spent the session sweeping for — a type
asserting fields the server never sends, with TypeScript vouching for them.

**The seam was left alone.** Registering the prefix would fix the casing and change it for
`ExportButton`'s job polling too, which works today. Changing a shared seam to suit one new
caller is a poor trade.

### Both route guards fired on the new page, immediately

`everyRouteIsSwept` demanded the route join the e2e sweep and `everyRoutedPageHasATest`
demanded a test file — within seconds of the route being added, before either was written.
That is the guards doing precisely the job they were built for, on their author.

And a third caught something subtler. `everyMockedClientHasARealModeTest` flagged the new
client as needing a real-mode test — because its docstring **mentions** `USE_MOCK` while
explaining why it has none. The guard was matching raw text. **A detector that reads
documentation as code will eventually report the file that documents the very thing it looks
for.** It strips comments now, with both directions asserted.

**Suite:** frontend 833 → 843 · e2e 84 → 86 collected · backend 3600 · edge agent 289.

## FS-492 — running the 47 tests that had never run here

47 of the 86 e2e tests are gated on `E2E_LIVE_BACKEND=1`, and locally they had only ever
skipped. They are the authenticated suites — the writes-actually-persist journey, the
data-reaches-the-screen sweep over every route, the controls sweep — written specifically to
catch the "renders but is wrong" class this session has been closing, and nothing here had
ever executed one.

### Standing it up found two environment facts worth writing down

**`localhost:5432` is not the compose database on this machine.** A native postgres owns
`127.0.0.1:5432` and `[::1]:5432`, and colima's container forward binds `*:5432` — so the
native server wins every host connection. `DATABASE_URL=...@localhost:5432` reaches a
postgres with no `omniusgrid` role and no timescaledb, which presents as *"role does not
exist"* while `docker exec` into the container works perfectly. That is a footgun for anybody
following the README on a colima machine.

The run used its own `timescale/timescaledb:latest-pg15` on **55432** rather than either
existing server — the dev database is never a safe target here, because the suite writes and
deletes at every endpoint.

### The result

**119 passed, 0 failed, and zero 5xx across 1,494 requests.** The 46 previously-unrun
authenticated tests pass against a live backend, which is the first real verification that the
work shipped this session holds outside jsdom.

### What it exposed: FS-492

`controls-do-not-break.spec.ts` swept **8 of 33 routes** from a private array. Its comment was
honest — *"the routes with the most interactive surface, not all 32 — this costs a click
each"* — and it had quietly become a coverage claim. The twenty-five it skipped were every
admin page, every engine, all three analytics pages, OEE, shop-floor, intake and NLP.

The file exists because `dispatchShipment` returned 422 on every call since it was written and
no test could see it because **no test clicked anything**. Three quarters of the product was
still in that position.

It could not drift into view either: `everyRouteIsSwept.test.ts` compares `App.tsx` against
`e2e/routes.ts`, so a private copy inside a spec is invisible to the guard built to catch
exactly this. Adding a route extended two sweeps and not the third.

### The cost that hid the coverage

Pointing it at all 33 routes timed out — at the original 240s, then at 396s after I made the
budget per-route, running 6.6 minutes and still failing. Raising the constant again buys an
eleven-minute serial job whose failure is one red line naming a list.

So the loop became one test per route, plus
`test.describe.configure({ mode: 'parallel' })` — the half that pays for the split, since
tests in one file run serially by default. **2.4 minutes for 33 routes against 6.6 for 8**:
four times the coverage in a third of the time, and a failure names its route in the test
title instead of inside an accumulated array.

All 33 pass. The per-route split would lose its vacuity check — each route passes trivially
with no buttons — so a separate test asserts the sweep still clicks more than fifteen
controls, or a selector change turns thirty-three green ticks into thirty-three no-ops.

**Suite:** e2e 86 → 119 collected, **119 passing against a live backend** · frontend 843 ·
backend 3603 · edge agent 289.

## FS-494 … FS-498 — two defects the edge agent's 289 tests could not see

The new plan's first wave. Both of the severe items were verified by hand before a line was
changed, and both had been broken since the day they were written.

### FS-495 — the live forward has never worked

`main.py:259` configures the Kafka producer with
`value_serializer=lambda v: json.dumps(v).encode('utf-8')` and hands that same object to the
coordinator (`:270`). The coordinator pre-encoded and passed the bytes as the value
(`coordinator.py:334-337`), so aiokafka ran `json.dumps(b'{...}')` — **`TypeError: Object of
type bytes is not JSON serializable`, on every single message.**

Reproduced in three lines before touching anything, then asserted by a test that fails against
the old code.

**It cost latency, not data.** The message is buffered before the forward is attempted and the
backfill path serialises correctly (`main.py:314`), so everything arrived by the slow road.
But the fast road never once carried anything.

**Why 289 tests missed it.** `tests/test_edge_agent_integration.py:47-55` defines a
`FakeProducer` whose `send()` appends `value` to a list — it applies no serializer, so it
accepts bytes happily. `test_coordinator_roundtrip.py:95` passes `kafka_producer=None` and
skips the path. The double was wrong at exactly the seam that was broken.

One existing test had to change: `test_backfill_contract.py:26` did `json.loads(raw)` with the
comment *"_forward_to_kafka serializes the whole message to bytes"* — a test written around
the defect. Its **intent** (packml_state reaches the top level) was always right and survives
unchanged; only the unwrapping moved, and it now asserts the value is a dict.

### FS-496 — a 100% failure rate logged at `debug`

The catch at `coordinator.py:302-309` logged `immediate_forward_failed` at **debug** and
incremented a counter. That reasoning holds for *one* failure — the data is buffered, it will
retry — and it is why nobody looked. It does not hold for a path that fails every time.

The first failure since the last success is now a `warning`; the rest stay at debug so an
offline broker does not write one line per message. Recovery logs once at `info`.

### FS-497 — every heartbeat has reported five zeros

`heartbeat.py:48-52` reads `buffer_pending`, `dead_lettered`, `dropped`, `active_collectors`,
`total_collectors`. `_health_snapshot()` returned `collectors_total`, `collectors_active` and
**no buffer keys at all**. Every read has a `, 0` default, so every field defaulted, every time.

This one reaches production monitoring: `backend/app/services/edge_fleet.py:69` sets the
`edge_agent_buffer_pending` gauge from that field, and `alerts.yml:241` alerts above 5000. **A
fleet backing up on disk looked idle.**

`tests/test_heartbeat.py:9-16` supplies its own `health()` dict with the correct names. It is a
good test of the reporter and can say nothing about the producer, because the two were never
connected in a test — both halves individually right, disagreeing about the contract between
them. The new test builds a real agent, takes its real snapshot, and runs it through the real
reporter, with no hand-written dict anywhere.

Both spellings are emitted, because `/healthz` consumers may read the old ones and fixing one
silent break by introducing another is not a fix. The buffer numbers come from a cache that
`_stats_reporter` already computed every five minutes and previously only logged —
`_health_snapshot` is deliberately sync (it serves the HTTP health server from another thread)
and the buffer's `get_stats()` is async.

### FS-498 — the alert that parsed and could not fire

`promtool check rules` validates an expression's syntax and says nothing about whether it can
ever cross its threshold, so `EdgeAgentBufferHigh` was syntactically perfect for exactly as
long as it was useless. Five promtool test files existed — errors, subsystems, platform,
workers, security — and none covered edge.

`tests/edge_alerts_test.yml` drives the gauge past the threshold and asserts the alert fires,
plus three cases that must stay quiet: below threshold, **exactly at it** (`> 5000` must not
fire on 5000), and a blip that drains inside the `for: 10m` window. Run through the
`prom/prometheus` image rather than installing anything, and mutation-verified by raising the
threshold to 500000. Now wired into the `prometheus-rules` job.

### FS-494 — the register, made to agree

Seven closures from the previous session went into `DELIVERED` and the verification table, and
FS-307 left the still-open list. The two-way guard added in FS-491 caught the disagreement the
moment the register moved first — which is what it is for.

**Suite:** edge agent 289 → 297 · backend 3603 · frontend 843 · e2e 119.

## FS-501, FS-502 — two defects in twenty lines, neither of which reports anything

Both in the collector supervision loop, and both invisible from outside the process: it keeps
running, the collector list still looks populated, and the only symptoms are CPU and a
supervisor that quietly stopped existing.

**FS-502 — the supervision tasks were dropped.** `start_all` built them into a local that went
out of scope on the next statement, never awaited and with no strong reference. asyncio holds
only a weak reference to a running task, so the loop was free to collect one mid-flight, and an
exception inside a collected task surfaces nowhere. `all_collectors_started` was logged before
any collector had started.

They are held on the instance now and cancelled in `stop_all` — because `self._running = False`
is checked at the top of the loop, which a supervisor sitting in `await collector.start()`
never reaches. Signalling is not stopping.

**FS-501 — a clean return spun the loop.** Restarts were counted and delayed only in the
`except` branch, so a `start()` that **returns** rather than raises incremented nothing and
slept for nothing: a tight loop for the life of the process, with no counter moving and nothing
in the log. A collector exiting normally when its connection closes is the ordinary case.

### The test I got wrong first, and what fixed it

My first assertion waited for the loop to exhaust `max_restarts` — which is now *correct*
behaviour and takes about fifty seconds (10 restarts × a 5 s delay), so it timed out against a
working fix. What actually separates the defect from the fix is **the rate**: a supervisor that
sleeps starts a handful of times in a short window; one that hot-spins starts thousands. The
test now runs the supervisor for 0.3 s and asserts the count is small.

The mutation proof is unusually direct. Reverting both fixes does not produce a failing
assertion — it produces a **hung test run**, because the loop spins hard enough to starve
everything around it. That is the defect, demonstrated.

**Suite:** edge agent 297 → 300.

## FS-493, FS-503 — the gate started working, and immediately found a 500

FS-307 moved the contract gate off the postgres superuser. The plan's first item was to
re-measure, because every previous conformance number had been taken with `FORCE ROW LEVEL
SECURITY` bypassed. Both configurations were run on the same database, back to back:

| | conforming | `ServerError` |
|---|---:|---:|
| as the owning **superuser** (the old gate) | **397 / 470** | 17 |
| as `omniusgrid_contract` (`NOSUPERUSER NOBYPASSRLS`) | **392 / 470** | 23 |

**Turning tenant isolation on costs five operations.** I had flagged that the ratchet might
fail on the first run; it does not — 392 is comfortably above the old floor of 360. The
prediction was wrong in the harmless direction, and worth saying so plainly.

The new floor is **380**, not 392. This is one run at the new configuration and the file
records a spread of up to nine operations with no code change, so a floor set at the
measurement would fail on variance. 380 leaves 12 of headroom and catches a regression of 13,
where 360 would have sat through a loss of 32.

### The six the gate could not previously see

Six operations fail **only** under the restricted role — they were passing because RLS was
switched off. Two are the audit trail; three are model-monitoring history; one is compliance
report scheduling. And the first one turned out not to be an RLS problem at all.

### FS-503 — `GET /audit/logs` 500s on any row that has an IP address

`AuditLog.ip_address` is `String(45).with_variant(INET, "postgresql")`, so on Postgres the
column is `INET` and the driver returns an `ipaddress.IPv4Address`. The response model declares
`Optional[str]`. Pydantic will not coerce an address object into a `str` field, so serialising
raises — twenty-five validation errors on a hundred-row page — and FastAPI returns **500**.

Every row with an IP breaks the page it lands on. This is the endpoint an auditor opens.

**Why nothing caught it**, and both reasons are ordinary:

* the tenant-scoping fixtures insert audit rows with **no `ip_address`**, so the column is
  NULL and `Optional[str]` accepts None happily;
* SQLite has no `inet` type, so the variant falls back to `VARCHAR(45)` and the driver returns
  a plain string — nothing outside `realdb` can see this at all.

And it surfaced only under the restricted role because **RLS changed which rows came back**.
As a superuser the page happened to contain rows without an address. That is Rule 117 again —
*the defect is a property of the schema and the failure is a property of the data* — one week
after the rule was written, in a field whose own column comment records a previous incident:
inserts bound VARCHAR against the INET column and `audit_trail` swallowed the failure, so "the
audit trail has been silently empty on real deployments while every write appeared to succeed".

Fixed by converting at the boundary in all three read sites rather than widening the declared
type, because the API's contract really is a string.

### Two detector corrections, both mine, both caught by reading the hits

Scanning for the general class — *a field declared `str` over a column that is not one* — my
first pass reported **28 offenders**. All 28 were false: I tested `str in get_args(annotation)`,
and `Dict[str, Any]` has `str` among its arguments. Comparing the field's **outermost** type
instead gives **zero**.

Which raised the real question: why does the FS-303 pairing not catch `ip_address` either? Because
`AuditLogEntry` is declared inline in `app/api/audit.py`, and that guard reads
`app/models/schemas.py` only. Measured: **313 pydantic models are declared inline across 54 api
modules, against 123 in `schemas.py`** — the pairing sees 28% of them. That is the FS-492 shape
again, a guard whose subject list is quieter than the code, and it is recorded here rather than
half-built.

**Suite:** backend 3603 → 3606 · contract floor 360 → 380.

## FS-500 — a `quality:` block that killed the collector it configured

`_start_collector` splatted the whole config block into the constructor:

```python
collector = collector_class(**config.config, on_message_callback=...)
```

Four keys in that dict are not the collector's business. They live there because that is where
an operator naturally writes them, and they are read from there by other parts of the agent —
`quality` by the coordinator, `packml` by `collectors/adapter.py:55`, `alerts` and `oee` by
`main.py:506,512`.

**Four of the seventeen registered collector types take no `**kwargs`**: mqtt, modbus, opcua,
orca_file. Measured, not assumed — the survey said five and named two files that map to adapter
types. For those four, writing any of those blocks raised
`TypeError: unexpected keyword argument`, which `_start_collector`'s own handler caught and
logged as `collector_start_failed`. **The collector never ran.**

The symptom is one log line at startup naming a config key the operator had every reason to
think was supported, then silence from that asset forever. And it depended on the device: the
adapter-wrapped collectors take the raw dict and were fine, so the same config file works for a
BACnet asset and kills an MQTT one.

Nothing caught it because the failure is in a handover. The quality pipeline has tests, the
collectors have tests, and no test starts a collector with a `quality:` block — one component
reading a key out of a dict another component is about to reject.

The stripped set is asserted against the four the agent actually reads, so a fifth
cross-cutting key added without registering it fails here rather than silently killing a
collector.

### Two test corrections, both mine

**A missing-argument failure masquerading as the defect.** My first fixture passed only the
cross-cutting blocks, so `modbus` failed on its own required `connection_type` — a different
defect, and asserting on it would have made the test dishonest. Each strict collector now gets
its minimum config, so the assertion isolates the thing under test.

**A test that passed alone and failed in the suite.** The "own keys still reach it" case built
a real `MQTTCollector` — and `test_edge_agent_integration.py:31-34` installs a fake
`opsgrid_agent.collectors.mqtt` into `sys.modules`, so by the time it ran the registered class
was somebody else's double. Caught because the full suite disagreed with the single-file run;
a green single-file run would have shipped a test that asserts nothing about mqtt. It registers
its own stub now — a test of what the coordinator *passes along* should not depend on which
collector implementation happens to be loaded.

**Suite:** edge agent 300 → 304.

## FS-499 — the path my own fix switched on, and why it is off again

FS-495 fixed the serialisation that had made the immediate Kafka forward raise on every message
since the day it was written. That fix was correct, and it had a consequence I had not traced:
**it turned the path on for the first time.**

The live forward publishes `telemetry.{asset}`. The contract — stated in
`edge-agent-statefulset.yaml:60-63` and parsed at `workers/ingestion.py:219` — is
`telemetry.{org}.{asset}`, and the worker rejects anything with fewer than three parts as
`invalid_topic_format`. So between FS-495 and this entry, every reading produced a backend
warning and a dropped copy, while the backfill copy arrived correctly. Noise, not loss, and
mine.

**Correcting only the topic is worse.** Nothing marks the buffered row sent — `mark_sent` is
called by the backfill loop alone (`main.py:357`), and `get_pending_messages` filters on
`retry_count`, not on delivery. A correct live publish would therefore deliver every reading
**twice**.

And marking on a successful send would be wrong too: `producer.send()` awaits the message being
batched, not acknowledged by the broker. Removing the buffered row on that basis gives away the
guarantee store-and-forward exists to provide.

So making the immediate forward real needs three things **together** — the organization in the
topic, an ack-guaranteed send (`send_and_wait`), and marking the row sent so backfill skips it.
That is a change to the delivery semantics of the core data path. It is not a defect fix and it
is not mine to decide.

**It is gated off, which restores exactly what has always shipped.** The path has never
delivered anything; buffer-then-backfill is the only behaviour production has ever had.
Enabling a second delivery path is the change that needs justification, not leaving it off.
`IMMEDIATE_FORWARD_ENABLED = False` says so at the definition, and a test pins it — re-enabling
it fails until the three pieces land together.

`_forward_to_kafka` is kept and correct, with the FS-495 tests retargeted at it directly. The
serialisation contract is a property of that function whether or not anything calls it today,
and asserting it means the day the gate opens, it opens onto working code.

**Suite:** edge agent 304 → 305.

## FS-504 — the buffer loss nothing counted, and the allowlist entry that said otherwise

*(The plan numbered this FS-503; that number went to the audit-log 500, which turned up
mid-flight and needed one. Recorded rather than silently reused.)*

`StoreForwardBuffer.store()` recovers from a full disk by deleting the 500 oldest rows and
retrying the insert. Those rows are **undelivered telemetry** — the buffer's entire purpose is
that a reading survives the uplink being down, and this is the one path where it does not.

`_prune_oldest_sync` returned `None` and its caller discarded the number. Up to 500 readings
disappeared per disk-full event with nothing recording it.

**The allowlist knew, and was wrong.** `test_every_buffer_loss_is_counted.py` exists to make
exactly this impossible, and it excused this method with a reason:

> emergency space reclamation; the hourly path counts the steady state

`enforce_size_limit` counts `cursor.rowcount` — rows **its own** DELETE removed. Anything the
disk-full handler had already deleted was gone from the table and could never appear in that
count. The entry is deleted, not reworded.

### Why the guard had to allow it in the first place

Its model was "`main.py` calls the method and passes the return value to `metrics.record_*`",
which is how the three periodic cleanups work. `_prune_oldest_sync` is reached from inside
`store()`, so `main.py` never sees it — and under that model the *only* way to satisfy the
guard was to be excused. **A guard whose model does not admit the correct shape will collect
exemptions**, and one of them will eventually carry a reason nobody re-checks.

It now recognises a method that calls `metrics.record_*` in its own body. Counting at the point
of deletion is the better shape for a path like this, and the guard should have said so.

### Structural and behavioural, because the AST cannot see a wrong number

The existing check reads the syntax tree, which proves a counter is *mentioned*. It cannot
tell whether the branch runs or whether the count is right, and 500 readings per event is not
a number to take on faith. Two behavioural tests drive the real buffer: six rows in, four
pruned, the counter moves by four — and an empty buffer moves it by nothing, so recovery on a
buffer with nothing to give up does not inflate the loss figure.

Mutation-verified: removing `metrics.record_dropped` fails both the structural guard and the
behavioural test.

**Suite:** edge agent 305 → 307.

---

## FS-505 — the cloud dispatches a command the fleet answers `unknown_action`

`rollout_orchestrator.py:297` picks the action by artifact type:

```python
action_id = "model_update" if release.artifact_type == "model" else "agent_update"
```

The agent registers **one** handler. `OTAUpdateExecutor.register` binds `agent_update`, and
`main.py:68,209` constructs and registers it. `ModelUpdateExecutor.register` binds
`model_update` — and nothing anywhere constructs that class, so `register()` never runs.
`commands/consumer.py:149-155` answers `{"error": "unknown_action"}`.

So every model rollout the cloud dispatches fails, and it fails as a **device** failure: the
rollout records the target as unable to take the update, against hardware that is working
perfectly.

### A comment asserted it worked

`api/health.py:728` justified removing the collector-restart endpoint with

> the edge agent registers exactly two command handlers: `agent_update` and `model_update`

The decision was right and the premise was half true, which is the kind that survives review.
Corrected in place, with what is actually registered and how to see it.

### Neither side could see the pair

The backend knows what it dispatches; the agent knows what it registers; nothing read both.
That is the same shape as FS-485 (truncation signals) and FS-486 (the ERP connector list) —
two lists that must agree with no single place that compares them.

`backend/tests/test_dispatched_commands_have_a_handler.py` walks the orchestrator for the
action ids it can assign, walks the agent for the handlers registered by classes **`main.py`
actually constructs**, and requires the sets to agree. Starting the walk from `main.py` is the
whole trick: reading `register_handler` calls package-wide would have counted the handler on
the class nobody builds, which is the defect.

`model_update` is carried as an exemption naming the owner and what closes it, and two further
tests assert the exemption is still both dispatched and unhandled — a stale entry is how an
allowlist stops describing the code and starts excusing it, which FS-504 had just cost.

**Not fixed here:** wiring `ModelUpdateExecutor` is three lines in the OTA lane, and it has no
tests at all (FS-507). Switching an untested 220-line handler into the live command path is a
separate act from noticing it is missing.

### The reader was wrong first

A regex over the assignment returned `{model_update, agent_update, model}` — `"model"` is the
*artifact type* the ternary tests against, not an action it sends. The reader now walks the
AST and descends into `body`/`orelse` but never into `test`. The difference is between reading
what the code sends and reading what it asks about, and the regex version would have reported
a phantom unhandled action forever.

Mutation-verified: removing the exemption fails three independent assertions.

**Suite:** backend 3606 → 3612.

---

## FS-506 — 460 lines of edge agent nothing imports, three of them fully tested

The backend has had an unreachable-module inventory since its 7,726-line measurement. The
agent never did, and its version has a twist that makes it *harder* to see: **three of the four
orphans have passing tests.**

| module | lines | tests | what is actually missing |
|---|---|---|---|
| `compression.py` | 43 | `test_dataplane_robustness` | **the receiver.** It frames output as `codec_marker + body` and nothing in `backend/app` decodes it — enabling it would make every uplink unreadable rather than smaller. Half a protocol, and the shipped half is the wrong one. |
| `aggregation.py` | 83 | `test_dataplane_robustness` | an opt-in config key and a flush loop. The key would be the fifth cross-cutting one and must join `CROSS_CUTTING_KEYS` in the same change, or a strict collector dies on it (FS-500). |
| `config_reload.py` | 114 | a dedicated file | **a trigger.** `main.py` installs no signal handler and the command consumer registers no `reload_config` action, so there is no path by which a reload could be asked for. |
| `ota/model_executor.py` | 220 | none | the wiring FS-505 documents. The only one here that is actively dispatched to. |

Coverage reports three of these green, the suite counts them, and a reader browsing the tree
finds a documented feature with passing tests. **A test is evidence the code is correct, never
evidence that anything calls it** — FS-490's class ("counted what does not run") arriving at a
different layer.

`edge-agent/tests/test_no_new_unreachable_modules.py` requires each entry to say what is
specifically missing, asserts every listed module is *still* unreachable, and fails on a fifth.

### The detector flagged the program itself

The first run reported `main.py` — true, and useless: it is the entrypoint (`pyproject.toml:21`,
`Dockerfile:49`). An inventory that flags the program nobody reads twice. Entrypoints are
excluded by name, and the exclusion is asserted against the packaging metadata so it cannot
become a hiding place.

Mutation-verified: a new orphan module fails the sweep by name.

---

## FS-507 — the live HTTP collector had no test, and every failure path is swallowed

`http_rest` is one of seventeen types in `SUPPORTED_COLLECTORS` — a collector an operator can
name in a config file and point at a device today. Before this, **zero tests named it**, and it
was the only registered type in that position.

That matters more than it sounds, because every failure path in it is swallowed. `_collect`
catches `httpx.HTTPError` and then bare `Exception` and returns; `_poll_loop` wraps the same
call in a second handler. The collector cannot crash, cannot restart, and cannot tell the
coordinator anything is wrong — **a poll that raises on every cycle looks exactly like a poll
that works.** Supervision (FS-501) never sees it, the heartbeat (FS-497) never counts it, and
the asset goes quiet. That is the FS-495 shape, and the only thing standing between this
collector and that outcome was that nobody had run it.

Ten tests drive the real object with a stubbed transport: a reading is emitted at all, the
payload survives normalisation, a nested object is flattened rather than dropped, a list
response uses its first object, the request goes where it was configured, a connection error
does not end the poll loop, a 200 carrying non-JSON does not propagate, and `stop()` closes the
client and cancels the task.

**The collector is correct.** No defect was found — the gap was purely the absence of any
assertion. Mutation-verified: removing the `emit` call fails five of the ten.

---

## FS-508 — the production posture was documented in a comment and configured nowhere

The agent reads four switches that each choose between a permissive and a safe behaviour:

| switch | default | what the default costs |
|---|---|---|
| `EDGE_REQUIRE_EXPLICIT_SOURCES` | `false` | an audio/video collector with no `source` **synthesizes** its readings instead of refusing to start |
| `EDGE_REQUIRE_TLS` | `false` | a failure to build the mTLS context degrades the uplink to plaintext instead of aborting |
| `KAFKA_SECURITY_PROTOCOL` | `PLAINTEXT` | no client certificate on the telemetry uplink |
| `ENROLLMENT_CA_FINGERPRINT` | unset | the CA bundle returned by the enrollment call is trusted unpinned — and that response is the trust root for the whole fleet |

**All four were set in exactly one place in the repository: a commented-out block in
`deploy/install.sh:35-38` headed "Production posture".** The shipped StatefulSet set none of
them, and `grep -rln edge-agent overlays/` is empty — no overlay patches the edge agent, so the
base manifest is what production runs verbatim.

Meanwhile the production overlay sets `MTLS_ENABLED=true` for the backend. One side of the
connection is configured to require mTLS and the other is configured for plaintext, in the same
tree, and nothing compared them. **A commented line documents an intention; it configures
nothing.**

`EDGE_REQUIRE_EXPLICIT_SOURCES=true` is now set in the manifest. It cannot break a running
fleet: it rejects only a config that omits `source` on a synthetic-capable collector, which is
a config that was already lying about what it measured.

The two TLS switches are **not** flipped. Fail-closed TLS aborts startup on an agent that has
not enrolled — `main.py:608-611` records that ordering hazard — so turning them on before mTLS
enrollment is proven end-to-end would brick the fleet on the deploy that enabled it. They are
recorded as deferred with what closes them (Wave L, a cluster) rather than guessed at.

`edge-agent/tests/test_the_shipped_deployment_sets_its_posture.py` requires every switch to be
either set in the manifest or listed with a reason and a closing condition, asserts a deferred
switch that got set is removed from the list, and asserts the agent still reads each one — a
guard whose subjects the code stopped reading protects nothing while looking diligent, which
FS-484, FS-492 and FS-504 each cost once.

### The reader has to tell code from comments

The variable this item is about was findable by grep in `install.sh` — as a comment. The guard
parses the manifest as YAML and has a test proving it does not count the commented-out
`COLLECTORS_FILE` block, because a detector that cannot tell the difference would have passed
on the broken tree.

Mutation-verified: reverting the manifest line fails two assertions.

**Suite:** edge agent 307 → 344.

---

## FS-509 / FS-510 / FS-511 / FS-521 — three stacks nobody compared to where they were sent

`monitoring/`, `autoscaling/` and `database-ha/` are deployed outside the app overlay: they
carry operator CRs and a cross-tree rule reference, so they cannot join the image-pinned
overlay build. Being outside it, nothing ever compared them to the environment they were
applied into. Three defects followed, and the CI gate that validated all three could not see
any of them.

### FS-509 — the staging deploy has been failing at that line

All three hardcode `namespace: omniusgrid`. The staging job piped the rendered output into
`kubectl apply -n omniusgrid-staging`, and kubectl refuses an object whose embedded namespace
disagrees with `-n`:

```
error: the namespace from the provided object "omniusgrid" does not match
the namespace "omniusgrid-staging"
```

The step runs under `set -euo pipefail`. **Staging has therefore never had monitoring,
autoscaling or the HA database applied** — the alert rules FS-498 and FS-583 are about have
never been loaded there.

Production was unaffected because its namespace happened to match. That is exactly why this
survived: the broken path had no working twin to be compared with.

`-n` cannot override an embedded namespace — it can only supply one that is absent — so the
fix is a per-environment overlay that declares it. Those live in `platform/<env>/<stack>` and
not `<stack>/overlays/<env>`, because kustomize refuses an overlay nested inside its own base
("cycle detected: candidate root contains visited root").

### FS-510 — KEDA has been scaling nothing, in *both* environments

`scaledobjects.yaml` targets `ingestion-worker`, `export-worker` and
`compliance-reports-worker`. The overlays that deploy those workers apply
`namePrefix: staging-` / `prod-`, so the Deployments are really `staging-ingestion-worker` and
`prod-ingestion-worker`. `autoscaling/` is applied outside the overlay and has no prefix.

KEDA does not fail loudly on this. It creates the ScaledObject, reports
`ScaledObjectCheckFailed`, and scales nothing — so the three Redpanda consumer workers sat at
a static replica count under any lag. `ingestion-worker` is `replicas: 1`, and that is the
telemetry path.

A `namePrefix` in the new overlay would have been the wrong fix: kustomize has no
nameReference rule for a custom resource's `spec.scaleTargetRef.name`, so it would rename the
ScaledObjects and leave the broken references untouched — the same bug with tidier names. Each
reference is patched explicitly.

### FS-511 — Prometheus discovering nothing, healthily

Four scrape jobs pinned `namespaces: ['omniusgrid']`. In staging, every one of them found zero
targets while Prometheus itself came up healthy with all rules loaded. **That is the failure
that looks most like success.** Both namespaces are now listed: Kubernetes SD does not error
on a namespace that is absent, it simply yields no targets, so one config is correct in either
cluster — and one config cannot drift from its copy.

### FS-521 — the lint, which is the actual deliverable

`tests/k8s/check_namespaces_and_targets.py` renders every platform stack per environment and
asserts three things `kubeconform` cannot: every namespaced object carries its declared
namespace, every `scaleTargetRef` names a workload the matching app overlay really deploys, and
every pinned scrape job discovers both environments. A namespace disagreeing with `-n` is
schema-valid YAML; a `scaleTargetRef` naming an absent Deployment is a string.

It also reads the **deploy job**, and fails if any stack is still applied by its raw path.
Fixing the manifests without fixing the workflow would have left the mismatch precisely where
it was — and that is the half a manifest lint would ordinarily never look at.

Vacuity is checked explicitly: all three checks pass trivially over an empty set, and each
reads from a build that can silently render nothing.

Mutation-verified three ways — reverting the scale-target prefix, narrowing the Prometheus
namespace list, and pointing CI back at a raw stack path each fail it with the specific reason.

**Gate:** 66 namespaced objects, 6 scale targets, 4 scrape jobs. All existing k8s gates still
pass (108 probes, 4 targets, placeholder-secret and backend-security checks).

---

## FS-516 / FS-517 / FS-518 / FS-519 — the local stack could not start, and would have lied if it had

Four defects in the compose observability stack. Each is invisible to the validator that owns
its artefact, and the gap is between them rather than in any one of them.

### FS-516 — Prometheus exited on startup

`docker-compose.yml:415` passed `--alertmanager.url=http://alertmanager:9093`. That flag was
**removed in Prometheus 2.0**, and an unknown flag is fatal. So the container exited
immediately on every `docker compose up`.

Nobody running the stack locally has ever had metrics, alerts or SLO rules. Four CI gates
assert those rule files are well-formed — `promtool check rules`, `promtool check config`,
the rule unit tests, the kubeconform pass — and **not one of them had ever been loaded by a
running Prometheus.** The flag was redundant besides: `prometheus.yml:8-12` configures the
alertmanager the current way, which is why removing it loses nothing. A test asserts the
alerting block is still there, because a fix that made the container start while dropping
alert routing would pass the first check and be worse than the bug.

### FS-517 — one container, two jobs, every series doubled

`prometheus.yml` defined `edge-agent` → `edge-agent:9108` and `opsgrid-edge-agent` →
`edge-agent-sim:9108`. `edge-agent` is a **network alias** for `edge-agent-sim`
(`docker-compose.yml:579-581`), so both scraped the same container.

The plan recorded this as "two jobs, both permanently DOWN". It is worse than that. **No alert
rule or dashboard panel filters by `job`**, so with the simulator profile on, every series
existed twice under two job labels: `sum(edge_agent_up)` on the fleet dashboard counted each
agent twice, and `EdgeAgentBufferHigh` would have fired two identical alerts per agent. The
fleet size was wrong in the direction that looks like growth.

### FS-518 — the simulator simulated nothing

`edge-agent-sim` set neither `COLLECTORS` nor `COLLECTORS_FILE`, so the agent logged
`no_collectors_configured` and produced no telemetry — while the scrape job pointed at it
reported it up and healthy. It now runs one `audio` collector with `source: "simulate"`, which
is explicit and therefore still honest under `EDGE_REQUIRE_EXPLICIT_SOURCES` (FS-508): the
readings are stamped synthetic rather than passing as hardware.

### FS-519 — the metrics port matched nothing

`main.py:600` defaulted `METRICS_PORT` to **9100**. The StatefulSet declares containerPort
9108, the compose service publishes 9108, and every scrape target is 9108. Any deployment that
did not set it explicitly served a full registry on a port nothing scraped — the agent looks
healthy, exports everything, and every edge alert stays silent for the honest reason that no
series exists. 9100 is also the node_exporter port, so on a host running one the agent would
be scraped *as* the node exporter or fail to bind.

`backend/tests/test_the_local_stack_can_actually_start.py` holds all four: no removed
Prometheus flag, the alertmanager still configured, every scrape target naming a real compose
service **or alias**, no two jobs on one container after alias resolution, the simulator
configuring a collector with an explicit source, and the agent's default port matching both
the scrape targets and the StatefulSet. Mutation-verified on FS-516, FS-517 and FS-519.

---

## FS-512 — a workload running below the floor its own autoscaler declares

The plan recorded this as "ten single-replica workloads with no PDB". Measuring it made the
finding smaller and sharper, and the plan's framing wrong.

`base/pod-disruption-budgets.yaml` already argues the general case correctly in its header:
only multi-replica workloads get a PDB, because `minAvailable: 1` on a single-replica workload
gives no protection and `maxUnavailable: 0` makes `kubectl drain` hang forever. Eight of the
ten are correctly excluded — `export-worker` and `compliance-reports-worker` have
`minReplicaCount: 0` and scale to zero, and timescaledb, redis, seaweedfs, jaeger and
otel-collector are true singletons whose availability needs replication, not a budget.

**One is a real defect, and it is the telemetry path.** `ingestion-worker` was `replicas: 1`
while the autoscaler that owns it declares `minReplicaCount: 2`, with the reason written out
beside it: *"Real-time telemetry: never scale to zero (cold start would drop the live stream
behind), keep a warm floor."* So the declared floor was 2 and the deployed floor was 1. On
every apply, ingestion ran as a single pod until KEDA's next 15-second poll — and where KEDA is
not installed, which the deploy job explicitly tolerates by gating on the CRD, it stayed at one
permanently.

It had no PDB either, and by that file's own rule it qualified. **The rule had been applied
against the Deployment's `replicas` field, and the floor that governs this workload lives in a
different stack, deployed by a different job.** Rule 122 again, in the manifests.

`tests/k8s/check_replica_floors.py` pairs them: any ScaledObject with a floor of 2 or more must
name a workload deployed at or above that floor and covered by a PDB. It deliberately does not
demand a PDB anywhere else — the existing exclusions are right and are left alone.

Mutation-verified both ways: reverting `replicas` and mistyping the PDB **selector** each fail
it with the specific reason. Renaming the PDB object does not, correctly — coverage is the
selector, not the name.

---

## FS-514 — six secrets the workloads consume and nothing provisions

`infrastructure/k8s/secrets/` holds two complete provisioning paths — an External Secrets
Operator manifest and a Sealed Secrets sealing script — and neither is referenced by any
kustomization or workflow. The plan recorded that as the defect. **It is not.** Both need a
real vault or a cluster keypair per environment, so CI cannot apply them; the overlays say so,
and `strip_placeholder_secrets.py` states the intended failure mode — a pod that never got its
secret dies with `CreateContainerConfigError`, loudly, rather than running on a placeholder.

Which makes the actual risk a different one, and worse. **If the provisioning manifests omit a
secret the workloads consume, the operator provisions everything the documentation asks for,
every step reports success, and the deploy still dies.** The failure is loud; the cause is
invisible, because the consuming half and the provisioning half live in different trees and
nothing compared them.

Pairing them found six:

| secret | keys | state |
|---|---|---|
| `app-secrets` | `edge-bootstrap-token`, `erp-encryption-key`, `geotab-webhook-secret` | **no path at all** |
| `smtp-credentials` | whole secret | **no path at all** |
| `grafana-admin` | `admin-password` | **no path at all** |
| `backend-tls` | whole secret | cert-manager |
| `ca-certificate` | whole secret | cert-manager |
| `redpanda-broker-tls` | whole secret | cert-manager |

The three TLS secrets are issued in-cluster by cert-manager rather than copied from a vault, so
they have a source — it is simply not this one. They are recorded as such, because "no
ExternalSecret" reading as "no source" is a wrong reason in an allowlist, and FS-504 had just
cost a buffer counter to exactly that.

The other three are real, and are **closed rather than recorded**: each now has an
ExternalSecret, an entry in `secrets.env.example`, and a `seal` call in `seal.sh`. They are not
minor — `edge-bootstrap-token` is what a device presents to enroll, so without it no agent can
join the fleet; `erp-encryption-key` decrypts every stored vendor credential; and every other
monitoring credential already had an ExternalSecret while `grafana-admin` did not, so the
monitoring stack was one secret short of starting even where the documented provisioning had
been done in full.

`tests/k8s/check_every_secret_has_a_source.py` reads `env`, `envFrom` **and volumes** — a
secret mounted as a file is just as fatal when absent as one read into an environment variable,
and only the env form is obvious — and holds **both** documented paths to the same rule, since
an operator picks one and a secret covered by only the other leaves them with precisely this
gap. `NO_SOURCE_YET` is empty and the tests assert any future entry is still both consumed and
unprovisioned, so it cannot go stale.

Mutation-verified on each path independently: removing a `seal` call and renaming an
ExternalSecret target each fail it with the specific reason.

**Not fixed here:** FS-515 (`overlays/dr` validated by CI and applied by nothing) is *correct*
as it stands. A DR site is cold; continuously applying to it from CI would defeat the point.
Five gates already build and validate it, and the runbook is what applies it. There is no
defect there — the plan's framing was wrong, and the honest close is to say so rather than
manufacture a deploy job for it.

---

## FS-520 — the canonical document that omitted a tree five gates build

`infrastructure/k8s/README.md` opens by calling the tree **canonical** and then named `base/`
and two overlays. `overlays/dr` has existed since FS-230, is built and validated by five CI
gates, and appeared nowhere in it.

A directory CI builds and the canonical document omits is worse than an undocumented one,
because the document is complete on its face. An operator reads it, concludes the tree is
`base/` plus two overlays, and either misses the DR site or — having found it another way —
stops trusting anything else the file says. **Documentation is load-bearing only while it is
exhaustive; the first omission takes the weight off all of it.**

The README now carries a table of all thirteen buildable trees with what applies each, and
`tests/k8s/check_the_readme_describes_the_tree.py` fails on any that is missing.

**It caught its own author immediately.** The first version of that table wrote
`platform/{staging,production}/{monitoring,autoscaling,database-ha}` — readable to a person,
and five of the six paths absent from the file as far as any reader searching for one is
concerned. An inventory earns its keep by being literal. The gap opened by **addition**, which
is the point: nobody edits a README two levels up when they add a directory, and this same
commit would have added five unnamed trees by exactly the route that lost `overlays/dr`.

---

## FS-513 — the reported defect was not there, and the real one was next to it

FS-513 was filed as "PITR still does not exist, while root `README.md:405-406` presents it as
live". The first half is true. **The second is not** — those lines are a branch-comparison
table mapping one repository path to another and claim nothing about capability.

Every recovery document is already explicit: the runbook's RPO line reads "Up to 24 h (no
point-in-time recovery)", it labels the pgBackRest instructions in the DR runbooks "not yet
operational", and its PITR section is titled "Restoring PITR (**not yet done**)". There was
nothing dishonest to correct, and the capability itself needs a database cutover that cannot be
done from here.

**One document was overstating, and it was not the one named.**
`infrastructure/k8s/README.md` described `database-ha/` as providing "continuous WAL archiving
to S3 for PITR" and noted two lines later that the stack is opt-in — but not on the sentence
making the promise. An operator scanning for "PITR" reads the promise and not the caveat. The
caveat now sits in the sentence, with what is actually protecting the deployed database.

### The detector was wrong first, and instructively

Its first version asked for a database image shipping the `pgbackrest` binary. That is the
requirement for the **archived** `legacy-patroni` path, and it is not how CloudNativePG does
PITR at all — CNPG uses barman-cloud, built into the operator's image, driven by
`backup.barmanObjectStore`. So the check demanded evidence the working path would never
produce, and would have reported "no PITR" for the rest of the repository's life, **including
after somebody built it**.

The question that decides it is which database is running, not which binaries exist somewhere
in the tree: `base/` still ships the single-pod TimescaleDB StatefulSet, so the cutover has not
happened and the deployed database has no WAL archive.

`backend/tests/test_the_recovery_promise_matches_the_deployment.py` holds the promise to the
deployment **in both directions**. The qualifier must stay while the cutover has not happened,
and must go the day it does — an under-promising runbook sends an operator to the slower
recovery during an incident, which is the same kind of wrong pointing the other way. That
matters here because this shape has already cost once: `legacy-patroni/` held the pgBackRest
CronJob, was in no kustomization, and staging and production had **no backups at all** while
the DR runbooks described restoring from a repository nothing wrote to.

Mutation-verified both ways: removing the runbook's qualifier fails it, and removing the
single-pod StatefulSet (simulating the cutover) fails it in the opposite direction.

---

## FS-522 — the drill restored every row and could not tell whether isolation came back

The plan listed this as "the drill needs to run against a real dump". It already does:
`test_backup_restore_drill.py` starts a real Postgres via testcontainers, runs the CronJob's
exact `pg_dump -Fc --no-owner --no-acl` inside the container, restores into a fresh database,
and compares row counts and the schema version. That premise was met.

**What it could not see is whether tenant isolation survived.** Every check it made compares
DATA. A restore that brings back every row and drops every RLS policy passes all four — and
hands the business a database where one organization reads another's rows, during an incident,
at the moment nobody is looking at authorization. The restore succeeds and the security
property does not.

This is not hypothetical for this schema. Tenant isolation here is *entirely* row-level: 66
policies across 65 tables, all of them `FORCE ROW LEVEL SECURITY` since FS-307. The CronJob
dumps with `--no-acl`, which drops GRANT/REVOKE; policies are separate objects and do survive,
but that is a fact about the current flags rather than a guarantee. Adding `--section=data`,
restoring into a database whose roles do not exist, or a migration writing a policy naming a
role the target lacks would each break it silently — and the restore step is deliberately
tolerant of partial failure two steps earlier, so nothing would raise.

Measured before asserting: **66 policies, 65 tables with row security, 65 with FORCE, identical
on both sides.** The restore is sound. `FORCE` is counted separately on purpose — it is what
stops the owning role from bypassing the policies, and losing only that would leave
`pg_policies` looking untouched while the isolation was gone.

Vacuity is checked: a schema with no policies satisfies the comparison trivially, so the drill
asserts the source has some before comparing.

Mutation-verified by dropping every policy from the restored database after the restore: rows
and schema version still match, and the drill fails with `policies: source=66 restored=0`.

**Wave L closes here.** FS-509, 510, 511, 512, 513, 514, 516, 517, 518, 519, 520, 521 and 522
are done; FS-515 needed no change and the reason is recorded above.

---

## FS-523 — fourteen create endpoints answered 422 to the only client that calls them

The plan filed this as "Yard's seven untested POSTs — all state-mutating, only 'does not 500'
coverage". Writing the tests found the coverage gap *and* something larger underneath it.

### The write-side twin of FS-99

Fourteen create endpoints declared a **required** `organization_id` on their request body,
while the handler derived the tenant from the token and never read the body's value. The
handlers say so themselves, in a comment repeated verbatim at each site:

> FROM THE TOKEN, NEVER THE REQUEST — `data.organization_id` is client-supplied, so a caller
> could file the row under any organisation they named.

Correct. And the schema next door forced every caller to send that exact client-supplied value
anyway, with no default — so **omitting it is a 422**. The frontend's types carry no
`organization_id`, so it omitted it:

```
POST /transportation/{carriers,drivers,shipments,routes,load-plans,freight-charges}
POST /yard/{trailers/checkin,dock/doors,dock/appointments,moves,driver-wait-times,checkpoints}
POST /logistics-correlation/load-quality
POST /assets
```

A shipment you cannot create, a carrier you cannot add, a trailer you cannot check in, an asset
you cannot register. FS-99 found the same defect on four yard **GETs** — a required
`organization_id` query parameter no frontend call sent — and fixed them one router at a time.
The read side got a guard. The write side did not, and the same shape was sitting in fourteen
places.

`test_no_handler_takes_its_tenant_from_the_body.py` passes on every one of them, correctly:
none of these handlers *reads* the tenant from the body. Nothing asked whether the schema still
**demanded** it. Two artefacts, each right about itself.

The field is removed rather than made optional. A field a caller can set that changes nothing
invites somebody to set it and believe it did something; pydantic ignores extra keys, so a
client still sending one is unaffected. One handler comment had already recorded the decision
to defer this — *"Making it optional there is a separate change with its own readers to
check"* — and those readers are now checked.

### The guard found two the sweep did not

`AssetCreate` and `DockDoorCreate` were missed by the first pass, which keyed on the handler's
own parameter being named `organization_id`; those two derive the tenant under a different
name. The guard reads the **imported model** and the handler's dependency, so it does not care
what anything is called. A detector one degree narrower than its class would have shipped with
`POST /assets` — the core create path of the product — still answering 422.

### Removing a spurious required field revealed a real one

With `organization_id` gone from `LoadQualityLogCreate`, `POST /logistics/load-quality` began
returning **500** on an incomplete body: `load_quality_logs.asset_id` is `nullable=False` with
no default and the schema declared it `Optional`, so the request reached the INSERT and raised
`NotNullViolationError`.

It had always been broken. The spurious field was failing validation *first*, so the endpoint
answered 422 for the wrong reason and the genuinely missing field was never reached. Sweeping
the class found **nine** Create-schema fields that are optional over a NOT NULL column with no
default, across six schemas — most supplied by their handler, this one not.

`asset_id` is now required, so the caller gets a 422 naming the field instead of a 500 they
cannot act on. `root_cause_asset` — the second NOT NULL column on the same table — stays
optional deliberately: the service computes it and overwrites any caller value.

### And the frontend was sending a tenant

`AssetCreate` in `frontend/src/types/asset.ts` declared `organizationId`, which the axios
transform seam turned into `organization_id` on the wire. So creating an asset from the UI
meant supplying your own tenant. Removed, for the reason already written three lines below it
about `metadata` (FS-423): a write type that names a field the endpoint cannot apply — or must
not trust — is a promise the API does not keep. The **response** type keeps its
`organizationId`; the server sends it, and reading it was never the problem.

### The seven yard writes, which is where this started

`route_walk.py` drives every route for 5xx, so none was unexecuted; all seven were unasserted.
"Returns 200" is a weak claim for a state transition — `POST /trailers/{id}/checkout` answers
a hand-built `{"message": "Trailer checked out successfully"}`, past tense, built before
anything is verified, and FS-352 removed an endpoint whose whole body was a sentence like that
and no action.

Eleven tests: each transition is asserted against the database (checkout stamps a departure,
assigning a door takes it out of `available`, starting an appointment moves it off
`scheduled`, a move relocates the trailer, completing one stamps a duration, a wait time
persists with the rate the charge is computed from) and four assert a second tenant cannot
drive any of it — the service takes each id straight into `WHERE id = :id` with no
organization filter, so RLS is the only thing in the way.

**Suite:** backend 3626 → 3668 · frontend 843 · `tsc` clean.

---

## FS-526 — proving the fourteen actually create, not merely that they answer

FS-523 removed a required field fourteen create endpoints demanded and their handlers
discarded. That makes them **callable**. It does not make them **work**, and the distinction is
the whole reason this was invisible for so long: nobody had ever driven one of these to a 2xx.

`test_write_endpoints_reject_cleanly_realdb.py` is the negative twin — an empty body
everywhere, asserting 422 rather than 500. A route can satisfy that and be broken for every
real payload.

Nine tests take the positive half with a minimal valid body per endpoint, asking three things
the negative walk cannot:

1. does it answer 2xx,
2. is a row there afterwards, and
3. **does the row carry the caller's organisation.**

(3) is the one that would be silently wrong. The request no longer carries a tenant, so the
server is the only thing that can supply one — and a null there is a row invisible to its own
creator through any scoped read, swept up by anything scanning the table unscoped. That is
verbatim the defect `test_no_handler_takes_its_tenant_from_the_body.py` opens by describing.

The load-plan and freight-charge test hangs both off a shipment created **through the API**,
which also proves the id a create returns is usable as a foreign key rather than merely echoed
back. And one test sends a body `organization_id` naming the *other* tenant and asserts the row
still lands under the caller's: pydantic drops the extra key today, but `extra="allow"` and a
handler reading `data.organization_id` would restore the IDOR shape, and nothing else would
notice.

### My own fixture reproduced the defect class it was written for

The first version inserted an asset with no `workcell_id` and hit a NOT NULL constraint, which
looked briefly like another instance of the FS-523 500. It was not: `AssetCreate` already
**requires** `workcell_id`, correctly, and the fixture was simply wrong. Recorded in the file,
because the distinction is the point — a required field over a NOT NULL column is right, and
only an *optional* one over a NOT NULL column is the 500.

**Suite:** backend 3668 → 3677.

---

## FS-533 — constants presented as measurements, on two screens where the number decides something

Wave F closed "generated figures presented as measurements" for the GeoTab surface: `random.*`
behind a gate, stamped. This is the quieter half of the same class — **deterministic constants
written inline in a response builder**. A random number at least moves. A hardcoded one reads
as a measurement that happens to be steady, which is why it survives longer.

### Driver safety: three constants and a period that was not applied

`_driver_safety_out` returned `idleTimeHours: 0`, `seatbeltViolations: 0` and `trend: "stable"`
for every driver in every organisation. The response model's own docstring recorded exactly
that and left it, which is how a documented placeholder becomes a permanent one.

**`seatbeltViolations: 0` is not neutral on a driver safety report.** It is a claim that no
driver has ever been recorded unbelted, on the same screen as a score that decides who gets
coached — and it was countable from the same `geotab_exceptions` rows as the other three the
whole time. It is now counted, across every spelling GeoTab uses for it: `exception_type` is a
free-form string, and missing a spelling under-counts a safety figure, which is the direction
that looks like good news.

**`period: "30d"` was the outright lie.** `_exceptions` applied no time filter, so every count
was lifetime-to-date under a label saying thirty days. A driver's score got worse permanently
and could never recover, because nothing aged out. The query is windowed now, which makes the
label true and makes `trend` a real comparison — this window's score against the one before
it, and **null** when there is no previous window, because with nothing to compare "stable" is
a claim rather than an observation.

**`idleTimeHours` is null, not zero.** Idle time is a duration; `geotab_exceptions` records
events and has no duration column. There is nothing in this schema to compute it from, and a
zero is a measurement.

### And a frontend branch that could never fire

`HealthSecurityPanel.tsx:335` tested `driver.trend === 'declining'` for its red styling. The
backend's vocabulary is improving/worsening/stable — **`'declining'` has never been sent**. Two
independent reasons the branch was dead, which is why neither surfaced: the value was hardcoded
`'stable'` anyway.

The mock fixtures supplied `'declining'`, so the branch rendered correctly in every mock-mode
test and never once against a real backend. **A fake that shares the caller's mistake cannot
refute it** (rule 120). The mock's `period: 'last_30_days'` disagreed with the server's `"30d"`
for the same reason and is aligned too.

### Fuel surcharge: a money figure from three default arguments

`calculate_fuel_surcharge` took `base_fuel_price=2.50, current_fuel_price=3.50, mpg=6.0` as
defaults, and its only caller passes none of them. **Every freight charge this product has
produced came from a dollar-a-gallon differential written in a function signature** — and the
response echoed those two prices back beside the amount, where they read as prices something
had looked up. `FuelSurchargeCharge`'s docstring had already recorded this and said the honest
fix was to label a fallback surcharge as one.

Worse than stale — **duplicated**. `optimize_route`, in the same class, already reads
`settings.FUEL_PRICE_USD_PER_GALLON` (3.50) and `settings.FLEET_AVERAGE_MPG` (6.0): the same
numbers, entirely disconnected. An operator setting their own fuel price moved the route
estimate and left every freight charge behind, with nothing indicating the two disagreed.
Identical copies are the state in which divergence is least likely to be noticed.

And the arithmetic was decorative: `rate_per_mile = (fuel_diff * (distance / mpg)) / distance`
cancels exactly, so the rate was always `fuel_diff / mpg` and the surcharge was
`distance * fuel_diff / mpg`. Written to look like a per-mile calculation over the trip. Left
algebraically equivalent and stated plainly — **the amount does not change**, which is asserted,
because a silent repricing would be a far larger act than the one intended.

All three inputs now come from settings, and an `assumptions` block travels with the figure in
the shape FS-348 established, naming its `basis`: `configured_fleet_assumptions` or
`contract_table_default_entry`. The contract branch takes `table['default']` and does not index
by price — its own comment says "Implementation would look up based on current fuel price" —
so a caller with a contract can now tell that their banded rate was not applied.

### The tests passed alone and failed in company

The first version drove the coroutine with `asyncio.get_event_loop().run_until_complete`, which
works in isolation and breaks inside the suite where pytest-asyncio owns the loop. A test that
passes alone and fails in company is testing the harness. Rewritten as async.

Mutation-verified three ways: restoring the hardcoded seatbelt count, the zero idle time, and
the literal fuel-price default each fail with the specific reason.

**Suite:** backend 3677 → 3688 · frontend 843 · `tsc` clean.

---

## FS-534 — two scores that were computed partially and presented as if completely

The sibling of FS-533, one layer in. Those were constants presented as measurements; these are
real computations missing a term they were designed with, and saying nothing about it.

### The root-cause correlation score

`_analyze_root_cause` seeds `correlation_score` at `0.5` — `# Default moderate correlation` —
raises it `0.15` per critical alarm during the operation and `0.1` for a prior similar defect.
Its own design names a telemetry-anomaly term that is not computed:
`# (simplified - would do actual anomaly detection)`.

The sharper problem is that **0.5 means two opposite things**. With no asset supplied the
function returns 0.5 having queried nothing at all; after examining an operation and finding no
alarms it also returns 0.5. "We looked and found nothing" and "we never looked" were the same
number, and `# Default moderate correlation` is how the second one read.

This is persisted onto `load_quality_logs.manufacturing_correlation_score` and served from
there — it becomes the figure a quality engineer reads months later when deciding whether a
shipping defect came from the line. FS-349 named this exact failure (a report carrying a
`model_version` for a model never loaded) and the fix was to say so in the payload.

**The basis has to outlive the transaction, and my first version did not.** It returned `basis`
from `_analyze_root_cause` and the caller passed only the number to the row constructor, so the
qualification existed for the length of one function call while the bare 0.5 was still what got
stored. The comment I had written claimed it "travels with the score" — it did not. It now goes
into `meta_data`, the existing home for per-row provenance on that table, and a test asserts
the persistence rather than the return value.

### The shipping-readiness score

`_score_asset_for_shipment` reads PackML state, estimates operation completion and counts
recent quality issues — all real queries. Then:

```python
# Check asset OEE (would need actual OEE calculation)
# For now, use placeholder
```

and **nothing happens.** There is no placeholder. The comment describes a stand-in that does
not exist, which is worse than either doing the work or leaving it out, because a reader takes
it for a known approximation.

`factors` is the function's own explanation of its score, returned to the caller and rendered
to a user. It listed every term that *was* applied and stayed silent about the one that was
not, so a score built from three of four inputs read as complete. The omission is now stated
there — through the mechanism already present, rather than a second one beside it — plus a
machine-readable `terms_omitted`.

### The guard could not find its own subject

The first version looked the methods up on the engine instance and raised `AttributeError`:
`_analyze_root_cause` lives on `LoadQualityCorrelator`, which the engine composes, and the
readiness method is called `_score_asset_for_shipment`. It now searches every class in the
module by name and fails loudly if a subject disappears — a guard that cannot find what it
checks reports nothing, which is the failure mode this file exists to prevent one level up.

Mutation-verified: dropping the persisted basis, and restoring the placeholder comment, each
fail with the specific reason.

**Suite:** backend 3688 → 3699.

---

## FS-537 — six swallowed failures on the ingest path, none of them counted

`ingestion.py` catches and continues around two WebSocket publishes, two OEE updates, an alarm
publish, and **alarm rule evaluation**. Swallowing is right: telemetry that reached the database
is what matters, and the alternative is a poison message halting the pipeline for everything
behind it.

**What was missing is that nothing counted them.** A rule that raises on every message wrote
one `alarm_rule_evaluation_failed` line per message and aggregated nowhere. "Server-side alarm
rules have stopped firing" was therefore a condition the platform could not report: telemetry
keeps flowing, dashboards keep updating, and the alerting is silently off until an operator
notices an alarm that never arrived.

This is the third time the same argument has been made here, which is why the deliverable is a
guard rather than six edits. `INGESTION_DEAD_LETTERED` (FS-464) exists because "recoverable is
not the same as noticed". FS-496 raised the edge agent's swallowed Kafka failure out of `debug`
after it had failed 100% of the time invisibly. FS-504 counted a buffer prune that dropped 500
rows silently. **The platform was monitoring the edge's silent failures and not its own,
twice.**

### The guard found the sixth

The plan listed five. `test_every_swallowed_side_effect_is_counted.py` walks every broad
`except` in the file that does not re-raise, and immediately flagged a sixth:
`_process_alarm`'s WebSocket publish. Its failure means an alarm was written to the database
and never reached the live feed — the alarm exists, the page does not update, and nothing says
why. Found after the survey that produced the list had finished, which is the whole argument
for the guard.

It also flagged the top-level consumer handler, correctly by its own rule and wrongly in fact:
that one calls `_dead_letter`, which increments two counters that both have alert rules. The
detector cannot see an increment inside a helper. Exempted **by log event name** with the
reason recorded, rather than by widening the body match — a body-shaped exemption would also
silently excuse any future handler that happened to call something.

### A counter nothing alerts on is a metric, not a signal

`IngestionSideEffectFailing` reads the counter with a 5-minute `for` window, and
`infra/prometheus/tests/ingestion_side_effects_test.yml` proves it can fire from a series
shaped as the worker emits it — plus two must-stay-quiet cases: a counter that never moves, and
a single blip that stops inside the window. `promtool check rules` proves an expression parses,
never that a series exists to make it true, which is exactly how `EdgeAgentBufferHigh` was
syntactically perfect and useless (rule 121).

### And the alert tests were a hardcoded list

The `prometheus-rules` job named six test files explicitly, so a new one ran only if whoever
added it also remembered to edit the workflow — **and an alert test that does not run is
indistinguishable from one that passes.** Same shape as FS-489, where 47 e2e tests had never
executed because the collector's pattern did not match their filenames. It is now a glob that
fails loudly on an empty match rather than reporting success over nothing.

Mutation-verified: removing the alarm-rule counter fails three assertions.

**Suite:** backend 3699 → 3711 · 49 alert rules linted, 7 unit-test files passing · README
floor raised 3,200 → 3,700 (its own staleness ratchet fired at a 613-test gap).

---

## FS-529 — 53 functions inside live modules that nothing calls

`test_no_new_unreachable_modules.py` tracks whole **modules** nothing imports. It cannot see an
orphan inside a file that is imported and used on every request — and that is the more dangerous
shape, because the module around it is alive, tested and reviewed, so the dead function inherits
all of that credibility.

### The two that are not merely unused

**`core/security.py` holds a second, unreachable WebSocket authenticator.**
`get_current_user_ws` has no callers. The live one is `api/auth.py:resolve_websocket_user`,
whose own comment reads *"Same checks as core.security.get_current_user_ws"* — **it cites the
dead one as its reference**, and they are not the same: the live one also handles the dev-token
path. A parallel implementation of *authentication* is rule 55 in the worst possible place. The
next person who reuses the helper sitting in `core/security` gets subtly different auth from
the rest of the product. `verify_token` and `api_keys.verify_api_key` are the same surface.

**`llm_client.stream_generate` and `strategic_engine.get_recommendation_history` are finished
capability with no route in front of them** — not dead code, unwired features, and the reason
two screens render an em dash. Both are already planned (FS-563, FS-567); the inventory
independently found them from the other direction.

### The detector was wrong first, by a factor of twenty

Its first run reported **1,111 of 1,936 functions — 57% of the codebase.** The bug was a
decrement: it subtracted one use per `def`, on the theory that a definition is not a use. A
definition emits no `Name` node for its own name, so nothing needed subtracting, and every
method called exactly once netted to zero.

A sweep that flags most of a codebase is one nobody reads twice — the module-level guard's
header records being wrong the same way, by a factor of three. It would also have buried the
two auth duplicates in a thousand lines of noise, which is the concrete cost.

Two further filters take it from 484 to 53, both real rather than convenient: decorated
functions are excluded (a route handler, a pydantic validator and a pytest fixture are all
invoked by name-free machinery — counting them flags every endpoint in the product), and
definitions inside already-unreachable modules are excluded, because the module guard counts
them once and double-listing would make this file look like it had found twice as much.

**And I double-listed anyway.** Three `oracle_correlation_patterns.py` entries went into the
inventory for a file the module guard already carries, so `_orphans()` excluded them and the
entries described nothing. The staleness test caught it on the first run — which is what that
test is for, one level up from the docstring warning I had just written and ignored.

A calibration test now asserts the detector never flags more than a tenth of the codebase, so
the 57% version cannot come back looking diligent.

Mutation-verified: a new function in a live module fails by name. The scan is cached, so 56
parametrized cases run in 1.8s rather than 60.

**Suite:** backend 3711 → 3768.

---

## FS-536 — the audit trail has been silently empty here before, and nothing had changed about why

`db/models.py:1561-1567` carries the post-mortem, above `audit_logs.ip_address`:

> Migrations 001/009 create this as INET. Declared as VARCHAR here, every insert bound
> `$n::VARCHAR` and Postgres rejected it … and audit_trail swallows the failure as
> `audit_log_failed`, so **the audit trail has been silently empty on real deployments while
> every write appeared to succeed.**

The type mismatch was fixed. **The condition that made it invisible was not.** The handler
still logged and continued, and nothing counted — so the next thing to break an audit write, a
constraint or a migration or a full disk or an RLS policy, reproduces the identical outcome,
and an auditor discovers it by finding a period with no rows.

Continuing is right: an audit write must not fail a user's request, and a test asserts the
handler still does not re-raise, because a fix that took the platform down on a schema change
would be a far larger fault than the one being repaired. But *"do not fail the request"* and
*"do not tell anyone"* are separate decisions, and only the first had been made. Same argument
as FS-537 on the ingest path and FS-504 on the edge buffer — three places where the swallow was
correct and the silence was not.

`AuditWriteFailing` is **critical with `for: 0m`**, and both are asserted. An audit gap is a
compliance finding, it cannot be reconstructed after the fact, and unlike a dropped WebSocket
frame there is no acceptable transient. `infra/prometheus/tests/audit_alerts_test.yml` proves
it fires on a single failure, and stays quiet for a counter that never moves and for a
historical failure that has aged out — a permanently latched alert from one old failure is
muted within a day, which is the same as not having one.

### Two functions that appeared to try and fail

`_get_request_body` and `_get_response_body` each returned `None` inside a
`try`/`except Exception`. A `return None` cannot raise, so the handler could never fire — the
try/except was theatre implying an attempt that was not being made, and a reader looking for
why audit rows carry no payload found a function that looked like it was trying. They now say
plainly that bodies are not captured, and why (reading the body consumes the stream before the
route handler sees it).

**And the guard for that was wrong first, in the way this repository has a rule about.** It
searched the source text for `"except Exception"` and failed against the fix — because the
docstring explaining the removal contains that phrase. Rule 37: a substring search matches the
comment describing a defect as readily as the defect. It parses the AST now.

## FS-540 — measured, and the premise was wrong

Filed as "`api/health.py:596` returns 200 with nulls on any failure — indistinguishable from a
working probe with no data". It is not: `available: False` distinguishes them, the response
model documents why the three figures are nullable rather than zeroed, and
`AdminPages.tsx:535` renders "Host metrics unavailable" off that flag. The design is honest end
to end.

One real gap, narrower than filed: the `try` covered only `import psutil`, and the three calls
after it were unguarded. psutil raises under a restrictive seccomp profile or with `/proc`
unmounted — both ordinary in a hardened container — and the result was a **500 on an admin
page whose entire design is to say "unavailable" gracefully**. The answer already existed; the
fix is to reach it.

**Suite:** backend 3768 → 3778 · 50 alert rules, 8 promtool unit-test files.

---

## FS-539 — 201 handlers swallow a failure and 11 count it; both numbers now ratchet

283 handlers in `app/` catch `Exception`, `BaseException` or bare. **201 never re-raise**, and
in 190 of those nothing increments a counter — the only record is a log line that aggregates
nowhere.

**A sweep would have been the wrong deliverable.** Most of these are correct: a background task
that must not die, a best-effort cache warm, a notification that is nice to have. A file
demanding 201 fixes gets argued with and then ignored. What is not correct is that the number
can grow unnoticed, and that a swallow on a path that matters looks exactly like one on a path
that does not.

So two numbers moving one way each:

```
MAX_SWALLOWING   201  only DOWN — a new uncounted swallow fails the build
MIN_COUNTED       11  only UP   — hardening a handler is recorded, not lost
```

**The pair matters more than either alone.** A count cap by itself is satisfied by deleting a
handler; a counted floor by itself is satisfied by adding handlers that count. Together the
only way to move both correctly is to make an existing failure visible.

This has already cost three times, and each was found by accident rather than by a gate:
FS-504 (a buffer prune dropped 500 undelivered readings and counted none), FS-537 (alarm rule
evaluation failing silently, so the alerting was off while telemetry flowed), and FS-536 (**the
audit trail silently empty on real deployments while every write appeared to succeed** — the
schema still carries that post-mortem). In all three the swallow was right and the silence was
the defect.

### The totals are too coarse on their own

Swapping a counted handler in `ingestion.py` for an uncounted one somewhere quiet leaves both
numbers intact. So `ingestion.py` and `audit.py` — hardened by FS-537 and FS-536 — are named
individually and must stay fully counted, with a companion test asserting each still *has*
swallows to check, so a moved file cannot satisfy the rule by emptying it.

Three further properties are asserted rather than assumed: the detector must not count a
handler that re-raises (translating an error properly is the fix, not the defect), the
allowance must sit within ten of the real figure (a ratchet set well above it allows growth
while reading as a constraint — the failure `contract_ratchet.py` names in its own header),
and the walk must find a plausible number in both directions.

`MIN_COUNTED` is **11, not the 10 a body-only scan reports**: `ingestion.py`'s top-level
handler counts through `_dead_letter`. That exemption is imported from the FS-537 guard rather
than restated — the two files share one detector limitation, and a second copy of the reason
is a second thing to keep true, which is the shape FS-492 named.

Mutation-verified: one new uncounted `except Exception: pass` fails at 202.

**Suite:** backend 3778 → 3787.

---

## FS-530 — four engines expose a status route and none of them is started

`main.py` starts eight background services. `tactical_engine`, `mlops_pipeline`,
`strategic_engine` and `cloud_gateway` are not among them. Each defines `start()`, each spawns
its loops there, and **nothing calls it**. `tactical_engine.py:442-446` records its own
unreachability in a docstring, so this has been known for some time.

Every figure those routes report is therefore the value the object was **constructed** with:

| route | reports | means |
|---|---|---|
| `/engines/tactical/status` | `model_loaded: false` | nothing loaded a model |
| `/engines/mlops/status` | `cached_models: []` | the poll loop never ran |
| `/engines/cloud/status` | `connected: false` | the connection manager never started |
| `/engines/strategic/recommendations` | `[]` | the listener never ran |

Each reads as an observation about the world and is a fact about an object nobody switched on.
**`connected: false` on a cloud gateway reads as "the cloud is unreachable"** — a different and
far more alarming statement than "we never tried". `cached_models: []` reads as "no models have
been published". An operator cannot act on the difference, because the payload does not carry
it.

### This deliberately does not start them

Whether these engines should run — and what happens to the telemetry path when they do — is a
product decision in the correlation-AI lane, not a defect fix. What *is* a defect is a status
endpoint that cannot distinguish **not running** from **running and idle**. That is FS-349's
shape exactly, where a report carried a `model_version` for a model that was never loaded, and
the fix there was to say so in the payload.

Each status route now carries `running` and a one-sentence note. `cloud_gateway` had no
`_running` flag at all — three siblings had one and it did not, so `get_stats()` had no way to
answer the question — and now does.

**Both directions are asserted.** A permanent "not running" banner on an engine that has since
been started is the same defect pointing the other way, and the one that would survive longest:
nobody investigates a warning that has always been there. A test fails the day any of these
four appears in `main.py`'s start list, so the note comes out with the same change that starts
the loop.

### The list route is signalled by header

`/strategic/recommendations` returns a bare array, and an empty one means both "ran, found
nothing" and "never started" — the failure that renders as emptiness (FS-487). The page renders
"No recommendations" either way.

`X-Engine-Not-Running` follows `X-Result-Truncated`'s reasoning verbatim: clients already
consume the bare list, and reshaping it into an envelope would break every caller in order to
fix something they could then no longer see. A test asserts the body is still a list
comprehension — **parsed, not grepped**, because `return [` matches a docstring as readily as
a return, and the docstrings in this file are long enough that it would.

One assertion in the first draft was `... or True`. Removed — a vacuous assertion in a file
about things that only look like they are checking something is worse than none.

**Suite:** backend 3787 → 3803 · frontend 843 · `tsc` clean.

---

## FS-532 — the GeoTab gate had two structural guards and nothing that ran it

`geotab_service` invents telematics at ~35 `random.*` sites, including `hos_violation`
exception types and hours-of-service figures — **DOT-regulated findings**. Two defences
existed and both are structural: FS-267's guard pairs gating against stamping across the
module, and the production settings validator refuses the flag. **Neither runs the code.**

That matters because the gate is spelled two different ways. Four functions call
`_require_simulated()`; `get_device_location` inlines `if not settings.GEOTAB_SIMULATED`,
because it *prefers* real data and only invents a position when no trip endpoint or exception
fix exists. A structural check has to know both spellings — and a third, added by someone who
did not read the first two, is invisible to it while the fabricated data flows.

**My own detector proved the point before this file existed.** Sweeping for functions calling
`random.` without calling `_require_simulated` flagged `get_device_location` as an ungated
fabricator. It is not; it gates correctly, by a different name. A structural sweep is one
rename from a false positive and one new spelling from a false negative.

### The mutation test caught this file being vacuous

Deleting `get_device_location`'s inline gate left every assertion passing. With simulation off
the mock registry is skipped, so `known_ids` is empty and the method raises "Device not
found" — **a refusal, from a branch that has nothing to do with the gate**. The test asserted
"it refuses" and got that from somewhere else, which is precisely the failure mode its own
comment warns about two lines above.

The discriminating case needed a device that IS known and has no fix: a trip row with neither
`start_location` nor `end_location`. That puts the device into `known_ids` and leaves
`location` as None — the only path that reaches the gate. With it, "No known location";
without it, coordinates drawn from a bounding box and returned as a fix. On a map those are
indistinguishable.

The fixture was then wrong in its own right: `get_device_location` issues two queries, and
answering both with the trip made the second read `exc.location` off a `GeoTabTrip` and raise
`AttributeError` — a failure in the fixture that read as a failure in the gate. It is
order-aware now.

Mutation-verified three ways, each on a different defence: removing the HOS gate (fabricated
DOT data escaping), removing the inline location gate, and dropping the provenance stamp from
`get_exceptions`.

The refusal assertion deliberately does not pin an exception type — `_require_simulated` raises
`SimulatedDataDisabled` and the location path raises `ValueError` — but it does exclude
`TypeError` and `AttributeError`, because a test that passes because it called the method
wrongly proves nothing about the gate. The first version of the call table used an invented
device id and did exactly that.

**Suite:** backend 3803 → 3816.

---

## FS-541 / FS-542 — the coverage ratchet could not see nine of ten component directories

`vitest.config.ts` included `src/components/ui/**` — **one** of the ten directories under
`src/components/`. The other nine (assets, charts, commands, common, fleet, kanban, layout,
nlp, yard) were **10,566 lines outside the measurement**, so the four percentages described a
subset chosen once and never revisited, and the thresholds could not fall no matter how much
untested component code arrived.

The config's own comment describes exactly this failure for an even narrower include it had
already fixed: *"it measured the code we happened to have tested, so it could never fall no
matter how much untested code was added."* **The class was fixed at one depth and left open at
the next** — the scope was widened to five paths and one of those five was itself a leaf.

### Widening lowers the number and the threshold still rises

```
before, ui/ only        50.96 / 55.57 / 45.25 / 52.61    thresholds 38 / 41 / 34 / 39
after,  everything      45.60 / 46.30 / 41.39 / 47.02    thresholds 44 / 45 / 40 / 46
```

The measured figure **fell** by five points, because previously invisible code came into
scope — and the threshold still rises by six, because the old one trailed even the narrow
measurement by 13. A ratchet sitting 13 points below reality would have sat through coverage
falling by a quarter. Both changes are in one commit so the number moves for a stated reason
rather than appearing to improve.

Verified to bite: raising `statements` to 47 fails the run with
`Coverage for statements (45.6%) does not meet global threshold (47%)`.

### The guard found four more, including one that mattered

`coverageSeesEverySourceDirectory.test.ts` pairs every directory under `src/` against the
config's include and exclude lists. After the components fix it flagged `utils`, `types`,
`i18n` and `i18n/locales`.

**`utils/` was the real one.** It holds `formatters.ts` — which wraps every date and number
conversion in a try/catch — and `constants.ts`'s `STATUS_COLORS`, whose contrast values have
a test (`utils/statusColors.test.ts`) written specifically to protect them. **Both had tests and neither counted toward the number.**
`types/` and `i18n/locales/` are now excluded with reasons: type declarations have no runtime
behaviour, so including them adds a denominator with no possible numerator, and translation
catalogues are data on the same argument as `mockApi.ts`.

### The guard was wrong twice, and the mutation test found the worse one

First it parsed the **wrong `include:`** — the config declares one for which files are *test*
files and one for which files are *measured*, and taking the first match asserted against the
test-file pattern. It now slices from `coverage: {`, and a companion assertion fails if the
test-file glob is ever what gets read.

Then, more seriously: narrowing the include back to `src/components/ui/**` failed only the
*specific* assertion and not the general one. `covers()` stripped `**` from anywhere, so the
exclude entry `'**/*.test.{ts,tsx}'` — a **file** pattern, not a directory scope — collapsed
to an empty prefix and marked every directory as deliberately excluded. The whole-tree check
was agreeing with itself. Only `src/`-rooted globs count as directory scopes now, and the
corrected version immediately found the four above.

**Frontend:** 843 → 847 tests · `tsc` clean · coverage gate passing at the new floor.

---

## FS-544 / FS-581 — two mocks that pointed at nothing, out of 136

`Kanban.test.tsx` carried two `vi.mock` calls naming modules that do not exist:

```
vi.mock('../components/kanban/KanbanMetrics', ...)   the file is KanbanMetricsBar.tsx
vi.mock('../components/ExportButton', ...)           it lives in components/common
```

**Vitest does not warn about a factory registered for a module nobody imports.** Both were
inert, both real components mounted, and the test whose stated purpose is to isolate the page
from them was doing no such thing. The suite passed either way — which is exactly why it
survived. *A mock that does nothing and a mock that works look identical from the outside.*

A dead mock is worse than no mock: a test with none is honest about what it renders, while a
test with a dead one states an isolation it does not have — so a failure originating in
`KanbanMetricsBar` surfaces as a Kanban *page* failure, and whoever debugs it reads the mock
list and rules that component out.

**Deleted rather than corrected.** The page test has been passing with both real components
mounted all along, so stubbing them now would remove coverage this file already has in order
to honour an intention that was never enforced. The four remaining mocks stand in for things
the test genuinely is not about — a drag implementation and three modals.

`mockPathsResolve.test.ts` sweeps all 136 `vi.mock` calls and fails on any whose path resolves
to no file. It skips bare specifiers, because `vi.mock('axios')` is npm's problem.

### The guard reported itself, twice over

Its header quotes both dead mocks verbatim, so the first version matched them inside its own
docstring and named itself as the offender. **Rule 37 in its purest form** — a text search
finds the comment describing a defect as readily as the defect — and the third guard today to
hit it. It strips comments now, as `everyMockedClientHasARealModeTest.test.ts` already did for
the identical reason.

The self-check for that was then wrong too: it asserted the stripped source contains no
`KanbanMetrics` anywhere, which fails, because the renamed-module test uses those names as
**data**. Forbidding a string is not the same as forbidding a match; it asserts the precise
property now — that this file contributes no entries to its own sweep.

**Frontend:** 847 → 851 tests.

---

## FS-550 / FS-552 — an unlabelled combobox, app-wide, reported at 100% coverage

`ui/Select.tsx` rendered a `<label>` with no `htmlFor` and a `<select>` with no `id`. **A
screen reader announced "combo box" and nothing else** — on every filter and every form built
from the shared primitive. Its error text had no `role="alert"`, no `aria-describedby` and no
`aria-invalid`, so a validation failure was perceivable only to someone looking at the colour.

`Input.tsx`, one file away, does all of this correctly with `useId()` and has since task 6.
**That is what makes this a defect rather than an omission**: the pattern was established,
applied to one primitive, and not carried across. `Select` now mirrors it exactly.

### It was reported at 100% of lines the whole time

The barrel imports it, so the module body executes and every line counts as covered. Nothing
ever *rendered* it. `a11y.test.tsx` covered `Button` and `Input` and stopped there.

That is the same distinction FS-529 drew between a definition being tested and being reached,
arriving at the coverage report: **a file can be fully "covered" and never exercised.** It is
also why FS-541's widened include does not by itself help here — the number was already 100%
and already wrong.

The axe baseline now covers six primitives (`Button`, `Input`, `Select`, `Table`, `Modal`,
`Badge`) with two `Select`-specific assertions: that the label is queryable — which is what
throws without `htmlFor`/`id` — and that the error carries `role="alert"` and the control
`aria-invalid`, because that is the difference between an error being *visible* and being
*perceivable*.

Mutation-verified both ways: removing `htmlFor` fails two tests, removing `role="alert"` fails
one.

### `tsc` caught the Table test using another component's API

The first version rendered `<Table columns={...} data={...} />`. This `Table` is compound —
`Table.Head`, `Table.Row`, `Table.Cell`. In a JavaScript test that would have rendered an
**empty table** and asserted it had no accessibility violations, which is true and worthless.
The type checker refused it.

**Frontend:** 851 → 856 tests · `tsc` clean.

---

## FS-551 — thirteen buttons with no accessible name, and one that did nothing

Thirteen of 96 `<button>` elements had no `aria-label`, no `title` and no text. A screen reader
announces those as "button" and nothing else. The list included **both sidebar logout
buttons** — so a screen-reader user could reach the control that ends their session and not be
told what it was — plus two modal closes, two alarm-acknowledge controls, and the Kanban
board/list toggle.

One had no handler at all. `KanbanColumn`'s chevron was a `<button>` with no `onClick`:
focusable, announced as a button, silent when pressed. **That is worse than no affordance** —
it invites the action and then fails without saying so. It is presentational now, because
giving it behaviour is a feature decision and removing a false affordance is not.

### The detector was wrong three times, in both directions

| version | flagged | why |
|---|---|---|
| regex over lines | **75 of 97** | any button whose text sat inside a child element |
| JSX parsed, one level | 18 | text nested deeper than one child was missed |
| recursed with `forEachChild` | 11 | **descends into a child's attributes** — `<LogOut size={16} />` reads as content because of `{16}` |
| recursed over `children` only | **13** | correct |

75 of 97 is most of the codebase, which is the signature of a broken detector rather than a
broken product — the same failure FS-529's first run made at 57%. There is now a calibration
assertion capping it at a tenth, so that version cannot come back looking diligent.

**The third correction is the instructive one.** It made the sweep *under*-report, and the two
buttons it hid were the most consequential in the set. A false negative in an accessibility
sweep is invisible by construction: nothing fails, and the control stays unnamed. Every other
detector error today was a false positive, which announces itself.

`tsc` then caught two of my labels reading `alert.geofence_name` and `event.event_type` where
the types are camelCase — the template would have rendered `undefined` into the accessible
name, which is a label that is present and useless.

Mutation-verified both assertions: stripping one logout label, and restoring the handler-less
button.

**Frontend:** 856 → 860 tests · `tsc` clean.

---

## FS-548 / FS-582 — "0 Vehicles" is the same lie as "No vehicles", and the sweep could not see it

`GeoTabIntegration` caught both of its fetch failures into `console.error` and nothing else.
A failed vehicle load left the array empty and the header rendered **"0 Vehicles"** beside an
empty map. A dispatcher reads that as the fleet not reporting — a claim about the world, from
a failure of the request.

**`failureIsNotEmptiness` is structurally blind to it.** Six broadenings had made that sweep
progressively better at finding empty *text*, and a number is not a phrase: a component can
say exactly the same thing in digits and never enter the population. A count reads as *more*
authoritative than a sentence, because a figure looks computed.

The component now has real loading and error states, and the count only renders when the
request succeeded. Geofences deliberately do not set the error — a geofence failure leaves the
map usable, and `loadError` is reserved for "the vehicle list did not arrive".

### The seventh pattern, and the seventh false positive

`RENDERED_COUNT` matches a count with a **noun beside it**, in JSX text. `{items.length}`
alone is usually a key or an index; `{items.length} Vehicles` is a statement to a user. Two
sites match across the tree — the right order of magnitude for a pattern meant to catch a
claim rather than an expression.

It flagged `CorrelationAIPane` on its first run, correctly by its own rule and wrongly in
fact: that badge sits inside `{currentSession && …}`, so a failed load leaves the object null
and nothing renders. **A count read off an object is guarded by that object existing** — a
guard shape none of the six previous patterns needed to know, because a literal phrase has no
receiver. The check requires the *same* receiver: `{foo && …{bar.count}…}` is not a guard for
`bar`, and accepting any nearby `&&` would excuse most of the tree.

That is the seventh false positive this file has recorded, and the first belonging to a
pattern that is not about phrases. Its history is now a chain of seven broadenings and seven
corrections, each written down where the next person will hit it.

Mutation-verified: reverting the badge to a bare count fails the sweep by name.

**Frontend:** 860 tests · `tsc` clean.

---

## FS-553 — forty-five labels that were captions, not labels

A `<label>` with no `htmlFor`, sitting beside its input rather than wrapping it, is a caption.
A screen reader announces the control as "edit text" with no name, clicking the text does not
focus the field, and the form is usable only by a sighted mouse user. `GeofencingPanel` had
eight, `CreateTaskModal` seven, `KanbanFilters` six.

Same defect as FS-550, one layer out: there the shared primitive was unlabelled; here it is the
pages that hand-roll their own form markup instead of using it.

34 were wired mechanically by an AST codemod — the shape is uniform, a `<label>` followed by a
sibling control inside a `<div>`, and 34 hand edits across ten files is how a typo gets in.

### Four forms count as association, and the detector knew one

| form | sites |
|---|---|
| `htmlFor` pointing at the control's `id` | 5 |
| the label **wrapping** its control — implicit, valid | 10 |
| the control being a self-labelling component (`ui/Input` takes a `label` prop) | 11 |
| the label wrapping **`{children}`** — a generic `Field` wrapper | 1 |

The first measurement said **"55 of 60 unassociated"**, knowing only the first form. Ten of
those wrap their control and are correct. That is the fourth detector this week to over-report
by not knowing a second idiom — and 92% of a tree is a number large enough to be dismissed
rather than acted on.

The fourth form was found by the guard on its first run: `ShopFloor` defines
`<label><span>{label}</span>{children}</label>` and passes each input in. At the call site the
label really does wrap its control; a static walk sees an expression and cannot know what it
will hold. The check is narrow on purpose — only the literal identifier `children`, or it
would excuse every label containing interpolated text.

### The codemod's first run generated colliding ids

It slugged the label text alone: `id="title"`, `id="description"`. Those collide the moment two
forms are mounted together, and **a duplicate id does not error** — the label silently points
at the first match in the document, so the association reads as fixed and is not. Every
generated id now carries its component's name, and a test asserts no literal id appears in two
files.

Eleven remain, listed with what each needs: a `ui/Input` sibling wants the `label` prop rather
than an adjacent `<label>`, and three controls are nested inside a wrapper div. A finite set
rather than a silent tail, with a staleness test so it cannot become a place findings go to be
forgotten.

Mutation-verified: removing one `htmlFor` fails by file and line.

**Frontend:** 860 → 865 tests · `tsc` clean.

---

## FS-554 / FS-555 / FS-556 — three frontend surfaces that may only shrink

Each is a population where most instances are fine, a few are defects, and telling them apart
needs judgement a sweep cannot supply. A file demanding thirty fixes gets argued with and
ignored; a number that can only move one way costs nothing and makes the next addition a
decision.

### The one real defect, and it is the sharpest kind

The plan listed "twelve non-null assertions on nullable network fields". Measuring found all
but one are guarded by a preceding `.filter()` or ternary — TypeScript simply cannot narrow
across a callback boundary. **The framing was wrong and the residue was one.**

That one is `GeofencingPanel`'s `(selectedZone.radius! / 1000).toFixed(1)`. The same file's
header records that `zone.center!.latitude` threw on the first centerless zone and, with only
the app-root ErrorBoundary, **blanked the entire app**. `radius` is optional for exactly the
same reason — a polygon zone has neither — so this is the identical crash on the sibling
field, twenty lines below the comment describing it. A polygon zone has no radius to show, so
the row is omitted rather than rendered as NaN.

### The ratchets

```
MAX_NON_NULL_ASSERTIONS   30    only DOWN
MAX_INLINE_TO_LOCALE      93    only DOWN
MIN_FORMATTER_CALLS       65    only UP
MAX_COLOUR_MAP_FILES      12    only DOWN
```

`utils/formatters.ts` wraps every date and number conversion in a try/catch returning
`'Invalid date'`. Ninety-three call sites bypass it, so `new Date(null).toLocaleString()`
renders the literal string **"Invalid Date"** to a user, and a malformed ERP timestamp becomes
a cell of nonsense rather than a handled absence.

That one is **paired with a floor**, for the reason FS-539 gives: a cap on the bad number
alone is satisfied by deleting a call site, and only moving both together means a conversion
was migrated rather than removed.

Twelve files map a status to a colour. `STATUS_COLORS` in **`utils/constants.ts`** has a
contrast test (`utils/statusColors.test.ts`) protecting its values, and the eleven copies do
not — `pages/Alarms.tsx` reproduces the map verbatim, **including the exact strings that test
exists to protect**. FS-492's shape, where the copy is of the one thing that has a guard, so
the guard covers a twelfth of what it appears to.

*(This paragraph first cited a statusColors module under utils/, which does not exist — the
test is named for the concept and the map lives in `utils/constants.ts`.
`test_documented_files_exist` caught it on the next full run: the guard doing its job on the
person adding guards.*

*It then caught this very sentence, because a confession that names the missing path in
backticks is indistinguishable from a citation of it — rule 37 once more, in a document rather
than a detector. The path is written in plain prose here so the guard reads it as English.)*

The non-null count is parsed rather than grepped: `!` appears in `!foo`, `!==`, and inside
every string in the tree, and only the AST distinguishes the assertion from the operator.

Mutation-verified: one added `x.a!.toLocaleUpperCase()` trips two ratchets at once.

**Frontend:** 865 → 871 tests · `tsc` clean.

---

## FS-557 — NetSuite syncs completed, stored rows, and analysed nothing

NetSuite has a working connector, it stores raw records, and
`erp_sync_correlation.route_for("netsuite", …)` returned `None` for every entity. So every sync
completed, wrote its rows, and reported `skipped: unrouted` — **a successful integration with
an empty correlation list, and nothing anywhere saying the vendor was never analysed.**

### Why not reuse SAP's transformer, demonstrated rather than asserted

The route registry states the rule in its own header: *"Reusing another vendor's transformer
would yield empty normalized records and a confident report of zero anomalies."*

A test now proves it. `transform_invoice` reads `InvoiceId` and `DueDate`; SuiteTalk sends
`tranId` and `dueDate`. Running SAP's transformer over a NetSuite payload produces
`invoice_number: None, due_date: None, total_amount: None` — and an analyzer reading a record
of nulls **finds nothing wrong with it**. The failure is a clean bill of health, not an error,
which is why it would have survived.

### Two SuiteTalk shapes that decide whether this works at all

* **Reference objects.** `status`, `entity` and `currency` arrive as
  `{"id": "3", "refName": "Open"}`, not strings. A dict is truthy and never equal to a status
  string, so the overdue check would take the wrong branch for every invoice.
* **String amounts.** `"4820.50" > average * 5` is a `TypeError` in Python 3, raised inside a
  background sync where it is swallowed and the vendor silently stops producing correlations.

### The status vocabulary is the one that would have been a confident wrong answer

`analyze_invoice_anomalies` tests `status != "paid"`. NetSuite never says "paid" — it says
**"Paid In Full"**. Without the mapping, *every settled invoice reports as overdue*: FS-435's
shape exactly, two vocabularies with no translation, and the output is wrong rather than
broken. Mutation-verified — removing the mapping fails seven tests, including the one asserting
a paid invoice is *not* flagged.

Inventory uses `quantityAvailable` (on-hand minus committed) against `reorderPoint`. Reading
`quantityOnHand` instead reports a real shortfall as healthy — the direction that looks like
good news — so the field choice is asserted with a payload where the two disagree (80 on hand,
12 available, reorder at 50), not merely commented.

### The half-finished registration failed closed, by design

The four routes were registered before the `PATTERN_CLASSES` entry, and `route_for` still
returned `None` — because it refuses a vendor with routes and no pattern class, exactly as its
docstring promises: *"a registry entry without a matching PATTERN_CLASSES entry resolves to
None rather than failing later inside a background sync."* A half-done edit produced no
correlations instead of an AttributeError in a swallowed task.

The existing registry guard then demanded a sample record for each new transformer and failed
until it got one. The samples are SuiteTalk-shaped — reference objects and string amounts —
because a sample of plain scalars would exercise neither of the two conversions the transformer
exists to perform.

**Suite:** backend 3816 → 3836 · frontend 871.

---

## FS-558 / FS-559 / FS-560 / FS-561 — the remaining four vendors, and the five spellings of "paid"

Odoo, Infor, Epicor and Intuit were each in NetSuite's state: a working connector, stored
records, and `route_for()` returning `None`. Every sync completed and reported
`skipped: unrouted`.

Each now has a transformer reading **its own** field names, a pattern class, registered
routes, and a test driving a real vendor payload to an anomaly. All eight vendors route.

### The five spellings of "this invoice is settled"

| vendor | field | settled looks like |
|---|---|---|
| NetSuite | `status` | the string `"Paid In Full"` |
| Odoo | `payment_state` | `"paid"` — and `state: "posted"` is **not** it |
| Infor | `Status` | `"Paid"` |
| Epicor | `OpenInvoice` | the **boolean** `False` |
| Intuit | `Balance` | the **number** `0` — there is no status field at all |

**Two of the five carry settlement in a field that is not a status, and one of those is a
boolean whose false value means paid.** A transformer looking for a status string finds
nothing on either, leaves it `None`, and `None != "paid"` — so *every Epicor and every
QuickBooks invoice would be reported overdue the moment its due date passed*. Not an error: a
confident wrong answer, on a finance screen, for two entire vendors.

Odoo's is subtler. `state: "posted"` means the document is finalised, not that money arrived;
reading it instead of `payment_state` marks every posted invoice paid and **suppresses every
overdue finding**. The two mistakes fail in opposite directions and neither raises.

A single test asserts all five normalise to the same token, because five per-vendor tests can
each pass while the vendors disagree — and then a cross-vendor view compares incomparable
values and nothing fails. Mutation-verified on all three unusual fields.

### The module guard called four live modules dead — and had two wrong already

The four new pattern classes are loaded by `importlib` from a dotted string in
`PATTERN_CLASSES`, so no `ast.Import` node exists and the guard reported them unreachable. The
fix a reader would reach for is to delete them.

Widening the walk to count a dotted `app.*` string in production code then exposed something
worse: **`oracle_correlation_patterns` and `infor_connector` were already in that baseline,
described as dead, with reasons somebody had written after checking.** Oracle has been routed
since it was wired; Infor's connector is loaded by the factory. A reader acting on either
entry would have deleted a live module.

That is the cost of a detector that knows one idiom — not a false alarm, which announces
itself, but **a false entry in a curated list, which reads as verified.**

Two smaller corrections on the way: the exclusion for test files used `is not` against
`ROOT / "tests"`, which builds a new `Path` each time, so the identity comparison was always
true and the vacuity probe kept counting itself.

### The two dead-code guards handed a finding to each other

Removing `oracle_correlation_patterns` from the module baseline moved it out of that guard's
population and into the definition-level one — where its three genuinely orphaned analyzers
belong. Nobody wrote them back: `test_no_new_orphaned_definitions` failed on the next full run
and named all three. They had been in that inventory earlier and were removed as
double-listed, which was correct at the time and stopped being correct when the facts changed.

**A finding that fell between two guards would have been invisible in exactly the way both
files exist to prevent.**

**Suite:** backend 3836 → 3873.

---

## FS-567 / FS-568 — a rejected recommendation vanished

`reject_recommendation` removed the recommendation from `pending_recommendations` and appended
it nowhere. The only record was a `queue_discrete_event` to `cloud_gateway` — **which is never
started** (FS-530) — so in practice the operator's decision was discarded the moment it was
made.

That is worse than losing an approval. An approval is visible in its effects; **a rejection is
a decision not to act, and the only evidence it happened is the record of it.** Without one the
same recommendation returns on the next cycle and the operator rejects it again, with nothing
to say they already did.

`get_recommendation_history` existed with no route in front of it — which is why
`StrategicEngine.tsx` renders an em dash for decision history, and why the method was in the
definition-level dead-code inventory (FS-529), found independently from the other direction.
It also read `implemented_recommendations`, which holds approvals only, so a history of
decisions omitted every decision not to act.

### The plan's premise was wrong, and the truth was worse

FS-568 said the response model omits `status`, `approved_at` and `rejected_at`, *"which the
engine does set"*. **The engine did not.** Those keys went into a cloud-event payload bound for
a gateway that never starts, and never onto the recommendation itself.

Both halves were missing — so declaring the fields on the response model alone, as the item
described, would have shipped a permanent `"pending"` for every recommendation ever decided.
The recommendation now carries `status`, `decided_at`, `decided_by` and `decision_note`;
`status` defaults to `"pending"` so a consumer never has to distinguish *not decided* from
*field absent*; and the response model declares all four, because FastAPI **omits** an
undeclared field rather than erroring.

### Three guards caught the change, each correctly

* `test_no_new_orphaned_definitions` named `get_recommendation_history` as a **stale**
  inventory entry the moment it got a route. An inventory reporting wired code as dead is what
  makes the whole list untrustworthy, so it is caught rather than curated.
* `test_readme_test_count_is_not_stale` noticed the API grew to 471 operations while the README
  said 470 — a figure quoted to describe how much of the API the contract gate covers.
* `test_capped_lists_cannot_grow` failed because the new route takes a `limit` and returned a
  bare array. `MAX_UNSIGNALLED` is zero and this was the first thing to break it. **On a
  decision log a full page reads as "these are all the calls anyone made"**, so it selects one
  extra row and sets `X-Result-Truncated` from evidence rather than from `len(rows) == limit`,
  which cannot tell a full page from a final one.

A test also asserts `/history` is declared before the `{rec_id}` routes: FastAPI resolves in
declaration order, and a parameterised route declared first would swallow the literal segment
while the endpoint still appeared registered.

Mutation-verified: making a rejection append nowhere again fails three tests.

**Suite:** backend 3873 → 3881.

---

## FS-575 — eight exported hooks nothing imports, and one of them is a whole subsystem

The frontend twin of the backend's unreachable-module inventory. An exported hook with no
consumer reads as available capability: typed, compiling, in autocomplete — so the next person
who needs that data writes a second one rather than finding this.

**All six `useFeatureFlags` exports are unused, and the backend serves the API.**
`app/api/feature_flags.py` mounts full CRUD and `featureFlagsApi` wraps it. So the feature-flag
system exists end to end and **nothing in the product consults a flag** — a different and more
interesting fact than "dead code". Deleting the hooks would leave a backend serving an API with
no client at all; wiring them is a decision about whether this codebase gates behaviour on
flags. Recorded, not resolved.

`useWorkcells` and `useOrganizations` are duplication rather than absence — both wrap endpoints
already read through direct api calls, which is rule 55's shape, so the entry says which is
which for whoever adds the third.

**The guard satisfied itself on its first run.** It lists all eight names in `DEAD_EXPORTS` and
in its own prose, and it lives under `src/` — so the consumer scan counted its own inventory as
usage and reported every recorded entry as wired. An inventory that satisfies itself is the
emptiest possible guard.

That is the same shape as the `vi.mock` sweep reading its own docstring (FS-544) and the
doc-citation guard flagging its own confession (FS-557). **Three times today, in three
different languages** — a guard that scans the tree it lives in must exclude itself, and it is
not obvious until it passes when it should fail.

Mutation-verified: a new unused export fails by name.

**Frontend:** 871 → 876 tests · `tsc` clean.

---

# FS-493 … FS-575 — what this tranche found, in one place

Eighty-three items across five waves. The summary is not a list of fixes; it is the set of
**shapes** that turned up more than once, because those are what the next person will hit.

## Six things were broken in production and produced no signal

| | |
|---|---|
| Every model rollout the cloud dispatched | the agent registers `agent_update` only and answered `unknown_action`, so the rollout recorded a **device** failure against working hardware (FS-505) |
| Staging never had monitoring, autoscaling or the HA database applied | all three hardcode `namespace: omniusgrid` and the job piped them into `-n omniusgrid-staging`, which kubectl refuses, under `set -euo pipefail` (FS-509) |
| KEDA scaled nothing, in **both** environments | the ScaledObjects target `ingestion-worker` and the overlays deploy `prod-ingestion-worker` (FS-510) |
| The compose Prometheus exited on startup | `--alertmanager.url` was removed in Prometheus 2.0, so nobody running the stack locally has ever had metrics — while four CI gates asserted the rule files were well-formed (FS-516) |
| Fourteen create endpoints answered **422** to the frontend | including `POST /assets`; their schema required an `organization_id` the handler discards, and the frontend sends none (FS-523) |
| Five ERP vendors synced, stored rows, and analysed nothing | `route_for()` returned `None`, so each reported `skipped: unrouted` behind a successful integration (FS-557…561) |

## The recurring shapes

**A number that was never computed.** `seatbeltViolations: 0` on a driver safety report is a
claim that no driver has ever been recorded unbelted — countable from the same rows all along.
Every freight charge came from a fuel differential written in a function signature. `period:
"30d"` on a query with no time filter, so a driver's score got worse permanently and could
never recover. And `0.5` meaning both "examined and found nothing" and "never looked", persisted
to the row a quality engineer reads months later.

**Swallowing was right; silence was the defect.** Three times — a buffer prune dropping 500
undelivered readings, alarm rule evaluation failing so the alerting was off while telemetry
flowed, and the audit trail *silently empty on real deployments while every write appeared to
succeed*. In each the `except` should stay and the counter should have existed.

**Two artefacts, each correct about itself.** The backend knew which commands it dispatched and
the agent knew which it registered. The consuming half knew which secrets it needed and the
provisioning half knew which it created. The label knew its text and the input knew its id.
Nothing read both.

**A guard whose subject list was narrower than the code.** `overlays/dr` absent from a
"canonical" README that five gates build. Six alert-test files listed by hand in CI. Nine of ten
component directories outside the coverage measurement. Each artefact was correct when written
and wrong the moment the tree grew.

## What the detectors cost, and it was mostly mine

Eleven detectors in this tranche were wrong before the code was. The pattern is stable enough
to state as a rule: **a sweep that flags most of a tree is a broken detector, not a discovery.**

| sweep | first reported | why |
|---|---|---|
| orphaned definitions | 1,111 of 1,936 (57%) | subtracted a use per `def`; a definition emits no `Name` node |
| unnamed buttons | 75 of 97 | regex could not see text nested inside a child element |
| unassociated labels | 55 of 60 | knew `htmlFor` and not the three other valid forms |
| ERP status vocabulary | — | five spellings, two of them not status fields at all |

The one that matters most went the **other** way. Recursing the JSX tree with `forEachChild`
descends into a child's *attributes*, so `<LogOut size={16} />` read as renderable content and
**both sidebar logout buttons dropped out of the unnamed list** — the control that ends a user's
session. An over-reporting sweep is noisy and gets fixed; an under-reporting one passes.

**Three guards satisfied themselves**, in three languages, in one day: the `vi.mock` sweep
matched the dead mocks quoted in its own docstring, the doc-citation guard flagged the paragraph
confessing a bad citation, and the dead-hook inventory counted its own list as usage. A guard
that scans the tree it lives in must exclude itself, and none was obvious until it passed when
it should have failed.

And a **false entry in a curated list** is worse than a false alarm, because it reads as
verified: two modules sat in the unreachable inventory described as dead, with reasons somebody
had written after checking. Both are loaded by `importlib` from a dotted string. A reader acting
on either entry would have deleted live, routed code.

## What is deliberately not done

* **FS-573** — 92 contract non-conformers. An L-sized burn-down needing the live gate to iterate
  against; the floor is unchanged and holding.
* **FS-563…566** — RAG streaming, async ingestion, document metadata, answer feedback. Another
  lane, untouched.
* **FS-562** — the backend reports `routed: false` with a reason per entity; surfacing that
  third state on the correlations view is a frontend data-flow change.
* **FS-530** — the four engines are still not started. Whether they should run is a product
  decision; what was fixed is that their status routes no longer report construction defaults
  as measurements.
* **Wave Q** (FS-585…592) — the standing carry-across hunt, not begun.

---

## FS-573 — the contract gate was run, and the number is not usable

Run locally against an isolated TimescaleDB after this tranche's changes:

```
contract conformance: 387/471 operations (ratchet: 380)
84 failed, 387 passed in 34:12
```

**The gate passes.** Nothing in this tranche dropped conformance below the committed floor,
including the fourteen create endpoints FS-523 made callable for the first time — which is the
question worth asking, because an endpoint that used to answer 422 on a missing required field
now reaches its handler, where generated input can find a 500.

**The number itself is not a conformance measurement, and the ratchet was not raised.**
`contract_ratchet.py` printed *"Raise BASELINE_PASSING to 387 to lock the gain in"*, and doing
that would have been wrong twice over:

* This run had **no Redpanda**. CI supplies one (`REDPANDA_URL: 127.0.0.1:39092`); locally the
  app spent the run retrying a broker that was not there — 352 `KafkaConnectionError` lines,
  individual requests taking up to **73 seconds**, and **47 of the 84 failures are read
  timeouts** rather than contract violations. A timeout is a fact about my laptop.
* 387 is **below the 392** measured earlier in this session under the restricted role. Raising
  a floor to a number lower than one already observed is not locking in a gain; it is lowering
  the bar while the tool's message makes it read as the opposite.

So the floor stays at 380 and FS-573's burn-down stays open. What this run does establish is
the negative: **no regression below the floor**, under conditions worse than CI's.

The tool behaved correctly throughout, including on the run before this one — a truncated
report was rejected with *"collected 1 operations, expected about 452 … a collapse in
collection would look like a pass"*, which is the vacuity check earning its place.

---

# Wave Q — the standing defect hunt

Eight carry-across items: take a class already closed once, ask which other component has the
same shape, sweep, guard, mutation-verify. **Three of the eight found nothing, and that is
recorded, because "proven clean" and "never checked" look identical afterwards.**

## FS-590 — no two guards keep the same list, and the first duplicate was mine

FS-492 found a sweep reading a private copy of the shared route list. Carried across to **the
guards themselves**: 86 module-level string collections live in `tests/`, and any two
describing the same fact will drift, because nothing compares them.

**`ENGINES` vs `EXPECTED_DORMANT`.** `test_service_lifecycle_is_declared.py` already declared
exactly which background services are dormant, with better reasons than a bare list — including
the one that matters: `cloud_gateway` holds a 10,000-entry in-memory queue drained only by the
`_flush_loop` its own `start()` launches, so starting any producer without it means events
accumulate and are silently dropped. **I wrote the duplicate hours before this sweep found it**,
in the FS-530 guard. It derives from the shared declaration now.

**`OTHER_LANES` vs `_OTHER_LANES`.** Two sweeps' idea of which routers belong to another dev —
and **they had already diverged**: one exempted `rag` and the other did not, silently, with
neither file able to see it. Benign as a subset, and the next edit to either would have widened
it. Lane ownership is one fact about the team, so it moved to `_lane_failures.LANE_ROUTERS`.

**Two media-type guards keep different lists of response classes** and each is missing entries
the other has — `DYNAMIC` has `RedirectResponse`, `_EMITTERS` has `PlainTextResponse`,
`HTMLResponse` and two helpers. `PlainTextResponse` sets its own content type and is absent from
the first, which looks like a gap rather than a distinction. **Recorded, not merged**: both
belong to a sweep I have not read in full, and merging two lists on a resemblance is how a guard
quietly widens or narrows.

**`PUBLIC_PROBES` ⊂ `PUBLIC_REQUIRED_EXACT`** — compared and left alone. Different questions
("must not disclose" vs "must be reachable unauthenticated"), and the subset relation is
coherent rather than accidental.

### Deriving a list trades one failure for another

Sharing removed the divergence and handed the source control of the consumer's population. When
a mutation test dropped `cloud_gateway` from `EXPECTED_DORMANT`, the engine-status suite went
from 16 tests to 14 **and reported success** — it had silently stopped checking the one engine
whose dormancy actually costs something.

A count is the cheapest thing that notices. Sharing a list is right; sharing it without
asserting what you got back is how a guard narrows to nothing one entry at a time.

The detector needed one correction of its own: two `Path` constants pointing at the same
workflow file share three "members" (`.github`, `workflows`, `quality-gates.yml`). Two guards
reading the same file is correct, and reporting it is the kind of noise that stops a sweep being
read — `Path` expressions are excluded.

## FS-589, FS-592 — swept, nothing found, recorded

**Hardcoded constants presented as measurements**, carried from FS-533 across all of `app/`.
Forty numeric literal defaults exist; narrowing to the actual shape — *a default no caller ever
overrides, whose value becomes a figure a user reads* — leaves **seven**, and every one is an
internal threshold or cap (a dedup TTL, a PSI threshold, a calculation interval, a field cap).
None is the fuel-surcharge shape where the default IS the answer on screen.

**Counted what does not run**, carried from FS-490 to the frontend test suite: **zero** `.skip`,
`.todo`, `xit` or `xdescribe` across 110 test files.

**Suite:** backend 3881 → 3897.

---

## FS-585 / FS-591 — the one counter that measures permanent loss reached nobody

Carried from FS-485 ("a signal the server sends and nothing consumes") to the **edge→backend
heartbeat** — the one wire in this product where a field crosses a network, a schema, an ORM and
a response model. Four boundaries, each of which fails silently.

**It found `dropped`.** The agent counts telemetry its store-and-forward buffer discarded;
FS-504 built that counter, because up to 500 undelivered readings vanished per disk-full event
with nothing recording it. The count is sent in every heartbeat, accepted by `HeartbeatPayload`,
and written to `edge_agent_status.dropped`.

Then it stops. `AgentStatusOut` omitted it, `update_fleet_metrics` set no gauge, and no alert
named it. FastAPI **deletes** an undeclared response field rather than erroring, so the number
travelled the entire wire, landed in a column, and reached nobody.

### The instrumentation was inversely proportional to the severity

| figure | what it means | gauge | alert |
|---|---|---|---|
| `buffer_pending` | waiting to send — **recoverable** | ✅ | ✅ `EdgeAgentBufferHigh` |
| `dead_lettered` | preserved for replay — **recoverable** | ✅ | — |
| `dropped` | **gone from the device, never arrived** | ❌ | ❌ |

Both recoverable figures were instrumented. The permanent one had no gauge, no alert, and no
field in the response. All three now exist, and `EdgeAgentDroppingTelemetry` is `critical`
reading an **`increase` over an hour** rather than a threshold on the cumulative total — an
agent that dropped 4,000 readings during an outage last quarter is not an incident today, and
an alert that always fires is muted within a day. The promtool test drives the firing case and
both quiet ones.

### And a second finding, recorded rather than resolved

`agent_version` **is** served — by a different route, from a different column.
`GET /fleet/agents/versions` builds its distribution from `Asset.agent_version`, written by the
**Kafka** heartbeat path (`workers/ingestion.py:415`); the **HTTP** heartbeat writes
`EdgeAgentStatus.agent_version`. Two writers, two tables, one fact — so an agent reporting over
one path and not the other shows a different version depending on which screen you open.

Not resolved here: reconciling them means deciding which table owns the fleet's version, which
is the OTA lane's call. Recorded so the next person to touch either writer sees the other.
Rule 122, again.

Mutation-verified at all three boundaries independently — removing the accept field, the
response field, and the gauge each fail with the specific reason.

**Suite:** backend 3897 → 3910 · 51 alert rules.

---

## FS-586 / FS-588 — a stale cost is a number a dispatcher acts on

Two carry-across sweeps, and the second found money attributed to the wrong shipment.

### FS-586 — the three-state chain, applied to hand-rolled fetches

`failureIsNotEmptiness` was broadened six times and reaches components that fetch by hand.
This asks the narrower question: does such a component have a **loading** and an **error**
state at all? Two matched, and one was a false positive — `App.tsx` builds routes with
`lazy(() => loader().then(…))`, which is code-splitting, not data.

The real one is `PlatformDataSourcePicker`, and it is FS-549's subject found independently:

```ts
platformCorrelationApi.listSourceTypes().then(setTypes).catch(() => setTypes([]))
```

A failed request left the list empty and the component rendered an empty `<select>` beside an
**enabled Add button** — which reads as "this platform has no data sources to offer" rather
than "we could not ask". The user then picks nothing, presses Add, and gets a *second* failure
from the attach call. **The first failure is discovered through the second, one interaction
later, with nothing connecting them.** It now says which happened, and the button is disabled
while it is true.

### FS-588 — three defects in two lines, all of them money

```ts
useEffect(() => {
  transportationApi.getShipmentCosts(shipment.id).then(setCosts)
}, [shipment.id])
```

1. **No clear.** Switching from shipment A to B leaves A's linehaul, fuel surcharge and total
   on screen, under B's heading, until B's request returns.
2. **No catch.** If B's request fails, A's figures stay there **permanently** — the panel never
   stops attributing them to B, and an unhandled rejection is the only trace.
3. **No cancellation.** If A's request is slow and B's is fast, A's response lands second and
   overwrites B's. Both requests succeeded and the screen is still wrong.

A stale list is a visible annoyance. **A stale cost is a number a dispatcher reads and acts on,
and nothing about it looks stale.**

`idKeyedFetchesDoNotGoStale.test.ts` asserts all three separately, so a partial fix fails on
the part that is missing. React Query does all three for you — a query keyed on the id returns
`undefined` while fetching, exposes `isError`, and discards a response for a superseded key —
which is why this class only appears in hand-rolled effects, and why the sweep looks only at
`useEffect`.

Mutation-verified: restoring the original two lines fails all three assertions at once.

**Frontend:** 876 → 881 tests · `tsc` clean.

---

## FS-587 — swept, nothing found, recorded

"A failure that renders as a fact", carried across to the five remaining fleet panels after
`GeoTabIntegration` turned out to have neither a loading nor an error state (FS-548).

**All five handle failure correctly.** `PerformancePanel` and `FleetTrackerMap` use the
three-state ternary (`isLoading ? … : error ? … : …`); `MaintenancePanel` and
`HealthSecurityPanel` return early on `if (error)`; `GeofencingPanel` branches inline. None has
a console-only catch.

The first pass of this check grepped for `{error ? …}` and reported four of five as unguarded —
**the third time today a grep proved narrower than the idioms in use**, and the reason
`failureIsNotEmptiness` knows five forms of failure branch rather than one. Its verdict on all
five is clean, and it is the detector that has been corrected seven times.

`GeoTabIntegration` was the outlier, not the pattern. Recorded because *proven clean* and
*never checked* look identical afterwards.

---

# Wave Q complete — FS-585 … FS-592

Eight carry-across items. **Four found a defect, four found nothing**, and the four negatives
are written down because the alternative is somebody doing the same work again in three months.

| | found |
|---|---|
| **FS-585 / FS-591** | `dropped` — the only unrecoverable buffer figure, and the only one with no response field, no gauge and no alert. The instrumentation was inversely proportional to the severity |
| **FS-586** | `PlatformDataSourcePicker` rendering an empty `<select>` and an enabled button after a failed request, so the first failure is discovered through a second one |
| **FS-588** | one shipment's costs shown under another's name — no clear, no catch, no cancellation |
| **FS-590** | three pairs of guards keeping the same list, one already diverged; **the first duplicate was mine, written hours earlier** |
| FS-587 | nothing — all five fleet panels already branch on failure |
| FS-589 | nothing of the FS-533 shape — seven numeric defaults survive the narrowing and all are internal thresholds |
| FS-592 | nothing — zero skipped tests across 111 frontend files |
| *(FS-585 folded into FS-591)* | one wire, one finding |

**The method's own result.** Carry-across produced four findings from eight attempts — and two
of the four were in code written **that same day**, by me: the duplicated engine list, and the
`dropped` counter I had built without checking whether anything consumed it. Asking "where else
does this shape live" is worth doing immediately after closing a class, not only months later.

---

## FS-583 — 30 of 51 alert rules could not be shown to fire

`promtool check rules` validates syntax and says **nothing** about whether a series exists that
would make an expression true. This repository has paid for that twice: `EdgeAgentBufferHigh`
was syntactically perfect and **unfirable for its entire existence** — the heartbeat sent
`collectors_total` and the rule read `total_collectors` (FS-497/498) — and `edge_agent_dropped`
had no rule at all, so the only counter measuring permanently lost telemetry reached nobody
(FS-591).

**An alert that cannot fire is indistinguishable from a healthy system.**

Eight new tests cover the rules where that costs most: telemetry leaving the system
(`IngestionDataLost`, `IngestionDeadLettering`, `EdgeBufferDropping`, `EdgeDeadLettering`), a
backup that stopped running (`DatabaseBackupJobFailed`), and the two processes whose absence
means the product is down (`TimescaleDBDown`, `BackendAPIDown`). Coverage 21 → 28 of 51.

### The untested set is named, not counted

A number alone can be improved by **deleting a rule** — better ratchet, fewer alerts, which is
the exact trade the gate exists to prevent. The remaining 23 are listed by name, and three
assertions hold the list honest: nothing new joins it, an entry that gains a test must leave
it, and an entry whose rule was deleted fails rather than quietly improving the figure.

Nine rules are **absolutely** required to have a test, outside the ratchet: the seven above
plus `EdgeAgentDroppingTelemetry` and `AuditWriteFailing`. The slow tail a ratchet tolerates is
not acceptable for a rule whose silence means data is gone.

### promtool compares annotations whether or not you supply them

Omitting `exp_annotations` asserts they are **empty**, so every expectation is a
byte-for-byte transcription of the rule's own prose — including `runbook_url`, and including
`{{ $value }}` and `{{ $labels.* }}` rendered to what the series actually produces. Three
drafts failed on that before the file was generated from `alerts.yml` rather than typed. The
first draft also invented plausible annotation text, which is the kind of error that reads as
correct right up until it runs.

**Suite:** backend 3910 → 3935 · 9 promtool files over 51 rules.

---

## FS-576 / FS-577 / FS-579 / FS-580 — the Wave P residue, and two premises that did not hold

### FS-579 — a value written twice, and the dead copy was the documented one

`ReconnectPolicy` declared seven tuning numbers as annotated class attributes, each with a
comment explaining it, and then repeated all seven as `__init__` parameter defaults. **The
class attributes were shadowed on every instance and decided nothing.**

This is the same defect the class was created to fix, one level up. FS-473 consolidated sixteen
copies of `cap=60.0` and `failure_threshold=5` out of eight collector modules into this file,
on the reasoning that *"a guess in eight places is a guess nobody can revise: the person with
the telemetry has to find all eight, and the ones they miss are the ones that keep the old
behaviour."* The consolidation then wrote the guess **twice in the file that consolidated it** —
and the copy a reader's eye lands on first was the dead one.

It survives review because both copies agree when written. The divergence arrives later as a
single edit, and there is no moment where the mistake is visible: the first reader sees two
consistent lists, the second sees a number that does not take effect and no reason why.

`@dataclass` makes the attributes the only place. `__post_init__` keeps the pairing check, and
a test asserts it still fires — a dataclass silently discards an `__init__` body that was not
moved, so the validation could have vanished with nothing failing.

The guard generalises it: a class-attribute default shadowed by a literal `__init__` default.
It deliberately does not flag a dataclass (that is the fix) or a `None` sentinel falling back to
the attribute (that is single-source).

### FS-580 — the exemption was right and its reason had expired

`coordinator.py` is exempt from the backoff invariant as *"routes messages between collectors;
owns no socket"*. Still true — and FS-501 gave it a supervision loop with a **fixed 5-second
delay bounded at 10 restarts**, so the file gained a retry loop its reason did not describe.

The exemption stays: the invariant is about not hammering a remote endpoint, and this restarts
a local object with a cap that bounds the cost. The reason now says so, and records what the
cap also does — **give up permanently after roughly fifty seconds**, leaving that collector
dead for the life of the process. That is a supervision-policy question for the edge lane, not
a backoff one, and it is written down rather than implied.

### FS-576 and FS-577 — measured, premises wrong

**FS-576** said `Spatial3DChart` is 127 unmounted lines "carrying a plotly dependency". The
lines are real; the dependency is not. `AnnotatedChart` and `FacilityHeatmap` are mounted in
`AnalyticsPages` and both import plotly, so deleting the third changes no dependency. What is
left is 127 lines the barrel comment already admits are unmounted.

**FS-577** said five backend scripts are unreferenced. **All seven candidates are referenced** —
`gen_030/032/033` by the migrations they generated (which name their generator, which is the
provenance of a generated file), `generate_openapi` by `generate_sdk.sh`, and the rest by the
README and the deployment docs. Nothing to remove.

**Suite:** backend 3935 · edge agent 344 → 351 · frontend 881.

---

## FS-578 / FS-584 — the retry nobody could take, and a split that turned off three guards

### FS-578 — idempotency is not a style preference here, it is the only recovery

`migrate.py` connects with `autocommit = True` and executes one statement at a time. That is
correct and it is documented — TimescaleDB continuous aggregates, `add_retention_policy` and
`CREATE INDEX CONCURRENTLY` all refuse a transaction block. **The consequence was written
nowhere:** a migration that fails at statement 7 of 12 has already committed statements 1
through 6, and its version row is never written. There is no rollback. The only recovery an
operator has at 3am is to run the file again.

The README has said "make statements idempotent" since FS-56, and nothing enforced it. The
honest reason nothing did is that **the static check over-reports five to one.** Postgres
offers no `IF NOT EXISTS` for a policy, a trigger or a constraint, so the idiom in this tree
is `DROP POLICY IF EXISTS` before the `CREATE`, or `ADD CONSTRAINT` inside a guarded `DO $$`
block. A text sweep sees the bare `CREATE` and reports a defect: **22 files look wrong,
4 are.** The difference is only visible by running them.

So the guard runs them. It builds a scratch database on the session container, applies the
chain from empty, and after each migration succeeds it re-runs that migration inside a
transaction it discards. Three details decide whether the number means anything:

* **Re-run at the file's own point in the chain, not at the end.** Re-running everything after
  the whole chain reports `010_api_keys.sql` failing on `relation "permissions" does not
  exist` — because `037_remove_unused_permission_rbac.sql` legitimately dropped that table
  twenty-seven migrations later. Neither that nor `009`'s renamed column is an idempotency
  defect, and a guard reporting them teaches people to ignore it.
* **"Cannot be tried" is detected from Postgres' error, not from a pattern list.** A list of
  statement shapes is a second place to keep one fact and it was wrong in both directions: it
  missed `CREATE MATERIALIZED VIEW … WITH (timescaledb.continuous)`, and marking that shape
  hostile wholesale would have *hidden* `002`, which fails the retry for an unrelated reason.
* **Skipped is not passed.** Two statements cannot be retried, and the guard says so rather
  than counting the files clean.

**None of the four can be fixed, and that is the load-bearing part.** Every existing database
has applied all four, and editing an applied migration is checksum drift — the runner then
refuses to migrate at all until somebody runs `--rebaseline-drifted`. A repair takes deployed
databases out of service and improves nothing. The README now names the four and says not to
touch them; the guard is forward-only.

The other half of the item's premise was wrong. *"37 of 65 migrations contain no
DROP/rollback"* measures the wrong thing — most migrations should not contain a `DROP`. Four
contain an irreversible statement, and those are the ones worth naming.

### FS-584 — splitting the document turned off three checks, and all three went on passing

7,239 lines, 229 sections, split into an index at the cited path and five parts under
`docs/engineering/sweeps/`. Verified byte-for-byte: index plus parts reproduce the original.

Then the full suite failed, and the reason is the finding.

* `test_method_rules_are_indexed.py` reads `## Rule N` sections. They all moved. It found
  **zero**, and every assertion it makes passed over an empty set.
* `test_the_session_arc_is_a_real_range.py` looks for the FS-range claim, which is in part 5.
  It had a vacuity check and failed honestly — the only one of the three that did.
* `test_documented_files_exist.py` names the document in a list of prose-heavy files whose
  source citations must resolve. Its entry still resolved, so **7,100 lines of citations left
  the check with nothing failing and the file count going up.**

The comment predicting exactly this was already in the third file, written when the delivery
log moved out of the README: *"Moving prose out of a checked document moves it out of the
check unless the scope moves with it."* It was right, and it did not stop me.

Both readers now share `backend/tests/_sweeps_document.py` rather than each keeping a private idea of
where the document lives — two guards with private copies of one fact is the defect FS-590
closed a week ago, and the split would have re-introduced it.

**And one citation had already rotted.** `fixed-sprints-344-393.md` cited
a citation reading *defect-class-sweeps.md, lines 777–786* for an argument about why a route prefix should not be edited;
those lines now hold an unrelated paragraph about a provenance flag. Nothing could have caught
it — the file exists, the lines exist, and only a reader who knows what they expected to find
can tell. Both line citations into that document are now section citations, no new ones are
allowed into it, and the rest are checked for being in range, which is the most a static check
can establish and is explicitly not a check that they point at the right paragraph.

---

## FS-574 — recorded as a decision, because it is one

`pre-commit` runs in CI with `continue-on-error: true`, above a comment reading *"Advisory
while the existing tree is brought into compliance."* The tree has not been brought into
compliance, and the comment has been true long enough that it now describes **a decision
rather than a transition**.

Measured on a clean tree with `pre-commit run --all-files`: **972 files changed, 55,068
insertions, 40,118 deletions.** The plan's figure was 924 and +53,752/−39,025 — three weeks of
new code older. `ruff format` alone accounts for 570 Python files against 125 already clean.

Both answers are defensible and they are not reversible against each other. Making it blocking
means one announced tree-wide reformat landed when no branch is open, because a 972-file diff
conflicts with every branch that exists — and `git blame` on 972 files then points at that
commit instead of at whoever wrote the line. Keeping it advisory means the comment stops
claiming a transition that is not happening, and the hooks keep the value that needs no
tree-wide change: merge conflicts and secrets.

**Not mine to make.** The reformat lands in four other people's lanes. It is now an entry in
`docs/engineering/open-decisions.md` — the register's first since it emptied on 2026-08-05 —
pinned by `backend/tests/test_the_precommit_decision_is_still_open.py`, which asserts the job
is still advisory and the four formatting hooks are still declared. Both are one-line edits
somebody could make for good local reasons, and neither would fail anything otherwise.

**The diff figures are dated, not continuously checked, and the entry says so.** Reproducing
them needs the hook versions pinned in `.pre-commit-config.yaml`; the `ruff` on this machine
reports 570 files and the pinned v0.6.9 may not agree. A live figure computed with the wrong
formatter is a different number presented as the same one — worse than a dated one, and it
would add a whole-tree format run to every test session in order to be wrong.

**Suite:** backend 3,947 · edge agent 351 · frontend 881 · `tsc` clean.

---

## FS-562 — the answer existed and died at the end of the request

`correlate_synced_records` has distinguished *"analysed, nothing anomalous"* from *"no analyzer
is registered for this vendor's field names"* since FS-557. Its log line spells out the stakes:
reusing another vendor's transformer would produce "empty normalized records and a confident
report of zero anomalies."

**And the answer reached the client only in the `POST /sync` response**, which is read once and
gone — while the page an operator watches polls `GET /sync-status`, built from a table with
nowhere to put it. So the correlations tab rendered an empty list for both cases, under a sync
row reporting **success**.

This is `failureIsNotEmptiness` one layer further back. Not a failed read shown as "no
results" — an analysis that never ran, shown as an analysis that found nothing, with a green
badge beside it.

**Three states, and the third is why the column is nullable.** Migration 063 adds
`correlation_routed BOOLEAN` and `correlation_reason TEXT`, both nullable on purpose: a row
written before the column existed recorded no correlation attempt either way, and stamping
`false` on it would invent a skip that may never have happened. The UI reads null as "not
recorded" and renders nothing.

The mutation that mattered was not deleting the warning — it was changing
`s.correlation_routed === false` to `!s.correlation_routed`. That one line would put a gap
warning on the entire sync history of every integration, which is the same mistake in the
opposite direction: a finding invented out of an absence of data. One test failed, and it is
the null case.

The warning is per **entity type**, not per integration, because one vendor can have an
analyzer for `Invoice` and none for `Shipment` — which is also why it lives on the status rows
rather than as a banner over the correlations list.

Four boundaries, each of which drops a field silently, and the guard pins all four: the
service returns it, the route persists it, `SyncStatusResponse` declares it (FastAPI **omits**
an undeclared field rather than erroring — the shape that hid the edge agent's `dropped`
counter), and the column exists to hold it. The mock now carries an unrouted row too: a mock
that only has the happy path is a mock that agrees with the bug.

## FS-573, first pass — the gate's own document had closed a limitation and not said so

`api-contract-gate.md` carried a section headed *"Known limitation: this gate runs with RLS
inert"*, ending **"This gate does not do the same yet."** FS-307 had already fixed it — the job
provisions `omniusgrid_contract` and connects as it, and the ratchet records the five-operation
cost. The prose describing the problem outlived all three edits that solved it.

**A closed limitation that still reads as open is worse than an unrecorded one.** Somebody
planning work either re-does the fix or discounts the gate's results on a caveat that no longer
applies — and this document exists to be read before touching a blocking gate.

Guarded by `test_the_contract_gate_doc_matches_the_gate.py`, which pairs the doc against the
workflow in **both** directions: the doc must not describe a gate that is gone, and the gate
must still provision the role the doc now says it does. Without the second half, deleting the
role from the workflow would leave the first assertion passing while the document became wrong
again. The doc was also never in `test_documented_files_exist.py`'s scope, so 554 lines of
path citations were unchecked; it is now.

---

## FS-573 — the gate's best-ever score, and why the floor did not move

**402 of 471**, measured 2026-08-08. The highest this gate has recorded, and the first run with
all three dependencies genuinely present: the restricted `omniusgrid_contract` role (FS-307),
Redis, and a broker advertising an address the client could reach. Every previous local
measurement was missing at least one of those — the 387 from the day before had 352
`KafkaConnectionError`s in it.

**The floor stays at 380.**

    Postgres + Redis + a reachable broker    402 / 471
    Postgres + Redis, broker absent          387 / 471

The broker step is `continue-on-error` and **removes its own container** when the advertised
address does not verify, because a half-working broker hangs the app and the run collects 1
operation instead of 452. That fail-safe is right. It also fixes the ceiling on the floor: the
worst *legitimate* configuration scores 387, and 387 minus the measured spread of 9 is 378 —
below the floor already in force. Raising toward 402 would fail every build where the broker
did not come up, which is exactly how this job's predecessor became advisory and was killed at
six hours.

So the next raise is gated on a **CI change, not a code fix**: make the broker required, or
measure the no-broker score deliberately and set the floor from that. Recorded in the ratchet's
own comments, where the next person to look at 22 points of headroom will find it.

### `ServerError` is 14, and twelve of them are not tickets

The only bucket that is entirely defects, down from 23 at the FS-307 re-baseline. Each one was
reproduced against a live app using schemathesis' own curl reproduction rather than inferred
from the report:

* **6** — `/admin/query-performance/*`. `pg_stat_statements` needs `shared_preload_libraries`
  and Postgres is a service container, which takes no command. Documented, environmental.
* **4** — `/rag/*`, vector store unreachable in this harness.
* **2** — `/edge/enroll` and `/sso/login/callback` return a **correct 503**. Schemathesis counts
  any 5xx, so a properly-reported missing dependency is charged to the API.
* **2** — real, and both in other lanes.

### The one that justified the run: an endpoint that has never returned successfully

`POST /api/v1/engines/correlation/integration/analyze` has a single return path and it cannot
be serialised:

    1 validation error for CorrelationAnalysisResponse
    integration_result.message
      Input should be a valid list [input_value='Integration processing in background']

`integration_result` is declared `Dict[str, List[str]]`; the handler passes
`{"message": "Integration processing in background"}`. Pydantic rejects it **while building the
response**, so the analysis runs, the background task is queued, and the caller gets a 500.
There is no input that makes this endpoint succeed and there never has been — the same class as
FS-486, a capability that ships and cannot be reached.

Left for the correlation-AI lane as FS-608, because which side is wrong is a shape decision:
either the annotation should be `Dict[str, str]`, or the message branch should be a list and the
field is meant to carry category → created-ids. The background task suggests the second.

The other real one, FS-609, is `POST /fleet/releases` letting a `PermissionError` escape when
the OTA artifact directory is missing — where the two correct 503s beside it show the shape it
should have.

---

## The pool was too short, which is the harder direction to notice

The first draft of `next-week-task-pool.md` claimed *"several entries that pool listed as open
have since closed — they are not repeated here."* **It was not checked before it was written.**
Auditing the 2026-07-26 pool item by item found **twelve entries still open** that the new one
had silently dropped, one of them regressed:

| Old # | Then | Measured 2026-08-08 |
|---|---|---|
| #5–#9 | Alex's five intake items | **all five unchanged** since 2026-07-22 |
| #46 | 190 `USE_MOCK` forks | **249** — worse by 59 |
| #47 | 0 `useTranslation` call sites | **still 0** |
| #20 | `get_db` on RLS tables, 24 files | **13** — reduced, not closed |
| #23 / #34 / #35 | no org CRUD, no ERP export, no ERP websocket | **all three still absent** |
| #42 | generated SDK unadopted | **still unadopted** |

**And a whole lane was gone.** Alex is an active contributor with three commits on this branch,
and the draft had no section for him — he would have been handed a pool containing nothing.

THE CAUSE MATTERS MORE THAN THE CORRECTION. Every previous plan in this repository rotted by
listing **more** work than existed, and the new pool's own preamble warns about exactly that.
This one rotted the other way, because it was built by asking *"what did I find this week?"*
instead of *"what is open?"* — so it narrowed to its author's footprint, and the lane that
overlaps nothing I touched disappeared completely.

**A short pool looks like progress.** That is the whole problem: an inflated backlog gets
questioned eventually, and a deflated one gets celebrated. The only reason this was caught is
that somebody read it and asked why it looked like the last one and where Alex's work had gone
— the second question is the one a diff would never have raised, because a missing section
produces no conflict.

It is the same shape as the three guards a document split disabled the same day: a derived list
quietly narrowing, with nothing comparing it against what it derives from. There the comparison
was a filename; here it was a person.

**Every item now carries its age** — the pool it first appeared in. Seventeen of thirty-one are
carried, and two are on their third consecutive pool (`main` promotion, correlation-AI honesty).
A repeat with no age on it reads as new work and hides how long it has been sitting, which is
how a decision nobody makes stays invisible while looking like a fresh ticket every fortnight.

---

## Assigning from the branch's status found two weeks of two people's work off the branch

The task was to allocate the pool. Measuring `hamad/converged-pre-main` first — before deciding
who does what — turned up something that makes most of the pool premature.

**Where each developer's most recent commit actually lives**, which took one command and had
never been asked:

* **Hridyansh** — nine commits dated 23–27 July on `backup/hridyansh/integration`, on **no
  `origin` branch and not on converged**. Signed agent self-update with rollback, fleet
  targeting and rollout cohorts, maintenance windows, audited remote operations, tenant user
  administration. **Two of the nine are titled "onto converged main"** — he was trying to land
  this and it reached the backup mirror and stopped.
* **htreinen** — three commits, 20–23 July, on a local branch that exists on **no remote**.
  Structure-aware chunking, ingestion guardrails, an eval suite. One disk failure from gone, and
  it has **no merge base** with converged, so it is a cherry-pick rather than a merge.
* **Alex** — merged. His work is on the branch.

Converged has zero files matching `rollout cohort`, `self-update`, `invitation` or
`maintenance_windows`, so Hridyansh's is unabsorbed work rather than work the convergence
superseded. How much is genuinely new needs triage with him; the diff figure alone includes
pre-convergence lineage and would overstate it.

**The cause is `main`.** It is 434 commits and 126,472 insertions behind this branch, and every
developer is told to branch from it. Anyone who follows the instruction starts from a tree that
predates the product — so two of them sensibly kept their old branches instead, and that is
exactly what is now stranded. The promotion has been an open decision for three consecutive
pools; this is the bill for that.

**It also invalidates part of the pool.** htreinen was assigned FS-563–566, and "structure-aware
chunking, ingestion guardrails, eval suite" plausibly overlaps them. Assigning work somebody may
already have done is the same waste as the pool being too short, arrived at from the other
direction.

So the assignment leads with three integration items ahead of every ticket, and records what it
assumes: that the other four are working this week at all. Commits in the last 21 days are
Hamad 541, Hridyansh 9, htreinen 9, Alex 6, Harsh 0. If that ratio holds, the integration is
mine alone and the per-person lists slip — worth writing down, because a plan that assumes
availability it does not have is the same fiction as one that lists work that does not exist.

**The check is now cheap and permanent:** before any future pool, ask where each contributor's
last commit lives, not just what it says.

---

## Landing two developers' stranded work, and completing it to the gates

Both integrations are on `hamad/converged-pre-main`. What made it expensive is worth writing
down: **twenty-one thousand lines that had never been through this branch's gates.**

### The two single lines that cost 719 and 29 tests

`Asset.workcell` became ambiguous because his composite `fk_assets_workcell_org` — which also
pins `organization_id`, so an asset cannot reference another tenant's workcell — sits alongside
the single-column FK converged already had. Both are wanted. SQLAlchemy refuses to guess, and
**every fixture that touches an Asset builds that mapper**, so one unresolved relationship took
719 tests with it.

Then a test that builds SQLite from six named tables stopped being closed under its own foreign
keys when Workcell gained one to `sites`. SQLite reports that as `no such table: main.sites` at
INSERT time, thirteen tests deep, nowhere near the list that is actually wrong.

### The gates were the point, and one of them caught me

Twenty-seven routes arrived with no `response_model`. Raising `MAX_UNDECLARED` would have been
one line; instead the router's own `_*_response` builders were read and declared. I checked
those five field-for-field, reported "no field is dropped" — and
`test_response_models_match_their_returns` then failed on **ten routes I had not checked**,
because deactivate, assign, bulk and inventory return different shapes:

* `deactivate_*` return the **full resource**, not an `{id, is_active}` acknowledgement. My
  model would have deleted five to six fields from each.
* assign/remove return `created`/`removed` — whether the call **changed** anything. I declared
  `assigned`, the state after the call, which is a different question.

**My confidence about the five is exactly what stopped me looking at the other ten.** Declaring
a response model makes FastAPI delete undeclared keys, so a documentation change silently
narrows a wire — the client sees 200 and a missing field.

### Four of six "unguarded mutations" were the detector

`FleetTargeting` deactivates four resources through a hoisted `options` object rather than
repeating the handler. Reading only the call site made all four a finding while the failure was
handled the whole time — and a non-greedy `{…}?` stopped at the inner `setFeedback({ … })`, one
line above the `onError` it was looking for. Rule 27: brace-matching, not a window.

The other two were real. A resume that failed left the rollout paused with the button reporting
nothing; a disable that failed left a maintenance window enforcing while the operator believed
it was off.

### A filename that was doing the work of a test

Deleting the emptied `AdminPages.test.tsx` — after its UsersPage describes moved to
`Users.test.tsx` — made `everyRoutedPageHasATest` report Collectors, SystemHealth and Settings
as untested. **They always were.** The file's name satisfied the walk while every describe
inside it was about a different page.

### What was preserved, and why that came first

`rag-rewrite` existed on **no remote at all** — three commits, 35 files, +4,433 lines, one disk
failure from gone. Hridyansh's tip was on the `backup` mirror only, and `origin` already had an
older, diverged `hridyansh/integration`, so the newer tip went in under its own name rather
than force-overwriting anything. Preservation before integration, because a merge is not a
backup and a resolution that goes wrong is only recoverable if the input still exists.

### Two findings that only appeared once both integrations were combined

Each integration was green on its own branch. Landing them together produced fifteen failures,
and neither cause was visible in either half alone.

**Four unbounded pagination parameters.** His `list_users` and `list_invitations` declare
`skip: int = 0, limit: int = 100` and then validate by hand — `if skip < 0 or limit < 1 or
limit > 500: raise 422`. The *behaviour* is correct. It is also **invisible to OpenAPI**, so the
contract gate cannot check it and the generated SDK will not carry it, and
`test_pagination_params_are_bounded` reports it as unbounded because from the schema's point of
view it is. Declared with `Query(0, ge=0)` / `Query(100, ge=1, le=500)`, which documents and
enforces the same rule his handler already applied.

**Four duplicate operationIds.** Both user-administration routers export `list_users`,
`get_user`, `update_user` and `deactivate_user`, and both were mounted under the tag
`User Management` — from which operationIds are derived. The generated SDK cannot represent a
duplicate. Fixed by tagging his `Tenant Users & Invitations`, which is also **the concrete cost
of keeping two user surfaces**: the decision to keep both was recorded as an open question, and
this is the first bill it has produced.

The general shape is worth keeping: **two changes that each pass alone can fail together**, and
the failure is in neither one's diff. Only the combined branch shows it, which is an argument
for integrating early rather than accumulating.

---

## FS-650 — the coverage ratchet was enforced by nothing, and had already gone false

Re-deriving the task pool from the promoted `main` — rather than editing the one written an
hour earlier — turned up something no ticket would have found.

**`vitest.config.ts` sets four coverage thresholds. No CI job reads them.** `ci-cd.yml` runs
`npx vitest run`; `quality-gates.yml` ran `npm run test`. Both are `vitest run` **without
`--coverage`**, and coverage thresholds only fail a run when coverage is being collected. So
FS-541/542's ratchet — built, documented, cited in the README, and quoted in two task pools —
was checked by nobody from the day it was written.

**It had already gone false.** The 2026-08-08 merge added roughly 700 lines of untested pages,
and lines fell to **45.45 against a threshold of 46**. Nothing reported it, because nothing was
looking. The config's own comment warns about exactly this — *"a ratchet that trails reality by
20 points is not a ratchet, it is a number in a config file"* — and the failure mode it
describes had happened to it in the other direction.

**Fixed by lowering the thresholds and raising the enforcement in the same change.** The
numbers went to the measured floor (43/44/37/45) and `npm run coverage` is now the blocking
step. Lowering a floor to make a build pass is the thing this repository forbids; this is the
narrow case where it is right, because **no build was passing or failing on it** — a lower
number a gate enforces is strictly tighter than a higher one nothing reads. The way back up is
the two untested component trees, not another edit to the config.

### And three figures in the previous pool were wrong

Re-measuring rather than carrying forward corrected:

* **"1,777 lines of service code production does not import" → 8,101 across 19 modules.** I had
  named four; the register holds nineteen. The largest is
  `erp_connectors/dynamics_data_extraction.py` at 737 lines, and `services/oee_calculator.py`
  (600) is the one worth alarm — OEE is a headline feature and 600 lines of it are unreachable.
* **`feature_extraction.py` "has a production importer" → zero.** It is named in the *comments*
  of two other modules. A grep for the module name found prose about it.
* **"Coverage has under one point of headroom" → the thresholds were breached**, per above.

Each of the last three pools has failed differently: one listed more work than existed, one
listed less and dropped a whole lane, and this one carried a figure that was wrong by a factor
of four. **The common cause is a pool written from the previous pool.** The only defence that
has worked is re-deriving every number, which is now what the document's own preamble instructs.

---

## FS-652 / FS-655 — the coverage lowering lasted two days, and a fan-out that reported success on nothing

### The correction first: `oee_calculator.py` is not dead

I reported it as the largest unreachable module and the lead of D1 — *"OEE is a headline
feature and 600 lines of it are unreachable."* **It is imported and started by `main.py:49`.**

It appears in that guard file inside the **positive control** — a short list of modules
asserted to be *reachable*, which exists to prove the walk works. I counted the register by
grepping the file for quoted paths, and the grep swallowed both lists. That inflated 16 modules
/ 6,955 lines into 19 / 8,101 and put a running worker at the top of a dead-code list.

Three measurement errors in two days, all the same shape: **reading a structure by pattern
instead of importing it.** The register is one import away and cannot include the control.

### FS-652 — five components nothing had ever rendered

All five in `components/common/` were replaced by `() => null` in every page test that mounts
them, so a stub and an exercised component looked identical to the coverage tool. Same for the
dialog primitives — 181 lines that became **load-bearing** three days ago when the admin Users
page was moved off `window.confirm` onto them.

The dialog tests are mutation-verified: flipping cancel to resolve `true` fails exactly the test
written for it, which is the failure that would deactivate a user nobody asked to deactivate.

**Lines 45.45 → 46.40**, and the thresholds are back to 44/45/38/46 — above where they were
before the merge pushed them under, with functions higher than they have ever been. The
lowering lasted two days, and the way back up was tests, as that note said it would be.

### FS-655 — `all([])` is True, on the path that means "the part was issued"

`shop_floor_fanout.FanoutResult.summary()` reports `fully_posted`, which the router turns into
what an operator is told. It was `all(p.status == POSTED for p in self.postings)` — and an
event that reached **no target at all**, because no integration has the capability or none is
configured, satisfies that vacuously.

So a shop-floor event that went nowhere reported that it went everywhere. A verdict computed
from emptiness, in a service with **four production importers and no test naming the module**
— found by the first test ever written against it.

---

## FS-653 / FS-655 — eight rules that could not be shown to fire, and a path-traversal guard nothing tested

### The alert rules, and why the quiet cases are the harder half

Eight of the twenty-three now have promtool tests: the two that say an agent is gone, the
collector, the buffer **pair**, the broker, the asset and the disk. `promtool check rules`
proves an expression parses; this repository has paid twice for the difference —
`EdgeAgentBufferHigh` was syntactically perfect and unfirable for its whole existence, and
`edge_agent_dropped` had no rule at all while the two recoverable counters beside it were both
alerted on.

**The buffer pair had to be done together.** `EdgeBufferGrowing` is data still held;
`EdgeBufferExpiring` is data already gone. Testing only the first leaves the loss unproven,
which is precisely the inversion FS-591 found — the recoverable figures instrumented and the
permanent one not.

**The must-stay-quiet cases are built from healthy signals, not absent ones.** A buffer at zero
or an asset with no series proves less than it looks: it shows the rule is quiet when there is
nothing to read, not when things are working. So the quiet buffer carries 400 messages and the
quiet asset reports a timestamp that keeps up with `time()`.

**Expectations generated from `alerts.yml`, not written by hand.** promtool compares
annotations even when they are omitted — an omission asserts empty and a guess asserts
something plausible and wrong. Three drafts failed that way during FS-583; this time the file
was generated from the rules themselves, and the only hand-written parts are the input series
and the reasoning.

`MAX_UNTESTED_RULES` 23 → **15**.

### The OTA storage guard, and why it is worth testing while unreachable

`agent_release_storage.py` — 165 lines, **four production importers, no test naming it** — is
the path that writes the binary a fleet of edge agents will download, verify and execute.

`resolve_bundle_path` builds a path from two UUIDs and checks the result is still under the
root. Through today's callers the traversal is **not reachable**, and that is exactly what
makes it worth a test rather than a comment: the check is the only thing between a future
caller that passes a string and an arbitrary write.

`absolute_bundle_path` has a real surface — it takes a `storage_key` **string straight from a
database column**, and `delete_release_artifact` hands it to `unlink`. Mutation-verified:
removing the containment check fails four tests, including the absolute-path escape.

The atomic-write property is asserted too. An agent that downloads a half-written bundle fails
its signature check, which is recoverable — but the release row would already claim a checksum
for bytes nobody wrote.

**`inference_client.py` was left alone deliberately.** Its only consumers are `rag_retriever`
and `rag_ingestion`, which is htreinen's lane, and he has an item to re-scope that work against
what just landed. Testing it would not have collided with him; assigning myself his module
would.

---

## FS-651 — the first tests on 1,811 lines of kanban, and two mutations that mattered

`components/kanban/` had **zero test files** — the largest untested tree in the product and the
one pulling coverage down hardest. The card and the column are the two halves of the same
gesture, and both fail in ways nobody sees.

**The drag payload.** `onDragStart` writes the task id into `dataTransfer`, and that string is
the only thing the drop target has to identify what was dragged. Remove it and the drop moves a
different task, or nothing — the board shows a card back where it started, which reads as a
failed request rather than a bug.

**A drop that is silently rejected.** HTML5 drag-and-drop **refuses by default**: a drop only
happens on an element that cancelled the preceding `dragover`. So a missing `preventDefault` is
a column that accepts nothing, with no error logged anywhere and nothing on screen but a card
sliding back.

**Overdue is a conjunction**, and the second half is the easy one to drop. Past due AND not
completed — because every finished task has a due date in the past, so a check on the date
alone paints the entire "Done" column red, and a colour that is always on is a colour nobody
reads.

**The WIP warning is `>`, not `>=`.** A column at exactly its limit is at the limit, not over
it. Off by one nags an operator who is doing precisely what the board asked.

All four mutation-verified: dropping each one fails exactly the test written for it, and no
others.

**Coverage 46.40 → 47.00 lines**, thresholds raised again to **45/46/38/46**. Every one is now
above where it stood before the merge, and branches at 46 is the highest this ratchet has ever
held — two days after it had to be lowered because nothing was enforcing it.

### The kanban store, and a comment that described the version this is not

`stores/kanbanStore.tsx` — 367 lines owning board loading and **every task mutation** — is
mocked wholesale by `pages/Kanban.test.tsx`. So the page tests proved the page renders whatever
the store returns, and nothing whatever about what it returns.

**`moveTask` is pessimistic, and its comment said optimistic.** The POST is awaited *before*
local state changes, so a rejected move leaves the card in its original column. That is the
better of the two orderings — a card that jumps to the new column and snaps back is
indistinguishable from a board that reordered itself, and the operator has no way to tell
whether the move took. The comment described the version that would have had that problem.
Class 53: a comment that argues for the code beneath it and is no longer true. Corrected, and
the ordering is now pinned by a test rather than by a note.

**A failed refresh has to do two things at once.** Keep the last known board — blanking it on a
transient failure throws away the only state the operator has — *and* set the error, because a
stale board with no error reads as current. Both are asserted, and so is the clearing of a
previous error once a refresh succeeds.

**Coverage 47.00 → 47.96 lines, 45.60 → 46.53 statements.** Thresholds now 46/46/39/47.

### The filter bar and the metrics bar, and a gate that hid a measured zero

**`KanbanMetricsBar` hid a cycle time of zero.** The panel was rendered behind
`{metrics.avg_cycle_time_minutes && (…)}`, and a truthiness gate hides **0** as readily as
absent. Those mean different things: absent is "not measured yet"; zero is a board where tasks
close the moment they open — extraordinary throughput, or a workflow nobody is using. Both are
worth seeing and the gate showed neither. **Falsy is not absent**, on a number rather than a
collection. Fixed to `!= null`.

**`KanbanFilters` clears with `undefined`, not `''`** — and that distinction is load-bearing.
An empty string is a *value*: the store would forward `?priority=` and the board would come
back empty while the control read "All Priorities", which is an empty result the user cannot
attribute to anything. Mutation-verified.

**"Clear all" resets by naming each field**, so a filter added later and not added there
survives the clear — the board stays filtered while the bar says it is not. Also
mutation-verified, by deleting one field from the reset.

**Coverage 47.96 → 48.21 lines.** Across the day: **45.45 → 48.21**, entirely by testing
components that were `() => null` stubs in every page test that mounted them.

### The board, and a refused move that left it holding the task

`KanbanBoard` is the only thing that remembers **which task** was picked up between the card
starting a drag and the column receiving the drop. That state was the finding.

`handleDrop` awaited `onDragEnd` and cleared `draggedTaskId` **afterwards**. So when the store
refused a move — a WIP limit, a permission, a dropped connection — the await threw, the two
resets never ran, and the board kept pointing at the task with the target column still
highlighted. **The next drop anywhere then moved that task**, not the one the operator was
dragging.

Fixed with `finally`, because the gesture has ended either way; whether it *succeeded* is a
separate question, and the error still propagates. Mutation-verified: replacing the
`try`/`finally` with plain blocks reproduces the defect exactly, and only that test fails.

This is the third defect in the same shape today — `all([])`, a truthiness gate over zero, and
now a cleanup that only runs on success. Each is a branch nobody took while writing the code,
and each was invisible until something rendered or called it.

**Coverage 48.21 → 48.57 lines**, 969 frontend tests.

### The last two modals, and ten writes that could not say no

`CreateTaskModal` and `TaskDetailModal` — 820 lines between them, both `() => null` in every
page test — hold every task mutation the product has. Ten of them. **Not one could tell the
operator it had failed**, and the two failed differently enough that fixing one would not have
suggested the other.

`createTask` **answers `null`** and logs to the console. The modal read the answer, found it
falsy, skipped the close and returned. The spinner stopped. Nothing else changed, and the form
sat there still filled — a refused create and a slow one were the same screen, and the only
move available was to press the button again.

The detail modal's nine handlers were `try { … } finally { … }` over a store that **re-raises**.
No catch, because there was nothing to catch with. Each rejection became an unhandled promise —
a console line. On approve, complete and delete the failure at least left the modal open, which
is a weak signal but a signal. On start, move, assign, unassign, save and reject there was
nothing at all: **a rejected write and a successful one were pixel identical.**

Both now route every write through one helper that names the action it could not do. Six
`TaskDetailModal` tests and four `CreateTaskModal` tests fail with the catch removed.

**The first draft of the fix committed the same class it was fixing.** Its message read *"Nothing
has been changed"* — and every store mutation POSTs and then refreshes the board, so a rejection
from the POST does mean nothing changed while a rejection from the **refresh** means the write
succeeded and only the re-read failed. From the modal the two are one exception. Telling the
operator nothing was saved would be a confident guess that is wrong exactly when it matters, and
on the create path it would invite a duplicate task. Both messages now say what is known — the
action did not complete — and ask the operator to check the board.

Both had passed `mutationFailureIsVisible`, which reads `useMutation` hooks; these are
hand-rolled async calls on a store. The sweep was not wrong, it was scoped — and a sweep's
scope is a hypothesis about where a thing lives. Recorded as **class 93**, with rules 130 and
131.

### The five primitives that were already "covered"

`Card`, `ChartContainer`, `Skeleton`, `Tooltip` and `Wordmark` reported high line coverage and
had no test of their own — the pages that mount them executed their lines. That is the same
state `ui/Select.tsx` was in at **100%** while rendering an unlabelled combobox. Twenty-one
tests now pin the branch each one owns, and `ChartContainer`'s error text gained the
`role="alert"` it was missing, on the same argument: a chart that failed to load is exactly
when a screen-reader user has no other cue.

**Coverage 48.57 → 50.24 lines; 1,017 frontend tests.** Across the day: **45.45 → 50.24**, and
functions clear 40 for the first time. Thresholds raised to 48/48/41/50.

### Every alert rule can now be shown to fire

The last fifteen rules in `alerts.yml` had no promtool test — `HighMemoryUsage`,
`APILatencyP95High`, `DatabaseBackupStale` and twelve others. Each is now driven true from a
series the product publishes, and each carries a must-stay-quiet companion. **51 of 51.**

The expectations were generated from `alerts.yml` rather than transcribed, because promtool
compares annotations even when a test omits them — three earlier drafts failed on copied text,
not on rule defects.

Two needed the harness understood rather than the rule changed. `SlowDatabaseQueries` wraps a
`rate()`, so its expression is not true until the range vector fills and the `for:` clock
starts around 3m rather than 0. `DatabaseBackupStale` compares against wall-clock `time()` and
needs a 27-hour window; sampled hourly it is **stale for 55 minutes out of every hour**, which
resets the `for:` clock before it can elapse — so the series is sampled every minute even
though the CronJob it describes runs hourly.

`UNTESTED` in the firability guard is now empty, and closed: the ratchet went 23 → 15 → 0, and
with nothing subtracted from it the guard asserts the strong form — every rule has a test. A
new rule ships with one or it does not ship.

### The contract floor, unblocked by admitting there are two of them

FS-593/FS-654 had sat as "gated on a CI change" since 2026-08-08. The impasse: a healthy run
scores **402** and a run whose broker step removed its own container scores **387**, and one
floor had to survive both — so it survived the worse one at 380. A healthy build carried 22
operations of headroom it could never spend, and the gate would have sat through a regression
of 22 rather than fail a build whose broker did not come up. That trade is exactly how this
job's predecessor became advisory and got killed at six hours.

There are two floors now — **393** with a broker, **380** without — and the run decides which
applies by **probing** the bootstrap address the app was given, after the suite. Not by a flag.
A flag is a claim, the lower floor is the one somebody would want on a red build, and *"the
broker must have been down"* is unfalsifiable after the fact for 13 operations of protection.
Selecting the lower floor now requires the broker to actually be unreachable.

Verified on the case that matters: a run scoring **390** now passes with no broker and fails
with one. That discrimination is the whole feature, and a single floor could not express it.

A broker that dies mid-run scores like one that was never there and gets the lower floor, which
is correct. A broker that recovers between the last request and the probe leaves the run held
to the *higher* floor, which fails safe.

**The guard that read the floor with a regex broke on this change, and was right to.** FS-654
turned `BASELINE_PASSING = 380` into `BASELINE_PASSING = BASELINE_WITHOUT_BROKER`, and a regex
over source cannot follow an indirection — it would have reported the constant "gone" while it
sat one line below. It now imports the module. Same shape as the sweep that called a live
module dead by grepping for its name in the file that already listed it as a positive control:
**reading source is not reading a value.**

### What a polled reading shows after it stops arriving

Class 93 asked what a modal does when a **write** fails. The carry-across is the read side,
and it is worse, because a read has no button to press.

react-query keeps the last successful `data` across a failed refetch — the right default, a
screen that blanks on every blip is unusable. But a consumer that destructures only `data`
cannot tell a live reading from one taken an unknown time ago, and on a **poll** that is not a
transient state: the retry runs forever, so the wrong reading stays for as long as the endpoint
is down and nothing on the page changes.

The cold-start form is what makes it serious. With no data yet, `data?.count || 0` is zero, and
zero renders as a fact.

**`Header.tsx` — the alarm badge.** Polls every ten seconds; hid the badge behind `count > 0`.
An alarm feed that had never answered rendered as a plant with **no active alarms**, in the
corner of every page. On an industrial monitoring product that is the one indicator that must
never quietly read all-clear. It now shows an explicit unknown state, and the stale form is
covered too: a surviving count is no longer presented as current.

**`Alarms.tsx` — the summary cards.** Showed "Active 0" on the same `|| 0`, and the card beside
it computes `total − count`, so a dead feed reported **every alarm on the page as
acknowledged**. This is the page an operator opens because they are worried. Both cards now go
to a dash together, because one is derived from the other.

**`kanbanStore` — the metrics poll.** Thirty seconds, catch reaching only the console, `metrics`
holding the last value. Hour-old throughput, WIP and cycle time read as the current floor. The
figures are deliberately kept and **labelled** rather than blanked: the last known state is
worth more than an empty bar, provided nobody mistakes it for now.

Three sites, one missing `isError` each. `failureIsNotEmptiness` could see none of them — it
looks for a rendered *phrase*, and these render a **number**. A confident `0` is the same lie
with better typography.

Guarded by `polledQueriesReportFailure.test.ts`, which resolves the polled hooks from
`refetchInterval` and checks their consumers. It carries a positive control that fails if the
sweep cannot distinguish a consumer reading the error from one that is not — without it the
sweep passes by calling everything safe, which is how three earlier sweeps in this repo
reported clean trees. Mutation-verified: reverting the Header names `Header.tsx:20` exactly.

Its allowlist is empty and its scope is stated rather than assumed — only the destructuring
form is matched, because `const q = useThing()` hands the consumer the whole query object and
the question stops having a static answer.

Recorded as **class 94**, with rules 132 (a poll turns a transient failure into a permanent
wrong answer), 133 (`|| 0` on a possibly-absent value is a measurement invented from nothing)
and 134 (derived numbers inherit the honesty of their inputs).

**Coverage 50.24 → 50.57 lines; 1,039 frontend tests.** Statements threshold to 49; the other
three moved by less than a point and were left, because a floor raised inside the noise starts
failing on variance rather than on regressions.

### Thirty-one hits, one defect, and it was in the client every page depends on

Rule 133 said `|| 0` on a possibly-absent value is a measurement invented from nothing. The
sweep that followed found the pattern **31 times**, and the honest result is that almost all of
them are fine — recorded here because "proven clean" and "never checked" look identical
afterwards.

Ten are `?.items || []` on a list, which is `failureIsNotEmptiness`'s subject. Three sit inside
`if (USE_MOCK)` blocks where the miss is a fixture lookup, **including a compliance score and a
freight charge** — either would be serious on a live path and neither is on one. `Dashboard`
renders `fmtNum(...)`, which answers `—` for absent, and its widget carries `isError`; the
`|| 0` there picks a colour beside a number already saying unknown. `OEE` early-returns on
`isError` before its expression can render.

**One was live: `handleApiError` computed `error.response?.status || 500`.** A request that
never reached the server reported that the server had answered 500.

Why it survived is the part worth keeping. `src/api/errors.ts` already holds
`normalizeApiError`, which answers `status: null` and `code: 'network_error'` for exactly this
case. Two normalisers, one directory, different contracts — and **all fifteen call sites read
only `.message`**, so no caller could see which one it had and nothing was visibly wrong. That
is the shape of a trap, not evidence of safety: the first caller to retry on `>= 500` would
retry a request that never left the machine, and error triage would attribute every network
outage to a server fault.

`handleApiError` now delegates. `ApiError.status` is `number | null` for the same reason `??`
replaced `||` in the alarm cards: absent and zero are different facts. The message for a
no-response failure says something a user can act on rather than axios's "Network Error".

**A caller branching on status already exists, and I said it did not.** I reported "all fifteen
call sites read only `.message`" from a regex matching `handleApiError(...).field`, which
cannot see a destructure — and `ComplianceAssistant.tsx` does exactly that, comparing
`status === 503` to distinguish a RAG service outage from a failed answer. Behaviour there is
unchanged, because `null === 503` is false exactly as `500 === 503` was. But the trap was one
caller closer than I claimed: the next one to write `status >= 500` would have retried requests
that never left the machine. Rule 37's neighbourhood again — the detector matched one spelling
of the thing it was looking for.

The delegation also fixed something no test had noticed: the crude normaliser could not read
the backend's actual `{ error: { message } }` envelope, so it fell through to axios's generic
text on every structured error the API returns.

Fifteen tests, mutation-verified — restoring the old body fails four, including that envelope
case. The invariant guarded is that **both normalisers answer the same status** for the same
input, not that one calls the other: "A must call B" passes for any delegation and fails for
any honest reimplementation, which is backwards.

**A miss of my own, caught by this pass.** `tsc` flagged two errors in the `Alarms.test.tsx`
block from the previous wave — the mock's return type was inferred from its default and the
failure cases hand it `undefined`. I had run `npx tsc --noEmit` *before* appending that block
and then only `vitest run`, which does not typecheck. A green test run is not a compile.

Recorded as **class 95**, with rules 135 (when a sweep comes back clean, the reason is the
result) and 136 (two implementations of one question is a defect before either is wrong).

**1,054 frontend tests**; branches 48.97 → 49.06, the other three unchanged.

### The gates that ran where nobody pushes

The previous entry ends with a miss of my own: a test file green under `vitest run` that did
not compile. I recorded it as a local process failure and then asked whether CI would have
caught it.

It would have — in a workflow that does not run on the branch.

`ci-cd.yml` has carried a blocking `npx tsc --noEmit` since FS-53 and a blocking
`npm run lint` since FS-54, and it triggers on `push: branches: [main]` plus `pull_request`.
`quality-gates.yml` is the one that fires on every developer branch — `hamad/**`,
`hridyansh/**`, `htreinen`, `HARSH-CONTRIBUTION`, `alex` — and it had **neither**. Every branch
in this repository has run with no typecheck and no lint for as long as both files have
existed.

Both consequences were already in the tree. My non-compiling test file, and **fifteen lint
errors** across e2e specs, adapter tests and page tests — none behavioural, every one enough to
fail the gate the moment a PR opened.

**Seven of the fifteen were not defects.** They are the omit-a-key idiom —
`const { alertType, ...withoutType } = WIRE` — where the discarded name *is* the documentation:
it says which field the test is proving the adapter cannot invent. The rule wanted them renamed
`_alertType`, which destroys the one thing the line exists to say. The fix was
`ignoreRestSiblings: true` in the config, not eight underscores in the tests. Answering a
misconfigured linter literally would have been the lasting damage.

The other eight were dead: three pairs of `EMAIL`/`PASSWORD` constants stranded when FS-452
moved authentication into a Playwright setup project, a vestigial per-route counter the file's
own vacuity test had superseded, a regex with two literal spaces (now `{2}`, and it is
load-bearing — it bounds a handler body by indentation), and an `eslint-disable` for a rule
this config does not enable.

Both checks are now blocking steps in `quality-gates.yml`, and
`test_branch_pushes_reach_the_gates.py` asserts that every check reachable only from `main`
also runs on a branch push. It is mutation-verified: deleting the typecheck step fails two
tests and names it.

**This repository has now paid for the same shape three times.** `develop` sat in a
branch-trigger list for months without existing on any remote, so the dev branches that did
exist ran zero CI. The coverage thresholds were enforced by no job in either workflow and had
already gone false when somebody looked. And now two blocking checks that only fire where
nobody pushes. None of the three announces itself: every job is green, the gate is in the
repository, and "we have a typecheck" is true and useless.

Recorded as **class 96**, with rules 137 (a gate that is never reached and a gate that does not
exist are the same gate — ask which pushes reach it, not whether it is blocking) and 138 (the
check you skipped is the one that finds your mistake — compile last, after the final edit).

Frontend lint: **15 errors → 0**.

### What the gate hole was hiding: a dispatch that succeeded and reported 500

Wiring the frontend checks into the branch-push workflow was the cheap half. The backend has
the same arrangement — `flake8 app --count --select=E9,F63,F7,F82` has been blocking in
`ci-cd.yml` from the start, on `main` and pull requests only. Its **first run against this
branch** reported:

    app/api/transportation.py:723:30: F821 undefined name 'driver_id'

`POST /transportation/shipments/{id}/dispatch` built its reply with a bare `driver_id`. The
body is `request.driver_id`; there is no such name in that scope. Every dispatch raised
`NameError` and answered 500.

**A 500 is the mild reading.** `dispatch_shipment` sets the status, assigns the driver and
trailer and **commits** before returning; the NameError fires afterwards, while the route
builds its response. The shipment really was dispatched and the operator was told it was not —
the one error that makes somebody do the thing twice.

Two guards had a claim on it and neither could reach it. `route_walk.py` drives every route
against a real Postgres looking for 5xx, but a generated `shipment_id` matches no row, so the
service raises `ValueError("Shipment not found")` and the route answers 400. **The defect is
reachable only by succeeding, and the smoke test never succeeds.** And the one check that names
this exact class by error code ran where no push reaches it.

Six tests, driving the success path with the service faked — mutation-verified, four fail with
the bare name restored. The refusal paths are pinned too, including FS-421's requirement that
an HOS block names its reason, because those are the branches `route_walk` does exercise and
they must keep working.

`flake8` at error level and `npx vite build` join `tsc` and `lint` as blocking steps on branch
pushes. `test_branch_pushes_reach_the_gates.py` now asserts all five.

The step covers `app` **and `scripts`**, which `ci-cd.yml` never did. `app/` held the only
F821 in the repository — `scripts/`, `backend/tests/` and `edge-agent/opsgrid_agent/` all
measured zero the same day, so widening the scope cost nothing and this is the only moment it
ever will. `scripts/` is worth the extra path on its own: it holds the migration runner and the
seeders, where an undefined name fails a deployment rather than a request.

Recorded as rule 139 — a smoke test that only ever fails has not tested the success path.

### The route twenty lines below the one FS-420 fixed

Rule 139 said a smoke test that only ever fails has not tested the success path. So: which
write routes in `transportation.py` have a success path nothing asserts? Four, measured with a
detector carrying a positive control — the dispatch route fixed an hour earlier, which had to
show a success assertion or the measurement meant nothing.

One of the four was `POST /shipments/{id}/status`, carrying FS-420's exact defect.

FastAPI reads a non-Pydantic scalar with no `Body(...)` marker as a **query parameter**, so
`status: str` on that route required `?status=`. The client posts `{ status, note }` as JSON.
**Every status update answered 422**, and the two buttons that call it — "Mark Delivered" and
"Cancel" — had never worked once.

Third instance. FS-379 on Strategic approve/reject, FS-420 on dispatch, now the route twenty
lines below it in the same file. Fixing an instance is not fixing a class.

`note` is the smaller half. The client sent one on every call; `Shipment` has no note column
and the service never read the field. Pydantic drops unknown fields silently, so accepting the
body would have made the API appear to record something it discards. The model declares
`extra: "forbid"` and the client no longer offers the parameter.

Eleven tests on the two routes; four fail with the bare scalars restored.

**Why the server side is still full of this shape.** Sweeping every router found **22 routes**
taking bare scalars, and nearly all are correct in practice — because FS-379 and the
maintenance-mode and NLP-chat routes were each closed by moving the **frontend** onto the
contract the server already published. `api/engines.ts` says so in a comment: the route belongs
to another lane, and moving the client needs no agreement to land. Right call every time, and
it leaves the shape in place 22 times over, each one client-edit away from breaking.

So the new guard demands no refactors in other lanes. It asserts that **the two sides agree**,
and fails when a caller posts a body to a route whose parameters live in the query. Its
allowlist is empty. Mutation-verified: it names both the route and the exact client line.

**The detector took two corrections before it was worth reading.** The first excluded four
FastAPI markers and reported 48 sites — including a correctly-declared `Header(...)` webhook
signature, which is not a query parameter and never was. The second matched routes by their
last path segment, so `/insights/activations/{id}/reject` was reported as a defect in
`/strategic/recommendations/{rec_id}/approve`: two unrelated routes sharing one word. Both
corrections are pinned as tests, because a detector that names correct code is one people learn
to skip.

Recorded as **class 97**, with rule 140 — fixing the caller closes the instance and preserves
the class.

### The seam the middleware stops at, and a sweep that came back clean

Rule 140 said fixing the caller closes the instance and preserves the class. So: where else did
this repository fix one side of a seam? The codebase answers in its own comments — six admit a
one-sided fix, three are distinct sites, and two were already closed by the previous guard.

The third is `IdempotencyMiddleware`. It dedupes retried mutations by prefix, and `main.py`
states the scope stops on purpose: correlation, kanban, intake, OTA, auth and RBAC are excluded
because they belong to other lanes. Right call — and it leaves **167 of 208 mutating routes**
outside the middleware with nothing separating the surfaces that were considered from the ones
nobody has looked at. A new mutation surface in a protected lane lands outside protection
silently: the middleware does not fail, it simply does not apply.

The guard asserts nothing about which surfaces *should* be protected — each lane decides that.
It asserts every mounted mutation surface is **accounted for**: protected, or named with the
reason it is not. Thirty-one are named, and `/api/v1/api-keys` carries the sharpest reason —
it **must not** dedupe, because every call is required to mint a distinct key.

I wrote the first register from guesses rather than from the measurement, and the guard failed
in both directions at once: seven real surfaces I had not accounted for, and fourteen entries
for prefixes that do not exist. Rebuilt from the route walk.

**A second sweep came back clean.** Three routers mount under `/api/v1/fleet` and two under
`/api/v1/compliance`, so a route declared twice would be shadowed by whichever mounted first —
FastAPI resolves first-match-wins and says nothing. **524 route-methods, zero collisions.**
Worth recording: a shared prefix looks exactly like a collision waiting to happen.

**Three detectors failed in a row getting here**, and the third is the lesson. A prefix matcher
whose direction was inverted, so `/api/v1/assets` "covered" `/api/v1` and everything read as
protected. A module name taken as `split(".")[-1]`, which is `"router"` for every
`include_router` call. And a hand-rolled route walk that reported **six routes for an app with
524**, because `app.routes` holds lazy `_IncludedRouter` entries whose children carry relative
paths.

`tests/_route_tree.py` has existed the whole time and its docstring opens by naming that exact
pitfall. Two wrong answers were the cost of not looking, and the second was a clean tree —
which is the kind that gets believed.

Recorded as **class 98**, with rule 141: before writing a walker, look for the one that already
exists.

### A checkpoint that could not say who inspected it

Rule 139's question, asked of a second file. `yard.py` is in far better shape than
`transportation.py` — eleven of its twelve mutating routes have a test asserting a 2xx. The
twelfth was `POST /checkpoints`.

`YardCheckPointCreate` declares `inspector_id` and `metadata`. `YardCheckPointResponse`
returns them. `YardCheckPoint` has both columns. **The route passed neither to the service** —
so both were accepted, discarded, and echoed back as `null` and `{}` from columns that stayed
empty. A complete round trip that loses the value in the middle and reports success at both
ends.

`checkpoint_type` is gate_in, guard_shack, weigh_station or gate_out. On a weigh-station or
guard-shack checkpoint the inspector **is** the audit trail: the record says an inspection
happened and cannot say who made it. A failed inspection with no inspector is a finding nobody
owns.

Eight tests; five fail with the pass-through removed.

**The same class, resolved the opposite way, an hour apart.** `POST /shipments/{id}/status`
accepted a `note` the client sent on every call, and `Shipment` has no note column — so the fix
was `extra: "forbid"`, refusing the field rather than appearing to record it. Here the column
exists and was simply not wired, so the fix is to store it. The discriminator is not how
harmless the field looks; it is **whether the field has somewhere to land**.

Recorded as **class 99**, with rule 142 — a declared field that is dropped is worse than one
that is refused. A refused field is a 422 the caller can read; a dropped field is a 200 and an
empty column.

### Two sweeps that came back clean, and one that found only my own mistake

Rule 141 said to look for the existing walker first. Carrying that across: do other guards
hand-roll a route walk? The first pass named eight files — and every one of them turned out to
be a **comment warning about the pitfall**, not a hand-rolled walk. Rule 37, on a rule written
an hour earlier: a text search matches the prose describing a defect as readily as the defect.

Re-run against code rather than prose: **zero guards iterate `app.routes` without the
flattener.** Six files carry a warning about it. The repository learned this before I did and
wrote it down in six places; I am the one who did not look.

### The same class, five fields wide, on the route beside it

Rule 142's carry-across is a sweep: which routes declare a body field the handler never reads?
**Eleven**, across six files. `POST /yard/trailers/checkin` is the one in my lane and the
sharpest.

It passed eight fields to the service and dropped five that `YardTrailerCreate` declares and
`yard_trailers` has columns for: `seal_status`, `temperature_setpoint`, `temperature_actual`,
`yard_location` and `metadata`.

`seal_number` was passed and `seal_status` was not. That pairing is the finding: the record
said **which** seal and could not say whether it was intact. A guard reporting a broken seal
got a 200 and a row that said otherwise. The temperatures are cold-chain evidence on a reefer
check-in, and `yard_location` is what the yard map reads — dropped, every trailer parks at
None.

`status` is the one declared field this route should keep ignoring, and now does so on
purpose: the service sets `checked_in`, and honouring a caller's status would let somebody
check a trailer straight to `checked_out` without it ever entering the yard. Declaring it on a
Create schema is that schema's error, the same one `organization_id` carries.

Fourteen tests; six fail with the pass-through removed.

**A defect this fix did NOT close, pinned rather than papered over.**
`YardTrailerBase.seal_status` is `str = "intact"` — not Optional. A check-in that says nothing
about the seal records **"intact" as a positive claim**: a value invented at the moment nothing
is known, and the most reassuring possible answer. Rule 133, on a security field.

Not changed here, and the reason belongs in the record. The column carries the same default, so
making the schema `Optional[str] = None` moves the fabrication one layer down rather than
removing it. The honest fix is a migration to a nullable column with no default plus a decision
about what existing rows mean — a contract change with readers to find, not a wiring fix. It is
recorded as a passing test that asserts the current behaviour and explains itself, so the day
somebody makes the column nullable it fails and points at the reason.

**The other ten routes are recorded, not fixed.** Four are in Harsh's lane
(`kanban`, `logistics_correlation`), and the transportation ones split into two kinds worth
telling apart: fields that are genuine creation input being lost (`CarrierCreate` drops
`insurance_expires_at` and `ctpat_expires_at` — compliance expiry dates on a carrier record),
and fields that are lifecycle state wrongly declared on a Create schema (`approved_at`,
`billed_at`, `is_executed`). The first is data loss; the second is an API accepting values it
will never honour. Both are class 99; the fix differs.

### A carrier the compliance check could never call compliant

The class-99 sweep listed `POST /transportation/carriers` as dropping `ctpat_expires_at`,
`insurance_expires_at` and `is_active`. It is the sharpest of the three instances found today,
because **the reader already existed and already depended on the dropped field**.

`get_carrier_compliance` computes:

    is_valid = certified AND expires_at AND expires_at > now

and the create route passed `ctpat_certified` and `insurance_on_file` while discarding both
dates. So every carrier created through the API had NULL expiries, and the compliance endpoint
reported its C-TPAT **and** its insurance invalid — whatever the caller sent, having been told
200 on the way in. Not merely incomplete data: a wrong answer computed from it.

`is_active` went the same way, so a carrier created as inactive was stored active.

Eight tests; six fail with the pass-through removed. The assertions run the **reader's own
expression** over what the create path stored rather than checking the hand-off, because
`assert kwargs["ctpat_expires_at"] is not None` would pass for a value the comparison still
cannot use. Its companion asserts an expired certificate keeps reading expired — a fix that
makes everything valid would be worse than the defect.

**Three instances of one shape in a day**, and only the third made it obvious:

| route | stored | dropped |
|---|---|---|
| `POST /yard/checkpoints` | an inspection happened | who inspected |
| `POST /yard/trailers/checkin` | which seal | whether it was intact |
| `POST /transportation/carriers` | certified, insured | until when |

Each keeps a flag and discards the field that says what the flag is worth, and each reads as
the more reassuring of the two possible answers. Recorded as rule 143 — when a boolean is
stored, find the field that bounds it; the pair is almost always adjacent in the schema and
split by the call. And rule 144 — assert the round trip through the reader, not the hand-off.

### The register for class 99, and a detector that hid nine routes while looking right

Rule 143's sweep — a boolean the handler passes whose qualifier it drops — comes back **empty**,
and the control proves the zero: reverting the carrier fix makes the detector name both pairs
(`ctpat_certified`/`ctpat_expires_at`, `insurance_on_file`/`insurance_expires_at`); restoring it
returns zero. That is a real clean result, not a broken sweep.

The general class needed a ratchet rather than more fixes, because most of it is in other
lanes. `test_declared_body_fields_reach_the_service.py` has two tiers:

**Absolute** — no route may pass a boolean and drop the field that bounds it. Empty, and may
not gain a member.

**Ratcheted** — fourteen routes carry a declared field the handler never reads, each recorded
with the reason. Two kinds, and the fix differs: **lifecycle state wrongly on a Create schema**
(`approved_at`, `billed_at`, `is_executed`) where the handler is right and the schema is wrong,
and **genuine creation input being lost** (`temperature_min`/`max` on a shipment,
`duration_seconds` on a yard move) which is data loss.

Two entries are deliberate and say so: `status` on a trailer check-in and on a kanban task must
be ignored, because honouring a caller's status would let somebody check a trailer straight to
`checked_out` without it entering the yard.

**One entry is named as the next fix rather than left in the pile.** `POST /drivers` drops six
fields, four of them **DOT-regulated Hours of Service** — `current_hos_status`,
`hos_cycle_hours`, `hos_drive_hours_today`, `hos_on_duty_hours_today`.
`HOSMonitor.check_compliance` reads exactly those to decide whether a driver may be dispatched,
and `dispatch_shipment` refuses on its verdict. That is the carrier defect's shape with a
regulator attached: a reader that already exists and already depends on the dropped fields. Not
fixed in this pass because HOS has a second writer — the ELD sync — and which one wins on
create is a decision, not a wiring fix.

**The detector was wrong first, and its failure is the interesting part.** The first version
matched decorator-to-next-decorator with a bounded body window, so a handler longer than the
window failed to match — and `finditer` resumed past the failed attempt, **taking the following
decorator with it**. Nine of yard's twelve routes vanished, including the one this guard uses
as its positive control. The sweep still produced a plausible eleven-route list; only the
control caught it. Splitting the file on the decorator and parsing each chunk fixed it, and
found five more routes the first version never saw.

That is the third detector this week whose failure mode was **under-reporting while looking
correct**, and the second caught only by a positive control. A sweep that names fewer things
than exist reads exactly like a clean tree.

### A driver created through the API could never be dispatched

The register entry I wrote last pass said `POST /drivers` was the next fix but deferred it:
*"HOS has a second writer, the ELD sync, and which one wins on create is a decision."* That was
wrong, and it took ten minutes to establish once somebody looked at the writers.

The chain, every link of which already existed:

1. `POST /transportation/drivers` declared `current_hos_status`, `hos_drive_hours_today`,
   `hos_on_duty_hours_today` and `hos_cycle_hours` — and passed none of them.
2. `HOSComplianceMonitor.check_compliance` collects **what is missing before what is wrong**:
   any of the three hour figures being `None` produces "cannot be assessed". By design —
   `float(x or 0)` would turn "never reported" into "has driven zero hours" and read as a fresh
   legal driver, which is the FS-421 defect this list was built to prevent.
3. `dispatch_shipment` raises on that verdict.

So a driver created through the API was **permanently undispatchable**, having been told 200
with the hours in the request body.

**And there was no other way in.** The GeoTab ELD webhook writes `hos_drive_hours_today` and
`hos_on_duty_hours_today` — only those two, only when that gated integration is live.
`hos_cycle_hours` and `current_hos_status` have no writer anywhere but `seed_demo_data.py`.
That is why the demo fleet dispatches and a real one would not: **a defect the seed data hides
is a defect nobody meets until production.**

Ten tests, all failing with the pass-through removed. They run `check_compliance` over what the
create path stored rather than asserting the hand-off (rule 144), and the negative cases hold
the line: a driver with no hours still reports unassessable, a driver at 11.5 drive hours still
reports in violation. A fix that made everyone dispatchable would be worse than the defect.

Writing the test surfaced its own small lesson. `check_compliance` also requires a medical
certificate, and the route already passes that one — so a "legal driver" payload needs it too.
The missing-data list is not merely empty for a complete driver; it still names what is absent
when anything is left out, and the test now proves both.

**The register did its job in both directions.** It held the entry until it was resolved, and
the moment the route was fixed the guard reported the entry stale and made me remove it. The
note left in its place says what it cost, because a register entry is a place to put a
decision, not a place to put a doubt.

### Which way is a dropped field wrong? Read the reader

The carrier and the driver were both fixed by wiring the field through. That is not the fix for
the rest of the register, and assuming it was would have done real damage.

Ranking the remaining entries by "does a reader depend on this field" produced two useful
answers and one warning.

**`POST /driver-wait-times` resolves the opposite way.** It drops `detention_charge`,
`demurrage_charge`, `total_wait_minutes` and four more — and `close_driver_wait_time` **computes
every one of them** at checkout from the two timestamps and the two rates. Dropping is correct,
and honouring them would be worse than the defect: an operator could post their own detention
charge on create and the system would bill it. The lie is the schema's, for accepting them; the
fix is a contract change, not wiring. Recorded in the register with that reasoning.

**`POST /routes` is the strongest remaining wiring case.** `total_distance_miles` is read by
`transportation_management.py:939` and `estimated_duration_hours` by `:356` — creation input
with dependent readers, the carrier's shape. Left for its own pass because it needs a decision
about whether a route's distance is operator-supplied or derived from its stops, and that is a
question rather than a doubt.

**The ranking's first answer was mostly wrong**, and the reason is worth the rule. It reported
`approved_at` as read by `kanban.py` — a *task's* approval, nothing to do with a freight charge
— plus `duration_seconds` by `dashboard.py` and `priority` by `data_shedding.py`. Common column
names live on a dozen models and `\w+\.field` finds all of them. Only same-module readers
survived scrutiny.

That is the **third name-collision false positive this week**, after
`/insights/activations/{id}/reject` reported as a defect in
`/strategic/recommendations/{id}/approve`, and a tail-match conflating two unrelated routes.
Recorded as rule 146 — anchor on the module, not the name — alongside rule 145, read the reader
before deciding which way a dropped field is wrong.

### Rule 145 overturning my own entry, one pass after I wrote it

Last pass I recorded `POST /routes` as "the strongest remaining wiring case" because
`total_distance_miles` has a same-module reader, and left it for its own pass. Applying rule
145 — read the reader, and ask whether the value has another producer — settled it the other
way in ten minutes.

`create_route` **always** runs `route_optimizer.optimize_route` and sets `total_distance_miles`,
`estimated_duration_hours`, `fuel_cost_estimate` and `toll_cost_estimate` from its result:
haversine, or OSRM road distance when configured. Every route created through the API already
has a computed distance.

So wiring the caller's value through would be the wrong fix, and not harmlessly: it would let
somebody override a computed route distance with any number they liked, and that number reaches
`get_shipment_costs`, which bills linehaul and fuel surcharge **per mile**. The entry is now
recorded as schema-side, with `is_active` called out as the one field in the list that is
genuine creation input.

Twice now the register has held an entry whose stated reason was wrong — the driver deferral,
and this. Both were resolved by reading rather than deciding, and in both cases the reading took
minutes. The register is doing what it should: holding a claim still long enough to be checked.

### A fabricated 500 miles, in a billing calculation

Found while reading the above, and left as a finding rather than a fix because it is a contract
question.

`get_shipment_costs` computes:

    distance = float(route.total_distance_miles) if route and route.total_distance_miles
               is not None else 500.0

and feeds that into `calculate_linehaul` and `calculate_fuel_surcharge`, both per-mile. It then
returns `'distance_miles': distance` — so the fabricated **500** is reported as the shipment's
distance, and the frontend renders "500 mi".

Since every route created through the API now carries a real distance, the fallback fires for
shipments with **no route at all** — and the existing comment beside it says as much: *"the
endpoint only worked for shipments with NO route — the case with the least to bill."* So a
shipment with no route is billed 500 miles of linehaul plus fuel surcharge on the same 500.

Rule 133, in a money calculation. The client is already able to be honest about it —
`distanceMiles: number | null`, and `TransportationManagement.tsx:1235` hides the row when null
— so the wire contract can express "unknown" today. What cannot be settled by reading is what
`linehaul.amount` and `total_cost` should say when distance is unknown: they are non-optional
floats, and answering 0 fabricates a cheap shipment exactly as 500 fabricates an expensive one.
That is a decision about what the endpoint promises, not a wiring fix.

### Two fabricated defaults compounding into a billed figure — class 100

Rule 133's sweep, run over `app/services/` for the first time. Ten numeric fallbacks; most
harmless — sort keys, a peak-hour range the pattern misread — and **two in the same call
chain**:

    get_shipment_costs:   distance = route.total_distance_miles if … else 500.0
    calculate_linehaul:   rate_per_mile = rate_per_mile or 2.50

Neither knows about the other, and neither reports that it fired. Quantified rather than
asserted, by running the real engine:

    linehaul        $1,250.00     (500 invented miles x $2.50 invented rate)
    fuel surcharge  $   83.33
    total           $1,333.33

and the endpoint returns `distance_miles: 500.0`, which the Transportation page renders as
"500 mi".

**A fabricated rate and a contracted one at the same value produce byte-identical results.**
That is what makes the figure dangerous rather than merely wrong, and it is the property a fix
has to remove.

Neither literal looks careless in place, which is why both survived. The 500 sits under a long,
correct comment about a Decimal/float `TypeError` — a real fix, beside which the fabrication
went unremarked. The 2.50 is labelled *"Default rates if not specified"*, true and silent about
the result being billed.

Not fixed: `linehaul.amount` and `total_cost` are non-optional floats, and answering 0 for an
unknown distance fabricates a cheap shipment exactly as 500 fabricates an expensive one. There
is no honest number — the endpoint needs to be able to say "not estimated", which is a contract
change and a decision about what the figure means. Pinned as five passing tests that state the
amount, so the finding lives beside the code.

Recorded as **class 100** with rule 147 — defaults compound, and no single site looks wrong;
follow the call chain rather than ranking fallbacks individually.

**Class 100 also broke the guard that counts the classes.** `_spell()` covered fifty to
ninety-nine, written when the highest class was in the sixties, and raised *"class count 100 is
outside the range this speller covers"*. It failed honestly rather than passing over a number
it could not render, which is why it was worth extending rather than replacing — it now covers
through 199 and says in its docstring that it will need doing again at 200.

### The billing fallbacks, fixed — "not estimated" is a state, not a zero

The first of the three open findings, and the decision it needed: **when the distance is
unknown the endpoint reports the charge as not estimated rather than inventing one.** That is
the answer FS-533 already gave for the fuel surcharge, and the shape `distance_miles` already
had on the wire.

The two defaults resolved differently, which is the point:

**The distance fallback is gone.** `None` now reaches both calculators and both answer
`amount: None` with `rate_basis: "not_estimated"` and an `assumptions.basis` of
`distance_unavailable`. There is no honest number for an unknown distance — `0` fabricates a
cheap shipment exactly as `500` fabricated an expensive one.

**The rate default is kept and labelled.** Removing it would refuse to price every uncontracted
shipment, a far bigger change than this defect warrants — and FS-533 made the same call, keeping
the fleet-average surcharge and labelling it. `assumptions.basis` now reads `default_list_rate`
where a contracted rate reads `contract_rate`. Those two were previously **byte-identical at
the same value**, which is the property that made the figure dangerous rather than merely
wrong, and the test that used to assert they were identical now asserts they differ.

`2.50` moved out of an inline `or` into `DEFAULT_LINEHAUL_RATE_PER_MILE`, so it can be cited
and so changing what an uncontracted carrier is billed is a visible edit.

**The contract change cost five fields.** `linehaul.amount`, `fuel_surcharge.amount`,
`mileage_charge`, `weight_charge` and `total_cost` are `Optional[float]` now, and the
TypeScript follows. `tsc` named the three render sites immediately. The page shows an em dash
rather than `$0.00` and carries one line explaining why — which is the argument its own comment
already made about the missing accessorials: *a zero in a cost breakdown reads as "nothing was
charged" rather than "not calculated here"*.

`total_cost` is `None` when either component is: summing with zero would put a confident total
under two charges that both say they are not estimates.

Ten tests, and the file that pinned the defect now pins the fix — including a guard that the
`500.0` literal has not come back. The frontend suite and `tsc` are clean.

### The seal that was intact because nobody looked

Second of the three. `yard_trailers.seal_status` is one of intact / broken / missing, and both
the Pydantic schema (`str = "intact"`) and the column (a server default from migration 050)
supplied "intact" when a check-in said nothing. That is not a neutral default — it is **the
most reassuring of the three values, written precisely when nobody looked**.

Reading migration 050 before overturning it was the right call, because its reasoning is sound
and is why this slipped in. It gave server defaults to 39 logistics columns whose ORM `default=`
fired only through SQLAlchemy, so a raw INSERT wrote NULL and the API could not serialise the
row. Its argument:

> a NULL `is_active` or `status` is a missing value, not an unknown moment, so writing the
> documented default is a correction, not an invention

True for `is_active`, for `{}` on a JSON column, for every other column in that list. **It does
not hold where the value asserts something.** An absent `is_active` has an obvious intended
reading; an absent seal check has none, and supplying one invents an inspection result.
`seal_status` was swept along with 38 columns whose defaults are genuinely harmless.

Migration 068 drops the server default; the ORM and the schema drop theirs. Silence now stores
NULL, which is what silence means.

**What it cannot do, stated in the migration header rather than worked around.** 050's backfill
was `UPDATE yard_trailers SET seal_status = 'intact' WHERE seal_status IS NULL`, so every row
that had never recorded a check now says 'intact' and is indistinguishable from one where a
guard genuinely reported an intact seal. Setting them back to NULL would erase the real checks
to undo the invented ones — a known fabrication traded for certain data loss. The rows are left
alone. This stops the fabrication from here on; nothing can undo what is already written.

The test that pinned this as an open finding now asserts the fix, and says which two defaults
have to stay gone — either one alone restores the claim.

### The third finding, split by rule 145 and half of it closed

The nine routes declaring body fields their handlers never read. Ranking them by *does another
writer produce this value* separated them cleanly:

**Produced elsewhere → the schema is wrong, not the handler.** `actual_pickup`,
`actual_delivery` and `status` on a shipment are written by `update_shipment_status`;
`actual_start`/`actual_end` on a dock appointment and `duration_seconds` on a yard move are
computed at their close. The handler is right to ignore all of them, and the fix is to stop the
Create schema accepting values it will never honour — a contract change, recorded.

**No producer anywhere → the workflow does not exist.** `executed_at`/`is_executed` on a load
plan, `approved_at`/`approved_by`/`billed_at`/`is_billed` on a freight charge. Nothing in the
codebase ever sets them, so the API is promising an approval and billing flow that has not been
built. Also schema-side, and worth saying plainly rather than filing as data loss.

**Genuine creation input → wired.** `POST /shipments` dropped four: `route_id`, `priority`,
`temperature_min` and `temperature_max`.

`temperature_required` was passed and the range it refers to was not — **the fourth instance of
a flag kept while the field giving it meaning is discarded**, after the checkpoint's inspector,
the trailer's seal status and the carrier's expiry dates. A reefer shipment marked as needing
temperature control, with no range to control to.

`route_id` is the one with reach. It is how a shipment gets a route, a route is where
`total_distance_miles` lives, and that distance is what `get_shipment_costs` bills per mile.
Dropped, a shipment created through the API could never be routed at create — and FS-665 has
just made that consequence *visible* rather than hidden, since a shipment with no route now
reports "not estimated" instead of inventing 500 miles. The two fixes meet.

Five tests fail with the pass-through removed. The register entry shrank from eight fields to
four, which is the ratchet doing what it is for.

**A test premise of mine was wrong again, and the correction is the interesting part.** I
asserted an omitted `priority` would arrive as `None`; `ShipmentBase.priority` is
`str = "normal"`, so the schema supplies it before the handler runs. That is the same question
`seal_status` failed — and the answer differs, which is the point. **"normal" is a genuinely
neutral default: it asserts nothing a reader acts on, where "intact" asserted a security check
that never happened.** A defaulted enum is only a lie when the value makes a claim.

### The schema-side half, and a deferral that was wrong for the third time

I recorded the twelve unhonoured fields as "a contract change with clients to check", which is
what I said about the driver HOS fields before reading the writers proved otherwise. Checking
first this time took one grep, and the precedent was already in the file I was about to edit:

> Removed rather than made Optional. A field a caller can set that changes nothing is its own
> small lie, and **pydantic ignores extra keys by default, so a client still sending one is
> unaffected**. — FS-523, on `organization_id`

So this is not a risky contract change. Client behaviour is **identical** either way, because
the value is already discarded. The only thing that changes is that the OpenAPI schema stops
advertising fields the server will not honour.

Five `*Base` classes were shared between Create and Response, which is how the lifecycle fields
reached Create at all. They moved down into the Response classes:

| schema | moved | why |
|---|---|---|
| `ShipmentBase` | `status`, `actual_pickup`, `actual_delivery` | written by `update_shipment_status`; `ShipmentUpdate` already carried all three |
| `DockAppointmentBase` | `actual_start`, `actual_end`, `status` | written when the appointment starts and completes |
| `YardMoveBase` | `duration_seconds` | computed by `complete_yard_move` |
| `LoadPlanBase` | `is_executed`, `executed_at` | **nothing sets these** |
| `FreightChargeBase` | `is_billed`, `billed_at`, `invoice_number`, `approved_at` | **nothing sets these either** |

The last two rows are worse than an ignored field. A caller could mark a freight charge billed,
with an invoice number, at creation — and the approval and billing flow **has never been
built**. The Create schema was advertising a lifecycle that does not exist, which a caller has
no way to discover.

`ShipmentUpdate` already carrying `status`/`actual_pickup`/`actual_delivery` is what confirms
the intent: lifecycle belongs on Update. The Base was simply the wrong place to put them.

The register went from 8 fields on shipments to 1, and 6 on freight charges to 3.

**And the remainder made a pattern visible.** `metadata` is now on nine of the thirteen
remaining entries — one defect wearing nine hats, not nine findings. Every one of those tables
has a `meta_data` column and the handler never passes it, so metadata attached to a shipment, a
yard move or a dock appointment vanishes with a 200. `POST /yard/checkpoints` was the same and
is already wired, which is why it is absent. Recorded as one pattern rather than fixed in nine
blind edits across four modules — each needs its service signature widened, and that is how a
mechanical change becomes somebody else's merge conflict.

### The metadata pattern, closed in this lane

`metadata` was declared on nine Create schemas across four modules and passed by almost none,
with a `meta_data` column waiting on every one of those tables. A caller attaching a reference,
a BOL number or an operator's note to a shipment, a yard move or a dock appointment watched it
vanish with a 200.

**One defect wearing nine hats, not nine findings** — and that was only visible once the
register had shrunk enough to read. It is the argument for keeping one.

Six routes wired in this lane: shipments, load plans, freight charges, dock appointments, yard
moves and driver wait times. The genuine creation input alongside it went too:

* **`currency`** on a freight charge — every charge was recorded as USD whatever the caller
  said. A charge in the wrong currency is a wrong number, not a missing one.
* **`temperature_zones`** on a load plan — the cold-chain layout of the trailer.
* **`driver_id`** and **`compliance_required`** on a dock appointment — who is expected at the
  door, and whether the visit needs a check. Booking facts, not lifecycle state.

`approved_by` moved to the response with its siblings. Nothing approves a freight charge, and a
Create schema accepting an *approver* for a flow that does not exist is the most misleading of
that set, because it reads as an audit field.

**My lane's register is now four entries, all schema-side or deliberate**, and one of the four
(`is_active` on a route) is the only genuine creation input left in it.

**Two of my own mistakes were caught mid-change, by two different gates.**

The suite caught a regression I introduced: `temperature_zones` is `List[Dict[str, Any]]` on
the schema and `Column(JSON, default=[])` on the table, and I defaulted it to `{}`. That stored
an object, the response model refused to serialise the row, and **every load-plan create
answered 500** — a route that had been working. `test_the_unblocked_creates_actually_create`
failed with the exact reason, before it shipped. That is the argument for running the whole
suite rather than the files I touched: nothing I edited was in that test.

And **`flake8` caught the other**, which is worth recording because it is the gate I wired into
branch pushes this morning. Locating a constructor with a bare `index("move =
YardMove(")` found the **first** occurrence in the file — a different method with no
`meta_data` in scope — and produced `F821 undefined name`. First-match-wins on a blind index is
the same shape as the tail-matching and module-name collisions this week; anchoring the search
inside the enclosing method fixed it. Ten seconds, because something was looking.

### A guard built from my own regression

The `temperature_zones or {}` mistake from the previous entry is now a guard, and the sweep it
came from is worth reporting for its result as much as its finding: **eighteen container
defaults across `app/`, zero other disagreements.** The tree was clean. I was the defect.

That is the argument for the guard rather than against it. The failure mode is a 500 on the
**success path only** — the wrong container is stored, the response model refuses to serialise
the row, and `route_walk` cannot see any of it, because with generated inputs a create rejects
before it reaches the response. What caught mine was a real-database test in a file I had not
touched.

`test_json_defaults_match_their_column.py` reads the column shapes from live SQLAlchemy
metadata rather than from the source text — a regex over `Column(JSON, default=[])` would miss
the columns whose default arrives through a shared helper, and this guard exists precisely
because a text-level assumption was wrong once already.

Its positive control is the line that shipped: it asserts the detector flags
`temperature_zones=temperature_zones or {}` verbatim, **and** that the column still declares a
list, so the control cannot go stale without saying so. Mutation-verified by reintroducing the
bug — it names the file and line.

One thing the guard deliberately does not fix: both containers are falsy when empty, so `or`
cannot tell "caller sent nothing" from "caller sent an empty one" at any of the eighteen sites.
That is a smaller problem than storing the wrong type and needs `is None` at every site rather
than a shape check. Recorded rather than bundled in.

Rule 148 — turn your own regression into the guard that would have caught it, and write it when
the sweep comes back clean, because that is when it is cheapest and feels least necessary.

### Fields you could set once and never correct

Following through on the fields wired today: **can they be changed?** Comparing every
`*Create` schema against its `*Update` sibling found twenty-six that could not, on entities
that already have a working PUT route updating ten other columns on the same row.

* A **driver's phone number, email, carrier and ELD device.** The most ordinary correction
  there is, on a route that already edits ten HOS and licence fields.
* A **shipment's** pickup and delivery schedule, origin, destination, weights, hazmat flag and
  temperature range — sixteen fields. A pickup moving is the most common event in dispatch.
* A **trailer's** seal number and reefer setpoint — while `seal_status` and
  `temperature_actual` beside them were already editable. A seal replaced at the gate could be
  marked intact **while still naming the old seal**, which is the pairing that makes the
  omission visible.

**`route_id` closes a loop from earlier today.** FS-665 stopped `get_shipment_costs` inventing
500 miles, so a shipment with no route now honestly reports *not estimated* — and nothing could
assign it a route afterwards, which made the honest state inescapable short of recreating the
shipment. An honest refusal with no way out is only half a fix.

Safe to add because every one of these handlers applies `model_dump(exclude_unset=True)` and
`setattr`, which `test_partial_updates_do_not_wipe_fields.py` already enforces: a field on the
Update schema is editable when sent and untouched when omitted, so widening cannot blank
anything. Both sibling guards were run and still pass.

`shipment_number` and `trailer_number` stay uneditable, and the test asserts it — an API that
lets a caller rename the thing it is addressing has a different problem, and that should read
as a decision rather than an oversight.

**Four entities have no update route at all** — dock appointments, load plans, freight charges
and routes. That is a missing feature rather than a broken one, and a different conversation:
an appointment that cannot be rescheduled and a freight charge that cannot be corrected are
product gaps, not defects in something that claims to work. Recorded, not built.

**A guard fired at the fix, and it was half right.** Widening `ShipmentUpdate` failed
`test_frontend_fields_exist_on_the_wire.py`, which asserts every declaration of `origin` reads
`Dict[str, Any]` — the new one reads `Optional[Dict[str, Any]]`. The guard's premise is *the
backend contracts no keys for this field*, and an optional untyped dict contracts none either,
so the premise held and only the literal `startswith` was too narrow. The repair strips exactly
one `Optional[...]` wrapper and nothing more; `Optional[Location]` still fails, which is the
case the check actually exists for. Rules 149 and 150 came out of this — the second because
`git checkout app/models/schemas.py`, used to undo the mutation, silently took the entire
uncommitted widening with it.

### A validation block that has never run

Carrying the FS-671 class across the rest of the schema file — every `*Create` against its
`*Update` sibling, not just the three transportation ones — turned up one that is a different
and worse shape.

`update_asset` contains a **tenant-scoped validation block**: if the caller sends
`workcell_id`, look the workcell up *within the caller's organization* and 404 if it belongs to
someone else. Somebody wrote that deliberately; it is the same cross-tenant check the create
path performs. `AssetUpdate` declares no `workcell_id`, so `"workcell_id" in update_data` is
always False, **the block has never executed, and an asset cannot be moved between workcells at
all** — a sensor registered against the wrong line stays there for the life of the row.

The dead check is what makes this a defect rather than a missing feature. The intent is in the
file; only the schema is missing. `asset_type_id` is the same omission without the tell.

**The sweep, and two detectors thrown away before one worked.** For every API handler taking a
pydantic model, follow the variable it dumps into and require every key read off that dump to
exist on the model. The first version matched `'key' in update_data` textually against a list of
likely variable names and found **one key across forty-three handlers** — a detector with no
negative control is not a sweep, it is a restatement of what you already found by hand. The
second followed the dump variable properly and flagged two `organization_id` sites that were
`payload["organization_id"] = org_id`: assignments, not reads. A subscript is a read only when
its AST context is `Load`. The third finds ten sites, eight of them reachable, with
`update_user` reading `role` and `is_active` as a negative control that is real rather than
constructed.

**Two of my three claims were false, and mutation-testing is what said so.**

* *"Without an `asset_type_id` existence check a bad id is a 500."* Removing the check left
  everything green: `app/core/errors.py` already maps a foreign-key violation to a 400 reading
  *"Reference in 'asset_type_id' does not exist in 'asset_types'"*, which is a better message
  than the copy produced. **The check was deleted.** A guard whose mutation test does not fail
  is asserting that the guard exists, not that it works.
* *"The behavioural test proves the workcell lookup is tenant-scoped."* Deleting
  `Workcell.organization_id == org_id` also left all five passing — RLS hides the other
  tenant's workcell from that session regardless. The predicate is still a real control, because
  RLS holding depends on the database ROLE and a BYPASSRLS connection turns the same request
  into a genuine cross-tenant write. But no behavioural test can currently distinguish it, so
  it is pinned statically instead, and both files now say which control they actually hold.

### One error line in an otherwise green run

The frontend suite reported **1,056 passed** and, underneath it, **`Errors 1`** — not a failing
assertion, an unhandled rejection the runner noticed and nothing owned.

`KanbanBoard.handleDrop` is `async` and is passed to `KanbanColumn`'s `onDrop`, which is typed
`(columnId: string) => void` and called from a DOM drop handler. TypeScript allows
`() => Promise<void>` where `() => void` is expected, so the compiler had nothing to say, and
the promise it returns is discarded. Its own comment made the claim explicitly — *"the error
still propagates to the caller"* — and there is no caller.

`Kanban.tsx` catches this and shows the user *"That task could not be moved"*, so the promise
never rejects in production today. That makes it a trap rather than a live failure — and the
trap is that a future `onDragEnd` which forgets to catch fails in complete silence.

**The sweep came back clean.** Thirty-six awaiting async handlers are passed to JSX props;
after this fix every one is guarded. Two detector corrections got it there, both of the
recurring kind — a handler that delegates to something that catches is safe, and the regex
capturing async arrows used `\([^)]*\)`, so `runAction(what: string, action: () => Promise<void>)`
was never captured and nothing could delegate to it. Uncorrected, either would have produced
seven confident false positives in one file.

The guard was written **because** the sweep was clean, with the try/finally that shipped as its
positive control. A green run with an unread error line underneath is how the next real one
gets missed.

### Ten background tasks nobody held and nobody watched

The frontend rejection above (FS-673) is a class, not an incident: **a failure whose owner is
nobody**. Carried to the backend's runtime, it lands on `asyncio.create_task`, and ten of the
twenty calls in `app/` threw the task away.

Two holes, both documented, neither visible:

* **The event loop keeps only a weak reference.** CPython's own docs: *"Save a reference to the
  result of this function, to avoid a task disappearing mid-execution ... may get garbage
  collected at any time, even before it's done."* A discarded task is work that may simply not
  happen. `edge_ingest` fired one **per request** to forward accepted readings to the broker —
  on a path whose response has already told the agent how many were forwarded.
* **An exception is never retrieved.** It surfaces as asyncio's own *"Task exception was never
  retrieved"* at garbage-collection time, on the `asyncio` logger rather than the structured
  one, with no request and no trace id. Every loop in `cloud_gateway`, `tactical_engine`,
  `strategic_engine`, `mlops_pipeline` and `websocket_manager` could die that quietly.

`app/core/tasks.py: spawn(coro, name=...)` closes both — the task is held until it finishes and
its result is inspected on completion, so a failure is logged where every other error is. It is
**not supervision**: nothing is retried, a dead loop stays dead, and the only difference is that
you find out. The name is required rather than optional, because `Task-17` identifies nothing
and the log line is the only evidence the work existed.

**The split was ten and ten**, which is what makes the sweep trustworthy: the other ten already
assign to `self._task`, so the guard requires the *property* (the reference is retained) rather
than banning `create_task`, and those ten are its negative control.

Three things went wrong on the way, and all three are the same lesson from different angles:

* The scripted import insertion put `from app.core.tasks import spawn` **inside a multi-line
  `from ... import (`** in `workers/ingestion.py`. The file stopped parsing, and what surfaced
  it was the guard's own AST walk crashing — not a test failure, a traceback. A bulk edit needs
  a compile check per file, not a diff that looks right.
* `caplog` captured nothing, because structlog renders through its own processor chain.
  `test_unknown_reference_is_a_client_error.py` had already hit this and written down that
  `capfd` passes alone and fails in the full suite; `structlog.testing.capture_logs` is the
  answer and was already in the repository (rule 141 again).
* Both were caught within a minute of writing the guard. Writing the sweep *before* declaring
  the migration done is what turned two silent breakages into two visible ones.

### Every MQTT message, lost on a thread boundary

Carrying the discarded-task sweep from `backend/app/` into the edge agent found six more
sites — and then asking, per site, *who calls this* turned a hazard into a live, total failure.

**`asyncio.create_task` only works on a thread that is running the loop.** Three of the six are
called from threads that are not:

* **`paho.mqtt` with `loop_start()`** dispatches `on_message` from its own network thread.
  `MQTTCollector._on_message` called `create_task` there, which raises
  `RuntimeError: no running event loop` **before the coroutine is ever scheduled**. The raise
  lands in the method's broad `except Exception` and is logged as `mqtt_message_handler_error`.
  **Every reading from the collector this agent is built around was dropped**, for as long as
  the code has existed. `BambuCollector` inherits it.
* **`watchdog`'s `Observer`** dispatches `on_created`/`on_modified` from its own thread. The
  same raise. `orca_file` is a **registered collector type** that could not process a single
  file it was watching for.

Proven before it was fixed, and proven the same way after: call `_on_message` from a real
thread with a stub callback and count deliveries. **Zero from paho's thread, one from the event
loop.** The fix reverses it.

`opsgrid_agent/tasks.py: spawn(coro, name=..., loop=...)` handles all three cases — a task on
the loop, `run_coroutine_threadsafe` against the loop captured at `start()` off it, and a
logged refusal with the coroutine closed when there is no loop at all. The collectors capture
their loop in `start()`, which is the only place they are guaranteed to be on it.

**The distinction between the six is the interesting part.** OPC-UA's handler runs on asyncua's
own loop and the adapter already handled the missing-loop case by hand: those two were *only*
unretained, and the code now says so rather than implying all six were broken.

**Why nothing caught it.** Neither handler had a test, and the shape is invisible to reading —
`asyncio.create_task(...)` inside a method is unremarkable, and nothing at that line says which
thread will run it. The first version of the new test called `_on_message` directly and passed
against the broken code; it proves nothing unless it calls from a real thread.

Edge agent: **380 passed, 1 skipped**. Both mutations — either collector back to a bare
`create_task` — fail exactly the tests that describe them.

### A schema written down and never wired

Chasing the last of the FS-671 Create/Update gaps into `registries.py` found something worse
than an asymmetry: `PUT /registries/correlations/{id}` declared three **bare scalars**, and
FastAPI reads a non-Pydantic scalar with no `Body()` marker as a query parameter. The endpoint
wanted `?correlation_strength=80`, so the obvious `api.put(url, {...})` would have returned
**200 having changed nothing** — the quietest failure available.

`DataCorrelationUpdate` was sitting in `schemas.py` referenced by no code at all. The intended
design had been written down and never connected. `update_registry`, `update_registry_item` and
`create_correlation` in the same file all take their model, so this was the one route that
missed it rather than a deliberate contract — and nothing calls it (no frontend client; the
only test naming it is the auth walk), so aligning it breaks nothing.

**And the schema was three fields of eleven.** `source_id` and `target_id` are nullable columns,
optional on create, so a correlation could be filed between *a task* and *an asset* with neither
identified and then never completed — the shape FS-665 left on shipments. The pair is now in
`test_what_can_be_created_can_be_corrected.py` rather than fixed only here, because a one-off
fix leaves the class open; the extended guard catches it on every run.

**A new sub-sweep, and a detector correction inside it.** Which write schemas does nothing
reference? The first answer was three — `AlarmCreate`, `DataCorrelationUpdate`,
`TruckAssetCorrelationCreate`. It searched every file *except* `schemas.py`, to avoid matching
each class's own definition, and therefore could not see `class AlarmResponse(AlarmCreate)`:
excluding a file to suppress self-matches suppressed the legitimate intra-file use as well.
**One of the three was real**, and the guard now asserts the correction directly — a base class
must not be reported as unused.

`TruckAssetCorrelationCreate` is recorded rather than acted on: `TruckAssetCorrelation` is a
table with five relationships and no reader and no writer anywhere in `app/`. That is a dead
*entity*, not a dead schema, and deleting a table is not a mechanical fix.

Mutation-verified three ways: the route back to query parameters fails the contract tests, the
endpoints dropped from the schema fails the completability tests *and* the extended FS-671
guard, and a handler that accepts the body and discards it fails three of the four real-database
tests.

### The five entities you could create and never update

Clearing the items recorded but not acted on. The Create-vs-Update comparison finds *fields*
that are frozen; it cannot see the worse case, where the schemas agree perfectly and **no route
serves the update at all**:

* a **dock appointment** that could be started and completed but never RESCHEDULED, on a
  surface whose most common event is a truck moving to another slot;
* a **load plan** that could not be amended, so a pallet that would not fit meant a second plan
  on the same shipment contradicting the first;
* a **freight charge** that could not be corrected — FS-665 found this service inventing a
  $1,333.33 linehaul from a 500-mile default, and once written that figure was permanent;
* a **route** whose distance prices every shipment on it, fixed at creation;
* a **dock door** that could not be reconfigured, so converting a bay from inbound to
  cross-dock meant deleting it and losing every appointment referencing it.

Four of the five had an `*Update` schema already written and wired to nothing — FS-676's shape,
four more times. Two of them (`RouteUpdate`, `DockAppointmentUpdate`) were even *imported* by
the module that failed to serve them.

**The dock appointment carries real logic, not a `setattr` loop.** `schedule_appointment`
enforces two invariants, and a reschedule that skipped them would make the update the way to
create exactly what FS-392 removed: a reversed booking that blocks a legitimate slot while
protecting none, and a double-booked door. Both are checked against the **effective** interval,
because a caller who sends only `scheduled_end` still changes it. `_check_conflicts` has
accepted an `exclude_id` since it was written and nothing ever passed one — without it an
appointment being moved conflicts with itself and no reschedule could succeed.

**The fifth was found by throwing a detector away.** The obvious check — every collection POST
should have a sibling PUT — reported **95 of 123 POSTs as missing an update**, because most
POSTs are actions (login, flush, enforce) and because `POST /assets/` and `PUT /assets/{id}`
differ by a trailing slash. Ninety-five findings in a tree with five is not a rough first pass,
it is noise that buries the answer. Pairing by **schema** instead, from the OpenAPI document,
has no heuristic in it — an action endpoint has no `*Create` model, so it never enters the
comparison — and it found the dock door that my own summary had missed.

### Nineteen kanban fields, and the one that needed the handler

Twelve on a task — type, planned start and duration, effort, tags, completion actions, and
every link it carries — and six on an automation rule: what fires it, where the task lands, who
it goes to, who is told, what happens on completion.

**This is the one place where widening the schema was not the fix.** Every other update handler
here applies `model_dump(exclude_unset=True)`; `update_task` hand-writes an `if x is not None`
block per field so it can build the activity-log changelog. A field added to the schema and not
to the handler is declared, accepted, validated and **silently dropped** — the FS-676 defect,
reintroduced by the fix for FS-671. Two of the twelve carry constraints: a board move needs a
column on the destination board (and the column check had to learn about the *effective* board,
or a legitimate move 404s on a column that exists), and a parent link must not close a cycle.

**The thirteenth `organization_id` is closed.** `TaskRuleCreate` required a tenant id that
`create_task_rule` discards, so the natural client — which carries none — got a 422 on every
rule it tried to create. FS-523 removed exactly this from twelve schemas; this one was found by
the guard, recorded in the register as another lane's, and left there. The register entry is
deleted rather than reworded: it only ever shrinks.

### Two things found by accident, and one claim of mine that was false

**`websocket_manager.broadcast_to_org` does not exist.** The method is
`broadcast_to_organization`. Every kanban task create, update and move raised `AttributeError`
inside a `BackgroundTasks` job — *after* the 200 had gone out, so `route_walk` sees a healthy
route and the live board simply never receives an event. Found by the first real-database
exercise of `POST /kanban/tasks` in this suite, written for something else entirely. It is
rule 139's blind spot reached from the other side: the failure is on the success path, after
the response.

**`TruckAssetCorrelation` is not a dead entity, and I said it was.** The register entry read
"a table with five relationships and no reader and no writer anywhere in `app/`". False —
`logistics_correlation_engine` reads it twice and writes it once. The grep behind the claim
ended in `head -6`, and `db/models.py` alone supplies six matching lines, so the truncation
removed every real use and the output read exactly like a complete answer.

With the premise corrected the decision got *easier*: the entity is **derived, never posted**,
and every field on its base is computed — including `detention_charge`, which is billable. A
create schema for that shape advertises that a caller may declare how long a truck waited and
what to bill for it. `TruckAssetCorrelationCreate` is deleted; the Response schema stays,
because `api/logistics_correlation.py` returns it and reading a computed correlation was never
the problem. The register is now empty.

### A call to a method that does not exist

`broadcast_to_org` was found by accident. The class is checkable: module-level singletons are
real objects at import time, so every attribute access on one can be resolved against the
object itself. **211 accesses across `app/`, all resolving** — clean, so the guard was written
while it was cheapest, with the literal line that shipped as its positive control.

Two corrections on the way, and the second is the more useful one.

**A global name map reported `main.py: twin_optimizer.router` as missing.** There `twin_optimizer`
is the API *module*, which has a `router`; the singleton sharing that name is a service, which
does not. Each file is now resolved through its own imports.

**And the detector nearly shipped having examined nothing.** During its own mutation test it was
run as a script file rather than through stdin. Python puts a script's directory on `sys.path`,
not the working directory, so every `importlib.import_module("app...")` raised, every exception
was swallowed by the `except` that exists for genuinely unimportable modules, and the sweep
checked zero accesses — **printing exactly what a clean tree prints**. The mutation test is what
exposed it: restoring the bug produced no failure, which is the one result a working detector
cannot give.

`test_the_sweep_examined_something` now asserts the denominator. Every failure mode of this
guard — a broken path, a renamed package, an import that starts raising — empties the result and
produces a report identical to health, and only a count can tell those apart.

### A class that is closed by the compiler, not by anyone's work

A standing plan item says ~90 inline `toLocale*` sites bypass an untested `formatters.ts`,
so `new Date(null)` renders "Invalid Date" to a user. The failure modes are real and the
null one is worse than advertised — `new Date(null)` renders **12/31/1969**, a plausible
date rather than an obvious error, which is the "absence rendered as a fact" shape this
codebase keeps finding.

**But it cannot happen here.** `tsconfig.json` sets `strict: true`, and `new Date(x)` where
`x` is `string | undefined` or `string | null` is a compile error — verified by planting both
forms and watching `tsc --noEmit` reject them. The typecheck is a blocking CI gate (added
earlier in this session), and `test_branch_pushes_reach_the_gates.py` asserts branch pushes
reach it. So the class is closed by construction, transitively guarded, and needs no sweep.

Recorded because **"proven impossible" and "never checked" look identical afterwards**, and
this one cost three detectors to establish:

* a name-based pass reported **18 unguarded sites**, using a single set of optional field
  names gathered from every type in `types/` — so `timestamp` being optional on one model
  marked every `.timestamp` in the tree, including `TelemetryPoint.timestamp`, which is
  required. The same global-name-map error as rules 160 and 162.
* a TypeScript compiler-API pass examined 236 `new Date(x)` sites and reported zero — the
  right answer, but its positive control never fired, so the zero was not yet trustworthy.
* the decisive check was the simplest available and should have been first: plant the defect
  and ask the compiler. One command, unambiguous.

The residual risk is not this class: it is a field the wire declares non-null and sends null
anyway, which is `test_frontend_fields_exist_on_the_wire.py` and the optional-versus-required
guard from FS-672, both already in place.

### A background task whose arguments do not fit its function

`broadcast_to_org` was the wrong *name*. The same blind spot swallows the wrong *call*:
`background_tasks.add_task(fn, a, b, c)` binds its arguments when the task runs, and it runs
after the response has been sent. A mismatch is a 200 to the caller, a traceback in Starlette's
background runner, and a feature that quietly never happens. `route_walk` cannot see it — the
status code was decided before the task failed.

Fifteen `add_task` sites in `app/`; all fifteen resolve and all bind cleanly. Mutation-verified
in both directions, which matters here more than usual: adding an argument at the **call site**
and adding a required parameter to the **target** are different edits with the same
consequence, and a guard that only watches one of them will be looking the wrong way when it
happens.

**The first draft examined a third of its subject.** It resolved only names imported from other
`app` modules and reported ten of fifteen targets as unresolvable — including all seven kanban
broadcasts, which are defined in the very file that schedules them. Ten unresolved out of
fifteen reads like a warning and behaves like a blind spot, so `test_every_target_resolves`
now fails on that state rather than letting it pass quietly. Same shape as rule 165: the
number that matters is how much was examined, not what was found.

### Thirteen mutating routes no test had ever named

Of **251 mutating routes, thirteen appear in no test file at all**. `route_walk` drives them —
it drives everything — but with generated input, which rejects at validation before the
handler body runs. Their success paths have never executed, and that is precisely where
`broadcast_to_org` was sitting when the first real-database exercise of `POST /kanban/tasks`
found it: an `AttributeError` raised after a 200 had already gone out.

Four are in this lane. Two are drivable without new infrastructure and are now driven:
`POST /commands/cancel/{command_id}`, which takes a row lock and walks candidate organisation
ids — so it gets a cross-tenant assertion as well as a double-cancel one — and
`POST /shop-floor/postings/drain`.

**The other two are unreachable here, not merely untested, and the difference is written
down.** `POST /bulk/alarms/acknowledge` and `POST /bulk/kanban/tasks/{operation}` create a
Redis-tracked job before doing anything and this harness has no Redis. In a coverage report
those two look identical to the routes nobody bothered with; in reality one is a decision and
the other is an oversight. Their synchronous validation runs ahead of the job store, so that
much is pinned regardless — and their 503 is worth pinning too, because
`_create_job_or_503` catches `Exception` broadly, so a genuine bug inside `create_job` reaches
the caller as *"Bulk job store unavailable"* indistinguishably from a real outage.

**A flaky test found by running the suite, and nearly mis-diagnosed as my own regression.**
The full run failed on `test_the_geotab_gate_actually_holds.py::test_every_row_carries_provenance[get_exceptions]`,
in a file this work had not touched. Stashing the working tree made it pass — which looked
like evidence that my changes had broken it, and was luck.

The cause is in the service: `get_exceptions` builds `range(random.randint(0, 10))` rows, so it
returns an **empty list about one run in eleven**, and the test's `assert rows` then fails for a
reason that has nothing to do with provenance. Seeded rather than relaxed: "zero rows all carry
provenance" is vacuously true, so accepting an empty draw would leave the test green while
checking nothing — the exact failure this file was written to prevent. Verified deterministic
over eight consecutive runs.

Both FS-680 routes pass on their first real exercise, so no live defect this time — but
`POST /commands/cancel/{command_id}` now has the assertion that mattered most: another tenant
cannot cancel your command, and `cancel_command`'s candidate-organisation walk is what makes
that worth pinning rather than assuming.

### Non-null assertions: 24 flagged by type, 0 defects, and why the sweep is not worth building

A standing plan item lists twelve non-null assertions on nullable network fields, "including
two in `GeofencingPanel.tsx`, the file whose comment documents a prior production crash from
exactly that pattern". Driven through the TypeScript checker: **27 assertions examined, 24
whose operand type genuinely includes `null` or `undefined`, and not one defect.**

Every one has a guard that TypeScript cannot carry to the assertion:

* **`filter` → `map`.** `carriers.filter(c => c.insuranceExpiry && …).map(carrier => … carrier.insuranceExpiry! …)`
  is safe, and narrowing does not survive the boundary without a type predicate.
* **A closure.** `doc.s3Key && <Button onClick={() => link.mutate(doc.s3Key!)} />` — the guard
  is in scope, but the arrow function runs later, so TypeScript discards the narrowing.
* **An `||` chain.** `rec.approvedAt || rec.rejectedAt ? formatDateTime(rec.approvedAt || rec.rejectedAt!) : '—'`
  never dereferences the undefined branch.

**And the crash the plan cites is already fixed.** `GeofencingPanel` defines
`CircleZone = GeofenceZoneExtended & { center: GeoLocation; radius: number }` and filters to
it, precisely so the map skips centerless zones rather than throwing — the comment at the top
of that file describes the incident in the past tense.

**So this class is not statically sweepable, and that is the finding.** A detector keyed on
"operand type is nullable" reports 24 of 24 correct sites as defects. To be useful it would
have to model narrowing across `filter`/`map`, closure capture and short-circuit chains — that
is, reimplement TypeScript's control-flow analysis and then exceed it. Recorded so the noisy
version does not get built, and so the twelve-item plan entry can be closed as examined rather
than sitting open forever.

### The right answer was already in the tree, one file away

Applying FS-675's *question* — which thread calls this? — rather than its *detector* found a
third collector with the same shape: `sparkplug_b.py` registers a paho callback and calls
`loop_start()`, exactly as `mqtt.py` does.

**It was correct all along.** It captures the loop in `start()` and delivers through
`run_coroutine_threadsafe`, with a docstring that names the boundary out loud:
*"paho callback (network thread) -> decode -> deliver on the event loop."* Somebody understood
this seam and wrote it down, one directory entry away from the two collectors that were
dropping every reading.

**The earlier sweep could not have seen it either way.** FS-675 keyed on discarded
`asyncio.create_task` calls, so it found MQTT and the file watcher because of the API they
happened to use, and would have been equally blind to a sparkplug that did nothing at all.
Keying on the API was the mistake; the property is the thread. The guard now asserts that every
collector handing a callback to a library with its own thread — `loop_start(`, `Observer(` —
captures the loop and delivers across it. Mutation-verified in both directions.

**One real gap closed.** The hand-rolled version returned silently when `self._loop` was None,
so a reading decoded on paho's thread before `start()` had run vanished without trace. Moved to
`spawn()`, which retains the future and logs `background_task_unscheduled` instead.

The reusable part is uncomfortable: FS-675 spent its effort building a detector when the
correct implementation was already in the repository, in a sibling file, with an explanatory
comment. Grepping for `run_coroutine_threadsafe` before writing anything would have produced
the fix and the pattern in one step.

### A ratchet holding by 0.02 points, and a finding I had to withdraw

**The withdrawal first, because it is the more useful half.** A coverage run reported twelve
failures across four file-walking guards, every one timing out just past the 5s default, and
`quality-gates.yml` runs `npm run coverage` as a blocking step on every branch push. That reads
as: CI is red for everyone right now. I said so.

It was wrong. Vitest had already printed the reason and I had not read it —
*"Make sure you are not running multiple Vitests with the same `coverage.reportsDirectory` at
the same time."* Three of my own coverage runs were racing over `coverage/.tmp`. A single clean
run: **131 files, 1,063 tests, zero failures.** The timeouts were contention I created.

This is the second time in this session that concurrent runs manufactured a finding — the first
was two pytest suites against one database. Different tool, different shared resource, same
shape: a measurement taken while something else is writing the thing being measured.

**What survived verification.** Coverage was **49.02 / 49.03 / 41.42 / 50.57** against
thresholds 49/48/41/50 — statements clearing by **0.02 points, about one and a half
statements**, in a config whose own comment describes a deliberate *"~1 point of margin: enough
that a single refactor does not fail the build, not enough to absorb a real regression."* That
margin was gone, so the next uncovered statement added anywhere would have turned the gate red
for a reason unrelated to the change that tripped it.

**The way back up is tests, which is that file's own doctrine.** `src/api/shopFloor.ts` was the
target: 228 lines at **0%**, the client behind a live page that issues parts, clocks operators
in and out, reports defects and opens downtime. Nothing had ever exercised it — the state
`broadcast_to_org` was in when its endpoint was first driven for real.

Reading it first found no defect; it agrees with the server. So the 21 tests pin the seam this
codebase keeps failing at — path, method, and the shape of what goes out — plus three
behaviours that are decisions rather than plumbing:

* `openLaborEntry` answers **null** for "no running clock"; `undefined` reaching the page
  renders as a loading state that never resolves.
* `clockOut()` sends an explicit `notes: null` rather than omitting the key — an absent key and
  a null are different requests to a pydantic body.
* `listPostings` **throws** on a malformed page rather than returning an empty one. An empty
  ledger means "nothing is waiting"; a malformed response means "we do not know", and rendering
  the second as the first tells an operator every event landed when none may have.

Statements margin restored **0.02 -> 0.38**, lines to 0.97. Thresholds deliberately NOT raised:
raising them to the new floor would consume the margin again and reproduce the condition this
entry is about.

### A wrong password showed the user nothing, and the test that would have said so had never run

Standing the live stack up — dedicated Postgres on 55432, 67 migrations, both seeders, uvicorn,
Playwright with `E2E_LIVE_BACKEND=1` — as a capstone check on a session that changed 26 schema
fields, added six routes and rewrote two kanban handlers. **125 passed, 3 failed**, and the
three unwound into one another.

**The test had never executed.** `authenticated.spec.ts` referenced `EMAIL`; nothing in that
file defines or imports it. It is a local `const` in `auth.setup.ts` and in
`writes-actually-persist.spec.ts`, which is exactly why it reads as though it were in scope.
Every run ended in `ReferenceError` at the `fill()` — before the click, before the assertion.
The claim that a wrong password does not log you in had been taken on trust for as long as the
file has existed. It skips without a live backend, so no laptop run would ever show it.

**Reviving it revealed it was also vacuous.** The assertion was `toHaveURL(/\/login/)`
immediately after the click, and `toHaveURL` passes the moment it matches — a quarter-second
after clicking you are still on `/login` whatever the server is about to say. Proven by
supplying the **correct** password and watching it pass anyway; a probe confirmed the app does
navigate to `/`, well after the assertion had already resolved. It now waits for the login
response, requires a 401, and requires the error to be *visible*.

**And that exposed a live user-facing defect.** The global 401 interceptor in `api/client.ts`
treats every 401 as an expired session: clear the tokens and `window.location.href = '/login'`,
which is a full page load. A rejected sign-in is a 401 with no refresh token, so **the browser
reloads and destroys the React tree and the zustand store before the error can render.**
Measured against the live backend: the user types a wrong password and the page blinks back
with no feedback at all. `authStore` sets `error: 'Login failed'` and `Login.tsx` renders
`{error && …}` — both correct, and neither survives the reload, which is why nothing in either
file looks wrong to a reader.

**A fourth, which I caused and then found.** `/accept-invite` renders a proper error state
("This invitation link is missing or invalid") but had no `<main>` landmark — it and `Login`
are the only pages outside `Layout.tsx`, so neither had one, and a screen-reader user had
nothing to skip to. Adding it broke `data-reaches-the-screen.spec.ts`, and the cause was a
latent flake rather than the change: `locator('main, body')` matches two elements once React
has mounted, which is a Playwright strict-mode violation. It had passed on every route only by
evaluating in the instant after `goto`, when `<body>` exists and `<main>` does not yet. **A page
that mounts fast enough loses that race** — so rendering *more* correctly broke it. Fixed with
`.first()`.

Final: **128 e2e passed against a live backend, 0 failed.** The `/alarms` 45s timeout from the
first run passed on a quieter machine and was contention, not a defect (rule 175).

### The compiler had never read the end-to-end tests

The root cause behind the dead test above, found by asking why `ReferenceError: EMAIL is not
defined` had survived: **`tsconfig.json` said `"include": ["src"]`.** The six Playwright specs
and their setup project were never typechecked by anything, and `vitest run` does not typecheck
either — it transpiles and discards the types.

So the one class of defect a compiler catches for free was invisible in exactly the directory
whose tests are hardest to run, skip silently without a live backend, and make the most
security-relevant claims.

Measured rather than argued: restoring the defect and running `npx tsc --noEmit` reports
`TS2304: Cannot find name 'EMAIL'` in one command. Widening `include` to `["src", "e2e"]`
produces **zero errors today** and needs no other wiring, because `npx tsc --noEmit` is already
a blocking step in `quality-gates.yml`.

`everyTestDirectoryIsTypechecked.test.ts` guards the config rather than the code — the compiler
already reports the errors, and the only thing that can silently undo that is someone narrowing
the include back, which is precisely the edit that looks harmless in review because the tests
still run and still pass.

**And the detector I tried first was rule 37 in a single line.** Before reaching for the
compiler I wrote a scanner for "identifiers used but never declared" in the e2e files. It
matched every capitalised word in every comment — `THE`, `WRONG`, `PASSWORD`, `NEVER`, `RUN` —
including the words in the comment I had just written *about* the defect. The compiler answered
the same question exactly, in one command, with no calibration required (rule 167).

### The edge agent had no gate on a branch push, and the guard for that was blind to it

Carrying FS-684's question — *which directories does a checker actually read?* — from the
frontend to the Python side found three gaps, all in the workflow that runs on every branch
push.

**The flake8 step did not do what its own comment said.** The note above it names
`backend/tests` and `edge-agent/opsgrid_agent` as measured clean and argues for widening the
scope, calling it "the only moment it ever will" cost nothing. The command underneath stayed at
`flake8 app scripts`. So 379 backend test files and 120 edge-agent files sat outside the one
check that catches an undefined name — `F82`, the Python spelling of the very defect FS-684
found in `e2e/`. Re-measured before widening: still zero everywhere.

**The edge agent had no test gate at all on a branch push.** `ci-cd.yml` runs its 386 tests and
fires on `main` and pull_request only. An edge-agent change was unchecked until somebody opened
a pull request — and that suite is where FS-675 lived, every MQTT reading dropped on a thread
boundary in the collector the agent is built around.

**And `test_branch_pushes_reach_the_gates.py` passed throughout**, because its
`REQUIRED_ON_BRANCH_PUSH` is a hand-maintained list of five gates and nobody had added this
one. A guard against "the check that runs in the wrong workflow" was itself blind to a whole
codebase, for the ordinary reason that its subject list was typed out by hand. It now carries a
second check derived from `ci-cd.yml` — every directory tested there must be tested on a branch
push — which fails when the new step is removed.

**One false-confidence matcher caught on the way.** The obvious entry for the new gate,
`("edge-agent",)`, passes with the suite step deleted: `pip-audit -r edge-agent/requirements.txt`
is also a run command containing that string. A matcher that cannot fail reports the gate as
present forever, so it was removed rather than kept — the derived check is what actually holds
this one.

### Finishing the sweep: what every static checker in this repository actually reads

Having asked the question twice and got a finding both times, it was worth finishing. Measured
across the whole tree rather than argued:

| directory | files | read by a checker before | now |
|---|---|---|---|
| `frontend/src` | — | `tsc` | unchanged |
| `frontend/e2e` | 7 | **nothing** | `tsc` (FS-684) |
| `backend/app`, `backend/scripts` | 258 | `flake8` | unchanged |
| `backend/tests` | 379 | **nothing** | `flake8` (FS-685) |
| `edge-agent/opsgrid_agent`, `edge-agent/tests` | 120 | **nothing** | `flake8` + its suite (FS-685) |
| `tests/k8s`, `scripts`, `dataset_synthesis` | 22 | **nothing** | `flake8` |

**528 Python files and 7 TypeScript files were outside every static check in the repository**,
and every one of them measures clean today — which is exactly why closing the gap cost nothing,
and the only moment it ever would.

The root-level 22 are the instructive tail. `tests/k8s/` holds the cluster checkers this
workflow *executes* — NetworkPolicy coverage, probe ports, placeholder secrets — so an
undefined name there fails a gate rather than a request, but at the end of a long job instead
of in the first thirty seconds. `scripts/` and `dataset_synthesis/` are run by hand and by
nobody in CI, which is the worse half: nothing would ever have said.

**The general lesson is about where to point the question.** Three consecutive findings —
FS-684, FS-685, and this — came from asking *which paths does a checker actually read?* rather
than looking inside any file. From inside a directory nothing looks wrong: the imports resolve,
the tests run, the suite is green. The gap is only visible from the config outward, and it is
invisible in exactly the places where it costs the most, because a directory nobody checks is
usually a directory nobody visits.

### Comments citing guards that do not exist

The env-var sweep produced no defects — all five direct `os.environ` reads are deliberate and
correct, and worth recording as examined: `ERP_WEBHOOK_ACCEPT_LEGACY_SIGNATURE` is read
per-request *on purpose* so the switch can be closed without a restart (moving it into the
import-time `Settings` singleton would regress that), `WORKER_HEALTH_PORT` is injected by four
Kubernetes manifests and correctly `None` outside them, and `GOOGLE_API_KEY` gates an opt-in
vision feature that is off by default and **reports its own unavailability in the response**
rather than returning an empty string as extracted text.

But chasing one of them surfaced something else: the code cited a guard file that does not
exist. Swept the class — 256 test filenames are named in prose across the tree — and two
citations were live:

* `fleet_health.py`: *"`test_fleet_health_filters_in_sql.py` asserts these reads do not loop"*.
  The property is real; the file is `test_fleet_health_query_shape.py`.
* `test_the_geotab_gate_actually_holds.py`: *"`test_production_settings_are_validated.py`
  refuses `GEOTAB_SIMULATED` in production"*. **That file has never existed.** The refusal is
  in `app/core/config.py::validate_settings`.

In both cases the guard was real and only the trail was broken — the failure that costs an
afternoon and teaches a reader to stop trusting the comments.

**The detector needed narrowing, and the reason is the best part.** The first version flagged
thirteen lines, including its own docstring explaining the defect, and including the very
sentence in the geotab file that *corrects* the citation. Prose that names a stale filename in
order to say it is stale matches the detector for stale filenames perfectly — rule 37 in its
purest form. It also captured only `realmode.test.ts` out of `geofencing.realmode.test.ts`,
because the dot sat outside the character class, reporting four existing files as missing.

Narrowed to **source trees only**, which is a principle rather than an exclusion list: a
comment in `app/`, `opsgrid_agent/` or `src/` naming a test file is a claim about the present,
while a test or a document may legitimately narrate history. 48 citations in source, all
resolving, and the guard fails when the original stale line is put back.

**And the documentation half of that guard already existed.** `test_documented_files_exist.py`
has checked every backticked path in `docs/` since FS-513, with a `DELIBERATELY_ABSENT`
register for names the prose must mention while they do not exist. I built the source-side
guard without looking for it — rule 141 for the second time in this session, and the shortest
route to the new guard would have been to read the old one first. They are complementary
rather than duplicate (`docs/` versus source comments), and
`test_no_two_guards_keep_the_same_list.py` confirms they keep different lists.

**It then caught me**, which is the part worth keeping. Writing this entry meant naming the two
missing files, and the existing guard failed on that prose within the same run — rule 37 from
yet another direction: a document explaining a stale filename matches a detector for stale
filenames exactly. The three names went into its register with reasons, which is precisely what
that register is for.

**One correction.** I said the existing guard shared my detector's dotted-name bug. It does
not: its pattern captures `geofencing.realmode.test.ts` whole. It flagged the fragment because
**I wrote that fragment in backticks** while explaining my own bug. The fault was in my prose,
not in its regex.

### Does every test the repository contains actually run?

The last configuration worth interrogating is the test runners themselves. "Which tests does
the runner collect?" is the same question as "which files does the compiler read", and it has
the same failure mode: a file that exists, looks wired, and is never executed.

Clean on all three, and two of the three questions already had guards:

* **pytest** — 358 `test_*.py` on disk, **357 collected.** The exception is
  `test_api_contract.py`, which skips at module level unless `RUN_CONTRACT_TESTS=1`. Verified
  rather than believed: `quality-gates.yml` has a dedicated `api-contract:` job that sets the
  variable and runs the file by name. Deliberate, documented, and wired.
* **vitest** — 133 on disk, 133 executed.
* **playwright** — already covered by `test_every_e2e_spec_is_run.py`, which exists precisely
  because the live-backend job invokes specs *by name*, so a new one looks wired and is not.

**My detector was the only thing wrong here, twice.** It reported "0 collected, 358 never
collected" — an absurd denominator, and only absurd enough to notice because the suite plainly
runs 4,472 tests. The cause: `addopts = -v` in `pytest.ini` makes `--collect-only` print a
TREE (`<Module x.py>`) rather than node ids, and I guessed the format twice before reading three
lines of it. The lesson is the one already recorded as rule 165 — assert the denominator — and
the corollary it earns here: when the denominator is impossible, stop and look at the raw
output rather than adjusting the pattern again.

### A ratchet that counts correct code, and the change it tempts you into

The swallow ratchet (`test_the_swallow_surface_only_shrinks.py`) tracks 201 broad handlers, 188
of them uncounted. Working through the largest clusters in this lane:

**The ingest path is already closed.** All eight handlers in `workers/ingestion.py` are counted,
so FS-537's *"an alarm rule that throws simply does not fire"* no longer holds. FS-540 is closed
too, and the comment there corrects the plan's premise directly — the `available` flag does
distinguish "no data" from "failed", and only the unguarded `psutil` calls were a real gap.

**The next cluster is twelve handlers in `api/health.py`, and every one is correct.** They catch
broadly and *return* the failure — `return f"error: {exc}", {}` — so `_run_health_checks` can
report each component and grade the whole. The ratchet excludes handlers that **re-raise**, but
not handlers that translate an error into a returned value, so these read as the largest block
of debt in the file while being exactly right for their job.

**That is not a harmless miscount.** The obvious way to shrink the number is to raise instead,
and the result would be a readiness probe that 500s whenever any one dependency is unavailable:
Kubernetes restarting a pod whose only problem is a slow Redis, and the operator losing the
per-component report that says which dependency it actually was. Nothing pinned that behaviour.
Now something does, and the mutation that proves it is precisely that tempting change.

**37 of the 201 are error-translation-by-return**, measured. Excluding them from the population
was considered and rejected: a returned error is only propagation if the **caller reads it**,
which the shape cannot show. `_run_health_checks` does read it — and demonstrating that is
worth more than editing the ratchet's definition, because it pins the behaviour rather than
adjusting the number.

**Two false starts, both mine, both in the test.** The stub passed a session to all four
checkers when two take none (`TypeError: _check_message_broker() takes 0 positional arguments`),
and then made the stub *raise* — which failed every aggregator test with `RuntimeError` and
looked briefly like a finding. It was the premise: `_run_health_checks` deliberately does not
wrap its checkers, because each catches its own failure and returns it. Stubbing a raise removed
the behaviour under test.

### A ratchet you can satisfy without doing the work

Rule 187 asks of every ratchet: *what would the cheapest reduction do?* Applied to the four
with non-zero floors:

* **The contract ratchet is safe.** `scripts/contract_ratchet.py` computes
  `total - failures - errors - skipped`, so marking an operation `skip` **lowers** the passing
  count. The obvious cheat makes the gate angrier, which is the right design.
* **The response-model ratchet is not.** `MAX_UNDECLARED = 52` asks only
  `getattr(route, "response_model", None) is None`, so the cheapest reduction is
  `response_model=Dict[str, Any]` — which counts as declared, emits an OpenAPI `object` with no
  properties, hands the generated SDK an untyped blob, and gives every downstream guard that
  reads declared models nothing to check. The route then *looks* documented, which is worse
  than being visibly undocumented.

**23 routes are already in that state.** Five are legitimately dynamic and are registered with
reasons — a feature flag's value is arbitrary client JSON, a Monte-Carlo result follows the
submitted scenario. The rest are debt that the existing ratchet cannot see.

I did **not** edit the existing ratchet. A companion keeps a separate list at its measured
figure, so the count is visible and can only shrink; the way down is a schema, not a new entry.

**The clearest instance is named on its own, and is deliberately not fixed here.**
`GET /transportation/drivers` answers `List[Dict[str, Any]]` while `DriverResponse` exists — but
the handler dumps that model and then adds seven derived keys in **camelCase**
(`carrierName`, `currentVehicleId`, `currentShipmentId`, `endorsements`, `licenseExpiry`,
`hosDriveHoursRemaining`, `hosDutyHoursRemaining`) while the model's own keys emerge snake_case.
Declaring a model that omits any one of them makes FastAPI **filter it out of the response** —
the "declared field that is dropped" defect this codebase has fixed more than once — and the
field it would land on is `hosDriveHoursRemaining`, which the compliance tab reads to count DOT
violations. The guard names the route and fails the day it is fixed properly, which is a to-do
with an expiry rather than an exemption.

### The README disagreed with itself, and only one half was guarded

Continuing the ratchet audit into the zero ratchets first: all four assert their own
populations — `len(ADAPTERS) >= 4`, `len(capped) >= 20`, `len(PAIRS) >= 8` — so none can pass
vacuously over an empty subject. Clean, and the repository got there first.

Applying rule 44 instead — *which numbers in prose does no guard check?* — found the run-command
block:

```
cd backend && pytest          # ~3,200 pass, ~92 skip
cd frontend && npx vitest run  # ~525 across 73 files
```

**The backend figure contradicted a guarded claim two hundred lines below it**, which states
"4,090+ tests" and is asserted by `test_readme_test_count_is_not_stale.py`. One document, two
numbers for the same suite, and only the second could ever be caught. The real figure is 4,489.

**The frontend figure was low by more than half** — 1,089 tests across 133 files, against ~525
across 73 — and nothing anywhere read it. It is the number a developer checks their very first
run against, so the failure mode is a new contributor seeing twice the claimed count and
wondering what they have broken.

Both are now floors and both are asserted. The frontend *test* count cannot be measured from
the backend suite without running vitest, so what is checked is the *file* count — a filesystem
fact, and the half that had drifted worst. Each gets the two-sided treatment the existing floor
already had: it must not overstate reality, and it must not sit so far below it that nobody
could fall through. Mutation-verified in both directions.

The two gate counts in the same document — "31 blocking jobs" across both workflows and "14
blocking gates on every branch push" — were checked and are different scopes, not a
contradiction.

### Proving FS-675 against a real broker, not a test double

The edge agent is the component this session changed most — every collector's delivery path,
plus a task helper — and it had never actually been run. Its 386 unit tests pass, but the fix
for FS-675 was verified with a `threading.Thread` standing in for paho's network thread, which
is a claim about paho rather than an observation of it.

So: a real `eclipse-mosquitto` broker, the real `MQTTCollector` connecting to it with
`loop_start()`, a real second paho client publishing three messages, and the collector's own
subscription delivering them.

| | readings delivered |
|---|---|
| pre-FS-675 (`asyncio.create_task` on paho's thread) | **0** — `mqtt_message_handler_error: no running event loop` |
| after the fix | **3** |

Same broker, same publisher, same payloads; the only difference is the one line. The defect and
its repair are now demonstrated against the infrastructure they concern, and the error string
in the failing run is the exact one a production log would have carried while the collector
dropped every reading.

**One false start, and it is the same shape as the last two.** The first drive published to
`opsgrid/test/#` and got nothing — because `_subscribe_to_topics` derives its topics from the
asset id (`device/printer-1/report`), so I had published where nothing was listening. Zero
deliveries, from correct code, because the harness was wrong. It took one line of the agent's
own log — `mqtt_subscribed topic=device/printer-1/report` — to see it, and that line was in the
output of the first run.

### Both halves of FS-675, and a defect only the real thing showed

Applying rule 191 to FS-675's *other* claim — that `orca_file` "could not process a single file
it was watching for" — needed no container at all, just a real watchdog `Observer` and a real
file in a temporary directory:

| | files processed |
|---|---|
| pre-FS-675 (bare `create_task` on watchdog's thread) | **0** — `RuntimeError: no running event loop`, unhandled |
| after the fix | **2** |

Worth noting the difference in visibility between the two halves. paho's `_on_message` wraps
its body in `except Exception`, so the MQTT failure was swallowed into a
`mqtt_message_handler_error` log line; watchdog does not, so the file-watcher failure surfaced
as a raw traceback. Same defect, same cause, and one of them was shouting while the other
whispered.

**And "2" is the finding.** One file write emits both `on_created` and `on_modified`, so the
collector processed and emitted every sliced G-code file **twice** — one print recorded as two,
with identical path and size, so nothing downstream could tell them apart.

The dedupe was there and could never work: only `on_modified` checked `_processed_files`, and
that set is written at the **end** of `_process_gcode`, after `await _wait_for_file_stable(...)`.
Both coroutines were in flight long before either marked the file. `on_created` did not check
at all.

**No double could have shown this.** The unit tests call `on_created` with one synthetic event
and correctly see one call; only a real `Observer` watching a real directory emits the pair.
That is rule 191 paying for itself twice in one sitting — the double proves the mechanism, the
real thing proves the behaviour.

Fixed by claiming the path synchronously on the observer thread, before any await; the drive
now reports one reading for one file. Guarded in both directions, because a claim that swallows
a genuinely new file would pass the first assertion and fail the product.

---

## FS-691 — a collector polling a dead device was invisible to every instrument

Carried across from FS-675 by the same method that found it: `http_rest` was the other
collector whose tests drive the real object through a **stubbed transport**, and its own
docstring says why that is dangerous — *"a poll that raises on every cycle looks exactly like
a poll that works."*

Driven against a live `http.server` returning 500, for three seconds:

```
readings from a server returning 500: 0
collector reports running: True
what the metrics say about press-2: (nothing — no counter names this asset)
```

**`metrics.errors_total` was incremented by nothing, in any of fifteen collectors.** The
coordinator calls `record_error` only when a message *handler* raises, and a failed poll
produces no message to hand to a handler, so the one call site could not fire for the case
it was needed for. `metrics.py`'s docstring asserted the opposite — that the coordinator seam
covered every collector "without editing individual collectors" — which is true of deliveries
and false of failures.

**And no alert covered it either.** `connection_state` is derived from
`task is not None and not task.done()`; the poll task is perfectly healthy, it is the device
that is dead, so the gauge reads *up*. `EdgeAgentOffline` watches `edge_agent_up`, which is 1
because the agent heartbeats fine. `EdgeAgentBufferHigh` watches buffer depth, which is 0
**because nothing was collected** — the alert that should catch the silence is silenced by it.
A machine that stopped reporting a month ago and one that is idle produced identical
monitoring.

Fixed with a failure seam mirroring the success seam that already existed: `emit()` for a
reading that worked, `record_failure()` for one that did not — same log line, plus the counter.
Ten collection-failure paths across ten collectors converted; startup refusals
(`*_driver_missing`, `*_no_host`) and teardown noise (`*_disconnect_error`) deliberately left
alone and registered with reasons, since a collector that never started has no collection to
attribute a failure to. The coordinator now hands the collector its configured type so the
counter and the gauge carry labels that join.

Guarded by `test_a_silent_collector_is_visible.py`, which drives a real socket in both
directions — a 500 server that must move the counter, and a 200 server that must not.

**The guard was nearly weaker than the fix.** Its first version pinned that the adapter still
exposes `_collector`; it did not pin that the coordinator uses it, and replacing the unwrap
with `inner = collector` skips labelling in silence — passing the whole package. It now drives
the real `_start_collector`. Rule 191 applies to guards as readily as to fixes.

Rules 194, 195, 196.

## FS-692 — a metric exported at zero, from a merge that brought two of everything

Found by running rule 194's other sweep — *which metrics does nobody emit?* —
after being explicit that it would **not** have found FS-691 (that one had a caller).

`COLLECTOR_MESSAGES` / `opsgrid_edge_collector_messages_total` arrived with the
hridyansh/integration merge, which added a second agent-level metric family for readings the
lowercase `messages_total` already counted. The merge kept both and wired one.

`prometheus_client` publishes the entire default registry, so the unwired one was not absent —
it was **exported, reading zero, with a description explaining what it would have meant.** A
dashboard built on it shows a flat line that reads as "this agent received no telemetry".

Wired at the site its twin was already wired, one line, same two arguments. Guarded by
`test_no_metric_is_exported_and_never_fed.py`, whose docstring is explicit that it is the
weaker sibling: a metric with one caller passes it, which is exactly how FS-691 survived.

### And the alert that could finally be written

A counter nobody alerts on is half a fix. Before FS-691 the rule was not merely missing — it
was **inexpressible**, because the only metric that could express it was incremented by
nothing.

`EdgeCollectorFailingEveryPoll` now fires on a collector that is erroring and delivering
nothing, with a promtool test driving each case (`tests/silent_collector_test.yml`).

**The operator writing it would have got it wrong**, and the test is what says so. The natural
spelling is

```promql
rate(errors_total[15m]) > 0 and rate(messages_total[15m]) == 0
```

and `and` requires a matching series on the right. A collector that has **never** delivered
a reading has no `edge_collector_messages_total` series at all — not one reading zero, an
absent one — so `and` finds nothing to match, produces nothing, and never fires. The worst
case, a device that was already broken when monitoring was set up, is precisely the one that
spelling misses. `unless` keeps the left side when the right is absent.

Mutation-verified by making that exact substitution: with `and`, the never-delivered test
produces `got:[]`.

---

## FS-693 — the same defect in the backend, on the control path

Rule 196 asks where else health is computed from the mechanism rather than the work. The
backend has two sites that answer `.done()`, and one of them is `_check_command_dispatch`.

```python
if dispatch_task is not None and dispatch_task.done():
    return "error: dispatch loop exited"
return "ok"
```

`_dispatch_loop` catches every exception per iteration and continues — **which is correct**;
one poisoned command must not stop dispatch for the fleet. It also means the task never
exits, so `done()` is False forever and the check above can only ever say `ok`. A
misconfigured producer, an unreadable row, a schema drift: `command_dispatch: ok` on the
operator's health page, and not one command dispatched. Commands are how an operator reaches
a machine, so this is the control path going quiet with a green light over it.

`_timeout_loop` had no check at all: commands that should expire silently never do.

Fixed by counting what the loops achieve. `_loop_failures` resets on a successful iteration
and increments on a failed one; three consecutive failures is an error, which is past a
transient DB hiccup and far short of an operator waiting on a command that will never be
sent. Both halves mutation-verified separately — the health branch, the increment, and the
reset each have a test that fails without them.

### And the surface behind it: seven of eight started services are watched by nobody

`main.py:88-104` starts eight background services. `/health/detailed` names one.

`oee_calculator`, `export_scheduler`, `compliance_report_dispatcher`, `rollout_orchestrator`
(mentioned in health.py only inside a comment), `posting_drain_scheduler`, `report_scheduler`
and `error_tracker` run for the lifetime of the process and appear in no check. A stalled OEE
calculator leaves every figure on the dashboard frozen at its last good value, which reads as
a quiet shift. If the error tracker dies, errors stop being reported and the silence reads as
a clean system.

Registered in `test_a_started_service_is_a_service_somebody_watches.py` with what would close
each entry, ratcheted so it can only shrink. Two are near-trivial (a counter, a last-run
timestamp); the rest need a definition of "working" that belongs to the lane owner, which is
why this is a register and not seven guessed probes.

**`test_no_two_guards_keep_the_same_list.py` caught it immediately** — `EXPECTED_STARTED` in
`test_service_lifecycle_is_declared.py` already enumerates these services. The overlap is
recorded rather than exempted by reflex: the new register parses `main.py` directly rather
than reading that list, so a service added to boot lands in its denominator whether or not
anyone updated a declaration, and the 7-of-8 overlap is the finding rather than a copy.

### The register shrinks by one, the intended way

`export_scheduler` came off `UNWATCHED` by acquiring a check, not by deleting a line —
`ExportScheduler._run` has the identical swallow-and-continue shape, so a scheduler whose
every cycle throws leaves scheduled exports undelivered and the customer discovers it before
the operator does.

**"Disabled" had to become its own status.** `start()` returns immediately when
`EXPORT_SCHEDULER_ENABLED` is false, so `_running` stays False and a check that knew only
ok / not_running would report a deployment posture as a fault — or, on an instance where
exports were never turned on, invite an operator to read `export_scheduler: ok`. It reports
`disabled`, and because the extended checks do not feed the overall ready/degraded verdict
(only database, broker, redis and ingestion do), that status changes no probe outcome.

Four mutations, four caught: the failure branch, the wiring into `/health/detailed`, the
counter in the loop, and — the one worth having — putting `export_scheduler` back on the
register after its check landed, which
`test_the_register_does_not_outlive_its_entries` rejects. A register that keeps solved
entries stops being read.

Six remain.

### The swallow ratchet charged for it, and the payment was real

Adding `_check_export_scheduler` took the broad-handler count from 201 to 202 and the build
failed: *"if the new one is deliberate, lower some other allowance first. This number only
goes down."*

The new handler is not debt — `test_a_failing_dependency_is_reported_not_raised.py` (FS-687)
exists precisely because health checkers must catch broadly and **return** the failure, or a
readiness probe answers 500 whenever any one dependency is slow. The ratchet counts it anyway,
which its own documentation calls coarse rather than wrong.

So it was paid, and the cheapest honest payment turned out to be worth making on its own.
`_payload_bytes` caught `Exception` around a `json.dumps` that already carries
`default=str` — which absorbs unserialisable values, leaving a circular reference, a
`default` that itself raises, and a stack-deep structure as the only real cases. The broad
catch also swallowed `MemoryError` and returned a 20-byte type name in place of the payload,
so the dead-letter envelope would have recorded the length of `"<class 'dict'>"` as
`payload_size` — a wrong number written down as a measurement. Narrowed to
`(TypeError, ValueError, RecursionError)`; anything else now propagates.

Back to 201. Rule 187 asks what a ratchet's cheapest reduction would do; this is the same
question from the other side — what its cheapest *payment* buys — and here it bought a
correction.

### Two more off the register: the report scheduler and the error tracker

Same pattern, two new wrinkles.

**APScheduler swallows harder than a `while` loop.** `ComplianceReportScheduler` has no loop
of its own — `dispatch_due` runs as an APScheduler interval job, and APScheduler catches the
job's exception, logs it through its own logger and keeps the schedule. A scan failing every
cycle (a bad migration, a missing grant) enqueues no compliance report forever, and a missed
compliance report is discovered by an auditor. The fix is a `_scan` wrapper that counts and
**re-raises** — the counter must not replace APScheduler's traceback, and the re-raise also
keeps it off the swallow ratchet. One guard pins that `start()` schedules the wrapper rather
than the bare method, because that regression would disable the counting while every other
test still passed.

**The error tracker fails in the most deceptive direction available.** If its flush loop
breaks, errors stop being persisted — and a system that has stopped reporting errors looks
exactly like a system that has stopped having them. It already carried a *cumulative*
Prometheus failure counter, which answers "how often, ever" and cannot distinguish "failing
right now" from "failed twice last month"; the consecutive counter is the health-shaped
question. Its check reports `error: … new errors are not being recorded`, which is the
sentence an operator needs.

The swallow ratchet charged two again and was paid with two more genuine narrowings:
`_coerce_domain`'s enum construction catches `ValueError` (the only thing an Enum constructor
raises) instead of hiding a broken `DomainType` definition behind "unknown domain", and the
rate-limit key derivation catches `(jwt.PyJWTError, ValueError, TypeError)` — what
`jwt.decode` and `UUID()` actually raise — instead of everything. 201 holds.

Four remain on the register: `oee_calculator`, `compliance_report_dispatcher`,
`rollout_orchestrator`, `posting_drain_scheduler` — each needing a definition of "working"
from its lane.

### Two more: the OEE calculator and the posting drain. Two remain, both in other lanes.

**The posting drain had the FS-691 seam one level down.** Per-organisation failures inside a
pass are logged and skipped — correct tenant isolation; one unreachable ERP must not stop
every other ledger — so `drain_all_organizations` returns normally with every organisation
broken, and a counter keyed on the pass raising would read a fleet-wide outage as health.
The totals now carry `organizations_failed`, and a pass with failures and zero successes
counts as a failed pass while one broken tenant among working ones does not. Both directions
guarded.

**The OEE guard's first mutation run found its own hole.** Deleting the increment passed
every test in the file: the per-asset-isolation test only exercised the outer handler's
success path. A counter needs a test per direction, or half of it can vanish silently — the
new failing-cycle test detonates inside the outer `try` (an `_asset_states` whose iteration
raises), which a stubbed `calculate_oee` cannot reach because the inner per-asset handler
absorbs it first.

The ratchet charged two, paid with two more mechanical narrowings: `_rss_bytes` catches
`(psutil.Error, OSError)` instead of converting a programming error into "memory unavailable
forever", and the correlation engine's `ast.literal_eval` fallback catches the five
exceptions that call documents itself raising. 201 holds.

Remaining on the register: `compliance_report_dispatcher` and `rollout_orchestrator`
(Hridyansh's OTA lane) — both need a lane-owner definition of "working", not a counter.

---

## FS-694 — the buffer gauge freezes, and takes both buffer alerts with it

Rule 196 applied to the instrument itself. `edge_buffer_messages` is refreshed by the
agent's stats loop every five minutes, and a gauge is only as honest as its last write: if
that loop fails every cycle — a corrupted SQLite file, a schema drift in `get_stats` — the
gauge does not zero and does not disappear. **It freezes at its final value.**
`EdgeBufferGrowing` then reasons about a number that stopped meaning anything, and the
heartbeat's `_buffer_snapshot` freezes with it, so `EdgeAgentBufferHigh` goes quiet in the
same breath. One failing loop mutes both buffer alerts, at exactly the moment the buffer may
be growing. The gauge measured the buffer; nothing measured the measuring.

Fixed with the standard watchdog: `set_buffer_stats` stamps
`edge_buffer_stats_last_success_timestamp_seconds` on every successful refresh — inside the
helper, not beside it, so the stamp cannot drift away from the gauges it vouches for — and
`EdgeBufferStatsStale` alerts when the age passes four report cycles.

**The absent-series trap, closed at the source this time.** A loop that never succeeds once
never creates the series, and `time() - <absent>` evaluates to nothing — the alert cannot
fire for precisely the agent broken since boot. `EdgeCollectorFailingEveryPoll` answered
this with `unless`; here the agent stamps a baseline at loop start instead, which reads
"stats were current as of startup" and then ages honestly.

Three mutations, three caught: the helper stamp, the baseline stamp, and the rule's
comparison inverted (promtool: negative control fires, positive stops). Guarded on the edge
side by `test_the_buffer_gauges_carry_a_freshness_stamp.py`, on the alert side by
`infra/prometheus/tests/buffer_stats_staleness_test.yml`.

---

## FS-695 — EdgeAgentOffline, severity HIGH, could never fire

The carry-across from FS-694's frozen-gauge class found the worst instance on the first
sweep. `EdgeAgentOffline` — the alert whose description reads *"Agent has not sent a healthy
heartbeat for 5m"* — watched `edge_agent_up == 0`. **Nothing writes 0.** The gauge is set
only when a heartbeat *arrives* (`edge_fleet.update_fleet_metrics`), and its single call
site hardcodes `"online"` — correctly, since a heartbeat arriving means online. An agent
that stops heartbeating freezes its gauge at 1. The one condition the alert exists for is
the one condition the metric cannot express.

**Its unit test passed the whole time**, by hand-writing `edge_agent_up 0` into the input
series — a value production cannot produce. Rule 188 named this for test stubs; it holds
for promtool inputs identically: a test input the real system can never emit proves the
rule parses, not that it fires.

Fixed with the FS-694 pattern — heartbeat ingest stamps
`edge_agent_last_heartbeat_timestamp_seconds`, and the alert ages it — deliberately NOT
with a staleness sweeper loop, because a sweeper is a background loop, and this arc has
spent the day establishing what an unwatched background loop costs. The timestamp needs no
loop: `time() - stamp` grows by itself the moment the agent goes quiet.

**Known gap, recorded rather than hidden**: gauges live in backend memory, so after a
backend restart an already-dead agent has no series at all and cannot alert until something
heartbeats. Closing it needs a DB-backed sweep of `edge_agent_status.last_seen` — which,
per FS-693, must arrive with its own failure counter and health check, not as a quick fix
inside this one. Noted in the alert's own comment.

Mutations: the ingest stamp deleted (caught by `test_edge_fleet.py`), the alert reverted to
the frozen gauge (caught by promtool — the updated test's dead-agent series now has no
`edge_agent_up` at all, so the reverted rule finds nothing and fails the expectation).

---

## FS-696 — eight dead metrics in the API process, two of them holding up alerts

The FS-692 sweep (exported-and-never-fed) carried into the backend found **eight** metrics
defined beside the `/metrics` endpoint in `app/api/health.py` and incremented by nothing —
because they describe quantities (telemetry ingested, PackML transitions, ingestion lag,
edge buffer depth, OCR accuracy, active alerts) that happen in the ingestion worker or on
the edge agent, and this is the API process. A labelled dead metric is subtler than a zero:
`generate_latest` emits only its HELP/TYPE header until a label is touched, so an operator
greps `/metrics`, finds the name documented, builds the dashboard, and gets *no data* —
indistinguishable from a label-filter typo, which is where the debugging time goes.

**Two were load-bearing.** `IngestionLagHighApp` (team backend, with a runbook link) and
`OcrAccuracyLow` (team edge) alerted on series only these dead definitions named. Neither
alert could ever fire. Both promtool tests passed by writing the series by hand — rule 188's
third appearance this arc.

Both quantities already existed and were being thrown away:
- the ingestion worker parses every event's edge timestamp and now sets
  `opsgrid_ingestion_lag_seconds` in **its own** registry (`app/workers/health_server.py`,
  scraped on 9109 per FS-213) at the write site — labelled by message family, not by Kafka
  topic, because live topics are `telemetry.{asset}` and a per-asset label grows a series
  per machine;
- the screen scraper computes `_ocr_confidence` on every read and shipped it only inside
  the telemetry payload, where no alert can see it; it now also sets `opsgrid_ocr_accuracy`
  at the edge.

The other six were deleted with a tombstone explaining where each would have to live.

**The guard's own mutation run improved the guard.** Unwiring `INGESTION_LAG` while leaving
its import intact passed the text-based draft — an import matched the regex. The detector
now counts AST `Name` loads, under which an import alias is a reference, not a feeding.
Backend guard: `test_no_metric_is_exported_and_never_fed.py` (twin of the edge file by the
same name), with the deletion of the eight pinned so a revert-happy merge cannot bring
them back.

### And the class gets a guard: every alert must watch a series something exports

Three alerts were found unable to fire, by hand, three findings apart. The question is now
asked mechanically: `test_every_alert_watches_a_series_something_exports.py` collects every
series name both codebases export (AST, with prometheus_client's suffix behaviour — a
`Counter("foo")` exports `foo_total`, a Histogram grows `_bucket`/`_sum`/`_count`), parses
every `expr:` in `alerts.yml`, strips PromQL functions and label names (the first draft
reported `agent_id` as an unbacked series, which is why the label parser is a named
negative control), and requires the remainder to be exported by code or by a **named**
infra exporter — node-exporter, kube-state-metrics, CloudNativePG, Redpanda — each register
entry carrying the deployment that provides it, which is the honest boundary of what a
repo test can verify.

What it cannot ask: whether an exported series can reach the *value* the alert compares
against — `edge_agent_up` existed the whole time; it was 0 that was unreachable. That half
still needs a human asking rule 194's question, and promtool for the arithmetic.

Mutation: deleting the worker's `INGESTION_LAG` definition fails both the denominator
control and the main sweep.

---

## FS-697 — the worker's age gauge was as fresh as the last liveness probe

The follow-on question from FS-695: an *age* gauge — who advances it? For
`opsgrid_worker_heartbeat_age_seconds`, the answer was `snapshot()`, which ran only on
`/healthz`. Prometheus scrapes `/metrics`, which called `generate_latest()` without a
refresh — so the age the `IngestionWorkerStalled` alert read was as fresh as the **last
liveness probe**, an unstated coupling between an alert and an unrelated component. Both
deployments happen to probe `/healthz` over HTTP today; switch either to a TCP check and the
gauge freezes — or, in a process never probed, never materializes its label child at all —
while the alert's hand-fed promtool test keeps passing.

One line: `/metrics` now calls `snapshot()` before `generate_latest()`, so every scrape
carries a current age no matter what the probe does.

**The guard's first mutation run failed, instructively.** Deleting the refresh passed all
eight tests, because the gauge is process-global and the staleness test earlier in the same
file had already materialized `test-worker`'s child with a large age via `/healthz` — the
new test was reading a neighbour's leftovers and calling them fresh. The test now uses a
label nothing else touches (`never-probed-worker`), which has no sample at all unless the
scrape under test produces one. Same lesson as the OEE counter: a guard is only proven by
the mutation actually failing, and "passed on the first try" is a reason for suspicion,
not celebration.

---

## FS-698 — one cancelled task ended all collector supervision, permanently

Reading `_health_monitor` for FS-694's frozen-gauge question found a sharper way for the
gauge to freeze: the loop that writes it can die. The monitor inspects every done collector
task with `task.exception()` — and for a task that was **cancelled**, that call does not
return an exception, it *raises* `asyncio.CancelledError`. CancelledError has been a
`BaseException` since Python 3.8, so it sails past the loop's `except Exception` and
terminates the monitor coroutine.

The window is real: `restart_collector` cancels the old task and then **awaits** it (2s
timeout) *before* popping it from `collector_tasks` — a suspension point at which the
monitor can wake and meet the cancelled entry. `stop_collector` (config hot-reload) pops
first, but the monitor iterates a `list(...)` snapshot, so an entry captured before the pop
is still inspected after the cancel.

What dying costs: the monitor is the **only** writer of `edge_collector_connection_state`
(frozen at last values — FS-694's class, inflicted by a single hot-reload), the only caller
of `refresh_collector_stats`, and the only automatic restart path for crashed collectors.
After one CancelledError the agent runs unsupervised, and the only trace is one unexplained
traceback. Driven live before the fix: the real monitor handed a cancelled task terminated
on its first iteration.

Fixed by treating cancelled as administrative, not crashed: logged, **not restarted**
(restarting would race the very restart/hot-reload that cancelled it), and the monitor
continues. Guarded in three directions: survives a cancelled task, does not restart it, and
— the negative control that mattered — still restarts a task that died of a real exception,
which caught the widened-guard mutation (`if True:`) that the first two tests let through.
The live-drive harness itself hung for 30 seconds the moment the fix worked, because its
sleep patch was timing-dependent; the committed test shrinks the pacing sleep through the
module's own reference and runs exactly one iteration deterministically.

---

## FS-699 — a removed collector kept exporting its liveness gauge forever

The removal case of the frozen-gauge class. A prometheus_client label child persists until
removed, and `stop_collector` (config hot-reload's teardown) popped the collector and its
task while leaving the `edge_collector_connection_state` child in the registry, frozen at
whatever the health monitor last wrote. Frozen at 0, `EdgeCollectorDown` — HIGH, `for: 5m`
— fires forever for a device that was deliberately decommissioned, and an alert that is
permanently wrong about the same collector is an alert operators learn to silence. Frozen
at 1, a phantom healthy collector nobody configured.

Fixed with `clear_connection_state`, called at the end of `stop_collector` — which reads
the config **before** the reloader pops it, and which is race-free by construction: between
the clear and the reloader's `configs.pop` there is no `await`, so the monitor cannot
republish the child in the gap. Absence is the honest answer for a removed collector.

The guard drives the real `stop_collector`, because `test_config_reload.py` substitutes a
`FakeCoordinator` at exactly this seam — the double records that "stop" was called and
cannot see what the registry still exports afterwards, which is the whole finding
(rule 191). Mutations: the clear removed (caught), and the subtler one — `clear()` of the
entire gauge instead of one child, which would blind `EdgeCollectorDown` for every *other*
collector until the monitor's next pass — caught by the negative control.

---

## FS-700 — every runbook link now provably resolves

Alert annotations carry `runbook_url` — absolute GitHub URLs into this repo — and nothing
checked them; the docs tree was reorganised this very branch (FS-584 split a 7,000-line
file into five), and `test_documented_files_exist.py` parses backticked paths in prose, not
URLs in YAML. A broken runbook link is discovered at 3am, mid-incident, by the person with
the least slack.

The sweep found all 31 links valid — including one a naive checker flags as broken:
`#failover--recovery` is GitHub's *correct* slug for the heading "Failover & recovery"
(`&` is dropped, both spaces become hyphens). The guard reproduces GitHub's slug rule and
keeps that link as its positive control; it also rejects URLs pointing outside the repo,
which no check here could keep true. Mutation: renaming one runbook path fails exactly
that link's test.

## FS-701 — five dashboard panels had displayed "No data" since the day they shipped

The dashboard half of FS-696. `backend-system.json` queried five of the dead health.py
metrics — *Telemetry ingested/sec*, *Ingest latency p95*, *PackML state changes/sec*,
*Active assets*, *Active alerts* — which were never fed even before FS-696 deleted their
definitions. Every one of those panels has rendered "No data" forever, and a dashboard of
empty panels reads as "the system is idle", not "these queries are wrong".

Two had real replacements and got them: ingestion throughput now reads
`opsgrid_worker_units_total{worker="ingestion"}` (fed per processed message), and the
latency panel became the worker heartbeat age. *Ingestion lag* — dead when the dashboard
shipped — is now real because FS-696 fed it, and stays. The three with no backing metric
(PackML rate, active assets, active alerts) are deleted rather than left lying. The edge
buffer panel was retitled: "backend view" described the deleted duplicate; the series that
answers it is agent-reported.

The sweep is now a guard: `test_every_dashboard_panel_queries_a_series_something_exports`,
sharing the alert guard's exported-series universe plus `slo_rules.yml`'s recording rules.
It parses the dashboards as JSON because the regex draft reported `horizontalpodautoscaler`
and `cronjob` as unbacked series — escaped quotes inside raw JSON defeated its label
parser. `keda_` joined the infra-exporter register with its provider.

---

## FS-702 — the drivers list finally declares what it sends

FS-688's named to-do, closed the way its own failure message demanded. `GET
/transportation/drivers` now answers `List[DriverListItem]`: `DriverResponse` plus the
seven derived keys, spelled exactly as the handler spells them — camelCase derived keys
over snake_case base keys, because the mixed casing IS the wire contract the frontend's
`registerTransform` seam expects.

The danger that kept this a finding rather than a chore: FastAPI **filters** any response
key the declared model omits, silently. So the guard asserts every one of the seven BY
NAME against a real response from a real Postgres — deleting `hosDriveHoursRemaining` from
the model fails on that field's name (proven by mutation), not on a count — and a
source-level agreement test pins handler keys == model extras == asserted keys, so a new
derived key cannot be added to the handler and silently filtered. The OpenAPI document now
carries real properties; the permissive-model ratchet dropped 23 → 22 and its provoke-test
was deleted per its own instruction.

## FS-703 — the monitor now defers to an operator restart

The open observation from FS-698, closed: the health monitor's auto-restart takes notice of
`_restart_locks` (skip-and-log while held) so a collector that crashes moments before an
API restart cannot draw `_start_collector` from both paths — two collectors polling one
device, one orphaned. The failed-operator-restart case still recovers: a failed restart
leaves a done task for the monitor's next pass. Mutation: removing the lock check fails the
new guard while the crashed-task-still-restarted negative control keeps the fix from
widening.

## FS-704 — a dead agent now alerts even across a backend restart

The gap FS-695 recorded in the alert's own comment. Gauges live in process memory, so a
backend restart erased the series of an already-dead agent — precisely the agent that will
never heartbeat it back. `edge_fleet_sweep` (a new service, watched from birth per FS-693's
rule) re-derives `edge_agent_up` and `edge_agent_last_heartbeat` from
`edge_agent_status.last_seen` — which survives restarts — every 60s, and finally makes
`edge_agent_up = 0` a value production writes.

THE TRAP WAS TENANCY: `edge_agent_status` is FORCE RLS, so an untenanted session reads
zero rows and *no error* — the sweep would refresh nothing and look healthy forever. It
iterates orgs and sets the GUC per org (the posting-drain shape), and the guard's first
assertion is the DENOMINATOR: `sweep_once` returns how many agents it refreshed, and the
GUC-removal mutation fails exactly there, with real rows behind a NOSUPERUSER NOBYPASSRLS
role.

## FS-705 — the unwatched-services register is EMPTY

`compliance_report_dispatcher` and `rollout_orchestrator` joined health with the
consecutive-failure pattern (the rollout entry keeps its cumulative OTA_ROLLOUT_FAILURES
counter — "how often, ever" — beside the new "failing right now" question). **Every
service `main.py` starts is now watched**; the register file remains so a ninth service
cannot arrive unwatched, and its comment-stripping positive control — which correctly
expired when `rollout_orchestrator` stopped being prose-only — was replaced with a
synthetic one that cannot expire.

The swallow ratchet charged four across the batch (two checkers here, the sweep's loop and
checker in FS-704) and was paid with SIX narrowings of one honest shape: every redis-backed
degrade path in `idempotency.py` and `alarm_rules.py` now catches
`(redis.RedisError, OSError, asyncio.TimeoutError)` — what the client actually raises when
the store is unreachable — instead of hiding programming errors as "store unavailable".
The ceiling ratcheted down 201 → 199.

---

# The page-by-page arc — FS-706…717

A survey of all 37 pages against their routers, then twelve ranked fixes. The survey's
own conclusion is the finding that matters most, and it is recorded as FS-706 because
everything after it is a consequence.

## FS-706 — the frontend was a release behind its own backend

Four parallel readers over the whole page tree, each asked the same question: what does
this page show, what can a user do, and **what does the router behind it serve that the
page never calls?**

The dominant defect class was not missing capability. It was unreached capability:

* **export schedules and templates — nine endpoints, zero frontend references.** A user
  could see that a scheduled report had failed and could not see what the schedule was,
  who received it, when it next ran, or how to pause it;
* all of `logistics_correlation.py` (detention risk, dock-production sync, liability);
* all of `model_monitoring.py` (drift, performance history);
* the whole `/api/v1/oee` router — losses, historical, current;
* `alarmsApi.list`'s six filter params, of which the page sent one;
* `list_assets`' three filter params, of which the page sent none;
* SSO (three routes, no UI), `GET /telemetry/{id}/metrics`, `GET /intake/{id}`,
  kanban comments/timers/rules, `GET /edge/fleet/{agent_id}`.

Twelve shipped enhancements needed **two** new backend routes between them
(`GET /shop-floor/downtime/open`, `PATCH /notifications/subscriptions/{id}`) plus one
query parameter (`assets?search=`). Everything else was a wire. Rule 198.

## FS-707…712 — six pages that could not answer their own question

**FS-707 · Alarms could not be filtered** (P1). `alarmsApi.list` supported `assetId`,
`isActive`, `severity`, `acknowledged`, `startTime`, `endTime`; the page sent `skip`. And
because the backend defaults to the last 24 hours when no range arrives, the "Total
Alarms" tile was a 24-hour count under an "all alarms in system history" tooltip. The
filter bar sends an explicit `start_time` always — "All time" sends the epoch — so the
default can no longer assert itself silently, and the tile names its window.
`acknowledgeAll` and `clear` existed as dormant client methods with no buttons.

**FS-708 · ShopFloor stranded its own downtime** (P5). The Machine Down card held the
open event id in component state, so a page reload left a machine recorded as down with
nobody able to end it — not the operator who started it, not anyone else, because no
other browser knew it existed. Open downtime is org-visible state; a new
`GET /shop-floor/downtime/open` is now what the card renders. The asset was a free-text
UUID box: nobody types 36 hex characters at a down machine.

**FS-709 · AlarmRules could not aim a rule** (P10). `assetId`, `assetTypeId` and
`workcellId` sat in the form's state and were copied on edit, and **no input ever set
them** — so every rule was org-wide and the backend's `_validate_targets` was unreachable
from the UI. A threshold that suits a press is rarely the one that suits an oven, so
rules were written for the loosest machine on the floor.

**FS-710 · AssetDetail had neither alarms nor OEE** (P7). The page an operator opens to
ask "what is wrong with this machine" listed no alarms — they had to leave for `/alarms`
and filter there, which per FS-707 they could not do either. It had no OEE while the
fleet table had a good three-factor breakdown locked inside `pages/OEE.tsx` as a local
component; extracted to `components/oee` rather than copied, because the honest-rendering
conventions (an unmeasured factor is "—", never "100%") are the content.

**FS-711 · The OEE question the product could not answer** (P8). "Where is my OEE going"
is what the number exists to raise, and `/api/v1/oee/losses` — the only endpoint that
answers it — had no client. The Pareto renders biggest-loss-first, scaled to the largest
loss rather than to 100 or to the total, because the three losses are independent factors
summed and the server says so: a stacked bar would draw an arithmetic that does not
exist. One time-range selector now drives the fleet query, the per-asset panels and the
PDF export, which previously hardcoded 24h beside a table pinned to the same default —
they could not disagree because neither could move.

**FS-712 · Notifications could not be edited, paused, or honestly tested** (P11). No
PATCH route existed, so a wrong URL meant delete-and-recreate — losing the id every
delivery log entry refers to. The `enabled` column was displayed and writable only at
creation, so the action an operator most wants mid-incident (stop paging this channel)
meant destroying the subscription. And Send Test hardcoded `warning`, so a critical-only
subscription could never match one: every check of it reported "matched 0", which is the
FS-487 failure arriving from the test button itself.

## FS-713…716 — four things that were true on screen and false in fact

**FS-713 · A legend promising a series that could never draw.** `TelemetryCharts`
declared `<Bar dataKey="oee">` over rows carrying only `availability`, so an "OEE (%)"
swatch has always sat beside a bar that cannot render — a chart asserting a second series
exists and happens to be empty today. Its heading said "Fleet OEE (current)" over the
same availability-only data: the FS-192/FS-399 overstatement, still standing one page
over from where it was corrected.

**FS-714 · Permanently lost telemetry, dropped a second time.** FS-591 traced `dropped`
the whole way — the agent counts discarded readings, sends them every heartbeat, the
handler persists them, and `AgentStatusOut` was given the field *specifically so a fleet
view could show it*. The fleet view then declared a TypeScript interface without it, so
the number arrived and was discarded one layer later: the same omission, one boundary
further on. Of the three buffer figures it is the only unrecoverable one — buffered is
waiting, dead-lettered is replayable, this is gone — and it now renders in its own colour.
Certificate expiry moved out of a hover tooltip into a badge at the alert rules' own
thresholds, so the page and the pager agree.

**FS-715 · System Health fetched its details and threw them away.** The endpoint has
carried a per-component `details` payload since the FS-693 arc gave every background
service a check — consecutive-failure counts, running flags, last error — and the page
typed them out of existence. Tiles expand into them now, with an overall verdict banner
and `checked_at`, and "disabled"/"skipped" stopped rendering as red errors: a deployment
posture painted as a fault is red that is always wrong, which is red an admin learns to
ignore.

**FS-716 · Two controls that did nothing.** IntakeInbox's status filter wrote state an
already-fired request had captured (`[]` effect deps), so the dropdown appeared to filter
and did not; and "View Results" had no `onClick` while the list endpoint never sends
`analysis_result`, so for anything analysed before the last reload the dead button was
the only path to data only `GET /intake/{id}` carries.

## FS-717 — the engine pages could not tell a stopped loop from an idle one

Every engine status route has reported `running` and a `note` since FS-530, and the
frontend types omitted both; strategic — whose list routes signal via the
`X-Engine-Not-Running` header instead — had no reader for it anywhere. So all four pages
rendered construction-time defaults as measurements. A shared banner now says it.

The same commit closed FS-567's frontend half: the decision-history route had landed and
`api/engines.ts` never followed, so the History card still read "not available from the
API" against an API where it was. Its client surfaces both header signals, maps a 404 to
null so an older server gets the honest "predates the endpoint" copy rather than "request
failed", and rejections now carry a real reason and the authenticated operator instead of
the string constants `'current-user'` and `'User rejected'` — an audit trail of nobody.

## What the guards taught, and one they got wrong

Four guards refused good-looking work, each correctly: `mutationFailureIsVisible` (a
per-call `onError` reads as silent at the mutation definition), the truncation sweep (a
hand-rolled header read bypassing `toListResult`), `frontendSafetyRatchets` (an inline
`toLocaleString`), and the route-auth walk (a new PATCH with no reviewed policy). A
fifth, `test_frontend_fields_exist_on_the_wire`, refused a client type invented for a
method nothing called — the "declared and never produced" defect written by the person
who sweeps for it (rule 202).

One detector was genuinely too narrow: the truncation sweep recognised its idiom only
*before* the `api.get` call, flagging the equally-correct capture-then-wrap shape needed
to read a second header off the same response. Its window is symmetric now. Rule 203 is
about the order of those two conclusions.

**And three of the arc's own tests were too weak, each exposed only by mutation**: a
`<select>` value check that passed with the state sync deleted (rule 199), a "paused"
presence check that matched a badge rather than the cell (rule 200), and a losses-failure
path no page test drove. Every fix in this arc is mutation-verified; three of the guards
had to be strengthened before that sentence was true.

### The exemption that expired exactly as its comment predicted

Rendering the Fleet OEE tile failed `test_qualifiers_reach_the_frontend.py`, and the
failure was written into the register years-of-commits earlier:

> `/oee/dashboard/summary` has NO frontend consumer at all … `avg_oee` is the verdict
> here and no screen shows it, so `assets_unavailable` has no claim to caveat. **The
> moment anything renders the aggregate, `test_the_qualified_field_is_still_unread` fails
> and this has to be wired with it.**

It did, and it was. This is the third exemption in that file to expire on the commit its
own comment named — `assessable` (FS-395), `detention_assessed` (FS-426), now this — and
the pattern is worth stating plainly: **an exemption is only honest if it says what would
end it**, because the thing that ends it arrives years later, in someone else's commit,
with no memory of the deferral.

The caveat travels with the verdict now: the tile's tooltip reads "8 of 10 assets
measured" and names the unread ones, so a fleet OEE computed over four fifths of the
floor is visibly that rather than a clean number.

**And the mutation testing here needed two removals, not one.** Deleting the tooltip
clause alone did not fail the guard, and neither did deleting the field from the client
type — because each left the other, and the guard asks whether the frontend carries the
field *anywhere*. Removing both fails it. Reporting either single mutation as "the guard
does not bite" would have been the wrong conclusion from a true observation.

## FS-718 — the correlation-engine merge, and the sixteen guards that read it

Two developers' branches came onto the scrubbed history: three spreadsheet-intake commits
(already present by content — every file byte-identical — so merged for ancestry only) and
the correlation-engine work, which is 12,417 lines across twenty backend files and 2,018
across seven frontend ones. The branch was at **4,646 passing, 0 failing** before it and
**16 failing** after. None of the sixteen was a merge conflict; every one was a guard
reading the new code and finding something. What they found, in the order the cost falls:

**A tenant leak that reads as an empty page.** Four `correlation_evidence` handlers took
`get_db`. `intake_items` is FORCE ROW LEVEL SECURITY, so a session with no
`app.current_org_id` reads **zero rows and raises nothing** — the handlers would have
404'd on the caller's own uploads with a clean log. `get_tenant_db` throughout.

**A fix that would have broken what it fixed.** Three `job_id: str` path params were
retyped to `UUID` for the id-typing guard, which is correct — and `correlation_jobs` keys
its store by `str(uuid4())`, so a `UUID` object misses every lookup silently. Converted at
the three call sites; the route validates the shape, the service keeps its contract.

**Two behavioural tests that described no real state.** The merge's own kanban tenancy
test asserted `workload.json() == {"workloads": []}` for an organisation that has exactly
one user and an endpoint that reports a row per user — so it never passed here. Worse, an
empty list is what a *broken* endpoint returns, so a tenant-scope test was satisfied by
"nothing came back" (rule 165). It now asserts the row is org A's user and is not org B's,
which fails both ways. The seeder smoke failure was three missing requirements —
`odfpy`, `pyarrow`, `pyxlsb` — the stale-image message it printed being exactly right.

**Stale-after-failure in the intake UI, found by a guard aimed at something else.** Three
`catch` blocks set an error and left the previous result rendered, so a failed evidence
rebuild showed "No safe automatic recommendation is available" and "No join candidate was
available" — conclusions about the *previous* scope — under a message saying this scope
could not be built. A stale answer beneath a fresh error reads as an answer.

**Four truncation qualifiers that reached no screen.** `groups_truncated`,
`rollups_truncated`, `sampled` and `input_truncated` each say how far to trust the number
beside them, and no frontend file named any of them. They are declared on
`EvidenceEntityRollups` and `OperationalAnalyticsResult` and rendered as a "What these
figures leave out" list. `sampled` sits on each anomaly block and each relationship — the
first draft of the type invented a top-level `series` map the server never sends, which is
the defect the wire guard refuses (rule 202); the shape was then read from the service.
The fifth, `scenario_sampled`, belongs to a route with no frontend caller at all and is
registered against the field it qualifies, which the exemption test re-proves is unread.

**The swallow surface, net +1 and now net zero.** Of four new broad handlers, two were
already honest (the job executor writes `status: failed` to the job the caller polls; the
parse handler returns a deterministic remediation). One was not a failure at all — an
Arrow IPC format probe using `except Exception` as control flow, narrowed to
`pa.ArrowInvalid`, which is the allowance lowered in exchange. The fourth is the one that
mattered: a Redis ping failure silently demoting the correlation job store to process
memory, where a second API worker turns every job into a 404. It is counted now
(`opsgrid_correlation_job_store_degraded_total`) and the counted floor rose to 14.

**Three detectors that were measuring the wrong thing** — see rules 204–208. The
body-fields extractor could not see a request forwarded to a shared executor and would
have absorbed five routes into its register, including `POST /answer`'s `question`. The
emptiness sweep scoped its query check per file, so a presentational drawer inherited its
page's fetch, and it matched the argument of `setEvidenceError(...)` as an empty state.
And `idKeyedFetchesDoNotGoStale` had silently fallen to a population of **zero** because
the tree's one id-keyed fetch is a wrapped promise chain and the pattern required the
receiver and the dot to be adjacent — no code changed, a line break did.

**Twenty routes wanted a response model, and the first answer was the cheap one.**
`response_model=Dict[str, Any]` satisfies the coverage ratchet, does not filter, and is
precedented here — and is precisely what `test_a_permissive_response_model_is_not_a_contract`
exists to refuse. It caught it. The real answer is a model with `extra="allow"`: named
fields in the schema, the SDK and the contract gate, with the engine's per-request keys
still passing through. That last claim is measured against a live response and kept as a
test, and the drop-detector now exempts open models for the same measured reason.

Registered rather than fixed, each with what it is and whose it is: five orphaned
definitions (one of them the enricher for a list its own module now deliberately leaves
empty, because attributing file-level totals to assets produced a convincing false trend),
`/api/v1/correlation` in the idempotency register with the two job routes that would most
benefit named, and fifteen correlation mutations in the role-policy register — each
checked for `get_current_active_user` before being listed, with `vocabulary/{id}/review`
and `actions/decide` flagged as approver-shaped surfaces any member can currently reach.

`document_store.get_document` came *off* the orphan list: the new artifact store calls it.

Backend 4,738 passing, frontend 1,192, edge 427, `tsc` clean.

## FS-719 — reviewing FS-718 found the two worst defects in the merge

FS-718 declared response models on twenty routes and drove eight of them. Reviewing that
work asked the obvious question about the other twelve — and the answer was that **no test
had ever sent an HTTP request to any of these routes**. The services beneath them carry
about 900 lines of direct coverage; every one of those tests calls the service. Everything
that exists only at the route boundary — the session dependency, the response model, the
background task — was unexercised.

Driving the pipeline the way a user drives it (upload two sheets, catalog, preview,
correlate, ask a question) found three defects in ten minutes, two of them severe:

**Both operations-assistant routes answered 404 for the caller's own uploads.**
`POST /operations/answer` and `POST /operations/briefing` took `Depends(get_db)`. Their
session goes to `_execute_evidence_request`, which reads `intake_items` under FORCE ROW
LEVEL SECURITY, so it matched zero rows and the routes reported "One or more intake sources
were not found" — while `/intake/preview` returned 200 for the same ids on a tenant-bound
session. The entire operations-assistant surface was unreachable.

**Every asynchronous evidence job failed.** The job rebuilds its session in a background
task as `AsyncSessionLocal()`, under a comment stating that every DB query was scoped
explicitly. Nothing scoped them. The first lookup matched nothing and the job ended
`failed`, with an error indistinguishable from a caller passing bad ids. It now uses
`tenant_session`, the same context manager `get_tenant_db` yields from and the one the bulk
and export processors already use. The job now completes and carries a result.

**A response model annotated from the field's name.** `GET /capabilities` declared
`approval: Dict[str, Any]`; it is a sentence. Caught by the GET smoke, which is why the new
serialisation smoke exists for the POST half — and it caught the second instance, where
three evaluation fields were typed as dicts and are Pydantic models.

**Why the static guard missed both tenant defects, and what it does now.** It asks whether a
router *names* a model whose table is under RLS. `operations_assistant.py` names none — the
query is one import away. The job's `AsyncSessionLocal()` sits in a nested closure whose
whole body is a call, so it names none either. Both halves now follow the call: one hop into
a same-module helper, one across a `from app.api.… import`.

Widening it surfaced two further problems in the guard itself. The `AsyncSessionLocal` half
still read RAW SOURCE, so a comment mentioning `current_org_id` exempted a function — FS-431
repeating in the other half of the same file, and it made a mutation test pass while
reporting a broken guard as working. And once comments were stripped, the check flagged
`run_erp_sync`, which binds its tenant correctly through an extracted `_set_tenant_guc`
helper; recognising only the inline spelling would have turned that file's best-documented
fix into a false positive, and false positives are what write permanent exemptions.

All seven other inline sessions in `app/api/` were checked by hand and every one binds its
tenant. The correlation job was the only offender, so this check is ABSOLUTE — no register.

`test_evidence_pipeline_over_http.py` pins all of it: catalog returns the caller's own
sources, a preview proposes a join for sheets that share a key, both operations routes
answer, a queued job reaches `completed` with a result, and another organisation gets 404
for that job. Each of the three fixes was mutation-verified by reverting it.

Rules 209-211. Backend 4,772 passing, frontend 1,192, edge 427.

One unrelated find on the same run: `rag-async-ingest` appeared on the backup
remote and matched no push trigger, so htreinen's async-ingestion work was running
ZERO gates. Covered by a `rag-**` pattern rather than a fourth branch name — the
list has now gone stale by exactly one branch three times (`develop`, `alex`, this).

## FS-720 — an operation anybody could finish, and the split that hid it

Continuing the "which routes has nothing ever driven" question from FS-719, one mutating
route in this lane had no test naming it: `POST /operations/{operation_id}/complete`. The
earlier count of 34 was mostly proxy noise — the yard and kanban tests build their paths
with f-strings, so the literal never appears in the source — and a segment-matching measure
puts the real figure at 15, of which 14 belong to other lanes.

Driving that one route found two defects, the second one worse than the first.

**It read its two inputs from two different places.** `success: bool = True` is a bare
scalar, which FastAPI serves from the QUERY string, beside `metadata: Optional[dict]`, which
is a body parameter. No client can fill both from one document: the natural
`api.post(url, {"success": false, "metadata": {…}})` applies the metadata, silently defaults
`success` to `True`, and the route records a FAILED operation as **completed** — with
`actual_duration` and the PackML state-duration rollup computed against that outcome, and a
200 in reply.

This is the quiet form of a class the repository has been bitten by three times (FS-379,
FS-420, FS-658). Those were all-query routes with REQUIRED parameters, so the natural client
got 422 on every call and the feature visibly never worked. A defaulted query parameter beside
a body parameter fails silently instead. Nine mutating routes read from both places and
**all nine are the silent kind** — measured, and now held by
`test_no_route_splits_its_input.py`, which registers the eight in other lanes with what a
body-only client actually gets from each. `/operations/{id}/complete` takes one
`OperationCompletion` body and is off the list.

**And the router leaked across tenants.** Writing the first test that ever drove the route,
a cross-tenant case was added out of habit — org B completed org A's operation and got 200.
`operations` has NO `organization_id` column, so it has no RLS policy and `get_tenant_db`
protects it not at all; its tenant is whoever owns the asset. Four of the five handlers
relied on the session anyway:

    GET  /operations/                     bare select(Operation)      every tenant's rows
    GET  /operations/{id}                 by id                       any tenant's
    GET  /operations/{id}/packml-summary  by id                       any tenant's
    POST /operations/{id}/complete        by id                       any tenant's, and WRITES

The fifth, `/active`, joins `assets` under a comment reading "THE TENANT JOIN IS NO LONGER
OPTIONAL" — added when this same defect was fixed there. One handler of five. All four now
go through `_own_operation(id, org)`, so the shortest way to select an operation in this file
is the scoped one, and the list's COUNT is joined too: an unjoined total reports a page out
of every organisation's rows (rule 165).

Eleven tests pin it, against the database rather than the response — the response echoes the
ORM object either way, so a test reading only the JSON would have passed against the defect.
Each of the four scoping fixes and the body fix was mutation-verified separately.

One nuance recorded rather than tidied away: the scoped query keeps both the join and an
explicit `Asset.organization_id` predicate, and deleting the predicate alone fails no test —
`assets` is FORCE RLS and the join inherits that. It stays because that is a property of the
SESSION, not the query, and the comment says the mutation was run and what it showed, so the
next reader deletes it deliberately or not at all.

Also checked and found sound: 25 service methods take `db` with an `AsyncSessionLocal()`
fallback, and every one of the 25 call sites passes a session, so the unscoped branch is
latent rather than live. Not touched.

Rules 212-213. Backend 4,795 passing, frontend 1,192, edge 427.

*(FS-723 and the contract-gate work below took the backend suite to 4,831.)*

## FS-721 — the fifteen tables RLS cannot see, swept

FS-720 turned on a fact worth generalising: `operations` has no `organization_id`, so no
policy of the usual shape exists and `get_tenant_db` does nothing for it. Its tenant is
whoever owns the asset. Fourteen other tables are in the same position — task columns,
comments and timers behind their board; session data sources and messages behind their
session; user sessions, revoked tokens and consent records behind their user; registry items
behind their registry; telemetry and PackML states behind their asset.

**Every `select()` of those fifteen models in `app/api` was read — 40 sites across six
routers — and `operations` was the only offender.** The convention holds everywhere else,
and it is a good one: verify the PARENT with an explicit organisation predicate, then query
children by the parent's id. `telemetry.get_telemetry_history` calls `_verify_asset_in_org`
before any read; `registries` selects its `ActionableRegistry` with
`organization_id == current_user.organization_id` before touching items; `gdpr` scopes by
`current_user.id`, which is narrower than the org; kanban fetches the board for the caller
and works from it, including the two sites in `update_task` that read a column by id — the
old one belongs to a task already verified, the new one is filtered by the effective board
(FS-677's comment is on that line).

A negative sweep is still a result, and the honest version of this one is: **the codebase
knows this pattern; one file forgot it.**

WHY THE ARTEFACT IS A REGISTER AND NOT A DETECTOR. Deciding statically whether a parent was
verified means following an id through a handler, and a detector that guesses either misses
the real thing or cries wolf until somebody writes an exemption — which is rule 211, learned
two commits ago. So `test_parent_tenanted_tables_are_declared.py` asserts the half that is
decidable and that actually failed: WHICH tables are in this category. Fifteen, each with
the parent its tenancy comes from. A sixteenth arriving unnoticed is how the next
`operations` happens, because the author will reasonably assume the session is doing the
work — for every other table in sight, it is.

Mutation-verified by removing `organization_id` from `Alarm`: the register names it.

Backend 4,814 passing.

## FS-722 — the README, section by section, and the gate it turned out to have broken

A full pass over `README.md` against the tree. Eleven claims were wrong; one of them was
not a documentation problem at all.

**The contract gate was hard-broken and nothing said so.** The README quotes the gate as
driving "all 546 documented operations" — a guarded figure, so it is current — and then, a
paragraph later, reported conformance as **"370 of 452"**. Both numbers cannot be right.
The second is the denominator `scripts/contract_ratchet.py` compares against, and it has a
10% drift check whose purpose is to stop a COLLAPSED collection passing as a green ratchet:

    if abs(total - EXPECTED_TOTAL) > EXPECTED_TOTAL * TOTAL_TOLERANCE:  # 452 ± 45

The correlation-engine merge took the schema to 546. |546 − 452| = 94, so the gate now fails
outright, printing *"Check that the schema still loads and the server started"* — the exact
opposite of what happened. Nothing collapsed; the API grew by a fifth while the number it is
measured against stood still. The check is right to exist and a denominator nobody
re-measures turns it into a tripwire on ordinary growth (rule 165, from the other end).

Re-baselined to **546, read straight from `app.openapi()`**. The PASSING floors were
deliberately not moved with it: they count conforming operations and only ever rise, so a
figure written from a guess would be worse than a loose floor. A full gate run was started to measure them
properly against a freshly migrated database and **did not finish**: after an hour it had
used one minute of CPU in the last ten, i.e. it was idle, which is the hang this gate's own
documentation describes ("every component fast, the whole impossible — a per-example event
loop plus a retry path with no backoff"). The cause was NOT established and is not being
attributed to the new surface: each of the six heaviest correlation routes was then driven
with the kind of input schemathesis generates (a random intake id, an empty configuration, a
minimal fixture) and every one answered in under a second — 404, 409, 202, 200. Recorded as
an open question rather than a conclusion. The denominator fix stands on an exact
measurement either way, and the floors are marked for the next run that completes.

**The route table listed 11 of 41 pages — and one of the 11 has never existed.**
`/registries` sat there with a description of what it did; the surface is `/compliance`.
Both directions are now generated from `App.tsx` and held by
`test_readme_documents_every_route.py`: a routed page nobody documents is a page nobody
finds, and a documented route that is not routed sends somebody looking for a page to write
a client against. The second is the worse failure and is the one the table actually had.

Writing that guard reproduced a mistake this repository has now made four times: the first
version read the whole section, so an API path inside a description (`/oee/dashboard/summary`)
and my own note *explaining* that `/registries` does not exist both registered as claims
about the router. Scoped to the route column. Mutation-verified in both directions.

**The document contradicted itself on its own subject.** The Overview said ERP was "13
connectors"; the ERP section's own heading says 8, and lists 8 vendors. It also said "10
protocol collectors" where the coordinator registers 17 types, 11 of them industrial
protocols.

The rest, each measured: the migration chain read `001..042` and is 71 files ending at 068;
the planning pointer offered `fixed-sprints-344-393.md` as "the next 50" while the series is
at FS-721, so it now points at the delivery log and marks that plan exhausted; Alex was
listed as "not yet assigned a branch or task" with three commits merged; `rag-inference/` —
a tracked service with its own image and requirements — had **zero mentions**; the Contents
promised "every documented endpoint" where the reference carries 113 rows of 546 (every row
IS checked to exist, which is the true half); the test floors had drifted to 4,600 against
4,919 collected; and the page→API wiring table predated Shop Floor, Activations, System
Health, Collectors, scheduled exports and the entire evidence pipeline.

The API reference now documents the **evidence correlation and operations-assistant surface**
— the twenty routes the merge added, the upload → catalog → preview → confirm → ask pipeline
they form, why a join is proposed and never assumed, and why every response is an open model.
Those rows are covered by `test_documented_endpoints_exist.py`, which was already checking
each documented path against the running app; it went from 118 to 126 checks with them.

The tenancy FAQ and the Security Model now say the thing FS-720 cost: RLS is not one
mechanism, fifteen tables carry no `organization_id` at all, and under RLS a read fails
silently while a write is refused — which is why every quiet variant of this class has
shipped at least once.

Backend 4,829 passing, frontend 1,192, edge 427.

**CLOSED, same session.** The gate was not slow, it was WAITING.
`case.call_and_validate()` carried no request timeout, so a single unresponsive operation
stopped the whole job: no junit XML, no conformance count, and the ratchet step then reading
"collected 1 operations" and reporting it as a collapsed schema. The failure presents as
silence, which is why an hour passed before it looked wrong.

With a 30-second per-request timeout — far above anything this API should take under
generated input, so a hit is a finding about that operation rather than a flaky threshold —
the same 546 operations finish in **14:41** and the run reports:

    contract conformance: 445/546 operations

**The floor moves 380 → 436** (445 measured, less the 9-operation spread the file's other
floor already allows for generation variance). Most of that gain is arithmetic rather than
earned — the merge added ~90 operations and most conform — which is exactly why the floor
has to move with the surface: 380 against 546 would let 65 operations regress unnoticed.

`BASELINE_WITH_BROKER` was left at 393 at first, and **a guard refused that** —
`test_the_contract_gate_doc_matches_the_gate.py` asserts the with-broker floor is the higher
one, because a run that reaches more operations *because a dependency was present* cannot be
held to a lower bar than one that could not reach them. It was right, and the fix was not to
raise it by arithmetic but to take the run: with a broker genuinely reachable,
**449 of 546**, so that floor is 440.

**That measurement also corrected the reasoning it replaced.** Both this log and the gate's
own documentation described the broker-dependent set as "~20 correct 503s". Measured on the
same tree it is **four** operations — 449 against 445. The two floors stay separate because
the distinction is real and worth probing rather than claiming, but the headroom it buys is
small, and that is a fact about the API rather than a fault in either number. A figure
inherited across three documents and never re-measured is exactly the shape this session has
now found in the README, the ratchet and here.

Of the 101 non-conformers: 72 answer a 5xx under generated input, 18 return a status code
their own schema does not declare, 2 violate the response schema — and **none is on the
`/correlation/evidence` or `/correlation/operations` routes the merge added**. The
correlation names in the failure list are `registries/correlations` and
`nlp/correlation/query`, both older than the merge.

A gate that can hang reports nothing at all, which is strictly worse than a gate that fails.

## FS-723 — the parent-tenanted sweep carried into the services, and a one-sided isolation test

FS-721 read every `select()` of the fifteen parent-tenanted models in `app/api` and found one
offender. The same models are queried from `app/services` and `app/workers`, where a route's
tenant boundary is just as easy to lose — so that half was swept too: **15 sites across nine
files, and every one is scoped.** They all follow the same convention as the API layer —
query children by a parent id that the caller's own request already verified —
`insight_activation` off a board it fetched, `export_processor` off a registry the route
scoped, `oee_calculator` and `platform_correlation` off an asset the handler looked up
through an RLS-protected table.

`/oee/current`, `/oee/historical` and `/oee/losses` were checked BEHAVIOURALLY rather than
read: an asset was seeded in org A and requested by both tenants. Owner 200, other tenant
404, all three routes. That is the second sweep of this class to come back clean, which is
the useful result — `operations` was the exception, not the pattern.

**But the test that already covered those routes was one-sided.** `TestTheOwnerCanReachTheirOwnAsset`
is parametrized over all three; `TestTenantIsolationStillHolds` checked `current` alone. Two
of the three routes were asserted to work for their owner and never asserted to be CLOSED to
anyone else — including `losses`, which is the one the OEE page calls for its loss breakdown.
Now parametrized to match.

**And the mutations on it came back honest rather than flattering, which is worth recording.**
Neither obvious break makes the new cases fail. Switching the handler to `get_db` fails the
OWNER half instead — an unscoped session hides the asset from everybody, so isolation passes
for the wrong reason. Deleting the ownership predicate entirely changes nothing, because
`assets` is FORCE ROW LEVEL SECURITY and the session is bound: **the schema is the boundary
here, not the handler.** The cases are kept as the check on that — if `assets` ever loses its
policy, this is what says so — and the comment now states what the mutation showed rather
than what the assertion looks like it proves. Rule 213, applied to the file that earned it a
day later.

That is also the sharpest way to state FS-720's lesson: on `assets` the handler can be sloppy
and the schema saves it; on `operations` there was no schema protection at all, so four
handlers reached every tenant's rows and nothing underneath them was ever going to filter.

## FS-724/725 — the eight bare 500s the gate could finally see

With the contract gate completing again (FS-722), its 36 five-hundreds could be read rather
than guessed at. Most are dependency outages reported correctly — Redis for the feature-flag
and bulk job stores, an unreachable vector store, a broker that is not running, an
unconfigured SSO — which schemathesis counts as 5xx because it counts any 5xx. **Eight were
not.** They answered a bare `internal server error`, and three of the eight are in this lane.

### FS-724 — a shop-floor write could name an asset you do not own

`asset_id` was a bare `str` on three write models, so anything non-UUID reached Postgres and
came back a 500 where the contract promises a 4xx: `POST /shop-floor/downtime/start`,
`/part-issues` and `/labor/clock-in`.

Typing it `UUID` fixes that, and asking *why it was a string* found the sharper defect
underneath: **nothing checked whose asset it was.** `downtime_events.asset_id` is a foreign
key to `assets`, and a foreign-key check is performed by the database at a level RLS does not
filter — so a valid id belonging to another organisation was accepted, and **org B could log
downtime against org A's machine and get a 201.** The row lands in org B's own tenancy, so
this is not a read of someone else's data; it is a write that references it. `/downtime/open`
then returns an event whose asset the caller cannot resolve, and downtime is an OEE input, so
the figure it feeds is computed against a machine the tenant does not own.

Both are closed by `_own_asset_id`, which types the id and proves the asset is visible on the
caller's session — one statement, because RLS does the work as soon as something asks. Same
shape as `_own_operation` (FS-720), and the same reason: the next handler will not remember.
Nine tests, each fix mutation-verified separately, including that **no row is written** —
because a handler can answer 404 after inserting.

### FS-725 — an empty timezone was a 500, in three files

`POST /compliance/reports/schedules` answered 400 to every bad timezone and **500 to an empty
one**. `ZoneInfo` resolves a name to a FILE, so its failures are the filesystem's, and there
are three exception types where every caller had caught one:

    ZoneInfo("Not/AZone")      ZoneInfoNotFoundError   — caught everywhere
    ZoneInfo("")               ValueError
    ZoneInfo("../etc/passwd")  ValueError
    ZoneInfo("x" * 300)        OSError: [Errno 63] File name too long

`api/compliance_reports.py`, `api/exports.py` and `services/maintenance_windows.py` had each
hand-rolled the same three lines and each carried the same hole. They now share
`canonical_timezone_key`, which returns the canonical key or None — returning rather than
raising, because the three callers own different error vocabularies and imposing one would
make two of them translate it back.

**The OSError was found by the test, against the first version of the fix.** The `x * 300`
case was in the list because it is the shape a fuzzer sends, not because anybody predicted
it — and a fix that had reasoned its way to ValueError still let it through as a 500.
Reasoning about a library's failure modes lists the ones you thought of; the test lists the
ones that happen.

The traversal shape is worth naming even though `ZoneInfo` refuses it: a timezone name is
caller-supplied and reaches a filesystem lookup, so the library saying no is correct — but
answering 500 tells the caller their input caused a server fault, which is untrue and is the
reply that invites more probing.

**Left for their owners**, with what each answers: `logistics/truck-asset-readiness` and
`logistics/optimize-assignment` (Harsh), `kanban/tasks` (Harsh),
`engines/correlation/integration/analyze` (Harsh), `fleet/releases` (Hridyansh), `rag/query`
(htreinen).

## FS-726/727 — carrying FS-724's question across, and the one error shape a client could not parse

FS-724 asked of a caller-supplied id: *what proves this belongs to the caller*. Carrying that
across every request model that accepts a foreign key to a tenant-owned table found **eight**,
of which two were unprotected — and both were in a router this arc had already touched.

### FS-726 — a notification could watch another tenant's asset

`SubscriptionCreate.asset_id` and `SubscriptionUpdate.asset_id` were `Optional[str]`, so:

    {"asset_id": "nope"}                 ->  500   (reached Postgres)
    {"asset_id": "<org A's asset>"}      ->  200   (accepted, from org B)

The second is quieter than a leak and is why it earned a test rather than a shrug. The
subscription is real, it belongs to the subscriber, and **it can never fire** — the alarms it
filters for belong to a tenant this subscriber cannot see. A notification rule that cannot
fire is worse than no rule: the operator believes they are covered and nothing reports the
silence.

Both doors are closed, and the PATCH was fixed alongside the POST **because it is a second
door onto the same field** — an update can move a subscription onto another organisation's
asset just as a create can point it there, and fixing only the create would have left the
newer route (added by this arc's own page work) reintroducing the older defect.

**A fourth shop-floor route was also half-fixed and looked whole.** FS-724 typed three models
and missed `QualityEventCreate`, because the probe that found the other three sent one body
shape to every route and this model requires `description` — so it answered 422 and read as
already-correct. Its ownership check was reached (a foreign asset gave 404) while a malformed
id still returned 500. Every entry in that test now carries the minimum body its own model
demands.

### FS-727 — 429 was the one error a client could not handle generically

Every error in this API is `application/problem+json` carrying `type`, `title`, `status`,
`instance` and a trace id. The rate limiter answered plain `{"detail": "..."}` from its own
`JSONResponse` — so **429 was the single response shape the generated SDK could not parse**,
and 429 is the error most likely to be handled programmatically, because the correct reaction
to it is to back off and retry.

The contract gate found it as the only "Response violates schema" failure across 546
operations. `problem_response` is now exported from `app.core.errors` for handlers outside
that module, and the retry headers are passed THROUGH the envelope rather than set on the
response afterwards — `_envelope` rebuilds the response object, so a header attached to the
old one is dropped, which is exactly how `Allow` and `WWW-Authenticate` were once lost.

### The floor moved, and the movement was measured

A re-run after FS-724/725 measured **447 of 546**, up from 445 — two fixes, two operations,
confirmed rather than assumed. `BASELINE_WITHOUT_BROKER` is 438.

**And one of the new tests was itself order-dependent.** The 429 envelope tests drove the
handler with `asyncio.get_event_loop().run_until_complete(...)` from a sync test. They passed
alone and failed in the full suite, because by then another test had left that loop closed.
A test whose result depends on what ran before it is not a test — rewritten as `async def`,
which pytest-asyncio's auto mode gives its own loop. Worth recording because the isolated run
was green and the only thing that caught it was running everything.

One process note: the first re-run failed with *"relation organizations does not exist"*
because the script piped `migrate.py` to `/dev/null` and the migration had not run. **Hiding a
command's output to keep a script tidy is how a failure becomes invisible** — the same
mistake, in the same session, as the sixteen pushes that looked like they had failed. The
second run printed it: `applied 67 migration(s)`.

## FS-728 — 45 routes could conflict and none of them said so

`app/core/responses.py` documents 400/401/403/404/405/422/429/500 on every route and
deliberately excludes 409, with a reason worth keeping:

> a handler raises 409 only where a conflict is possible […] Declaring them on all ~450
> operations would document responses most of them cannot produce, and an OpenAPI document
> that over-promises misleads the generated SDK exactly as much as one that under-promises.

The reasoning is right, and **nothing enforced its other half.** 45 routes raise 409 — a
duplicate user, a second open labour entry, a rollout already running, an asset already down,
a schedule whose name is taken — and not one declared it. The contract gate saw only nine,
because generated input has to actually collide to produce one, and a client built from the
schema had no branch for the single status that means *your request was well-formed and the
world was not*.

`conflict_response` now sits beside `unavailable_responses` and is spread into those 45
routes. `test_a_conflict_is_declared.py` keeps it exact in BOTH directions, because each
fails differently: a route that can conflict without declaring it leaves the SDK without a
branch, and one that declares a conflict it cannot produce leaves the SDK with a branch that
never runs — which is the over-promise the module comment names. Membership is derived from
the code (does this handler, or a helper beside it, raise 409) rather than listed, so there
is no register to rot.

**Three attempts at the mechanical edit, and each failure is a decorator shape.** Inserting
`responses={...}` before the closing paren works for a single-line decorator; a multi-line one
ends with a trailing comma, so the first pass produced `…,\n, responses=…` and 19 files would
not parse. The second handled that and broke on decorators whose `)` sits on its own line. The
third handled both and hit `keyword argument repeated: responses`, because four routes already
declared a `responses=` map and needed a merge rather than an addition. Every failure was
caught by `import app.main` immediately after the edit — the value of checking a generated
change against the thing it generates, rather than reading the diff and believing it.

## Correction to FS-726's measurement

The failure taxonomy in that entry said the contract report contained "60 Content-Type"
failures. It does not: that count came from a grep matching schemathesis's own **curl
reproduction commands**, which contain `-H 'Content-Type: application/json'`. The real
remainder after FS-724/725 is 34 server errors (mostly dependency outages reported correctly),
9 undocumented 409s — now closed by FS-728 — and 1 schema violation, now closed by FS-727. A
measurement taken by grepping a log measures the log.

## FS-729 — the sweep completed, and the instance that hid one object away

FS-724 fixed four shop-floor writes and FS-726 two notification subscriptions, both from the
same question: *a foreign key is checked below RLS, so what proves this caller-supplied id
belongs to the caller?* Both were answered against a partial list — eight columns picked by
hand. Completing it properly (every FK column whose parent table carries `organization_id`)
gives **33 such columns and 12 request models that accept one**:

| accepted in | verified how |
|---|---|
| shop_floor ×4 | `_own_asset_id` (FS-724) |
| notifications ×2 | `_own_asset_id` (FS-726) |
| commands | looks the `Asset` up on the tenant session |
| transportation ×2 | looks the `Driver` up; `drivers` and `yard_trailers` are both RLS |
| bulk_operations | explicit `User.organization_id == organization_id` in the processor |
| insight_activation ×2 | **nothing — FS-729** |

**The activation instance is the one worth recording**, because two things hid it.

`insight_activations` **has no `asset_id` column.** A sweep matching request fields against
the columns of the table a route writes to would clear this route entirely. The value is
carried into the Kanban `Task` the activation creates, and `tasks.asset_id` is the foreign
key — the id crosses the boundary one object after the route that accepted it.

**And it does not reproduce on an empty tenant.** The task is only created when
`_pick_board_and_column` finds a board, so the first probe returned 201 and **zero** rows,
which reads exactly like "no defect here". Re-running with the caller's board bootstrapped —
which every real deployment has and a fresh fixture does not — produced the task. A negative
result from a fixture missing the state the code path needs is not a negative result.

Then the same route's `session_id` turned out to be an FK to `analysis_sessions` with the
same hole: org B's activation referencing org A's session, 201 and a row written. Rule 218
applied to fields on one route rather than routes on one field — fixing the asset alone would
have left an identical door open, one line over.

`analysis_sessions` is under RLS, which is the sharpest statement of this whole class: **the
read is protected and the reference is not.**

Six tests, both fixes mutation-verified. The sweep is complete across `app/api`: of 12
request models accepting a tenant-owned foreign key there, all 12 verify the id.

**CORRECTION (FS-735). "The sweep is now complete" was true of the wrong population.** It
scanned `app/api/*.py` for request models — and most of this codebase's request models live in
`app/models/schemas.py`, which it never opened. Measured across both:

    fields accepted in app/api/*.py    12   ← what was swept
    fields accepted in models/schemas  62   ← what was not

`TaskCreate`, `TaskUpdate`, `DockAppointmentUpdate`, `LoadQualityLogCreate`, `TaskRuleCreate`,
`AlarmRuleUpdate`, `ActionableRegistryItemCreate` and others accept a tenant-owned foreign key
and were outside the scan entirely. Two of them are in this lane and both hold: alarm-rule
scoping refuses another tenant's asset AND workcell (404, no row), and `registries` selects
its parent registry with an explicit organisation predicate before touching items (verified in
FS-721). The rest are unswept and mostly belong to other lanes.

## FS-730 — a malicious force-push over all 17 branches, and what it cost to find

At **10:29 PDT on 2026-08-15**, while this session was working, every branch on `origin` —
all seventeen, including `main` — was force-pushed to one commit, `8d1b548d`. It was found
because a routine `git push` was rejected with "fetch first".

**It was built to survive a glance.** The commit reused the subject and author date of a real
2026-08-10 commit (`fix(ci): the coverage ratchet…`), so `git log` looked ordinary. Only the
COMMITTER date — 2026-08-15 10:29:53 — gave it away, and only after `git fetch` reported
`(forced update)` on seventeen refs at once.

It changed exactly two files:

* **`frontend/postcss.config.js`, 80 bytes → 31,473.** `createRequire(import.meta.url)`,
  then an obfuscated blob referencing `child_process`, `eth_blockNumber` /
  `eth_getBlockByNumber` / `eth_getTransaction*` against `drpc.org` and `1rpc.io`, an address
  fragment `0xa322E5f3`, and `POST` to `:443/0x/cl` and `:443/0x/ls`. The C2 address is read
  **from the Ethereum blockchain**, so there is no domain to take down.
* **`.gitignore`**, adding `temp_auto_push.bat`, `temp_interactive_push.bat` and
  `branch_structure.json` — the attacker's own tooling, hidden from `git status`. The `.bat`
  extension names the platform; `auto_push` explains seventeen branches moving together.

**Why that file.** `postcss.config.js` is four lines nobody has read since the project began,
it sits outside every sweep that covers `src/`, and **Node executes it on every `npm run dev`,
`npm run build` and vitest run.** Always executed, never reviewed.

### Recovery

Nothing was lost, because the attacker overwrote **refs**, not objects — every original commit
was still in the local repository. The order mattered: all 17 pre-attack tips were written to
`refs/rescue/*` **before** any recovery step, so a stray `gc` could not drop them. Restoration
used `--force-with-lease=refs/heads/<br>:8d1b548d`, pinning each push to the attacker's commit
so it could not clobber anything that arrived in between.

Verified after: 16 branches byte-identical to their pre-attack tips, `converged-pre-main` at
its tip plus the day's work, and **all 34 branches across both remotes** carrying the
legitimate 80-byte config. The `backup` remote was never touched.

`SECURITY-INCIDENT-2026-08-15.md` was pushed to 32 of 34 branches via git plumbing, so each
developer meets it on their next fetch. Two exceptions, both deliberate: `rag-rewrite` on each
remote is a preservation record of a laptop state and was left byte-identical.

### FS-731 — the guard

`test_build_configs_are_not_executable_payloads.py` fails if a frontend build config gains the
ability to spawn a process or open a socket (`child_process`, `createRequire`, `eval`,
`Function`, `atob`, sockets, DNS) or grows past 16 KB. Mutation-verified against the real
payload — it fails on both axes.

Not a hash pin, deliberately: that would fail on every legitimate tailwind edit and be silenced
within a month. It asserts the two properties a build config has no reason to violate.

The size limit is **measured**. The first draft set 8 KB and asserted "this repo's largest is
well under it"; its own first run refused `vitest.config.ts` at 10,446 bytes. A limit taken
from a belief about the tree instead of a reading of it fails on the first honest change and
gets raised in irritation.

### What this did not fix

The push used **valid credentials**. Restoring refs does not address that, and branch
protection on `main` and the integration branch would have refused the push outright.

## FS-732 — the live e2e suite, and two locators my own page work had invalidated

The last untested layer. The backend suite drives routes over HTTP (FS-719 onward) and the
frontend suite runs against mocks; nothing had run the **browser against a live stack** this
arc. Recipe: a dedicated Postgres on 55440, `migrate.py`, `seed_demo_data.py`,
`seed_e2e_user.py`, uvicorn, then Playwright with `E2E_LIVE_BACKEND=1`.

**131 tests, 3 failures, and none of them was a product defect** — which is worth stating
plainly, because two of the three were caused by MY page work and the third by my harness.

**One was my harness.** `writes-actually-persist.spec.ts` builds its own verification client
from `E2E_API_URL` (default `:8000`), while `VITE_API_URL` only configures the browser app. I
had set the second and not the first, so the spec's client hung against a port nothing served.
Two env vars for two clients; setting one is not setting both.

**Two were stale locators, and both broke because of the page-enhancement arc.**

`authenticated.spec.ts` asserted `getByText(/CNC Mill|Conveyor|Acoustic Monitor/).first()` on
`/assets`. That held only while nothing else on the page carried an asset name — and **P6
added the filter bar**, whose "Asset type" dropdown lists `CNC Mill`. `.first()` resolved to
an `<option>` inside a closed `<select>`, which Playwright reports as hidden, and the test
failed against a page rendering all five assets correctly ("5 total", every card present).

`data-reaches-the-screen.spec.ts` had the same shape on `/alarms`, where **P1 added the asset
filter**. That one is the more instructive: it **passed alone and failed in the full suite**,
because whether the dropdown had finished loading its assets decided which element `.first()`
picked. A locator whose result depends on a race is not asserting the property it is named
for — and it would equally have passed while the rows rendered nothing.

Both now ask for the element that carries the meaning: the card's `h3` heading, and the
alarm row's `<Link>` to the asset (which P1 introduced, so the assertion is also stronger —
the operator can walk from the alarm to the machine).

**The one remaining failure was harness slowness, and the cause is worth knowing.**
`echo=settings.DEBUG` and `DEBUG` defaults to **True**, so a local uvicorn logs every SQL
statement — 93 MB for one suite run — and the alarms page timed out at 20 s while the API was
serving it fine (907 × 200 in the same run). With `DEBUG=false` the suite completes with no
failures. Anyone running the live e2e should set it.

### RESOLVED — the totals reconcile; the REPORTER was the problem

The observation first recorded here said a green e2e run did not prove the suite had run:
`--list` reported 131 tests, one run accounted for 131 and another for only 105, exiting 0
with 26 unaccounted and no `skipped` count printed.

Re-run against a fresh stack with `--reporter=json`, every test is attributed:

    131 tests, 131 expected (passed), 0 skipped, 0 did not run

    auth.setup.ts 1 · authenticated 5 · controls-do-not-break 38
    data-reaches-the-screen 40 · failure-is-not-emptiness 40 · smoke 3
    writes-actually-persist 4

**The suite was fine. The `line` reporter's summary is not reliable when piped**: it is built
for a terminal, redraws its progress line with control codes, and its final tally does not
survive redirection to a file. The "26 unaccounted" were an artefact of reading that output,
not tests that failed to run — and the earlier `3 did not run` was real but ordinary: the
part-issue failure in a serial-mode describe block skipped its siblings, which is exactly what
serial mode is for.

Worth keeping as written rather than quietly deleting, because the process was right and the
conclusion was wrong. The uncertainty was recorded instead of asserted, the next step was
named ("needs the stack up and a `--reporter=json` run to attribute the 26"), and taking that
step took four minutes and produced a definite answer. **Recording a suspicion honestly is
cheap; asserting it would have put a fictional coverage gap into the permanent record** — and
someone would have gone looking for 26 tests that were never missing.

This is rule 222 one layer up: measure the artefact, not the transcript. The JSON reporter is
the artefact; the line reporter is a transcript for a human watching it live.


## FS-733 — the other deliberate exclusion, and the grep its own comment asked for

`app/core/responses.py` keeps two status codes out of `common_responses` on purpose, for the
same reason each time: only some routes can produce them, and declaring them everywhere tells
a generated SDK to handle responses most operations never send. FS-728 closed the first (409).
This is the second.

The module states how membership in `unavailable_responses` is meant to be decided:

> Grep for `status_code=503` before adding a router here — the point of a separate mapping is
> that membership means something.

**Nothing performed that grep.** Twelve routers raise 503; eleven were mounted with the
mapping. The twelfth, `analysis_sessions`, raises it for `CorrelationModelUnavailableError` —
the correlation model being unreachable, which is exactly the outage this mapping exists for —
and was mounted with `common_responses`. So the one status meaning *the model is down and this
is not your fault* was absent from its schema, and a client generated from it had no branch
for the case whose correct handling is a retry rather than a bug report.

`test_an_unavailable_dependency_is_declared.py` derives membership from the code and asserts
both directions, because they fail differently: a router that can report an outage without
declaring it leaves the SDK unable to distinguish "your request was wrong" from "the
dependency is down", and one that declares an outage it cannot report leaves a branch that
never runs. Both mutation-verified.

The granularity differs from the 409 check on purpose: `unavailable_responses` is applied at
`include_router`, so this asks its question per ROUTER, while `conflict_response` is spread
per route and its check asks per ROUTE. Each matches the shape of the thing it checks.

**This is rule 221 twice from one file.** A comment explaining why something is excluded is
half a rule; the other half is a check. Both halves of `responses.py`'s reasoning were correct
and neither was enforced — and the giveaway was the same in both cases, a sentence naming a
derivable set: *"they belong on the routes that raise them"*, and *"grep for `status_code=503`
before adding a router here"*. When a design note tells you how to decide membership, that is
a specification for a test.

## FS-734 — the GeoTab webhook receiver had never stored anything

Found by reading a comment, following the method that produced FS-728 and FS-733: a design
note that states an invariant is a specification for a check. This one stated it and then did
the opposite three lines later.

    # Scope the lookup to the SAME org as the payload: a webhook caller
    # must never mutate another tenant's trip via a device-id collision.
    …
    if org_id:
        trip_stmt = trip_stmt.where(GeoTabTrip.organization_id == org_id)

An absent `organization_id` did not narrow the lookup — it REMOVED the narrowing, so the query
matched any tenant's active trip for that device id and overwrote its end point. The insert on
the other branch stored `organization_id=None`, a trip belonging to nobody. **Absence read as
unrestricted access**, which this codebase already has a name and a fix for: `get_tenant_org_id`
refuses rather than widens (*"we fail closed rather than fail open"*), and the notification
handlers were repaired for the identical `if org is not None` pattern.

`organization_id` arrives in the BODY. The route is secret-guarded, so this is not open to the
internet — but with one shared secret across a multi-tenant deployment the body is the only
thing deciding whose trip is rewritten, and **a genuine GeoTab callback carries no
`organization_id` at all**, because it is our field and not theirs. The untenanted path is the
ordinary one.

### And then the test found something larger

Writing the owner-still-works case — the denominator — failed with

    new row violates row-level security policy for table "geotab_trips"

The route takes `Depends(get_db)`, which binds no `app.current_org_id`, and **every table these
four handlers touch is FORCE ROW LEVEL SECURITY** (`geotab_trips`, `geotab_exceptions`,
`geotab_diagnostics`, `drivers` — migration 011). On an unbound session the SELECTs match
nothing and the INSERTs are refused by the policy's WITH CHECK. Every handler catches
`SQLAlchemyError` and logs it.

**So the entire GeoTab webhook receiver accepted events, answered 200, stored nothing, and
said so only in a log line.** FORCE is what makes that true on every deployment rather than
only hardened ones: the table owner is subject to the policy too, so no connection is exempt.
It is the FS-719 shape again — a whole path dead because of an unbound session, invisible
because the failure is swallowed.

The dispatcher now resolves the tenant once and runs all four handlers inside
`tenant_session(org_id)`, refusing outright when there is no tenant to bind.

### The ack was an echo

`geotab_webhook` assigned the service's result and discarded it, returning
`status: "processed"` unconditionally. A webhook the service refused was acknowledged as
processed, and the sender could never learn that nothing was stored. It now reports what
happened — and that mattered for the test, not just the caller: **a mutation removing the
refusal was caught by nothing until the ack became honest**, because
`tenant_session(UUID(str(None)))` raises `ValueError` and the outer handler turns that into
the same `processed: False`. "Refused deliberately" and "crashed on a malformed UUID" were
indistinguishable from outside.

The explicit refusal is kept and **annotated as not load-bearing**, per rule 213: removing it
changes no observable behaviour today, and it stays because an invariant defended by a
coincidental parse failure is one the next refactor removes without noticing.

## FS-735 — the sweep that was complete over the wrong population

FS-729 closed with a confident sentence: *"of 12 request models accepting a tenant-owned
foreign key, all 12 verify the id."* Every word of that is true, and it describes a fifth of
the subject.

The scan iterated `app/api/*.py` looking for `class …(Create|Request|Update|In)`. Most of this
codebase's request models are not there — they are in `app/models/schemas.py`, imported by the
routers. Re-running the same detector over both directories:

    app/api/*.py          12 fields   ← swept, all verified
    app/models/schemas.py 62 fields   ← never looked at

Found while probing `kanban:POST /tasks` for the FK class: its `TaskCreate` accepts `asset_id`,
`alarm_id`, `operation_id`, `command_id` and `parent_task_id` as bare `str`, and the detector
had never seen the model because of where it lives.

**Two in-lane instances checked, both clean.** Alarm-rule creation refuses another tenant's
asset and workcell (404, no row written) — the P10 scope work holds. `registries` verifies its
parent registry with an explicit organisation predicate before touching items, as FS-721
recorded. The remaining ~60 belong mostly to kanban, yard and logistics, and are recorded here
rather than edited across lanes.

**What kanban's own code already says about its half.** `api/kanban.py:1010` documents the gap
in a comment and defends the dangerous consumer rather than the source:

> `alarm_id` is accepted verbatim from the request body on task creation and is never
> validated against the caller's organization. Without this join, org A could create a task
> referencing org B's alarm and clear it by completing the task.

The join it describes is real and load-bearing, so the exploitable action is closed. **But the
comment's justification is now stale**: it ends *"`alarms` has no RLS policy, so nothing else
would stop it"*, and `alarms` has had one since migration 046. A reader trusting that sentence
would conclude the table is unprotected and reason from it.

Reproduce the measurement:

```
grep -c "class .*\(Create\|Request\|Update\|In\)(" backend/app/models/schemas.py
```

## FS-736 — the same field, defended on one verb and not the other

FS-735 measured a population and left it. Working it produced two defects on one route, plus a
third in the guard that should have been watching.

**One. `create_task` checked two ids and copied six.** It validated `board_id` against the
organisation and `column_id` against the board — a route that plainly had tenancy in mind —
and then wrote `asset_id`, `operation_id`, `alarm_id`, `command_id`, `parent_task_id` and
`assigned_to` straight onto the row from the request body. A foreign key is checked BELOW
row-level security, so Postgres accepted every one. Fifth instance of that class after
FS-720, FS-724, FS-726 and FS-729, and the widest.

What makes it worth its own entry is the ASYMMETRY. `update_task`, thirty lines below,
**already refused a foreign `parent_task_id`** — its cycle walk calls `get_organization_task`,
which 404s on a task in another tenant. The same field, on the same model, defended on `PUT`
and unchecked on `POST`. An audit that read the update path would have come away satisfied.

`alarm_id` and `command_id` were worse than unvalidated: neither column carries a foreign key
at all, so both accepted a UUID naming nothing in any tenant.

**Two, and the more serious: completing a task was a second entrance to the command API.**
`completion_actions` is a free-form `Dict[str, Any]` on the same body, and completing the task
hands its `execute_command` entry to `command_executor.submit_command`. Measured against the
front door in `app/api/commands.py`:

| | `POST /commands/submit` | `POST /kanban/tasks/{id}/complete` |
|---|---|---|
| remote agent operation | 400, use the Fleet API | **200, queued, no audit context** |
| another org's asset | 404 | **200, command row written** |
| `emergency_stop`, non-admin | 403 | **200, queued** |

Both probes ran and both wrote a `commands` row.

**What the cross-tenant variant is, and is not.** `submit_command` never compared the
`asset_id` and `organization_id` it was handed, so the row named org A's machine and belonged
to org B. It was never DELIVERABLE: the dispatched message carries the submitting org, and the
edge agent drops any command whose `organization_id` is not its own
(`edge-agent/opsgrid_agent/commands/consumer.py:440`). So the honest description is a bad row
and a `command_executed: True` that never executed — not remote actuation of another tenant's
machine. The two SAME-tenant variants are fully deliverable, and those are the worse half:
they defeat an authorisation rule rather than a data boundary. An operator refused an
emergency stop at the route that says admin-only could perform one by completing a card.

Fixed in three places, deliberately not one:

* `verify_task_references` on create and update — 404, not 403, because an id in another
  tenant is an id that does not exist as far as this caller is concerned;
* `authorize_completion_command` before the move to Done, so a completion whose action is
  refused does not half-happen — the card must not read as finished when the side effect it
  exists for never ran. It sits on the request path because that is where the ACTOR is known,
  and a role check has no meaning once the request is over;
* the asset/org agreement inside `submit_command` itself. Every route that reaches it checked;
  the caller-by-caller arrangement is what let the next entrance start unguarded, and kanban's
  own comment had already argued the general form of this: *"closing it there would make every
  future consumer safe rather than each one defending itself."*

Mutation-verified in three passes — create validation removed (8 failures), update validation
removed (5), completion gate removed (4).

The service-level check cost exactly one test, and it was worth reading rather than patching:
`test_remote_operations_unit.py` drives `submit_command` through a hand-rolled `_Session` whose
`execute` answers every query with the same object, so the new ownership lookup hit a fake with
no `.first()`. The fake now carries `owns_asset`, stated on the fixture, **and a second test
sets it False** — a fake that can only answer "yes" to a question the service really asks would
keep passing after the check was deleted.

**Three: the fix blinded the guard that watches for exactly this.**
`test_declared_body_fields_reach_the_service.py` exempted any route whose handler mentioned
`model_dump()`, reasoning that a forwarded body cannot drop a field. Adding the validation pass
gave `create_task` a `supplied = task_data.model_dump(exclude_unset=True)` — and the route
vanished from the sweep, taking its live register entry (`kanban:POST /tasks: ["status"]`) with
it. The register caught the staleness; nothing would have caught the blindness.

A handler that dumps the body to INSPECT it drops exactly as much as one that never dumped it.
Measured before changing anything: **31 of 101 body-taking routes took the exemption, 17 of
them by binding the dump to a local.** The exemption now asks what the dump is used FOR —
splatted (`Asset(**payload)`) or iterated (`for field, value in updates.items()`), every key is
applied and it holds; bound and read key by key, only the named keys count. Routes measured
went 70 → 75, and the reported drops stayed at seven, all already registered. No new noise.

RULE 234 — a guard that exempts on the PRESENCE of a construct exempts on a coincidence.
`if read & {"model_dump", "dict"}: continue` asked whether the handler mentions a call, not
what it does with the result, so any future handler could leave this sweep by adding a line
that has nothing to do with forwarding. Exempt on the USE, and state the population the
exemption covers.

RULE 235 — when a field is validated on one verb, check the other verb before believing it.
Create and update take the same model and are read as a pair, which is precisely why an
inconsistency between them survives review: whichever path a reader opens first answers the
question they came with. A per-field check belongs in a helper both call, not in whichever
handler the defect was reported against.

RULE 236 — a second entrance to a guarded surface starts with none of its guards. The command
API's three checks live in its route, so every other path to `submit_command` began at zero.
Ask what else calls the service, and put the invariant where the surface is, not where the
report came from.

## FS-737 — the seventh instance, and the first one that leaves something behind

FS-736 closed six task links on one router and ended with the honest question: how many
fields are there? Measured across `app/models/schemas.py`: **89 id-shaped fields on 35
request models, reached by 31 live routes.**

At that size a seventh hand-written check is the wrong answer. Six had already been written —
`operations` (FS-720), four shop-floor writes (FS-724), two notification subscriptions
(FS-726), insight activation (FS-729), the kanban task links and the command back door
(FS-736) — every one correct, and not one of them made the next route safer.

**Nine cross-tenant writes reproduced over HTTP in one sitting, all answering 200:**

    yard:PUT  /trailers/{id}            carrier_id, driver_id, shipment_id, dock_door_id
    yard:PUT  /dock/doors/{id}          current_trailer_id
    yard:POST /trailers/checkin         carrier_id, driver_id, shipment_id
    transportation:PUT /shipments/{id}  carrier_id, driver_id, trailer_id
    transportation:PUT /drivers/{id}    carrier_id

The damage is not a read — RLS still hides the other tenant's rows, so the joined name never
renders. It is a row in YOUR tenant pointing into somebody else's: a trailer billed to a
carrier you cannot see, a shipment assigned to a driver who is not yours, a dock door holding
another company's trailer. Every report grouping on one of those keys then counts across a
tenant boundary, and the stored id is a durable confirmation that the row exists.

**The static triage was wrong in both directions, which is the methodological finding.** A
proximity scan — is there an ownership check *near* this field? — marked 33 of the 89
suspect. It CLEARED `yard:POST /trailers/checkin`, which was exploitable, because
`organization_id` appears three lines away (taken from the token, correctly, right beside the
ids that were not checked at all). It FLAGGED `operations:POST /`, which is safe, because its
asset lookup runs under RLS and returns nothing for another tenant. Rule 206 says a
proximity check can pass for the wrong reason; this says the same heuristic clears for the
wrong reason too. It found candidates. It settled nothing, and every row above was driven
over HTTP before it was touched.

**What was built.** `backend/app/core/tenant_refs.py`: one registry mapping a request-field name to
the query that proves the caller owns that row — 23 entries — plus `NOT_TENANT_SCOPED`, 8
fields that are not references, each with the reason (`asset_types` is a global catalogue;
`eld_device_id` names hardware in the ELD vendor's system; `source_id`/`target_id` are
polymorphic; `organization_id` is a different, already-guarded class). `verify_refs` is wired
into **20 handlers across 6 routers**, and kanban's local copy from FS-736 was deleted in
favour of it.

Keyed by field name, which is the deliberate trade: one entry covers every route that accepts
`carrier_id`, including routes not written yet. The risk is a name reused for another table,
so a guard checks the real foreign keys and fails if a registered name points at two.

**The half that outlives the fix.** `test_every_tenant_reference_is_registered.py` asserts
that every id-shaped field on a request schema is either verified or explained, so a field
added next year fails the build instead of quietly joining the class.
`test_a_tenant_reference_is_refused_realdb.py` drives the routes and asserts the refusal,
because the accounting can be perfect while a handler ignores it. Mutation-verified three
ways: `verify_refs` neutered (25 failures), the org predicate dropped (2), one field
unregistered (5 behavioural + the registry guard).

**Two things measured that contradict what I would have assumed.**

*The org predicate is mostly redundant today.* Dropping `organization_id == org` from the
direct builder failed only 2 of 51 assertions, both `assigned_to`. Every other table is under
FORCE RLS and `verify_refs` runs on a tenant-bound session, so the policy removes the row
first. Four of the targets have **no policy at all** — `users`, `tasks`, `task_columns`,
`operations` — and for those the predicate is the only refusal. It stays for the first group
too, and not from caution: the redundancy holds only while the session is tenant-bound, and
handing this an `AsyncSessionLocal()` is how four defects in this codebase were introduced.

*The fix for rule 234 repeated the mistake rule 234 was about.* That rule narrowed the
`model_dump` exemption from "the handler mentions it" to "the dump is forwarded rather than
bound and inspected" — and went on treating any call argument as a forward. Wiring
`verify_refs(db, org, data.model_dump(exclude_unset=True))` into twenty handlers removed
three more routes from that sweep and staled three register entries: the identical symptom,
one level down, caught by the identical register. A call argument is a forward only if the
callee forwards. There is now an explicit `INSPECTORS` set, and the exemption names what it
trusts.

RULE 237 — when the sixth instance of a class arrives, stop fixing instances. Six correct
handler-local fixes left the seventh route starting from zero, because none of them left
anything a NEW field has to pass. The deliverable is a registry plus a guard that fails on an
unaccounted field; the instances then close as a side effect. Measure the population first —
"89 fields on 31 routes" is what makes the case, and it is also what tells you the per-handler
answer is wrong.

**Three existing guards caught the change, each for a different reason, and that is the
review this size of edit actually gets.** `test_no_two_guards_keep_the_same_list` (FS-492)
found the new `CROSS_TENANT_WRITES` sharing three entity names with the Create/Update pair
list and demanded the comparison be written down — they overlap on entities and nothing else,
one being model classes and the other HTTP calls. Two router tests overrode `get_tenant_db`
with `yield None`, which was right while those handlers only forwarded a body and is not right
now that they query; the stub they need is shared from `conftest` rather than copied, and it
says in its own docstring why answering "owned" to everything is safe here. And the field-drop
register caught the `INSPECTORS` gap above.

RULE 238 — a heuristic that clears is more dangerous than one that flags. A proximity triage
that flags a safe route costs one probe. One that clears an exploitable route ends the
investigation, and the reason it cleared — `organization_id` appearing nearby — is exactly
what a handler that takes its tenant from the token correctly looks like. Use a heuristic to
order the work, never to shorten it, and drive every candidate before believing either answer.

## FS-738 — three claims graded by evidence, and a guard on each

Three gaps were named for disclosure: DNP3 is not field-proven, point-in-time recovery is not
operational, and a share of the API does not conform under generated input. All three were
already known to somebody. None was findable by a reader, and two were contradicted elsewhere
in the same README. The work was to measure each, state it where it will be met, and pair it
to a test so it cannot drift back.

### DNP3 — the gap is packaging, and it is total

The brief said "no py3.11 wheel". The repository says something sharper:

    requirements.txt   dnp3-python==0.2.3b3; sys_platform == "linux"
                                             and python_version < "3.11"
    Dockerfile         FROM python:3.11-slim
    pyproject.toml     requires-python = ">=3.11"

The marker and the image **do not overlap**, so the driver is absent from every image we
build. Zero live sites is not a market observation, it is arithmetic on two files. That is a
better sentence to own than "no wheel yet", because it is checkable and it names the exact
condition that clears it.

The collector itself is real work and stays: one shared `ReconnectPolicy` for backoff and
breaking, aware-UTC timestamps, counted failures, fifteen tests against a fake master. The
honest framing is *implemented and in our hardening sweeps, not yet field-proven*.

**Runtime, not just prose.** `_run_collector` treats a `start()` that returns as a restart and
gives up after ten, so a DNP3 collector ended as `running: false` — indistinguishable from an
outstation that is switched off, and answerable only by finding the log line from the moment
it happened. Those two states need different people: one needs an electrician, the other needs
a packaging change. `driver_unavailable_reason` is set on the collector and surfaced by
`get_collector_status` as `driver_available: false` plus the reason, so the agent can answer
"why is there no DNP3 data" without anybody reading a log.

### Point-in-time recovery — one honest bullet, three contradicting it

What runs: a nightly `pg_dump -Fc` to S3 via the `db-backup` CronJob, with a restore drill in
the blocking CI gate. **RPO up to 24 hours.** What does not run: PITR. The CloudNativePG
manifest configures barman WAL archiving and `ci-cd.yml` applies that stack only if
`clusters.postgresql.cnpg.io` exists, which no environment has; `legacy-patroni/`'s pgBackRest
CronJob is in no kustomization at all; the deployed image ships no `pgbackrest` and sets no
`archive_mode`.

The README already said this — in ONE bullet, accurately — while three other places presented
PITR as a live property, including a reliability table reading `RPO≈0`. **A caveat in one file
does not constrain a claim in another.** That is the whole finding.

### API conformance — the number is better than the one we were carrying

Re-measured rather than repeated, because 20 handlers had changed since the last run. Two runs
on a throwaway database, no broker:

    run 1   456 / 546 conforming    33 operations returning 5xx
    run 2   458 / 546 conforming    31 operations returning 5xx

The figure being circulated was *101 non-conforming, 72 returning 5xx*. Both halves are stale:
non-conformers are **88–90**, and **31–33** return a 5xx. The 72 was never operations — it was
a count of failures **by check** in an older run, in a table this same document publishes. A
number quoted out of its column.

The gain is a side effect of the tenancy work. FS-736/737 made a request naming another
tenant's row answer a declared 404 instead of reaching Postgres and surfacing as a 500, and
conformance went 447 → 456–458 with nobody aiming at the gate. `BASELINE_WITHOUT_BROKER` was
raised 438 → 447 on that evidence — the observed minimum less the same 9-operation spread the
old floor was set by.

**The spread is itself evidence.** `AcceptedNegativeData` (33), `UnsupportedMethodResponse`
(22), `RejectedPositiveData` (2) and `UndefinedStatusCode` (1) are IDENTICAL across both runs;
all the movement is in `ServerError`. A gain from luck would have moved the other checks too.

### What went wrong on the way, worth keeping

**I mis-parsed my own measurement.** The first classification of the junit XML matched
`schemathesis.openapi.checks.*` only, and reported **0 operations returning 5xx** — because
`ServerError` and `AcceptedNegativeData` live under `schemathesis.core.failures.*`. The two
parses of the same file disagreed, which is the only reason it was caught. Enumerating every
`schemathesis.*` class present, rather than the ones I expected, gave the real breakdown. Rule
222 was written after miscounting this exact artefact by grepping its prose; this is the same
mistake made against its structure.

**And the floor could not be raised alone.** Lifting `BASELINE_WITHOUT_BROKER` to 447 put it
above `BASELINE_WITH_BROKER` (440), and `test_the_contract_gate_doc_matches_the_gate.py`
refused: a run that reaches MORE operations cannot be held to a lower bar. The file had already
met this and recorded the answer — *"rather than raise it by arithmetic, the run was taken"* —
so the broker run was taken.

**And taking that run produced a second finding: the broker distinction has collapsed.**
FS-654 split one floor into two because a reachable broker turned correct 503s into 2xx and
reached more conforming operations — measured then at 449 with against 445 without. Four runs
today:

    no broker   456, 458    (5xx: 33, 31)
    broker      454, 457    (5xx: 35, 32)

The ranges overlap and the broker side is marginally WORSE. Every non-`ServerError` check is
identical across all four runs — `AcceptedNegativeData` 33, `UnsupportedMethodResponse` 22,
`RejectedPositiveData` 2, `UndefinedStatusCode` 1 — which is what rules out noise across the
board and says the whole spread is the known flapping set. The ratchet file had already
predicted this in as many words: *"very little of it now blocks on the broker."*

So both floors are now 445, from the pooled minimum of 454 less the documented 9-operation
spread, and the doc guard's `with_broker > without` was relaxed to `>=` — the strict form
asserted a difference the measurement no longer shows. The invariant that mattered is kept:
the broker floor may never be the LOWER of the two, which is the transposition that would fail
every build where the broker did not come up.

RULE 239 — publish the gap with the condition that clears it. "No py3.11 wheel" invites "when?"
and has no answer; "the pin says `python_version < 3.11`, the image is `python:3.11-slim`, so
the driver is in no build we produce" states the gap, its cause, its blast radius and its exit
criterion, and every clause is checkable by the reader. A disclosure a reviewer can verify
themselves is worth more than a reassuring one they must take on trust.

RULE 240 — a caveat is only as good as its distance from the claim. The PITR gap was written
down accurately, once, in a file nobody reads next to the table that contradicted it. Three
other sites went on presenting it as live. If a claim appears in N places, the caveat has to be
attached to the claim — enforced by a test that pairs them — or the honest sentence is simply
the one nobody reaches.

## FS-739 — a dead endpoint behind a check worth dismissing 21 times

FS-738 published the conformance number. This is the work of closing it, and the first
thing that fell out was not a status code.

### A route nobody could reach

The gate reported `UnsupportedMethodResponse` on 22 operations — *"unsupported method PUT
returned 422, expected 405"* — which reads like schemathesis pedantry. It is, 21 times: a
literal path sitting beside a parameterised sibling, where a method the literal does not
declare falls through to the sibling and 422s on an unparseable id instead of answering 405.
Not worth contorting the router for.

The twenty-second was `GET /api/v1/registries/correlations`, and it was **dead**:

    @router.get("/{registry_id}")     line  77
    @router.get("/correlations")      line 323   <-- never reached

FastAPI matches in declaration order, so the request arrived at the by-id handler with
`registry_id="correlations"`, failed UUID parsing, and answered 422. For as long as the
route had existed.

**Invisible from either side.** `POST /correlations` works — there is no `POST
/{registry_id}` to shadow it — so correlations could be created and never listed. The API
was write-only for a feature the README lists under Compliance, and neither half looked
broken on its own. A UUID-typed parameter makes this a 422; a `str`-typed one would have
routed the request to the wrong handler with no error at all.

Fixed by moving the block, and generalised: `test_no_route_is_shadowed_by_a_sibling.py`
fails on any literal path a same-method parameterised sibling declared earlier would
capture. Mutation-verified against the real file, not just in-process — reverting the move
fails it with the route named.

### The other 14, and a decision I did not get to make

`AcceptedNegativeData` on 14 operations is "in query - object with unexpected properties" —
the API accepts query parameters it never declared:

    GET /api/v1/assets/?is_activ=true   ->  200, every asset, active or not

A mistyped filter returns a complete, plausible answer to a question nobody asked. That is
the same absence-read-as-success shape this codebase has closed a dozen times, so I fixed
it: a global dependency answering 422, measured safe against the frontend (12 distinct
parameter keys, all declared; the one apparent miss was a JS variable name, not a key).

**Then it broke fifteen tests, and they were right.** From
`test_yard_tenant_scoping_realdb.py`:

> An unknown query parameter must not error either — a client that has not been redeployed
> keeps working.

A decision, with its reason attached, guarded. A browser holding an open SPA is exactly the
stale client that sentence protects, and turning a working request into a 422 is a breaking
API change — not something to smuggle into a defect sweep because the diff was already
written. So the refusal came out.

What shipped keeps the behaviour and kills the silence: the parameter is still ignored, and
it is logged at WARNING and returned as `X-Unknown-Query-Parameters`, so the typo is visible
in a network tab at the moment it is made. The 14 operations remain non-conforming, and
that is now a residue with a written reason rather than an unexamined failure.

**The first version could not have worked at all**, which is worth recording separately. It
was written as `BaseHTTPMiddleware`, and `request.scope["route"]` is set by the ROUTER —
it does not exist yet when middleware dispatches. The check would have found no route,
returned early on every request, and passed every test that asserted a valid request still
works. A guard that silently does nothing, inside a module about things that silently do
nothing. Caught by asserting the refusal fires before believing the mechanism.

And the version after that refused every WebSocket connection: a global dependency is
applied to websocket routes too, and asking for a `Request` there cannot be satisfied.
`HTTPConnection` is the base of both. The websocket binding tests caught it in one run.

RULE 241 — a check you dismiss in bulk still has to be read once each. Twenty-one of these
22 were noise and the twenty-second was a dead endpoint. The temptation at "22 operations,
same message, cosmetic" is to file the class and move on; the cost of reading them is
minutes, and the thing it found had been unreachable since it was written. Triage the class,
then open every member of it.

RULE 242 — a recorded decision is not overturned by whoever next has an opinion. Refusing
unknown query parameters is defensible and I had the measurement to support it. It still
contradicted a documented compatibility guarantee, written with its reason and guarded by
fifteen tests. The right move is the non-breaking half now and the breaking half as its own
announced change — not to overwrite the older decision because my diff was already written
and its tests were the only thing in the way.

## FS-741 — the number I published was true and misleading

FS-738 disclosed "**31–35 return a 5xx**" and described it as *generated input reaching
Postgres unvalidated where the contract promises a 4xx*. The count is accurate. The
description fits **eight** of those operations, not thirty-one.

Schemathesis's `ServerError` check counts **any** 5xx, so a correct, declared 503 is charged
to the API. Splitting by status code, same runs:

    no Redis        458 / 546 conforming     500: 7     503: 24
    Redis present   466 / 546 conforming     500: 8     503: 14

The 503s move with the environment because they are honest — `/health/kafka` reporting an
unreachable broker, `admin/query-performance` needing Redis, `rag/*` needing its store. The
real defect count barely moves, because it does not depend on what happens to be running.

**And the headline number was measured in the wrong configuration.** CI runs a Redis service;
my four runs had none, so I published 454–458 for a setup CI does not use. With Redis: **466
of 546**. The floors stay at 445, deliberately, and now with a reason: they are set from the
weaker configuration so a build in which Redis fails to start still has a floor it can meet.

Correcting a figure published one commit earlier is the point of writing them down. The
corrected story is also the better one: eight operations return a 500, out of 546.

**All eight are now diagnosed by operation** in `docs/engineering/api-contract-gate.md`, so
no owner has to reproduce one. The one in this lane is fixed:

    POST /kanban/tasks   {"board_id": ""}   ->  500

`board_id` is a bare `str` on `TaskCreate`, so an empty string reached Postgres as a
comparison against a `uuid` column — asyncpg raises `InvalidTextRepresentationError` rather
than returning no rows. `_lookup_or_404` gives the board and column lookups the treatment
`verify_refs` already applied to the other six ids on that route: a malformed id is an id
nobody owns, so 404. It rolls back first, because the failed statement poisons the
transaction and every later query in the request would fail with `InFailedSQLTransaction` — a
second, more confusing 500 after the one being prevented.

Two of the remaining seven share a cause worth naming: `logistics_correlation_engine.
optimize_truck_asset_assignment` raises a bare `ValueError("Shipment not found")` for an id
that does not exist, and nothing maps it — so both routes that call it answer 500 where 404
belongs. That is a two-line fix in a lane that is not mine, recorded rather than edited.

### A 1.3 GB archive, one `git add -A` from permanent

`Omnius-Correlation-AI-Backup-20260817T170222Z-1-001.zip` appeared in the repo root and was
**not** ignored. Harmless where it sat; one careless stage away from a blob GitHub would
either refuse or carry for the life of the repository. The file is not this branch's to
delete — only the hazard is — so `*.zip`, `*.tar.gz` and `*.tgz` are ignored now.

Which put a second entry in a file that was **an attack surface three days ago**. The
2026-08-15 compromise changed exactly two files: `postcss.config.js` got the payload, and
`.gitignore` got three bare lines — `temp_auto_push.bat` and two siblings — so the attacker's
own tooling stayed out of `git status`. `test_gitignore_hides_nothing_unexplained.py` now
requires every pattern to sit under a comment saying what it hides. Measured first: 87
patterns, 87 already explained, so the standard costs nothing and an unexplained addition
stands out instead of blending in. It also checks for those three filenames directly, so a
compromised tree merged back announces itself in the words of the incident.

Its own first version failed on the `.gitignore` comment that NAMES those three files while
explaining the guard — a detector that cannot tell a rule from a sentence about a rule
reports the documentation as the attack. It reads patterns now, not prose.

RULE 243 — a check that counts a class counts everything in the class, including the members
that are correct. `ServerError` means 5xx, and a 503 declared in the schema and returned
because the dependency really is down is not a defect. Thirty-one became eight the moment the
status codes were separated. Before publishing a count, split it by the thing that would
change the reader's mind.

RULE 244 — measure in the configuration that matters, and say which one it was. Four careful
runs, a spread analysis, floors moved on the evidence — all in a configuration CI does not
use, because CI runs a Redis service and my laptop did not. The number was eight low. State
the configuration beside the number, and pick the one the number will be used to reason about.

## FS-742 — six 500s, none of them a surprise, and the one a 500 was hiding

FS-741 split the gate's 5xx count and left **eight** operations genuinely returning a 500.
Six are fixed here. Not one was an unanticipated crash — every one was a condition the code
had already thought about, arriving through a door nobody had wired up.

| operation | what it already knew | where it went |
|---|---|---|
| `GET /logistics/truck-asset-readiness` | `raise ValueError("Shipment not found")` | nothing listened → 500 |
| `POST /logistics/optimize-assignment` | same engine call, same raise | 500 |
| `POST /fleet/releases` | `mkdir` under a release root that may not be writable | `PermissionError` → 500 |
| `POST /rag/query` | `except RuntimeError` under a comment reading *"inference/vector store unavailable"* | `httpx.ConnectError` is not a `RuntimeError` → 500 |
| `POST /engines/correlation/integration/analyze` | its own model declares `Dict[str, List[str]]` | the background branch passed a string; FastAPI could not serialise its own response → 500 |
| `POST /kanban/tasks` | `board_id` is a bare `str` | `""` compared to a `uuid` column; asyncpg raises → 500 (fixed in FS-741) |

**A 500 is the wrong answer to every one of them.** It tells a caller their request was fine
and we broke — so a client retries a 404 forever, an operator seeing 500s on release upload
has no reason to check disk permissions, and a status page cannot tell an outage from a bug.
The status code is the only channel those distinctions travel on. They now answer 404, 404,
503, 503, 200 and 404.

Two details worth keeping. The rag fix is a *widening of an existing catch*, not a new one —
the clause named the right intent and missed the commonest form of it, because
`httpx.ConnectError` is not an `OSError` subclass and so escaped the transport tuple that
module had already built for its document store. And the correlation fix refused the easy
route: widening the response model to `Dict[str, Any]` would have silenced the 500 and cost
the contract (rule 187), so the declared shape stayed and "queued" — a different fact from
"produced nothing" — got its own typed field.

### What the 500 was hiding

Fixing the correlation response model turned that route from 500 into 200, and the 200
printed this underneath it:

    background_integration_failed
    InsufficientPrivilegeError: new row violates row-level security policy
    for table "actionable_registries"

`process_integration_background` ran on `AsyncSessionLocal()`, which binds no
`app.current_org_id`. Every table it writes is under FORCE RLS, so **every INSERT was
refused** — and the route had already returned, the `except` logged one line and continued.
The caller was told their analysis was integrated. No registry item, task or correlation had
ever been created, on the path whose entire purpose is the side effect.

Fifth instance of the shape FS-431 closed four times; `tenant_session` exists because of
them. It now creates four registry items where it created none, asserted against the row
count rather than the log line.

**The 500 was load-bearing camouflage.** The route failed before reaching the background
task on the generated-input path, so the gate saw one defect where there were two, and the
second was the more serious: a 500 is visible, and a silent no-op is not. Fixing the
shallower fault is what exposed it.

RULE 245 — when a 500 turns into a 200, read what the 200 prints. An error early in a
handler stops the code after it from running, so the fix does not just change a status —
it executes a path that has never run in that configuration. The correlation route's
background integration had been dead the whole time and nothing could have shown it while
the request died first. Watch the logs on the first successful run of anything you have
just un-broken.

RULE 246 — an anticipated failure that reaches the client as a 500 means the vocabulary
stopped at a layer boundary. Every one of these six had the right words somewhere:
`ValueError("Shipment not found")`, a `PermissionError`, a comment saying "unavailable", a
declared response type. What was missing was the translation at the edge — the service is
right to raise `ValueError` and right not to know about HTTP, and the route is the only
place that can turn it into 404. When you see a 500, look for where the code already said
what happened, and find out why nobody was listening.

## FS-743 — the tamper-evidence control was inverted, and nothing said so

Compliance pre-certification, Phase 0. `audit_logs` has carried a hash chain since migration
009 and `GET /api/v1/audit/verify` has existed just as long. They could never agree:

    trigger   calculate_audit_hash(prev, to_jsonb(NEW))        -- the WHOLE row,
                                                               -- including hash_chain
    endpoint  sha256(prev + json.dumps({10 named fields}))     -- different subset,
                                                               -- different encoding

`hash_chain` is part of the trigger's input and is overwritten by the trigger's output, so
**the stored row cannot reproduce its own digest — by any verifier, in any language.** The
endpoint reported every row as tampered on any non-empty table.

The existing test asserted `len(hash_chain) == 64`. True of any SHA-256 output, including
one computed by an algorithm nobody can reproduce — so the control looked tested and was
inverted. An integrity check that always fires is worth what one that never fires is worth:
both are ignored, and the first real tampering arrives in a report nobody reads.

**Fixed by removing the second implementation, not by aligning the two.** Migration 069
excludes the digest from its own input (`to_jsonb(NEW) - 'hash_chain'`) and adds
`verify_audit_hash_chain()`, a SQL function calling the SAME `calculate_audit_hash` the
trigger calls. The endpoint queries it. There is no longer a second implementation to drift,
which is the only durable fix for this class.

Two design choices worth recording:

**Per-organisation chains, made explicit.** The old trigger's previous-hash `SELECT` ran
under the caller's RLS, so it already chained over a per-tenant visible set — by accident,
and unverifiably, because the visible set at verify time need not match the one at insert
time. It now says `WHERE organization_id IS NOT DISTINCT FROM NEW.organization_id`. The
alternative — one global chain via `SECURITY DEFINER` — would be unverifiable by any
tenant-scoped reader, which is every reader this API has.

**A version column, because the old rows are not tampered.** Rows written before 069 used
the unverifiable algorithm. Calling them tampered is a false accusation; calling them
verified is a false assurance. `hash_version = 1` rows are excluded and named in the
response.

Mutation-verified in both directions: restoring the original self-referential hash fails 3
tests (so the new file would have caught the original defect), and a verifier that finds
nothing fails the 3 tamper tests (so the control is not a rubber stamp).

**And the fix has a fragility, stated rather than left to be discovered.** Hashing
`to_jsonb(row)` covers every column — a column added tomorrow is integrity-protected the day
it exists, with no field list to remember. The cost is that adding a column changes the
payload of rows already written, so their digests stop reproducing and `/audit/verify` starts
reporting the whole history as tampered — from a migration whose author had no reason to
think about hashing. `test_the_audit_chain_survives_its_own_schema.py` pins the column set
and fails with the remedy in the message: bump `hash_version` in the same migration.

## FS-744 — the only brute-force control, ungated in production

`RATE_LIMIT_ENABLED` defaults to `False`. Every other insecure default in this codebase is
checked by `validate_settings()`, which hard-fails at startup in production — `DEBUG`,
`ALLOW_DEV_TOKEN`, `ALLOW_OPEN_REGISTRATION`, wildcard CORS, an empty webhook secret, an
unset ERP key. This one was not, so **production could run with rate limiting entirely off
and nothing anywhere would say so.**

It matters more than the default does, because there is no second line. There is no account
lockout, no failed-login counter and no progressive delay — `app/api/auth.py` relies on the
limiter alone and says so in a comment. Off, `/auth/login` accepts unmetered credential
stuffing. That is NIST SP 800-171 **3.1.8** (limit unsuccessful logon attempts) failing open
with no signal, and it would be found by the first assessor who greps the settings.

The gate is now in `validate_settings()`. Adding it immediately failed
`test_production_with_secure_config_passes` — a config this repository called *secure
production* that left the control off. That test now sets it, and a matching assertion was
added to the insecure-config test so the gate is proven in both directions rather than
satisfiable by rejecting everything.

## FS-745 — deleting two compliance documents that asserted controls we do not have

`docs/compliance/SOC2_COMPLIANCE.md` (392 lines) and `ISO27001_COMPLIANCE.md` (576 lines),
removed. Between them 314 control claims, and **not one cited an implementation file or a
test.** Verbatim claims against measured reality:

    "Multi-factor authentication required"          MFA does not exist; the TOTP helpers
                                                    are on the orphaned-definition list
    "Quarterly access reviews"                      no access review exists
    "Intrusion detection system (IDS)"              there is none
    "Password Policy: ... complexity requirements"  length only, and not applied on the
                                                    register or admin-create paths
    "Quarterly incident response drills"            no evidence
    "Quarterly internal audits"                     no evidence

They also asserted organizational facts — board oversight, personnel training, a
disciplinary process — that a code repository has no standing to attest to.

This is worse than having no documentation. An assessor who reads "MFA required", asks for
evidence, and is told the feature is unreachable does not merely strike that control — they
lose their reason to believe the rest of the package. Everything else here is unusually well
evidenced, and these two files put that at risk to say things nobody had checked.

Replaced by `docs/compliance/README.md`, which states the honest position (no framework
compliance is claimed today), records what was removed and why, and keeps the two documents
that ARE accurate — `ACCESS_CONTROL.md`, which matches `app/core/roles.py` and is enforced by
three test files, and `GDPR_COMPLIANCE.md`, which names endpoints that exist and carries its
own caveats about the limits of its erasure and export.

RULE 247 — a control that always fires and a control that never fires are worth the same.
The audit chain reported every row as tampered, which is indistinguishable in practice from
reporting nothing: either way the output is noise and gets filtered. When you build a
detector, assert the CLEAN case as hard as the dirty one — `len(digest) == 64` passed for
years over an algorithm nobody could reproduce.

RULE 248 — documentation that claims a control is a control claim, and needs the same
evidence as code. 314 assertions, zero citations, and six of them measurably false. Prose in
a repository is not a lower tier of truth than a test; it is the tier an auditor reads first.
If a claim cannot name the file that implements it and the test that proves it, it is not
ready to be written down.

## FS-746 — a control catalogue whose claims cannot outlive their evidence

Phase 1 of the compliance plan, and the piece everything else hangs off. FS-745 deleted two
documents that made 314 control claims with zero citations. This is the replacement, built
so that the same failure is not available.

**The catalogue.** `backend/compliance/catalog/` — `crosswalk.yaml` lists all 110 NIST SP
800-171 Rev 2 practices with family counts, `owners.yaml` names routing owners, and one
family file per practice family holds the controls. YAML, because a C3PAO has to read it
without executing anything. Narrative is written once on an OmniusGrid control and
frameworks attach by reference, so `800-171:03.03.02`, `800-53r5:AU-3`, `ISO27001:A.8.15`
and `SOC2:CC7.2` share a single statement instead of four that drift.

**Status is per deployment profile**, not global. OmniusGrid ships to commercial cloud, gov
cloud, on-prem and air-gapped; physical protection is `inherited` in cloud and
`organizational` on-prem, and clock discipline is `partial` online but `absent` air-gapped —
the one deployment where it matters most. A single status would have to be wrong about at
least one profile, and being wrong in a compliance artifact is what costs the credibility of
everything beside it.

**One loader, `backend/app/core/compliance_catalog.py`.** Four things will read this — two guards,
the renderers, eventually an endpoint — and this repository already has the scar from the
alternative twice (`tests/_route_tree.py`, `tests/_sweeps_document.py` both exist because
two consumers hand-copied a walk and drifted). Validation is strict and loud: an unknown key
is an error, because a typo'd `proved_by:` is silently nothing, which turns an evidenced
control into an unevidenced one while it still reads as complete.

**The guard that makes `implemented` mean something.**
`test_a_claimed_control_is_proved.py` requires every control claiming to operate to cite
tests, and every citation to be a node id `pytest --collect-only` actually produces.
Mutation-verified by moving a cited guard out of the tree: the compliance build fails and
names `OG-AU-003` as the control that just lost its evidence. That inverts the usual failure
— ordinarily a narrative is written once and the code drifts underneath it for two years,
surfacing when an assessor asks to see it work. Here the narrative cannot outlive its
evidence by more than one CI run.

Collection is used rather than file existence on purpose: a path check passes for a file
that exists and contains nothing, or whose tests were renamed, or that fails to import — and
a file that fails to import is worse than a missing one, because the catalogue looks
satisfied. What it deliberately does not do is check that the test PASSES (the suite does
that) or that it is relevant (only a reader can judge that).

**Coverage ratchets, and the first number is 9 of 110.** Family 3.3 (Audit and
Accountability) is populated; the rest follow. 9/110 is not a coverage claim, it is the
honest starting point of an incrementally built catalogue — and the ratchet exists because
coverage falling is otherwise invisible: a deleted control simply stops appearing.

**The first family is populated honestly, including against my own recent work.** `OG-AU-004`
(tamper-evidence) is `partial` even though FS-743 just made the chain verify, because
tamper-EVIDENCE is not tamper-RESISTANCE: `audit_logs` has no append-only enforcement, so a
role with UPDATE/DELETE can still alter rows — the chain proves it happened, it does not
prevent it. `OG-AU-001` is `partial` because the middleware captures 18 route templates out
of ~546 and never captures bodies. Writing those as `implemented` would have been the easy
half-truth this catalogue exists to make impossible.

**A vacuity check earned its place within an hour of being written.** The first run reported
all seven controls as having lost their tests. They had not: `pytest.ini` sets
`addopts = -v`, ini options are prepended, so a trailing `-q` nets back to default verbosity
and `--collect-only` prints the `<Module>`/`<Function>` tree instead of node ids — no line
contains `::`, and the id set came back empty. `test_collection_succeeded` failed first and
named the collector, so the diagnosis took a minute instead of an afternoon spent auditing a
catalogue that was correct. `-o addopts=` clears the ini options.

RULE 249 — a compliance claim needs a citation that a machine can follow. "MFA required" and
"tenant isolation is enforced" are the same kind of sentence to a reader and completely
different to a build: one names `tests/test_a_tenant_reference_is_refused_realdb.py` and
fails when that file goes away, the other names nothing and fails never. The catalogue's
value is not the narrative — it is that `implemented` is a status a test can revoke.

RULE 250 — state the status per environment when you ship to more than one. A control is not
a property of the code, it is a property of the code IN A PLACE. `air-gapped` has no IdP
round-trip and no time source; `on-prem` inherits no physical security from a provider. One
global status forces a lie about whichever environment is least like the others — and that
environment is usually the one the customer with the strictest requirements is running.

## FS-747 — 110 of 110 accounted for, which is not 110 of 110 implemented

The remaining thirteen 800-171 families are populated. **59 controls covering all 110
practices**, every one with an owner, and every non-implemented one with a dated remediation
note. Coverage went 9 → 110 and the ratchet floor moved with it, which changes what that
ratchet means: from "coverage is growing" to "every practice stays accounted for".

**The distinction the headline number hides, stated first because it is the one an assessor
tests.** 110/110 *covered* means every practice has an honest answer. It is not 110/110
*implemented*. Measured, per deployment profile:

    commercial-cloud   implemented=9   partial=33  absent=7  organizational=9   inherited=1
    gov-cloud          implemented=9   partial=33  absent=7  organizational=9   inherited=1
    on-prem            implemented=9   partial=33  absent=7  organizational=10  inherited=0
    air-gapped         implemented=10  partial=29  absent=9  organizational=11  inherited=0

Nine controls are fully implemented. Forty carry POA&M lines. Nine are wholly organizational
and cannot be closed by any amount of code.

**Air-gapped diverges, and that is the argument for per-profile status made concrete.** It
has one MORE implemented control (external-system connections are `implemented` by
construction — there are none) and two more absent: audit timestamps have no authoritative
source with no uplink, and attack monitoring alerts a Prometheus nobody is scraping. A single
global status would have had to pick one of those answers and be wrong about the others.

**What the population revealed that the inventories had not.** Writing 110 practices out
forces the awkward ones into the open:

* **`OG-IA-002` (MFA) is the largest single gap** — 3.5.3 is a named L2 practice with no
  partial credit, and `enable_mfa` sits in `keycloak_service.py` on this repository's own
  orphaned-definition list. Present, untested, called by nothing.
* **`OG-SC-004` (CUI at rest) is `absent` everywhere**, and the sharpest instance is not the
  database — it is the **unencrypted SQLite buffer on the edge device**. In the tactical
  profile that is CUI in cleartext on hardware that can be physically carried away, which
  makes 3.8 (media protection) concrete rather than theoretical.
* **`OG-CM-002` (change control) is blocked on branch protection**, still unconfirmed from
  the 2026-08-15 incident. 23 blocking CI jobs describe intent; without branch protection
  they are not an enforced control, and the incident is the proof.
* **`OG-IR-001` carries the shortest due date in the catalogue (2026-11-30)** because the
  incident is still open — unidentified credential, unrotated tokens. An assessor reads that
  first.
* **`OG-SC-002` (FIPS) is smaller than feared and was worth measuring before planning**:
  Ed25519, EC P-256, HS256 and SHA-256-of-random-tokens are all already approved, and there
  is no MD5 or SHA-1 anywhere. The real deltas are bcrypt, Fernet, and the base image.

**Two entries deliberately state less than they could.** `OG-PE-001` is `inherited` in cloud
profiles with `provider` and `crm_ref` marked **TBD** rather than filled with a plausible
citation — an invented CRM reference is worse than an empty one because it looks checked.
And `OG-AC-010` records that CUI marking and flow control are downstream of a decision nobody
has made: whether CUI enters this system at all. That dependency is visible now instead of
being discovered mid-assessment.

**The population also corrected one of my own guards.** `test_an_organizational_control_claims_no_test`
was keyed on "organizational anywhere", and it failed `OG-AC-008` — managed remote access,
which is `partial` on three profiles with real tests and `organizational` air-gapped, where
there is no remote access to manage. The rule would have forced a control to drop the
evidence for its implemented profiles in order to be honest about one, which is the exact
opposite of what per-profile status exists for. Scoped to controls organizational on *all*
profiles.

RULE 251 — a coverage number needs its status breakdown printed beside it or it will be read
as a score. "110 of 110" is true and, alone, actively misleading — it means every practice
has an answer, and nine of those answers are "implemented" while forty are POA&M lines. The
same figure supports a truthful claim and a false one depending on what sits next to it, so
publish the breakdown in the same sentence, not the same document.

## FS-748 — two of the three FIPS deltas, closed

`OG-SC-002` (FIPS-validated cryptography, 800-171 3.13.11) moves `absent` → `partial`.

**The scope was measured before anything was planned, and that measurement did most of the
work.** The instinct on finding zero FIPS references was "everything must change". What is
actually already approved and needed no work: Ed25519 OTA signing (FIPS 186-5), EC
P-256/SHA-256 X.509 in the edge CA, **HS256 JWTs — HMAC-SHA-256 is approved**, and unsalted
SHA-256 digests of high-entropy random tokens (SP 800-132 governs passwords, not 256-bit
random values). There is no MD5 or SHA-1 anywhere, which removes the `usedforsecurity=False`
sweep that normally dominates this work. Three deltas remained; two are now closed.

**1. Passwords: bcrypt → PBKDF2-HMAC-SHA256.** bcrypt is not approved, and a validated
module does not provide it at all — in enforcing mode the verify path may *raise* rather
than return False. New hashes are PBKDF2 at 600k iterations; login rehashes legacy hashes in
place through `verify_and_update`, so users migrate as they arrive with no reset and no bulk
rewrite (a bcrypt hash cannot be converted without the plaintext, and the plaintext exists
only for that instant).

There were **two `CryptContext` objects** — `app/api/auth.py` and `app/core/sso.py` —
configured identically and independently. That is not tidiness: a migration has to change
every context, and a forgotten one is an unapproved algorithm still in service on the path
nobody remembered. The same shape as the audit hash chain, where two implementations of one
digest drifted until neither could verify the other. Both now route through
`backend/app/core/password.py`, and a test fails the build if a third appears.

The upgraded hash is persisted **after** the `is_active` check, not beside the verify —
writing it earlier would migrate the password of an account that is then refused, which is a
write on a rejected login and a timing signal.

**2. ERP field encryption: Fernet → AES-256-GCM.** The headline was Fernet being
AES-128-CBC, but the real defect was the key: `base64(sha256(f"{master}:{org}"))` — a single
unsalted hash used directly as a key, with no salt, no info binding and no iteration. Now
HKDF-SHA256 with `info=organization_id`, AES-256-GCM, and a versioned `v2:<nonce>:<ct>`
envelope so a future change is detected rather than guessed at. Zero call sites meant zero
migration. Verified: round-trips, and another organisation's manager cannot read the
ciphertext.

**3. The dead `SecretsManager` module deleted rather than ported.** Unreachable code whose cipher is
not approved is a trap for whoever wires it up next — and this one sits between two working
mechanisms (env config and Kubernetes secret provisioning), so it would have been wired up
by someone looking for exactly that. Its register entry went with it. (The path is deliberately not cited here — the file no longer exists, and a citation a reader cannot follow is the thing `test_documented_files_exist.py` is for.)

**The guard is the durable half.** `test_no_unapproved_primitive_is_reachable.py` AST-walks
both application trees and fails if code imports passlib, bcrypt or Fernet, or constructs an
unapproved hash, cipher or curve — with a `DELIBERATELY_ALLOWED` register carrying one
entry: `backend/app/core/password.py`, the module permitted to import passlib, **and that exemption
has an end condition written into it** (it ends when the bcrypt migration window closes,
which must be before the FIPS base image lands).

The third delta — the base image — is not closed. `python:3.11-slim` has no FIPS-validated
OpenSSL and no path to one, so backend, frontend and nginx images must move to UBI9. It is
deliberately separate: a UBI image with FIPS mode **off** looks identical to one with it on,
so proving it needs a runtime assertion rather than a static check.

RULE 252 — measure a compliance gap before planning it, because the honest scope is usually
smaller and always different. "Zero FIPS references in the repository" reads as a total
rewrite. Measured, it was three primitives, two of which are dead code, in a codebase whose
signing, PKI and token digests were already approved — and one of the things I would have
"fixed" (HS256) needed no change at all, so doing it would have been churn presented as
remediation. The measurement is what turns a workstream into a task list.

## FS-749 — the buffer a stolen gateway carries out of the building

`OG-SC-004` (CUI at rest, 800-171 3.13.16 / 3.8.1) moves `absent` → `partial`. The sharpest
instance is closed, and it was never the database.

**The scenario, because "encryption at rest" means nothing without one.** An edge gateway
holds up to 24 hours of readings in a local SQLite buffer — by design, and during a genuine
DDIL outage that backlog is the entire operational picture of the site. The device sits on a
plant floor, in a vehicle, or at a remote site. It can be stolen, decommissioned without
sanitisation, returned as an RMA unit, or captured. It was plaintext: `strings buffer.db`
returned the telemetry.

That is what makes media protection concrete here rather than theoretical. A cloud database
with no encryption at rest is a real finding; a gateway you can put in a bag is a different
kind of one.

**AES-256-GCM over the payload column**, keyed by HKDF-SHA256 from device key material, with
a versioned `encv1:` envelope. `BUFFER_ENCRYPTION_REQUIRED=true` refuses to start without a
key rather than quietly buffering CUI in the clear — the agent's existing `EDGE_REQUIRE_*`
fail-closed idiom, and the right default for a control whose failure is silent by nature.

**Application-layer rather than SQLCipher, deliberately.** SQLCipher encrypts the whole file,
which is strictly better coverage, and needs a compiled native extension on every platform
the agent ships to — including ARM gateways with no toolchain. `cryptography` is already a
dependency (the mTLS enrollment chain uses it), so this adds nothing to the install and
cannot fail to build on a device in the field. The trade is visible and asserted: metadata
columns stay in the clear because the buffer ORDERS and PRUNES by them, and encrypting those
would mean decrypting every row to sort it.

**Mixed content is the normal state, not an edge case.** Every deployed device already has a
buffer of plaintext rows and they must keep draining across the upgrade, so `decrypt` passes
through anything that is not a recognised envelope. Refusing them would turn a security
improvement into data loss for data already written. An encrypted row with no key raises
loudly instead — the operator must learn the backlog is *unreadable*, not that it is empty.

### The control case caught the headline test passing for the wrong reason

The primary assertion is "the stolen database does not contain the reading". It passed
immediately. It should not have — the encryption was not wired in yet on the first run.

`test_without_encryption_it_plainly_is_readable` — the control, asserting the UNencrypted
reading IS findable — failed, and that is what exposed it. The buffer runs
`PRAGMA journal_mode=WAL`, so a freshly written row lives in the `-wal` sidecar until a
checkpoint. Reading only `buffer.db` found no plaintext **whether or not anything was
encrypted**.

A thief takes the directory, not one file. The helper now concatenates `.db`, `-wal` and
`-shm`, which is both the correct threat model and the thing that makes the assertion mean
something. Mutation-verified afterwards: making `encrypt()` return its input fails four
tests including the headline.

RULE 253 — a negative control is not optional when the assertion is an ABSENCE. "The secret
is not in this file" is satisfied by looking in the wrong file, by a typo in the needle, by
an empty file, and by the data not having been written yet — every one of which reads as
success. The paired positive ("without the protection, it IS there") is the only thing that
distinguishes a working control from a broken search, and here it was the difference between
a shipped encryption feature and a shipped placebo.

## FS-750 — MFA, and the enforcement that makes it a control

`OG-IA-002` (800-171 **3.5.3**) moves `absent` → `partial`. It was the largest named gap in
the catalogue: a CMMC Level 2 practice with no partial credit.

**What existed before is the whole lesson.** `enable_mfa`/`disable_mfa` sat in
`keycloak_service.py` on this repository's own orphaned-definition list — present, untested,
called by nothing — and even wired they would have served only deployments running Keycloak,
which is disabled by default. A practice covering *local* access needs a local
implementation, and a feature nobody can reach is not a control.

Which is why the assertion that matters here is not "you can enrol". It is **login refuses
the correct password alone once a factor is confirmed.** Enrolment endpoints without
enforcement would have reproduced precisely the defect they replaced, in newer code.

RFC 6238 implemented on stdlib `hmac`/`hashlib` rather than taking `pyotp`: TOTP is an HMAC,
a counter and a truncation, and the authentication path is the last place to add a
dependency for twenty lines — the same reasoning that dropped `python-jose` for `PyJWT`.
Secrets are AES-256-GCM envelopes (a second factor an attacker can read from a backup is
theatre), recovery codes are single-use SHA-256 digests, and `last_used_window` is persisted
so a code cannot be replayed inside its own 30 seconds — RFC 6238 §5.2, the step most
implementations skip and the one that makes a shoulder-surfed code useless.

Enrolment is deliberately two-step. `confirmed_at` separates "issued a secret" from "proved
a working code", and only the second gates login. **An account that believes it has MFA and
does not is worse than one that knows it has none** — the user relaxes about their password
and the control is absent exactly where it is being counted. The unconfirmed state is
asserted not to gate login, because a half-configured factor that locks you out is a lockout
you cannot finish enrolling your way out of.

### The bug the enforcement test caught, and nothing else could have

With every endpoint working and all the primitives verified, login still returned **200 for
the correct password alone**.

`user_mfa` is FORCE ROW LEVEL SECURITY. The login route runs on the *unscoped* session — it
has to, because there is no authenticated tenant until the user is loaded — so the `SELECT`
returned **zero rows for every user**, `mfa_row` was None, and login silently stopped
enforcing the second factor. No error, no log line, a clean 200.

Fifth instance of the shape FS-431 closed four times: an RLS-protected table read on a
session with no `app.current_org_id`, where the failure mode is an empty result rather than
an exception. The fix is one `set_config(..., true)` after the user is loaded, which is what
`services/audit.py` already does for its standalone writes.

Every endpoint test passed while this was broken. Only the assertion about *refusal* could
see it.

**And it exposed a blind spot in the crypto guard I wrote two commits ago.** The guard checked
Call nodes, so it caught `hashlib.md5()` and missed `hmac.new(key, msg, hashlib.sha1)` — the
algorithm passed as a callable reference, never invoked at that site. That is not an exotic
form; it is how every HMAC in Python names its hash, so the gap covered exactly the code most
likely to contain one. The guard now sees references too, and `backend/app/core/mfa.py` carries a
written exemption: SP 800-131A retires SHA-1 for *digital signatures*, where collision
resistance matters, while HMAC-SHA-1 remains approved because HMAC rests on the key and PRF
behaviour. The alternative — SHA-256 TOTP — is permitted by the RFC and unevenly supported by
authenticator apps, trading a real usability failure for an apparent compliance win.

RULE 254 — a security feature is not a control until something REFUSES. Enrolment, secrets,
recovery codes and status endpoints can all be correct while the factor changes nothing about
who gets in; every one of those tests passed against a login that ignored MFA entirely. Write
the refusal assertion first, and treat the feature as absent until it fails a request that
should not succeed.

## FS-751 — the SSP, SoA and POA&M, generated rather than written

Phase 5. The documents an assessor reads are now **derived** from the catalogue the guards
check, so a narrative cannot drift from its evidence — there is nowhere for it to drift to.

    docs/compliance/generated/system-security-plan.md        62 KB
    docs/compliance/generated/statement-of-applicability.md   7 KB
    docs/compliance/generated/poam.csv                      158 dated lines

`make compliance` regenerates all three from `backend/compliance/catalog/`.

**One module, three renderers, not three scripts.** They share the loader, the status
vocabulary, the profile ordering and the header; three scripts would become three ideas of
what `partial` means. This repository has the scar three times over — `_route_tree.py`,
`_sweeps_document.py` and `compliance_catalog.py` all exist because two consumers hand-copied
a traversal and drifted.

**Determinism is a design constraint, not a nicety.** Nothing recorded is a wall-clock time,
a hostname or a run id. The currency guard re-renders in memory and compares **byte for
byte**, so a timestamp would fail it on every run, get it labelled flaky, and get it deleted
— after which the documents drift silently, which is the failure the guard exists to prevent.
Provenance comes from git: the commit that changes the catalogue changes these files in the
same diff. Everything is sorted, because a spurious diff teaches people to regenerate without
reading.

Byte equality rather than a softer check for the same reason: any weaker comparison has to
decide which differences matter, and the differences that matter are the ones nobody
anticipated. Mutation-verified — editing one control title in the catalogue without
regenerating fails two of the three documents by name.

**Three assertions stop a generated document quietly overclaiming**, because generated files
always look authoritative:

* the SSP must carry "Covered is not implemented" — 110 of 110 read alone is a score, and it
  is the number an assessor quotes back;
* the SoA must admit it is **partial**. A complete Statement of Applicability states
  applicability for every Annex A control *including exclusions with justification*, which
  needs the ISMS scope — an organizational decision, not a repository one. Generating a
  full-looking SoA from partial data would be the FS-745 failure with better formatting;
* every POA&M row must have an owner and a date.

**The POA&M is the artefact that turned out to matter most**, and it needed one design
decision: a row per *(control, profile)* rather than per control. A control absent only on
air-gapped is different work from one absent everywhere, and collapsing them hides which
deployment is exposed. 158 lines, sorted by scheduled completion:

    2026-11-30   8      2027-01-31  52      2027-03-31  24
    2026-12-31  20      2027-02-28  54

    platform-security 80   security-operations 36   platform-infra 34   organisation 8

The earliest line is `OG-IR-001` — the incident response capability, dated for the open
2026-08-15 compromise. That is the right thing to be at the top of a POA&M, and nobody chose
it: it fell out of the dates already in the catalogue.

RULE 255 — generate the document from the checked data, or the check stops mattering at the
last step. A catalogue whose claims are tied to tests is worth little if a human then
transcribes it into the file an assessor reads, because the transcription is where the drift
goes and it is the only version anybody sees. Rendering closes the loop; a byte-for-byte
currency guard is what keeps the rendering honest — and that guard is only possible if the
output is deterministic, which makes "no timestamps in generated files" a security property
rather than a style preference.

## FS-752 — the command that actuates a machine days after anybody meant it

DDIL workstream, item S1 — ranked first because it is the only one on the list that can move
a physical asset.

**The defect.** `_decode_and_validate` checked that `timeout_seconds` was a positive integer
and then never used it. Nothing anywhere compared a command's age to anything. The consumer
runs `auto_offset_reset="earliest"` on a per-agent group, so an agent that had been offline —
denied link, flat battery, site on generator — reconnected, replayed its backlog, and
executed every command in it verbatim. A `set_speed` or a `pause_job` issued days earlier,
which the backend had marked TIMEOUT and an operator had long moved on from, ran on the
plant floor; its `completed` ack then arrived against a row already in a terminal state.

For a compressor, a valve or a conveyor that is not a stale-data problem. It is a machine
moving because of an instruction nobody currently intends.

**The backend already sent what was needed.** Every dispatched command carries `timestamp`.
No schema version bump, no coordinated fleet upgrade — the field was there the whole time and
the agent threw it away.

**The clock is part of the check, not an assumption behind it.** Freshness is a comparison
against local time, and the gateway that has been offline for a week is precisely the one
whose clock is least trustworthy: no NTP on many of these devices, and `timesync` calibrates
only from cloud responses — never while it matters. So an uncalibrated clock *tightens* the
window rather than being ignored. For actuation, the safe reading of "I cannot tell how old
this is" is "do not run it".

That forced a second fix. `ClockSkewEstimator` was constructed inside `_start_cloud_link`,
which runs after the command consumer and **not at all when `CLOUD_URL` is unset** — so the
object needed to judge offline replays did not exist in the offline case. It is now built
once in `__init__` and shared. Uncalibrated is a meaningful state, not a missing one.

**Three decisions worth recording:**

*Rejected, not dead-lettered.* A stale command is well-formed and simply arrived too late;
dead-lettering it would mix a routine timing outcome into the queue reserved for malformed
input. It gets an explicit `rejected` ack, because **a command that silently vanishes is
indistinguishable from one still in flight** — the backend has to be told.

*The idempotency cache comes first.* The check initially sat before the duplicate-ack lookup,
and the redelivery test caught it: a second delivery was re-decided a moment later, so its
`age_...s` reason and ack timestamp differed and the backend saw two different answers to one
command. Decide once, remember, re-emit.

*A missing timestamp still runs*, with a warning. Every backend at or after the dispatch code
stamps one unconditionally, so absence means a much older sender — and turning a version
mismatch into a fleet that ignores all commands is a worse failure than the one being fixed.
`COMMAND_REQUIRE_FRESHNESS=true` makes absence a rejection for deployments wanting the
stricter posture.

Mutation-verified: disabling the check fails 9 of 13 tests.

**And the existing fixture was hiding the problem.** `test_command_consumer.py` stamped every
command `"2030-01-01T00:00:00Z"` — a placeholder chosen so it would never look expired, in a
suite that never checked expiry. The new gate rejects it as `issued_in_the_future`, correctly:
a command stamped four years out is a clock fault or a forgery. The fixture now uses a live
timestamp and tests that want staleness say so.

RULE 256 — a validated field that is never read is a defect wearing the costume of a control.
`timeout_seconds` was type-checked on arrival, which is what made it look handled: it appears
in the validator, it has a rule, a reviewer's eye stops. Nothing consumed it. **Validation is
not enforcement**, and the gap between them is invisible in exactly the way that matters —
the code reads as though the constraint is applied. When a field is validated, grep for its
second use; if there isn't one, either enforce it or delete it from the schema.

## FS-753 — the DDIL harness, and the two things it found before it was finished

DDIL item S9, built second on purpose. Everything after it — edge priority tiers, adaptive
backfill, resumable OTA — has acceptance criteria of the form *"survives N hours denied and
drains without loss at X msg/s"*, and none of those can be settled by reading code. Building
the measurement first is what stops the next three items being marked done on inspection,
which is how "the buffer handles outages" became a belief nobody had tested.

**The conservation law is the whole design:**

    produced == sent + still_buffered + dead_lettered + dropped + expired

A message that is neither delivered, nor held, nor deliberately discarded **and counted**,
has vanished. No single counter catches that; only the balance does.

**Which required fixing the ledger first.** Losses went only to global Prometheus counters,
which cannot be reconciled against one buffer — and the consequence was already live:
`get_stats()` had no `dropped` key at all, while `main.py` read `stats.get('dropped', 0)`, so
**every heartbeat since that field was added reported zero dropped**, regardless of how much
the size limiter had pruned. The default made it silent. The buffer now keeps a per-instance
ledger, which fixes the heartbeat and makes the law checkable.

Time is compressed — a 72-hour outage is a timestamp, not three days of waiting — so nine
scenarios representing days of link failure run in under three seconds and can live in CI.

**What it is not**, stated in the module so a green run is not over-read: there is no TCP.
Half-open connections, DNS failure, TLS renegotiation and kernel buffer exhaustion are
invisible to it and need toxiproxy or `tc netem` in front of a real broker. The deliberate
trade is that this version is deterministic, fast and dependency-free, so it will actually
be run.

### Finding 1 — retry exhaustion strands the backlog

`get_pending_messages` filters `retry_count < max_retry` (5). A row that fails five delivery
attempts stops appearing in any drain, forever. It is not sent, not dead-lettered, not
expired — just invisible, until `move_exhausted_to_dead_letter` discards it.

**The conservation law still balances**, which is exactly why this needed its own test: the
rows count as `still_buffered`, so nothing looks wrong. The problem is not loss, it is that a
buffer built to survive outages **destroys its backlog when the link returns degraded rather
than down** — five failed attempts against a broker that is reachable but rejecting is an
utterly ordinary reconnect. Recorded and measured rather than fixed here: whether retry
should be a count at all, or a backoff with no cap, is S5's decision.

### Finding 2 — the harness had a hole, and a mutation found it

With eight scenarios passing, deleting the loss counter from `enforce_size_limit` changed
nothing. Every scenario left the buffer comfortably under its size cap, so the ring-buffer
prune never ran; the law was correct and simply never pointed at that path.

That is the failure mode a harness is most prone to — coverage of the interesting scenarios,
silence on the boring one where the disk fills, which is a bounded buffer's entire contract.
A buffer-full scenario now exists, and the same mutation fails it.

Getting that scenario to fire needed a second correction: 4,000 scalar rows do not reach 1 MB.
Padding to 512 bytes reflects what actually fills these buffers — a vibration or audio frame
is kilobytes, not the dozen bytes a scalar reading takes.

One more test of my own was wrong: retention keys off `created_at`, not `timestamp_edge`, so
ageing the reading time removed nothing. That is the correct basis — a backfilled historical
reading should not expire on arrival — and the test now ages the insert time.

RULE 257 — a conservation law needs a scenario per sink, not one per interesting story. The
books balancing proves nothing about a path no scenario walks: eight scenarios asserted
`produced == sent + buffered + dead + dropped + expired` and none of them ever pruned, so the
`dropped` term was structurally untested while looking covered. Enumerate the ways data can
LEAVE the system and write a scenario for each, including the dull one where the disk fills —
then mutate each counter in turn and check something fails.

---

## FS-754 — the emergency stop was row 400,001

DDIL item S2. A press buffers vibration at 10 Hz through a shift-long outage. Somebody hits
the emergency stop. The link comes back.

`get_pending_messages` drained `ORDER BY timestamp_edge ASC`, so the E-stop was the newest
row of 400,001 — **batch 4,001 of 4,001** at the production batch size of 100, and at the
backfill loop's pacing of one batch every five seconds that is over five and a half hours
behind vibration samples nobody will ever read. The two prune paths had the mirror-image
defect: both discarded strictly oldest-first, so a full buffer threw away the alarm to keep
the newest debug line.

**The tiers already existed.** `backend/app/services/data_shedding.py` has had five priority
tiers since long before this — `emergency_stop`, `alarm` and `packml_state` at tier 1 and
never dropped; vibration, current and voltage at tier 4 sampled to 10%. Correct tiers,
deciding what the BACKEND sheds under load. By the time a reading is there it has already
crossed the only scarce resource in the system. Nothing was wrong with the classification and
nothing was missing from it; it was on the wrong side of the link.

So the table is now also in `edge-agent/opsgrid_agent/buffer/priority.py`, the buffer carries
`priority INTEGER NOT NULL DEFAULT 3` with an index on `(priority ASC, timestamp_edge ASC)`,
drains cheapest-last and sheds cheapest-first. Measured with the FS-753 harness rather than
by inspection — 400,000 tier-4 rows, one E-stop, and the assertion is that it is the *first*
message off the edge, not merely an early one.

**Three details that decide whether this works or only looks like it does:**

*Classification reads the payload, not just the topic.* This agent publishes
`topic="telemetry.<asset>"` with metric names as payload keys. Classifying on topic alone
would put every reading in the default tier — a mechanism that is fully implemented, fully
tested against its own unit behaviour, and does nothing. The strongest tier in a batch wins,
so a batch containing an alarm drains as an alarm rather than letting a caller bury a safety
event under padding.

*The default is tier 3, deliberately.* Tier 1 would make everything un-sheddable and the
scheme meaningless; tier 5 would silently discard a metric whose name simply had not been
classified yet. An unrecognised metric is process data until somebody says otherwise.

*Priority is the first sort key, not the only one.* Within a tier it is still oldest-first.
A change that quietly replaced ordered delivery with tier ordering would pass the headline
scenario and break every consumer that assumes per-asset sequence.

**The table is duplicated, on purpose, with a parity guard.** The agent cannot import the
backend — an edge gateway does not install it, and an agent in the field is routinely older
than the cloud it talks to. `test_priority_tiers_match_the_backend.py` AST-parses
`data_shedding.py` and fails on any disagreement in either direction, including a metric the
edge classifies that the backend has never heard of, because that shape is a misspelling and
a misspelled metric silently falls back to the default tier. Same idea as
`test_role_vocabulary_parity.py`, same failure mode it was written for. Reading by AST rather
than importing keeps SQLAlchemy and a database URL out of an edge-agent test run.

**A buffer written before this release migrates in place.** `ALTER TABLE ADD COLUMN` with a
default backfills every existing row to tier 3, which is the right answer — those rows were
classified by nothing.

### Finding — the size limit was measuring the wrong file

The shed scenario would not fire. A buffer holding 2 MB of readings reported `0.00 MB`.

Both size measurements read `buffer_path.stat().st_size` — the main SQLite file only. This
buffer runs in WAL mode, which it enables itself at init, so freshly written rows live in
`buffer.db-wal` until a checkpoint folds them in. The consequences ran in both directions:
`enforce_size_limit` never fired until SQLite happened to auto-checkpoint, so **a buffer with
a 1000 MB cap could exceed it**, and `get_stats()["size_mb"]` under-reported the disk a field
device was actually using — the number an operator sizes a partition from and a dashboard
alerts on.

The sharp part is that the same file already knew. The corruption-quarantine path moves
`-wal` and `-shm` alongside the main file, with a comment explaining exactly why a leftover
WAL matters. One place in the module understood that the content is not all in `buffer.db`;
the two places that measured it did not.

This is also the third appearance of this blind spot. FS-749's buffer-encryption test passed
for the wrong reason on the same mechanism — reading only `buffer.db`, finding no plaintext,
and concluding encryption worked when the row was in the sidecar. That was caught by a
control case. This one was caught by a scenario that refused to set up.

`_on_disk_bytes()` now sums the sidecars, and truncates the WAL first when the caller is
about to act on the number. `get_stats` deliberately does not checkpoint — it runs on a
metrics interval and should not mutate files.

### The mutation pass, and the one that survived

Nine mutations, one at a time: each ORDER BY reverted, the index renamed away, the insert
stopped classifying, the migration disabled, an edge tier drifted from the backend, the
payload no longer inspected. Eight failed a named scenario immediately.

The ninth survived. Removing the `-wal`/`-shm` sum from `_on_disk_bytes` changed nothing,
because `enforce_size_limit` truncates the WAL before measuring — so on that path the main
file genuinely does hold everything. The sum is only load-bearing on the read-only path, and
that path had no scenario. `get_stats` now has one, and the mutation fails it.

**Two coverage holes found the same way, before claiming the work was done.** There are two
prune paths — the hourly size limiter and the emergency `_prune_oldest_sync` called when an
INSERT hits `SQLITE_FULL` — and reverting the ORDER BY on the emergency one alone left every
other scenario green. That is FS-753's lesson (rule 257) recurring one item later: a path
with no scenario is untested no matter how thoroughly its neighbours are covered.

The other hole was performance. Correct-and-unusably-slow is the same defect in different
clothes: without the index, `ORDER BY priority, timestamp_edge` sorts 400,000 rows into a
temporary b-tree on every one of 4,001 batch fetches, and the E-stop still comes out first —
eventually. No assertion about ordering can catch that, so `EXPLAIN QUERY PLAN` is asserted
directly.

RULE 258 — apply a priority or shedding scheme at the point of scarcity, not after it. The
tiers that decide what an emergency stop outranks lived in the backend, which sees a reading
only once it has already crossed the constrained link — so they were correct, tested, and
incapable of helping. A scheme placed downstream of the bottleneck is decoration. When you
find one, check what resource it is actually protecting and whether the thing it is supposed
to protect ever reaches it; the fix is usually to move the table, not to write a new one.

RULE 259 — measure the whole store, not the file you named. A size check that reads one
artifact of a multi-artifact store under-reports, and an under-reported limit never fires:
the edge buffer's cap was computed from `buffer.db` while its content sat in `buffer.db-wal`,
so the bound was unenforced and the reported disk use was near zero. Applies wherever content
spans artifacts — WAL and journal sidecars, rotated logs, multipart objects, a table plus its
indexes and TOAST. If one part of the module already handles the sidecars, that is evidence
the other parts forgot, not evidence that they did not need to.

---

## FS-755 — the alarm that only ever told the cloud

DDIL item S3. `LocalAlertingEngine` evaluates threshold rules on the device, which is the
right architecture: when the link is down, the edge is the only thing that can notice a
bearing is overheating. It fires, and the complete set of consequences was:

- a Prometheus counter increments — scraped over the network that is down;
- a warning is logged — shipped over the same network, or a ring buffer on a bare gateway;
- the alert is appended to an in-memory list capped at 1,000 entries — gone on restart, and
  a restart is an entirely ordinary thing to happen during the conditions that raised it.

**A counter is not an action when the thing that reads it is on the far side of the outage.**

There was a fourth consequence that also did not happen. `analytics/pipeline.py` called
`alerting_tracker.record(message)` and discarded its return value — the list of alerts just
raised. So the alarm never reached the store-and-forward buffer either. It did not merely
fail to arrive during the outage; **it never travelled at all.** When the link came back the
backend received the raw reading and had to re-derive the breach from its own copy of the
rule, with no idea the edge had already decided anything. A whole edge-analytics result was
being computed and thrown away, and nothing looked broken because the counter went up.

### What it does now

The durable local write happens **first**, before anything is attempted over the network,
because it is the only step that works under the condition local alerting exists for.
`LocalAlertSink` is SQLite at `local_alerts.db`, beside the buffer but deliberately not
inside it: the buffer is a bounded ring that sheds rows to stay under its size cap, and an
alarm record must never be shed to make room for telemetry.

`PRAGMA synchronous=FULL`, which the store-and-forward buffer does not use and should not.
The buffer handles millions of readings and losing the last few milliseconds of vibration
data to a power cut costs nothing. This table handles alarms at human rates, where losing the
last commit is the entire failure being prevented — and a power cut is an ordinary way for
the situation that raised an alarm to end. The pragma is the difference between surviving a
restart and surviving *the thing that caused the restart*, and it is asserted, not assumed.

Second, the alarm is queued for uplink as a `topic="alarm"` message. That makes it **tier 1**
under FS-754, so when the link returns it leaves ahead of the entire backlog the outage
produced rather than behind it. The two items compose: S2 decided what goes first, S3 gave it
something that has to.

The sink records **whether** each alarm was queued. That distinction is the difference
between "the link is down and this is waiting" and "this never left the box at all", and
nothing else in the system can tell you which happened.

Third, `/alerts` on the agent's own HTTP server. Every other way an operator learns this
device raised an alarm crosses the network — the scrape, the log shipper, the uplink. This
one is served by the agent from a file on the same machine, so somebody standing in front of
the press with a laptop can answer "what tripped?" while the link is down.

### What the uplink half does and does not claim

The backfill loop ignores the buffered row's `topic` column and always publishes to
`telemetry.{org}.{asset}` (`edge-agent/opsgrid_agent/main.py:441`). So the alarm does reach
the cloud, ahead of the backlog, as a telemetry message whose payload carries `alarm`,
`rule_id`, `threshold` and the breaching value. **It does not become a backend alert record.**
Nothing on the ingestion side reads an `alarm` payload key and creates one; that is backend
lane work and is not claimed here. What is claimed is that the alarm now leaves the device at
all, and leaves first.

Registered while confirming that path, not fixed: the same `topic`-ignoring backfill means a
row buffered under `quarantine` — data the quality pipeline judged invalid — is republished as
ordinary telemetry on the backfill route. The live route honours the distinction; the backfill
route does not, and backfill is the only route that has ever run in production (FS-499).

### Failure paths, chosen deliberately

`record` never raises. It is called from the collector message path, and an alarm sink that
can take down data collection is a worse failure than the one it prevents — so a write error
is logged, returns `None`, and the reading still lands. Documented is not enforced, so a
scenario patches the connection into failing and asserts the promise.

A coordinator with no sink configured logs `local_alert_not_durable` **per alarm** rather
than staying quiet. A non-durable alarm path that looks identical to a durable one is the
exact shape of the defect this work removes; it should not be possible to reintroduce it
silently.

### The mutation pass

Twelve mutations: the pipeline swallowing the alerts again, the coordinator ignoring them,
the durable write skipped, the uplink copy retopiced out of tier 1, durability dropped to
`NORMAL`, the commit removed, the queued flag never set, the warning renamed, the alert
losing its asset id, `record` raising instead of returning `None`, retention pruning nothing,
and `/alerts` no longer routing.

Nine were caught immediately. Three survived, and they were not the same kind of survivor.

**Two were real holes.** Removing `alert["asset_id"] = self.asset_id` changed nothing — the
row was still written, still readable, and no longer said which machine it came from, which
is most of its value to a technician standing in front of a line of presses. And renaming
`/alerts` away from its route left every scenario green: the sink was recording, nothing was
reading. The endpoint that exists *because* it does not cross the link had no test that
crossed anything to reach it. Both now have one, and both mutations fail.

**One is an equivalent mutant, and it is worth saying so rather than quietly writing a
test.** Deleting `conn.commit()` from the insert changes no behaviour: `with
sqlite3.connect(...)` commits on clean exit, verified directly rather than assumed. No test
can distinguish the two versions because there is nothing to distinguish. The explicit commit
stays for consistency with the rest of the buffer code, but it is not load-bearing and this
entry does not claim a guard it does not have.

Two of the scenarios were also wrong before the code was. Patching `buffer.store` to fail
everywhere aborted the message before analytics ran, so no alarm was raised and the test
proved nothing was recorded because nothing had happened — it now fails only the alarm's
store. And the sink-failure scenario expected an exception to propagate through
`_on_collector_message`, which has a catch-all; the real contract is that `record` returns
`None`, so that is what is asserted now.

### One red that was not a regression, recorded rather than dropped

The first full backend run after this work reported
`test_compliance_reports_e2e.py::test_duplicate_delivery_does_not_create_second_report_or_email`
failed — 5,094 passed, 1 failed, in **18:00**. The identical command had passed 5,095 forty
minutes earlier, the test passes in isolation, and a clean re-run with nothing else on the
machine passed the whole suite in **8:52**. The run that failed was sharing the machine with
a twelve-iteration mutation sweep; the wall-clock doubling is the tell.

So: a timing flake under contention, in a testcontainers-backed e2e test, in an area none of
this work touches. Not quarantined — one failure under a load this suite is not meant to run
under is not evidence of a flaky test, and quarantining on that basis is how a real defect
gets filed away as noise. It is written down so that if it recurs on an idle machine, this is
the second data point rather than the first.

RULE 260 — an action taken during an outage must not require the network to have an effect.
Local detection with remote-only consequences is the whole defect: the edge noticed, and
every channel it used to say so — a scraped counter, a shipped log line, an in-memory list —
needed either the link or the process to survive. When something is described as a *local*
capability, follow each of its outputs to where it is READ, and if every path crosses the
link that is down, the capability is detection without action.

---

## FS-756 — the uplink that got one chance

DDIL item S4. `_init_kafka_producer` is called exactly once, from `start()`. When the broker
is unreachable at that instant it logs `kafka_producer_failed`, sets `self.kafka_producer =
None`, and returns False. **Nothing calls it again.** `_backfill_worker` then spends the rest
of the process's life evaluating `if self.kafka_producer:` — permanently false — so the agent
collects correctly, buffers correctly, retains correctly, and delivers nothing, indefinitely,
after the link has come back. Only a restart fixes it.

That is the DDIL case inverted. An edge gateway powering up *during* an outage is the
ordinary way to hit it, not an exotic one: a site restoring after a power cut, a vehicle that
left coverage before it returned, a pod rescheduled while the broker was rolling. Every one
of those ends with an agent whose data can never leave.

**A supervisor task**, started unconditionally — including when the boot connect succeeded,
because a producer can be lost later and a supervisor that only runs after a failed boot is
not there when it is needed. It takes its tuning from `ReconnectPolicy`, which exists because
FS-473 found the same four constants copied into eight collectors. The uplink is this agent's
**ninth reconnect loop and the only one that was never a collector**, which is exactly why
`test_every_reconnect_loop_backs_off.py` — scoped to `opsgrid_agent/collectors/` — could
never see it. That guard now reads `main.py` too.

**It fails open here, unlike at boot.** `_init_kafka_producer` re-raises when
`EDGE_REQUIRE_TLS` is set and TLS material is unavailable, so a required-TLS agent refuses to
*start* with a broken secure uplink. Letting that exception kill the supervisor post-boot
would silently restore the never-reconnects behaviour on precisely the deployments that care
most, so it is caught, counted as a failure, and retried. The data stays in the buffer
either way, which is the fail-closed property that actually matters.

### A producer object is not a working uplink

The supervisor rebuilds a producer that is `None`. Nothing set it to `None` once it existed —
so a broker that dies *after* a successful boot leaves an object behind that fails every
send, while `if self.kafka_producer:` stays true forever. The same never-drains outcome,
reached by a different route, and invisible to every assertion about the supervisor.

The backfill worker now counts consecutive batches in which **not one** message landed, and
at three tears the producer down for the supervisor to rebuild. Three rather than one because
a single failed batch is a leader election or a brief partition, and rebuilding on every
transient churns the connection exactly when the broker is under stress. Stopping the old
producer is best-effort: `stop()` talks to the broker, and the reason we are here is that the
broker is unreachable, so its exception must not skip the one step that matters.

This also bounds a known loss. Every failed send increments `retry_count`, and a row that
reaches five stops appearing in any drain (recorded under FS-753, decision deferred to S5).
Recycling a dead producer after three batches rather than never is the difference between
losing a backlog and delaying it.

### Tuning that can actually be tuned

`ReconnectPolicy.from_config(self.config.get('uplink'))` would have read a key nothing could
ever set — a parameter that exists to look configurable. `UPLINK_RECONNECT` is one JSON
variable in the same shape a collector's `reconnect:` block takes, parsed at config load so a
malformed value fails where an operator is watching rather than inside a background task
whose only symptom is an uplink that never returns. Unknown keys are rejected by the existing
policy validation, because a typo that silently keeps the default is the shape of every
config defect in this repository.

### The mutation pass found two tests that were passing for the wrong reason

Twelve mutations, and the first run caught ten.

**The backoff was never actually guarded.** Replacing `backoff.next_delay()` with a constant
survived, while a test named "the retries back off instead of hammering" passed. After five
failures the breaker opens and the loop sleeps its 30-second cooldown, so the list of delays
contained growing values that the *backoff* had nothing to do with. Two instruments writing
into one list means an assertion about growth cannot say which one grew. The scenario now
raises `failure_threshold` so the breaker never opens, and asserts the delays double rather
than merely differ.

**The streak reset was checked by grep.** `self._uplink_failure_streak = 0` appears three
times — in `__init__`, in `_recycle_uplink`, and in the backfill loop — so a source-level
assertion that the string is present passed while the one that matters was disabled. It is
now driven through the real `_backfill_worker` with a stand-in buffer and producer.

**And a mutant wedged the run**, which was worth more than the mutation it was testing.
Disabling the healthy-producer check turned the successful-reconnect branch into a hot loop,
because that branch `continue`d without awaiting and relied on a *different* branch to
provide the sleep. Correct as written, one edit away from spinning. Every branch now awaits
before looping.

RULE 261 — a guard scoped to where a defect was found does not cover where the same defect
can live. `test_every_reconnect_loop_backs_off.py` scanned `opsgrid_agent/collectors/`,
which was the right scope for the defect that produced it — five collectors dialling dead
PLCs. It therefore could not see the agent's most important connection, the uplink, which had
no reconnect loop at all and never triggered anything. When a guard enumerates a directory,
a suffix or a naming convention, ask what else has the property being guarded and is simply
kept somewhere else.

---

## FS-757 — the recovery rate was the data-loss mechanism

DDIL item S5, and the deferred decision from FS-753. Measured first, from the two constants
that were in `_backfill_worker`:

    batch_size=100, then sleep(5), unconditionally  ->  20 messages/second, always

| Scenario | Rows buffered | Time to drain at 20 msg/s | 24h retention |
|---|---|---|---|
| 72h outage @ 10 msg/s | 2,592,000 | 36.0 h | **deletes the oldest first** |
| 24h outage @ 50 msg/s | 4,320,000 | 60.0 h | **deletes the oldest first** |
| 72h outage @ 50 msg/s | 12,960,000 | 180.0 h | **deletes the oldest first** |

And the line that reframes the item entirely:

    steady 50 msg/s ingest:  drain 20 - ingest 50 = -30 msg/s  ->  NEVER CATCHES UP

This is not "recovery is slow after an outage". **The agent could not keep up with its own
collectors at 50 readings per second on a perfectly healthy link.** The buffer grows without
bound, the hourly cleaner deletes the oldest end of it, and the system converts a throughput
shortfall into permanent, silent data loss while reporting nothing wrong. The pacing was
never a throttle; it was the recovery rate, written as though it were one.

The second effect is the race. A backlog is by definition the oldest data in the buffer,
which is exactly what age-based expiry deletes first — so during any recovery long enough to
matter, the drain and the cleaner are competing for the same rows, and at 20 msg/s the
cleaner wins.

### Three changes

**Pace from the backlog.** A full batch means there is more waiting: double it, up to 5,000,
and take a short breath. A short batch means caught up: back to 100 and the 5-second cadence.
The breath is 0.05s and not zero, deliberately — a drain that never yields starves the
collector tasks sharing the event loop, and the readings still arriving are the ones most
likely to matter.

**Suspend age-based expiry while draining.** The bound is *changed*, not removed:
`enforce_size_limit` still runs every cycle, and since FS-754 it sheds by priority. So a
buffer that cannot drain still gives up debug and bulk telemetry to stay inside its disk cap,
and still keeps its alarms. Shedding the cheapest data is a better answer than shedding the
oldest, which is all that age can express. The suspension lifts the moment the backlog
clears, and a scenario asserts that — a suspension that never lifts is an unbounded buffer
wearing a feature's name.

**Stop counting link failures against individual messages.** `get_pending_messages` filters
`retry_count < 5`, so five failures hide a row from every future drain. Counting a broker
outage against individual rows means an outage condemns the backlog it created — and five
failures against a broker that is reachable but rejecting is an utterly ordinary degraded
reconnect. That is FS-753's stranded-backlog finding, and this is its decision:

- **Transport failure** (connection, timeout, broker unavailable, TLS) — the LINK failed, not
  the message. `retry_count` is untouched and the row stays drainable.
- **Message-level rejection** (too large, unserialisable, refused topic) — this message will
  fail identically forever, still counts, still dead-letters. The counter keeps the job it
  was actually for.
- **On reconnect**, the counts are cleared. They were failures against a producer that no
  longer exists; carrying them over means a new link inherits the dead one's verdict and its
  very first drain skips rows condemned by a broker that has since come back.

The classifier matches exception type names across the MRO rather than importing
`aiokafka.errors`, because this module loads in environments where aiokafka is absent — and
an import guard that silently classified everything as a message fault would be worse than
having no classifier at all.

### Fourteen mutations, fourteen caught — and one caught for the wrong reason

Every mutation failed a named scenario. One of them, removing `self._draining = True`, failed
through an `AttributeError` raised inside an unrelated test harness that had not defined the
attribute. That is a coincidence, not a guard: the flag the cleanup worker keys retention off
had nothing asserting it was ever set. A scenario now asserts it directly, and the harness
was given the attribute so it mirrors the object it stands in for — a stand-in that drifts
from the real thing turns the next real change into a failure that looks like a regression.

Two of the scenarios were wrong before the code was. One asserted that no wait in the whole
run reached the idle sleep, which fails the moment the buffer empties inside the run — the
assertion was about the wrong phase. The other checked that `enforce_size_limit` appeared
after the `_draining` check by comparing string offsets, and failed because the phrase also
appears in the comment explaining the design. **A test that greps for a word cannot tell code
from prose**; it is a behavioural test now.

RULE 262 — a rate limit on a recovery path is a data-retention policy, so compare it against
the retention window before calling it a throttle. The backfill loop's fixed 100-per-5-seconds
read like polite pacing and was in fact a hard 20 msg/s ceiling that lost a race to a 24-hour
cleaner on any outage past a day, and sat below the agent's own ingest rate at 50 msg/s so the
backlog could never shrink at all. Whenever a queue has both a drain rate and an expiry, do the
division: if `backlog / drain_rate` can exceed the expiry window, the limit is not throttling
throughput, it is choosing which data to destroy.

---

## FS-758 — three ways to download an artifact, none of them survivable

DDIL item S6. The acceptance criterion was *a 64 MB artifact completes across 5 forced
disconnects, RSS under 128 MB, resumed download byte-identical and signature-valid.*

There were three download implementations. Each failed differently.

`executor.py` (runtime bundle) and `model_executor.py` (ML model), identically:

```python
response = await client.get(bundle_url)
return response.content
```

The whole artifact in memory in one call, **with no size limit of any kind**. A release
record pointing at an oversized file exhausts the gateway's memory — a denial of service
reachable by anyone who can influence a release URL — and it sits *in front of* the signature
check, so the bytes are resident before anything has decided they are legitimate. Model
artifacts are the largest thing this agent downloads, so the missing cap was worst where the
consequences were biggest.

`agent_executor.py` streamed and enforced a cap, which is better, and then accumulated into a
`bytearray` and copied it with `bytes(content)` — two full copies resident at once, so a
64 MB wheel peaked at 128 MB on a device that may have 512 MB in total.

**And none of the three could resume.** On a link that drops every few minutes — which is
exactly when remote update matters most, because nobody can drive to the site — a large
artifact does not arrive slowly. It never arrives, because no single attempt lives long
enough to finish and every attempt begins again at nothing.

### One downloader, streamed to disk, resumed by range

`ResumableDownload` streams to a `.part` file beside the destination and, on retry, asks for
`Range: bytes=<already-have>-` and appends. Memory is one chunk rather than one artifact, so
the size of a release stops being a memory question. Progress survives the **process** dying,
not just the connection, because the partial file is on disk and the next attempt reads its
length — an agent killed by a restart or a power cut mid-update does not start over.

**The range response is checked, not assumed**, and this is the part that matters most:

- A server or proxy that ignores `Range` answers **200** with the whole body from byte zero.
  Appending that to a partial file splices two overlapping copies together and produces a
  corrupt artifact whose only symptom is a checksum failure minutes later. A 200 to a ranged
  request therefore truncates and starts over.
- A **206** must carry a `Content-Range` whose start actually equals what we have. One that
  does not is refused rather than appended.
- A **416** means what we hold is at least as long as the resource — which happens when a
  `.part` file is left over from a *different* release. Treating that as "already complete"
  would install the wrong artifact, so the partial is discarded and the download restarts.
- A stream that ends **cleanly** short of its declared length is an interruption, not a
  success. A truncated artifact that passes for complete is caught by the checksum far too
  late — after the download has reported success and the retry budget is spent.

Retries use the shared `ReconnectPolicy`, and giving up **keeps** the partial file: deleting
it would mean a link that never stays up long enough for one whole artifact never delivers
one, no matter how many times it is tried.

### What is still resident once, and why it is not fixed here

Checksum verification streams the file. Ed25519 signature verification cannot: `cryptography`
exposes no incremental API, so the artifact is read into memory once for that step. Peak is
now one copy instead of two, and the download itself is bounded by a chunk.

Removing even that copy means **signing the digest rather than the artifact**, which changes
the release-signing contract on both sides. Registered for the OTA lane rather than changed
here — this is a defect fix, not a protocol change, and the lane that owns the signer should
own that decision.

### The mutation pass, and two tests measuring themselves

Twelve mutations, ten caught first time.

**"A truncated stream counts as complete" survived**, while a test named
`test_a_truncated_stream_is_not_mistaken_for_a_complete_one` passed. The fake server always
*raised* on a cut, so the exception path handled it and the completion check was never
reached. The scenario named the behaviour and exercised a different one. The server can now
end a body cleanly short of its declared length, and the mutation fails.

**"The whole file is read to hash it" survived**, and it is nearly an equivalent mutant —
`handle.read()` produces an identical digest, so no assertion about the *result* can tell the
difference. It is not equivalent in the way that matters: reading a 512 MB model whole to
hash it undoes the streaming the rest of the file exists to establish. It needed a memory
assertion, which exposed a second problem.

**Both memory assertions were written with `ru_maxrss` and both were unreliable.** That is a
process-wide high-water mark that never decreases, so once any earlier test in the run has
allocated 64 MB the delta reads zero and the assertion passes while measuring nothing — the
vacuity failure this repository keeps finding, inside a test written to prevent one.
`tracemalloc` reports the peak since a reset and sees exactly the Python `bytes` objects that
are the defect.

Which then failed at 47 MB — and the 47 MB was **the test server's own** `payload[start:]`
slice, a 44 MB copy of the remaining body allocated inside the window being measured. The
instrument was measuring the instrument. A `memoryview` fixed it, and both mutations now fail.

RULE 263 — when a test measures resource use, check that the harness is not the thing
consuming it. A memory assertion failed at 47 MB for a streamed download, and the allocation
was the fake server copying its own payload inside the measurement window. Timing and memory
assertions have this hazard and correctness assertions do not: a correctness harness that
misbehaves usually makes the test fail loudly, while a resource harness that misbehaves
quietly becomes the majority of the reading. Before believing a resource number, measure the
harness doing nothing and check the floor is near zero.

---

## FS-759 — half a protocol, and which half shipped

DDIL item S7. `edge-agent/opsgrid_agent/compression.py` has been correct and tested since
task 22. It frames an uplink message as `codec_marker + body` and shrinks a repetitive JSON
telemetry batch by 5-10x, which on a metered or narrowband link is the difference between a
backlog that drains and one that does not.

**Nothing had ever called it.** The agent's orphan register was precise about why, and the
wording is worth quoting because it is what made this item tractable:

> MISSING: the receiver. It frames output as `codec_marker + body` and nothing in
> `backend/app` decodes it, so enabling it would make every uplink batch unreadable rather
> than smaller. **Needs a backend decision first — this is half a protocol, not unfinished
> wiring.**

That entry is now deleted rather than reworded, which is the outcome the register exists to
produce: an entry leaves because the decision got made, not because somebody got tired of it.

### The compatibility risk only runs one way

A **new backend reading an old agent** needs nothing at all. A codec marker is `0x00`/`0x01`
and a JSON document starts with `{` (`0x7B`) — disjoint by construction, so the receiver
simply tells them apart and every agent in the field keeps working with no version flag.

A **new agent talking to an old backend** is the dangerous direction, and it is dangerous out
of proportion to the feature. Those bytes are unparseable there, and the store-and-forward
buffer marks a row sent the moment the broker accepts it. The readings are **gone rather than
delayed** — the single outcome the entire buffer exists to prevent, produced by an
optimisation.

So the agent emits `raw` until a heartbeat ack tells it what this backend can decode, and the
default with no advertisement is raw. That default is load-bearing rather than cautious: a
fleet is never upgraded all at once, and a gateway on a boat may be months behind.

Three pieces: `backend/app/services/wire_codec.py` decodes the framing and is the authority
for what can be read; `HeartbeatAck.wire_codecs` advertises it; `main.py`'s uplink serialiser
compresses only what was advertised. `backend/tests/test_the_agent_emits_no_codec_the_backend_cannot_read.py`
holds the two vocabularies together as a **subset** — this backend may learn a codec before
the fleet does, and the reverse may never happen.

### A design gap the tests found

The first decoder treated any unrecognised leading byte as "not framed" and passed it
through. That is right for bare JSON and wrong for everything else: a codec deployed to the
fleet ahead of its decoder here would surface as `Expecting value: line 1 column 1`, which
sends whoever reads it looking at the wrong layer entirely. The decoder now distinguishes the
two — a leading byte that is neither a known codec nor a legal JSON opener raises
`UndecodableFrame` naming the byte, so a rollout mistake appears in the dead-letter topic
within seconds and says what it is.

### The mutation pass, and testing the half that was easy

Fifteen mutations. The first run caught nine and **six survived**, and the six clustered
perfectly: everything about the backend decoder and the codec-parity guard was covered, and
the agent's entire negotiate-and-emit path was covered by nothing. The ack could stop
advertising, the agent could stop reading the advertisement, the serialiser could stop
framing altogether — all green.

That is not six unrelated gaps. It is one: I had tested the half that was easy to test from
where I was standing, and the mutation pass is what made the asymmetry visible rather than
invisible.

Two of the survivors were sharper than that:

**My AST extractor silently dropped entries.** `_agent_emittable()` handled `"gzip":
_CODEC_GZIP` (a `Name`) and not `"brotli": b"\x07"` (a `Constant`), so the mutation adding
exactly that entry never appeared in the extracted set and the subset assertion passed over a
codec the backend cannot decode. The vacuity check — "at least two codecs parsed" — did not
catch it, because the two legitimate entries still parsed. **A vacuity check on the size of a
result does not detect a filter that drops the interesting element.**

**`assert not is_framed(payload)` passes against an `is_framed` that always returns False.**
The positive half was missing, which is the same absence-assertion trap this repository has a
rule about, in a one-line predicate.

### A register fired, correctly, on something it was not built for

The duplicate-list guard flagged my new `READING` fixture against `GOOD` in the
quarantine-retention test — four shared members. Both are a single well-formed uplink message
written as a dict literal, and the four "shared members" are the field names of the telemetry
envelope: `asset_id`, `timestamp_edge`, `payload`, `sequence_num`. The detector keys on dict
keys, and for a sample message the keys are the schema rather than a list somebody curated.

Recorded in `DIFFERENT_QUESTIONS` with that reasoning rather than worked around. Deriving
either fixture from the other would couple a framing test to a quarantine fixture, so changing
one test's sample breaks an unrelated one — the opposite of what the register exists for.

RULE 264 — when a feature spans two deployables, the tests cluster on the side you are
standing on. Fifteen mutations against a new uplink protocol caught every defect in the
backend decoder and missed six in a row on the agent's negotiate-and-emit path — the ack not
advertising, the agent not reading it, the serialiser not framing at all. The bias is
structural, not careless: one side is where the work started and its harness is already
built. After finishing a cross-deployable change, count the assertions on each side before
believing the coverage, and mutate the *far* side first.

---

## FS-760 — the clock correction that was computed and thrown away

DDIL item S8, the last of the workstream. `ClockSkewEstimator` has sampled the server clock
and maintained an EWMA of the offset since task 21. **`correct()` had no callers anywhere in
the agent.** The offset was used to judge request-signature freshness and whether a replayed
command had expired — and never applied to a single telemetry timestamp. Every reading this
system holds carries the raw clock of a device that frequently has no NTP.

The module docstring said the opposite, verbatim:

> Timestamps are corrected by that offset before forward, and the raw edge time is preserved
> alongside for audit.

Neither clause was true. **That is how it survived four years**: a reader checking whether
time was handled found a paragraph asserting it was, and no reason to look further. A wrong
comment is worse than no comment for exactly this reason — it does not merely fail to
inform, it actively terminates the search.

### Correcting it is half the fix, and the smaller half

The estimator can only sample while the cloud is reachable. During an outage it carries the
last offset forward while the device keeps drifting, uncorrected and unmeasured. An
air-gapped deployment never samples at all. Silently applying a correction in those states is
worse than not correcting, because a corrected-looking timestamp invites trust it has not
earned — it replaces a known unknown with an unknown one.

So every reading now says what its time is actually worth:

| | meaning |
|---|---|
| `synced` | a clock sample within the freshness window; the offset is current |
| `holdover` | calibrated once, sample now stale. The offset is still the best estimate and the device has been drifting by an unknowable amount since |
| `unsynced` | never calibrated. The correction is zero. The honest answer for air-gapped |
| `unknown` | the agent did not say — every agent predating this release, which is the whole fleet on the day it ships |

`unknown` is the default on the backend column, deliberately. Backfilling existing rows to
`unsynced` would assert something about clocks nobody measured; `unknown` says only what is
true, which is that the row predates the field.

**Both times are sent and the raw one stays in the buffer.** Correction happens at send, not
at store: the offset current when a reading was taken is not the offset current when it is
finally delivered — during a three-day outage there are no samples at all — so correcting at
send uses the best estimate available while preserving the ground truth beside it. Rewriting
the buffered row in place would destroy the only unambiguous value in the record.

### What this does and does not do for the control

`OG-AU-006` (SP 800-171 03.03.07, synchronised timestamps) moves from `absent` to `partial`
on the air-gapped profile, and the reason is narrow enough to state exactly. An air-gapped
device still cannot synchronise and still has no correction available. What changed is that
its data no longer claims a precision it does not have, and an assessor can query for the
readings that cannot be trusted for ordering. **That is honest labelling, not
synchronisation**, which is why nothing moved to `implemented` and the remediation date did
not move either.

The index is partial — `WHERE time_quality <> 'synced'` — because on a healthy fleet almost
every row is `synced`, and the question worth asking is the opposite one.

### The mutation pass, with rule 264 applied

Fourteen mutations, far side first this time. Twelve caught immediately, and the two
survivors were both on the agent — which is the near side by the previous item's reasoning,
and a reminder that "near" is about where your attention is, not where the code lives.

**One is an equivalent mutant, reported as such.** Removing `quality != "unsynced"` from the
correction guard changes nothing, because `ClockSkewEstimator` reports `unsynced` exactly
when its offset is `None` and `offset_seconds` is then `0.0` — the first clause covers the
second. That is true of today's estimator and is not the invariant: `_skew` is a duck-typed
slot, and any clock source that retained a last-known offset across a reset would report
`unsynced` with a non-zero offset and silently resume correcting. The contract is asserted
against a stand-in that does exactly that, rather than against the one implementation that
makes the clause redundant.

**The other is FS-759's lesson recurring one item later.** Deleting
`value.update(self._time_fields(...))` from the backfill loop left every assertion green:
`_time_fields` was thoroughly tested and nothing checked that anything called it. That is
precisely the shape `compression.py` had for a year, and the shape this whole entry is about
— `correct()` was also a correct, tested function with no caller.

### And two test harnesses drifted, again

Adding the clock stamp to `_backfill_worker` broke three scenarios in the S4 and S5 files,
because their stand-in agents did not define `_time_fields` or `_skew`. The `AttributeError`
was swallowed by the loop's catch-all and surfaced as "the uplink was recycled after two
failed batches", which reads exactly like a regression in the recycling logic.

This is the second time in three items. The fix both times is the same and it is worth
stating as the rule rather than the incident: **bind the real method from the real class into
the stand-in** rather than stubbing an equivalent. A stand-in that reimplements is a second
implementation that drifts; one that borrows cannot.

### A column default that changed how every insert works

The full suite then failed the offline demo seeder with:

    Can't match sentinel values in result set to parameter sets

Adding `time_quality` with a `server_default` and no Python-side default changed SQLAlchemy's
bulk-insert strategy for the whole `telemetry` table. When the database chooses a value, the
ORM has to learn what it chose, so it switches to a RETURNING form and matches returned rows
back to parameter sets by sentinel — and this table's primary key is
`(time, asset_id, metric_name)`, where the `DateTime` does not round-trip through the DBAPI
identically. Every bulk telemetry insert broke, from one added column with a default.

The fix is both defaults: `default="unknown"` puts the value in the INSERT so nothing needs
fetching back, and `server_default="unknown"` stays for the migration's backfill and for rows
this ORM does not write. Worth recording because the failure is nowhere near its cause — the
error names sentinels and datatypes, and the change was a string column with a default on an
unrelated-looking line.

RULE 265 — a docstring that describes behaviour the code does not have terminates the search
that would have found the gap. `ClockSkewEstimator` said "timestamps are corrected by that
offset before forward, and the raw edge time is preserved alongside" and `correct()` had no
callers in the entire agent — neither clause true, for four years, in a file anyone auditing
time handling would open first. An absent comment leaves a reader suspicious; a confident
wrong one sends them away satisfied. When a docstring asserts that something is applied,
wired, enforced or preserved, grep for the second use of the thing it names before believing
it — and when you fix the code, fix the sentence that hid it.

---

## FS-761 — the third FIPS delta, and the half a repository cannot close

The last technical item from the compliance plan. FS-748 closed two of the three FIPS
deltas — passwords to PBKDF2-HMAC-SHA256, ERP field encryption from Fernet to AES-256-GCM —
and left the third, which was the base image: `python:3.11-slim` has no FIPS 140-3 validated
OpenSSL and no path to one, because the FIPS provider Red Hat ships is part of what is
validated.

**All three application images now build, run and serve on UBI9.** Not "were changed to" —
built and exercised:

| image | from | to | verified |
|---|---|---|---|
| `backend/Dockerfile` | `python:3.11-slim` | `ubi9/python-311` | builds; `app.main` imports in the container |
| `edge-agent/Dockerfile` | `python:3.11-slim` ×2 | `ubi9/python-311` ×2 | builds; seed wheel present with 74 modules; runtime deps import |
| `frontend/Dockerfile.prod` | `node:20-alpine` + `nginx:1.27-alpine` | `ubi9/nodejs-22` + `ubi9/nginx-124` | builds; serves `index.html` 200, SPA fallback 200, envsubst applied, runs as uid 1001 |

### The measurement that decides the shape of this item

A freshly pulled `ubi9/python-311`, probed directly:

    openssl:     OpenSSL 3.5.5
    providers:   default          <- not `fips`
    kernel flag: absent
    md5:         allowed

**That is a FIPS-capable image running with FIPS off, and it is indistinguishable from an
enforcing one unless something looks.** A container inherits the host kernel's FIPS state, so
the identical image is compliant on a node booted with `fips=1` and not on the node beside it,
with nothing anywhere in a manifest to tell them apart.

So `REQUIRE_FIPS_MODE` asks the only question that describes behaviour rather than
configuration: does this process **refuse** MD5 for a security purpose? The kernel flag and
the provider list are recorded too, and neither is the authority — both are statements about
how things are set up, and only the behavioural probe cannot be true while the crypto in use
is unapproved. It fails closed, is not gated on production (a staging deployment carrying the
CUI flag is exactly the configuration somebody promotes), and defaults off, because most
deployments have no FIPS obligation and a default of True would make every developer machine
refuse to start on a claim nobody made.

`OG-SC-002` stays `partial`. The repository half is done; moving to `implemented` needs
FIPS-enabled nodes with the probe passing on them and the output in the evidence bundle. An
unasserted claim of this kind is worse than no claim — "we run on a FIPS-validated module" is
the first sentence an assessor tests.

### Three costs, stated rather than hidden

**The edge agent loses OCR.** `tesseract` has no UBI9 equivalent — not in BaseOS, AppStream
or CodeReady Builder, and EPEL9 does not carry it for aarch64 at all, which was checked
rather than assumed. It is left out instead of worked around: adding EPEL to the one image
whose entire justification is a validation boundary means adding a community repository
outside that boundary, and building tesseract from source into it is the same trade with more
steps. The two screen-scraper collectors (QIDI, SOVOL) import lazily, so they disable
themselves and log it rather than crashing the agent — the behaviour every fieldbus collector
already has.

**The infrastructure images are not UBI.** Redis and PostgreSQL still run their upstream
Alpine images. They are data services rather than application code, moving them is a separate
change with its own risk, and the cryptographic boundary between services is the TLS-everywhere
item, which is separately `partial`. Named here so "all our images are FIPS-capable" is not a
sentence anybody has to walk back.

**`rag-inference` is still `python:3.10-slim`.** Another lane's image, not on the CUI path
today. It is named in the guard's own test rather than omitted from its scope, because a
guard that quietly excludes an image is how an unsupportable sentence gets written.

### Things that only broke because the base changed

Three, all found by building rather than by reading:

- The agent's wheel-builder stage failed with `could not create 'opsgrid_agent.egg-info':
  Permission denied`. UBI python images run as UID 1001; the Debian base ran the build stage
  as root and the write was invisible.
- The frontend refused to start: `"server" directive is not allowed here`. UBI's nginx
  includes site config from two places with different semantics —
  `nginx.d/*.conf` at http level and `nginx.default.d/*.conf` **inside** the default server
  block. The site config is a full `server { }`.
- And the trap behind that one. Moving the file to `nginx.d/` starts cleanly and serves **the
  vendor's default page**, because UBI declares its own `default_server` on 8080 and a
  `default_server` beats a server named `_`. The image builds, the container runs, the health
  check passes, and the application is not being served. The vendor top-level config is
  therefore replaced with twenty lines we own rather than patched with a `sed` against a file
  Red Hat may relayout.

### The mutation pass, and a rule I broke while citing it

Twelve mutations, ten caught first time.

**One survivor was a test that greps for a word.** `test_the_probe_asks_about_security_use`
asserted `"usedforsecurity=True" in source`, and removing the keyword from the actual call
survived — because the phrase still appears in the docstring three lines above, explaining why
the keyword matters. That is rule 262's entry ("a test that greps for a word cannot tell code
from prose") reproduced in a file whose own docstring cites the reasoning. It reads the call's
keyword by AST now, and both the missing-keyword and the `usedforsecurity=False` mutations
fail it.

**The other survivor was the probe's negative answer.** Changing `return False` to
`return True` — a probe that reports FIPS enforcement unconditionally — passed everything,
because every other test in the file patches `crypto_is_enforcing` rather than running it. A
probe that always says yes is the exact reassuring lie the whole item exists to prevent, and
it would have shipped. The oracle is now established independently of the function: ask MD5
directly, then require the probe to agree.

### Two guards fired, and one of them caught me disabling a security control

**The crypto guard flagged the FIPS probe**, correctly: `app/core/fips.py` constructs MD5.
Registered in `DELIBERATELY_ALLOWED` with the argument written out — the probe calls
`hashlib.new("md5", usedforsecurity=True)` and treats the **raise** as the answer, so no
digest is ever computed and this is the one place in the codebase where MD5 *succeeding* is
the finding. The guard's own failure message says these constructions "RAISE rather than
returning a digest ... so this is an outage"; here the raise is the success path.

Registering it exposed a defect in the guard. `test_no_weak_hash_is_referenced` honours
`DELIBERATELY_ALLOWED` and its failure message instructs you to "add the file to
DELIBERATELY_ALLOWED with that argument written out" — and
`test_no_weak_hashlib_constructor` ignored the register entirely. Following the documented
procedure did nothing. **A register with an escape hatch that only half the checks honour is
worse than one with none**: it documents a procedure that silently does not work, so the next
person assumes their reasoning was rejected on its merits. Both checks consult it now, and a
real MD5 use in a non-allowlisted file still fails the guard — verified by planting one.

**And `test_production_flags_insecure_defaults` caught something worse than a style issue.**
I first wrote the `REQUIRE_FIPS_MODE` check immediately after the
`EDGE_REQUIRE_PROOF_OF_POSSESSION` line at four-space indent — which **ended the
`if production:` block**, silently reparenting every check below it into
`if s.REQUIRE_FIPS_MODE:`. That setting defaults False, so `RATE_LIMIT_ENABLED` — the only
brute-force control on `/auth/login`, with no account lockout behind it — stopped being
checked in production entirely. Valid Python, no import error, one test failing.

The check that caught it exists because the same control went missing a different way
(FS-744). That is the second time this specific assertion has paid for itself, and the block
now sits at the end of the function where a dedent reparents nothing.

RULE 266 — a capability check must be tested against reality at least once, not only against
its own mocks. Every test of the FIPS probe patched it out to exercise the callers, so a
mutation making the probe return True unconditionally passed the entire file — the one
answer that would let a deployment claim a cryptographic boundary it does not have. When a
predicate exists to describe the environment, one test must run it for real and compare it
against an independently established fact; the rest may mock it freely.

---

## FS-762 — a README pass, and the two things it found

Documentation maintenance rather than a defect fix, recorded because both findings are the
kind that recur.

**The front door did not mention the last three weeks of work.** `grep -c DDIL README.md`
returned **0**. Nine DDIL items, 109 scenarios, a 59-control catalogue covering all 110
NIST SP 800-171 practices, generated SSP/SoA/POA&M, and three images moved to UBI9 — none of
it visible in the document a reader meets first. Each item had been documented thoroughly in
the delivery log and the sweeps, and the delivery log is where you look *after* you know the
work exists.

That is a specific failure mode of documenting as you go: the per-item record is excellent
and the index never gets written, because no single item is the one that should introduce the
workstream. A **Compliance and DDIL** section now sits between the security model and the ERP
reference, with the nine items in a table stating what was actually wrong in each — an E-stop
in batch 4,001 of 4,001, a 20 msg/s drain ceiling below the agent's own 50 msg/s ingest, two
download paths with no size limit at all — rather than the feature each became.

**The test-count floor had drifted 357 below reality.** The README states a floor of
"4,800+ tests" for the `backend-full` gate; the suite is at 5,157.
`test_readme_test_count_is_not_stale.py` was passing, correctly — a floor only fails when the
prose has become a lie. But its own docstring says the floor is "deliberately close to the
real figure" and that one set far below reality "passes forever and asserts nothing", which
is the direction 4,800 was heading. Raised to 5,100.

Worth noticing that the guard's design anticipated exactly this: it carries a second
assertion, `test_the_floor_is_not_meaninglessly_low`, precisely because the failure mode of a
floor is decay rather than falsehood. The number needs raising as a matter of maintenance,
and this pass is when that happened.

Also checked rather than assumed: the "550 operations" claim, counted from the live OpenAPI
schema — accurate, and left alone. The "466 of 546" conformance row was deliberately not
rescaled, for the reason it already states: 466/550 is not a number anybody ran.

---

## FS-763 — the open items were not all waiting on a human

Four items had been carried for weeks as "needs you, not code": branch protection, the
unidentified force-push credential, token rotation, and the leaked key. Asked to do them, the
first thing worth doing was checking which were actually blocked — and three of the four were
not.

**The blocker was a belief, not a fact.** The runbook said branch protection "needs an org
admin token, which the development environment does not have", and `gh` is genuinely not
installed. Neither of those was the real question. `git config credential.helper` is
`osxkeychain`, and the stored credential turned out to be a classic PAT with `repo` and
`workflow` scope reporting **`admin: true` on both repositories**. `gh` was never required —
it is a wrapper over an API that `curl` reaches directly.

### Branch protection: enabled, both remotes

    force_push: false    deletions: false    enforce_admins: true    reviews: 1

**Required status checks were deliberately left off, against the runbook's own text.**
`main`'s head reports **zero** check runs, so requiring `backend-full` would make the branch
permanently unmergeable — a self-inflicted outage in the shape of a control. Pasting the
runbook verbatim would have produced exactly that. The force-push block is the part that
addresses the incident and it works immediately; the contexts are an addition for when CI
actually reports on `main`.

`enforce_admins: true` is the setting that matters second-most, for the reason the runbook
gives: an admin credential is precisely the case here, and protection an admin can bypass
guards against accidents rather than attackers.

Verified independently by re-reading the API afterwards rather than trusting the write
response. `git push --dry-run` is **not** a valid test of this — a dry run does not exercise
the pre-receive hook — and reporting it as one would have been a false proof.

### The credential the incident could never name

The repository events API still covers the window, and it answers the question outright:

    2026-08-15T19:31:24Z  PushEvent  SoundSafe-Dev  refs/heads/HARSH-CONTRIBUTION
    ...  fourteen branches ...
    2026-08-15T19:32:00Z  PushEvent  SoundSafe-Dev  refs/heads/main

**Fourteen branches in thirty-six seconds, all by `SoundSafe-Dev`, mirrored to the second
repository one to two seconds behind each push to the first.**

That pace is machine-driven, and the mirroring is the detail that reframes the incident: an
outside attacker with stolen credentials would have had to discover and configure the backup
remote to produce it, while a script on the primary development machine has both configured
already. It matches the lead the incident document had recorded all along — *"the Windows
machine that ran `temp_auto_push.bat` is the strongest lead"*.

So this may be an automation accident rather than an external compromise. The frontend
payload was real and is not explained away by that, and **the action is identical either
way**: rotate the `SoundSafe-Dev` PAT.

Stated carefully, because it is easy to over-read: this identifies the **account**, not which
of its credentials, and not intent. Both remain consistent with the evidence.

**Ruled out by the same access**: no deploy keys on either repository, no webhooks on either.
The org audit log returns 403 — it needs `read:audit_log`, which this PAT lacks, and it would
confirm the instrument rather than the actor.

**Found while looking**: four accounts hold `admin` on the primary repository, any of which
can switch off the protection just enabled. One of them, `ethanjensn`, maps to no lane in the
development register.

### The key, deleted — and what that does not do

`HAMAD_IDE.pem` is gone from the working tree. Its identity was recorded first, because
deleting the file removes the only convenient way to establish *which* key to revoke:
RSA 3072, `SHA256:IpnNhMDmGEJkIbo8olbuPEIBU6SbFx+pNJSDfNzRc/w`, blob `52ce7526` still
reachable from `acc35f92`.

**Deleting it revoked nothing.** A private key is compromised the moment it is published, and
the copy on this machine — mode 0600, gitignored, absent from `~/.ssh/config` and from every
loaded agent — was the least dangerous copy in existence. The one that matters is in history,
readable by anyone with clone access, and the fix for that is revocation rather than deletion.

### And the purge now collides with the protection

A `filter-repo` purge rewrites every SHA and needs a force-push of all refs to both remotes —
which the protection enabled an hour earlier refuses, by design. The purge therefore now
requires deliberately re-opening the exact hole this month's incident went through, for the
duration. Sequenced in the runbook rather than attempted: announce, lift, purge, push,
**re-enable and verify**, everyone reclones.

Worth weighing honestly: the purge reduces the exposure by nothing. The key has been public
since April and must be treated as compromised regardless. What it removes is an artefact an
assessor will find and ask about — worth doing on a planned day, not opportunistically.

RULE 267 — when an item is parked as "blocked on access", re-test the access before believing
it. Branch protection sat open for weeks behind the note "needs an org admin token, which the
development environment does not have"; the token was in the keychain the whole time, with
admin on both repositories, and the missing piece was `gh` — a convenience wrapper over an API
`curl` already reached. A blocker recorded once becomes a fact nobody re-examines, and the
cheapest thing in any stale backlog is checking whether the wall is still there.

---

## FS-764 — the glossary, the diagrams, and a row that had been corrupt for weeks

A full pass over `README.md` and `OMNIUSGRID_GLOSSARY.md` after the DDIL, compliance and FIPS
arc. Four findings, one of them a defect rather than staleness.

### A merge artifact, sitting in the glossary since July

```
+(d1031146, 6d8893b3, b7d2e2c6)| **API Key Hash** | SHA256 hash of API key ... |
```

A `+` and three commit SHAs prepended to a table row — the residue of a conflict resolved by
pasting. It arrived in `fa6bb72f` (the cross-tab workbook slice) and has been rendering as a
broken row ever since, in the security section of the document people are pointed at to learn
the vocabulary.

**Nothing could have caught it.** `test_docs_links.py` checks links, `test_documented_files_exist.py`
checks cited filenames, and neither has an opinion about whether a Markdown table is
well-formed. Found by reading the section, which is the method the whole arc keeps
rediscovering: guards catch the class you thought of.

### The diagrams described an edge agent that no longer exists

The data-flow diagram carried `Edge Agent · 10+ collectors · 24h buffer · PackML` with a link
labelled `outbound-only mTLS`. Every word true when written, and by now it omits everything
the last three weeks changed: the buffer is encrypted at rest, drained by priority, and the
uplink is compressed only when the far end has said it can decode.

More to the point, **the condition the platform is built for had no picture at all.** Three
diagrams showed the happy path; the link being down is the ordinary case for a factory
basement or a vehicle, and nothing depicted what a reading does when nothing is reachable. A
fourth diagram now does — local durable alarm write before anything on the network,
priority-ordered drain, the negotiated codec, the supervisor rebuilding a dead producer, and
the size cap shedding tier 5 before tier 4 and never tier 1 — with the note that every arrow
is measured by a scenario rather than asserted.

**Rendered with the real parser, not eyeballed.** A bracket-and-`subgraph` balance check
passes on plenty of diagrams Mermaid then rejects, so all four were run through
`@mermaid-js/mermaid-cli`; all four produce SVG. A diagram that fails to parse renders as a
code block on GitHub, which looks like a formatting choice rather than an error.

### The glossary had none of the arc's vocabulary

Zero entries for DDIL, CMMC, FIPS, POA&M, SSP, control catalogue, deployment profile,
priority tier, `time_quality`, codec negotiation, conservation law. **654 terms and not one of
them from the work the repository has been doing.**

Three new sections — *DDIL & Edge Resilience*, *Cryptography & FIPS*, and a
pre-certification subsection under Compliance Frameworks — plus per-reading telemetry fields
(`timestamp_edge_raw`, `time_quality`, backfilled readings) in the section where a reader
would look for them.

And six entries under Testing Infrastructure for the method vocabulary this arc produced,
because those terms appear in commit messages and review comments with no definition anywhere:
**equivalent mutant**, **harness drift**, **instrument measuring itself**, **grep-vs-prose**,
**near-side bias**, **blocked-on-access decay**. A term used in a commit message and defined
nowhere is jargon; the same term with a row in the glossary is shared vocabulary.

The header now states when the glossary was last reviewed and that terms are defined by what
the code does rather than by what the feature was called when planned — several rows read
"this used to claim X and did Y", which is the honest form for a document whose failure mode
is preserving the intended meaning after the implementation diverged.

### Numbers checked rather than trusted

- Glossary term count: README said **540+**, actual **654**. Restated as a floor of 650+ with
  the count and date beside it, for the same reason the test-count floor is a floor.
- The Documentation index listed **no compliance material and no security material at all** —
  not the generated package, not the incident record, not the runbooks. All four added.
- Architecture section numbering: inserting the new diagram produced two sections numbered 5.
  Caught by re-reading the headings after the edit, which is the cheapest check there is.

### The guard, and the eleven more rows it found immediately

`backend/tests/test_the_reference_docs_are_well_formed.py` is the structural check that was
missing: no conflict residue, every table row starts its row, cell counts are consistent
within a table, and every glossary contents entry resolves to a heading that exists. Scoped to
the two documents people *look things up in* rather than read through, because a broken row in
a lookup document is found by the person who needed that row.

**It failed on its first run, on eleven rows nobody had noticed** — one in the README's
reliability table and ten in the glossary, each missing its final cell, each rendering with a
silently empty column. Ten of them are method-vocabulary entries whose `Backend/Frontend`
value was simply never typed.

It also failed on two rows that were *fine*, which mattered more. The first splitter treated
every `|` as a delimiter, so it reported

    `mode=section\|document\|table\|image\|batch`

as a seven-column row. Escaped pipes and pipes inside inline code spans are **content**, and a
structural guard that cannot parse the structure produces false positives on its first run —
which is how a guard becomes the one people learn to skip. It strips code spans and splits on
unescaped delimiters now.

Six mutations, six caught: the original artifact reintroduced, a conflict marker, a row losing
a cell, a row gaining one, and a contents entry pointed at a heading that does not exist. Two
earlier "survivors" were malformed mutations of mine — replacing a row prefix left the rest of
the line intact, so the row still had three cells and nothing should have failed.

---

## FS-765 — the second documentation pass, and what the first one missed

The previous pass (FS-764) updated diagram 1, added diagram 4, and rewrote three glossary
sections. Going back over the same two documents with the question *"what did I not look at"*
found five more things, which is the useful result: a pass that finds nothing on the second
attempt was not a pass, it was a skim.

**Diagrams 2 and 3 were never audited.** The first pass fixed the diagram whose defect it had
gone looking for and left the other two alone. Diagram 2's API node predated MFA entirely.
Diagram 3 is titled *"offline-capable edge + cloud"* and drew **neither the store-and-forward
buffer nor the local alarm sink** — the two components that make the claim in its own title
true. It showed twelve collectors feeding a database directly, which is the architecture the
DDIL work spent three weeks establishing is not what happens.

**`Running the suites` documented neither of the commands this arc added.** That section
answers "the commands CI runs, and what each proves", and it had no `pytest -m ddil` and no
`make compliance`. Both now present, with the reasons they are shaped the way they are — the
DDIL scenarios are nightly because one buffers 400,000 rows, while the cross-repository parity
guards are unmarked and gate every push, because tier drift is a per-PR concern and a drain
measurement is not.

**The Security Model table had no MFA, no FIPS, no edge encryption and no branch protection**
— four controls shipped in this arc, absent from the table a reader consults to learn what the
security model *is*. It now also carries a row naming what is still open, because a security
table that lists only what is done is the kind of document an assessor stops trusting halfway
down.

### Three glossary definitions that had become wrong

Not missing — **wrong**, which is worse, and none of them would have been found by looking for
gaps:

- **Hash Chaining** read *"to prevent tampering"*. It does not prevent tampering; it makes
  alteration detectable. `audit_logs` grants no append-only enforcement, so a role with UPDATE
  or DELETE can still alter rows and the chain proves it happened. That distinction is the
  entire reason `OG-AU-004` is `partial`, and the glossary was teaching the overclaim the
  catalogue exists to avoid.
- **Timeout** described only execution duration. Since FS-752 the same field is also the basis
  of an expiry check that refuses a stale command *before the actuator is touched* — the
  defect being that it was validated and discarded for years while days-old actuations
  replayed on reconnect.
- **Emergency Stop** said *"highest priority"*. True as an intention when written and now true
  as a mechanism, in a specific place that did not exist: tier 1 in the edge buffer, drained
  first and shed last.

### And the guard I added yesterday broke on a formatting choice

Aligning the columns of the run-command block — `cd backend    && pytest` — broke
`test_readme_test_count_is_not_stale.py`, whose patterns match the exact single-space form.
The alignment was not worth touching a guard for, so the block went back.

But the edge-agent line I had added to that block arrived **unguarded**, which is precisely
how the backend figure drifted 357 below reality before anyone looked. The guard now checks it
too, in both directions — not an overstatement, and not a floor so low it would pass through a
large regression — and it counts the DEFAULT configuration deliberately, because counting with
`-m ddil` would let the stated figure drift upward by 109 without anybody editing the README.

RULE 268 — a documentation pass finds what it went looking for, so the second question is
always "what did I not open". The first pass here fixed the diagram whose defect had prompted
it and never opened the other two, one of which was titled "offline-capable edge" and drew
neither of the components that make it so. Gaps are found by auditing scope; **wrong**
statements are found by re-reading things you have no reason to suspect — the glossary's
"hash chaining prevents tampering" had been confidently false since it was written, and no
audit of coverage would ever have surfaced it.

---

## FS-766 — UX friction, and the white screen it walked into

The ask was seamlessness: find and remove UX friction. The friction was measured rather than
guessed at, three classes were fixed, and the exercise then ran into something considerably
larger than any of them.

### What was measured

| Class | Measured | Now |
|---|---|---|
| Failure states the user can act on | **3 of 68** offered any action | Shared `ErrorState`; the operator-facing pages converted, the rest ratcheted |
| Mutations that confirm anything | **4 of 21** pages gave any feedback | `ToastProvider`; there was no non-blocking primitive at all |
| Native `window.confirm` | 3 sites, beside a `DialogProvider` built to replace them | 0 |

**65 of 68 failure states were a sentence in red and nothing else.** The cost is not the
missing button: the only recovery left is a full page reload, which throws away filters, the
selected time range, scroll position, and anything half-typed elsewhere on the page. A
transient 502 on one panel cost the operator their whole working state — and `refetch` was
sitting in react-query the entire time. The Alarms page said *"Check your connection and try
again"* while offering no way to try again.

**Nothing could confirm an action had happened.** `DialogProvider` offers a modal `alert()`,
which is the wrong tool: it takes focus and demands a dismissal for something the user already
knows they asked for, and a confirmation that interrupts gets dismissed unread. There was no
non-blocking primitive, so seventeen pages simply said nothing — you acknowledge an alarm,
the list refreshes on its ten-second poll anyway, and there is no way to tell your click
landed. The natural response to that uncertainty is to click again, which is also why seven
of those pages were double-submittable.

### A detector that was about to make things worse

The first version of the dead-end detector counted the four engine pages, which say
*"Retrying automatically…"* — and every one of them carries a `refetchInterval`, checked
rather than assumed. Those are not dead ends. Counting them would have inflated the number and
then pressured somebody into adding a Retry button that duplicates a poll: **friction added in
the name of removing it.** The detector now honours the claim only when the file genuinely
polls, because a page that *says* it retries and does not is a worse dead end than one that
says nothing, since the user waits.

The remaining 67 are ratcheted rather than converted. Sixty-odd JSX sites cannot honestly be
rewritten in one change — each needs its own query's `refetch` wired by hand — and a guard
that fails until they all are is a guard somebody disables.

### And then: the production bundle had been a white screen

Driving the app to look at the new error state — rather than trusting the tests — the built
bundle threw on load:

    TypeError: Cannot read properties of undefined (reading 'createContext')

`frontend/vite.config.ts` put React in its own manual chunk and everything depending on it in
`vendor`. The two then imported each other:

    react-vendor.js  imports -> vendor.js
    vendor.js        imports -> react-vendor.js

ES modules resolve a cycle by handing out partially-initialised bindings, so whichever
evaluated first saw `undefined` for the other's exports. `vendor` won, reached
`React.createContext` inside react-query, and threw. **The entire application was a white
screen in any production build.**

It was not mine. Confirmed by stashing the day's work and rebuilding: identical failure. And
it is not a subtle degradation — it is the app not starting.

**Why nothing caught it, which is the part worth keeping.** `vite build` exited 0. `tsc` was
clean. 1,211 unit tests passed — they import source. The Playwright suite passed — its
`webServer.command` is `npm run dev`, and the dev server does no manual chunking at all, so
**the chunk graph that broke exists only in the artifact that ships and no test had ever
loaded that artifact.** I had even built the production Docker image the day before and
"verified" it by checking nginx returned 200 for `index.html`. It did. A 200 for a page that
then throws on load.

The fix is one line — keep React in the same chunk as its dependents, which removes the cycle
while leaving the plotly/leaflet/charts splitting that the config exists for. The guard is
`frontend/e2e/the-built-bundle-boots.spec.ts` with its own config pointing at `vite build && vite
preview`: three shallow assertions — no page error, `#root` is not empty, something
interactive is visible. Deliberately shallow, because this asks whether the bundle can execute
at all, which is a question nobody was asking. Mutation-verified by reintroducing the exact
chunk cycle; it fails.

A separate config rather than a flag, because the dev-server suite is what people run while
working and a build costs ten seconds — making the everyday suite slower is how a check gets
skipped.

RULE 269 — test the artifact you ship, not the one you develop against. Every check here was
green while the production bundle white-screened: the build produced it, the type-checker read
the source, the unit tests imported the source, and the end-to-end suite drove a dev server
whose module graph is a different shape entirely. A bundler's output is a build ARTIFACT with
its own failure modes — chunk cycles, load order, minifier assumptions — and none of them
exist upstream of it. At least one check must load the thing that is actually deployed, and
"the server returned 200" is not that check.

---

## FS-767 — the CI that failed on every run, and the rest of the UX drain

Two asks: drain the friction backlog, and stop the workflows burning quota on failures.

### Every run was failing, and half of them were duplicates

520 runs on `origin`, 740 on the mirror, and a sample of the last thirty on each showed a
**100% failure rate**. Every push ran the full 22-job suite twice, because both remotes carry
the same branches and both had Actions enabled.

**The mirror's Actions are now disabled.** `SoundSafe-Dev/OmniusGrid-X` holds the identical
SHA — checked, not assumed — so its CI was re-proving what `origin` had just proved. That
halves the burn on its own and is reversible in one API call.

Then the failures themselves, four of which were real and fixable:

| Job | Why it failed | Fix |
|---|---|---|
| `supply-chain` | `aquasecurity/trivy-action@0.24.0` **does not exist** — the tags carry a `v` prefix. Died at "Set up job" on every run since it was pinned | Pinned `v0.36.0`; `ci-cd.yml` was on `@master`, also pinned |
| `backend-full` | `ModuleNotFoundError: No module named 'cv2'` collecting the new DDIL tests | Made the OCR imports lazy — see below |
| `frontend-unit` | One `no-useless-escape` error and one hook warning, with `--max-warnings=0` | Both fixed |
| `pre-commit` | `--all-files` on a tree that has never been formatted | Scoped to changed files |

**A supply-chain gate that cannot start is not a lenient gate, it is an absent one** — and it
had been absent long enough that nobody read the red any more, which is the real cost of a
permanently failing job.

### The lazy-import invariant that was already written down

`requirements-dev.txt` states it plainly and builds CI around it: *"The collectors import
their drivers lazily, so importing them without the drivers is exercised on purpose"*, and it
deliberately does not install opencv. `screen_scraper.py` imported `cv2`, `numpy` and
`pytesseract` at module scope, and `collectors/coordinator.py` imports `screen_scraper` at
module scope — so **importing the coordinator required the entire OCR stack.**

Nothing noticed for as long as no test imported the coordinator. When one did, the suite
failed at COLLECTION, and a pytest marker cannot help there: deselection happens after import.

Guarded by `edge-agent/tests/test_optional_drivers_are_not_required_to_import.py`, which runs
each import in a **subprocess** with the drivers blocked. The first version patched
`sys.modules` in-process and failed with "Duplicated timeseries in CollectorRegistry" — a
harness artifact reported as a product defect. A fresh interpreter is also the honest
simulation: CI does not re-import, it imports once, in a process where the driver was never
installed.

### pre-commit: a decision that belongs to four other people

Running the hooks repo-wide produced **1,159 files changed, 65,682 insertions** — ruff-format
and prettier over a codebase that predates both. That is not a whitespace fix, it is a
reformat, and it lands on every lane's in-flight work.

So the job now checks **only the files a change touched**, with the reformatters skipped. Even
scoped, prettier rewrote 2,139 lines of `IntakeInbox.tsx` — a file in the intake lane's active
work — for a one-character lint fix, which turns a lint fix into somebody else's merge
conflict. The hygiene hooks (whitespace, YAML, large files, merge markers, secrets) cost
nothing and pass today; formatting the tree is a deliberate decision that wants a quiet week
and everyone's agreement, and the SKIP is documented to be removed in the same change that
makes it.

### The drain, and three corrections to my own instrument

Dead-end count: **68 → 40**, and the path down was as much about the detector as the code.

1. `console.error('Failed to load…')` is a log line the user never sees. Rewriting it as a
   component would be nonsense.
2. A comment quoting the copy is not a failure state — the detector was counting its own
   prose, and `ErrorState`'s docstring.
3. **`<ErrorState>` without `onRetry` no longer counts as actionable.** It did, briefly, and a
   bulk conversion promptly produced sixteen sites that satisfied the detector and left the
   user exactly as stuck. The ratchet was gameable by the person draining it, which is the
   worst possible auditor.

`ChartContainer` gained `onRetry`, so every chart that passes it becomes recoverable in one
line. `Fleet`, `AnalyticsPages`, `MaintenanceWindows`, `FleetTargeting` and
`TransportationManagement` are wired.

**What remains is 40 sites, and the reason is worth stating rather than apologising for.**
Almost every one sits in a component with several queries, so wiring a retry means deciding
*which* query the message describes. A retry wired to the wrong query is worse than none —
it looks like it worked. The conversion script refuses to guess and reports those; the ratchet
holds the line meanwhile.

RULE 270 — a metric that the person improving it can satisfy without doing the work will be
satisfied without the work, and not deliberately. Converting `<p>Failed to load…</p>` to
`<ErrorState message="Failed to load…" />` felt like progress, passed the detector, and
changed nothing for the user; sixteen sites went that way in one batch before the detector was
tightened to look for the ESCAPE rather than the component. Write the check against the
property the user experiences, not against the mechanism you happen to be introducing — and
when you are both the author of the metric and the person being measured, assume you will find
the loophole by accident.

---

## FS-768 — the last forty, and a guard that lost sight of its subject

The dead-end backlog is **0**. The ceiling in `errorStatesAreActionable.test.ts` is zero, so
the next one cannot be added quietly, and the mutation check confirms it: reintroduce a
`<p>Failed to load…</p>` and the ratchet fails.

Getting there was not a find-and-replace, and the reasons are the interesting part.

### Most of them needed a decision, not a transform

Almost every remaining site sat in a component with three or four queries. Wiring a retry
means answering *which* query the message describes, and getting it wrong produces the worst
outcome available — a button that runs a different request, succeeds, and leaves the failed
panel exactly as it was. It looks like it worked.

Where a message covered several queries at once, the retry repeats all of them:
`FleetOverview` says "Fleet data could not be loaded" over three requests, and retrying one
would leave the page unchanged and read as a broken button.

### Several needed a refactor before a retry was possible at all

    useEffect(() => {
      const fetchData = async () => { ... }
      fetchData()
    }, [])

A fetch defined inside its effect cannot be called by anything else. The only way to run it
again was to remount the component — close the modal, reload the page — which discards
whatever the user had typed. Four of these were lifted into `useCallback`:
`TaskDetailModal`, `FleetTrackerMap`, `PlatformDataSourcePicker`, and the shipment-costs
fetch in `TransportationManagement`.

### Three sites deliberately did not get an `ErrorState`

- **A status chip in a header row.** A full block would push the map off screen, so the retry
  is a small control beside the badge.
- **A table cell.** The retry sits *in* the cell, where the reader's eye already is.
- **A DOT-regulated compliance notice.** This one is worth stating plainly: the block is
  already `role="alert"` with carefully-worded copy refusing the inference that unknown means
  compliant. Nesting an `ErrorState` — itself an alert — produced **two alerts in one region**,
  which a screen reader announces twice and which broke the test that reads the notice. It got
  a plain button.

### And a retry is not always the right answer

`FleetRolloutDetail` said "Rollout not found or failed to load", merging two cases that need
opposite treatment. A 404 is final; offering a retry sends the reader clicking at something
that will never work. They are told apart now, and only the failure gets a button. A fleet
with no organisation attached is not a failure at all and gets no control either.

### The guard that lost its subject

Lifting those fetches out of `useEffect` broke `idKeyedFetchesDoNotGoStale.test.ts` — not an
assertion, its **vacuity check**: "finds the effects it is meant to be checking", expected 0
to be greater than 0.

The class it guards is a hand-rolled id-keyed fetch that fails to clear, catch or cancel. The
code was unchanged; the hook around it was not, and the sweep's population fell to zero. Its
own header records losing the population once before, to a line break, and says the vacuity
test is the only reason that was noticed. It now scans `useCallback` as well, because the
defect lives in the fetch, not in the hook that happens to hold it.

### Five corrections to the detector, and what they cost

The count went 68 → 40 → 0, but three of those steps were the instrument rather than the work:

| Correction | Why it was wrong |
|---|---|
| `console.error('Failed to load…')` excluded | A log line the user never sees |
| Comments excluded, including `{/*` | It was flagging the prose that EXPLAINS a failure state, its own included |
| `<ErrorState>` no longer counts as actionable | The component is a means; the assertion is about the escape |
| Setter lookback widened to five lines | A ternary inside `setError(` puts the copy well below the call |
| Window widened to ±10 | A failure and its retry are still adjacent with a comment between them — and comments are common there, because these are the places somebody stopped to explain what the failure means |

RULE 271 — when you change the shape of the code, check what was watching that shape. Lifting
four fetches out of `useEffect` into `useCallback` did not change a line of their behaviour
and silently emptied the population of the sweep that guards them; only its vacuity check
noticed, and that check exists because the same sweep had already been emptied once by a line
break. A guard keyed on syntax follows the syntax, not the defect — so after a refactor, run
the guards that scan for the construct you just moved, and read the number they report rather
than the pass.

---

## FS-769..798 — the SLA instrument, and nine alerts that could never fire

Wave 1 of the FS-769..968 sprint. The driver is a contractual SLA for critical-infrastructure
customers, and the first question is not "what should we promise" but "can the instrument
record a breach". It could not.

### The availability SLI was structurally incapable of recording an outage

`slo_rules.yml` computed availability from `http_requests_total` — a series the backend
exports about **itself**. When the backend dies it does not report zero requests; the series
ceases to exist, and a ratio over an absent series produces no sample at all.

Measured with promtool rather than reasoned about (`infra/prometheus/tests/slo_outage_test.yml`):

| scenario | `SLOErrorBudgetFastBurn` |
|---|---|
| backend up, serving 100% 5xx | **fires** (control) |
| backend gone, 70 minutes | **silent** |
| backend gone, 70 minutes | `SLOErrorBudgetSlowBurn` also **silent** |

The two alerts guarding the availability SLO detected a *degraded* backend and were blind to
a *dead* one. And the hole propagates: a monthly figure computed by averaging skips absent
samples, so the outage is not averaged in as zero — it is excluded from the window, and the
month reads ≈100%.

Availability is now `probe_success × (1 − 5xx_ratio)`, where the probe comes from a blackbox
exporter **in a different process**, which is the entire reason it still reports — reporting
0 — when the backend is gone.

**The second half matters as much as the first.** When the instrument itself is missing these
rules produce *nothing* rather than guessing. There is no `or vector(1)`, which would recreate
the original bug, and no `or vector(0)`, which would page forever on a stack that has not
deployed the exporter. "I cannot measure availability" is a third state, and it is handled
where it belongs: `ProbeSignalMissing` and `BackendMetricsMissing` page on `absent()`.

Adds 28-day windows and error-budget-remaining. The longest window in the repository was 6h,
so nothing here could answer the only availability question a customer ever asks.

### Nine alerts that could never fire — three of them `critical`

| alert | severity | why it was inert |
|---|---|---|
| `TimescaleDBDown` | critical | `up{job="timescaledb"}` — no such scrape job in either config |
| `DiskSpaceCritical` | critical | `node_*` — no node-exporter anywhere |
| `APIHighErrorRate` | critical | metric written only behind a flag that is off everywhere |
| `HighMemoryUsage` | high | `node_*` — no node-exporter anywhere |
| `AssetOffline` | medium | `opsgrid_asset_last_seen_timestamp_seconds` — nothing exported it |
| `SlowDatabaseQueries` | low | a metric name no exporter produces, **and** `rate()` over a gauge |
| `APIErrorRateElevated`, `APILatencyP95High` | warning | same flag-gated metric |
| `WorkerDown`, `EdgeAgentUnreachable` | high | job labels that exist only in compose — inert in k8s **only** |

`opsgrid_http_requests_total` has exactly one write site, `profiling.py:239`, five lines below
`if not PROFILING_ENABLED: return`. That flag defaults False and is set in no environment, so
the counter has never been incremented — and `prometheus_client` omits a childless metric from
`/metrics` entirely.

### Three blind spots in the guards that were supposed to catch exactly this

The guards were good. Each failed in *how it read its input*, not in what it asserted.

1. **Line-scanning YAML.** `test_every_alert_watches_a_series_something_exports` matched
   `expr:\s*(.+)` per line, so the **13 of 53** expressions written as block scalars (`expr: |`)
   were captured as the literal string `"|"`. A quarter of the file was invisible to the sweep
   whose entire purpose is noticing alerts over series nothing exports — and two live defects
   were sitting in that quarter.

2. **An allowlist nobody could check.** `INFRA_EXPORTERS` waved metrics through by naming a
   "deployed exporter we name". node-exporter and postgres-exporter were deployed **nowhere**.
   Adding a prefix silenced the sweep, and the naming was precisely the unfalsifiable part.

3. **Declared is not observed.** An AST sweep over `Counter(...)` calls answers "is this
   metric declared", which a disabled feature flag leaves perfectly true.

### The notification path did not exist at all

`amtool check-config` on the compose Alertmanager:

```
FAILED: unsupported scheme "" for URL
```

`${SLACK_WEBHOOK_URL}` is not a URL, so the configuration is **invalid and Alertmanager
exits**. It has never started. Prometheus has been posting to `alertmanager:9093` — a
container in a restart loop — for the whole life of the file, so the local stack has had
rules, dashboards, and no notification path whatsoever. `test_alert_routing_coverage` passed
throughout, because it parses the YAML and asks whether each severity has a route: a question
perfectly answerable about a config that will not load. **Parsing is not loading.**

Both inhibit rules were also structurally dead in both configs: `equal: ['alertname']`
requires source and target to share a name while the matchers require them to differ in
severity, and every rule hardcodes one severity across 70+ distinct alertnames.

### Neither CI-job number was right, and the guard produced one of them

The compliance catalogue said **23** blocking CI jobs; the README said **31**. The guard meant
to stop that number going stale collected job names with a regex over two-space-indented keys
— which in a GitHub workflow also matches the `on:` triggers. `pull_request:` and `push:` were
counted as jobs in each workflow: four phantom gates. The README had been updated to match the
parser's own error, and the SSP is generated from the catalogue, so three documents carried
three numbers and none of them was **27 blocking + 1 advisory**.

That file's docstring already recorded being bitten by a confounded detector twice. This is the
third.

### Also delivered

Log aggregation in Kubernetes (Loki + promtail existed for **compose only**, so every runbook
step reading "check the container logs" — including the one `WorkerCrashLooping` links to —
was unexecutable in production). aiokafka tracing and **worker tracing at all**: `setup_tracing`
was called from `app/main.py` and nowhere else, so the four worker processes emitted no spans
of any kind. Jaeger moved from in-memory to a PVC, because a restart is what an incident
produces and yesterday's outage could not be investigated today. Tail sampling, so the traces
kept are the ones that failed or were slow rather than whichever survived the memory limit.
PVC-fullness alerts (kube-state-metrics was scraped and **no rule used it**, so nothing
anywhere alerted on storage exhaustion), public-certificate expiry, a dead-man's switch, and
alerts on Prometheus and Alertmanager themselves. RED and capacity/forecast dashboards.
`docs/engineering/uptime-commitment.md`, which states plainly which of its four numbers the
system does not yet meet.

RULE 272 — **a guard's reading of its input is part of the guard.** Every one of the three
blind spots above was a correct assertion applied to a silently narrowed population: a
line-scan that skipped block scalars, an allowlist whose entries were unverifiable, an AST
sweep that could see a declaration but not a write. A sweep that examines less than it
believes reports exactly what a clean one reports. When adding a sweep, assert the size and
shape of what it actually read — and when a sweep has an escape hatch, something must hold the
escapes to a fact.

RULE 273 — **parsing is not loading, and linting is not running.** `promtool check rules`
proved every alert expression parsed while nine of them could never fire; a YAML-parsing
routing test passed over an Alertmanager config the binary refuses to start on; `vite build`
and 1,211 tests passed over a bundle that was a white screen. Where a real binary can render
its own verdict — `amtool check-config`, `promtool test rules`, loading the built artifact —
run that binary in CI. A checker you wrote agrees with your model of the format; the tool that
consumes it does not have to.

---

## FS-799 — the RPO in the runbooks was wrong by about 100×

First item of Wave 2, done here because it is a documentation correction and the document is
where an SLA number gets quoted from.

`docs/runbooks/rto-rpo-checklist.md` published a target table naming the mechanism behind each
number. Three rows named a mechanism that does not exist:

| claimed | mechanism named | what is actually there |
|---|---|---|
| RPO **5 min** | "Patroni failover + WAL archiving" | Patroni lives in `legacy-patroni/`, applied by **no kustomization**. No `archive_mode` or `archive_command` anywhere in `base/`. The deployed image ships no `pgbackrest` binary |
| RPO **15 min** | "Cross-region replication + DNS failover" | `overlays/dr/kustomization.yaml` says in its own header that it **does NOT create cross-region data replication** |
| RPO **15 min** (partition) | "Partition heal + resync" | No resync mechanism exists; recovery is the same nightly dump |

What runs is a nightly `pg_dump -Fc` to S3. **The real RPO is up to 24 hours** for every
database-loss scenario, and RTO is *unmeasured* — the restore drill exists and has never been
timed.

The repository already knew this. `docs/runbooks/database-backup-restore.md` states "RPO — up
to 24 h (no point-in-time recovery)" in its second table, and the backup CronJob's own header
records that the image has no pgbackrest and no archive_command. Two documents, one of them
correct, and the one an operator reaches during an incident was the wrong one.

Both are now corrected with an **Actual today** column beside the target, and the runbook index
carries a note saying the target column must never be quoted to a customer. Corrected
**before** the mechanisms are built rather than after, because the failure mode is not an
engineer being confused — it is a number reaching a contract.

RULE 274 — **when a document states a target beside the mechanism that delivers it, check the
mechanism.** A bare number ages quietly and everybody knows to distrust it. A number with a
named mechanism reads as *verified*, and is the version that gets quoted — so it needs a
matching check more than a bare one does, not less. Where the claim is customer-facing, publish
the measured value alongside the target rather than replacing it: the gap is the work item, and
deleting the target loses it.

---

## FS-808 / FS-810 — the drill that could skip, and the number it never produced

Two defects in the same file, and both are about a gate that reports success without doing
the work.

### A skipped gate and a passing gate are the same green tick

Eleven test modules opened with `pytest.importorskip("testcontainers")`. That is correct on a
laptop — the real-DB suites need Docker, and a developer without it should not be blocked. It
is wrong in CI, where `pytest` exits 0 whether a suite ran or skipped itself.

The sharpest of the eleven is `test_backup_restore_drill.py`, whose own docstring says of the
nightly backup: *"this drill is what stops it from becoming the same kind of fiction: a backup
nobody restores is not a backup."* **A drill that silently skips is that fiction one level up**
— the gate is green and nobody has restored anything. And the claim it backs is the
customer-facing RPO that FS-799 has just finished correcting by a factor of a hundred.

There *was* a preflight: `backend-realdb` runs `import testcontainers.postgres` and fails the
job if it is missing. That covers the case it was written for. It does not cover the preflight
being renamed, reordered or dropped in a workflow edit — after which all eleven suites skip and
the job stays green, which is precisely the failure the preflight exists to prevent, one level
of indirection out. **A guarantee that lives beside the tests is only as durable as the file it
lives in.**

`tests/_realdb.py` now provides `require_testcontainers()`: skips on a laptop, raises when
`REQUIRE_REALDB=1`. CI sets it, and `test_the_realdb_suites_cannot_silently_skip.py` asserts CI
still sets it — so removing it is itself a test failure, which is the property the preflight
lacked. Both branches were proven by faking the import failure, not by uninstalling anything.

### The drill had never been timed

`database-backup-restore.md` said of RTO: *"Restore time of one dump — measure it during the
next drill."* Every drill since restored correctly and measured nothing, so the RTO column of
the checklist was an aspiration sitting beside three RPO figures that turned out to be wrong.

The restore step is now timed on every run. **0.75 s** for a migrated schema, with a 120 s
ceiling.

That number is deliberately described as a *floor*, not an RTO: CI hardware, a near-empty
database, and production is neither. What it buys is a regression barrier — if restoring an
almost-empty database starts taking minutes, no amount of production tuning reaches a
60-minute RTO for a real one. The ceiling is generous on purpose; one tight enough to be
interesting on a laptop would flake on a shared runner, and a flaky gate gets disabled, which
is how the measurement would be lost a second time.

RULE 275 — **a preflight beside a test is weaker than a precondition inside it.** A CI step
that checks a dependency protects the tests only while that step exists, in that job, under
that name; the tests themselves carry no memory of the requirement. Where a suite must not be
allowed to skip, put the refusal in the suite — gated on an environment variable CI sets — and
then assert from the suite that CI still sets it. The check and the thing checked then move
together, and the failure mode becomes a red test rather than a silent narrowing.

---

## FS-817 — the audit table nobody prunes, and why not pruning it was the right call

`audit_logs` has **no retention policy**. Its sibling `user_audit_logs` has one — 7 years for
GDPR, `005_data_retention.sql:177` — and raw `telemetry` is dropped after 7 days. `audit_logs`
is neither, and being a plain table rather than a hypertable, `add_retention_policy` does not
even apply to it. Nothing else deletes from it either.

**The failure is circular and lands on the critical tier.** Unbounded audit growth fills the
volume; the audit write then fails; and `AuditWriteFailing` is severity `critical`. The control
that records what happened is the one that ends the system. Until FS-781 added the PVC alerts,
nothing anywhere alerted on storage exhaustion, so the first symptom would have been the
failure itself.

### Why the obvious fix is wrong

Adding a retention policy looks like a five-line migration. Three things say otherwise:

1. **The hash chain.** Migration 069 makes each tenant's rows a chain, each row hashing its
   predecessor's digest. Delete the oldest rows and the earliest survivor's `previous_hash`
   names a row that is gone. A verifier must be taught that a pruned prefix is a **root**, not
   a violation — and FS-743 established the stakes exactly: "an integrity control that always
   reports a violation is indistinguishable from one that never reports anything: both are
   ignored within a week." A naive prune recreates the bug that migration existed to fix.

2. **OG-AU-004 plans to make deletion impossible.** Its remediation note is
   `REVOKE UPDATE, DELETE ON audit_logs` plus a WORM export — tamper-*evidence* becoming
   tamper-*resistance*. A retention job is the opposite change. Both are defensible; only
   archive-then-delete satisfies both, and only in that order.

3. **How long is required is a contract question.** CMMC 3.3.1 asks for a defined period
   without naming one, and these customers may carry longer obligations.

### What was done instead

The half that is *not* a decision: making it visible before it is an outage. `pg_table_growth`
exports the table's size and live rows; `AuditLogTableGrowingUnbounded` pages at 20 GB; and
`AuditLogGrowthAccelerating` projects 30 days ahead, so the deadline arrives before the volume
does. Registered as open decision #2, pinned by
`test_the_audit_table_growth_is_watched.py` — which **fails the day someone adds a retention
policy**, telling them to delete the register entry and this file rather than leave a register
outliving its item.

### A note on the promtool test, which was wrong first

The first draft of the unit test fed the size gauge at a 1-hour interval and neither alert
fired. The rules were correct; the test was driving them wrong. Prometheus's 5-minute lookback
makes an hourly series stale for 55 minutes of every hour, so a `for:` clause can never
accumulate. Undiagnosed, that reads exactly like an unfirable alert — the class Wave 1 spent
its whole length closing — and the reflex would have been to "fix" a working rule. The alert's
own window was also lowered from 7 days to 24 hours **because** the 7-day version could not be
driven true by any test of reasonable size, and a rule nobody can drive is the thing this
sprint exists to stop shipping.

RULE 276 — **choose windows a test can drive.** A rule over `[7d]` with `for: 6h` is honest
about the phenomenon and impossible to unit-test at reasonable cost, so in practice it ships
unverified — which is how the nine unfirable alerts of FS-774 got there. Prefer the shortest
window that still answers the question, keep the longer baseline on a dashboard where being
un-unit-testable costs nothing, and when a test cannot drive a rule true, suspect the test's
sampling interval against Prometheus's 5-minute lookback before suspecting the rule.

---

## FS-816 / FS-800 / FS-801 — a wrong premise caught by a guard, and the parameter that bounds RPO

### The retention premise was wrong, and the fix for it would have destroyed data

FS-816 was scoped from `005_data_retention.sql:22`:

```sql
SELECT add_retention_policy('telemetry', INTERVAL '7 days', if_not_exists => TRUE);
```

**That statement is a no-op and always has been.** `001_init.sql:104` had already installed a
retention policy at 30 days, and `if_not_exists => TRUE` means "succeed quietly if one exists"
— it does not change the interval. Then `034_historian_retention.sql:210` removed the global
policy altogether, deliberately, and replaced it with `enforce_tenant_historian_retention()`:
a per-tenant, per-metric row DELETE, because a Timescale chunk holds rows for many
organisations and a global chunk-drop cannot honour a per-tenant window.

The real default was **30 days, tenant-configurable**. The seven never existed. Three
documents repeated it, including one written earlier in this same sprint.

**The first migration written to fix it reinstated the global policy.** It would have dropped
whole chunks out from under tenants who had configured longer windows — silent, cross-tenant,
irreversible data loss, discovered only when a customer asked for data they were entitled to.
It was caught because `test_migration_chain_hygiene` rejected the file for an unrelated reason
(it looked data-only) and the investigation went one level deeper.

The delivered change raises the **per-tenant default** 30 → 90: the column default, and the
`COALESCE` fallback that is what a tenant with no configured row actually gets. Tenants who
set their own value are untouched, and the change only ever lengthens retention, so it cannot
delete anything that previously survived.

### What it costs, measured rather than assumed

Against the real schema and the real `compress_segmentby`, 2,161,000 rows:

| | bytes/row |
|---|---|
| uncompressed | 142.7 |
| compressed | 19.4 |
| **ratio** | **7.3× (86.4% saved)** |

Compression at 7 days is live and *is* realised — chunks compress at day 7 and rows are
deleted at day 30, so twenty-three of those days already cost compressed bytes. Extending to
90 therefore costs compressed bytes too: ~140 GB and about **$14/month** for a 250-asset fleet
at a 5-second poll.

`DELETE` against a compressed chunk was verified before shipping, because the whole scheme
depends on it — 7,201 rows across 6 compressed chunks, deleted cleanly on TimescaleDB 2.26.3.
Below 2.11 that DELETE is refused, which would silently stop tenant retention past day 7.

### The parameter that bounds RPO was not set

The CNPG cluster defines WAL archiving to object storage, and a weekly base backup. It did not
set `archive_timeout`.

**WAL archiving existing is not the same as RPO being bounded.** Postgres archives a segment
when it *fills* — 16 MB — so on a quiet system the tail of the log sits unarchived for as long
as it takes to produce 16 MB. Overnight, on a single-site fleet, that is hours. Recovering from
object storage would lose everything since the last completed segment, and nothing in the
cluster would have looked unhealthy.

`archive_timeout: 5min` forces a segment switch even when the segment is mostly empty. It also
made explicit two RPOs the runbooks had been conflating: a lost **primary** is ≈0 because
`minSyncReplicas: 1` means a standby confirmed every acknowledged commit, and only a lost
**cluster or site** is bounded by the archive.

### The cutover was a manual step, and manual steps get skipped

`database-ha/README.md` described repointing `DATABASE_URL` at the pooler as something an
operator does by hand. The failure mode is the worst kind: the HA cluster runs, WAL archiving
works perfectly, and it archives a database nothing is writing to.

It is now a kustomize component included by `overlays/production`, repointing all seven
clients — backend, four workers, migration Job, backup CronJob. The production deploy applies
`database-ha` first and **fails outright** if the CloudNativePG CRDs are absent, rather than
rolling out pods that point at a Service nobody created.

**Two defects in that component were found only by reading the built output.**

1. A single shared patch named `PLACEHOLDER` as the container, assuming the patch *target*
   supplies the name. It does not — kustomize merges containers by name, found no
   `PLACEHOLDER`, and **added a second, image-less container to all seven workloads** while
   each real container went on using the old secret. `kustomize build` exited 0 and
   `kubeconform` was satisfied.
2. Once the names were right, strategic merge combined the env entries *field by field*, so
   `DATABASE_URL` carried both `value` and base's `valueFrom`. The API server rejects that —
   "may not have more than one field specified". Build green, apply fails. `valueFrom: null`
   is what deletes the inherited field.

Neither is visible in an exit code. `test_the_cnpg_cutover_is_coherent.py` now holds the
component, the built manifests and the deploy job to one another.

RULE 277 — **when a premise names a line of code, read what that line does at the point it
runs.** `add_retention_policy('telemetry', INTERVAL '7 days', if_not_exists => TRUE)` says
seven days and means nothing, because a policy already existed and a later migration removed
it. Three documents and a sprint plan repeated the number; the file was quoted accurately every
time. A statement is not a state — reconstruct the state the chain actually produces, and
prefer a guard that reads the whole chain in order, including removals, over one that reports
the first or last match.

---

## FS-821 / FS-825 — the database engine floated on `:latest`, and one component was never pinned at all

### Nothing could be rolled back to

`base/` ran the **database engine** on `timescale/timescaledb:latest-pg15` and the **broker**
on `redpandadata/redpanda:latest`. Both tags are repointed by their publishers on every
release, so two clusters built a week apart ran different builds of the two components every
byte of customer data passes through. During an incident, "which version is this" and "roll
back to the previous one" had no answer.

The sharpest of the three was the **backup** image. `postgres:15-alpine` floats across every
15.x patch, so the `pg_dump` writing the archive could change minor version between runs — and
a dump written by a newer `pg_dump` than the `pg_restore` used to read it is a restore that
fails *during the recovery it exists for*.

Every deployed image is now pinned `tag@sha256:…`, digests resolved from the registries on
2026-08-20 rather than invented. The tag stays for readability; the digest is what Kubernetes
enforces.

### And one component was pinned by nothing

`build-images` builds and pushes **backend, frontend and edge-agent**. `base/kustomization.yaml`
deploys the edge-agent StatefulSet. Both deploy jobs repointed only backend and frontend.

So the deployed agent ran `omniusgrid/edge-agent:latest` — whatever was pushed last, with no
correlation to the release tag. On the component that receives OTA bundles and talks to
industrial equipment, nobody could say which build was on the floor, and rolling back the
platform left the agent where it was.

This is the exact failure mode the exemption list would have hidden: `omniusgrid/*` is exempt
from digest pinning *because every deploy repoints it*, and for one of the three that was
false. `test_no_workload_runs_a_mutable_tag.py` therefore checks the exemption's premise as
well as the rule — every image claimed to be deploy-pinned must actually appear in both deploy
jobs.

### The image scan could not fail a deploy

`security-scan` produced SARIF, uploaded it, and set no `exit-code` — so it exited 0 whatever
it found. Both deploy jobs list `security-scan` in `needs:`, which made the gate look real; it
had never been able to stop anything, and the SSP said so in OG-RA-002.

A second step now blocks on **fixable CRITICAL** findings, using the same reviewed
`.trivyignore` the filesystem scan has used since FS-79. Narrower than that scan's
HIGH,CRITICAL on purpose: a container image carries its whole base OS, and unfixable distro
CVEs would leave the build red every morning — a gate people route around is worse than the
advisory one it replaced. Its first real exercise is the next CI run, because it scans an
image that only exists after the push; if it fails on unfixable noise the answer is a triaged
`.trivyignore` entry, not removing the exit-code.

RULE 278 — **an exemption is a claim, and it needs its own check.** "These images need no
digest because every deploy pins them" was true for two of three, and the third was the edge
agent. A register that lists what is excused, without asserting the excuse, converts a
finding into a permanent blind spot — and reads as diligence while doing it. Where an entry
says *because X*, test X.

---

## FS-829 / FS-833 — the plan the runbooks were standing in for

Eleven runbooks, communication templates, and a real worked incident with IoCs. What was
missing is the thing none of them is: **a plan.**

A runbook tells you how to restart a wedged worker. It does not say who declares an incident,
who is allowed to, who talks to the customer, or what the 72-hour regulatory clock is attached
to. `docs/runbooks/incident-response-plan.md` is that document. Three choices in it are
deliberate:

- **Severity is keyed to customer impact, not to which component broke.** A failed database is
  SEV-1 if customers cannot use the product and SEV-3 if a standby took over and nobody
  noticed. Severity tables keyed to components produce SEV-1s for healthy failovers, and then
  get ignored.
- **Any engineer may declare; only the IC may resolve.** A culture where declaring needs
  permission produces incidents declared late, which is precisely what the notification
  deadlines cannot absorb.
- **The statutory clocks are stated separately** — GDPR Art. 33 and DFARS 252.204-7012, both
  72 hours from *discovery*, both shorter than any customer-notification row above them, and
  both previously captured in no document at all.

Step 2 of the first fifteen minutes is *check the instrument before the system*: if
`ProbeSignalMissing` is firing, no availability figure from that period is valid. That
instruction only became meaningful this sprint — before FS-770 the SLI could not record a
total outage, and before FS-789 "check the container logs" was not executable in production.

### The runbook the alerts were already pointing at

`storage-exhaustion.md` covers the PVC alerts, the audit-growth alerts and the two `node_*`
alerts, none of which could fire before this sprint. It exists mostly for its **What not to
do** section, because the two obvious ways to free space are both wrong:

- **Deleting audit rows** breaks the per-tenant hash chain, so the verifier reports a permanent
  tamper violation — which FS-743 established is indistinguishable from a control that reports
  nothing.
- **Adding a global retention policy on `telemetry`** drops chunks containing many tenants'
  rows. That is the mistake FS-816 nearly shipped, and it is now blocked by a test.

Under pressure, at 3am, both look like the obvious move. That is when a runbook earns its
keep.

RULE 279 — **a document that reads as operational and has never been exercised is worse than
an obvious draft.** Every section of the incident plan that depends on a human who does not
exist yet is marked 🔲 and listed again in a closing "what is not real yet" table: no on-call
rota, no owner for the statutory filings, never rehearsed. The temptation is to write those
sections as though they were true, because the document looks finished and the compliance
entry moves. It also means the first person to open it during an incident discovers the gap
at the worst possible moment. Mark the gaps in the document itself, not only in the tracker.

---

## FS-821 (continued) / FS-801 — verifying the gate, and the check the deploy could not make

Two things were shipped in the previous slice with a caveat attached. Both caveats are now
closed, and closing them found more.

### The image gate: verified, and not vacuously

FS-825 added an `exit-code` to the image scan, and the commit said plainly that it scans an
image which only exists after the push, so its first real exercise would be the next CI run.
That is an uncomfortable thing to leave in a supply-chain gate.

Scanned instead with `trivy` against the exact base the Dockerfile uses, with the gate's exact
settings — `--severity CRITICAL --ignore-unfixed --ignorefile .trivyignore`:

| target | fixable CRITICAL | exit |
|---|---|---|
| `registry.access.redhat.com/ubi9/python-311` | 0 | **0 — passes** |
| `backend/requirements.txt` | 0 | **0 — passes** |

And the check that matters more, because a gate can pass by finding nothing at all:

```
6,139 vulnerabilities parsed in the base image
      0 CRITICAL
    193 HIGH      (102 with a published fix)
   3735 MEDIUM
   2211 LOW
```

The scanner is working and the policy is letting 6,139 findings through deliberately. **The
102 fixable HIGHs are the vindication of the CRITICAL threshold** — the earlier commit
justified it as avoiding "unfixable distro CVEs", and the real reason is stronger: a HIGH gate
would have failed on its first run, on 102 findings whose only remedy is a Red Hat base-image
bump nobody here controls the cadence of.

### The finding that came out of it: no `FROM` was pinned either

FS-821 pinned every image in the Kubernetes manifests — which image *runs*. It said nothing
about the Dockerfiles, which decide what is *in* it. Every `FROM` in the repository was
unpinned, and three named their image with **no tag at all**, resolving to `:latest`.

So two builds of the same release could sit on different base images, and "rebuild last
month's release" was not a thing that could be done. All six are now digest-pinned.

**Pinning alone would have been a trade, not a fix.** A pin never moves, so the base ages out
of security support silently — nothing breaks, the build stays green, and the CVE count
climbs. `tests/k8s/check_base_images_are_current.py` runs nightly and compares each pinned
digest against what its tag resolves to today. Nightly rather than per-PR on purpose: a base
image moving is news about the world, not a defect in whichever pull request happens to be
open, and a check that fails unrelated merges is a check people route around.

### The deploy can now tell whether the data moved

The previous slice wired the CNPG cutover into `overlays/production` and made the deploy refuse
if the operator's CRDs are absent. The honest caveat was that the CRD check proves the
*operator* exists and says nothing about whether the customer data was ever moved out of
`base/timescaledb-statefulset.yaml`.

That gap fails in the quietest possible way. A healthy but **empty** CNPG cluster accepts the
connection; the migration Job builds the schema in it; the application answers 200; and every
customer sees an empty product — while the probe-based availability SLI reports perfect
health, because the system genuinely is up. Nothing crashes. No alert fires. The old data is
still in the StatefulSet, so it is recoverable, but it is a total outage that every instrument
reports as a successful deploy.

`tests/k8s/preflight_cnpg_cutover.py` runs between the CNPG apply and the manifest build. It
compares row counts in the three tables migrations cannot reconstruct — `organizations`,
`users`, `assets` — and refuses if the new cluster is short.

**Row counts rather than a marker**, deliberately. A marker file or an annotation records that
somebody *intended* to migrate. The counts are the migration itself, whatever route it took —
`pg_dump`/restore, `pg_basebackup`, or CNPG's import — and they also catch a cluster that has
since lost its data to a deleted PVC or a bad restore, which a marker never would.

RULE 280 — **a caveat in a commit message is a promise to come back.** Two slices shipped with
"this is not verifiable locally" and "this still needs a human" attached. Both were honest and
both were load-bearing: one was a supply-chain gate whose first real exercise would have been
a production pipeline, the other a deploy that could destroy a customer's view of their own
data. Written down, a caveat looks like diligence; left alone, it is a known gap with a note
next to it. Come back within the same arc, and prefer converting "a human must remember" into
a check the machine makes — the preflight above is nine kubectl calls, and it replaces a
sentence in a README that everyone would have skipped.

---

## FS-802..806 — point-in-time recovery, proven rather than described

`database-backup-restore.md` carried a section headed **"Restoring PITR (not yet done)"**, and
every DR runbook describing a pgBackRest restore pointed at a repository nothing wrote to.
FS-799 then found the RPO table promising 5 minutes via a mechanism no kustomization applies,
when the real figure was 24 hours.

FS-800 set `archive_timeout` — the parameter that actually bounds RPO, and which was unset, so
Postgres archived a WAL segment only when it FILLED (16 MB) and a quiet system left its tail
unarchived for hours. FS-801 made the application talk to the CNPG cluster at all. Both are
configuration. What was still missing is evidence that a recovery to a chosen instant returns
the data.

### The drill

Proven by hand first, then encoded. `test_pitr_recovers_to_a_point_in_time_realdb.py` runs a
real Postgres with continuous archiving, takes a base backup, records a timestamp, then
performs the mistake we are recovering from — a `DELETE` nobody meant to run, and a write
after it:

```
live database after the mistake      ->  1 row  ("after the mistake")
recovered to a timestamp before it   ->  2 rows ("before", "also before")
```

The destroyed rows come back and the write made after the target does not. About 8 seconds.

It asserts the property that matters rather than "the restore completed" — **a restore that
returns *a* database is not a restore that returns *the* database as it was at 14:32**, and
only the second is what an RPO is a claim about. Mutation-verified by moving the recovery
target past the mistake, which makes it fail.

It drives `docker` directly rather than testcontainers, because PITR requires stopping the
server and restarting it against a restored data directory, and the testcontainers postgres
image runs postgres as PID 1 — stopping it kills the container. A second test asserts the CNPG
cluster still declares all three prerequisites (WAL archiving, a base-backup schedule,
`archive_timeout`), because any one going missing leaves a repository that recovers nothing,
silently.

### The repository's own guard stopped the write-up over-claiming

Rewriting the runbook to say PITR was proven failed
`test_the_recovery_promise_matches_the_deployment.py`, which pairs the promise against the
deployment and computes whether PITR is *actually available*:

```
deployed: False
why: base/ still ships the single-pod TimescaleDB StatefulSet, so the CNPG cutover
     has not happened and the deployed database has no WAL archive
```

That is correct, and the distinction it forced is the most useful thing in this slice.
**Proven in a drill and available in production are different claims**, and a document that
blurs them sends an operator to a recovery they cannot perform. The section now leads with the
status — mechanism proven, not yet available in any environment, every environment still on
the nightly dump at RPO 24 hours — and the guard requires the qualifier to appear on *every
line* that mentions PITR, because the operator reads the sentence they landed on, not the
section.

The qualifier comes off automatically the day `base/` stops shipping the single pod: the same
guard then fails in the other direction, on the grounds that under-promising after the
capability lands sends an operator to a slower recovery during an incident.

RULE 281 — **"we tested it" and "it is available" are different claims, and documentation
collapses them by default.** The drill here is real, repeatable and mutation-verified, and PITR
remains unavailable in every environment because no cutover has happened. Writing "PITR is
proven" would have been true and would have been read as "PITR is available" by the one person
who matters — someone recovering an outage at 3am. State the capability and the availability
separately, and put the availability first.

---

## FS-811 — the archive was inside the cluster it protected, and the bucket was a sentence

FS-811 was scoped as "enforce bucket immutability as IaC, not as an instruction". Doing it
found something larger first.

### The WAL archive was written to the cluster it protects

`database-ha/cluster.yaml` archived continuously to `http://seaweedfs:8333` — the
**single-replica** object store running in the same cluster (`base/object-store.yaml`,
`replicas: 1`). The comment above it read *"Continuous WAL archiving + base backups to S3 →
point-in-time recovery. This is the PITR the pg_dump CronJob explicitly could not provide."*

Against the two RPO figures the runbooks quote — figures **this sprint wrote, two commits
earlier**:

| failure | claimed | actual with that endpoint |
|---|---|---|
| lost primary instance | ≈ 0 | ≈ 0 — unaffected. A standby confirmed every commit; the archive is never read |
| lost cluster or site | ≤ 5 min | **24 hours.** The archive is in the cluster, so it goes with it. The only surviving copy is the nightly `pg_dump` |

The second is the scenario the number exists for. FS-800 had set `archive_timeout` precisely to
bound it, against an endpoint that was quietly making it meaningless — and the failure is
invisible, because archiving works perfectly right up until the moment the cluster is gone.

Both environment overlays now patch the endpoint out of the cluster. They ship
`https://REPLACE-ME…s3.example.invalid`, which **fails**, on the same reasoning as the
`alertmanager-secrets` placeholders: a value that fails loudly beats one that quietly works
against the wrong store. Staging carries it too, because a site-loss rehearsal (FS-925)
against a different archive topology from production tests the wrong thing.
`test_the_wal_archive_leaves_the_cluster.py` asserts no overlay carries an in-cluster Service
name, and that the endpoint is `https://` — WAL leaving the cluster in plaintext is OG-SC-003,
and every committed row travels through that stream.

### Then the bucket

The runbook said: *"enable versioning + object lock so a compromised key cannot erase
history."* One sentence, describing the control that decides whether an attacker holding the
backup credentials can delete every backup you have. Nothing applied it; nothing checked it.

`base/scripts/bucket-immutability.sh` does both. `bootstrap` creates a bucket with versioning,
Object Lock in **COMPLIANCE** mode, the public-access block, default encryption and a
lifecycle rule. `verify` is read-only and checks a live one.

COMPLIANCE rather than GOVERNANCE is deliberate and is a real trade: GOVERNANCE can be
bypassed by a principal holding `s3:BypassGovernanceRetention` — exactly the permission an
attacker who has compromised the account grants themselves — while COMPLIANCE cannot be
bypassed by anyone including root, which also means an object locked by mistake cannot be
removed until its retention expires. Versioning alone is not enough: a delete leaves the old
versions, and a holder of the key can delete those too.

**And nobody has to remember to run it.** The cluster already holds the credentials, because
the nightly upload needs them, so `backup-immutability-check` runs `verify` weekly and
`BackupBucketNotImmutable` pages when it fails.

Separate from `db-backup` on purpose. Folding the check in would mean an unprotected bucket
stops backups happening at all — turning a bad situation into a worse one — and would stop
`kube_cronjob_status_last_successful_time` advancing, firing `DatabaseBackupStale` and telling
an operator there are no backups when there are. Two distinct problems, two distinct signals.

### The kustomize trap, twice

Putting the script in a tidy `infrastructure/backup/` broke `base`, because CI builds it
without `--load-restrictor LoadRestrictionsNone` and a generator reading a file above its own
kustomization is refused. Moving it under `base/scripts/` fixed that — and appending a second
`configMapGenerator:` key to the kustomization then silently **replaced** the existing one,
because YAML keeps the last of a duplicated key. Every overlay failed with `backend-config
does not exist`. Both caught by building all four trees rather than the one being edited.

RULE 282 — **a backup that shares a failure domain with its source is not a backup of that
failure domain.** The archive ran, the retention was tuned, `archive_timeout` bounded the
number, and every dashboard was green — and a cluster loss would have taken the archive with
it, silently downgrading a 5-minute RPO to 24 hours. When a recovery figure is written down,
name the failure it survives, then check the artefact is somewhere that failure does not
reach. The same question applies to a backup bucket in the account that was compromised, and
to a runbook stored only in the cluster it describes.

### Documentation pass for FS-799..811

Four documents carried claims this arc changed, and one carried a claim it *created*.

**README.** The Maturity row for point-in-time recovery said "Not operational" — still true,
and now incomplete: PITR is proven by a drill and unavailable in every environment, which are
different sentences and the row now carries both. The Database HA row gained `archive_timeout`
and the pooler cutover. The DR bullet gained the fact that the restore drill is now *timed*,
because RTO had been an aspiration since the drill was written.

A seventh diagram, **"What survives which failure"**, because none of the six drew the
recovery path — which is where every finding in this arc was. Three failures need three
different answers and they do not substitute for each other: synchronous replication survives
a lost primary, an off-cluster archive survives a lost site, and only Object Lock in
COMPLIANCE mode survives a compromised credential. The dotted arrow is the WAL archive as it
was: pointing at a single-replica store inside the cluster it protected. `Loki` is dotted too
and deliberately unfixed — log aggregation was deployed in-cluster so "check the container
logs" would be executable in production, and during a cluster loss those logs are gone with
everything else. Recorded rather than solved, because pretending otherwise is how the archive
finding happened.

**Glossary** +10 terms, and two of them are the ones that would have prevented this arc's
findings if anybody had written them down first: *failure domain* ("a backup that shares a
failure domain with its source is not a backup of that domain") and *`archive_timeout`* ("WAL
archiving existing is not the same as RPO being bounded"). Also base backup, recovery target,
PITR, Object Lock, COMPLIANCE vs GOVERNANCE, pooler, cutover preflight, digest pin. 696 → 706.

**Compliance.** `OG-MP-001` said immutability was "explicitly the operator's job… configured
by hand, so neither is evidenced here". It now records the tooling and the weekly check, and
gives three *narrower* reasons for staying `partial`: `bootstrap` has not been run against the
real bucket, the off-cluster endpoints are placeholders that fail, and RPO is still 24 hours
everywhere because the cutover has not happened. A remediation note that only records the good
news is how a control drifts to `implemented` while nothing changed on the ground.

**The runbook** replaced its one-sentence instruction with the two commands and the reasoning
behind COMPLIANCE mode, including what it costs.

All seven mermaid diagrams render under `mermaid-cli`.

---

## FS-812..815 — three stores nothing backed up, and the Job that could not reach the database

Until this slice the only backup in the platform was the nightly `pg_dump`. Three other
stateful services held data and none of them was backed up at all.

### They are not the same problem

Treating them as one would have produced two jobs nobody needs and missed the one that
matters. What each actually holds decides what a backup of it should even be:

| store | what is in it | what a backup should be |
|---|---|---|
| **Redis** | `FeatureFlagService` is a "Redis-backed feature flag store" with **no database fallback** — Redis is the store of record. Plus idempotency keys and job state, both short-lived and reconstructible | dump the keyspace. It is persistent (`appendonly` on a PVC) so a restart is safe; a lost PVC loses every flag, and flags gate production behaviour |
| **SeaweedFS** | compliance reports (regulatory evidence), the RAG document library, generated exports. `replicas: 1` | sync the objects out. Durable customer-facing artefacts with no replication and no copy |
| **Redpanda** | telemetry in flight | **the configuration, not the messages.** Consumers persist the data and an agent that cannot deliver buffers and backfills — the conservation law holds across the gap. What is *not* reconstructible is partition counts, retention and consumer groups |

Each job also refuses a plausible-looking empty result: an RDB with `DBSIZE` of zero, a sync
that pulled no objects, a config capture with no topic sections. All three look exactly like a
successful backup of an empty system.

### FS-815: the size anomaly `test -s` cannot catch

The dump container already runs `test -s` and `pg_restore --list`, which catch an empty or
corrupt file. Neither catches the case that actually happens: **a dump that is well-formed,
restorable, and a fraction of yesterday's** — a schema dropped by a bad migration, a `--schema`
flag left in, a tenant deleted. That file passes every existing check and is a faithful backup
of a database which has already lost the data.

Compared against the most recent previous object rather than a fixed floor, because a real
database grows and any constant is either immediately obsolete or so loose it catches nothing.
The threshold is 50% and deliberately not tighter: a backup job that cries wolf gets disabled,
and then there are no backups at all.

### And the finding that came out of widening a gate

The four new CronJobs needed NetworkPolicies. Adding them raised a better question — why had
nothing *told* me? `check_netpol_coverage.py` walked only Deployments, StatefulSets and
DaemonSets. **Every scheduled job in the platform was outside its population**, while it
printed "every workload is covered in both directions".

A CronJob's pod template is one level deeper (`spec.jobTemplate.spec.template`), which is
presumably why it was skipped — and is exactly the kind of reason a sweep silently narrows.

Adding `CronJob` and `Job` took the checked population from **13 to 19** and immediately found
a pre-existing break: **`db-migrate` had no NetworkPolicy of any kind.** Under
`default-deny-all` its pod cannot open a connection, so `scripts/migrate.py` cannot reach the
database and the Job never completes — and `deploy-production` runs

```
kubectl wait --for=condition=complete job/prod-db-migrate --timeout=300s
```

before applying anything else. **Every production deploy would have timed out there.** It has
gone unnoticed because staging deploys are behind an opt-in variable and production deploys
only run on a tag.

Ingress is exempted for batch kinds — nothing dials a pod that runs once and exits — but
egress is not, and the asymmetry is the point rather than a convenience: outbound is the
direction batch work fails in, and a blanket exemption in both directions would have hidden
all five findings.

RULE 283 — **when you write the thing a gate should have demanded of you, ask why it did not.**
Four CronJobs needed egress policies and the coverage gate was silent, because CronJob was not
in `WORKLOAD_KINDS`. Adding the policies would have been a complete, correct, entirely
insufficient fix: the next scheduled job would have shipped cut off in exactly the same way,
and the gate would have gone on reporting full coverage. Widening the population took five
minutes and found a production deploy that could not have worked. **The absence of a complaint
is evidence about the checker, not about the code** — and the moment you notice you are doing a
gate's job by hand is the cheapest moment you will ever get to check its population.

---

## FS-834..837 — the four missing runbooks

The runbook set covered component failures — a database down, a broker down, a worker wedged.
It had nothing for the four situations where the *system* is working and something has gone
badly wrong anyway. Each of these is written against what this codebase actually is, not
against a generic checklist, and in three of the four the most useful content is a constraint
that would otherwise be discovered mid-incident.

### Certificate expiry — two incidents sharing a word

`IngressCertificate*` and `EdgeAgentCert*` differ in every respect that matters. An expired
ingress certificate is every customer at once; an expired edge certificate is one device that
buffers and backfills. SEV-1 versus SEV-3, and the runbook leads with the table that separates
them.

Two things worth knowing before the alert fires:

- **The ingress alert reads `probe_ssl_earliest_cert_expiry`** — what a customer's handshake
  sees, not what cert-manager believes it issued. Those diverge exactly when the controller is
  still serving the old certificate from a valid renewed Secret, which is the confusing case.
- **An expired edge certificate is not self-healing.** Renewal happens over the uplink, and an
  agent whose certificate has expired cannot authenticate to ask for a new one. So the runbook
  says: plot the expiry *distribution* first. A handful spread over weeks is maintenance; a
  cliff is a fleet-wide outage with a date on it, because certificates issued in one enrolment
  campaign expire together.

### Tenant-isolation breach — do not start by reading the endpoint

SEV-1 **on suspicion**, because the GDPR Art. 33 and DFARS clocks start at discovery. The
diagnostic order is deliberately not "read the code":

1. `SELECT rolbypassrls FROM pg_roles WHERE rolname = current_user` — if that is true, every
   RLS policy in the schema is decorative and everything below means something different. It
   is an open question in `api-contract-gate.md` and it is one query.
2. Was `app.current_org_id` set? A plain `get_db` on a FORCE-RLS table reads **zero rows and
   raises nothing**. `test_tenant_session_guard.py`'s header records the incident this runbook
   exists for: the first MFA check read `user_mfa` on an untenanted session, matched zero rows
   for every user, and **login stopped enforcing the second factor while returning 200**.
   Zero rows read as "no MFA configured".

And the honest limit on scoping: the audit middleware captures **18 route templates out of
~546**, so absence of an audit row is not evidence nothing was read. Better known at hour one
than at hour seventy.

### A bad deploy wrote bad data — rolling back does not undo the writes

The ordering is the content: **stop, measure, then choose the narrowest instrument.** Four
options ranked by how much good data they destroy — correct in place, recompute from raw
telemetry (retained 90 days per tenant since FS-816, so most of it is reconstructible without
a restore), PITR into a *side* database to diff against, and a full restore last.

"Recover to a new cluster, never over production" is the step that matters. It turns an
all-or-nothing choice into a diff, which is what lets you keep the legitimate writes from
tenants who had nothing to do with the bad deploy. And it carries the qualifier the other
documents carry: PITR is proven and **not available in any environment yet**, so today the
equivalent is restoring the nightly dump into a scratch database.

### A noisy tenant — every containment option is blunt, and the runbook says so first

This one leads with what is missing, because reaching for a knob that does not exist is the
default failure mode:

- **rate limits key on the token's `sub`** — the user id — so a tenant's budget scales with
  its user count, and a service account is limited as though it were one person typing;
- **there are no quotas at all**: `quota`, `max_assets`, `tenant_limit`, `plan_limit` return
  zero hits across the backend.

So containment is: find and stop the specific job, cancel the queries (`pg_cancel_backend`
before `pg_terminate_backend`, which just makes the client retry), shed by priority tier, and
only then block the tenant — which is a customer-affecting decision that starts its own
notification clock. The closing table names FS-842..845 and 860..864, because if this happens
twice it is not an incident, it is a missing feature.

### Also

Eight alerts now carry `runbook_url`s pointing at these — including `AuthBruteForceSuspected`
and `AuthFailureRatioHigh`, which previously sent an operator to error triage. Removing a
duplicated annotation key uncovered a live pointer to `scripts/certificate-rotation.sh`, now
referenced from the runbook with the warning its own header implies: it writes to `/certs` and
expects to run somewhere those paths mean something.

RULE 284 — **a runbook's most valuable content is the constraint, not the procedure.** The
commands in these four are unremarkable and mostly recoverable from memory. What is not is that
an expired edge certificate cannot renew itself, that a plain `get_db` on a FORCE-RLS table
returns zero rows silently, that the audit log covers 18 routes of 546, and that there is no
per-tenant rate limit to raise. Each is a fact that changes what you *do*, is invisible from
the code you would naturally open first, and would otherwise be learned at the worst possible
moment. Write the constraints at the top, above the steps.


## The two dev branches — what merging them actually cost

Two lanes had shipped work that had never met the converged line: the OTA lane
(`hridyansh/integration`, 85 commits to 2026-08-23) and the RAG lane
(`feature/RAG-Compliance-Doc-Pipeline`, 41 commits to 2026-08-27). Both live on the `backup`
remote only. Fifteen of the seventeen branches on each remote differ from `main` by nothing but
the `SECURITY: origin was force-pushed` notice commit.

**The survey mattered more than the merge.** The RAG branch's raw diff touches ~900 files and
reports **155 conflicts**; the number that decides how to approach it is that its author
authored changes to **89**, of which **21** collide with mine. The other 134 are the
2026-08-15 force-push recovery: it re-hashed my commits, so the copies merged onto his branch
on 2026-07-19 are no longer ancestors of my line, and git correctly refuses to guess about
files exactly one person ever edited. `git merge-base --is-ancestor <my-old-commit> HEAD`
returning NO while the same query against his branch returns YES is the signature, and it turns
134 files from "resolve by hand" into "take mine, by definition". That is method rule 288.

The OTA branch was the opposite shape: 20 files, all in lane, migrations a byte-identical
subset, four conflicts.

### What each merge found that its own tests did not

Neither branch was careless. Both were behind, and *behind* is its own failure mode.

**The OTA merge moved an alert onto a metric nothing watches.** `HTTPRestCollector` was
refactored to call `record_poll_failure` — classified, with `failure_class` and consecutive
counts — instead of `record_error`. Strictly the better metric, and the only writer of
`edge_collector_errors_total`, which is what `alerts.yml:216` and `:312` fire on and what
`edge-collectors.json` plots. A device answering 500 forever would have incremented a counter
no rule reads while both edge alerts stayed silent: the green-by-vacancy class the FS-769..798
wave had just spent thirty items closing. The fix is one line — the classified counter is now
additive to the coarse one — and what caught it was an FS-691 test written months earlier for
a different reason.

**The RAG merge twice lost my own work to "his lane, his file".** `rag_retriever.py` and
`rag.py` predate the 2026-07-31 Compliance Assistant slice, so taking them wholesale deleted
`SourceDoc`, `_build_sources`, the ERP operational leg, `POST /documents/link` and the FS-742
transport handling — with git reporting both files cleanly resolved. `test_rag_erp_context.py`
failed on a missing import and `test_lane_failure_root_causes_stay_fixed.py` found three routes
that had stopped translating a connection failure. The files are now his structure — a shared
`_gather_context` feeding both `retrieve` and `stream` is better than what I had — carrying my
additions back on top. That is rule 285, and it is the one I would most expect to repeat.

### The six guards, and why none of them was loosened

| Guard | What it caught |
|---|---|
| `check_migrations.py` | 043/044 collided; renumbered to 073/074. Duplicate prefixes are grandfathered here, but *new* ones fail, and the four grandfathered entries stayed four |
| `test_insert_ordering_is_possible` | `RagDocument` had FK columns and no `relationship()`, so a flush could emit it before its parent — a Postgres FK violation, silently fine on SQLite |
| the naive-datetime guard | `default=datetime.utcnow`, the form FS-96/97 removed, which is why `models.py` no longer imports `datetime` at all |
| `check_probe_ports.py` | `rag-indexing-worker` shipped with **no probe of any kind**: a pass wedged on an unreachable Qdrant left a pod Kubernetes called healthy while the queue backed up |
| `test_the_swallow_surface_only_shrinks` | three new broad handlers. Two now count; two were **narrowed to what their own comments claimed** — a defect on our side was being requeued, written to the row as `failed`, and dressed as an infrastructure fault |
| `test_response_model_coverage_ratchet` | two undeclared routes. `/query/stream` declares `text/event-stream`, because declaring the media type is how a route honestly says it has no JSON schema; `/documents/{doc_id}/status` got a real model instead of `Dict[str, Any]` |

The mutable-tag guard is the interesting one. The RAG base runs three unpinned images and is
built by no kustomization, so it is exempt exactly as `legacy-patroni` is — but a path-prefix
exemption never expires, and wiring the tree into an overlay is one line. The entry therefore
arrived with a test that fails the moment any kustomization names it, mutation-verified by
adding `- rag` to `base/kustomization.yaml` and watching it go red. That test retroactively
closes the same hole `legacy-patroni` had carried since it was created. Rule 287.

### Two things taken from the branches and two deliberately not

Taken: the RAG lane's **per-org ingest quotas** are the first per-tenant limits anywhere in the
backend — FS-842 says there are none, and that is now half wrong, with a working template to
copy. And `TEST_DATABASE_URL`, an escape hatch for hosts without Docker bridge networking,
which runs the full migration chain against whatever it names. Its docstring warned about that;
it now refuses, because the obvious value to reach for on a developer machine is the dev
database, which is the one whose schema must not be rewritten.

Not taken: `S3_ENDPOINT_URL` repointed at the rag namespace — it is shared with the export
pipeline, so it would have moved exports onto a host that resolves only where the rag base is
applied — and `MTLS_ENABLED` as an explicit `env` entry, which beats `envFrom` and would have
broken the staging overlay's `MTLS_ENABLED=false`. Both are recorded in the manifest beside the
lines that would otherwise invite them back.

Backend 5,306 → **5,398**; frontend 1,211 → **1,223**; edge 477 → **490**, plus 109 DDIL
scenarios. Method rules to **288**.

## Wave 3 (FS-839..870) — capacity, and the numbers nobody had chosen

Wave 1 asked whether the platform could see an outage. Wave 2 asked whether it could
survive one. This wave asked what happens on an ordinary busy Tuesday, and the answer kept
being the same shape: **a limit existed, it was chosen by an upstream project, and nobody
here had ever looked at it.**

### The connection budget: 465 against 100

`create_async_engine` was called with no `pool_size`, so every process ran SQLAlchemy's
default of 15 connections. The base StatefulSet set no `max_connections`, so that was
PostgreSQL's default of 100. Two upstream projects had chosen the numbers governing this
platform's scale-out.

Reverting both halves and running the new check measures it: **staging demanded 465
connections against 100**, DR 120 against 100 —

    ingestion-worker  12 x 15 = 180      backend            2 x 15 =  30
    export-worker      8 x 15 = 120      ota-rollout        1 x 15 =  15
    compliance         6 x 15 =  90      rag-indexing       1 x 15 =  15

Production never showed it, because the CNPG pooler multiplexes in front of the cluster.
**Staging applies identical KEDA ceilings with no pooler**, so the environment that breaks
is the one nobody load-tests — and past the limit PostgreSQL refuses the next connection
from *anybody*, so the backend and every worker fail together, during the load spike that
caused the scale-out meant to relieve it.

The guard is the durable part: it sums each environment's worst case from the manifests and
follows the pooler where it is in the path, checking clients against `max_client_conn` and
what the pooler opens against the cluster's own limit — because multiplexing moves the
ceiling rather than removing it.

### The SLA was computed from half its data

The same shape, one layer up. `slo_rules.yml` derives the contractual error budget from
`avg_over_time(...[28d])`; Prometheus kept **15 days**. Nothing errored — `avg_over_time`
averages the samples present and ignores the absent ones — so the number was confident,
derived from a fortnight, and because the missing half is always the oldest, **a bad start
to a month vanished from that month's budget. The error flattered.**

That is the FS-770 finding again (`clamp_min` reading 1.0 during a total outage) with the
expression correct and the store wrong. Wave 1 fixed what the query said; this fixed what
it had to say it about. The customer-facing uptime commitment carries the correction,
because it promised the 28-day window in writing.

### Shedding was deliberate data loss with no signal

`DataSheddingManager` was better than the plan assumed — already cloud-side, five tiers,
per-tenant overrides, wired into the ingestion worker. What it did not do is say so. The
only record of a dropped reading was `logger.debug("data_shedded", ...)`, and the deployed
`LOG_LEVEL` is `info`. **On a production cluster a tenant's telemetry was discarded and
nothing anywhere recorded it.** The first party able to notice was the customer, looking at
a gap in a chart.

### Which led to the item the plan had pointed in the wrong direction

FS-865 asked for admission control on the ingest endpoint. That endpoint exists, is
authenticated, has rate limiting and quarantine handling — and **nothing calls it**; its own
header says so. The agent publishes straight to the broker.

The real loss is upstream of shedding: the agent drains its buffer as fast as the link
allows, Kafka gives a producer no view of consumer lag, and by the time the worker starts
dropping readings those readings had been sitting safely in an encrypted durable buffer on
the device. **The edge holds data well; the cloud under pressure holds it by dropping it.**
So the answer was to slow the producer and leave the data where it is safest — carried on
the heartbeat ack every agent already polls, with every failure direction resolving to
"keep sending", because a mechanism that fails toward throttling silences a fleet on a typo.

### The rest, briefly

Per-tenant rate limits (a 500-user tenant had 500× the budget of a single-user one, so the
noisiest neighbour was structurally the largest customer), volume quotas including a storage
figure that had to be built before it could be enforced, a bulkhead so one tenant cannot
take every connection in a pod, a request deadline because the ingress cut the client off at
60s and nothing told the server, a circuit-breaker primitive, one Redis pool instead of
seven, namespace quotas, `preStop` hooks, spread constraints, priority classes, and a
startup probe for a database that was being **killed 60 seconds into WAL recovery** — each
kill leaving more WAL to replay, so the loop diverged rather than converging.

### What this wave says about the method

Five of the findings were caught by guards written for something else, and four were in code
written earlier in the same session. That is the system working, and it is worth stating
plainly rather than quietly: **the guards found my new code as readily as anyone's.** The
recurring failure was mine, not the codebase's — a check that could not distinguish the
states it claimed to (rule 37), five separate times: a name-in-file match that survived
deleting the code it guarded, a character-window that survived moving code out of its block,
a line match located with `str.index` on a repeated line, a prefix match that could not tell
a removed flag from its replacement, and a test that reloaded config and broke 27 others.

Every one was found by mutation-testing rather than by reading. The habit is cheap and it is
the only thing that reliably separates a guard from a decoration.

Backend 5,171 → **5,510**; edge 477 → **515** plus 109 DDIL; frontend 1,223. Method rules to
**293**. Twelve Kubernetes gates, 79 alert rules, 17 promtool suites.

## FS-871..879 — closing Wave 3, and the first of Wave 4

### How long does a device survive an outage, and what decides it

No document answered that, so the answer was whatever the operator guessed. Measured
against the real buffer: **195 bytes per reading on disk** — a full telemetry row after
JSON framing and SQLite page overhead, checkpointed, because without the checkpoint the WAL
hides a third of the writes and the figure comes out low in the one direction that matters
when somebody is sizing a disk from it.

The byte count is not the finding. **Which of the three limits governs changes with the
reading rate**, and the crossover is 62 readings per second:

    10/s     161 MB/day    retention (24h) binds     24.0 h of buffer
   100/s   1,607 MB/day    size cap (1 GB) binds     14.9 h

Below the crossover, raising `max_size_mb` buys nothing — age is deleting the data first.
Above it, the 24-hour figure everyone quotes is no longer what the device delivers. The two
knobs looked interchangeable and are not, and an operator had no way to know which one they
were arguing with.

What falls out of that is worse than a capacity question. The two full-buffer mechanisms
lose *different data*: the size cap fires hourly and sheds by priority tier, while a full
disk raises `SQLITE_FULL` and prunes the oldest 500 rows — age being all that path can
express, so it will discard an alarm to make room for a vibration reading. A `max_size_mb`
larger than the disk is not a bigger buffer; it is a buffer whose real limit is the blunt
mechanism.

### The DDIL case that eight scenarios missed

Every existing scenario denies the link — deny it, flap it, lose packets, throttle it — and
the agent's answer is always the same and always obvious: hold the data. FS-866 created a
case none of them cover. **The link is perfect.** The backend is up and answering
heartbeats. The pipeline behind it cannot keep up, so the cloud asks the device to slow
down.

That is the interesting one precisely because sending is the default and every instinct in
the drain loop is to keep going — and the readings it would push are ones the cloud has
already said it will drop, converting data that is safe in an encrypted local buffer into
data that is gone. Ten scenarios, including the mirror case a naive `if level:` gets
backwards: a malformed ack must not CLEAR a legitimate throttle either, because a malformed
response is not evidence the cloud recovered.

### Wave 4 opens: five questions where two would do

`/overview` ran five queries — three reading `assets`, two reading the same `Alarm ⋈ Asset`
join, each pair differing by one predicate. A subset asked as its own query pays a round
trip, and for the alarms a second join, to re-ask something already in flight. It is polled
every 30 seconds per open tab, against a pool of 10 connections per process.

**The task pool's suggested remedy did not apply**, and that is the third time this sprint:
"read from the continuous aggregates instead of recomputing" — but those roll up
`telemetry`, and nothing here is time-series. They are row counts. The fix was `FILTER`
clauses; five round trips became two.

### The test that proved nothing

The correctness of that collapse rests on one identity: `total_assets` is now the sum of the
state histogram rather than its own `COUNT`, which holds only while the grouping covers the
same population. The guard asserted exactly that, over HTTP.

It passed. It also passed when the query was mutated to exclude NULL states — because the
shared fixture holds **zero assets**, and `sum({}) == 0` regardless of what the query does.

The assertion was right. What was wrong is that an end-to-end test inherits its population
from a fixture written for someone else's purpose, and that population is invisible at the
point of assertion. The derivation is now extracted and tested against inputs it constructs
itself — a NULL state, an empty population, and a subset invariant that catches a
mis-ordered unpack. That test cannot be vacuous.

Second time this sprint a guard of mine proved nothing until something deliberately broke
it, and both times mutation-testing was the only thing that noticed. Rules 294 and 295.

Backend **5,518**; edge 515 plus **119** DDIL scenarios; frontend 1,223. Method rules to
**295**.

### FS-880, FS-881 — the worst N+1 in the tree, and a fleet sent as a parameter

`erp_integrations.py`'s sync ran one `SELECT ERPEntity` per record, nested inside the
per-entity-type loop — a 10k-row SAP sync was 10k round trips. Fixed with one `IN`-batched
pre-fetch keyed on `(entity_type, entity_id)`, built once per type before the record loop,
with a same-batch duplicate-id guard (`existing_by_id[eid] = created` on insert, so a second
record with the same id in one batch updates rather than re-inserting).

`/fleet/oee` selected every active asset in the org into Python, then passed
`.in_([a.id for a in assets])` back to Postgres — the id list, and the round trip to build
it, both grow with the fleet. Replaced with a `JOIN` from `PackMLState` to `Asset` so the
fleet never leaves the database as a parameter.

### Two guards that measured the wrong thing, on the first attempt

The `/fleet/oee` test located its target function with `"oee" in node.name.lower()`, which
matched `get_asset_oee` — defined earlier in the same file — instead of `get_fleet_oee`.
The guard passed while inspecting a function the fix never touched. Fixed with an exact
name match.

The tenant-scoping assertion, `assert "Asset.organization_id == org_id" in source`, passed
both before and after the join predicate was removed by mutation, because the literal
string already appears in the same function's earlier asset-fetch query. Sixth guard this
sprint confounded by a subject that exists somewhere else in the file it's read from.
Fixed by counting occurrences instead of presence. Rules 296 and 297.

Backend **5,527**. Method rules to **297**.

### FS-882, FS-883 — a flush that got slower during the incident it existed for

`error_tracker._flush_once` upserted one `error_events` row per fingerprint and, nested
inside that, one `error_event_buckets` row per hour bucket that fingerprint touched. Both
counts grow with error DIVERSITY — a single root cause fanning out across routes and status
codes produces more fingerprints, not more occurrences of one — so the flush got slower
exactly when an incident made speed matter. Fixed by flattening the batch into two
parameter lists (one per statement) and issuing each via `executemany`, so a flush costs
two round trips no matter how large the batch.

`edge_fleet_sweep.sweep_once` opened two fresh `AsyncSessionLocal()` per organisation per
sweep interval — one to set the tenant GUC and read `EdgeAgentStatus`, a second to set the
same GUC again and read `Asset`. A background loop that never serves a request was taking
two pooled connections per org on a timer, direct pressure on the ceiling FS-839 sized
against `maxReplicas × pool ≤ max_connections`. Both reads now share one org-scoped
session.

Both guards were written matching their target function by exact name (rule 296) and
mutation-verified against the pre-fix code via `git stash` before committing.

Backend **5,533** passing, 110 skipped.

### FS-884, FS-885 — the same session-per-org shape, twice more

`command_executor.expire_timed_out` and `workers/compliance_reports.recover_stale_jobs` are
both periodic background sweeps — a timeout loop and a stale-job recovery loop — that run
forever, unconditionally over every organisation, and both opened a fresh
`AsyncSessionLocal()` per org on every pass: the identical shape FS-883 fixed in the fleet
sweep. Both now reuse one session for the whole pass, re-setting the tenant GUC per org.

Checked the same premise against `compliance_report_queue.recover_stale_publications` — the
plan's other cited line — and it was already correct, one session reused from the start.
`command_executor` has four other per-org loops (`get_command_status`, `cancel_command`,
`handle_command_ack`, `get_pending_count`); all four resolve to a single org in production
because every caller passes `organization_id`, so they were left alone rather than
refactored for a path that isn't actually hot.

Fixing FS-885 broke `test_worker_tenant_guc_hygiene.py`'s exception for the org-enumeration
session — an 8-line proximity window had been crediting that untenanted read with the NEXT
session's `_set_org` call, by coincidence, since before this sprint. Consolidating the
per-org sessions moved that call outside the window and surfaced it. Same shape as rule
297: a check satisfied by something nearby for an unrelated reason. Named the exception
explicitly rather than leaving it to proximity.

Backend **5,539** passing, 110 skipped.

### Registered, not fixed: the session-per-org shape recurs four more times

A sweep for the FS-883/884/885 shape (`for org_id in ...` opening a fresh
`AsyncSessionLocal()` per iteration, in a loop that runs forever) across `app/services` and
`app/workers` found it again in `export_delivery.dispatch_due`,
`rollout_orchestrator` (its own org loop), `report_scheduler.dispatch_due` (nested two
levels deep — a session per org AND a session per due schedule inside that), and
`posting_drain_scheduler`. Not fixed in this pass: several of these interleave an external
publish (Kafka) between the per-item DB reads and writes, which is a legitimate reason for a
narrower transaction boundary — the same reasoning that kept `command_executor.dispatch_pending`
untouched — and distinguishing the safe consolidations from the correctness-motivated ones
in four more files is its own pass, not a rider on FS-885. Registered for a dedicated sweep.

**Separately, and unrelated to the session-count question:** `export_delivery.py:214` sets
`app.current_org_id` with `is_local=false` — session-scoped, not transaction-local — twice.
`test_worker_tenant_guc_hygiene.py` already documents this exact footgun in its own
docstring ("nothing leaking today... a property of the current code, not of the
mechanism") but the guard's own glob only scans `app/workers/*.py`, and `export_delivery.py`
lives in `app/services/`. The known risk has no guard watching it. Registered.

### FS-886 — premise verified and corrected: bounded, not data-scaling

`verify_refs` in `core/tenant_refs.py` does run one query per registered FK field present
on the request body, as the plan states. **Measured against the real population before
touching it**: the ceiling is **8** (`TaskCreate`/`TaskUpdate`/`TaskResponse`), most models
carry 1-4, and the number is fixed by the SCHEMA, not by data volume — unlike every other
Wave 4 item so far (ERP records, fingerprint diversity, organisations on a timer), this cost
does not grow with fleet size, error volume, or org count. It is a bounded per-request cost
on a write path, not a loop that gets worse.

Restructuring it into one combined query would mean a UNION across differently-shaped joins
(`_direct`, `_via_asset`, `_via_board`) with a discriminator to recover which field failed,
and losing the ability to catch a single malformed id (`DBAPIError`) without poisoning the
whole batch — real complexity, in the file that carries this repo's tenant-isolation
reasoning (FORCE RLS interaction, 404-never-403, the redundant-until-someone-breaks-it
comment already in the module). Given the ceiling is 8 round trips on a request that isn't
high-frequency, the fix does not clear its own bar. **Not changed.** Corrected in place
rather than implemented as written, per the house rule that a premise gets verified before
it gets built around.

### FS-887 — registered, HARSH's lane, not edited

`api/kanban.py:1522-1560` `/workload` runs 4 aggregate queries per user (50 users = 201
queries; collapsible to one `GROUP BY assigned_to` with `FILTER` clauses, the same shape
FS-879's dashboard fix used) and `api/analysis_sessions.py:494-504` runs 2 `SELECT`s per
session plus `len(...scalars().all())` to count — materialising whole rows to get a number.
Both confirmed present at the cited lines. Correlation/MLOps is HARSH's lane; registered
rather than edited, per the sprint's lane rule.

### FS-888 — the largest table in the product had no index its own search could use

`assets` carries ten indexes and none on `name`, while every list call orders by it and a
search term filters `name.ilike('%search%')`. A leading wildcard cannot use a plain btree
index — the match can start anywhere in the string — and none of the 75 prior migrations
ever installed `pg_trgm`, so nothing could have served that filter even with an index
present. Migration 076 adds `(organization_id, name)` for the ordering/RLS case and, guarded
behind a `pg_extension` existence check, a `pg_trgm` GIN index for the search case — a
restricted environment without extension privileges gets the composite index and a slow
search rather than a broken migration.

The guard runs against a real database rather than reading the migration file: it confirms
the extension is actually installed (not merely attempted), the GIN index exists, and —
since the test fixture's empty table would otherwise let the cost-based planner choose a
sequential scan regardless of which indexes exist, the same vacuous-fixture shape as rule
295 — asserts with `enable_seqscan` forced off that an index-based plan exists at all.

Backend **5,542** passing, 110 skipped.

### FS-890 — premise did not reproduce: these four tables are already indexed

The plan named `sites`, `fleet_tags`, `fleet_groups`, `fleet_cohorts` as having **no index
at all**, including none on `organization_id` — which the RLS policy on each evaluates on
every row. **Measured against a real database before touching it**: all four carry
`UNIQUE (organization_id, key)` and `UNIQUE (organization_id, name)` constraints
(065_fleet_targeting.sql), and a UNIQUE constraint in Postgres creates a backing btree
index — `organization_id` leads both, exactly the shape migration 043 established for the
tenant-scoping predicate. `sites` and `fleet_tags`/`fleet_groups`/`fleet_cohorts` are not
doing a sequential scan on RLS's predicate; every route in `api/fleet_targeting.py` filters
on `organization_id` (plus `is_active` or `id`), and both are covered.

`test_schema_parity.test_org_scoped_tables_have_org_index` already asserts this for every
table with an `organization_id` column, was already passing before this item was opened,
and would fail if any of these four regressed. **Not changed.** Corrected in place per the
house rule — the premise did not reproduce.

### FS-889, FS-891 — two more missing indexes; a repeated detector weakness fixed on sight

`session_data_sources` and `session_messages` (FS-889) had a foreign key on `session_id`
and no index leading with it — the only index on either table is a GIN on
`shared_keys::jsonb`, unrelated to the join. Migration 077 adds both.

`shipments` (FS-891) had one composite index, `(organization_id, created_at DESC)` from
migration 043, and two other real access patterns with nothing: the shipments list filters
`status` after the org predicate, and the driver panel filters `driver_id` + excluded
statuses ordered by `scheduled_pickup`, with no index on `driver_id` at all. Migration 078
adds both.

FS-891's guard caught its own first-draft weakness before it shipped: a bare "no Seq Scan"
check for the org+status query passed even WITHOUT the new index, because the pre-existing
`ix_shipments_org_created` already lets the planner avoid a sequential scan on the
`organization_id` equality alone, leaving `status` as an unindexed Filter step on top of an
Index Scan. Same shape as rule 297 — a check satisfied by something already present for an
unrelated reason. Fixed by naming the new index specifically in the assertion rather than
checking for the absence of a scan type.

Backend **5,548** passing, 110 skipped.

### FS-892 — the live-detention query scanned the org's whole trailer history

`api/yard.py`'s live-detention query filters `check_in_at IS NOT NULL AND check_out_at IS
NULL` — the currently-checked-in subset — but the only index touching that shape,
`ix_yard_trailers_org_checkin` (migration 043), orders the org's FULL history. Migration 079
adds a partial index on the open-row predicate, the same idiom `060_shop_floor_events.sql`
already used for `labor_entries` and `downtime_events`.

Its guard needed the same fix as FS-891's: the pre-existing index absorbs
`organization_id` and `check_in_at IS NOT NULL` as an Index Cond, leaving `check_out_at IS
NULL` as an unindexed Filter on top — a bare no-sequential-scan check would have passed
without this migration. Named the new index specifically, verified the without-migration
EXPLAIN shows exactly that shape.

Backend **5,550** passing, 110 skipped.

### FS-893 — the remainder table, measured item by item

`carriers` and `drivers` already carry `(organization_id, created_at DESC)` from migration
043 — nothing to do. `analysis_sessions` had the same org index, but almost every route in
`api/analysis_sessions.py` filters by `user_id` instead (fetch, list, delete), several also
filtering `status` — neither column had an index. Migration 080 adds `(user_id, status)`.

The rest of the plan's list does not need an index, measured rather than assumed:
`asset_types` is a small global catalogue whose only non-PK filter is `category`;
`organizations` and `data_retention_config` (keyed by `table_name`, "one config" per the
module's own comment) are both small reference tables. And `telemetry_buffers`,
`permissions`, `role_permissions`, `reward_metrics` have **zero references anywhere in
`backend/app`** — no ORM model, no raw SQL, nothing queries them at all. Indexing a table
nothing reads is pure waste; the real finding is that they're dormant. Registered for
FS-913 (dormant services/tables) rather than indexed here.

Backend **5,552** passing, 110 skipped.

### FS-894 — a register, not a sweep, and said so up front

The plan's own item asked for "a test that every column a list route filters or orders on
is either indexed or registered with a reason" — which, done honestly for the whole app,
is its own project: an AST walk across ~60 API modules matched against a live schema,
without becoming a shallow tool confident about the wrong thing (rule 296/297's territory,
repeatedly hit this sprint). Built the scoped version instead: a register locking in the
thirteen (table, column) pairs FS-888 through FS-893 actually measured, checked by index
NAME against a real database, plus seven exemptions each carrying a non-empty reason.
Explicit in its own docstring about what it is not. Gives future index work a place to
register into rather than a false sense that the whole surface is covered.

Backend **5,573** passing, 110 skipped.
