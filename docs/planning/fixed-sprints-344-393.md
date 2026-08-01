# Fixed sprints FS-344 → FS-393

Written 2026-08-01 on `hamad/converged-pre-main`. Continues the FS series (highest prior:
FS-343, plus FS-259b and FS-284b).

## How this document was made, and why that matters

**It was derived from the codebase. The previous plan was derived from the task pools, and
that is why it was wrong.**

`fixed-sprints-241-343.md` was written on 2026-07-31 from `next-week-task-pool.md`. Executing
part of its Wave A the following night established that it could not be trusted as an
inventory of remaining work: **five of the eight platform items examined described work that
was already delivered** — by FS-200, FS-214, FS-230 and FS-240, every one of which predates
the plan. The plan inherited each claim the pools had already outgrown.

That earlier document's header warns about drift, but about numbers drifting in the
*flattering* direction — a count that makes the state look better than it is. These drifted
the other way: describing work that no longer exists and **inflating what is left**. Both are
harmful, and the second is harder to notice, because nobody investigates a backlog that looks
too long.

So every item below carries the evidence that justifies it — a file path, a line number, or a
measurement taken on 2026-08-01. Where a claim could not be verified it is marked *unverified*
rather than asserted. **Verify the premise before starting anyway**, and if it does not
reproduce, correct the entry in place with the date.

## Lane discipline

Derived from each dev's own commits. **Hands off**: `auth.py`, `kanban.py`, `telemetry.py`,
`analysis_sessions.py`, `nlp_correlation.py`, `model_monitoring.py`, `logistics_correlation.py`,
`engines.py`, `rag_*.py` internals.

Items marked **⚠** touch another lane and need the owner's agreement first. Everything
unmarked is clear. Sizes: **S** under half a day · **M** 1–2 days · **L** 3+.

## The weighting

| Wave | Kind | Count | Why here |
|---|---|---:|---|
| F | **Honesty** | 10 | Generated figures presented as measurements. First because the schema work of FS-253…264 made these surfaces *look* more trustworthy without making them more true. |
| G | **Correctness & tenancy** | 10 | Data that reaches the wrong tenant, or does not reach anyone. |
| H | **Verification** | 12 | Code that ships and nothing exercises, plus the guards for defect classes already found by hand. |
| I | **Product capability** | 10 | Features. Two of them are UI that renders nothing because the fields behind it are never sent. |
| J | **Production readiness** | 8 | The operational items that are not gated on a second cluster. |

---

# Wave F — Honesty (FS-267, FS-344 … FS-352)

A generated number behind a clean schema is worse than a generated number behind no schema,
because the schema is a claim that someone checked. Three of these already carry a source
comment admitting the problem. **A comment is not a control** — the same argument FS-200 made
for placeholder secrets.

- **FS-267 · GeoTab: two gated functions are never stamped** · M — pool #44
  `geotab_service.py` has two defences and they cover **different sets**. `_require_simulated()`
  (line 28) is called by four functions — `get_exceptions` (97), `get_device_diagnostics` (132),
  `get_driver_hos` (352), `get_fleet_summary` (624). `_simulated_provenance()` (line 37) is
  applied at **two** sites only: 394 and 645.

  So `get_exceptions` returns up to 10 fabricated records per call — `exception_type` drawn
  from a list containing `hos_violation`, and `details.value` / `details.threshold` from two
  *independent* `random.uniform(0, 100)` calls, so a value and the threshold it supposedly
  breached are uncorrelated — and reaches the client through `GeotabExceptionsResponse` with
  **no provenance field**. `get_device_diagnostics` returns fabricated DTC codes, battery
  voltage, odometer, engine hours and reefer `temperature_setpoint`/`temperature_actual` under
  `response_model=Dict[str, Any]`, so nothing would flag the absence either.

  Cold-chain temperatures and DTC codes are the same class of actionable figure as HOS.
  *Done when:* every `_require_simulated` call site has a matching `_simulated_provenance`
  stamp, **and a test fails if a new one does not**.
  ✅ **DONE 2026-08-01.** All four gated functions stamp; the exceptions envelope stamps too
  (the generator can draw zero records, and an empty simulated list would otherwise carry no
  provenance at all — the reading an operator is most likely to trust). `simulated_provenance`
  is now public because the envelope is built in the API layer.
  `tests/test_simulated_data_says_so.py` sweeps the pairing by AST — not by grep, because the
  docstrings here quote both helper names while explaining the defect, and this repo has
  already had a sweep flag the comment describing its own fix.

