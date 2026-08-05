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
