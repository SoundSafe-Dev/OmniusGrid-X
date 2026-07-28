# Defect-class sweeps

A record of defect *classes* found in one subsystem and then checked across the whole
platform, with what each sweep found and which guard keeps it closed.

**Why this document exists.** "Proven clean" and "never checked" look identical
afterwards, and only one of them justifies not looking again. Two of these sweeps found
nothing; without a record, someone would eventually redo the work — or, worse, assume the
class had been handled when it had not.

The method throughout: find a class of bug where **code looks wired and cannot work**,
fix the instance, then ask whether the same shape exists elsewhere. Every guard listed is
mutation-tested — reverting the fix must fail the test, or the guard proves nothing.

---

## The seventeen classes

The first five were all originally found in ERP. The sixth came out of the fifth, the
seventh out of two failing tests that turned out to share a cause, and the eighth out of
the seventh — the same "we are testing a double, not the thing that ships" shape, moved
to the frontend/backend seam.

| Class | Swept | Found elsewhere | Guard |
|---|---|---|---|
| Response model stricter than its columns | all 61 API modules | **49 real, now 0 — the sweep was wrong twice** | `test_api_response_schema_matches_columns.py` |
| Pagination truncation | list endpoints | **3 ERP endpoints** | `test_erp_platform_integration_realdb.py` |
| Invented vendor endpoints | all 8 connectors | ERP only | `test_erp_no_invented_endpoints.py` |
| Silent success | all of `app/` | **1, live** | `test_logistics_sync_dashboard_honesty.py` |
| A name that claims a side effect | all of `app/` | **1, in the control path** | `test_helper_names_match_behaviour.py` |
| Data reported as kept, but discarded | quarantine/DLQ paths | **1, live, on ingestion** | `test_edge_ingest_quarantine_retention.py` |
| A test double that reimplements what it stands in for | every `get_tenant_db` override | **4 copies, hiding an RLS bug** | `test_tenant_guc_survives_commit_realdb.py` |
| Frontend calling endpoints the backend does not serve | all 183 real-mode API calls | **4, one wired to a live button** | `test_frontend_calls_real_endpoints.py` |
| Response shape disagreeing with the frontend's type | 86 typed calls | **none** | `test_frontend_response_shapes_match.py` |
| Query parameters the endpoint does not declare | 37 param-sending calls | **2, plus 4 IDOR-shaped endpoints** | `test_frontend_query_params_are_declared.py` |
| An org-scoped table with neither a filter nor RLS | `get_db` handlers on org tables | **~60 handlers: 2 leaks, an IDOR, and whole surfaces returning nothing** | `test_tenant_session_guard.py` + 5 real-DB suites |

---

## 1. A response model stricter than its columns — **49 real, now zero; the sweep was wrong twice**

A required response field over a nullable, defaultless column means a valid row cannot be
serialised: pydantic raises inside the handler and FastAPI returns 500, naming a
validation error in *our schema* rather than the data. It cost four ERP endpoints at once,
because create, list, get and update all built the same model.

**Swept:** every response model in `app/api/` paired to its own ORM model.

**This sweep was reported clean, and that was wrong.** It found 11 pairs across 7
routers; the corrected version finds **40 pairs across 16 routers, 603 fields, and 158
offenders**. Two exclusions were at fault, and both looked reasonable:

- It skipped any column with a **Python-side ORM default**, on the reasoning that the
  ORM fills it. It fills it only for rows written *through SQLAlchemy* — a migration, a
  seeder or any raw `INSERT` leaves NULL. 148 of the 158 are this shape.
- It required `obj.__module__ == module.__name__`, which skipped every response model a
  router imports from `app/models/schemas.py` — where a large share of them live.

**The class is real, not theoretical.** A raw-inserted dock door made
`GET /api/v1/yard/dock/doors` return a live 500: *"equipment_capabilities: Input should
be a valid dictionary"* — a validation error naming our schema rather than the data, so
nobody would think to look at the row. `DockDoorResponse` now mirrors its columns, with
the overrides on the response model so create/update keep their stricter types.

A pydantic default does not rescue this either: the ORM hands the field an explicit
`None` rather than omitting it, so the default never applies. The corrected check tests
optionality of the annotation, not `is_required()`.

**Then the corrected sweep was wrong in the other direction, by a factor of three.** It
read `column.server_default` off the ORM metadata — and **109 of the 158 columns already
have a database default**, added by migration 044 and never mirrored back into the ORM
declaration. The application's opinion of the schema is not the schema. Those columns can
never be NULL from any INSERT, so they were never at risk.

The check now reads `information_schema` from the migrated database. **The true count was
49**, and it is now **zero**:

- **39 were given server defaults by migration 050** — all in the logistics/yard tables
  that 044 did not reach, each default taken from the ORM's own `default=` so the
  database now enforces exactly what the application already assumed. Unlike 044, these
  backfill existing NULLs: a NULL `is_active` or `status` is a missing value, not an
  unknown moment, so writing the documented default is a correction rather than an
  invention.
- **10 are nullable with no default anywhere** — mostly optional foreign keys
  (`dock_door_id`, `trailer_id`, `driver_id`, `shipment_id`). Their response fields now
  mirror the columns, overridden on the response model so create/update keep the
  stricter types.

The shrink-only baseline is gone with them. It was the right instrument for what the
evidence looked like at the time, and the wrong one once the evidence was measured
properly — most of what it recorded described columns that were never broken.

**The first scan was wrong, and the error is worth remembering.** It reported 8 defects.
Testing one against real Postgres returned HTTP 200, not the predicted 500 — the
optionality check tested only `typing.get_origin(a) is typing.Union`, but PEP 604
`str | None` produces `types.UnionType`, a different object. Every field in modern syntax
was misread as required. The same flaw sat in the ERP guard, where it would have failed a
*correct* model. Both now test the detector before anything that depends on it.

Reachability is part of the check: a nullable column with a default can never hand
pydantic a `None`, so it is excluded.

## 2. Pagination truncation — **3 endpoints fixed**

Returning one page and presenting it as the whole set. This bit three ERP *connectors*
(NetSuite, Dynamics via `@odata.nextLink`, Odoo), and then turned up on our own API.

The ERP hub's three list endpoints returned exactly `limit` rows and nothing else, and the
UI passed no limit — so a tenant with 5,000 entities would have been shown the first 200
as everything. They also **clamped silently**: `min(limit, 1000)` with no bound declared on
the parameter, so `limit=5000` returned 1,000 with nothing saying the request had been
changed.

Fixed: the bound is on the query parameter (an over-limit request gets 422 rather than a
quiet substitution), truncation is reported in `X-Result-Truncated` via a `limit + 1`
probe rather than a COUNT, the API client returns `ListResult<T>` so the flag cannot be
dropped, and the hub's Entities/Events/AI tabs render it as
*"showing the most recent N of more than N."*

Those tabs did not exist when the endpoints were fixed, which made the fix latent. Building
them was the other half of the work.

## 3. Invented vendor endpoints — **ERP only**

All seven original connectors POSTed to a `/webhooks`-shaped URL with byte-identical
`{name, url, event_type}` payloads across seven unrelated vendors — so at most one could
have been right. None was.

Against a real Odoo it returned `True` for a subscription that was never created:
`/xmlrpc/2/<anything>` matches, and Odoo answers **HTTP 200 with a fault in the body**,
while the connector checked only the status. 379 lines removed; connectors now declare the
real mechanism in `EVENT_SUBSCRIPTION_MECHANISM`.

This class is inherently vendor-integration-specific, so there was nowhere else to sweep.

## 4. Silent success — **1 real, and live**

A handler that swallows an exception and still reports success. The caller has no way to
know, which makes it the worst-consequence class of the four.

**Swept:** every `try/except` in `app/` whose handler neither re-raises nor returns an
error, inside a function returning something success-shaped. **12 candidates, inspected
individually rather than counted.**

**Eleven were legitimate** and were left alone: connector cleanup in a `finally`, handlers
that swallow then `return False`, an `ImportError` fallthrough, and one that deliberately
reports the failure as `status="error"` rather than raising a 500. The three ERP
`extract_all_entities` loops already record `{"status": "failed"}` per entity and count
failures.