- **FS-344 · `GEOTAB_SIMULATED` defaults to `True`** · S — **ALREADY SATISFIED, corrected
  in place 2026-08-01, on the first day of this plan's own life.**
  `config.py:307`; a production validator at 386-387 raises if it is still true in production.
  This entry offered two ways to close it — flip the default, or prove the validator's coverage
  with a test that fails when it is removed. **The second was already true**:
  `test_config_validation.py:28` asserts it, and mutation-checking confirmed the test fails
  when the validator line is deleted.

  Flipping the default is the wrong half to take: `GEOTAB_SIMULATED=True` is what makes the
  documented offline demo work, and the README's claim that the whole platform demos with no
  live services depends on it.

  **Recorded rather than quietly ticked off, because this document was written the same
  morning and made the same mistake it was created to prevent** — the item came from an
  evidence report saying "the exposure rests entirely on one production validator", and I did
  not check whether that validator was tested before writing the sprint. Verify the premise.
  A second assertion was added to `tests/test_simulated_data_says_so.py` anyway, beside the
  provenance sweep, because the default is what makes the validator load-bearing.

- **FS-345 · A simulated position is indistinguishable from a fix** · S
  `geotab_service.py:502-519`. `get_device_location` invents a lat/lon inside a US Midwest
  bounding box when no real fix exists. Correctly gated at 503 — and the returned dict carries
  no provenance, so a consumer cannot tell.
  ✅ **DONE 2026-08-01**, and the stamp here is **conditional**, unlike every other one in the
  file. This method prefers a real trip endpoint or exception fix; stamping unconditionally
  would label a genuine GPS fix as simulated — a falsehood in the other direction, and one
  that would teach a consumer to ignore the flag. Both branches are asserted.

- **FS-346 · The compliance report states four figures it does not compute** · M
  `compliance.py:406` — `"active_assets": total_assets  # Simplified for now`. The active
  count is the total count, on an **ISO-27001** block. `:411` does the same on SOC-2
  (`pending_assessments = total_vendors`). `:414-415` hard-codes `consent_records: 0` and
  `data_processing_records: 0` on a **GDPR** block, with `# Will be populated from…`.
  A compliance report that reports zero consent records is not neutral; it is a finding.
  ✅ **DONE 2026-08-01.** All four now counted — every column already existed
  (`security_assets.status`, `vendor_risk_assessments.status`, and both GDPR tables), and
  the three existing counts moved from `len(rows.all())` to `func.count()` while I was there.
  `consent_records` is a JOIN through `users`, not a filter, because that table has **no
  `organization_id`** — `gdpr.py` records `user_id` as the right grain for consent.

  The tests seed rows in the **non-default** state deliberately: `status` defaults to
  `"active"`/`"pending"`, so a test built on default rows would pass just as happily against
  the bug. An AST assertion also fails on any hardcoded literal in the returned blocks, which
  is what makes `consent_records: 0` fail even for an org whose true count is zero.

- **FS-347 · The residency validator can only see its own tags** · M
  `data_residency.py:305-307`. Untagged rows — the ones a residency check exists to find —
  are invisible to it, and it scored **100%** on an org with one tagged row and ten thousand
  untagged ones.
  ✅ **DONE 2026-08-01 — as an admission, not a real count.** Counting the target table is not
  safely available here: `table_names` is caller-supplied (identifier interpolation), the
  handler runs on `get_db` so counting an RLS table returns 0 (a *fresh* wrong number), and
  `data_residency_tags` has no `organization_id` at all. A cross-tenant count needs FS-311.

  So `total_records` and `untagged_records` are now `None` rather than 0 — zero asserts that
  nothing is untagged — `compliance_percentage` is renamed `tagged_region_percentage` after
  what it is actually over, and a `coverage_warning` states the gap in the payload.

  **The endpoint had no behavioural test, and that cost me one.** The rename left a stale
  `validation_results["compliance_percentage"]` in the logger call, and a *full green suite*
  ran past a `KeyError` on the response path, because only `test_route_auth_walk` touched
  this route and it checks auth alone. A route that is only walked is a route whose body is
  unexecuted.

