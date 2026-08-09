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