**The twelfth was real.** `get_sync_dashboard` analysed each dock appointment in a `try`
and, on failure, incremented **no bucket at all** — the appointment vanished from the
breakdown while remaining in `total_appointments`, the denominator of
`production_dock_sync_percent`. So every failed analysis pushed the reported sync
percentage *down*, making dock-production performance look worse than it was, with nothing
saying an analysis had failed.

Failures now get their own bucket and leave the denominator — counting an unanalysable
appointment as "not on time" asserts precisely what we failed to determine. An *unlinked*
appointment is treated differently on purpose: `no_operation` is a real status we know, not
a measurement failure, so it stays in the denominator.

## 5. A name that claims a side effect — **1, in the autonomous control path**

The previous class lies in a return value. This one lies in the identifier, so no
log-scanning or response-shape guard would ever see it: the call site reads exactly as
though the work happened, and nothing at runtime contradicts it.

**Found in ERP.** `sap_webhook_integration` had `_create_alert_for_po_anomaly`,
`_create_alert_for_po_status_change` and `_create_alert_for_low_inventory`. None created
an alert; each was a single `logger.warning` under a comment reading *"This would
integrate with the alarm/alert system."* What made it genuinely misleading rather than
merely optimistic is that `_create_task_for_work_order`, in the same class twenty lines
away, **does** create a `Task`. Now `_log_*`.

**Swept:** every function in `app/` whose name starts with a side-effect verb —
create/send/persist/store/write/save/publish/emit. **129 helpers, 2 log-only bodies.**

`utils/signed_urls._emit_fallback_warning` is honest: emitting a warning *is* logging.
It is excluded by name, not by judgement — a helper whose object is a log line
(`_warning`, `_error`, `_log`) cannot be lying about it.

**The other was `tactical_engine._send_command`, and it is the worst instance of any of
these five classes.** Its whole body assembled a command dict and logged
`command_queued` at DEBUG, publishing nothing. `execute_decision` — whose docstring
reads *"Returns True if executed, False if blocked"* — then logged
`tactical_decision_executed` and returned **True**:

```python
await self._send_command(decision)            # built a dict, logged at DEBUG
logger.info("tactical_decision_executed")     # ...for a command never sent
return True
```

The trap is the same as the SAP one, with actuation of industrial assets behind it. The
two safety gates immediately above the dispatch are implemented properly and carefully —
maintenance-mode and a 0.7 confidence floor — and the maintenance check even fails SAFE,
under a comment reading *"a broken control command is worse than a skipped one."* Anyone
reading that had every reason to assume the dispatch below it was equally real.

It is currently unreachable: `execute_decision` is only called from `_inference_loop`,
and `start()` is absent from `main.py`'s startup list. That is the only reason it has
never mattered, and it is one line from mattering — the other seven engines are all
started there.

**It now refuses instead of dispatching, and that is deliberate.** The real sink exists
and is already running: `command_executor`, backed by the `Command` model, and
`api/commands.py` already documents `"tactical"` as a command type. Wiring it would
switch on autonomous actuation of industrial assets, which is a decision with a safety
review attached rather than a side effect of a naming fix. So `_dispatch_command`
returns `False`, `execute_decision` returns `False` with it, and the module says what it
would take to wire — the same posture as `erp_database_replication.start_replication`.

**A second-order defect fell out of it.** `execute_decision` queues a
`tactical_decision` event to the cloud as *training feedback*. A decision that never
reached the asset produced no outcome to learn from, so feeding it in as though it had
actuated teaches the model from something that never happened. The payload now carries
`dispatched`.

**The detector had to be rewritten before it was worth trusting**, and how it failed is
the useful part. The first version asked *"does this call something from a list of
doing-verbs?"* and produced three false positives immediately, in three different
flavours of delegation it could not see: `create_from_config` constructs an object,
`_persist_rotated_refresh_token` calls an injected callable, `_send_alert` calls a
notification service. All three are honest; the detector was not — and a longer verb
list would only have moved the boundary. Asking the opposite question, *"is logging ALL
it does?"*, needs no list of approved verbs, so delegation of any shape passes, while
still catching the real ones exactly, because they were a `logger.warning` and nothing
else. Two detector tests pin this: one that a log-only body is caught, one that
assembling a payload before logging is **not** mistaken for dispatch.

## 6. Data reported as kept, but discarded — **1, live, on the ingestion path**

Found by following a loose end from class 5 rather than by pattern-matching, which is
the more interesting part of how it turned up. `tactical_engine` had a `start()` that
`main.py` never calls, so the obvious next question was whether it was alone.

**Swept:** every module-level service singleton in `app/` exposing a `start()`, checked
against every process that could start one — `main.py`, the workers, and the edge agent.
**12 singletons; 5 are started nowhere at all:** `cloud_gateway`, `egress_scheduler`,
`mlops_pipeline`, `strategic_engine`, `tactical_engine`. `main.py` even works around one
of them, at line 82: *"Offline demo: the cloud strategic listener never connects, so
seed a few…"*.

`cloud_gateway` is the one that matters, because six call sites queue into it. It is an
in-memory list capped at 10,000 that sheds the oldest, and `_flush_loop` — the only
thing that drains it — is started nowhere. Following its callers reached
`schema_registry._persist_to_dlq`, *"Persist quarantined record to dead letter queue"*,
whose comment reads *"Persist to dead letter queue (SQLite or file)"* and which is
neither. **That one is not live** — nothing in the running app imports
`schema_registry`, so it is unwired rather than broken, and it is recorded below rather
than fixed.

**But the search pattern found a second quarantine path that IS live.**
`EdgeIngestGateway.ingest` validated each reading and, on failure, called a sink and
incremented an integer. `api/edge_ingest.py` constructs the gateway with no sink, so the
default ran:

```python
def _default_quarantine(self, agent_id, reading, reason):
    logger.warning("edge_ingest_quarantined", agent_id=agent_id, reason=reason)
```

`reading` is accepted and never used. The payload went nowhere — no table, no topic, not
even the log line — and `POST /api/v1/edge/ingest` then answered `quarantined: 47`.

**The count was true and the word was not.** "Quarantined" means set aside for
inspection, and the module docstring promised these were *"diverted to a dead-letter
sink."* An operator had no way to learn the number described 47 readings that no longer
existed anywhere, and no way to find out what the agent producing them was doing wrong —
which is the entire reason to look.

The fix has two halves, because either alone leaves the hole open:

- **Retention moved into `IngestResult.quarantined`**, which now holds the readings
  themselves rather than a count — mirroring `accepted`, and for the same reason: the
  caller has to be able to do something with them. Every caller gets them whether or not
  it injects a sink, which is what the API configuration needed. A reading that is not
  even a dict is kept as its `repr` rather than dropped for being the wrong shape; "it
  was not a reading at all" is exactly what an investigation needs.
- **A real dead-letter topic hop** in the endpoint, so they outlive the request, using
  the `RedpandaForwarder` already constructed there and sharing its circuit breaker.

`summary["quarantined"]` still returns the count, so the API response shape is untouched.

**The DLQ topic keys on `agent_id`, not `asset_id`, and that is load-bearing.** These
readings failed validation, so nothing inside them can be trusted for routing — the
malformed field may well *be* `asset_id`. Keying on it would scatter dead letters under
bug- or attacker-controlled topic names and discard the one identity that was actually
verified, the client certificate. A test asserts a reading carrying
`asset_id: "../../evil"` still lands on `telemetry.dlq.<agent>`.

## 7. A test double that reimplements what it stands in for — **1, and it was hiding an RLS bug**

Two tests had been failing for a while, in other people's lanes, and were assumed
independent. They had the same cause, and the cause explains why nothing caught it.

**The bug.** `get_tenant_db` set `app.current_org_id` once, before yielding the session,
with `set_config(..., false)`. The docstring justified the `false`: a session-scoped
value survives an endpoint that commits mid-request, where a transaction-local one would
not.

It does not survive. `commit()` ends the transaction **and returns the connection to the
pool**; the next statement checks out a connection that was never configured. The GUC
reads empty, `NULLIF` makes it NULL, and every RLS policy fails closed — so an endpoint
that wrote a row and read it back got nothing, for data it had just committed itself.
`create_rollout` in `api/agent_rollouts.py` returned **404 for a rollout sitting in the
table**.