- **FS-348 · Route optimisation returns four hard-coded constants as results** · M
  `transportation_management.py:267-285`. Distance is estimated; duration is
  `total_distance / 50`; fuel is `gallons * 3.50`; tolls are `distance * 0.05`. Arguably worse
  than randomness, because deterministic output reads as computed. Same family as the fuel
  surcharge already recorded in the burn-down doc (`base_fuel_price=2.50`,
  `current_fuel_price=3.50` fallbacks).

- **FS-349 · `model_version = "gemma-4-placeholder"` ships in analysis payloads** · S · ⚠ Harsh
  `correlation_ai_engine.py:43`. There is no gemma-4. The `_simulate_analysis` path beside it
  (197-198, 227-228) *is* correctly labelled with `simulated: True` and a `simulation_reason`,
  which is the standard the version string does not meet.

- **FS-350 · Demo recommendations are loaded into the live queue** · S
  ~~`strategic_engine.py:118-119` … masked only by the fact that nothing starts
  `strategic_engine`.~~ **PREMISE CORRECTED 2026-08-01 — the gate exists.** `main.py:87`
  wraps the call in `if settings.ALLOW_DEV_TOKEN:`, the same flag as the dev-token auth
  bypass, which `validate_settings` refuses in production. The evidence report that produced
  this item read the service and not the caller.

  ✅ **DONE**, because what was genuinely missing is that **nothing tested the gate**. The
  exposure rested on one `if` that no assertion covered. `test_simulated_data_says_so.py` now
  fails if the call is not lexically inside a test of `ALLOW_DEV_TOKEN` — mutation-verified by
  replacing the condition with `if True`. Checked by AST rather than by running the lifespan
  twice, which would start the broker, the schedulers and the error tracker to prove one `if`.

  *Third premise in this document to need correcting on its first day* — after FS-344 and
  FS-352. All three came from evidence reports that were right about the code they read and
  silent about the guard one layer out. **Read the caller, not just the callee.**

- **FS-351 · Critical-risk alerts are logged, never dispatched** · M
  `correlation_registry_integration.py:1049-1050` — `# This would integrate with the
  notification/alerting system` / `# For now, log the alert`, on a path that classifies
  `severity: "critical"` when `risk_score > 75`. A name that claims a side effect.

- **FS-352 · `POST /admin/collectors/{id}/restart` restarts nothing** · S
  The whole handler is a `return` with `"status": "pending"` and a hardcoded
  `"2026-01-15T10:30:00Z"`.
  ✅ **DONE 2026-08-01 — removed**, along with the dead `assetsApi.restartCollector` client
  function, its route-walk and RBAC test entries, and the `CollectorRestartAck` model.

  **Two corrections this item needed.** First, it said "`assets.ts` calls it… so an operator
  clicking Restart gets a 200 and no restart" — carried from the burn-down doc. Wrong: the
  client function existed with **zero call sites**, and the Collectors page has no restart
  control. The endpoint lied, but nobody was listening.

  Second, "restarts a collector" was not an available closure. A restart must reach the
  device, and the edge agent registers exactly two command handlers — `agent_update` and
  `model_update`. Submitting a `restart_collector` command would queue something nothing
  consumes: the same lie one layer down and harder to see. Adding the handler is Hridyansh's
  lane. A 501 was rejected too — it is a 5xx, and the contract gate counts any 5xx as a
  ServerError, so an honest "not implemented" would have scored *worse* than the dishonest
  200. The route back is recorded in `health.py` where the handler used to be.

---

# Wave G — Correctness and tenancy (FS-266, FS-272, FS-311, FS-353 … FS-358, FS-259b)

- **FS-266 · `DELETE /rag/documents/{doc_id}` has no org filter** · S · ⚠ htreinen
  Carried from the previous plan, with one addition measured 2026-08-01: `doc_id` is typed
  `str`, so it is also the **one** `UnsupportedMethodResponse` operation that returns 500
  rather than 422. Its 13 siblings reject the literal path segment during path-param
  validation because their parameter is typed (`key_id: UUID`); this one accepts `"link"` as a
  perfectly good string and **reaches the deletion handler**.

