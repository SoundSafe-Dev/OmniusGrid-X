# `response_model` burn-down — pool #43, and the lane map that keeps it out of everyone's way

Started 2026-07-31 on `hamad/converged-pre-main`.

## Why this and not something else

Pool #43 is the prerequisite for #38 meaning what its name implies. The contract gate now
runs and blocks, but **schemathesis can only check what is declared** — so a gate over an API
where more than half the routes declare no response is validating well under half the surface.
Every route declared raises what the gate can see; every fix raises the ratchet.

**Measured 2026-07-31** (the pool's own instruction is to re-derive before starting, because it
drifts):

| Fact | Pool said | Actually |
|---|---|---|
| Undeclared routes in `app/api/` | 195/458 declared | **227 undeclared** of 419 |
| Contract ratchet floor | 290 | **350**, observed min 359 of 451 |
| Non-conforming operations | 152 | **~92** |

The other session moved 299 → 360 via the problem+json headers and UUID path params. The
remaining gap is smaller than the pool records and the shape is unchanged.

## The hazard this work carries

**Declaring a `response_model` is not additive — FastAPI filters the response through it.**
A model that omits a field the frontend reads deletes that field from the payload, and the UI
renders blank rather than erroring. That is this repository's most-documented defect class
(sweeps #19, #21) arriving through the front door.

So the method per route is fixed, and the second step is the one that matters:

1. Read what the handler actually returns — every branch, including error and empty paths.
2. **Grep the frontend for the consumer** and confirm every field it reads is in the model.
3. Declare the model, reusing an existing schema wherever one fits.
4. Prove it: a test that fails if a field is dropped.

A route whose real return shape cannot be pinned down gets **skipped and listed here**, not
guessed at. A wrong model is worse than none — none is honestly undeclared, wrong is a
contract that lies and a gate that certifies the lie.

## Lane map — measured, not assumed

Derived from each dev's **own commits** (`git log $(merge-base)..$branch`), not their branch
tips: every stale branch appears to touch 82 API files because it is 28–112 commits behind, so
tip-diffing is useless for this.

**Hands off — actively worked by someone else:**

| File | Contention | Owner |
|---|---|---|
| `auth.py` | 6/6 branches | Hridyansh (RBAC) |
| `kanban.py`, `telemetry.py` | 6/6 | shared / Harsh |
| `analysis_sessions.py` | 5/6, htreinen ×9 | htreinen |
| `nlp_correlation.py` | 5/6, htreinen ×7 | Harsh / htreinen |
| `model_monitoring.py` | 4/6 | Harsh (MLOps) |
| `logistics_correlation.py` | 6/6 | Harsh |
| `engines.py` | 6/6 | mixed — MLOps half is Harsh's |
| `rag.py` | — | htreinen |

**Safe — zero other branches touch them:** `fleet_health.py` (7), `notifications.py` (5),
`dashboard_analytics.py` (5), `simulation.py` (2), `fleet_agents.py` (1), `erp_webhooks.py` (1),
`alarm_rules.py` (1).

**Mine by lane, low contention** (platform / observability / schema / deploy, per the README
ownership table): `exports.py` (20), `query_performance.py` (12), `gdpr.py` (9),
`data_retention.py` (8), `compliance_reports.py` (8), `compliance.py` (8),
`feature_flags.py` (6), `bulk_operations.py` (6), `data_residency.py` (6), `audit.py` (5).

## The queue

| Batch | Files | Routes |
|---|---|---|
| Guard | ratchet test so new routes cannot land undeclared | — |
| 1 | the seven zero-contention files | 22 |
| 2 | `exports.py` | 20 |
| 3 | `query_performance`, `data_retention`, `gdpr` | 29 |
| 4 | `compliance_reports`, `compliance`, `audit` | 21 |
| 5 | `feature_flags`, `bulk_operations`, `data_residency` | 18 |

**110 routes available in-lane**, which is where the 100 comes from. The guard is first
deliberately: without it the ratio drifts back while the burn-down is still running, which is
exactly what happened between the pool being written and today (191/417 → 195/458 — the
absolute number rose while the ratio fell).

## Progress

| Date | Undeclared | What moved |
|---|---|---|
| 2026-07-31 | **250** | baseline, measured from the live route table |
| 2026-07-31 | 243 | `fleet_health` ×7 |
| 2026-07-31 | 229 | `notifications` ×5, `dashboard_analytics` ×5, minus 6 that were never debt (204) |
| 2026-07-31 | 209 | `exports` ×13, minus 8 that were never debt (binary media types) |
| 2026-07-31 | 197 | `query_performance` ×12 |
| 2026-07-31 | 184 | `gdpr` ×9, `data_retention` ×12 (the pool counted 8) |
| 2026-07-31 | 179 | `audit` ×5 |
| 2026-07-31 | 164 | `compliance_reports` ×7, `compliance` ×8 |
| 2026-07-31 | 158 | `bulk_operations` ×6 |
| 2026-07-31 | 146 | `data_residency` ×6, `feature_flags` ×6 |
| 2026-07-31 | 139 | `geotab` ×7 |
| 2026-07-31 | 116 | `fleet_logistics` ×23 — the largest single file |
| 2026-07-31 | **100** | `health` ×16 (17 routes, one already documented as `text/plain`) |

**113 routes off the list, of which 99 were declarations and 14 were miscounts.**
Both halves matter: the ratchet is only worth obeying if its number is honest, and
14 routes that could never be declared would have made the target unreachable.

## What is deliberately NOT debt

The count excludes two categories, in the ratchet itself rather than as an
exemption list, because neither is unfinished work:

- **204 No Content** (6 routes). RFC 9110 §15.3.5 forbids a body. There is
  nothing to declare and never will be.
- **A declared non-JSON media type** (8 routes). `response_model` describes a JSON
  schema; there is none for an xlsx or a PDF. The export routes state their real
  type through `responses={200: {"content": {...}}}`, which is what #38's fix
  used and what the contract gate reads.

## Skipped, with reasons

*(a route listed here is a decision, not an oversight)*

Nothing skipped yet. Every route attempted so far had a shape that could be
pinned down exactly.

## Defects found while declaring

The method — read the handler, check the consumer, declare, prove it cannot drop
a field — has so far found two bugs that had nothing to do with coverage:

1. **`DELETE /notifications/subscriptions/{id}` would have started returning 500.**
   It returns `{"deleted": subscription_id}`, and that value is the path parameter
   FastAPI already parsed into a `UUID`. Typing the field `str` is the obvious
   reading of the handler; pydantic v2 does not coerce UUID to str, so response
   validation would have failed on every successful delete. Found by validating
   the model against a real UUID rather than trusting the read. Typed `UUID`,
   which serialises to the identical JSON string.

2. **`GET /exports/jobs/{job_id}` declared `text/csv` and has never served one.**
   It is the status/progress endpoint returning `_job_public`, JSON; the CSV is
   one segment down at `/download`, and the media type was almost certainly copied
   from that neighbour. This is the exact inverse of the defect #38 fixed across
   nine export routes — same class, opposite direction — and it survived that
   sweep because the sweep looked for *handlers returning binaries*, not for
   *declarations claiming one*. Anyone generating a client from this schema would
   have typed the polling endpoint as a file download.

The second one also caught the ratchet: `_serves_a_binary` initially believed the
declaration and excluded the route from the count. A guard that reads a lie
inherits it.

3. **`query_performance`'s seven list endpoints each return `count`**, and the
   first version of their models declared only the items key — which would have
   deleted `count` from all seven at once.

4. **`/logistics/delivery-efficiency` is typed in the client under three names it
   has never sent.** `transportation.ts` declares the call as
   `{ onTimeRate, avgTransitTime, totalDeliveries, lateDeliveries }`.
   `compute_delivery_efficiency` returns `onTimeRate`, `avgTransitHours`,
   `deliveredToday` and `totalDelivered` — one name in common out of four, and
   `lateDeliveries` is computed nowhere on the server. `onTimeRate` is the one
   they share and they disagree about it too: the server sends a **ratio**
   (`round(on_time / delivered, 4)`), the client's own mock path for the same
   field computes a **percentage**, so the real backend renders a 92% on-time
   fleet as "0.92".

   The model here declares the **function's** names, not the client's. Declaring
   the client's would have made the schema agree with the TypeScript and disagree
   with the payload, which is the wrong of the two to fix from the server side —
   and it would have deleted all four real fields on the way out. Left for a
   frontend change, recorded rather than reconciled.

5. **`_zone_out` sends `polygon`; the client reads `coordinates`.** Same class,
   found in the same file. `adaptZone` maps `zoneType -> type` and
   `radiusMeters -> radius` but takes `coordinates` straight through, so a polygon
   zone's vertices arrive under a name nothing reads and the shape never draws.
   Circles are unaffected, which is why it survived: the default zone type is
   `circle`. Not fixed here — the fix is one line in the adapter, in a file this
   pool does not touch.

6. **Two 500s of my own making, found only when 393 unrunnable tests were
   unblocked.** `HealthBandItem.min/max` declared `int` against a band whose upper
   bound is `100.01`; `HistorianPolicyOut.ingestion_priority` declared `str`
   against a numeric column. Both keys were named correctly — the AST sweep
   compares names — and the unit guards validated against fixtures I wrote, so
   they agreed with my own wrong assumption. **The only thing that disagrees with
   a wrong type is a real row from a real column.** See FS-284b.

## The check is now automatic

Finding (3) by eye, after finding (1) by eye, was the signal. `test_response_models_match_their_returns.py`
walks the AST of every API module, finds handlers whose decorator sets
`response_model=`, and compares the model's fields to the keys of every literal
dict the handler returns. 50 handlers checked, mutation-verified against the
`count` bug it was written for.

It states its own blind spots rather than pretending to totality: handlers that
return a variable or a helper call have no keys in the syntax, so they are covered
instead by `test_declared_models_do_not_drop_fields`, which calls the shaping
helpers directly. A `**spread` in a returned dict is skipped rather than guessed
at. **A partial check that names its gaps is worth more than a total one that is
wrong** — and between the two files, both shapes are covered.

`fleet_logistics` is the case that proves the split was worth drawing. All 23 of
its routes build their payload through four helpers — `_zone_out`, `_schedule_out`,
`_order_out`, `_history_out` — so **not one of them has a dict literal for the AST
sweep to read**, and the sweep passes the whole file while checking nothing in it.
The companion file now calls those four helpers directly, plus
`summarize_maintenance` and `compute_delivery_efficiency`; `_schedule_out` alone
backs five routes, so one field missing there is one field missing from five
endpoints at once. Mutation-verified: removing `estimatedCost` from
`MaintenanceScheduleOut` fails `test_schedule_out`.

This is the leverage that makes the remaining routes safe to do at pace: the
expensive part of each declaration was reading the handler carefully enough to be
sure no key was missed, and that part is now mechanical. It paid immediately —
`gdpr` (9) and `data_retention` (12) went in as one pass and the sweep, now
covering 72 handlers, confirmed both clean without a hand-written test each.

## What a clean schema makes look true

Two endpoints in this burn-down now have tidy, documented response models over payloads that
are not measurements. **A declaration makes a surface look more trustworthy without making it
more true**, so both are named here rather than left for a reader to discover from the schema.

1. **GeoTab's HOS endpoints.** `geotab_service` generates the DOT-regulated hours-of-service
   figures with `random.uniform`. The schemas are clean and the numbers are invented. A
   comment in `app/api/geotab.py` points at **FS-267**, where the real fix — label them
   simulated, or gate them behind a flag — belongs.

2. **`POST /admin/collectors/{collector_id}/restart` restarts nothing.** The whole handler is
   a `return`. It answers `{"message": "Restart signal sent to collector …", "status":
   "pending", "timestamp": "2026-01-15T10:30:00Z"}` — a hardcoded past timestamp, and a
   message in the past tense about a signal no code sends. `assets.ts` calls it as
   `restartCollector()` and returns `Promise<void>`, so an operator clicking Restart gets a
   200 and no restart. `CollectorRestartAck` describes what is sent and its docstring says
   outright that it does not vouch for it; making the endpoint do the thing, or removing it,
   is a behaviour change and not this pool's to make.

## The probes, and why the usual hazard runs backwards there

`health.py` was the one file where the standing rule — *a model that omits a field deletes
it* — was not the thing to be most careful about. Checked before declaring anything:
`infrastructure/k8s/base/backend-deployment.yaml` wires all three probes as `httpGet`
(liveness and startup to `/health`, readiness to `/health/ready`), and **an httpGet probe
reads the status code and never parses the body**. No field named or omitted in those models
can affect a rollout.

The hazard is the inverse, and it is worse. A response model that *rejects* a payload turns
a 200 into a 500, and on `/health/ready` a 500 is a failed readiness probe — three of them
and kubelet pulls a perfectly healthy pod out of the Service. **A declaration on a probe is
a new way for the probe to fail.** So every field is typed against what the checkers can
actually emit, including the branches only a degraded or unconfigured deployment reaches:
`available: False` with three nulls when psutil is absent, `checks: {}` before the cache has
been filled once, `database_size_bytes: None` when the row could not be read.

`/health/db`, `/health/redis` and `/health/kafka` return `{"status": ..., **details}` where
`details` belongs to the checker (`{"reason": "rate_limit_disabled"}`, `{"url": ...}`,
`{"source": ..., "broker": ...}`, or `{}`). Those three models document the keys their own
checker emits today and set `extra="allow"`, so a key added to a checker tomorrow reaches
the caller instead of being filtered out of a 200. The AST sweep skips a `**spread` return
by design, so nothing else covered these — `TestHealthComponentModelsDoNotFilterTheCheckerDetail`
asserts the extras really do survive rather than trusting that they should.

## One shape declared deliberately open

`UserDataExport` (`GET /gdpr/data-export`) keeps `user` and `consents` as open
objects. This payload is a GDPR Article 15 subject-access response — the legal
deliverable — and a response model that FILTERS it is the one thing it must never
be. An under-declared model would quietly withhold a column from a data-subject
request and return 200 while doing it.