Part of this had already been diagnosed. An inline comment, right below the docstring
that contradicts it, warns against `db.refresh()` after `commit()` for exactly this
reason, and twenty such calls were removed. That was worth doing, but it treated the
symptom: *any* query after a mid-request commit was affected, not just a refresh.

**Fixed at the cause:** the GUC is now re-established per transaction from an
`after_begin` hook, so any number of commits is fine. Because it re-runs per transaction
it is written *transaction-locally*, so it also cannot leak onto a pooled connection —
which removes a second hazard the old code needed a cleanup block to manage.

**Why every RLS test we had was blind to it.** `conftest` must point endpoints at the
testcontainers engine, and did so with an override that hand-copied the body of
`get_tenant_db`, under a comment reading *"Mirrors the production get_tenant_db."* It
mirrored the bug as well as the behaviour — and being a copy, it could not do otherwise.
The suite was exercising the duplicate, so a defect in the original was undetectable, and
fixing the original would not have reached the tests either.

A test double that reimplements the thing it stands in for can only prove the double
works. The override now delegates to a shared `tenant_session`, with only the session
maker injected, and a guard asserts it keeps delegating — checking source text rather
than behaviour on purpose, because a reimplementation that happens to be correct today
is still the failure mode.

**And then the sweep found three more.** The first version of that guard read `conftest`
only. Sweeping every file that overrides `get_tenant_db` turned up byte-identical copies
of the same buggy body in `test_rul_api`, `test_twin_optimizer_api` and
`test_historian_api` — **four copies in total**, so the RUL, twin-optimizer and historian
suites were all still asserting against the defect rather than against production. All
four now delegate, and the guard sweeps rather than spot-checks: it enumerates every
overriding file, fails naming the offender, and has a vacuity check because a broken
discovery would pass while checking nothing — which is precisely how three of the four
survived the first pass.

**The guard needed a second pass, and this is the part worth remembering.** Written the
obvious way it *passed against the reintroduced bug*. With a normal pool, `commit()`
returns the connection and the very next statement checks the same one straight back
out, so the GUC appears to survive — which is exactly why the defect read as
intermittent and needed contention to appear. The fixture now uses `NullPool`, making
every checkout a fresh connection: the worst case a loaded server produces routinely.
Under mutation it fails the four commit assertions and nothing else. **A guard that
fails only when the pool happens to cooperate is not a guard.**

**A second, unrelated race surfaced in the same test.** `test_compliance_report_scheduling_e2e`
also failed with `KafkaConnectionError: Unable to bootstrap` — but only in a full run,
never in isolation, the classic shape of a readiness check that returns too early. The
Redpanda fixture waited for the log line *"Started Kafka API server"*, which Redpanda
prints when it binds **inside the container**; the host's published port can take
meaningfully longer to forward, and that gap widens with the number of running
containers. It now waits for a connection to actually succeed. Wait for the thing you
need, not for a log line that correlates with it.

## 8. Frontend calling endpoints the backend does not serve — **4, one live**

`src/test/setup.ts` forces `VITE_USE_MOCK='true'` before any module evaluates, and
`src/api/mockMode.ts` reads it into a module-level `const USE_MOCK`. So every frontend
unit test has always taken the mock branch of the **213 `if (USE_MOCK)` forks across 33
files**. The real branch — the code that actually ships — is executed by no test at all.

Same shape as class 7 at a much larger scale: the suite exercises a double instead of the
thing that runs. And the same shape as class 3, "invented endpoints", moved from vendor
APIs to our own seam.

**Swept:** every `api.get/post/put/patch/delete` call in `src/api/` — **183 calls across
22 modules** — against the backend's live route table.

**Found four the backend does not serve**, each confirmed by issuing the request
in-process rather than trusting the diff:

| Call | Result | |
|---|---|---|
| `PATCH /api/v1/fleet/security/events/{id}` | **404** | **live — wired to a UI button** |
| `PATCH /api/v1/fleet/dtcs/{code}` | 404 | uncalled |
| `GET /api/v1/transportation/vehicles/{id}` | 404 | uncalled |
| `GET /api/v1/yard/moves` | 405 | uncalled (POST-only path) |

**The live one had a second failure stacked on it.** `HealthSecurityPanel` awaited the
call with no `catch`, so the 404 rejected the promise, the optimistic state update never
ran, and the rejection went unhandled — an operator clicked "acknowledge" on a fleet
security event and saw nothing happen, with nothing on screen saying why. The endpoint now
exists (everything else was already there: `geotab_exceptions` carries `acknowledged`,
`acknowledged_by`, `acknowledged_at`, and the GET already filtered on the flag — only the
write was missing), and the component reports failures instead of swallowing them.
`acknowledged_by` comes from the token, not the body, matching `alarms.acknowledge_alarm`.

The other three were **uncalled**, and their only working branch returned fabricated mock
data. Implementing three endpoints nobody calls would be speculative; the client functions
were removed instead, so the next person to want the feature writes both halves together.

**A previous fix of this exact class had already run, and missed these.** This router's
docstring says it was created (FS-15) to serve "/api/v1/fleet/* routes that never existed
(dead real branch)" — and it left both PATCH routes behind. That is the argument for
sweeping rather than fixing by hand.

**The guard checks route existence, deliberately and only.** Request bodies and response
shapes need real-mode tests per module (`src/test/realMode.ts`, which today has exactly
one adopter of 34 API modules); this is the cheap total-coverage check for the failure mode
that actually occurred.

**Its first run reported 185 failures against a backend that serves all of them.** The
route table was read from `app.routes`, but this app includes routers lazily behind an
`_IncludedRouter` wrapper, so at import time that list holds 74 entries covering none of
the API. `app.openapi()` resolves the wrappers (373 paths). The extractor was wrong twice
over: it had also read `` `/x/entities${q}` `` — a query string glued to a path — as a
path segment, inventing a fifth missing endpoint. A path parameter is always preceded by a
slash; the glued form is a suffix. `TestTheExtractor` runs first for exactly this reason.

## 9. Query parameters the endpoint does not declare — **2, and they exposed 4 more**

Class 8 checks that the path exists. This checks what is sent to it, and the failure is
quieter: **FastAPI ignores unknown query parameters silently.** A misspelled or invented
filter does not error — the endpoint returns the UNFILTERED set, and the caller renders it
as a filtered result. No stack trace; just the wrong rows.

**Swept:** every frontend call whose parameter keys are statically resolvable — a literal
`?a=b` or a `params: { … }` object literal. **37 calls checked, 1 skipped** (params passed
as a variable, which is reported rather than guessed at).

**Found two, wrong in different ways.** `yard.getDockDoors` sent `workcell_id`, which the
endpoint does not declare — and `dock_doors` has no workcell column, so it could never
have been honoured. Only the mock branch, filtering fixture data on a field the real model
lacks, made the feature look implemented.

`nlpCorrelation.chat` sent `conversation_history` as a query parameter with a `null` body.
The handler declares it `Optional[List[Dict[str, str]]]`, and FastAPI reads complex types
from the **body** — so the server received `None` every time, while the endpoint's
docstring promised it "maintains conversation context for multi-turn queries". It had no
context to maintain. Now sent as the body; `message` genuinely is a query parameter and
stayed.