- **FS-353 · Every inbound ERP webhook 404s** · M
  `tests/test_tenant_session_guard.py:113-121`, verified against a real database:
  `integration_configurations` has FORCE RLS and the candidate lookup returns nothing, so the
  webhook cannot find the integration it belongs to. The guard exempts `erp_webhooks.py`
  rather than pretending it is fine. **Needs a design decision** — a privileged read path, or
  the tenant in the URL — not a dependency swap.

- **FS-354 · `kanban.py` and `nlp_correlation.py` on `get_db` over FORCE-RLS tables** · M · ⚠ Harsh
  17 sites (10 + 7), pinned in `KNOWN_GET_DB_ON_RLS` at `test_tenant_session_guard.py:60`. A
  session that never sets `app.current_org_id` makes the policy predicate NULL, so **every row
  is filtered without raising**. Four of the ten known 5xx allowlist entries trace to it.

- **FS-355 · `error_events` has a tenant column and no policy** · L
  `test_every_tenant_table_has_a_policy.py:59-73` marks it **"REAL GAP, AND BLOCKED ON A GRAIN
  CHANGE"**: closing it needs `primary key (fingerprint, organization_id)`, a composite FK from
  `error_event_buckets`, and a rewritten `ON CONFLICT`/`COALESCE` in the ingestion upsert — or
  the platform-admin role of FS-311.

- **FS-311 · The `super_admin` role** · M — *decision before implementation*
  `roles.py:48-58` states the problem exactly: `data_retention`'s config table has no
  `organization_id` and its DB functions act across every tenant, so a per-org `require_admin`
  would let one tenant's admin purge another's data. The consequence is **8 routes are dark** —
  `test_data_retention_router_unmounted.py` fails the build if anyone mounts the global router
  — plus a 493-line `query_performance` router in the same state. The role vocabulary is three
  deep (`VIEWER/OPERATOR/ADMIN`), pinned by a CHECK constraint in migration 048.

- **FS-356 · Eleven capped lists still cannot say they were capped** · M
  `defect-class-sweeps.md:1435`. Twelve bare-array endpoints truncate with no signal; only
  `/api/v1/rul` was fixed. The recorded reason is that a fix needs the frontend consumer wired
  at the same time, and four are in other lanes. `mark_truncated`/`X-Result-Truncated` already
  exists in `app/core/pagination.py` and `erp_integrations.py` uses it — this is applying an
  existing utility, not designing one.

- **FS-357 · Twelve paths served at `/api/v1/logistics/logistics/…`** · S · ⚠ Harsh
  `logistics_correlation.py:62` declares `prefix="/logistics"` and `main.py:326` mounts it at
  `/api/v1/logistics`. Confirmed live: 12 paths carry the doubled segment, and one of them
  (`truck-asset-readiness`) is among the contract gate's 500s.

  **Why it is not a routing edit**, per `defect-class-sweeps.md:777-786` — and that analysis
  is correct, checked 2026-08-01. *Removing* the inner prefix would land
  `logistics_correlation`'s `/delivery-efficiency` and `/compliance/summary` on the paths
  `fleet_logistics` already serves, and since `logistics_correlation` registers first it would
  **silently win**, changing the payload the frontend receives on the two paths it actually
  calls. A route walk confirms **zero collisions today** — which is the point: the doubling is
  what prevents them. Choosing a canonical implementation per path is a product decision.

- **FS-259b · Give the contract job real dependencies** · M
  Redis landed 2026-08-01 and recovered ~14 operations (368-370 → 383). Two dependencies remain,
  and **both are blocked by the same GitHub limitation**: a service container accepts
  `image`/`env`/`ports`/`options` and **no `command`**.
  - Redpanda needs `redpanda start --advertise-kafka-addr`. Without it the client connects to
    bootstrap, is redirected to an address it cannot resolve, and hangs — the app then never
    serves `/openapi.json` inside the suite's 120s window and the run collects **1 operation
    instead of 452**. Observed, not predicted. With it, the app starts in 3.3s and conformance
    reaches 387.
  - Postgres needs `shared_preload_libraries=pg_stat_statements`. Migration 004 creates the
    extension but stats collection needs the preload, which is why the **six**
    `/admin/query-performance/*` operations 503.
  *Done when:* both run as `docker run` steps, the suite still collects ~452, and the floor is
  raised **from CI's own measurement** rather than a workstation's.

