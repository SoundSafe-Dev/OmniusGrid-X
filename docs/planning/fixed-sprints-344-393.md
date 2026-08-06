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

## Verification pass, 2026-08-06 — nine entries were already delivered

**This plan now overstates what is left, in the same direction as the one it replaced.** Its
own header says to verify a premise before starting and to correct the entry in place with the
date. This is that correction, taken from the codebase rather than from this document.

Every FS-344…393 item was checked against the code it cites. Eight no longer reproduce, and a ninth is below the table:

| item | claim | what is actually there |
|---|---|---|
| FS-266 | `DELETE /rag/documents/{doc_id}` has no org filter | org-scoped from the token via `_org_id(current_user)`, and documented in the handler |
| FS-272 | residual contract `ServerError`s | `tests/_lane_failures.py` is **empty** — `GET_FAILURES` and `WRITE_FAILURES` are both `{}` |
| FS-345 | a simulated position is indistinguishable from a fix | `get_device_location` sets `invented = True` where it fabricates and stamps from that variable |
| FS-350 | demo recommendations loaded into the live queue | gated on `ALLOW_DEV_TOKEN`, seeds only when the queue is empty, and carries `simulation_basis` provenance since FS-434 |
| FS-354 | `kanban.py` and `nlp_correlation.py` on `get_db` over FORCE-RLS tables | both at zero. The one `Depends(get_db)` string left in `kanban.py` is inside a comment explaining its removal |
| FS-357 | twelve paths at `/api/v1/logistics/logistics/…` | closed by FS-468: `fleet_logistics` is canonical, the correlation variants moved under `/correlation/`, and a guard fails any route that repeats a segment |
| FS-359 | `correlation_registry_integration.py` has zero test references | `test_correlation_registry_integration.py`, 30 tests |
| FS-361 | the document-intake cluster is untested end to end | `test_document_intake_parsers.py` and siblings, from FS-440/441 |

**FS-355 makes nine, and I missed it on the first pass.** The entry reads "`error_events`
carries `organization_id` and **no RLS policy**", sized L on a primary-key grain change. The
absence of a policy is real. It is also **deliberate, evidenced, and already argued through**:

* `error_events` is keyed on `fingerprint` alone by design — one row per distinct error for
  the whole platform — so it is a cross-tenant triage view on purpose;
* the disclosure risk was found, reproduced against a real database, and fixed by redaction:
  `_visible_sample` withholds another tenant's `message_sample` and `traceback_sample` while
  leaving the payload-free triage metadata visible;
* the write side 403s when the row's owner is not the caller;
* and `test_error_triage_sample_redaction_realdb.py` records **why scoping the view by
  organisation was rejected** — a shared row's `organization_id` names only one of the
  tenants that hit the bug, so filtering on it would hide errors that genuinely are the
  caller's.

Adding RLS would not harden that table; it would break the view it is supposed to be. What
remains is the question FS-311 already carries — there is no platform-admin role, so tenant
admins are performing platform triage — and that is a decision, not an L-sized migration.

**How I missed it.** The first pass checked whether an RLS policy exists (it does not) and
stopped. It did not ask whether one was *wanted*. That is the same error as FS-460: asserting
something from one direction without checking the other. **Absence is not evidence of a gap
until you have checked whether the absence is deliberate** — and here the reasoning was
sitting in a test docstring, one grep away.

**FS-368 is half true and worth splitting.** The defect — a WebSocket opened to
`/ws/fleet-tracking`, a route that does not exist, so the live map silently froze — is fixed;
both clients poll now and say so in a comment. The *capability* (real push through the
authenticated `/ws` stream) is untouched, and that is a feature rather than a bug.

### What is still open, verified 2026-08-06

`FS-344` (`GEOTAB_SIMULATED` defaults `True`; a production validator flags it, so the
question is whether one validator is enough) · `FS-307` (the contract gate still runs as superuser) · `FS-362` (ERP suites still
skip without credentials) · `FS-364` (routed pages with no test) · `FS-369`…`FS-376` (the
production-readiness wave: PITR, HA/autoscaling wiring, the advisory `pre-commit` job, the
missing latency SLO gate, hand-provisioned secrets, the README/manifest contradiction).