**The sweep then exposed something bigger than what it asserts.** Four yard GETs —
`/trailers`, `/dock/doors`, `/dock/appointments`, `/dwell-times` — took `organization_id`
as a **required, client-supplied query parameter** and used it directly in the `WHERE`
clause. That is the IDOR shape `app/core/tenant.py` exists to forbid ("endpoints must
NEVER trust a client-supplied organization_id"), with RLS the only thing standing between
it and a cross-tenant read — defence in depth doing the whole job rather than backing
something up.

They were also simply broken: the parameter was required and **no frontend call sent it**,
so all four returned 422 to every request the UI made. Four endpoints the yard page calls,
none of which could ever have answered. They now derive the org from the token;
`test_yard_tenant_scoping_realdb.py` pins that supplying someone else's `organization_id`
changes nothing in either direction.

**And fixing them surfaced class 1 all over again.** Seeding a dock door with a raw
`INSERT` — the case a Python-side ORM default does not cover — made the endpoint return a
live 500 on `equipment_capabilities`. That is what exposed the two holes in the class-1
detector, and the reason its "clean" result above is now a correction.

## 10. An org-scoped table with neither a filter nor RLS — **1 live cross-tenant leak**

Tenant isolation here is meant to be two layers: an explicit `organization_id` filter in
the handler, and RLS as defence in depth (`app/core/tenant.py` says so in as many words).
This class is what happens when a table has **neither**.

```python
query = select(Vehicle).where(Vehicle.is_active == True)   # get_db, no org filter
```

`vehicles` carries `organization_id` but has no row-level security, so nothing caught it.
**Every authenticated user listed every tenant's fleet.** Proven before fixing: a probe
seeded one vehicle per org, and org A's client saw both.

**Why the existing guards could not see it.** `test_route_auth_walk.py` asserts routes
require authentication — this one does; authentication was never the issue. And the
RLS-based isolation tests exercise policies, of which this table has none. A table
outside RLS is outside their reach entirely, which is the part worth remembering: the
absence of a policy silently removes a table from the suite that would otherwise cover
it.

**Swept:** every `get_db` handler touching a model with an `organization_id`, classified
by whether its table has RLS and whether the query filters. Most hits were `User`
appearing as a `Depends()` annotation rather than a cross-tenant query — a false-positive
class worth naming, since a careless reading gives 68 "leaks".

The real surface is three files: `transportation.get_vehicles` (**fixed** — filter added,
`vehicles.organization_id` is a `String(36)`, so the comparison is against `str(org_id)`),
`api_keys.verify_api_key` (**correct as written** — the key is the credential and the org
comes from it), and **`fleet_logistics.py`, 23 handlers of the same shape** across
`geofence_zones`, `geofence_alerts`, `maintenance_schedules` and `repair_orders` — all
org-scoped, none under RLS. `create_zone` additionally takes `organization_id` **from the
client payload**.

`transportation.py` has two further variants beyond the one fixed: `get_carriers` and
`get_drivers` take `organization_id` as a client-supplied query parameter, and
`get_carrier` fetches by id with no org check at all.

**`fleet_logistics.py` is now fixed too**, in a following pass rather than bolted onto
the sweep. Its 23 handlers were confirmed leaking in two distinct shapes before being
touched: the zone list returned every tenant's zones, and **fetch-by-id returned another
tenant's zone outright** — the list filter and the by-id lookup are separate code paths,
and a guard covering one says nothing about the other.

Every handler moved to `get_tenant_db`, and every query on the four unprotected tables
is wrapped in a `_scope(...)` helper. Both halves are needed: the tenant session sets a
GUC that no policy on these tables reads, so the session alone protects nothing here.

The four create paths took `organization_id` **from the request payload**, letting a
caller file a record under any organization they named — with no RLS to question it.
They now take it from the token.

**The same move fixed the opposite failure in the same file.** Endpoints reading
`Shipment`/`Carrier`/`Driver` — tables that DO have RLS — were on `get_db`, which sets no
GUC, so they were returning **zero** rows. One dependency, two failure modes, depending
only on whether the table happened to have a policy.

****Command dispatch and the emergency stop were unreachable.** `assets` is FORCE RLS, and
three handlers in `commands.py` looked the asset up through a session with no GUC —
`submit_command` and `emergency_stop` via an inline `AsyncSessionLocal()`,
`get_asset_commands` via `get_db`. Each then hits
`if not asset: raise HTTPException(404, "Asset not found")`, so all three answered **404
for every asset, including the caller's own**: submission impossible, history empty, and
the admin-gated emergency stop dead. A 404 is the least suspicious symptom available — it
reads as "that asset does not exist", which nobody investigates.

**The guard under-counted this file, and that is the lesson.**
`test_tenant_session_guard.py` keys on `Depends(get_db)` and recorded **one** site here.
Two of the three handlers open a session inline, which the guard cannot see. A static
check keyed on one idiom under-reports any file that uses two — the same failure as
reading ORM metadata instead of the schema, one level up. They now use
`tenant_session(org_id)`, the context-manager form extracted earlier for exactly this
case.

**The ERP webhook receiver was broken, and needed a policy rather than a dependency
swap.** Verified against a real database: every inbound webhook was rejected 404, because
`integration_configurations` is FORCE RLS and the candidate lookup returned nothing. This
endpoint is an unauthenticated vendor callback — there is no user to derive a tenant from,
and by design the tenant is *whoever holds the secret that verifies these exact bytes*, so
the lookup must span organizations before any tenant is known. `get_tenant_db` cannot
apply, and moving the tenant into the URL would mean trusting a caller-supplied
identifier to choose whose secret to check against — strictly worse than the design it
would replace.

**Fixed by migration 052**, which adds a second, deliberately narrow policy:
`webhook_tenant_resolution` permits **SELECT only**, on **active ERP rows only**, **only
while `app.erp_webhook_lookup = 'on'`**. The handler sets that GUC transaction-locally
immediately before the candidate query and clears it in a `finally`, so it is off for the
event INSERT and every other path. Postgres OR-s permissive policies, so this widens one
flagged moment and changes nothing else — and it needs no superuser, which matters because
the application connects as `NOSUPERUSER NOBYPASSRLS` on purpose and
`SET row_security = off` would have required giving that up.

The narrowness *is* the security argument, so it is tested rather than asserted: the flag
cannot write, cannot see dormant or non-ERP rows, and does not leak into ordinary tenant
sessions. Both halves are mutation-verified — removing the flag kills the webhook again
(4 failures), widening the policy is caught as a security regression (2 failures).

**One test of mine was wrong in a way worth recording:** it expected the disallowed UPDATE
to raise. RLS does not raise on a write it disallows — it filters the rows the statement
can see, so the UPDATE simply affects zero rows. The same "fails quiet" property that made
every defect in this sweep hard to notice was present in the guard written against it.

The residual risk is stated in the migration: anything able to set that GUC can list
active ERP integrations across tenants, including the `configuration` JSON that holds
webhook secrets. That is the same trust boundary as the database credentials themselves,
and it is as narrow as a table-level policy can be — RLS cannot restrict columns.

**The whole ERP surface was then verified end to end**, not just the webhook: all 12
routes the app serves (create, list, get, update, delete, sync, sync-status, entities,
events, mappings, webhook-config, test, correlations/recent) exercised against a real
database. Every one responds correctly.

**The NLP analysis-session surface was entirely dead, and it is the one instance that did
NOT fail quietly.** `analysis_sessions` is RLS-protected and all 22 handlers ran on
`get_db`, so reads matched nothing — empty list, 404 by id — while **create raised
`InsufficientPrivilegeError: new row violates row-level security policy`, a 500**, because
the policy's `WITH CHECK` rejects an INSERT made with no tenant GUC.

That split is the useful part: under RLS **a read fails silently and a write fails
loudly**. Every other defect in this sweep was the quiet kind, which is precisely why they
survived for so long.

A 500 on create would normally be noticed at once. It was not, because the correlation
model and its LoRA adapter are **deliberately unloaded right now** — that surface is meant
to be dormant, so nobody exercising it is the expected state rather than evidence of
neglect. An earlier draft of this note drew the opposite conclusion and was wrong.

**Restoring the surface exposed a second, latent defect, and that is worth stating as a
rule.** With the model unloaded, `correlation_ai_engine` serves a heuristic and marks it
`simulated: True` with confidence dropped to 0.4 — honestly. Both chat handlers read the
fallback's *text* and discarded the flag, so heuristic output reached the caller
indistinguishable from a real inference. That was harmless while the RLS defect kept the
endpoints unreachable; fixing the RLS made it live. **A change that turns a dead path into
a working one owns whatever that path then does** — so the provenance
(`simulated`, `simulation_reason`, `confidence`, `model_version`) is now carried through
to the response, with a guard that forces a non-simulated result to prove the flag is not
hardcoded.

Note what that guard does *not* establish: it patches the engine, so it proves the
plumbing forwards the flag and nothing about whether a loaded adapter would set it. The
`simulated: false` branch has never run for real. `docs/CORRELATION_AI_ENGINE.md` carries
the check to perform when the model is switched back on — if a real inference still
reports `simulated: true`, the adapter did not load and the engine is quietly serving
heuristics under a model-version string that says otherwise.

The application layer was correct throughout (`organization_id=current_user.organization_id` was already set on
create); only the GUC was missing.

(Kanban RLS and `/nlp/correlation/intake/{id}` are items #16 and #17 in the current task
pool and were left alone.)

**The two remaining correlation routers were the same shape, with an extra twist.**
`logistics_correlation.py` (12 handlers on `dock_appointments`) and
`platform_correlation.py` (1 on `analysis_sessions`) both queried RLS tables through
`get_db` and returned empty results — `logistics_correlation` even filtered on
`organization_id` correctly itself, which changed nothing, exactly as in `gdpr.py`. Nine
of its handlers additionally took `organization_id` as a **required client-supplied query
parameter**: the IDOR shape, and a 422 for any client that omitted it. Both now derive the
org from the token.

**One thing there is deliberately NOT fixed.** `logistics_correlation` declares
`prefix="/logistics"` while `main.py` mounts it at `/api/v1/logistics`, so every route
serves at `/api/v1/logistics/logistics/…` — the double-prefix bug already corrected in the
yard and transportation routers. Correcting it here would **collide** with
`fleet_logistics.logistics_router`, which serves `/delivery-efficiency` and
`/compliance/summary` at the single prefix — and those are the two paths the frontend
actually calls. Since `logistics_correlation` registers first it would silently win,
changing the payload the frontend receives. Choosing a canonical implementation per path
is a product decision, not a routing edit, so the tests use the real doubled paths rather
than pretending otherwise.

**Real-mode frontend coverage went from 1 module to 3, chosen by what the backend guards
cannot see.** `src/test/setup.ts` forces `VITE_USE_MOCK=true`, so every ordinary unit test
exercises the mock branch; `src/test/realMode.ts` re-imports a module with the flag off and
stubs axios, so the assertion is about *which request the client builds*.

The three now covered are the contracts changed in this sweep, and the choice matters:

- **`nlpCorrelation.chat`** is the one no backend guard can reach. `message` is a query
  parameter and `conversation_history` is the **body**, because the handler declares it
  `Optional[List[Dict[str, str]]]` and FastAPI reads complex types from the body. The
  query-param guard flagged it while it was in the query — and could say nothing about
  whether it subsequently landed in the body. Only a test that inspects the outgoing
  request can.
- **`transportation`** — `organization_id` gone from carriers, drivers and shipments.
- **`yard.getDockDoors`** — no `workcell_id`, and no parameter at all, since the column
  it filtered on does not exist.

All three are mutation-tested by reinstating the old request shape. Backend guards catch
a reintroduction from the server's side; these catch it in the suite where the change
would actually be made.

**The third leg of the frontend/backend contract — response shape — came back clean.**
Its siblings check the path exists and the query parameters are declared; neither says
anything about what comes back. An endpoint returning `{items, meta}` to a call typed
`Carrier[]` is a runtime `.map is not a function`; the reverse reads `.items` as
`undefined` and renders an empty list. TypeScript cannot catch either, because the type
argument to `api.get<T>` is an assertion about JSON rather than a checked fact.

**86 typed calls, zero mismatches** — the FS-99 envelope migration evidently landed on
both sides. The guard exists so the next one cannot half-land.

Its first run reported one mismatch that was not real: it treated any object with an
`items` property as a paginated envelope, and `SuggestedQuestionsResponse` legitimately
has `questions`, `items`, `context_summary` and `intelligence`. An envelope now requires
`items` **plus** a pagination sibling. Third detector in this document to need correcting
before its output was worth anything.

**`health.py` was split rather than converted, and the distinction is the point.**
`/admin/system/status` is admin-gated with a real user and was on `get_db`, so its
`assets` and `alarms` counts — both FORCE RLS — came back **zero** regardless of what
existed. An engineer's status page reporting no active assets on a running platform reads
as an idle system, not a broken query. It is now tenant-scoped.

The other four sites stay on `get_db` deliberately: `/health/live`, `/health/ready` and
`/health/startup` are unauthenticated probes and cannot resolve a tenant from a user they
do not have, so they read only tables without a policy. A uniform conversion would have
turned three working probes into 500s. Pinned in both directions.

**The core product surfaces were then swept for the same failure, and came back clean.**
One organisation seeded with an asset, an alarm and an operation, then every main
authenticated read exercised against a real database: `dashboard/overview` reports
`total_assets: 1, active_alarms: 1`, `alarms/active` and `operations/active` each count 1,
and the remaining zeros are tables that were not seeded. So the empty-page class does not
extend past the routers already fixed — worth recording, because "swept and clean" and
"never checked" are indistinguishable afterwards.

**One honesty gap did come out of it, in `health.py`.** `_check_ingestion` read
`MAX(assets.last_seen)` and published it as `latest_asset_seen_at`. It runs from the
**public** readiness probe, which has no authenticated user and therefore no tenant
context, so on a `NOBYPASSRLS` role that query returned NULL regardless of how much data
existed. The report then said `latest_asset_seen_at: null` — which reads as "no asset has
ever been seen", a different and false statement from "this figure is not obtainable
here". A monitoring endpoint is the worst place to blur those. `telemetry` has no policy
and was already the primary signal, so the asset read is gone and no verdict changes; a
per-tenant asset figure belongs on an endpoint where a caller, and therefore a GUC,
exists.

**The audit trail and the GDPR records were blank for the same reason.** `audit_logs`
and `data_processing_records` have carried tenant policies since migration 011, and every
handler in `audit.py` and `gdpr.py` ran on `get_db` — so both surfaces returned **zero
rows, including for the caller's own organization**. An audit trail reporting no activity
is the one thing an audit trail must never do, and from outside it is indistinguishable
from a quiet system: HTTP 200, empty list.

`gdpr.py` is the sharper illustration of why the application layer alone cannot save you:
its handlers filtered on `current_user.organization_id` **correctly**, and it made no
difference, because RLS had already removed the row.

Fixing `audit.py` also settled a design question rather than just a dependency. It carried
an unreachable branch — `if current_user.role != "admin"` under a `require_admin` gate —
written for a cross-organization admin view. One tenant's admin reading another's audit
trail is precisely what an audit trail should preclude, so scoping is now the caller's own
organization; genuine cross-org access needs the super-admin role that does not exist yet.

RLS on the four unprotected tables is now in place** — migration 051, ENABLE + FORCE
with a `tenant_isolation` policy each, so the application filter and the database policy
finally line up with the two-layer model `app/core/tenant.py` describes. Two details
mattered: the policy does **not** cast to `::uuid` (unlike 011/033) because
`organization_id` is `character varying` on these four and casting would raise on every
row; and FORCE is set because without it the table owner bypasses the policy, which makes
`relrowsecurity = true` read as protected while the application's own connection is
exempt.

The writer audit that gates this came out clean: nothing outside `app/api/` touches these
tables except `seed_demo_data.py`, which sets no tenant GUC — but it already writes
`assets` (ENABLE + FORCE since 011) and defaults to SQLite, so it does not work against
Postgres RLS today and this changes nothing for it.

**The transportation endpoints turned out to fail the OTHER way.** `get_carriers`,
`get_drivers`, `get_shipments`, `get_routes` and `geotab.get_fleet_summary` all took
`organization_id` as a required client-supplied query parameter — the IDOR shape — but
never leaked, because their tables have ENABLE **and FORCE** RLS and the handlers set no
GUC. The policy filtered every row, so **each returned an empty list to every caller,
including for its own organization**. Verified against a real database: listing carriers
with the caller's own org id returned nothing while the row sat in the table.

That is the same mistake as `get_vehicles` — one wrong dependency — producing the exact
opposite result, decided only by whether the table happened to carry a policy. A leak and
a permanently-empty page are indistinguishable from a status code, which is why both are
now pinned by tests that assert the caller sees its OWN rows as well as not seeing
anyone else's. The frontend stopped sending the removed parameter, and the
`organization_id`-from-localStorage helper it needed went with it.

## 11. A globally-keyed table read as if tenant-scoped — **1 live PII disclosure**

Every tenant sweep so far chased **reads on tenant-partitioned tables**. This one is the
opposite shape: a table deliberately NOT partitioned, whose contents are nonetheless
tenant-sensitive.

**Swept:** write paths (POST/PUT/PATCH/DELETE) touching org-scoped tables that have no
RLS to fall back on — the gap left after migration 051 covered the fleet tables. Four
tables qualify: `api_keys`, `error_events`, `users`, `vehicles`.

`api_keys.revoke_api_key` is **correctly scoped** (`APIKey.organization_id ==
current_user.organization_id`), and most apparent `users` hits were the same
`Depends()`-annotation false positive that has recurred throughout this document.

**`error_events` is the real one, and it is not a missing filter.** `fingerprint` is the
PRIMARY KEY — one row per distinct error for the entire platform — so the triage view is
cross-tenant *by construction*, and `require_admin` means a **tenant** admin, since no
platform-admin role exists. Any tenant's admin could therefore read any other tenant's
`message_sample` and `traceback_sample`, and PATCH its status.

Verified against a real database: org A retrieved a row owned by org B whose message
carried a customer identifier and whose traceback carried a payment-card value. Exception
text and tracebacks are the two fields most likely to contain customer data, precisely
because nobody chooses what goes into them.

**The module already flagged the question** — *"the API is not tenant-filtered (open
question flagged to the manager)"*. What it lacked was evidence of what was exposed, which
is the difference between a design question and a disclosure. A question can wait; a
disclosure of another tenant's PII should not.