- **FS-272 · The residual contract 500s** · M — *rescoped from eight batches to one*
  The previous plan allocated **FS-272…279, eight sprints**, to "~92 remaining operations…
  per-endpoint input validation". Measured 2026-08-01 against a throwaway database: with
  dependencies reachable there are **65 failing operations, of which 42 are the documented
  policy disagreements** (`AcceptedNegativeData` 28, `UnsupportedMethodResponse` 14 — both
  re-audited that day, characterisation holds) and only **9 `ServerError`s are in lane**. Six
  of those nine are FS-259b's `pg_stat_statements`. What is left for this sprint:
  `/edge/enroll`, `/sso/login/callback`, and `POST /fleet/releases` (500 because
  `OTA_SIGNING_PRIVATE_KEY_PATH` is unset and `sign_bundle` cannot load a key).

- **FS-358 · `/api/v1/gdpr/data-delete` is probed by nothing** · S
  `test_write_endpoints_reject_cleanly_realdb.py:78` lists it in `SKIP_EXACT`: it takes no path
  parameter and erases the caller's data, so every walk skips it. That is the correct decision
  for a walk and the wrong outcome for coverage — a destructive, unprobed endpoint.
  *Done when:* it has a dedicated test with a disposable tenant, and the skip cites that test.

---

# Wave H — Verification (FS-286…291, FS-303 … FS-307, FS-359 … FS-365)

### The guards for classes already found by hand

- **FS-304 · A declared media type must match what the handler returns** · M
  **No guard exists**, and both directions have already shipped: five routes streamed a
  `FileResponse` while the schema promised JSON (`/compliance/reports/{id}/download`, its
  signed twin, `/exports/deliveries/{id}/download`, `/fleet/releases/{id}/bundle`,
  `/models/{id}/download`), and `/exports/jobs/{job_id}` declared `text/csv` while serving JSON.
  The second fooled the coverage ratchet's own `_serves_a_binary`.
  *Done when:* a sweep pairs each route's declared content type against whether its handler
  returns a `Response` subclass, mutation-verified both ways.

- **FS-305 · Extend the returned-keys sweep to helper-built returns** · M
  `test_response_models_match_their_returns.py` compares a model's fields to the keys of every
  **literal dict** a handler returns. `fleet_logistics` proved the cost of that blind spot: all
  23 of its handlers return `[_shaper(x) for x in …]`, so the sweep passed the entire file
  while checking nothing in it. Six shaper-level assertions were added by hand;
  the general version does not exist.

- **FS-303 · A model's field types must accept what the handler produces** · M
  Currently hand-written per model (`test_declared_models_do_not_drop_fields.py:172`). Both 500s
  that FS-284b caught were **type** mismatches with correct field names — a float band bound
  declared `int`, a numeric priority declared `str` — so the AST sweep passed them and the unit
  guards agreed with the wrong assumption.

- **FS-307 · Run the contract gate as a non-superuser** · S
  The job connects as the database superuser, and **a superuser bypasses RLS even where FORCE
  ROW LEVEL SECURITY is set**. So every tenant-isolation policy is inert for the suite's
  duration: the gate cannot catch a contract failure that only appears under RLS, and its
  results must not be read as statements about isolation. `conftest.py` already does this
  correctly for the real-DB suite by creating a `NOSUPERUSER NOBYPASSRLS` role. **Expect
  conformance to drop** when it lands; that needs a deliberate re-baseline, which is a
  different act from lowering a floor to make a build pass.

### Code that ships and nothing exercises

~3,640 lines of wired service code have **zero** references anywhere in `backend/tests/`.

- **FS-359 · `correlation_registry_integration.py`** · L — 1,065 lines, four app importers.
- **FS-360 · `yard_management.py`** · M — 749 lines, backs a live API surface.
- **FS-361 · The document-intake cluster** · L — `pdf_parser` (188), `docx_parser` (175),
  `image_text_extractor` (161), `document_store` (187), `rag_chunker` (152), `rag_ingestion`
  (534). **1,397 lines, the entire file-ingest path, untested end to end.**