**Why this keeps happening**, since it is the second plan in a row to overstate: both were
written as inventories and then *not* re-derived, while the work carried on against the
codebase. A plan is a snapshot of a belief about a repository, and the repository does not
update it. The delivery log and the defect-class sweeps are written as things happen and have
not drifted; this document is written in advance and has, twice.

---

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
  `transportation_management.py:267-285`. Duration is `total_distance / 50`; fuel is
  `gallons * 3.50`; tolls are `distance * 0.05`. Arguably worse than randomness, because
  deterministic output reads as computed.
  ✅ **DONE 2026-08-01.** The four literals are now settings
  (`FLEET_AVERAGE_SPEED_MPH`, `FLEET_STOP_MINUTES`, `FLEET_AVERAGE_MPG`,
  `FUEL_PRICE_USD_PER_GALLON`, `TOLL_COST_USD_PER_MILE`) and `optimize_route` returns the
  `assumptions` it used beside the figures.

  **The item's premise was half wrong, in the code's favour.** It said "distance is
  estimated" — `_estimate_distance` in fact delegates to `app.services.routing`, which does
  real haversine or OSRM road distance. Only the three *derived* figures were invented, and
  the distance's provenance is now reported separately so the fix does not tar it with them.

  Why it mattered more than it looked: `create_route` **persists** all three onto
  `routes.estimated_duration_hours` / `.fuel_cost_estimate` / `.toll_cost_estimate`, which
  `GET /transportation/routes` then serves — so a national fuel average from an unrecorded
  date became a stored per-route cost. Two independent guards: behavioural (each figure must
  move when its setting moves) and an AST sweep that fails if a numeric literal returns to
  the costing arithmetic, since the behavioural ones assert *direction* and a literal keeps
  the direction right for the default configuration.