**Fixed by redaction, not by scoping**, and the distinction matters. Filtering the view by
`organization_id` would be wrong: with `fingerprint` as the key, one row is shared by every
tenant hitting that bug and its `organization_id` names only one of them, so a filter would
hide errors that genuinely are the caller's. Only the two payload-bearing fields are
withheld, only from a viewer in a different organisation. Counts, route, method and status
stay visible — that is the triage value, and it carries no payload. A row with no
`organization_id` is platform-level and stays visible to everyone. The list endpoint was
already safe; it returns no samples at all, now pinned.

If a platform-admin role is added, gate the samples on that rather than dropping the check.

**A guard of this document's own making was also found blind.** `test_tenant_session_guard`
derives its RLS table set by grepping migrations for a literal
`ALTER TABLE <name> ENABLE ROW LEVEL SECURITY` — and migration 051 enables RLS through
`EXECUTE format('ALTER TABLE %I …')` over a table array. All four tables that migration
protects were invisible to it, so a `get_db` regression on any of them would not have been
flagged. Parsing SQL text is a proxy for asking the database, and this was the cost of the
proxy; the parser now understands both forms and a test pins it. Same lesson as rule 6, in
a place that had already learned it.

## 12. A worker branch that writes without binding a tenant — **1 live silent no-op**