### Tests that pass without running

- **FS-362 · Seven ERP suites skip silently** · M
  `test_erp_{odoo_integration,sync_e2e_realdb,dynamics_sandbox,platform_integration_realdb,
  intuit_sandbox,sap_sandbox}` and `rag_eval/test_robustness` all `pytestmark`-skip when
  credentials are absent. Rule 49 in the sweeps doc is literally *"a suite that skipped is not a
  suite that passed"*, and the RLS guard already recorded the near miss:
  *"'25 passed' would have confirmed the migration against tests that never ran the code it can
  break."*
  *Done when:* a skipped ERP suite is visible in CI output as a skip with a reason, and the
  count of skipped suites is itself asserted so it cannot grow silently.

- **FS-363 · Give the known-failure allowlists an expiry** · M
  Ten endpoints are permitted to 5xx — six GET (`test_realdb_endpoint_smoke.py:37`) and four
  write (`test_write_endpoints_reject_cleanly_realdb.py:45`). `test_quarantine.py` already
  solved this shape for skipped tests: owner, diagnosis, expiry date, and a check that fails
  both when a window lapses and when an entry starts passing. Apply the same register.

### Frontend and end-to-end

- **FS-286 … FS-291 · Real-mode client tests, rescoped** · M each — pool #46
  `test/setup.ts:9` stubs `VITE_USE_MOCK='true'` for the whole unit suite, so every test that
  does not opt into `src/test/realMode.ts` asserts the mock branch. **8 of 20 clients now have
  a `.realmode.test.ts`** (was 4). The 12 without include `analysisSessions.ts` — 477 lines,
  17 `USE_MOCK` forks, 30 endpoints — plus `fleetHealth`, `engines`, `telemetry`, `kpi`,
  `dashboardAnalytics`, `fleetTracker`, `alarmRules`, `rul`, `historian`, `twinOptimizer`,
  `userContext`.

- **FS-364 · Eight routed pages with no test at all** · L
  `CorrelationAIPane` (863 lines, `/nlp`), `Fleet` (574), `IntakeInbox` (387), `ErrorTriage`
  (371), `Historian` (309), `FleetRolloutDetail` (268), `Kanban` (255). The directories
  `components/kanban/` (7 files, ~1,700 lines) and `components/nlp/` (9 files, ~2,400 lines)
  have **no tests whatsoever**.

- **FS-365 · The E2E suite covers four routes** · L
  `authenticated.spec.ts` is `test.skip(!LIVE)` and runs only in one job; it covers `/`,
  `/assets`, `/alarms`, `/login`. Nothing E2E touches Kanban, NLP, intake, ERP, yard,
  transportation, OEE, engines, compliance, historian or admin. Two structural problems beside
  the coverage:
  - `frontend/e2e/compliance-assistant.visual.ts` is **not collected** — `playwright.config.ts:6`
    matches `.spec.ts`, so a visual test exists and never runs.
  - `nightly-e2e.yml` is named "Nightly real-mode e2e" and **starts no browser**: it is a Python
    `urllib` script hitting five endpoints for `status == 200`. It is also cron-only, so it
    gates nothing.

---

# Wave I — Product capability (FS-241…250, FS-285, FS-366 … FS-368)

- **FS-366 · The Decision History panel is built on seven fields the API never sends** · M
  The sharpest of the declared-but-unsent findings, because unlike the known
  `Alarm.createdAt` case **it is actively rendered**. `types/engine.ts:22-49` declares `status`
  (required), `createdAt` (required), `approvedAt`, `approvedBy`, `rejectedAt`, `rejectedBy`,
  `rejectionReason`, `assetName`. `engines.py:35-44` declares nine fields and none of those
  eight. So in `StrategicEngine.tsx`: `historyRecs` (54-55) is **always empty**, the Approved
  counter (100) and Rejected counter (116) are **always 0**, and the history table's status
  badge and timestamp (215-229) never render.

  `strategic_engine.py:200,227` **does** produce `approved_at`/`rejected_at` — they die at the
  response-model boundary. This is a serialization gap, not a missing feature.

  The existing wire-fields sweep misses it by the documented Rule-34 blind spot: it credits a
  field whose name appears anywhere in the global vocabulary, and `approved_at` /
  `rejection_reason` exist on `kanban.py` and `compliance_reports.py`.