- **FS-349 · `model_version = "gemma-4-placeholder"` ships in analysis payloads** · S · ⚠ Harsh
  ~~There is no gemma-4… the standard the version string does not meet.~~
  **PREMISE CORRECTED 2026-08-01 — NOT A DEFECT. Closed without a code change.**

  `_model_version` has exactly three sites: set in `__init__` (43), emitted once (239),
  overwritten with the real `f"{CORRELATION_BASE_MODEL}+lora"` when a model loads (294). The
  single emission is **inside `_simulate_analysis`**, whose payload already carries
  `simulated: True`, a `simulation_reason` and a lowered confidence of 0.4 — deliberately not
  the 0.85 the real inference path reports. That is precisely the standard FS-267 applied to
  GeoTab, and this path already met it. The string also contains the word *placeholder*.

  Checked the obvious escape route too: `engines.py:59` reports
  `tactical_engine.model_version`, a different object, so the correlation placeholder does
  not leak through the status endpoint.

  **Residual, for the owner rather than for a sprint:** naming a model family that does not
  exist is mildly confusing even inside a labelled payload — `"unloaded"` would say the same
  thing without implying gemma-4 was ever the plan. One line in `correlation_ai_engine.py`,
  which is Harsh's lane, and not worth a cross-lane change on its own.

  **Fourth premise in this document to fail on its first day** (FS-344, FS-352, FS-350,
  FS-349) — all four from evidence that was right about the line it read and silent about its
  context.

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
  `correlation_registry_integration.py:1049-1050`, on a path that classifies
  `severity: "critical"` when `risk_score > 75`.
  ✅ **DONE 2026-08-01.** Now dispatched through `notification_service.dispatch`, which
  already existed and already loads the tenant's subscription rules, delivers, records the
  deliveries and pushes failures into error-triage.

  **The item understated it.** The function did not merely log — it returned
  `f"alert-{now:%Y%m%d%H%M%S}"`, and that identifier went into `result["alerts"]`, which
  `process_correlation_analysis` returns. Callers received alert *references* for alerts that
  were never sent. That is the class `test_reporting_honesty.py` exists for, and its static
  scan missed this one because the function claims no count and logs no `*_created` event —
  it invents a **reference**, which is a different tell worth adding to that scan (see
  FS-305's neighbourhood).

  Three outcomes are pinned, because only the first is an alert: delivered → an identifier;
  **no subscribers → `None`** (an empty delivery list is legitimate, and returning an id for
  it would restore the lie in a quieter form); dispatch raised → `None`, error-triage, and
  the already-committed correlation survives rather than being discarded over an
  undeliverable email.

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
  ~~`integration_configurations` has FORCE RLS and the candidate lookup returns nothing…
  **Needs a design decision**.~~
  **PREMISE CORRECTED 2026-08-01 — ALREADY FIXED. Closed without a code change.**

  The design decision was taken and implemented: **migration 052** adds
  `webhook_tenant_resolution` — SELECT only, active ERP rows only, and only while
  `app.erp_webhook_lookup = 'on'`, a GUC the handler sets transaction-locally immediately
  before the candidate query and clears in a `finally`, so it is off for the event INSERT and
  every other path. Guarded by `test_erp_webhook_tenant_resolution_realdb.py` — 12 tests,
  including that the flag permits no writes, hides dormant and non-ERP rows, and that nothing
  is visible without it.

  **The stale claim was inside a guard's own comment**, `test_tenant_session_guard.py:113-121`,
  which still read "It is nonetheless BROKEN" while citing
  `defect-class-sweeps.md` — a document that already said "Fixed by migration 052". So the
  guard contradicted the doc it pointed at, and a reader trusting the guard would re-plan
  finished work. Corrected in place. **Guard prose is documentation and goes stale like any
  other** — a lesson worth more than the item, because guard comments are exactly what I have
  been treating as ground truth.

  Fifth premise in this plan to fail on its first day.

- **FS-354 · `kanban.py` and `nlp_correlation.py` on `get_db` over FORCE-RLS tables** · M · ⚠ Harsh
  17 sites (10 + 7), pinned in `KNOWN_GET_DB_ON_RLS`. **Premise verified 2026-08-01 — the
  counts are exact and current** (health 3, kanban 10, nlp_correlation 7), unlike FS-353's.
  **HANDED OVER, not attempted** — Harsh's lane.

  The item said "four of the ten known 5xx entries trace to it". Measured: **five**, and they
  share a much narrower shape than "17 `get_db` sites" —

      GET  /kanban/board · /kanban/metrics · /kanban/workload
      POST /kanban/board/view
      POST /engines/correlation/integration/initialize-registries

  all five are **write-on-read**: a GET that lazily creates a default row on a session with no
  tenant GUC, so the policy's WITH CHECK rejects the INSERT and the read 500s. Under RLS a
  read fails silently and a write fails loudly — which is why these are the ones that
  surfaced, and a reminder that the quiet ones are still quiet.

  The other five known failures would **survive a dependency swap**: `/kanban/rules/premade`
  (non-UUID template ids), `/nlp/correlation/intake/{id}` (`select()` given a class),
  `/engines/correlation/generate` (500 on an empty body), and two `/rag/documents` entries
  (SeaweedFS). So the loud half is **two code paths, not seventeen**. Written into the guard
  where its owner will look.

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
  `/api/v1/rul` was fixed.
  ✅ **DONE 2026-08-01 — as a ratchet, and the item's own framing was wrong.**

  I wrote "this is applying an existing utility, not designing one". That misses the reason
  the eleven were left, which the sweep states plainly: **a header no client reads is a
  caveat sent and dropped** — a second instance of a different defect, not half a fix. Each
  needs its consumer wired in the same change. Verified on the best candidate:
  `/api/v1/health-index` is the analogue of `/rul` (and worse — it has no `order_by` at all,
  so its cap takes an arbitrary 100 assets), and it has **no frontend consumer**, so a header
  there today would be exactly that defect.

  So the deliverable is `test_capped_lists_cannot_grow.py`, pinning the population at 12.
  **It is already 12, not the 11 the sweep left** — one arrived in the interval, which is
  what a recorded-not-fixed list does with nothing holding it in place.

  Reproducing the count required getting the filter right: 45 GETs take a `limit`, but most
  return an envelope with a `total`, and **a total is a truncation signal**. Only a bare array
  leaves the caller with nothing. Split: 7 mine (commands, geofencing/alerts, health-index,
  notifications/log, registries ×3), 5 other lanes (analysis_sessions ×3, kanban ×2).

  Mutation-verified in both directions, and the first attempt was too weak to count:
  neutralising `mark_truncated` alone left `X-Result-Truncated` in the same handler, so the
  detector rightly still saw a signal. Removing both takes it to 13.

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

  **HANDED OVER 2026-08-01.** Three of these twelve also 500 under the contract gate with all
  dependencies reachable — `truck-asset-readiness`, `load-quality`, `optimize-assignment` —
  so the file has live defects independent of the prefix question. Both are Harsh's.

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
  ◑ **BROKER DONE 2026-08-01; `pg_stat_statements` deferred deliberately.**

  The broker runs as a `docker run` step with `--advertise-kafka-addr PLAINTEXT://127.0.0.1`,
  and the step is **fail-safe by design**, because an absent broker is harmless and a
  half-working one is not: the app starts in ~2.6s with no broker at all (503s on the
  broker-backed endpoints — this job's behaviour until today) and ~3.3s with a correct one,
  and the dangerous state is in between. So the advertised address is verified from the
  runner, and if anything is wrong the container is **removed**, leaving the job in its old
  known-good shape rather than the hanging one.

  Both paths were run verbatim on a workstation — the step extracted from the YAML with
  `yaml.safe_load` and executed — because the workflow itself cannot be tested from here.
  Success reports "usable"; substituting an image that can never advertise correctly prints
  the explanation, removes the container and exits 0.

  **`pg_stat_statements` is left**, and it is the six `/admin/query-performance/*` operations.
  It needs the postgres *service* replaced by a `docker run` for exactly the same
  no-`command` reason — but a postgres that fails to start **collapses the whole suite**,
  where a broker that fails to start merely degrades it to 503s. That is a materially
  different risk on a blocking job and wants a real run to watch. **The floor stays at 360**
  regardless: it should move on CI's measurement, not a workstation's.

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
  ✅ **DONE 2026-08-01.** `test_gdpr_data_delete_realdb.py` mints a **disposable user per
  case** and spends it — the arrangement a walk cannot have, since a walk authenticates once
  and reuses the session. The skip now cites the file, so the reason and its remedy sit
  together.

  Six cases: the confirmation guard (absent, wrong case, anonymous caller), the erasure
  itself, deactivation, and that erasing one user leaves another in the same organisation
  intact — the endpoint takes no identifier, so the subject is entirely implicit, which is
  the shape that erases the wrong person if a session is misread.

  Worth recording: the handler **anonymises rather than hard-deletes**, and that is right
  against a schema with foreign keys into `users` — a hard delete would cascade into audit
  history or fail on a constraint. The tests assert the identity is gone, not the row.
  Mutation-verified: relaxing the guard to `confirmation.upper()` fails the case-exactness
  case.

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

---

# Appendix — QA sweep against a running stack, 2026-08-01

Method: real backend (SQLite dev path, the one `make seed-demo` produces) + real Vite dev
server with `VITE_USE_MOCK=false`. Three passes: 33 routed pages mounted; 253 GET operations
called; every non-destructive control on every page clicked (one skipped by name —
`STOP NOW` on `/assets/:id`; two pages capped at 14 of 15 controls).

**A caveat about the first pass, because it matters for anyone repeating this.** The page
sweep recorded failed requests from Playwright's `response` event and reported "no 4xx/5xx
anywhere". That was not evidence: a response the browser rejects for CORS never fires that
event, so FS-378 was hiding every unhandled 500 from the sweep that found it. The one 500
present was visible only in the console log. **Read the console, not just the network tape.**

## Fixed here

| | |
|---|---|
| **FS-378** | Unhandled 500s reached the browser with no CORS header, so they surfaced as `Network Error` with no status and no trace id — the exact class error triage exists for |
| **FS-380** | `_check_ingestion` assumed a `datetime`; aiosqlite returns a string, so the documented dev path reported a working database as a subsystem in error |
| **FS-381** | `/admin/system/status` 500'd on SQLite — `pg_database_size` called with no dialect guard, taking the page down over one optional figure |
| **FS-382** | The CI-gate counter read a fail-safe *step* as an advisory *job*; the README's 30/2 was read off that bug. Real: 31 blocking, 1 advisory |
| **FS-379** | Approve/Reject on `/engines/strategic` sent `operator_id` in the body where the server declares a query param — 422 every time, never worked once |

## Handed over — cross-lane, all reproduced against the running stack

| Endpoint / page | Cause | Lane |
|---|---|---|
| `GET /api/v1/nlp/sessions/{id}/data` | `DataSourceResponse.source_id` is declared `UUID`; real data holds `'yard'`. The response model rejects its own handler's output — **FS-303's class exactly** | ⚠ Harsh |
| `GET /api/v1/nlp/sessions/{id}/context/registries` | `'ActionableRegistryItem' object has no attribute 'title'` | ⚠ Harsh |
| `GET /api/v1/nlp/correlation/intake/{id}` | SQLAlchemy misuse — the `IntakeItem` *class* passed where a column expression is expected | ⚠ Harsh |
| `GET /api/v1/kanban/rules/premade` | 50 validation errors: premade rule ids are not UUIDs. **Not environmental** — this fails on Postgres too, the ids are static | ⚠ kanban owner |
| `GET /api/v1/rag/documents`, `POST /api/v1/rag/query` | Storage/vector backends unreachable (`seaweedfs:8333`, DNS). Environmental **but returns 500 where every Redis-backed endpoint returns 503** — an unreachable dependency is not a server defect, and the status should say so | ⚠ htreinen |

## Two more, both since fixed — and one was filed too low

I first recorded these as "neither worth a sprint on its own". That was right about the
second and **wrong about the first**, which is worth keeping as a note on how the triage
went astray: I classified it from the React warning text rather than from the behaviour.

| | |
|---|---|
| **FS-383** | `StatCard` in `TransportationManagement.tsx` (×9) and `YardManagement.tsx` (×8) is used under `<TooltipTrigger asChild>` and was not a `forwardRef`. Filed as "React warns on both pages" — a cosmetic reading. Radix's Slot clones the child to merge in a ref **and its own event handlers**, and a plain function component drops both. Measured by hovering "Total Shipments": `role="tooltip"` 0 → 1, Radix popper 0 → 1. **All seventeen tooltips were dead.** A repo-wide sweep now enforces the shape; no other offenders exist today |
| **FS-384** | `getWsUrl()`'s dev branch hardcoded `:8000` and ignored `VITE_API_URL`, so moving the API port left the socket retrying forever while every HTTP call succeeded. `VITE_WS_URL` still wins; an unparseable value falls back rather than throwing at module load. Production (same-origin, `wss:` on https) was already correct and is untouched |

**The lesson worth carrying:** a React console warning describes the symptom the framework
can see, not the one the user gets. "Function components cannot be given refs" says nothing
about the handlers going the same way, and the handlers were the whole feature. Hover the
thing before deciding it is cosmetic.

## Then, following the same thread into the deployment (2026-08-01, later)

| | |
|---|---|
| **FS-385** | **Every overlay shipped an admin-auth bypass.** `ALLOW_DEV_TOKEN` and `ALLOW_OPEN_REGISTRATION` default to **true** in `config.py` (so a laptop demo works offline) and no manifest overrode them — so a deployed backend accepted the literal string `dev-token` as an admin credential and took unauthenticated registrations, alongside `DEBUG=true`, wildcard CORS and `GEOTAB_SIMULATED=true`. `validate_settings()` hard-fails on exactly this, but every check sits inside `if ENVIRONMENT == "production"` and **ENVIRONMENT appeared in no manifest at all**: `kustomize build overlays/production \| grep -c ENVIRONMENT` → `0`. A real guard nothing had ever armed |
| **FS-386** | All three overlays declared a `backend-config` ConfigMap and **nothing consumed it** — no `envFrom` existed anywhere. So `LOG_LEVEL=warn` (production), `MTLS_ENABLED=false` (staging) and `DEPLOYMENT_SITE=dr` were rendered and ignored: staging ran with mTLS **on**, and DR logs went unlabelled through the failover the label exists for |
| **FS-376** | The k8s README's storage "known gap" described the state before the remedy it asks for was implemented. Verified against the manifests: all three workloads set `EXPORT_USE_S3=true` |
| **FS-304 / FS-387** | A media-type sweep now exists. It found `/exports/telemetry/{asset_id}` declaring only `200: text/csv` while returning **`202 application/json`** above `SYNC_ROW_CAP` — the JSON arriving on exactly the large exports most likely to need job-polling, against a schema this repo generates an SDK from |

**Arming a guard means satisfying it.** Setting `ENVIRONMENT=production` made `validate_settings()`
demand five more things. Without wiring those, the commit would have traded a silent insecure
deploy for a CrashLoopBackOff — so `CORS_ALLOW_ORIGINS` and `EDGE_REQUIRE_PROOF_OF_POSSESSION`
joined the ConfigMap and three secrets moved to a new `app-secrets`. Verified by extracting the
rendered production env and running the validator against it: zero problems.

**Two traversal mistakes, both of which produced a confident "0 problems" from a sweep examining
almost nothing** — worth recording because they are the same shape and neither was obvious:

- `app.routes` yields **2** APIRoutes; the other 450 sit behind mounted routers and only
  `tests/_route_tree.http_routes` walks them.
- `return FileResponse(...)` appears almost nowhere — responses are helper-built and assigned to
  a variable first, so an `ast.Return`-only walk sees none of them. (The same blind spot FS-305
  records for the returned-keys sweep.)

Earlier in the same session a `git cat-file --batch` pipeline reported **0** blobs containing a
string when the answer was 3. Three times now the tool was broken and the clean result was
believed. **A sweep that finds nothing must prove it can see its subject** — every guard written
today carries a floor test that fails if the traversal stops working.

## The demo and CI paths (2026-08-01, last batch)

| | |
|---|---|
| **FS-388** | **The documented skip-login demo returned 401.** `make demo` and `docs/DEMO.md` both said `VITE_USE_MOCK=false npm run dev` + "login: dev / any password". The bypass has *two* gates — `ALLOW_DEV_TOKEN` (backend) and `VITE_DEV_MODE` (frontend, `Login.tsx` requires `import.meta.env.DEV && VITE_DEV_MODE === 'true'`) — and the instructions named one. Now `make demo-ui`, with a guard that reads the requirement off `Login.tsx` and checks DEMO.md **per line** |
| **FS-389** | `alex` exists on origin and matches **no** `on.push.branches` pattern, so that branch runs **zero** push CI |
| **FS-374** | **Recorded premise was partly wrong.** "ERP regressions land on main before anything vendor-facing runs" — but push covers `hamad/**`, `hridyansh/**`, `feature/**`, `htreinen`, `HARSH-CONTRIBUTION`, so most work *is* checked on branch push. The real hole only appears when combined with FS-389: `alex`'s PR is its only gate, and pull_request was the event the ERP jobs skipped |

**FS-388 is the most instructive of the whole session.** The frontend gate was *tightened* at
some point and that change was correct — `Login.test.tsx` asserts a production bundle cannot
enable the bypass. Nothing connected it to the two places that tell a human how to start the
demo. So a security improvement silently broke the demo, and **neither side could tell**: the
frontend test passed, the backend test passed, and the only thing joining them was prose.
Wherever a security boundary tightens, whatever documents crossing it legitimately has to move
in the same commit or it becomes a lie on a delay.

**An allowlist of personal branch names is the underlying FS-389 problem**, and it has now been
wrong in both directions — the workflow's own comment records `develop` being listed while never
existing; `alex` is the mirror. It fails *silently*: no job reports "this branch has no gates",
the signal is an absence, and nobody reads a workflow file to see whether their branch is in it.

## Verification wave, and three more stale premises (2026-08-01)

| FS | Outcome |
|---|---|
| **FS-366** | **Done.** `0 Approved` was a false claim, not an empty state — see the commit. Cross-lane remainder: `strategic_engine.get_recommendation_history()` exists and no route exposes it |
| **FS-367** | **Done.** Six engine fields removed, plus `ModelDeployment`; `mockApi` had supplied all six |
| **FS-305** | **Done.** Returned-keys sweep follows helper-built returns; 145 → 181 cases, no new mismatches |
| **FS-304** | **Done.** Media-type guard; found the undeclared `202` on `/exports/telemetry/{asset_id}` |
| **FS-363** | **Done.** The ten other-lane 5xx entries now carry owner + precise fix + expiry, in one shared registry read by both walks |
| **FS-368** | **STALE — nothing to do.** Recorded as "`/ws/geofencing` and `/ws/fleet-tracking` do not exist; the live fleet map is not live". Both were already converted from those nonexistent routes to documented polling, and no user-facing text claims "live" for the fleet map — `ConnectionStatus` has distinct `Live` / `Polling` / `Reconnecting…` states and only says `Live` when the socket is up |
| **FS-374** | **Corrected** (previous section): branch pushes already cover most work; the hole was `alex` |

**Three of the five endpoints I "handed over" from the QA sweep were already recorded** in
`KNOWN_LANE_FAILURES` with the same diagnosis — kanban premade ids, the `nlp` intake
`select()`, and `rag/documents` on SeaweedFS. Two were genuinely new:
`/nlp/sessions/{id}/data` and `/context/registries`.

**Why the real-DB walk cannot see those two, and it is worth knowing:**
`/nlp/sessions/{id}/data` 500s because a row carries `source_id='yard'` against a `UUID`
field. The walk's fixture has no such row, so the endpoint answers cleanly there. A sweep
against *seeded demo data* found what a sweep against an *empty fixture* structurally
cannot. Neither harness is wrong; they see different failure classes, and the data-shaped
ones only appear when there is data.

## The yard service — FS-360, and three defects inside it (2026-08-02)

`app/services/yard_management.py` is 749 lines behind a live API surface and had **zero
tests**. Four yard test files existed and none imported it: `test_yard_detention.py` tests
`build_detention_alert` in `app/api/yard.py`, a different function in a different module
that happens to share a subject. That is how it looked covered.

Each part of it had something wrong.

| FS | Defect |
|---|---|
| **FS-391** | Both money calculators compared a stored timestamp against `datetime.now(timezone.utc)`. SQLite cannot preserve tzinfo, so on the documented dev path every value is naive and checking a trailer out raised `TypeError` — failing on the plain `total_wait_minutes` subtraction before the calculators were even reached |
| **FS-392** | `schedule_appointment` accepted a booking whose end precedes its start. Not inert: `_check_conflicts` matches such a row through its "contained by" branch, so a 13:00→08:00 appointment **blocks a legitimate 09:00–10:00 booking** while protecting no real slot. Measured exactly that. Zero-length bookings were accepted too |
| **FS-393** | `getDwellTimes` declared a summary object; the endpoint returns a **list**. So `dwellTimes.trailersExceedingTarget` was `undefined`, `undefined > 0` false, and **the dwell warning banner never rendered in real mode** — while the mock rendered it in development |

**Two things worth carrying beyond this file.**

*Assuming UTC needed an argument, not a default.* Everything writing those columns writes
`datetime.now(timezone.utc)`, so a naive value has already lost a tzinfo that said UTC.
Reading it as local time would shift every detention charge by the host's offset **and pass
a test that only checked it stopped raising** — so there is a test asserting naive and aware
produce the same number.

*A conflict check fails in two directions and only one gets reported.* The overlap
arithmetic was correct, including back-to-back bookings not conflicting. That case is now
pinned, because a check that flags everything produces no bug report — the dock simply looks
permanently full.

**FS-393 is the third instance of one shape today**, after FS-366 and FS-367, and it is the
variant the new phantom-field guard **cannot see**: that sweep reads interface *fields*, and
this was a client function's inline *return type*, agreed with by a mock and nothing else.
Extending it to client return types is the open follow-up.

## README restructure (2026-08-02)

3,428 lines → ~1,790. Two separate Quickstarts merged; the delivery log (1,048 lines), the
ERP architecture reference (387) and the correlation dataset samples (261) moved into
`docs/`; a contents table added.

**The guards caught two real mistakes in the move**, which is the argument for having them:

- `docs/DELIVERY-LOG.md` carried 14 links written relative to the repo root, which resolved
  to `docs/docs/...` once the file lived in `docs/`.
- The README is required to cite the current sweep-rule range, and that sentence left with
  the moved block.

And one that no guard would have caught, so it was handled deliberately:
`test_documented_files_exist.py` is scoped to **top-level documents, not `docs/**`**, so
moving 1,048 lines of file-citing prose into `docs/` would have dropped every one of those
citations from the check **while the file count went up**. The guard's scope moved with the
content. Moving prose out of a checked document moves it out of the check.

## Full-system functional sweep (2026-08-02)

Run against a real stack after a fresh seed: all 253 GET endpoints, and all 33 routes with
every tab on each.

| | Result |
|---|---|
| GET endpoints | **192 × 200**, 14 × 503 (Redis / `pg_stat_statements` absent, expected), 42 × 4xx (unresolved ids, auth-gated), **5 × 500** |
| Remaining 500s | `kanban/rules/premade`, `nlp/correlation/intake/{id}`, `nlp/sessions/{id}/data`, `nlp/.../context/registries`, `rag/documents` — **all cross-lane, all in `tests/_lane_failures.py` with an owner, a fix and an expiry** |
| Frontend | **1 problem across 33 routes and their tabs** — the `/nlp` 500 above surfacing in the UI |
| Blanks / NaN / undefined | **zero** |

**FS-399** (every asset flagged Critical on `/oee`) and **FS-400** (carrier compliance 500)
were found and fixed by this sweep; both are in the commits above.

### Two false leads, and why they mattered

The sweep flagged `/alarms/` and `/yard/dock/appointments` as "200 but empty **while rows
exist for this org**" — which is the exact signature of a broken tenancy filter, and I was
one step from filing two defects against my own lane.

They were stale demo data. `seed_demo_data.py` writes timestamps relative to when it runs,
`GET /alarms/` defaults to the last 24 hours, and the seed was a day old. A fresh seed
returns 4 alarms and 2 appointments. **An empty page on aged demo data is indistinguishable
from a broken filter until you check the seed's age** — now recorded in `docs/DEMO.md`,
because the next person to hit it will reason exactly as I did.

Six pages render thin, and all six are correct: real data (`/analytics/maintenance` shows a
live DOT inspection due in 13 days; `/fleet/organization` shows the real hierarchy) or an
honest, explanatory empty state (`/admin/collectors`: *"Agents appear here once they enroll
and send a heartbeat."*). A count of table rows is not a measure of function — three of the
six render cards, not tables.

## Write paths, and the guards that now cover them (2026-08-02)

Reads had been swept exhaustively; **writes had barely been touched**. A live sweep against
the running stack verified 11 write paths — assets create/read-back/update, alarm
acknowledge, yard check-in, carrier, subscription, schedule. **All 11 work.** The UI's write
actions work too: acknowledge, Approve, Reject and notification-test all return 200 through
the browser.

**None of them had a test that would notice if they stopped.**

| FS | What |
|---|---|
| **FS-401** | `test_writes_round_trip.py`. The existing write walk asserts a POST with an empty body answers 422 — VALIDATION, not function. A handler that answers 200 and commits nothing passed it. The new test asserts the value goes in, comes back, appears in the LIST query a page actually uses, and survives an update. Mutation-verified: removing `await db.commit()` fails 5 of 7, and the 2 survivors are the controls, which do not depend on a commit |
| **FS-402** | `test_readme_test_count_is_not_stale.py`. The README said 2,149 tests; collection reports 3,191. True when written, and a thousand short within weeks — in the flattering direction, which is the one that gets quoted |
| — | Fifth quadrant added to the wire sweep: interfaces declared in `src/api/` beside their client. `DriverHOS`, `ShipmentCosts` and `FleetHealthStatistics` were outside every check on that page — the FS-393 gap, one level up |

**Two design notes worth keeping.**

*The round-trip test runs on in-memory SQLite, not the real-DB fixture.* Those are gated on
`importorskip("testcontainers")` and skip wherever Docker is absent — true for this entire
session. A test that only runs in CI does not stop you shipping a broken write at 2am.
Tenant isolation is explicitly **not** claimed there; SQLite has no RLS and that stays with
the real-DB suite.

*The README count is a FLOOR, not an exact figure, and the floor is guarded from both
sides.* An exact assertion fails on every commit that adds a test, which trains people to
edit the number without reading it — the same reflex that let 2,149 survive. A floor set far
below reality passes forever and asserts nothing, so a second assertion keeps it within 600
of the truth. Mutation-verified in both directions.

### Still open

- The RAG branch is **verified and pushed** (2026-08-02):
  `backup/feature/RAG-Compliance-Doc-Pipeline` at `ac86e811`, 360/360 commits, all
  author/date/subject metadata identical and tip tree byte-for-byte identical.

  Prior state remains pinned locally at `refs/qa-safety/rag-branch-prior` →
  `ee19defb`. The blocker was the throwaway clone having no credentials for
  the remote, and pushing from the main repo worked first try.
- **Extend the phantom-field guard to client RETURN types** — the FS-393 gap above.
- `correlation_registry_integration.py` (FS-359): 1,065 lines, four importers, zero tests.

## Not a defect, recorded so it is not re-investigated

- `model_registry_storage: "error: storage root missing and not creatable"` is accurate
  reporting of an environment fact; the check behaved as designed.
- `/health/ready` 503 follows correctly from stale ingestion.
- The 15 other 503s are the known Redis and `pg_stat_statements` gaps (FS-259b).
- A stale local `dev.db` fails `make seed-demo` with `no such column: maintenance_mode`
  rather than "delete this file" — `create_all` does not alter existing tables. Deleting
  `dev.db` fixes it. Gitignored artefact, not a repo defect, but a real trap.