Every tenant sweep so far looked at API handlers. A worker has no request and no user, so
it sets `app.current_org_id` by hand from the message it is processing — and nothing in
the API guards checks that.

**Swept:** all five workers. Three bind a tenant; `ota_rollouts` and `health_server` touch
no tenant data. Two findings, one live.

**LIVE: the edge-agent heartbeat updated nothing.** `_process_agent_heartbeat` runs
`update(Asset)` to record fleet-version fields. `_process_message` binds the tenant for the
telemetry/state/alarm branch — but the agent-status branch **returns before reaching that
code**, so this path ran with no GUC at all. RLS filters a WRITE silently rather than
raising, so the UPDATE matched zero rows on every heartbeat and the worker logged
`updated_assets=0`: an accurate log of total failure, which nobody reads because nothing
looks wrong. Verified against a real database — `agent_version` stayed NULL after a
heartbeat naming the asset directly. The binding now lives inside the handler, next to the
`organization_id` it derives from, so it cannot be lost to another early return.

**LATENT: `export_delivery` bound the tenant session-scoped (`false`).** That value stays
on the connection after the session closes and rides it back into the pool, so the next
task inherits a stale tenant unless it sets its own. Every operation there does set its
own, so nothing was leaking — but that is a property of today's code rather than of the
mechanism, and it is the same footgun `get_tenant_db` had to be fixed for. Both sites are
transaction-local now.

**HOW THE LIVE ONE WAS FOUND is the part worth keeping.** A guard written to assert
something else — that the ingestion message path commits exactly once, so a
transaction-local GUC cannot be dropped mid-message — failed on a count of 2. The second
commit was a different branch, so the assertion was too crude. But reading that branch to
correct the test is what exposed the missing binding. **The wrong assertion pointed at the
right place**, which is an argument for writing the crude version early rather than
waiting to write the precise one.

Also checked and clean: the compliance worker has 14 sessions and 13 `_set_org` calls, and
the one without hands its session to `build_report_payload`, which binds the tenant itself.
That exception is now asserted, along with the delegation it depends on, so the two cannot
drift apart.

## 13. A rule enforced on one route and leaked by its neighbour — **2 public probes**

`test_route_auth_walk.py` already proves no route answers 2xx without a token, with 18
public routes allowlisted and reasoned. What nothing checked was **what those 18 return**.

**Swept:** every allowlisted public route, read as an anonymous caller. Two disclosed
internal topology:

```
/health/kafka  503  "error: KafkaConnectionError: Unable to bootstrap from
                     [('redpanda', 29092, <AddressFamily.AF_UNSPEC: 0>)]"
/health/ready  503  same string, inside the per-component checks
```

Internal broker hostname, port, and the technology in use — to anybody who can reach the
endpoint, and precisely when the broker is down, which is when someone probing would be
looking.

**What makes this a defect rather than a choice** is that the rule was already written,
one function away, on `/health/detailed`: *"Auth-gated for the same reason as
/health/system: the per-component report (broker/redis/ingestion state, connection error
strings) is recon-useful. Probes use /health/live|ready, which stay public."* The gating
was right and the reasoning explicit. The same strings simply escaped through the routes
named as the safe alternative. **A rule enforced in one place and leaked by its neighbour**
is the recurring shape of this entire document — the class-8 endpoint that a hand fix had
already visited, the class-11 disclosure flagged in a docstring, the class-12 branch that
returned before reaching the binding its sibling had.

**The fix withholds nothing from anyone entitled to it.** A probe consumer needs the
status — Kubernetes reads the code, not the body. An operator reads the logs or
`/health/detailed`, both of which still carry the full exception text. Statuses that are
already coarse pass through; anything carrying a payload after a colon collapses to its
first word, so `error` survives and the hostname does not.

**A second inconsistency fell out of it.** The readiness probe's *cached* not-ready branch
returned a bare `"Service not ready"` while the uncached branch returned per-component
checks — so the probe's response shape depended on whether the cache had expired, and an
operator hitting it twice got two different answers, the second saying nothing about which
component was down. Both branches now return the same sanitised structure.

## 14. App-permitted values a CHECK constraint rejects — **clean, and only half guardable**

The write-side twin of class 1. There, a response model was stricter than its column; here,
the application permits a value the database refuses. A column defaulting to `"queued"`
under a constraint allowing `('pending', 'running', 'done')` rejects every insert that
omits the field — an IntegrityError from a value the application chose for itself.

Migration 050 made this newly relevant: it copied 39 ORM defaults into SERVER defaults, so
a bad default is no longer one insert path's problem but the column's.

**Swept in two halves, and only one of them is shippable.**

**ORM defaults vs CHECK — clean, and now guarded.** Every scalar `default=` on a column
carrying a value-list constraint, compared against the live schema. Zero violations. This
half is precise because an ORM column names its own table.

**Pydantic `Literal`s vs CHECK — clean, and deliberately NOT guarded.** The broad version
matched request-model fields to constrained columns by NAME, and produced six findings,
every one false. `StatusUpdateRequest.status` was flagged against `agent_releases`,
`agent_rollouts`, `model_registry` and two others — tables it never writes to, which merely
also have a `status` column. `ScheduledComplianceReportCreate.frequency` was flagged
against `scheduled_exports`, a different feature's table; its real target
(`scheduled_compliance_reports`, migration 017) allows all five values, and the handler
validates against the matching five-value set.

Making that half trustworthy needs a request-model-to-table mapping, and unlike
`FooResponse -> Foo` there is no naming convention to derive one from. **So it was run,
found nothing, and was not shipped.** A guard with six known false positives trains people
to ignore it, which costs more than the coverage is worth — and this document already
records three detectors that had to be corrected before their output meant anything.
Recording the negative result keeps the work from being repeated without pretending it is
enforced.