- **FS-367 · Six more fields and a whole interface with no producer** · S
  `TacticalEngineStatus.{lastInferenceAt, averageLatencyMs, totalInferences}` and
  `MLOpsStatus.{lastPollAt, lastDeploymentAt, deploymentHistory}` plus the entire
  `ModelDeployment` interface (`types/engine.ts:56-66`). Grep for those names across
  `backend/app` returns **zero hits**; the only populator is `mockApi.ts`. The sweep skips them
  because no component currently reads them — they are live traps for the next page.

- **FS-368 · The "live" fleet map is a poll against endpoints that do not exist** · M
  `geofencing.subscribeToAlerts` polls every 15s and `fleetTracker.subscribeToUpdates` every
  30s, because `/ws/geofencing` and `/ws/fleet-tracking` are not registered — only `/ws` is.
  Both files record this honestly in comments. Geofence events are still not published on the
  authenticated `/ws` stream.

Carried unchanged from the previous plan, still verified as open: **FS-241** (document metadata
record · L · ⚠ htreinen — unblocks 242/284/328/329), **FS-243** (async ingestion · L · ⚠),
**FS-244** (streaming answers — `stream_generate()` exists and no route uses it · M),
**FS-245** (answer feedback loop · M), **FS-247** (ERP export definition · M), **FS-249/250**
(Dataverse and Odoo PO transformers · M each — **do not reuse the SAP transformer**; it reads
SAP field names and would produce empty records and a confident report of zero anomalies),
**FS-285** (export delivery failure surfacing · M).

---

# Wave J — Production readiness (FS-369 … FS-376)

- **FS-369 · Point-in-time recovery does not exist** · L
  `infrastructure/k8s/legacy-patroni/` holds the pgBackRest CronJob and is in **no
  kustomization and no apply step**. What runs instead is `base/db-backup-cronjob.yaml`, a
  logical `pg_dump -Fc` — so the real RPO is **up to 24 hours**, not the continuous archive the
  DR overlay's RTO/RPO language implies. `infrastructure/k8s/README.md:16-25` states the
  blocker: restoring PITR needs a database image shipping `pgbackrest` (`timescaledb-ha`) plus
  an `archive_command`, and the current image has neither.

- **FS-370 · The HA and autoscaling stacks are conditionally skipped** · M
  `ci-cd.yml:408-427` (staging) and `:515-534` (production) gate each apply on the operator's
  CRDs and print `SKIP` otherwise. Correct behaviour — and it means that unless an operator was
  installed out of band, `base/` runs a **single** TimescaleDB pod ("a node/disk loss is a full
  outage") and the four workers stay at `replicas: 1`.
  *Done when:* the operator install is part of the documented path, or the skip is loud enough
  that nobody believes they have HA when they do not.

- **FS-371 · Nothing reaps testcontainers** · S
  `conftest.py` disables Ryuk because it bind-mounts the Docker socket and colima refuses the
  mount — the right trade (silently skipping the DB half of the suite is the worse failure),
  and its own comment calls the cleanup "a chore". Measured 2026-08-01: **23 stopped containers
  holding 13 GB**, four of them `timescaledb` from contract-gate runs. This also **un-gates
  FS-293**, which is blocked on ~5 GB of Docker disk: the VM is at 96% with 2.5 GB free, and
  `docker container prune` recovers 13 GB without touching a single image.

- **FS-372 · `pre-commit` is the only wholesale advisory job** · S — needs FS-280
  `quality-gates.yml:1028`, `continue-on-error: true`. Its content overlaps
  `.pre-commit-config.yaml`, so **nothing enforces those hooks on any branch**. Blocked behind
  FS-280 (the two unfixable `ruff` errors) and, for the formatting half, the coordinated
  reformat of FS-326 — `black`/`isort` are advisory in `ci-cd.yml:96-97` against a written,
  quantified blocker (159 of 184 files predate black).

- **FS-373 · No latency SLO gate anywhere** · M
  `load-test` blocks on error rate but explicitly **not** on the script's own p95 latency SLOs,
  and CI overrides the 29-minute/1000-VU profile with 5 VUs for 30s. `infra/prometheus/slo_rules.yml`
  exists and is wired into `monitoring/`, so the SLOs are defined and unenforced. Related:
  `profiling.py:66-69` records its 1000 ms slow-request threshold as *"an UNCONFIRMED
  placeholder pending confirmation from Hamad"* — the same missing number in two places.

- **FS-374 · The ERP sandbox jobs never run on pull requests** · S
  All four are `if: github.event_name == 'push'`, so an ERP connector regression lands on `main`
  before anything vendor-facing runs. Cheap to change; the cost is sandbox rate limits, which
  is the trade to state explicitly rather than leave implicit.

- **FS-375 · Every secret is provisioned by hand** · M
  `infrastructure/k8s/secrets/README.md` lists nine required Secrets. Neither `sealed-secrets/`
  nor `external-secrets/` is applied by any workflow — `secretstore.example.yaml` is an example
  and `seal.sh` is a manual script. The README's own warning for `backup-credentials`:
  *"WITHOUT THIS THERE ARE NO BACKUPS — the CronJob will fail every night."*

- **FS-376 · The README contradicts the manifests on worker storage** · S
  `infrastructure/k8s/README.md` says in one place that exports go to SeaweedFS and in another
  that the export/compliance workers write to an `emptyDir` and *"production needs a shared RWX
  PVC or object storage"*. The manifests side with SeaweedFS
  (`base/export-worker-deployment.yaml:70-73` sets `EXPORT_USE_S3`; the emptyDir is scratch, per
  its inline comment). The stale paragraph is the one an operator reads.

---

# Decisions, not sprints

These need a person, not a session. Listed so they are not mistaken for work.

| # | Decision |
|---|---|
| **FS-252** | Adopt the generated SDK, or delete it. Premise corrected 2026-08-01: it is **not** committed, so it cannot drift; the generator **works** (375 paths → 2.3 MB in ~0.5s). Still zero importers. |
| **FS-317** | ERP → Kafka. **1,997 of the 7,726 unreachable lines** are the five `erp_middleware` transports blocked on this one call. |
| **FS-377** | The slow-request threshold. `profiling.py:66-69` says the 1000 ms default is unconfirmed and names Hamad; no HTTP latency SLA exists to ground it. Pairs with FS-373. |
| FS-312 ⚠ Harsh | Correlation-AI honesty decision. |
| FS-308/309/310 | The eight stale branches, `node_modules` in four of them, and the `main` promotion window. |
| FS-315 · FS-320 · FS-322 | i18n scope · dependency review · ownership-table rebalance. |
| FS-326 | The `pre-commit` freeze window — the reformat touches every lane at once and all outstanding branches would rebase through it. |

# Still genuinely blocked

- **Needs a second cluster** — FS-296, FS-297, FS-298, FS-324, FS-325. The DR overlay's own
  header: *"UNVERIFIED AGAINST A REAL CLUSTER. There is no second cluster to try it on."*
- **Needs external access** — FS-269, FS-270, FS-300. Note on the first two: the SAP, Intuit
  and Dataverse credentials were shared in conversation, and `HAMAD_IDE.pem` **is still in git
  history on both remotes**. Untracking a file does not revoke a key.
- ~~Needs disk — FS-293~~. **Un-gated by FS-371**: 13 GB is recoverable from stopped
  containers alone.

---

# Sequencing

```
FS-259b ──▶ FS-272            (six of the nine 500s are the missing preload)
FS-259b ──▶ FS-307 ──▶ re-baseline the floor from CI
FS-241  ──▶ FS-242, FS-284, FS-328, FS-329
FS-311  ──▶ FS-327, FS-342, and unblocks FS-355's alternative route
FS-371  ──▶ FS-293            (prune, then the 5 GB is available)
FS-280  ──▶ FS-372 ──▶ FS-326
FS-244  ──▶ FS-330
FS-304, FS-305 ──▶ any further response_model work in other lanes
```

# What is realistically executable alone

Waves F, H and J are almost entirely unblocked: **28 of the 50** need no other person. Wave G
has three ⚠ items and one that needs a design decision first (FS-353). Wave I is the most
dependent — five of its ten need FS-241 or another lane's owner.

The honest count: **28 executable now, 12 soft-gated on an owner's agreement, 10 gated on a
decision, a cluster, or a credential.**