## 15. A naive datetime crossing an API boundary — **9 calls, one module**

**Swept:** every `datetime.now()` and `datetime.utcnow()` in `app/`. Nine were naive, all
in `model_monitoring.py` — the only such island against 483 timezone-aware constructions
elsewhere.

**Inside Python it was harmless, and that is why it survived.** The drift and performance
histories are in-memory, both sides of every comparison were naive, and nothing raised.

**The hazard is at the boundary.** Those calls serialise to ISO strings with no offset,
while every other endpoint emits `+00:00`. `new Date("2026-07-28T02:15:00")` is parsed by
JavaScript as LOCAL time; the same string with `+00:00` is UTC. The same instant would
render hours apart depending on which endpoint returned it — silently, with no error
anywhere. No frontend consumes those routes today, which is the only reason it never
showed, and exactly the kind of "only reason" this document keeps finding.

The louder failure mode already has a scar in the codebase: `fleet_logistics._aware()`
exists to coerce naive/aware mismatches away, because Postgres returns aware timestamps
and SQLite returns naive ones, so the same code path differs by backend.

**The detector had to be corrected twice, in both directions.**

A grep for `datetime.now()` found the nine — and *missed nothing*, but a grep-based guard
would have flagged its own explanatory prose, so the guard uses the AST instead. The AST
version then immediately flagged **four uses of SQLAlchemy's `func.now()`** in
`app/db/models.py`, which renders SQL `NOW()` and returns an aware `timestamptz` on
Postgres — entirely correct. It matched on the method name without reading what it was
called on. Flagging those would have meant "fixing" working code.

So the guard now reads the receiver, and both mistakes are pinned as tests: prose is not a
call, and `func.now()` is not `datetime.now()`. That is the fifth detector in this document
to need correcting before its output was worth anything — which is no longer a surprising
result and is why rule 3 exists.

## 16. A channel the route-walk cannot see — **2 live defects on the websocket**

Every tenant sweep in this document looked at HTTP handlers. `/ws` is not one, and the
guard that enforces authentication everywhere else **skips it by construction** — its own
comment reads *"skips WebSocketRoute (/ws) + mounts"*.

Two live defects, both confirmed against the running app before the fix.

**Anyone could subscribe to any organisation, with no token at all.** The handler opened
with `if token:`. With no token, `user` stayed `None`, control fell through to the
client-supplied `organization_id`, and the connection was accepted as "anonymous" — the
log line even says so. A caller who could reach the endpoint received another
organisation's telemetry, alarms, state changes and command statuses **continuously**.

**An authenticated user could name someone else's organisation.** The binding read
*"default to the user's organization if not specified"*, so a supplied value took
**precedence**. Org A's user passing `?organization_id=<org B>` was added to org B's
broadcast set. This is the same IDOR shape already removed from yard, transportation and
logistics_correlation — on a channel that streams rather than answering once.

**The manager was never the problem.** `active_connections` is keyed by organisation and
`broadcast_to_organization` writes only to that key. It was correct, and it was told the
wrong key. Which is the sharper version of a pattern this document keeps recording: the
mechanism is sound and the caller supplies the wrong input, so nothing downstream can
detect it.

A mismatched `organization_id` is now **refused** rather than silently replaced.
Substituting the correct organisation would leave a caller believing it had subscribed to
something it had not — and this codebase already had enough silently-ignored parameters.

**The same sweep found the HTTP ingest endpoint forwarding nothing.** `/api/v1/edge/ingest`
resolves each reading's organisation to pick a Redpanda topic, and that lookup reads
`assets` — FORCE RLS — through a session with no tenant context. It returns `None` for
every asset, so `by_org` stays empty, nothing is published, and the response still reported
`accepted: N`. Verified: `_resolve_org` returns None for an asset that demonstrably exists.

**It is not a live outage, and checking that mattered.** The edge agent publishes straight
to the broker; nothing calls this endpoint. So the proportionate fix was honesty rather
than machinery: `accepted` and `forwarded` are now separate counts, and an unresolved
reading logs loudly. Building a policy migration for a path nobody calls would have been
speculative work; leaving a success response that implies delivery would have been the
class this whole document is about.

**A second, latent defect there is recorded rather than fixed**, because fixing it needs a
decision. The organisation comes from the ASSET a reading names, with no check that the
asset belongs to the submitting agent — so a valid agent could route readings into another
tenant's stream. `assets.agent_id` exists and looks like the binding to enforce against,
but **nothing ever populates it**: it is NULL for every row. Keying a policy on it would
have replaced one silent failure with another, which is why the column was checked before
the design rather than after.

**A note on the mutation test.** A hand-written reconstruction of the old code caught
nothing: the later `user_org` lookup still refused the connection, so anonymous access
stayed blocked for a different reason and the test passed. Reverting to the **actual**
pre-fix file failed exactly the two assertions naming the two defects. Reconstructing a
defect is a guess about what it was; restoring it is not.

## 17. SQL built by interpolating a value into quotes — **8 sites, all dormant**

`text(f"... WHERE id = '{asset_id}'")` assembles a quoted literal by string formatting. An
apostrophe in the value breaks the statement; a crafted one rewrites it. The codebase has
paid for this once already — `tactical_engine._is_maintenance_mode` carries a comment
recording that `' OR '1'='1` used to match every row.

**The check is "interpolated INSIDE quotes", not "f-string in SQL", and the distinction is
what makes it shippable.** Sixteen `text(f"…")` calls in `app/` are entirely correct,
because identifiers and intervals *cannot* be bound:

| Interpolated | Source |
|---|---|
| `{_HISTORIAN_POLICY_COLUMNS}` | a module constant |
| `{sort_col}`, `{order_sql}` | dict lookup and a ternary |
| `INTERVAL '{seconds} seconds'` | an int from `AGGREGATION_SECONDS` |
| `FROM {view_name}` | three hardcoded call sites |

Banning f-strings outright would flag all sixteen, and a guard with sixteen false positives
is one nobody reads — the same reasoning that kept class 14's `Literal` half unshipped.
Quotes are the signal: they mean the value is *data*, and data can be bound.

**Found eight, all now parameterised:**

- **`device_provisioning` (5)** — an INSERT interpolating `certificate_pem` and
  `json.dumps(metadata)` as quoted literals, plus approve, revoke and two lookups.
- **`feature_extraction` (3)** — `asset_id` and timestamps, where `asset_id` arrives from
  edge telemetry: the same untrusted source the tactical-engine fix was about.

**Both modules are dormant, and one is worse than dormant.** `device_provisioning` is
referenced by nothing *and cannot be imported*: it reads `settings.CA_KEY_PATH`, which does
not exist — the setting is `EDGE_CA_KEY_PATH`. That was verified against the pre-existing
file before claiming it, since it would have been easy to mistake for damage from this
change.

They were fixed anyway. The cost is small, and a dormant injection is precisely what gets
woken up when somebody wires a feature back on — which this document has already watched
happen once, when restoring the analysis-session surface made a latent
`simulated`-flag-dropping bug live.

---

## Writing a sweep that is worth trusting

Both false starts above came from the same mistake — trusting the scan instead of testing
one of its findings. The habit that catches it:

1. **Verify one hit empirically before believing the count.** A scan that reports 8
   defects and cannot demonstrate one is a broken scan.
2. **Test the detector first.** If the helper deciding every assertion is wrong, the
   result is meaningless in one direction or the other.
3. **Guard against vacuity.** Assert the sweep discovers something — a rename or a moved
   module otherwise makes it pass while checking nothing.
4. **Mutation-test the guard.** Reintroduce the defect; the test must fail. A mutation
   that lands on the wrong line proves nothing, so check the mutation applied where you
   meant.
5. **Record a negative result.** It is the only thing that stops the next person redoing
   the work.
6. **Ask the system, not the model of the system.** A guard that reads ORM metadata is
   reporting what the declaration claims. This one flagged 158 fields because it trusted
   `column.server_default`, while the database — the thing that actually decides whether
   an INSERT can write NULL — had defaulted 109 of them. Where a real instance is
   reachable, read it.
7. **Distrust a clean result from a detector with exclusions.** Every exclusion is a
   claim about what cannot happen, and class 1's two — "a Python-side default makes a
   column safe" and "a response model lives in its router's module" — were both false.
   A sweep that finds nothing should be read as *"nothing, within these exclusions"*, and
   the exclusions are the part to attack.
8. **Measure the object the code operates on, not one that contains it.** A flaky
   assertion in `test_signed_report_downloads` was "ruled out by measurement" — the
   measurement decoded the whole 480-character JWT rather than its 43-character signature
   segment, compared garbage to garbage, and reported 0/200 collisions. Measuring the
   segment gives 18/400. An HS256 signature is 32 bytes in 43 base64url characters, so the
   final character carries two unused bits and four characters decode identically; the
   test's `token[:-1] + "a"` left the signature valid 4.5% of the time. The form of the
   check was rigorous and it was pointed at the wrong thing, which is indistinguishable
   from rigour until someone re-derives it.
9. **A guard you cannot make precise is worse than a recorded result.** Six false
   positives train the reader to skip the output, and the next real finding goes with it.
   If the mapping the detector needs does not exist, run the sweep, write down what it
   found, and say why it is not enforced — see class 14.
10. **Mutate by reverting, not by reconstructing.** A hand-written "undo" of the
   websocket fix caught nothing, because the reconstruction was not the original — a
   later check still refused the connection and the test passed for the wrong reason.
   Restoring the actual prior file failed exactly the right assertions. If the old code
   is still in git, use it.
11. **Fix forward, not down.** When a corrected sweep surfaces a pile of pre-existing offenders,
   weakening 158 contracts to make the guard pass is the wrong direction. Record a
   shrink-only baseline that fails on a new offender AND on a stale entry, and fix the
   cause — here, server defaults in the database.

---

## Open observations, not yet tickets

**RESOLVED, as a checked record rather than a fix.** The split is now pinned by
`test_service_lifecycle_is_declared.py`: seven services started by `main.py`, five
recorded as dormant *with the reason for each*. A new singleton nobody starts fails the
test; starting a dormant one without updating the record fails it too, which forces the
consequence to be read rather than discovered.

The sharpest of those consequences has its own assertion. `cloud_gateway` holds a
10,000-entry in-memory list that only its `_flush_loop` drains, and four dormant services
queue into it. That costs nothing today — verified, not assumed: every producer is itself
dormant or unwired. Start any one of them **without** starting `cloud_gateway` and queued
events accumulate and are silently dropped, so the guard fails on exactly that ordering.

Making an invisible state checkable is the point. `tactical_engine` reported dispatches it
never made, and the only reason it never hurt anyone was that nothing started it — a fact
recorded nowhere and discoverable only by grepping.

**Five service singletons have a `start()` that no process calls** — `cloud_gateway`,
`egress_scheduler`, `mlops_pipeline`, `strategic_engine`, `tactical_engine` — against
seven that `main.py` does start. They are the edge-AI stack, so running them in the API
process may well be wrong; the point is that nothing runs them *anywhere*, and the code
around them does not say so. Two consequences are already handled above:
`tactical_engine` now refuses to claim a dispatch (class 5), and the live quarantine
path was fixed independently of `cloud_gateway` (class 6).

The rest is a decision, not a bug fix: either these belong to a process that does not
exist yet, or they should say they are dormant. Until then, anything queued into
`cloud_gateway` accumulates in a 10,000-entry in-memory list that sheds the oldest and
is never flushed.

**`schema_registry` is unwired.** Nothing in the running app imports it, so its
`validate_payload` / `_quarantine_payload` / `_persist_to_dlq` chain never executes.
Worth knowing before anyone wires it: `_persist_to_dlq` is documented *"Persist to dead
letter queue (SQLite or file)"* and does neither — it forwards to `cloud_gateway`, which
nothing drains. Same shape as class 6, one level of indirection deeper.

**Seven ERP modules, ~3,800 lines, imported by nothing.** Measured, not estimated —
`sap_data_extraction` (641), `oracle_data_extraction` (552), `dynamics_data_extraction`
(714), `erp_database_replication` (492), `sap_webhook_integration` (501),
`oracle_correlation_patterns` (492) and `dynamics_correlation_patterns` (404). No module
imports any of them, and no public symbol they define is referenced anywhere else.

**One of them turned out to be finished work that was never plugged in.** Oracle's
`transform_invoice` / `transform_shipment` and its `analyze_invoice_anomalies` /
`analyze_shipment_correlation` are matched pairs — the transformer emits exactly the five
fields the analyzer reads, verified field-by-field. They were simply absent from
`CORRELATION_ROUTES`, so every Oracle sync reported `skipped: unrouted` while the code to
produce its correlations sat unused. Registering them took a per-vendor analyzer-class
lookup and four registry lines. That closes most of task #33 in the current pool.

**All seven have now been checked, and none should simply be deleted.**

| Module | Verdict |
|---|---|
| `oracle_correlation_patterns` | **wired** — matched transformers already existed |
| `dynamics_correlation_patterns` | **wired**, after correcting three field names |
| `erp_database_replication` | already refuses honestly: `start_replication` raises `NotImplementedError` because its CDC helpers are stubs. Nothing to do |
| `sap`/`oracle`/`dynamics` `_data_extraction` | **superseded, annotated in place** |
| `sap_webhook_integration` | **reviewed** — three log-only `_create_alert_*` helpers renamed `_log_*` (class 5 above); the live webhook path remains `api/erp_webhooks.py` |

The three extraction modules are not duplicates of `run_erp_sync` — they store the
**normalised** record, where `run_erp_sync` stores the **raw** one and transforms at
analysis time. Raw storage is the approach that survived, because it is lossless: three
field names in the Dynamics invoice transformer were wrong, and with raw storage that was
a code fix rather than a re-sync. Wiring them back would create a second ingestion path
writing the same table in a different shape, which is worse than either alone. Each now
carries a module-level note saying so, since the risk is not that they sit unused but that
someone starts one.

So the tally is: of seven modules, **two were finished work worth wiring**, one was
already honest, three are superseded and now say so, and the last one carried three
helpers whose names claimed work they never did. All seven are now reviewed. A straight
delete would have discarded the two.

**Dynamics was then registered too — after correcting three field names.**
`transform_dynamics_product` was already correct (all eight columns verified against
Microsoft's product table reference). `transform_dynamics_invoice` was not, and every
error would have failed silently, because an unmapped field is `None`, the analyzer finds
nothing, and the sync reports a clean run over data it never read:

| Was | Problem | Now |
|---|---|---|
| `invoiceid` → `invoice_number` | that is the GUID primary key | `invoicenumber`, falling back to the GUID |
| `invoicedate` | **not a column on invoice** | `datedelivered`, falling back to `createdon` |
| `customerid_account` → `customer_id` | a navigation property for `$expand`, not a scalar | `_customerid_value`, the Web API shape |

Invoices and products are routed. Two Dynamics entities are deliberately not:
`project` is not a base Dataverse table (confirmed absent from a live environment;
Project Operations exposes `msdyn_project`), and `account`'s analyzer takes an account ID
rather than a record — its transformer *is* verified, all six columns real.

**That evaluation exposed a hole in the registry itself.** Field alignment is necessary
but not sufficient: the router calls `analyze(db, normalized_record)`, and an id-taking
analyzer would receive a dict. It would not fail loudly — the per-record `except` catches
it and counts a failure, so a whole sync would report `failed: 500` and look like bad
vendor data rather than a wrong registry entry. `test_erp_sync_correlation.py` now asserts
every registered analyzer's second parameter is a dict, and proves that check can fail by
naming a real id-taking analyzer that must never be registered.

**And registering the routes found two bugs in code that had never run.** Nothing called
these transformers, so nothing exercised them. `transform_manufacturing_order` referenced
`sap_po` while its parameter is `sap_mo` — a `NameError` on every call, in a route that
was **already registered**. It would not have surfaced as a crash: the per-record handler
catches it and counts a failure, so an entire SAP manufacturing sync would have reported
`failed: N` and read as bad vendor data. Its status map also listed `"DLV"` twice, so the
second entry silently won and `"delivered"` was unreachable.

Every registered transformer is now called once with a realistic vendor record, which is
the cheapest possible check that a route's central claim — *this transformer works* — is
true.
