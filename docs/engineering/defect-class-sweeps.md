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

## The forty-two classes

The first five were all originally found in ERP. The sixth came out of the fifth, the
seventh out of two failing tests that turned out to share a cause, and the eighth out of
the seventh — the same "we are testing a double, not the thing that ships" shape, moved
to the frontend/backend seam.

The last six are one question asked six ways: **what does this code claim when it does not
know?** They ran from a compliance verdict computed over an empty driver list, through five
more mechanisms that turn absence into a reading, out to a widget that disappears, a claim
rendered beside its own error banner, and finally to the action side — a button whose
failure reaches nobody. Each was found by taking the previous one's shape seriously enough
to ask where else it could live.

| Class | Swept | Found elsewhere | Guard |
|---|---|---|---|
| Response model stricter than its columns | all 61 API modules | **49 real, now 0 — the sweep was wrong twice** | `test_api_response_schema_matches_columns.py` |
| Pagination truncation | list endpoints | **3 ERP endpoints** | `test_erp_platform_integration_realdb.py` |
| Invented vendor endpoints | all 8 connectors | ERP only | `test_erp_no_invented_endpoints.py` |
| Silent success | all of `app/` | **1, live** | `test_logistics_sync_dashboard_honesty.py` |
| A name that claims a side effect | all of `app/` | **1, in the control path** | `test_helper_names_match_behaviour.py` |
| Data reported as kept, but discarded | quarantine/DLQ paths | **1, live, on ingestion** | `test_edge_ingest_quarantine_retention.py` |
| A test double that reimplements what it stands in for | every `get_tenant_db` override | **4 copies, hiding an RLS bug** | `test_tenant_guc_survives_commit_realdb.py` |
| Frontend calling endpoints the backend does not serve | all 196 real-mode calls, axios and raw `fetch` | **4, one wired to a live button** | `test_frontend_calls_real_endpoints.py` |
| Response shape disagreeing with the frontend's type | 86 typed calls | **none** | `test_frontend_response_shapes_match.py` |
| Query parameters the endpoint does not declare | 52 param-sending calls (all of them) | **5, plus 4 IDOR-shaped endpoints** | `test_frontend_query_params_are_declared.py` |
| An org-scoped table with neither a filter nor RLS | `get_db` handlers on org tables | **~60 handlers: 2 leaks, an IDOR, and whole surfaces returning nothing** | `test_tenant_session_guard.py` + 5 real-DB suites |
| A globally-keyed table read as if tenant-scoped | tables keyed on something other than org | **1 live PII disclosure** | `test_error_triage_sample_redaction_realdb.py` |
| A worker branch that writes without binding a tenant | every worker write path | **1 live silent no-op** | `test_worker_tenant_guc_hygiene.py` |
| A rule enforced on one route and leaked by its neighbour | public/unauthenticated probes | **2 probes disclosing broker host and port** | `test_public_probes_do_not_disclose.py` |
| App-permitted values a CHECK constraint rejects | Literal types vs CHECK constraints | **clean; 6 false positives, recorded not enforced** | none — see class 14 |
| A naive datetime crossing an API boundary | every `datetime.now()` in `app/` | **9 calls, one module** | `test_datetimes_are_timezone_aware.py` |
| A channel the route-walk cannot see | the websocket surface | **2 live: anonymous access and cross-tenant subscribe** | `test_websocket_tenant_binding.py` |
| SQL built by interpolating a value into quotes | every raw SQL construction | **8 sites, all dormant** | `test_sql_is_not_built_by_interpolation.py` |
| A provenance flag left to its default | every model declaring one, all constructions | **1, live, on the error path** | `test_provenance_flags_are_always_set.py` |
| A qualifier the frontend never reads | every boolean qualifier on the wire | **3 fields, 2 defects, both live** | `test_qualifiers_reach_the_frontend.py` |
| A cache key that omits what the fetch varies on | every `useQuery` in the frontend | **clean — 0 of 30+; nearly introduced during this work** | `queryKeysAreComplete.test.ts` |
| A write whose result the UI never re-reads | every `useMutation` and invalidation | **3 live: ERP sync, command history, emergency stop** | `ERPIntegrations.sync.test.tsx`, `CommandPanel.test.tsx` |
| A capped list that cannot say it was capped | every `limit`-bearing GET | **12 bare arrays; `/rul` fixed, the rest recorded** | `test_rul_truncation_is_reported_realdb.py` |
| An audit write with no tenant bound | every `audit_logs` writer | **4 of 8 — exports, bulk jobs and flag changes recorded nothing** | `test_audit_writers_bind_a_tenant_realdb.py` |
| A handler that builds its own unbound session | every inline `AsyncSessionLocal` in `app/api` | **5 live: 3 endpoints 404ing on your own asset, 2 reporting an empty fleet** | `test_tenant_session_guard.py` (second idiom) |
| A request body the endpoint's schema rejects | every frontend POST/PUT/PATCH | **clean — 7 of 15 checkable, recorded not enforced** | none; see class 25 |
| An endpoint the README documents but the app never served | all 124 API-Reference rows | **22 wrong — 404 for anyone who followed them** | `test_documented_endpoints_exist.py` |
| A source file the docs point at that is not in the repo | every filename cited in three docs | **1 fiction, 5 omissions** | `test_documented_files_exist.py` |
| A frontend catch that swallows a failure | every `catch` in `src` | **clean — all 10 report or recover** | none; see class 28 |
| A verdict computed from emptiness | every querying component + compliance verdicts | **14 live: 13 UI, 1 server-side** | `failureIsNotEmptiness.test.ts`, `test_carrier_compliance_needs_something_to_assess.py` |
| The same verdict, five more mechanisms | HOS/OEE/grade paths on both sides of the wire | **8 live: NULL coercion, empty iteration, SQL 3-valued logic, an empty-set average, a threshold on a percentage of nothing** | `test_logistics_compliance_status_realdb.py`, `test_oee_failure_is_not_zero.py` |
| A tenant-scoped write that matched nothing | every unchecked `UPDATE` in `app/api` | **2 live: error triage cross-tenant, maintenance mode 500ing on a column that did not exist** | `test_maintenance_mode_realdb.py`, `test_error_triage_sample_redaction_realdb.py` |
| A widget that vanishes when its query fails | every JSX gate on a query-derived value | **1 live: the fleet page's vehicle map, with no string to grep for** | `failureIsNotEmptiness.test.ts` (second detector) |
| A claim rendered beside a handled error | every falsy ternary branch / coerced count outside an error branch | **6 live: gateway mTLS + queue, model badge, MLOps ×3, dashboard heading, strategic tiles** | the per-page suites; rule 24 |
| A mutation whose failure reaches nobody | every `useMutation` in the frontend | **9 live across 3 files, incl. delete-user and a stale connection-test success** | `mutationFailureIsVisible.test.ts` |
| A tenant taken from the request BODY | every route handler in `app/api` | **14 live; 13 saved by a policy, `vehicles` had none and wrote the row** | `test_no_handler_takes_its_tenant_from_the_body.py` |
| A tenant taken as a client-supplied PARAMETER | same, second variant | **8 live: 6 geotab + operations + yard detention, all Optional so a bare request filtered by nothing** | same guard, parameter check |
| A tenant filter applied CONDITIONALLY | `if org is not None: … where(…)` | **4 live in one router: an unscoped DELETE, two leaking reads, a latent dispatch fan-out** | `test_notification_tenant_isolation_realdb.py` |
| A tenant table with no policy | every table carrying `organization_id` | **6 with no RLS, 5 with RLS but no FORCE; `vehicles` closed by migration 055, 9 recorded** | `test_every_tenant_table_has_a_policy.py` |
| A response model declaring a field its table lacks | 34 `*Response` models | **clean after the DockDoor audit — 5 fields deleted there** | `test_response_models_match_their_tables.py` |
| A TS field the wire never carries | every `types/*.ts` field a component reads | **3 live: a relabelled odometer, a UUID slice shown as a work-order number, 3 of 5 cost figures** | `test_frontend_fields_exist_on_the_wire.py` |
| A field the compliance check reads that nothing writes | `hos_drive_hours_remaining` and its neighbours | **1 live, and the worst of the session: every fleet cleared of HOS violations** | `test_hos_remaining_is_derived.py` |

Twenty-nine of these carry a numbered section below. **Response-shape mismatch is the
exception**: it was swept in the same pass as the `get_db` work and came back clean, so
it is written up inside class 10 rather than given a heading of its own. The row stays in
this table because a clean result that is not listed is indistinguishable from a check
nobody ran — which is the whole reason this document exists.

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

## 9. Query parameters the endpoint does not declare — **4, and they exposed 4 more**

Class 8 checks that the path exists. This checks what is sent to it, and the failure is
quieter: **FastAPI ignores unknown query parameters silently.** A misspelled or invented
filter does not error — the endpoint returns the UNFILTERED set, and the caller renders it
as a filtered result. No stack trace; just the wrong rows.

**Swept:** every frontend call that sends query parameters. **52 calls checked, 0
skipped** — see *Reopened* below; the first pass reported 37 checked and 1 skipped, and
both numbers were wrong.

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

### Reopened: the guard's coverage number was itself a defect

The first version matched two shapes — an object literal and a bare variable — and
counted only the second as skipped. Everything else fell through both branches: it was
neither checked **nor counted**. Nine calls sat in that gap while the sweep printed "37
checked, 1 skipped" and looked complete. This is the class-4 failure (silent success)
applied to a detector, which is worse than an ordinary instance of it, because the whole
point of the guard is to be believed.

Two live defects were in the gap.

**`workcellsApi.list` sent `organization_id`** to `GET /api/v1/workcells/`, which declares
only `skip` and `limit`. The parameter was dropped silently, so the call returned the
caller's own workcells either way — a filter that had never filtered, in a query key that
could not affect the result. The organisation comes from the JWT; the argument is gone
from both the client and `useWorkcells`. It was invisible because the params were a
**ternary**, `params: organizationId ? { … } : undefined`.

**`authApi.getUsers` sent `skip` and `limit`** to `GET /api/v1/auth/users`, which declared
**no query parameters at all**. Both were discarded, so a caller asking for the first 25
of 300 users received all 300 — and read `hasMore` as `undefined`, which is falsy, meaning
"you have seen everything". It had, which is exactly why nobody noticed: the bug only
becomes visible as an organisation grows. Three of the five fields the declared
`PaginatedResponse<User>` type promises were never sent. It was invisible because the
params were the shorthand **`{ params }`**.

The handler now paginates for real, and `total` became a `COUNT` over the organisation
rather than `len(items)` — as a paginated field, the page length tells a 300-user
organisation it has 25 users and stops the caller from paging. Eleven real-DB assertions
in `test_auth_users_pagination_realdb.py`; reverting the handler fails eight of them.

**Fixing the server would have been half a fix.** The handler now defaults to 50, so the
admin table would have shown one page and given no sign that anyone was missing — the
same silent truncation wearing a different hat. `AdminPages` requests an explicit page
size, reports "Showing 20 of 120 users", and states the server's 200-row ceiling instead
of quietly ending the list.

**The guard now resolves variables** — from a local `const`, from later `params.x =`
assignments, from an inline parameter type, or from a named interface — scoped to the
enclosing function, because three functions in `analysisSessions.ts` each build their own
`params` and merging them would invent parameters no single call sends.

**The last skipped call turned out to be a detector bug too.** `platformCorrelation.attach`
posts `{ source_type, params }` — that is the axios **body**, since `post` takes
`(url, body, config)` while `get` takes `(url, config)`. The extractor read every
argument, so a body field named `params` was a query string as far as it was concerned.
Reading the config argument *by position* both removed that false-positive risk and closed
the last gap: **46 checked, 0 skipped**.

**And it had to learn about the casing seam, or it would have reported a fabricated
defect.** `historian.query` sends `assetId` to an endpoint declaring `asset_id`. That is
correct: `transformRegistry.ts` converts request params to snake_case for registered URL
prefixes. Keys under a registered prefix are now compared in both forms, and the prefix
list is read from the frontend source rather than hardcoded, so removing a registration
tightens the check instead of leaving a stale exemption. `_t` — a deliberate cache-buster
that the server is *supposed* to ignore — is the one named exemption.

### Reopened a second time: six calls the extractor could not see at all

Writing a real-mode test for `workcellsApi` — the fix from the first reopening — turned
up a third gap, and it had been hiding a fifth live defect.

`AssetListParams` declared `organizationId?: string` and `assetsApi.list` forwarded the
caller's object verbatim. `GET /api/v1/assets/` declares `workcell_id`, `asset_type_id`,
`is_active`, `skip` and `limit` — **no organisation**. So the parameter was dropped in
silence, in a type that read as a tenant filter, on the client every asset page uses.

The guard had reported "46 calls checked, 0 skipped" and could not see it. Its call
pattern required `<[^;{]*?>` between `api.get` and the parenthesis, and this call is:

```ts
api.get<{ items: Asset[]; meta: { total: number; … } }>('/api/v1/assets/', { params })
```

Braces and a semicolon inside the type argument, so the pattern matched **nothing** — the
call was not checked and not counted, exactly the failure mode the first reopening was
supposed to have closed. **Six calls were invisible that way.** The extractor now finds
`api.<method>` and *scans* for the opening parenthesis past a balanced type argument,
rather than pattern-matching up to it: 46 → 52.

**And fixing it produced a false positive out of my own comment.** The note added to
`AssetListParams` explaining the removal quoted that very call, and the field extractor
read `items` and `meta` from inside the comment as query parameters — while swallowing
the field that followed, because a key needs a `,`, `;` or `{` before it and a comment
line supplies none. Comments are now stripped before parsing, anchored to line starts so
a `https://` inside a string literal survives. That is method rule 14 again, one file
over from where it was written.

**A third gap, found while testing the audit page.** `AuditLogs.tsx` does not use the
shared axios client at all — it calls `fetch('/api/v1/audit/logs')` with a hand-built
`Authorization` header. The guard scanned only `src/api/*.ts`, so that page sat outside
**every** frontend-contract sweep in this repo: not skipped, not counted, never looked at.
Both of its endpoints turned out to be real, which is luck rather than coverage. The scan
now walks the whole `src` tree for raw `fetch` as well: 194 → 196.

**Rule 18 paid immediately.** The sibling guard, `test_frontend_calls_real_endpoints.py`,
carried the *identical* pattern and therefore the identical hole — while its docstring
claimed to check "183 real-mode calls across 22 modules". With the scanner it sees **194**:
fourteen calls had never been checked by the sweep that exists to prove every path is
real. All 194 pass, so nothing was hiding there, but the coverage claim was false and only
became true after looking. The third sibling, `test_frontend_response_shapes_match.py`,
was checked too and does NOT share the flaw — its pattern tolerates braces because there
is no `>` inside one. Verified rather than assumed.

**The fix is runtime, not just type-level.** Deleting the field from the interface is a
compile-time guarantee; forwarding the caller's object still puts any extra key on the
wire. `assetsApi.list` now builds the five declared parameters explicitly, and
`assets.realmode.test.ts` passes an organisation id in anyway and asserts it does not
reach the request.

*That test's first version was worthless and is worth recording as such:* it called
`list()` with no argument, and the pre-fix code only attached `organization_id` when
given one — so it passed against the defect. Passing the argument is the whole test.

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

## 18. A provenance flag left to its default — **1, live, on the error path**

`SessionChatResponse.simulated` defaults to `False`, and that default is a **claim**:
*this was a genuine inference*. Two of the three constructions in `session_chat` carried
the engine's real value through, under a comment saying exactly why — "never defaulted to
False here". The third was the exception handler, and it built the response without those
fields at all.

So the one reply that is not an analysis in any sense — the engine raised, nothing was
inferred — was the only one asserting that it was. Its text made that worse: *"the
correlation AI integration is being set up"* describes a deployment state, not an
exception, so an operator reading it had no way to know anything had failed.

This is live rather than theoretical: the correlation model and its LoRA adapter are
**deliberately not loaded**, which is what makes the failure paths the ordinary ones.

**Why a default is the wrong place for this.** A default is what you get when nobody
thought about the field, and the moment nobody thinks about it is precisely the handler
written in a hurry to stop a 500. `False` is not neutral here — it is the strongest claim
the model can make.

**Fixed:** the fallback sets `simulated=True` with a reason naming the exception TYPE, not
`str(e)` — an exception message is the field most likely to carry internal detail or
customer data, which is why `/admin/errors` redacts message samples across tenants. The
reply now says the analysis failed and reports no risk score, because a risk score implies
an analysis happened. Reverting the handler fails 4 of the 7 new assertions.

**Swept:** every model annotating any of nine provenance field names, and every
construction of one. **1 model, 1 omission, 0 skipped.** The guard keys on field NAMES
rather than that one model, so adding `degraded` or `availability_only` anywhere brings it
under the rule without further work.

**The same broken link, found by asking where else provenance was carried.** OEE has
flagged its own honesty since FS-234: `quality` reads 1.0 when an asset has no part
counters, `performance` reads 1.0 without an ideal cycle time, and the endpoint returns
`quality_measured` / `performance_measured` with a comment saying a consumer "should
render '—' rather than '100%' when this is false". **Nothing in the frontend read either
flag** — the fields were not in `OEEMetrics`, so an uninstrumented asset displayed
flawless quality, and OEE, being the product of the three, was reported as a result when
it could only be an upper bound.

1.0 is the correct arithmetic — it is the neutral multiplier — and the wrong thing to
print, because "100%" is a measurement and this is the absence of one. The panel now shows
`—` for an unmeasured factor with the reason underneath, labels the product **"OEE (upper
bound)"** when either factor was stood in for, and shows the good/total part counts when
they exist. An older response carrying no flags is treated as measured, so a deployment
that predates them is not covered in dashes. Six page tests; reverting the page fails five,
and the sixth is the negative control.

These flags live in a dict, not a Pydantic model, so the AST sweep above cannot see them
— the detector found the class and a human found the second instance of it. Worth stating
plainly: the guard covers response MODELS, and provenance carried in a plain dict is
outside it.

**And the chain was broken again one link further on.** `SessionChatResponse` in
`analysisSessions.ts` did not declare `simulated`, `simulation_reason`, `confidence` or
`model_version`, so the server's "do not read this as an inference" was dropped by the
client that had asked for it — nothing downstream could label the reply because nothing
downstream could see the field. A flag the operator never sees is the same as no flag.

The type now declares all four, `appendAssistantMessage` carries them onto the rendered
message, and the chat pane shows a **"Not a model inference"** badge whose tooltip is the
reason. The mock branch sets `simulated: true` as well — mock output is simulated by
definition, and returning `false` there would have made the demo the most confident
surface in the product. `test_provenance_flags_are_always_set.py` pins all four links, so
removing any one of them fails rather than quietly restoring the confident version.

**The sweep it came out of found nothing else.** 28 broad `except` handlers wrap a
database write; **all 28 log at ERROR or WARNING**, and the audit writers — the subset
where a swallowed failure is a compliance control failure rather than an inconvenience —
already record an outcome rather than assuming one. `record_audit` confines its failure to
a `SAVEPOINT` (a rejected audit INSERT would otherwise roll back the very change it
describes) and returns a boolean; the audit middleware binds the tenant GUC before
inserting into `audit_logs`, which is `FORCE ROW LEVEL SECURITY`. The one handler that
turned a failure into a confident success was the one above.

## 19. A qualifier the frontend never reads — **3 fields, 2 defects, both live**

Classes 4, 5 and 18 are all about a system describing itself untruthfully. This is the
seam version: the backend describes itself **correctly**, and the description is dropped
one layer up.

A *qualifier* is a boolean whose whole job is to say how far to trust the value beside it.
Sending one and ignoring it is worse than never sending it, because the backend author
then believes the caveat is being shown — the code review passes, the field is in the
payload, and the reader still sees a confident number with its footnote removed.

Two instances, both found by hand before this sweep existed, and both would have been
caught by it:

* **`simulated`** — the correlation chat's error fallback returns a reply that is not an
  analysis at all, and says so. `analysisSessions.ts` did not declare the field.
* **`quality_measured` / `performance_measured`** — `quality` reads 1.0 for an asset with
  no part counters, the neutral multiplier for OEE and not a measurement. The endpoint has
  flagged this since FS-234, with a comment telling consumers to render `—` rather than
  `100%`. `OEEMetrics` did not carry the fields.

**Swept:** every boolean qualifier the API can emit, from two sources — the OpenAPI
schemas AND the raw dicts handlers return. That second source is the whole reason the
sweep works: about half these endpoints declare no `response_model`, so nothing about
them reaches `components.schemas`, and `/dashboard/assets/{id}/oee` — where
`quality_measured` lives — is one of them. **Reading only the schemas made the first
version look clean while missing the defect it was written for.** Its own vacuity check
caught that, which is the strongest argument for writing vacuity checks: it failed with
"the OEE flags are not being swept" before a human noticed.

**The detector was wrong twice more, in opposite directions.**

*Too loose:* keying on name stems alone matched `estimated_duration_hours`,
`estimated_seconds` and `total_estimated_cost` — business QUANTITIES, none of them a
statement about trust. `estimated_X` names a number; the qualifier form is a flag.
Requiring `boolean` removed the whole family without an allowlist, which is the better
repair: an allowlist of false positives is a list of checks that no longer run.

*Too generous:* matching raw source made `simulated` look read, because `fleetTracker.ts`
carries the comment *"Mock vehicle positions (simulated GeoTab data)"*. An English
sentence about an unrelated feature was standing in for code that consumed the field, and
the mutation run proved the cost — against the real pre-fix frontend the sweep flagged the
OEE pair and **missed the correlation flag**. Comments are now stripped before matching,
and a test pins that the strip removes prose without removing code.

**What it deliberately cannot prove:** that the value is *displayed*, only that the code
names it. Parsing TSX for rendered output would mismodel enough to manufacture defects, so
the display half is pinned per instance instead — six OEE page tests and the four-link
chain in `test_provenance_flags_are_always_set.py`.

## 20. A cache key that omits what the fetch varies on — **clean, and nearly broken by this work**

React Query caches on the key alone. If the fetch depends on a value the key does not
name, changing that value serves the PREVIOUS result straight from cache — no refetch, no
loading state, no error. The screen updates its controls and not its data. It reads as
"the filter doesn't work", and clicking around rarely finds it, because the first render
is always right.

**This one is recorded because of how it arrived.** Making `/api/v1/auth/users` paginate
meant `AdminPages` had to send an explicit page size, and the first version of that change
kept `queryKey: ['users']` while the fetch became `getUsers({ limit })`. "Show more" would
have re-read the same 50 rows forever. Caught before commit — but nothing in the type
system or the existing suite would have caught it after, which is the argument for the
guard. It costs one line to make this mistake.

**Swept:** every `useQuery` in the frontend, 30+ of them. **Zero offenders.** The whole
value is in staying that way, so the guard lives in the frontend suite rather than in a
document.

**The detector was wrong first, in the usual direction.** Reading identifiers out of the
call arguments flagged seven sites, all of them correct:

* six pass an object literal such as `{ limit: 500 }` — `limit` is a KEY with a constant
  value and varies with nothing. Object keys are stripped before matching, exactly the
  correction the backend's query-parameter sweep needed for the same reason;
* one passes `startTime`, derived one line above from `timeRange`, which IS in the key. A
  derived value is covered transitively, so a dependency whose declaration mentions a key
  variable is not reported.

Both corrections are pinned as tests. Seven false positives would have trained the reader
to skip the output, and the one real finding would have gone with them.

## 21. A write whose result the UI never re-reads — **3 live**

Class 20 is about a cache key that is too narrow. This is the other half: the write
succeeds, the server changes, and nothing tells the screen to look again. It is
particularly quiet where the work happens **off the request path**, because there the
success response is honest and still insufficient — "triggered" is the whole truth, and
the result arrives later with nothing watching for it.

**`erpApi.triggerSync`.** `POST /erp/integrations/{id}/sync` hands the work to FastAPI
`BackgroundTasks` and returns immediately. The page reported *"Sync triggered for N entity
type(s)"*, which reads as done, and never refetched `erp-sync-status` — so the Status tab
sat on the previous run's counts for as long as anyone cared to watch.

*A plain invalidate would not have fixed it,* and this is the part that needed reading the
handler rather than pattern-matching the page: a single refetch on success lands
milliseconds after the trigger, re-reads the row the sync has not written yet, and never
fires again. It would have passed review and changed nothing on screen. The Status tab now
polls while mounted; the invalidate only gives an immediate first read to whoever is
already there. The backend writes no "running" marker at the start of a sync, so there is
no in-flight state to poll until it clears — polling while the tab is open is the honest
version of what is knowable here.

**The command panel, a cluster of four.** Both mutations invalidated
`['commands', assetId]`; **no query in the codebase declared that key**, so the refetch
went nowhere. The panel told the operator to *"view command history in the asset details
page"* — the page that renders this panel and no history. `GET /api/v1/commands/asset/{id}`
worked and had **zero callers**. And emergency stop did not invalidate at all, so the one
command an operator most needs to see land was the one guaranteed missing.

The consequence is bigger than a missing list. `command_executor` dispatches off the
request path, so *"Command submitted successfully"* only ever meant a row was written —
whether the machine did anything was not observable **anywhere in the product**. The panel
now renders recent commands with their status, polls while any is in flight and stops when
they settle, and says so instead of pointing at a page that has no history.

**The sweep found this only after the detector stopped vouching for itself.** The first
version collected query roots from every `queryKey:` in the tree — including the ones
*inside* the `invalidateQueries` calls it was checking. Every invalidation registered its
own key as a valid target, so all 18 matched and the sweep reported zero. Roots now come
only from query DECLARATIONS (`useQuery` and friends), and `'commands'` surfaced
immediately. A detector whose input includes its own subject proves nothing, and it fails
in the most convincing way available: clean.

It was wrong in the other direction too. Reading only each mutation's body reported the
three `AlarmRules` mutations as never refreshing; they call a local `const invalidate = ()
=> queryClient.invalidateQueries(...)` declared a few lines above. Resolving local helpers
took the false positives from 8 to 5, and the 3 that remain are correct — `testConnection`,
`optimize` and `analyze` produce a result rather than changing a list.

## 22. A capped list that cannot say it was capped — **12 found, 1 fixed, the rest recorded**

An endpoint that returns a bare JSON array capped at `limit` gives the caller no way to
tell a full page from the complete set. The convention for fixing it already existed —
`X-Result-Truncated` from a `limit + 1` probe, added to the three ERP list endpoints — so
the sweep was really asking where else it belonged.

**Twelve bare-array endpoints cap without a signal.** On most that is ambiguity.
`/api/v1/rul` is different, and it is the one that got fixed.

Remaining useful life is computed **per asset in Python** by `rul_service.assess_asset`,
so risk is not a column and cannot be ordered on in SQL. The page is therefore ordered by
asset **NAME**, which means the cap keeps the alphabetically-FIRST `limit` assets. An asset
three days from failure whose name begins with W is absent from the risk view entirely —
and Predictive Maintenance's tiles counted "Assets Assessed" and "High / Critical Risk"
over the survivors as though the fleet had been fully assessed. The one page whose purpose
is finding machines about to fail was quietly excluding some of them.

Fixed on both sides: the endpoint reports the header, `rulApi.listAssessments` returns
`ListResult` so the flag cannot be dropped on the way in, and the page carries a notice
naming what is missing and why. `ListResult` and the `mark_truncated` helper moved to
shared modules when this became their second consumer — the ERP copy now delegates rather
than keeping a second version of a convention that would drift the moment either was
edited.

**The other eleven are recorded, not fixed, and the reason is class 19.** Adding a header
no client reads would create exactly the defect that class exists to catch — the caveat
sent and dropped. Each needs its consumer wired at the same time, which is per-endpoint
work; four are in other lanes.

**The detector's second category had to be thrown away.** It also flagged 26 endpoints as
"an envelope with no total", which turned out to mean *no `response_model`* — the schema
was empty, so it could see nothing either way. It listed `/api/v1/auth/users`, which had
been given `total`, `skip`, `limit` and `hasMore` an hour earlier. Only the declared-type
half of the result says anything, and the rest is *unknown* rather than clean.

### What the log noise gave up: a function that had never once returned a row

Running the new `/rul` tests printed `health_index_oee_unavailable` for every asset, with
`'>=' not supported between instances of 'str' and 'datetime.datetime'`. Every column
reference in `oee_calculator.get_historical_oee` was a **Python string literal**:

```python
func.avg("oee_metrics.availability")      # averages a string
"oee_metrics.asset_id" == asset_id        # str == uuid -> False
"oee_metrics.timestamp" >= start_time     # str >= datetime -> TypeError
```

The third raised before the statement was ever compiled. `health_index` calls it inside a
broad `except` and logged a warning per asset per request; `/api/v1/oee/historical/{asset_id}`
has no such handler and returned a **500**.

It could not have worked in any case: **no migration creates an `oee_metrics` table**. Its
writer passed the same string to `insert()` and swallowed the failure in its own broad
`except` — and `oee_calculator` is one of the services `main.py` actually starts, so that
error fired on every asset on every pass of the loop. A permanent error stream, for a write
that could never land, into a table that does not exist.

Both halves are now honest. The reader aggregates `packml_states` — real, populated, and
already the basis of `/api/v1/dashboard/oee/trend` — which makes it **availability only**,
declared per row, with `None` rather than `1.0` for the two factors it cannot measure.

The writer was first rewritten as a no-op that explained itself, **and class 5's own guard
rejected it**: a helper named `_store_*` must store. That was the right call, so it is
deleted rather than renamed, and the explanation moved to the call site — where someone
wondering "why isn't this persisted?" will actually look. OEE here is *derived* from data
already persisted, so a rollup table would be a cache; building one needs a migration, a
model, RLS scoping and a retention policy rather than a string. A test asserts no migration
creates that table, so the day someone adds one it fails and asks for a real write.

Satisfying: a guard written for an earlier class caught a defect introduced while fixing a
later one, in the same run, without anyone looking for it.

**Two broad excepts, one on each side, are what kept this alive.** Class 4 covered a
handler returning success after a failure; this is the same shape applied to a service —
and it survived longer precisely because it *did* log. A warning nobody reads is not a
signal, it is a place for a defect to live.

## 23. An audit write with no tenant bound — **4 of 8 writers, all silently lost**

`audit_logs` is `ENABLE` + **FORCE** `ROW LEVEL SECURITY`. FORCE means the policy binds
the table owner too, so an INSERT is rejected outright unless `app.current_org_id` is set
on the connection — and `AsyncSessionLocal` never sets it.

Four writers opened their own session, inserted, and caught the rejection in a broad
`except` that logged and moved on: `record_audit`'s standalone path, and `_audit` in
`export_processor`, `bulk_processor` and `feature_flags`. **Every export, every bulk job
and every feature-flag change recorded nothing**, while the operation itself reported
success.

For a compliance surface that is the worst failure available: the action happened, the
evidence that it happened did not, and the only trace is a log line nobody reads. Four of
the eight writers were already correct, which is what makes the class worth a guard rather
than a fix — the convention exists and is simply easy to omit.

**Found in log noise, not by a sweep.** `export_audit_failed ... new row violates
row-level security policy for table "audit_logs"` scrolled past three times during an
unrelated real-DB run while the `/rul` tests were being written. The same run gave up
`get_historical_oee`, which had never returned a row. Both had been failing continuously,
on every request, for as long as they had existed; both were caught, logged, and forgotten.
That is method rule 16, and it earned its place twice in one afternoon.

**Why writes and not reads, again.** Under RLS a read with no GUC returns zero rows in
silence; a write is rejected *loudly*. That should make writes the easy case — and it does
not, because the loud error is caught two lines later and what reaches a human is
identical to the quiet one. A `try/except` around a write is where the distinction that
RLS gives you for free gets thrown away.

**The detector needed the same correction as three before it.** Reading each writer's own
body reported `report_scheduler._audit_enqueue` as an offender; it binds through
`self._set_org`, one call away. Following one level of same-module helpers took the list
from five to four, and the correction is pinned as a test — four false positives out of
eight would have made the file worth ignoring.

The static guard proves a `set_config` call is present. Only the real database proves the
policy accepts what follows it, so three assertions write an actual row and count it
through a superuser connection.

**That was still only half the property, and the file said so before it tested it.**
Counting through a superuser connection bypasses RLS entirely — it proves the INSERT is no
longer *rejected*, not that the entry is *visible*. What the compliance desk depends on is
the row coming back from `GET /api/v1/audit/logs`, read through the tenant-scoped session
as their own organisation; a row that lands and is then filtered out on read is, from that
desk, identical to one that was never written. Three further assertions read the trail
back, including one confirming the other organisation cannot see it — binding the GUC made
these rows writable and readable, and the audit trail is the one table where a
cross-tenant read is itself the incident.

Reverting the four services fails five of the ten, with the RLS rejections printed in the
output.

## 24. A handler that builds its own unbound session — **5 live**

Class 10 swept handlers taking `Depends(get_db)` on an RLS-protected table. This is the
same defect reached by a different route: a handler that takes no session dependency at
all and opens `AsyncSessionLocal()` inline. It binds no `app.current_org_id`, so a read
of `assets` — FORCE ROW LEVEL SECURITY — matches nothing.

**The guard had already written down its own blind spot and nobody acted on it.** The
note explaining why its `commands.py` count was wrong ends: *"A static guard keyed on one
idiom under-counts a file that uses two."* The second idiom was named, the sentence was
committed, and the sweep was never extended to it. Five more handlers were sitting in
that gap the whole time.

Verified against a real database, with an asset that plainly existed:

| | | |
|---|---|---|
| `GET /api/v1/oee/current/{id}` | **404** | "Asset not found" |
| `GET /api/v1/oee/historical/{id}` | **404** | "Asset not found" |
| `GET /api/v1/oee/losses/{id}` | **404** | "Asset not found" |
| `GET /api/v1/health-index` | 200 | `[]` |
| `GET /api/v1/simulation/fleet-summary` | 200 | `{"asset_count": 0, …}` |

Both halves of the RLS failure mode on one screen. Three endpoints that **404 on an asset
you own**, and two that answer 200 with a confident, empty lie — and the quiet pair is
worse, because "asset_count: 0" on a running plant reads as an idle factory rather than a
broken query. Nobody files a bug against a number.

**`health_index` and `simulation` are the sharpest version of the class.** Both filtered
on `current_user.organization_id`, and both were right to. It changed nothing: RLS had
already removed the rows before the filter ran. A reviewer reading those handlers sees a
correct tenant check and no reason to look at the session — which is why this survives
review, and why it needs a static guard rather than more care.

The guard now sweeps both idioms. Setting the GUC by hand still counts as binding, since
that is what the ingestion worker and the audit writers legitimately do. `kanban.py` is
the one remaining offender and is **recorded, not fixed** — the kanban RLS defect is
another lane's open ticket, and one root cause behind it also 500s `/kanban/board`,
`/metrics` and `/workload`. The exemption carries its reason, and a second test fails if
the file stops offending, so a paid debt cannot sit on the allowlist pretending to be
owed.

## 25. A request body the endpoint's schema rejects — **clean, and deliberately not guarded**

The third leg of the frontend/backend contract. Class 8 checks the path exists, class 9
checks the query parameters are declared; `test_frontend_calls_real_endpoints.py` says in
its own docstring that it "deliberately does NOT check request bodies". Rule 17 says a
limitation written into a comment is a finding waiting to be re-found, so it was swept.

**Result: clean, and it stays a written record rather than a guard.**

**15 request bodies; 7 statically resolvable; 0 mismatches** — after the detector was
wrong twice, both times in the way that manufactures defects:

* `twinOptimizer` appeared to send `assetIds`, `emitRecommendations` and three more
  fields "not in the schema". `/api/v1/twin` is registered with the casing seam, so they
  arrive as `asset_ids` and friends. The same correction class 9 needed, for the same
  reason, one sweep later — worth noting that knowing about a trap is not the same as
  remembering it.
* `erpApi.createIntegration` appeared to send `requests_per_minute` and `burst_limit`,
  neither in `ERPIntegrationCreate`. They are NESTED inside `rate_limit`, which is. The
  field-extractor flattened one object into two phantom fields.

**The other 8 are all `Partial<T>`** — `createZone(zone: Partial<GeofenceZoneExtended>)`
and seven like it. `Partial` makes every field optional, so the type permits `{}` and a
static comparison cannot say whether a required server field will be present. Extending
the resolver would report all 8 as "optional in TypeScript, required on the server", which
is true of every `Partial<T>` by construction and tells a reader nothing.

**And the failure mode is loud.** A body missing a required field is a 422 on the first
call, unlike an unknown query parameter, which FastAPI drops in silence and which is why
class 9 found four live defects. The quiet cousin is worth a guard; this one is worth
knowing about.

Recorded per the rule that a guard you cannot make precise is worse than a written-down
result — the same call made for class 14.

## 26. An endpoint the README documents but the app never served — **22 of 124**

Class 8 asserts that a path the frontend calls is served. The README's API Reference is
the **other client** — the one a new engineer or an integrator reads before writing any
code — and nothing checked it at all.

**22 of 124 documented rows were wrong.** Not stylistic drift; paths that 404 for anyone
who follows them:

* `/api/v1/commands/{command_id}/status` and `…/cancel` — the real routes put the verb
  *before* the id: `/commands/status/{id}`, `/commands/cancel/{id}`.
* `/api/v1/telemetry/latest/{id}` — really `/telemetry/{asset_id}/latest`.
* `/api/v1/kanban/boards` and three siblings — **there is no boards surface**. One board
  per organisation, at `/kanban/board`.
* `/api/v1/registries/{id}/compliance-score` and `/risk-score` — two invented variants of
  a single real `/score`.
* five `/api/v1/correlations*` rows that actually live under `/registries/correlations`.
* five logistics rows missing a path segment — and this is the interesting one.

**The logistics rows document an intention and hid a defect.** `logistics_correlation`
carries its own `/logistics` prefix *and* is mounted under `/api/v1/logistics`, so its
routes really are at `/api/v1/logistics/logistics/…`. That doubling is recorded elsewhere
in this document as deliberately unfixed — removing the inner prefix collides with
`fleet_logistics`, which owns the single-prefix path. The README showed the *tidy* path,
so the one artefact that would have told a reader about the collision instead concealed
it, and every one of those rows was a 404 waiting to be found by hand.

**Why this class is worth a guard rather than a proofread.** Documentation that cannot be
executed rots silently, and the rot is invisible *because nobody runs a README*. The
guard parameterises over every row, so a wrong path fails by name. Reverting the README
fails exactly 22 assertions.

Path-parameter NAMES are deliberately not compared — `{id}` in the docs and `{asset_id}`
in the code are the same endpoint, and comparing them literally would fail on nearly every
row and teach the reader to ignore the file.

## 27. A source file the docs point at that is not in the repo — **1 fiction, 5 omissions**

The companion to class 26. That one checks the API Reference; this checks every
source filename the prose names. A reader who goes looking for a named file and cannot
find it has no way to tell whether it moved, was renamed, or never existed.

**The ERP project-structure listing named sap_correlation_patterns.py** between its
Oracle and Dynamics siblings, both of which exist. It never has. SAP correlation runs
through the generic `app/services/erp_correlation_patterns.py`, and **the symmetry of the
list is what hid it** — three vendors, three bullets, one of them fiction. Nothing about
the shape of the document invited a check.

The same pass found the quieter half: five real files the inventory omitted
(`intuit_connector.py`, `intuit_qbo.py`, `netsuite_auth.py`, `oauth2.py`, `sap_batch.py`),
including the eighth ERP connector the README describes at length elsewhere. An inventory
is only useful if it is complete in **both** directions.

**`docs/**` was swept by hand and is clean**, and is deliberately left outside the guard.
Its 50 files use three idioms a static check cannot distinguish from a broken reference:
*"Create `configs/lora_config.json`:"* is an instruction, not a claim; *"there is no
network-policies.yaml"* is a deliberate absence note — the same shape as the SAP one
above, arrived at independently; and unchecked checklist items name files that are not
meant to exist yet. Automating it would report eleven false positives against correct
prose, which is the fastest way to make a check worth ignoring.

**Resolution is deliberately loose.** Exact path first, then a suffix match against
`git ls-files`, because the docs legitimately write `sap_connector.py` for a file six
directories down. Only existence is asserted, never location — tightening that would fail
on nearly every prose mention and teach the reader to skip the file.

### The first version of this guard had a hole with a comment attached

The fictional name was put on the exemption list, alongside the genuinely
deliberate absences (the README's "superseded paths" table compares another branch, so
its left column is *supposed* to be missing here). The mutation run then **passed**: the
name was excused by the exemption, so re-adding it as a bullet in the ERP listing was
invisible — the exemption excused the exact fiction it had been written to record.

Fixed by removing the exemption and spelling the name **without backticks** in the
sentence noting its absence, so the citation pattern never sees it. Now re-adding the
bullet fails two assertions. An exemption keyed on a bare name is not a record; it is a
hole that reads like one.

Both directions of the exemption list are also pinned: an entry that starts resolving is
a stale claim hiding a real file, and an entry no longer cited anywhere is dead weight
outliving whatever it protected.

**It has now caught this document three times.** Writing *about* an absent file is
itself the hazard: every sentence recording that something does not exist is, formatted as
a citation, indistinguishable from a claim that it does. The convention that fell out of
it — name an absent file in plain text, never in backticks — is the whole reason the
`docs/**` idioms above cannot be automated, and the reason this section spells two
filenames without them.

**And it failed its own first full run, correctly.** Resolution went through
`git ls-files`, so the guard could not see a file added in the same commit as the sentence
describing it — it called the documentation broken while the documentation was right. A
check that cannot see uncommitted work punishes exactly the change it exists to encourage.
It now falls back to the working tree, and that case is pinned by name.

## 28. A frontend catch that swallows a failure — **clean**

Class 4 is a backend handler returning success after a failure. This is its frontend
form: a `catch` that neither tells the user, retries, nor rethrows, so a failed request
renders as an empty list or an unchanged screen — and an empty list is a claim.

**Swept:** every `catch` block in `src`. **10 found that neither report nor rethrow, and
all 10 are correct.** Three are `formatters.ts` returning `'Invalid date'`, which *is* the
report. Two are auth paths where the recovery is the point — a failed logout still logs
out locally, a failed refresh clears the session and redirects to `/login`. One defaults
the theme to dark when the stored preference will not parse. One keeps a default export
message when the error body is a Blob that will not decode, and the outer handler shows it.
`Login.tsx` deliberately swallows because the store holds the error, which
`Login.test.tsx` now pins.

**One false positive, and it is the same shape as every other detector correction here:**
`ERPIntegrations.tsx` reports through `setTestResult`, which was missing from the list of
names that count as reporting. A reporting sweep that does not know all the ways this
codebase reports will accuse correct code, and four false positives out of ten would have
made the output worth skipping.

**Not guarded.** The remaining risk is not a silent `catch` — it is a handler that reports
correctly into a state the page then renders as ordinary emptiness, and distinguishing
those two statically means knowing what each screen does with its error state. That is
per-page work, and it is what the page tests added this week actually assert: `AuditLogs`
must not render a fetch failure as an empty trail, and `ErrorTriageDetail` must not render
a redaction as a missing traceback.

## 29. A verdict computed from emptiness — **14 live: 13 in the UI, 1 in the API**

Class 28 came back clean: no frontend `catch` swallows a failure. This is where the
failures actually go instead. React Query does not need a `catch` to lose one — on error
`data` is simply `undefined`, so `data?.items ?? []` renders an empty list and the
component never mentions that anything went wrong.

The consequence is not a missing error message. It is a **claim about the world**:

* **`YardManagement`** — a failed trailer query rendered *"No trailers found"*. A yard
  manager reads that as an operational fact and dispatches on it.
* **`TelemetryHistoryChart`** — a failed history query rendered *"No history for this
  metric"*, which an engineer diagnosing a machine reads as *"this sensor produced
  nothing in that window"*, concluding something about the equipment from a failure of
  the request.

Both now say a failure is a failure, and both offer a retry rather than a dead end. The
empty states stay, because "the yard is empty" and "the sensor is quiet" are real and
useful answers — they simply are not the same answer.

**The count grew from 2 to 13 as the detector was sharpened**, and the worst of them was
found last:

| | |
|---|---|
| `TransportationManagement` | **"No HOS violations detected"**, under a green tick |
| `TacticalEngine` | "No safety thresholds reported by the engine." |
| `MLOpsPipeline` | "No model deployed" |
| `AdminPages` | "No edge agents have reported yet. Agents appear here once they enroll…" |
| `Historian` | "No assets" in the picker; "No data points in this window." |
| `ERPIntegrations` | "No syncs recorded yet."; "No mappings configured." |
| `OEE` | a failed fleet load rendered **nothing at all** — no rows, no message |
| `YardManagement` | "No trailers found"; "No appointments found" |
| `TelemetryHistoryChart` | "No history for this metric" |

**The HOS one is the sharpest defect in this document.** On a failed drivers query
`drivers` is `[]`, so `drivers.filter(d => d.hosDriveHoursRemaining === 0).length === 0`
is true and the page rendered a **green checkmark** reading *"No HOS violations
detected"*. Hours of Service is DOT-regulated. A compliance officer reads a green tick as
clearance, and it was produced by a request that never returned. Unknown is not clear.

`TacticalEngine` is the same shape with a twist: it already showed a failure banner at the
top of the page, and the thresholds panel *underneath it* still asserted that the engine
reported no safety limits. Two contradictory statements on one screen, and the more
specific one was the false one.

`OEE` failed in the opposite direction and is worth separating: with `fleetOEE` undefined,
`fleetOEE?.assets?.length === 0` is **false**, so even the empty state did not render. The
page showed a table with no rows and no explanation. Silently empty is worse than wrongly
labelled — there is nothing for the reader to disbelieve.

**And the server had the same defect on the same data.**
`get_carrier_compliance_summary` returns
`overall_compliant = ctpat_certified and insurance_on_file and hos_violations == 0`,
counting violations by looping over the carrier's drivers. **`hos_violations == 0` is
trivially true when there are no drivers**, so a carrier whose driver records had never
been entered — a new carrier, a failed sync, a partial migration — was cleared on Hours of
Service. One is an empty table and the other is an empty response; both produced
clearance from nothing having been inspected.

**A third mechanism, and a fourth surface, found by sweeping the coercion itself.** A
detector for "a threshold check made on a null-coerced value" returned ten sites. Two were
already fixed; the rest split into two more live defects and a handful of correct uses.

`/logistics/logistics/compliance/summary` reached the same wrong answer through **SQL
three-valued logic**. Its violation query filters on
`hos_drive_hours_today > 11 OR ... OR medical_cert_expires < now()`, and **a NULL never
satisfies a comparison** — it evaluates to UNKNOWN, which `WHERE` discards exactly as it
discards FALSE. A driver who has never reported, or has no certificate on file, is
therefore not counted as a violation and not counted as anything else, so `hos_count == 0`
and the endpoint returned `"COMPLIANT"`. It now reports `INCOMPLETE_DATA` as a third
status, because "your fleet has a problem" and "we could not check your fleet" send an
operator to different places.

`/logistics/logistics/delivery-efficiency` failed the **opposite** way. With no shipments
in the period `on_time_percent` is 0, which is below every threshold, so `efficiency_grade`
came out **"D"** — a failing mark awarded for a week with nothing to deliver. Pessimism
from absence is no more true than optimism from it. The grade is now `None` with a
`graded` flag.

`yard_management` had the mild version: `float(detention_charge or 0)` turned "not yet
calculated" into "nothing owed", so `is_detention` read as a settled answer on billable
time nobody had worked out.

**A fifth mechanism: the average of an empty set.** `sum(xs) / len(xs) if xs else 0`
reports a number for a fleet nobody measured. `/dashboard/fleet/oee` returned **0
availability for a fleet with no assets** — which renders as 0%, a fleet-wide outage,
produced by having nothing to average. `/logistics/…/compliance/summary` did the same with
`(ctpat_count or 0) / (total or 1)`: the invented denominator exists so the expression
cannot raise, and the 0% it yields is indistinguishable from an organisation whose
carriers are all uncertified. Both now return `None`, with `assets_measured` alongside.

**And fixing the API alone would have been invisible**, which is the part worth keeping.
Both consumers wrote `(value || 0) * 100`, so an honest `null` was coerced straight back
into `0.0%` one layer up — the defect recreated by the code reading the fix. The OEE page
now renders `—`, and the analytics chart plots no point rather than a bar at zero. This is
class 19 again from the other side: it is not enough for the server to stop lying if the
client restores the lie.

**So the class has now appeared through five distinct mechanisms** — Python `or 0`
coercion, iteration over an empty collection, SQL `NULL` in a comparison, and a threshold
applied to a percentage of nothing. That is what makes it worth a name rather than a
handful of fixes.

**Sweeping the class properly found its root, one level further down.** A detector for
"a positive verdict that hinges on a count being zero" returned exactly two hits: the
carrier roll-up above, and `HOSComplianceMonitor.check_compliance`, which produces the
per-driver verdict the roll-up counts.

That one is worse in two ways. Every HOS column is read as `float(x or 0)`, so a driver
who has **never reported** becomes a driver who has driven zero hours — no violations,
therefore compliant. And the medical-certificate check had both branches guarded on the
field being SET:

```python
if driver.medical_cert_expires and driver.medical_cert_expires < now:      # expired
elif driver.medical_cert_expires and driver.medical_cert_expires < now+30d: # expiring
```

so a driver with **no certificate on file at all** produced neither a violation nor a
warning and came back clean. A current medical certificate is a condition of driving; its
absence is a finding, not the lack of one.

**Fixing it required not over-correcting.** Marking unassessed drivers as violations would
trade a false clearance for a false accusation, and an operator chasing a phantom HOS
breach stops trusting the number in both directions. Missing inputs are now collected
separately (`missing_data`, `assessable`), the carrier roll-up counts
`unassessable_drivers` apart from `hos_violations`, and `compliant_drivers` is
`total − violations − unassessable` rather than `total − violations`, which had been
putting the unjudged on the compliant side of the ledger.

The verdict now requires that something was assessed, and reports `drivers_assessed` so
the reason is legible rather than inferred from a count. The C-TPAT and insurance checks
are deliberately untouched: they read fields on the carrier itself, which either hold a
valid date or do not. **Emptiness is only ambiguous where a COUNT stands in for an
inspection** — that is the line worth remembering, and it is what makes this a class
rather than two bugs.

**How it was found, which is the part worth keeping.** Not by this sweep. It came out of
writing a page test whose first version asserted only that a known trailer was *absent* —
true in the empty state AND the error state, so it passed against the defect while
claiming to guard it. Asserting each branch by its own text is what made the page's
silence visible; the sweep was written afterwards, and found the second one immediately.

That is the third time this week a weak assertion has hidden a live defect from a test
written specifically to catch it. The pattern is always the same shape: asserting that
something is *not there* is satisfied by every reason it might not be there.

**The detector took five corrections, each one found by the false positive it produced.**
v1 asked whether the FILE mentions `isError` — `TransportationManagement` has seven
queries, three of them handled, so it looked safe. v2 counted queries against handlers,
which found four more but could not settle `AdminPages`, a file holding five separate page
components. v3 asks the real question, per empty state: does a failure branch precede this
one in its own chain?

Then the idioms. Keying on the ternary alone accused `AlarmRules` (`{isError && …}`),
`AssetDetail` (`if (isError) return`), and `Dashboard` (`isError={q.isError}` passed to a
widget). And an early return guards everything after it however far away, which a
proximity window cannot express — `OEE` returns at the top and renders its empty states
hundreds of lines below.

Comments are stripped, for the third time in this document: a comment *explaining this
very defect* quoted the empty-state text, so the quoted-string pattern reported a phantom
second occurrence, and that same comment sat between the failure branch and the real JSX
node and pushed them apart. The window is 2500 rather than 900 because what separates a
real failure branch from the empty state is that branch's own markup — an alert, an icon,
a retry button — which on two pages ran past 900 characters. Erring small produces false
positives on exactly the pages that took the trouble to explain themselves.

**Scope.** A component qualifies when it queries AND renders a literal "No …" empty
state. Both halves are load-bearing: the query is what can fail, and the empty string is
where the failure lands. A presentational list handed its rows as props has nothing to
distinguish and is correctly ignored.

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
12. **A detector's skip count must account for everything it did not check.** The
   query-parameter guard matched two shapes and counted only one of them as skipped;
   anything matching neither fell out of both branches and was invisible. It printed "37
   checked, 1 skipped" while nine calls — holding two live defects — were in the gap. The
   rule is structural, not about regexes: the recogniser and the counter must partition
   the input between them, so that what the sweep cannot read is *reported as unread*
   rather than dropped. A coverage number the guard cannot substantiate is worse than no
   number, because the whole point of a guard is to be believed.
13. **Before flagging a mismatch, check what sits between the two sides.** The same sweep
   was ready to report `historian.query` sending `assetId` to an endpoint declaring
   `asset_id`. An axios interceptor converts request params to snake_case for registered
   URL prefixes, so the code was correct and the finding would have been fabricated — the
   two ends only look mismatched if you ignore the seam in the middle. Comparing endpoints
   of a pipeline means reading the transforms along it.
14. **A substring match on source is satisfied by prose.** The qualifier sweep considered
   `simulated` "read by the frontend" because an unrelated comment said *"simulated GeoTab
   data"* — a sentence about a different feature standing in for code nobody had written.
   Strip comments before matching identifiers, and pin the strip with a test, or the
   result depends on what someone happened to write in English.
15. **Never let a detector's input include its own subject.** The invalidation sweep
   harvested query keys from every `queryKey:` in the tree, including the ones inside the
   `invalidateQueries` calls it was auditing — so each call registered its own key as a
   valid target and vouched for itself. All 18 matched, the sweep reported zero, and a
   dead invalidation sat in the command panel. The failure mode is the dangerous one: it
   comes back clean. Ask what the detector reads, and whether the thing under test is
   inside it.
16. **Read the log noise from your own test runs.** `get_historical_oee` had never once
   returned a row — every column reference was a Python string, and `str >= datetime`
   raised before the query compiled. No sweep found it and no test covered it. It
   surfaced as `health_index_oee_unavailable` warnings scrolling past during an unrelated
   real-DB run, on a service `main.py` starts, which had been emitting them on every
   asset on every pass for as long as it had existed. A warning nobody reads is not a
   signal; it is a place for a defect to live.
17. **Act on the blind spots your guards have already written down.** The tenant-session
   guard's own docstring said "a static guard keyed on one idiom under-counts a file that
   uses two", naming `AsyncSessionLocal()` as the idiom it could not see. That sentence
   was committed and the sweep was never extended. Five live defects were in the gap,
   three of them 404ing on the caller's own asset. A known limitation written into a
   comment is a finding waiting to be re-found; either close it or record it where it
   will be read as debt.
18. **A guard that has already been wrong once is the most likely place to be wrong
   again.** The query-parameter sweep was reopened twice. The first fix taught it to
   resolve variables; the second found that six calls had never matched its call pattern
   at all, because a type argument containing `{` or `;` broke the regex — so they were
   neither checked nor counted, the same failure the first fix was meant to close, one
   layer down. Both times it was reporting full coverage. When a detector turns out to
   have a gap, re-derive its *entry point*, not just the part that failed.
19. **An exemption must not be keyed on something the check itself matches.** A filename
   was allowlisted so one sentence could say "this does not exist" — and that allowlist
   then excused the same name appearing as a factual bullet three paragraphs above, which
   is precisely what it existed to catch. The mutation run passed and looked like proof.
   Scope the exemption to the context, or write the citation so the pattern never sees
   it; an exemption keyed on a bare name is a hole with a comment attached.
20. **Verifying a write through a privileged path proves the write, not the read.** The
   audit tests counted rows with a superuser connection, which bypasses RLS — so they
   showed the INSERT was accepted and said nothing about whether the entry was ever
   visible to the tenant whose trail it belongs to. Under row-level security those are
   different questions, and the one that matters is usually the second. Assert the
   property through the same path the user takes; use the privileged connection to set up
   and to explain a failure, not to conclude one.
21. **Asserting that something is NOT there is satisfied by every reason it might not
   be.** `expect(queryByText('TR-1001')).not.toBeInTheDocument()` passes when the yard is
   empty, when the request failed, when the component crashed, and when the selector is
   simply wrong. Three live defects this week hid behind exactly that shape, in tests
   written specifically to catch them. Assert what the state DOES say — the empty-state
   text, the alert role, the specific message — and pair it with the opposite case, so
   the two branches have to differ. A negative assertion is a control, never a
   conclusion.

   *And twice more while writing the analytics tests.* A negative assertion about a
   chart passed against the defect because **Recharts draws nothing under jsdom** — it
   measures a zero-size container — so "no bar at zero" was true of every possible input.
   Stubbing the chart to expose its `data` prop made the assertion about what the page
   decided to plot. Then the corrected version STILL passed, because it ran before the
   component left its loading branch: no chart existed, so "no availability series" was
   true because nothing had rendered at all. Waiting for the chart to exist first is what
   finally made it fail against the old code, with the exact series it would have drawn.

   *Applied backwards over the existing suite:* 12 tests assert nothing but absences.
   Nine are correct — the property genuinely is an absence (`sends no tenant
   identifier`, `says nothing about truncation when the list is complete`) and each is
   paired with a positive control. **Three were written the same day this rule was, and
   were wrong:** two claimed to show a loading skeleton and an error state while
   asserting only that the data was missing, and one titled *"says so when verification
   itself fails"* checked only that the success text was absent — which was equally true
   before the button was ever pressed, and would have passed against a verifier that did
   nothing at all. All three now assert what the state SAYS.

   The detector needed correcting first, in the usual direction: matching
   `expect\([^)]*\)` cannot see `expect(screen.getByText('x'))`, whose argument
   contains parentheses, so the first run reported 49 negative-only tests of which
   roughly forty had a positive assertion it simply could not read.

   *And again on the backend.* 164 Python tests assert nothing but absences, which is
   mostly correct — refusals, guards and isolation are negative properties. The sharper
   question is whether each isolation suite has a **positive control**, because "org B
   cannot see org A's row" is satisfied by a policy that hides the table from everyone,
   and this codebase has shipped exactly that twice (`audit_logs` and
   `data_processing_records` returned zero rows to their own owners for months).
   `test_compliance_report_migration.py` had no such control: it seeded one job, for org
   B, and asserted three zeros. It now seeds a job for each tenant and asserts org A can
   read and delete its own — with the GUC pointed at an org that owns nothing, the new
   assertion fails and says why.

22. **When a fail-safe stops firing, something it was hiding starts happening.** A
   `try/except` returning the conservative answer, an `or 0`, a `?? []`: each converts a
   defect into survivable behaviour, and survivable behaviour is never investigated. The
   tactical engine's maintenance check failed *safe* for as long as the column was
   missing, so adding it would have flipped suppress-everything into suppress-nothing.
   Work out what the safe branch was standing in for before removing its cause — the
   commit that makes the error go away is the moment of maximum risk. *(Full account:
   § Maintenance mode.)*

23. **A suppression assertion is satisfied by a broken connection.** Four engine tests
   assert `is True`, and `True` is also what the `except` branch returns for a database
   that never answered — three passed on the first run against `role "placeholder" does
   not exist`. Any suite whose assertions all sit on the safe side of a fail-safe needs
   one that produces the *unsafe* side through the same path, or it is only testing that
   the code is unreachable. Rule 21, one layer down.

24. **An error banner does not immunise the rest of the page.** `CloudGateway` handled
   `isError`, rendered a clear red notice, and then laid out four cards asserting the
   opposite of unknown. Marking a failure and *acting* on it are different jobs, and a
   reviewer grepping for `isError` finds the first and assumes the second. Ask not "does
   this component handle the error" but "what does it still claim while the error is on
   screen". Six pages were wrong this way. *(§ The third form.)*

25. **A qualifier nobody renders is a qualifier that does not exist.** A caveat the UI
   never reads leaves the number rendered bare while the backend believes the caveat is
   shown. Wire it, drop it, or record that the field it qualifies is unrendered too — in
   an exemption that expires by itself the moment anything renders it.

26. **A sweep that finds nothing has told you about the sweep.** The emptiness guard
   reported zero offenders tree-wide while three pages were unguarded: a 40-character
   phrase cap hid a hundred-character empty state, and a 2500-character proximity window
   found an *unrelated* mutation's error branch and called the page clean. Control every
   guard against the real pre-fix file restored from git — a synthetic fixture proves the
   function works, only the file proves the walking around it does. *(§ Rule 26.)*

27. **A window is a guess about code shape; bounds are not.** Looking for `onError`
   within 600 characters of a `useMutation` gave two false positives out of four files —
   a long `mutationFn`, and a `try/catch` around `mutateAsync`. The options object has
   exact bounds, so count braces. And treat a parse failure as "cannot tell": a sweep
   that turns one into a finding spends the reader's trust on noise. *(§ Rule 27.)*

28. **A mock more generous than the wire hides the defect it was built to catch.** Every
   test passed while the maintenance panel rendered a fabricated mileage, because the
   fixtures were written from the TypeScript type and the type described fields the API
   had never sent. `VITE_USE_MOCK` is global in `test/setup.ts`, so every unit and
   Playwright test ran against them. Copy a fixture from what the SERIALIZER emits; when
   type and wire disagree, the type is what is wrong. Deleting the field from the
   interface then makes `tsc` name every place the fabrication was propped up.

29. **A create that returns `{id, status}` cannot be checked.** The caller cannot tell
   whether what it sent was stored, which is exactly how a silently dropped `priority`
   survived in a form that posted it on every submission. Return the stored row and the
   round trip becomes assertable in one call.

30. **`.test()` on a global regex is stateful, and a guard that uses it is lying.**
   `RegExp.prototype.test` advances `lastIndex` and resumes there, so consecutive calls
   over different strings alternate on identical content. The emptiness sweep's own
   vacuity check did this and had been passing by luck; editing four unrelated pages
   dropped the count below its threshold and it failed with nothing wrong in the tree.
   Use `.match()`, and assert the count is the same twice — the failure mode is
   inconsistency, which one run cannot see.

31. **A guard that derives its expected value from its own input asserts nothing.** A
   baseline computed at import from the tree it is then compared against yields an empty
   difference by construction. Pin baselines as literals. The tell is that the expected
   and actual values come from the same function call.

32. **A feature is not one thing, and finding one defect in it says nothing about the
   rest.** Maintenance mode was wrong in five places — schema, write, read-under-RLS,
   response model, call site — found by four separate sweeps weeks apart, each fix looking
   complete at the time. A sweep is organised by SHAPE, not by feature, so it sees one seam
   and walks past the others. When a sweep finds a defect in something, walk the whole path
   by hand before believing the feature works. And check the contract from both ends: the
   server not sending what the client reads, and the client not sending what the server
   reads, are different defects that no single sweep finds.

33. **Fixing a correctness defect is where performance and robustness defects get
   introduced.** The join that made the geofence alert readable also added an N+1 and a
   500-on-real-data, and neither was in the code being fixed — both were in the fix. Run
   the whole suite, not the new file.
   *(Fuller account: § Rule 33.)*

34. **A global vocabulary passes a name that is wrong for the entity holding it.** Six
   `DockDoor` fields were declared against a table carrying none of them and the
   wire-vocabulary sweep reported none, because each name is a column on some other table.
   Per-entity audits are a different, narrower job.
   *(Fuller account: § Rule 34.)*

35. **Name the field after the wire, not after the nicer word.** Mapping `active_devices`
   to `vehiclesActive` in a client made the sweep report the new name as unsourced —
   correctly, since nothing produces it, and a reader cannot tell a rename from a
   fabrication either. One name per concept, chosen where the concept lives.
   *(Fuller account: § Rule 35.)*

36. **A request field checked against a response vocabulary is a false positive by
   construction.** `ErrorListParams.sort` sat on a baseline as unsourced while the endpoint
   accepted it: the vocabulary collected class attributes but not function parameters, so
   it was comparing what the backend CONSUMES against what it PRODUCES.
   *(Fuller account: § Rule 36.)*

37. **Prose about a defect gathers around the defect, so strip comments in every source
   assertion.** `assert "currentMileage" not in logistics_ts` failed twice against FIXED
   code — first the comment explaining the deletion, then one citing it as a precedent.
   *(Fuller account: § Rule 37.)*

38. **Prefer the check with a definite answer, even if it covers less.** The broad
   wire-vocabulary sweep produced nine findings and needed three corrections; the narrow
   response-model-versus-table audit was right first time with a two-entry false-positive
   surface.
   *(Fuller account: § Rule 38.)*

39. **Six hand-fixes and no guard is a class that will come back.** The tenant-from-body
   shape had been removed by hand from six handlers, each with a careful comment, while
   fourteen more instances sat in the same three files. A comment records a fix; only a
   guard prevents the next one.
   *(Fuller account: § Rule 39.)*

40. **Never act on truncated diagnostic output.** A guard printed thirteen offenders, `head
   -10` showed nine, nine were fixed, and four "new" ones appeared on the re-run — briefly
   looking like the fix had caused them.
   *(Fuller account: § Rule 40.)*

41. **A migration that enumerates its targets leaves the next arrival unprotected.** 011,
   033 and 051 each named their tables; `vehicles` arrived between them and had no policy,
   which is why it was the one handler whose tenant defect wrote a real cross-tenant row.
   *(Fuller account: § Rule 41.)*

42. **A test asserting emptiness must be given something to find.** `_load_rules(None) ==
   []` passed against a restored fan-out because the test omitted the fixture that seeds
   rows. Rule 21 in ordinary clothing: a fixture left off a parameter list.
   *(Fuller account: § Rule 42.)*

43. **A guard proves the absence of the shape it models, not of the class.** Three guards
   for "the caller decides which tenant" — assignment from a body (14 handlers), a query
   parameter (8), a conditionally-applied filter (4) — each clean while the next variant
   sat in the same three files.
   *(Fuller account: § Rule 43.)*

44. **A hand-maintained number in prose is a claim that will be wrong.** The README said "206
   backend test files" against a measured 201, cited rules 21–38 when the doc had reached 41,
   and said thirty-seven classes when the table had grown past it. A rule range and a class
   count change rarely and are worth asserting; a test count changes every commit and pinning
   it would make every new test fail the suite. Re-measure the rest at each milestone rather
   than trusting them — two of those three were wrong when measured.
   *(Fuller account: § Rule 44.)*

45. **A module-level copy of a patched name is a defect waiting for a new caller.**
   `tenant_session` held `AsyncSessionLocal` captured at import, and the harness rebinds that
   name per module — invisible while the helper was only reached through the dependency the
   suite overrides wholesale, and instant the moment a service called it directly. Resolve such
   names at call time. And simulate the broken state in the test: comparing engines passed under
   the mutation, because whether the copy is patched is exactly what varies.
   *(Fuller account: § Rule 45.)*

46. **A filter added to a read is a claim about the write path.**
   `WHERE organization_id = :org` asserts that something fills that column. Nothing did, so
   `/admin/collectors` was empty for every tenant since the endpoint was written — a leak
   converted into a permanent emptiness by a fix that was otherwise right. Check the writer in
   the same commit, and assert the column from the write side against the database.
   *(Fuller account: § Rule 46.)*

47. **Fixing one half of a defect can arm the other half.**
   One tenant claiming another's `agent_id` was inert while the tenancy column was never
   written; attributing the row made the last heartbeat win the tenancy. Ask what a dormant
   defect was being kept dormant *by*, before removing it.
   *(Fuller account: § Rule 47.)*

48. **A guard answers the question it was asked, so ask the broader one too.**
   The duplicate-tenant-session guard asked "which test files override `get_tenant_db`?" and
   answered it correctly while two production services held copies of the same helper. Asking
   "what in the whole tree binds `app.current_org_id`?" instead returns thirty call sites — and
   the two helpers among them. Re-derive a long-green guard's population from first principles.
   *(Fuller account: § Rule 48.)*

49. **A suite that skipped is not a suite that passed.**
   The four ERP real-DB suites report 25 passed, 29 skipped — and the 29 are every test that
   touches the function migration 058 could break, skipped for want of vendor credentials. Read
   the skip count, not just the pass count; then notice which part actually needed the
   credentials (the vendor HTTP call, and nothing else) and stub only that.
   *(Fuller account: § Rule 49.)*

50. **A fixture in a shape no endpoint produces tests the fixture.**
   The maintenance trend chart labelled its axis with `month.split(' ')[0]` — right for the
   mock's `"Jan 2024"`, and rendering the server's `"2026-01"` as the literal string. The panel
   test used the same fixture, so test and code agreed with each other about a format the wire
   does not send. Fixtures carry what the serializer emits, and nothing else.
   *(Fuller account: § Rule 50.)*

51. **An upper-bound assertion is satisfied by zero.**
   An N+1 guard asserted `len(vehicle_reads) <= 1` and passed against a one-query-per-driver
   mutation, because its matcher wanted `" FROM vehicles"` with a leading space and SQLAlchemy
   puts `FROM` at the start of a line. Assert the exact count: `== 1` fails at zero, so the
   matcher's silence becomes a failure rather than a pass.
   *(Fuller account: § Rule 51.)*

52. **When a fix does not move the baseline, suspect the detector.**
   `Driver.currentVehicleId` stayed on the declared-but-unsent list after the server began
   sending it — `_wire_vocabulary` collected dict-literal keys and not `row["name"] = …`. A
   baseline that does not move when the code does is evidence about one of the two; find out
   which. Widen with both a positive and a negative control.
   *(Fuller account: § Rule 52.)*

53. **A NULL a column can hold is a value the schema has to accept.**
   `Dict[str, Any] = Field(default_factory=dict)` rejects `None` — the factory fires only when
   the key is ABSENT, and `model_validate(orm_row)` supplies the attribute's value. Seventeen
   `meta_data` columns have no DDL default, so one raw INSERT 500s a whole list page. Coerce
   only where the absent value and the empty one genuinely mean the same thing.
   *(Fuller account: § Rule 53.)*

---

## Open observations, not yet tickets

**The password-reveal toggle on the login page has no accessible name.** It is an
icon-only `<button>` whose meaning lives in a Radix tooltip, which is exposed as a
*description*, not a name — a screen-reader user hears "button". Found while writing
`Login.test.tsx`, which selects it structurally rather than by role+name because of this.

**Deliberately not fixed.** The `htmlFor` / `aria-label` sweep is another lane's first
ticket, and quietly fixing one instance would take the interesting part of that work and
leave the pattern behind. Recorded here so it is not re-found from scratch.



**A TypeScript response type omitting fields the server sends — swept, not enforced.**
The field-level companion to class 9's shape check, restricted to URL prefixes the casing
seam does not touch so names are literal on both sides. **One hit:** `erp.ts`'s
`FieldMapping` omits `created_at` and `updated_at`, which the client has no use for. That
is the whole problem with enforcing this class — a missing field is usually a deliberate
narrowing, and only occasionally a dropped meaning like `simulated` above. Recorded per
the rule that a guard you cannot make precise is worse than a written-down result. The
provenance case, where the omission *is* a defect, is enforced separately by
`test_provenance_flags_are_always_set.py`.



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

---

## Maintenance mode: a feature that could not work, and the fix that would have made it dangerous

`POST /admin/assets/{id}/maintenance` writes `assets.maintenance_mode`;
`TacticalEngine._is_maintenance_mode` reads it to decide whether a control command may be
dispatched to a machine. `frontend/src/api/assets.ts` calls the endpoint. **The column did
not exist in the schema.**

Three defects, stacked, each hiding the one beneath it.

**1. No column.** The endpoint raised `UndefinedColumnError` and returned 500 on every
call. Nothing in the product could put a machine into maintenance.

**2. The reader failed safe, so nobody found out.** Its `except` returned `True` — *in
maintenance* — with a comment already anticipating the missing column ("the query can also
error on deployments where assets.maintenance_mode doesn't exist"). Failing safe was the
right call and it is exactly what made the gap invisible: every asset looked suppressed,
which is indistinguishable from a working feature nobody had used.

**3. The read could never have worked either.** The body was

```python
row = result.fetchone()
return bool(row and row[0])
```

on `AsyncSessionLocal`, which sets no tenant GUC because nothing here runs behind a
request. `assets` is FORCE ROW LEVEL SECURITY and the app connects as `tenant_user`, a
non-owner, so the policy predicate is NULL and **every row is filtered**. `row` is `None`,
and `bool(None and ...)` is `False`: *not in maintenance*.

So **adding the column alone would have flipped the engine from suppress-everything to
suppress-nothing** — commands dispatched to machines an operator had explicitly locked
out. A migration that looked like completing a feature would have been the most dangerous
change in the sequence. The read had to be fixed in the same commit as the write, and this
is the general shape: *when a fail-safe has been absorbing a defect, removing the defect
releases whatever the fail-safe was hiding.* Check what the safe branch was covering
before you delete its cause.

The reader now has three outcomes rather than two — in maintenance / not in maintenance /
**could not determine** — with the last folded into "do not command" and logged as
`maintenance_mode_asset_not_visible`. It accepts an `organization_id` and binds the GUC
when given, so a caller that can name its tenant gets a real answer; one that cannot gets
a deliberate suppression instead of an accidental clearance. Nothing upstream carries a
tenant today (the feature vector is `asset_id`-keyed from the edge), which is itself worth
recording.

**The write had the class-10 defect too.** It updated by `id` alone — not scoped to the
caller — and ran on `get_db`. Under RLS an INSERT is rejected loudly and **an UPDATE is
filtered silently**: it succeeds having matched nothing. Adding an `organization_id`
predicate was not enough and testing it proved so — the caller's *own* asset came back
404, because RLS had already removed the row before the predicate could match it. The
handler is now on `get_tenant_db` with the rowcount checked, which is the only thing that
separates "done" from "matched nothing".

## Rule 22 — when a fail-safe stops firing, something it was hiding starts happening

A `try/except` that returns the conservative answer, an `or 0`, a `?? []`, a 404 branch
that is reached for two different reasons: each one converts a defect into a survivable
behaviour, and survivable behaviour does not get investigated. Before removing the cause,
work out what the safe branch was standing in for — the fix is complete only when the code
downstream of it is correct too, and the moment of maximum risk is the commit that makes
the error go away.

## Rule 23 — a suppression assertion is satisfied by a broken connection

Four of the new engine tests assert `is True`, and `True` is also what the `except` branch
returns for a database that never answered. Three of them passed on the first run against
`role "placeholder" does not exist` — the engine dials `AsyncSessionLocal` directly and
only the `app` fixture rebinds it at the testcontainer. Rule 21 again, one layer down: any
suite whose assertions are all on the safe side of a fail-safe needs a test that produces
the *unsafe* side through the same path, or it is testing that the code is unreachable.

## The third form: a falsy branch that is an assertion

The sweep for this class began with a phrase — "No trailers found" — and grew a second
detector for a widget that vanishes. `CloudGateway` is the third form, and the most
quietly wrong of the three, because the page renders its error banner **and then
contradicts it**.

With `data` undefined, four values were derived and printed as facts:

| rendered | from |
|---|---|
| `Disconnected` / `Offline` | `status?.connected \|\| false` |
| `Queue Depth 0 items` | `status?.queueSize ?? 0` |
| `mTLS Disabled` | `status?.mtlsEnabled ? … : …` |
| "Mutual TLS is not enabled on this gateway connection." | the same ternary's falsy branch |

Two of them are consequential. **Queue depth 0** says no data is stranded at the edge —
the exact check an operator runs after an outage, and the reading that stops them
looking. **mTLS Disabled** is a security finding, printed under a red shield with a
sentence explaining the consequence, about a link nobody managed to inspect.

The shape to look for is not `?? 0` on its own — it is **a ternary whose falsy branch
states something**. `x ? 'Enabled' : 'Disabled'` is a two-valued answer to a
three-valued question, and it is invisible in review because both branches look like
deliberate handling. A blank would have been safer than either word.

A failed status query means the STATUS is unreadable. It does not mean the gateway is
down, its queue is empty, or its encryption is off — the gateway may be perfectly
healthy while the endpoint describing it is not. Every field is now `known`-gated and
says "Unknown", and the security card says outright that this is *not* a finding that
mTLS is disabled, because a blank beside a security heading still reads as reassurance.

## Rule 24 — an error banner does not immunise the rest of the page

`CloudGateway` handled `isError`. It rendered a clear red notice, and then laid out four
cards asserting the opposite of unknown. Marking the failure and *acting* on it are
different jobs, and a reviewer who greps for `isError` finds the first and concludes the
second. The question to ask is not "does this component handle the error" but "what does
this component still claim while the error is on screen".

## The backend form: an except branch that fills the gap with zeros

The frontend variants of this class coerce `undefined`; the backend variant catches an
exception and appends a plausible-looking row. Both OEE fleet surfaces did it:

```python
except Exception:
    summary.append({..., "oee": 0, "availability": 0, "performance": 0,
                    "quality": 0, "runtime_minutes": 0, "status": "no_data"})
```

Zero OEE is not a null result. It is a machine that produced nothing for the entire
window — the worst number this platform can report about a piece of equipment.

**And the status named the one thing it was not.** `calculate_oee` returns zeros through
the *success* path for an asset that genuinely reported nothing, so this branch only ever
fired when the calculation itself broke. "no_data" was reserved for the case that was not
missing data.

Two consequences beyond the row:

**The fleet mean averaged the placeholders.** `sum(s['oee']) / len(summary)` divided by
every asset including the failed ones, so one broken calculation in twenty pulled the
average down and the plant read as a partial outage. This is the empty-set-average defect
one step removed — the set is not empty, it is full of stand-ins for absence, which is
harder to see and produces a number that looks entirely reasonable.

**The other copy renders to PDF.** `/exports/oee/summary` builds a document that gets
filed, printed and forwarded. Four numeric columns reading "0, 0, 0, 0" have told the
reader the machine was dead before their eye reaches the status column. Those cells are
em dashes now — deliberately not the CSV `_cell` helper, which maps None to `""`: a blank
in a spreadsheet reads as missing, a blank in a printed table reads as an omission and
the reader supplies the zero themselves.

The substitution is keyed on `is None` and never on falsiness, because a genuine 0 is a
finding and hiding it behind a dash is the same defect facing the other way.

## Rule 25 — a qualifier nobody renders is a qualifier that does not exist

Adding `assets_measured` / `assets_unavailable` to the OEE aggregate made
`test_qualifiers_reach_the_frontend` fail, which is the guard doing its job: a caveat the
UI never reads leaves the number rendered bare while the backend believes the caveat is
shown. The honest resolutions are to wire it, to drop it, or — as here — to record that
the field it qualifies is not rendered either, in an exemption that expires by itself the
moment anything renders it. `/oee/dashboard/summary` has no frontend consumer at all; the
dashboard reads `/dashboard/fleet/oee`.

## Rule 26 — a sweep that finds nothing has told you about the sweep

The emptiness sweep reported **zero offenders across the tree** while `StrategicEngine`
sat unguarded, telling anyone whose recommendations had failed to load: *"No pending
recommendations. Check back later for new suggestions from the cloud strategic engine."*
It escaped through two independent blind spots, and neither was visible from the clean
result.

**The length cap.** `EMPTY_PHRASE` matched up to forty characters after "No "; that
sentence runs to about a hundred. A helpful empty state is longer than a terse one, so
the cap bit hardest on exactly the pages that took the trouble to explain themselves —
the third time this pattern has had to be widened, and the first time something was
actually hiding in the gap.

**Proximity found the wrong error branch.** With the cap widened it *still* passed: the
nearest `isError` inside the 2500-character window was `{optimizeMutation.isError ? …}`,
a different mutation in a different card. The chain "contained an error branch" and the
file read clean. The page's own failure banner is a hundred lines above and guards
nothing below it either — rule 24 arriving inside the guard.

The fix is `guardsPosition`: when a JSX expression container OPENS with an error check
(`{someError && …}` or `{someError ? … : …}`) and closes before the empty state, that
occurrence is a banner and does not count. Brace counting, because nesting is precisely
what a regex cannot follow.

**It is deliberately narrow, and the first version was not.** Counting braces from
whatever `{` preceded the match, and defaulting to "does not guard", broke two correct
idioms at once: the `{ data, isError }` of the destructuring, and `isError={q.isError}`
passed as a **prop**, where the guard is the receiving component and position is
meaningless — that one flagged all six Dashboard widgets. Anything that is not the banner
idiom is now assumed to guard, so the rule can only remove a false negative, never
manufacture a false positive.

Three sweeps in this session came back empty. Two of those were true, and each is now
controlled against the real pre-fix file rather than a synthetic fixture — restore the
file from git, watch the guard name it, restore the fix, watch it go quiet. A synthetic
fixture proves the function works; only the real file proves the file-walking around it
does.

`ERPIntegrations` fell out of the same widening: its top-level list query did not
destructure `isError` at all, so a failed load rendered "No ERP integrations yet. Add one
to get started." — an instruction to go and configure something, given to someone whose
integrations could not be read. That file already defined an `EmptyOrError` component and
used it in every sub-panel. Only the first thing on the page skipped it.

**One false positive was found and exempted, not suppressed.** `PredictiveMaintenance`
says "No notification dispatched for this assessment" from `a.notificationDispatched ? …`
where `a` is an already-rendered assessment — the line cannot be reached by a failed
request. `NOT_A_QUERY_EMPTY_STATE` records it with the reason, and three tests keep the
entry honest: the phrase must still exist in the named file, the list must stay short
enough to read, and the pattern must still match the phrase — so the list cannot quietly
describe code that has moved on, or hide a sweep that has narrowed.

## The action side: a mutation whose failure reaches nobody

Every sweep so far was about reads. `useQuery` failures render as emptiness. **`useMutation`
failures render as nothing at all**, and that is worse in one specific way: the user pressed
the button deliberately, so they already expect a change, and no response is
indistinguishable from the instant before the list refreshes.

Nine silent mutations across three files, all of which had `onSuccess` and no `onError`:

**The stale success is the sharpest thing in this session.** `ERPIntegrations`'s
test-connection wrote its outcome into a per-integration map on success only. A failed test
wrote nothing, so the PREVIOUS test's *"healthy: connected"* stayed exactly where it was —
same place, same colour, nothing marking it stale — as the result of a test that had just
failed. The button exists to refresh that claim; the person pressing it is asking the
question again and getting last time's answer. That is not missing feedback, it is a false
one.

**The silent delete is the most consequential.** `AdminPages` deleted a user and said
nothing on failure. "Row still there" is exactly what a successful delete looks like until
the list refetches, so there was nothing to notice — and an admin who believes they revoked
someone's access, and did not, has a security problem they cannot see. `Notifications` had
the same shape for a subscription: an admin who thinks they stopped a webhook has not.

Both files already contained the right idiom and skipped it locally — `AdminPages` uses
`alert` from `useDialog` for its missing-field checks, `ERPIntegrations` has an `onError`
on `analyzeMut` and nowhere else. Rule 18 yet again, and `Notifications` was found *after*
being read for query defects and declared clean: the sweep for one class does not see the
next one.

`ERPIntegrations` also rendered every outcome in the accent colour, so even the failures it
did record were displayed identically to successes. The map now carries `ok` alongside the
text.

## Rule 27 — a window is a guess about code shape; bounds are not

The first version of the mutation sweep looked for `onError` within 600 characters of the
declaration and produced **two false positives out of four files**: `CommandPanel`, whose
`mutationFn` body is long enough to push `onError` past the window, and `AlarmRules`, which
handles failure in a `try/catch` around `mutateAsync`. Both were correct code.

The options object has exact bounds, so the guard counts braces instead, and recognises all
three real idioms: `onError` in the options, `name.isError` rendered by the component, and
`name.mutateAsync` awaited at a call site. It also treats a parse failure as "cannot tell"
and stays quiet — a sweep that turns a parse failure into a finding spends the reader's
trust on noise, and after two or three of those nobody reads the output.

The same lesson had already been paid for once in `failureIsNotEmptiness`, where a 2500-
character proximity window found an unrelated mutation's error branch and cleared a page
that was genuinely broken.

## A round trip that could not close: the maintenance schedule

Chasing the casing seam (`transformRegistry` converts snake_case to camelCase for
registered URL prefixes only) produced a clean result — every client on an unregistered
prefix reads snake_case, or its backend deliberately emits camelCase. But reading the
`/api/v1/maintenance` client to prove that turned up an adapter comment —

```ts
// component reads currentMileage.toLocaleString(); backend only has dueMileage
currentMileage: s?.currentMileage ?? s?.dueMileage ?? 0,
```

— and behind it, three defects in one round trip, each hiding the next.

**Creation always failed.** `create_schedule` raised 400 *"vehicleId is required"* unless
the payload carried `vehicleId`. `_schedule_out` emits the vehicle under **both**
`vehicleId` and `vehicleNumber`, from the same column, and the form sent what it had been
shown. Reading a field out under one name and refusing to accept it back under that name
is a round trip that cannot close.

**`priority` was collected, sent and dropped.** The form offers Low/Normal/High/Urgent;
the panel renders a coloured badge on every row. There was no column, so the handler
ignored it, the serializer never emitted it, and the client's adapter substituted the
literal `'medium'` — **not a member of its own declared union**. Every schedule displayed
the same invented priority whatever the operator chose.

**`currentMileage` was dropped too, and displayed.** The panel printed
`Mileage: {currentMileage}` from `dueMileage` — the odometer at which the service falls
DUE — which a technician reads as where the vehicle is now. The two differ by exactly the
distance left before the service. With neither value present it printed `Mileage: 0`.

Fixed by migration 054 (a real `priority` column), by accepting `vehicleNumber`, by
returning the whole row from create instead of `{id, status}`, and by **deleting**
`currentMileage` rather than manufacturing it — a schedule knows when service is due; it
does not know the vehicle's present odometer.

## Rule 28 — a mock more generous than the wire hides the defect it was built to catch

Every existing test passed. `maintenanceMocks.ts` supplied `currentMileage` and a real
`priority`, because the fixtures were written from the TypeScript type — and the type
described fields the API had never sent. `VITE_USE_MOCK` is set globally in
`test/setup.ts`, so *every* unit and Playwright test ran against those fixtures.

The fixture must be copied from **what the serializer emits**, not from the type the
frontend declares. When the two disagree, the type is the thing that is wrong, and a
fixture built from it will agree with the type forever.

Deleting `currentMileage` from the interface made `tsc` name every place the fabrication
had been propped up — the mocks, the panel, the form — which is the useful direction:
the type system finds the props once the lie is removed from the type.

## Rule 29 — a create that returns `{id, status}` cannot be checked

`create_schedule` returned two fields. A caller cannot tell from that whether what it sent
was stored, which is exactly how a silently dropped `priority` survived in a form that
posted it on every submission. Returning the stored row makes the round trip assertable in
one call — and the test that now pins it (`what was sent is what comes back`) is the one
that would have caught all three defects on the day they shipped.

## Sweeping the whole contract: TS fields the wire never carries

`currentMileage` suggested a general question — *which other fields does the frontend
declare, read and render that no backend source ever emits?* — and it is mechanically
answerable. The sweep builds the backend's **wire vocabulary** (every string key in a
dict literal across `app/`, every model and schema attribute, every `Field(alias=…)`,
each also in camelCase) plus the casing seam's `inAliases` values, then reports every
field declared in `types/*.ts` that is absent from it **and read somewhere in a component**.

Controlled against the real file: with the pre-fix `logistics.ts` and panel restored it
reports `MaintenanceSchedule.currentMileage` and a total of 61; with the fix in place, 60.

**53 after the alias correction**, and the `RepairOrder` cluster is the same defect family
in the same component — the adapter beside `adaptSchedule`:

| rendered | actually | consequence |
|---|---|---|
| `workOrderNumber` | `id.slice(0, 8)` | eight characters of a UUID, as the row heading a technician quotes to a vendor |
| `estimatedCost` … "estimated" | `repair_orders.cost`, `?? 0` | a repair with no cost recorded displayed as **"$0 estimated"** — a free repair, and an estimate nobody made |
| `priority` | `?? 'medium'` | see the enum note below |

Renaming is fine; inventing is not. `title → issueDescription` and `openedAt →
reportedDate` are honest maps onto columns that exist. The two above were not maps.

**Recorded, not fixed:** `repair_orders.priority` is `low | medium | high | critical` and
the TypeScript union is `low | normal | high | urgent`, so two of the four server values
arrive as strings the union does not contain and `getPriorityColor` falls through to its
default. Reconciling the vocabularies is a product decision — which words does the
operator use? — not a mechanical fix. `partsUsed`, `laborHours`, `assignedTechnician` and
`actualCost` have no columns at all; every one is rendered conditionally, so they are
simply never shown. That is a missing feature, not a false statement, and it is left as
one rather than faked.

The remaining ~45 entries are recorded here as a work-list rather than swept in one pass:
each needs the same judgement — is this field renamed, absent, or invented? — and the
three answers have three different fixes.

## The HOS clearance, found a second time in the same component

`hosDriveHoursRemaining` came out of the wire-vocabulary sweep, and it is the most serious
thing this session found.

Migration 042 added `drivers.hos_drive_hours_remaining` and `hos_duty_hours_remaining`
with no default and no backfill. **Nothing in this codebase has ever written to either** —
no ELD sync, no ingestion path, no computation. The model comment states what they were
meant to be (`# 11 - hos_drive_hours_today`) and nothing did the subtraction.

The transportation compliance tab counts a violation as `hosDriveHoursRemaining === 0`.
**`null === 0` is false.** Every driver was counted compliant, every fleet returned zero
violations, and the page rendered a green *"No HOS violations detected"* tick — on the
**success** path, with the data loaded, for DOT-regulated hours.

**This page had already been fixed for this exact class.** The earlier fix covered a
*failed* drivers query — `[]` also produces zero violations — and left the far more common
case untouched: the query succeeds and the field is simply null. Rule 18 in its plainest
possible form, and it took a different sweep to find the second instance.

Three more defects fell out of the same field:

**The list endpoint 500'd on any unreported driver.** `DriverBase` declared
`hos_drive_hours_today: float = 0` while the column is nullable, so `model_validate`
raised on a NULL and the entire `/drivers` response failed — one silent driver took the
page down for the whole fleet. The `= 0` was the sharper half: **a schema default is a
claim about the world just as much as a coalesce is**, and zero hours driven is a clean HOS
record, not an absent one.

**`formatDuration` crashed the tab.** It guarded with `hours === undefined`, and the API
sends JSON `null` — `null === undefined` is false, so it fell through to `null.toFixed(1)`
and threw, taking the whole drivers tab down. Never surfaced because the mock fixtures
supply a number for every driver (rule 28 again).

**`null < 2` is `0 < 2`.** An unreported driver was painted amber — the colour reserved for
one running short of hours — and captioned "N/Ah".

The fix is a derivation, not a default: remaining is computed from the consumed figure that
*is* populated, and stays NULL when that is missing too. A driver who has reported nothing
is unassessable, and inventing "11 hours left" for them clears them just as effectively as
null did.

## Rule 30 — `.test()` on a global regex is stateful, and a guard that uses it is lying

The emptiness sweep's own vacuity check —

```ts
const QUERYING = FILES.filter((f) => QUERIES.test(readFileSync(f, 'utf8')))
```

— uses a `/g/` regex, and `RegExp.prototype.test` advances `lastIndex` and resumes from
there on the next call. Consecutive calls over different strings therefore alternate
between matching and not matching identical content, so the count depended on how many
files preceded each one and how long they were.

It had been passing by luck. Editing four unrelated pages moved enough characters to drop
the count below its threshold and the check failed with nothing wrong in the tree it
guards. A guard whose result depends on iteration order cannot tell you anything about
anything. It now uses `.match()`, and a test asserts the count is the same twice —
because the failure mode is *inconsistency*, which a single run cannot see.

## The costs tab: three of five figures were manufactured in the client

`/maintenance/costs` returns `{ ytdTotal, byCategory }`. The tab renders five figures, so
the client filled the gap:

| rendered | from | what it said |
|---|---|---|
| Total YTD | `ytdTotal` | honest |
| Monthly Average | `ytd / 12` | wrong in every month but December — in February it understates roughly sixfold |
| Per Vehicle | `0` | a fleet whose maintenance costs nothing per vehicle |
| Upcoming (Est.) | `0` | in a **highlighted** box, so it reads as "nothing is coming up" rather than "nobody calculated this" |
| Monthly Cost Trend | `[]` | an empty chart |

Plus `(amount / costs.totalYTD) * 100` for the category breakdown, which is `Infinity`
when the total is zero and renders the literal string **"NaN"** through `.toFixed(1)` —
reachable exactly when a cost breakdown means least.

A figure the server does not send is now absent, and the panel says which ones are not
reported by this deployment. **An absent row prompts a question; a row reading `$0`
answers one** — that is the whole difference, and it is why omitting beats defaulting
every time the value is a measurement rather than a count.

Note the direction of the two hardcoded zeros. Both were written to make a layout look
complete, and both survived review because a zero in a currency column is unremarkable.
That is exactly what makes this class expensive: the fabricated value is always the one
that looks most normal.

## Rule 31 — a guard that derives its expected value from its own input asserts nothing

The wire-vocabulary sweep became a permanent guard, and the first version of it was
vacuous in a way worth recording because it looked completely reasonable:

```python
BASELINE = _declared_but_unsent()      # computed at import, from the current tree
...
new = sorted(_declared_but_unsent() - BASELINE)
assert not new
```

`new` is empty by construction. The guard could never fail, for any tree, ever — it was a
very expensive way of asserting that a set equals itself. Nine tests passed and one of
them was inspecting nothing.

A baseline must be a **literal**, written into the file, so the comparison is against what
was true when someone looked rather than against what is true now. The fix is mechanical;
noticing is the part that isn't, and the tell is that the expected value and the actual
value come from the same function call.

Controlled the only way that means anything: a fabricated field (`inferencesPerSecond`,
declared on a type and read by a component, emitted by nothing) was introduced into the
real tree, and the guard named it. Restored, it goes quiet.

Two other guards in this session had the same shape of problem and neither was caught by
running them — the emptiness sweep reported zero offenders while three pages were broken
(rule 26), and its vacuity check depended on iteration order (rule 30). **Three guards,
three different ways of being confidently wrong.** The only method that has reliably found
these is to break the real tree on purpose and check that the guard notices.

## Maintenance mode, finished: five defects in one feature

The wire-vocabulary sweep flagged `Asset.isInMaintenance`, and finishing that thread closed
the last two of **five independent defects in a single feature**. Worth listing together,
because each one alone would have broken it, and each was individually plausible:

1. **No column.** `assets.maintenance_mode` did not exist. The write endpoint 500'd on
   every call while the frontend called it (migration 053).
2. **The write was not tenant-scoped and did not check its rowcount.** Under RLS an UPDATE
   is filtered, not rejected — it succeeds having matched nothing and returns 200.
3. **The engine's read was blind to RLS.** `bool(row and row[0])` on a session with no
   tenant GUC turns an invisible row into *not in maintenance*, so fixing the column alone
   would have flipped suppress-everything into suppress-nothing.
4. **`AssetResponse` never declared the field.** FastAPI drops whatever the schema omits,
   so with the column present, the write working and the engine honouring it, **no client
   could see which assets were out of service.** The frontend's own name for it,
   `isInMaintenance`, had never been sent by any endpoint under any spelling.
5. **The one call site sent the flag where the server does not look.**
   `setMaintenanceMode` posted `{ inMaintenance }` as a JSON body; the endpoint declares
   `enabled: bool = True`, a scalar FastAPI reads from the query string. The body was
   discarded and the default took over, so **calling it to take an asset OUT of maintenance
   put it IN** — a 200, the opposite of the requested effect, and a response reading
   "Game-theoretic engine commands are blocked".

## Rule 32 — a feature is not one thing, and finding one defect in it says nothing about the rest

Four separate sweeps found these, weeks of work apart: an unchecked-UPDATE audit, a
fail-safe audit, a contract sweep in one direction, and reading a client while chasing
something else. Each fix looked complete at the time. What actually distinguishes them is
that every one sits on a different *seam* — schema, write, read-under-RLS, response model,
call site — and a sweep is organised by shape, not by feature. **When a sweep finds a defect
in something, walk the whole path by hand before believing the feature works.** The column,
the writer, the reader, the response model and the caller are five different places to be
wrong, and this feature was wrong in all of them.

The corollary is about direction. Defects 4 and 5 point opposite ways — the server not
sending what the client reads, and the client not sending what the server reads — and
neither sweep could have found the other. A contract has two ends and needs checking from
both.

## Every geofence alert read "Violation"

Triaging the wire-vocabulary baseline table-aware — *does the entity's own table have a
column that could feed this field?* — separated the entries into three real fixes: rename
the producer, expose an existing column, or delete the field. The geofence cluster was the
first kind, and the largest single finding left on the list.

`GET /geofencing/alerts` emitted `zoneId`, `eventType` and `createdAt`. The TypeScript
`GeofenceAlert` declares `geofenceId`, `alertType` and `timestamp`. **No overlap on any
field that matters**, and nothing in the frontend read the names being sent — the producer
and its only consumer had drifted completely apart.

`alertType` is the one that did damage. `GeofencingPanel` renders

```tsx
alert.alertType === 'entry' ? 'Entered' : alert.alertType === 'exit' ? 'Exited' : 'Violation'
```

An undefined field matches neither branch, so the last one fires — and the last one is an
assertion. **Every alert read "Violation"**: routine authorised entries, exits, everything.
That is the sixth time in this sweep that a falsy ternary branch has stated something it had
not earned, and it is now the most reliable single shape to grep for in this codebase.

`geofenceName` and `vehicleNumber` were undefined too, so a row could not say which zone or
which vehicle. Both live on other tables and are now resolved in two batched queries.

**Three separate corrections were needed to get that right**, and the second and third both
came from running things rather than reading them:

*The N+1 guard was vacuous.* It attached `before_cursor_execute` to
`app.db.database.engine` — but `conftest` builds its own `test_engine` and rebinds every
module's `AsyncSessionLocal` to it, so nothing was ever recorded and `len([]) <= 1` passed
for any implementation. A deliberate per-row-query mutation did not fail it. Fixed by
listening on the `Engine` **class**, which catches every instance, plus an assertion that
*something* was recorded at all.

*The batching 500'd on real data.* `geofence_alerts.zone_id` and `.vehicle_id` are
`String(36)` while the tables they reference have UUID primary keys, so `IN (…)` against a
free-form string raises `DataError: invalid UUID`. Integrations do write device identifiers
there — the existing tenant-isolation suite seeds `'VEH-a'`, which is what caught it. Only
parseable UUIDs are looked up now; the rest resolve to `None`, because a device reference
that is not an internal id is not a reason to fail the whole list.

## Rule 33 — fixing a correctness defect is where performance and robustness defects get introduced

The join that made the alert readable also added an N+1 and a 500-on-real-data, and neither
was in the code being fixed — both were in the fix. The correctness change is the moment the
code is least reviewed, because attention is on the defect. Run the **whole** suite, not the
new file: the isolation suite caught the crash, and the new file's own N+1 guard had to be
repaired before it could catch anything.

## Triaging the rest, table-aware: three fixes, not one

The wire-vocabulary baseline is a list of names, and a name alone does not say what to do
about it. The question that makes it actionable is **does this entity's own table have a
column that could feed the field, or a reference to one that does?** — and it sorts every
entry into one of three fixes:

| answer | fix | example |
|---|---|---|
| the producer uses a different name | rename the producer | `eventType` → `alertType` |
| a column or reference exists | expose it | `trailerLicensePlate` through `current_trailer_id` |
| nothing could ever feed it | delete the field | `workcellName` on a dock door |

The yard cluster needed **two of the three at once**. `dock_doors.current_trailer_id` and
`dock_appointments.trailer_id` both reference `yard_trailers`, where the plate lives — so the
door card was printing an empty line exactly where the trailer occupying the dock should be
named, and that is an expose. `workcellName` sat next to it and is a delete: `dock_doors` has
no workcell relationship of any kind, so the card was rendering a blank for an association
this schema does not have.

**The response model nearly ate the fix, again.** `GET /yard/dock/doors` declares
`response_model=List[DockDoorResponse]`, so resolving the plate in the handler without
declaring it on the schema would have deleted it from every response and changed nothing
visible — the same trap that hid `maintenance_mode` on `AssetResponse`, hit twice in one
session. Worth stating as a habit: **after adding a field to a handler, check what the
response model does to it.**

**And the fixture found a second, unrelated 500.** `dock_appointments.meta_data` is
`Column(JSON, default={})` — a *Python-side* default, so a row written by a migration, a
seeder or a raw INSERT holds NULL, the ORM hands the field an explicit None, and
`metadata: Dict[str, Any]` rejected it. `GET /yard/dock/appointments` answered 500 with
"metadata: Input should be a valid dictionary", an error naming our own schema rather than
the row. `DockDoorResponse` carries a long comment describing this exact failure being fixed
for `equipment_capabilities`; the appointment schema beside it was left alone. Rule 18, and
the fixture that caught it was not looking for it.

## Rule 34 — a global vocabulary passes a name that is wrong for the entity holding it

`DockDoor.workcellId`, `supportedEquipment`, `hasLoadingEquipment`, `maxWeightCapacity`,
`currentAppointmentId` and `estimatedReleaseAt` are all declared on a table that carries
none of them — `dock_doors` has `equipment_capabilities` as JSON and nothing else — and the
wire-vocabulary sweep reports **none** of them. Its vocabulary is global: a name that exists
as a column on *any* table passes, whatever entity declares it.

That is a deliberate trade (a per-entity vocabulary needs a type-to-table mapping the sweep
does not have), but it bounds the claim. The sweep finds names nothing anywhere produces; it
does not find names produced *somewhere else*. Auditing one interface against its own table,
end to end, is a different and narrower job — and it is where the rest of `DockDoor` lives.

## "Fleet Status (GeoTab Live)" — six blanks under a claim of live data

`geoTabApi.getFleetSummary` declared a return type of
`{ totalVehicles, vehiclesMoving, vehiclesIdle, vehiclesOffline, avgSpeed,
totalDistanceToday, fuelConsumedToday }` and returned `response.data` untouched.
`/geotab/fleet/summary` sends `total_devices, active_devices, total_drivers,
drivers_on_duty, drivers_driving, exceptions_today, hos_violations_today,
average_fuel_efficiency, total_miles_today`.

**Not one field overlapped.** Every figure on the card was `undefined`, two of them printed
beside bare units — `" mph"`, `" mi"` — which reads as a measurement rather than an absent
one. The declared shape was plausible enough that nobody compared it to a response.

**And the payload says it is simulated.** Every GeoTab response carries `simulated: true`,
`data_source: "geotab_simulator"` and the sentence *"Not measured from a device and not valid
for DOT/ELD compliance reporting"* — stamped server-side precisely so a consumer could tell.
Nothing read it, and the heading said **Live**. That is rule 25 on the most sensitive data in
the product: a qualifier nobody renders is a qualifier that does not exist.

The card now shows only the figures the endpoint reports, renders `—` rather than a bare
unit for the ones it does not, and labels the panel *simulated* with the server's own warning
when the flag is set. `avgSpeed` and fuel *consumed* were deleted: the server reports fuel
*efficiency*, which is a different quantity.

## Rule 35 — name the field after the wire, not after the nicer word

The first version of this fix mapped `active_devices` → `vehiclesActive` in the client, and
the wire-vocabulary sweep immediately reported `vehiclesActive` as unsourced — correctly, in
the sense that no server file spells it. The sweep cannot tell a client-side rename from a
fabrication, and neither can a reader six months later.

Renaming the TypeScript fields to `totalDevices` / `activeDevices` / `totalMilesToday`
removed the adapter entirely. It is also more honest: the endpoint counts **devices**, and
calling them vehicles was part of what made the original mismatch invisible — the shape read
plausibly while sharing no field name with any response. One name per concept means nothing
to drift and nothing for the sweep to report.

The same argument settled the geofence rename in the other direction: there, the producer had
the odd names and no consumer, so the producer moved. The rule is not "always change the
client" — it is "one name per concept, chosen where the concept actually lives".

## Working the list down: 53 → 32

Nine findings so far from the wire-vocabulary baseline, and the distribution is the useful
part. **Only three of the nine were false claims**; the rest were information the product
collected, or could have collected, and could not show:

| finding | fix | what the user saw |
|---|---|---|
| `currentMileage` | delete | the DUE odometer labelled as the current one |
| `workOrderNumber` | delete | eight characters of a UUID as a work-order number |
| cost figures ×3 | delete | "$0" per vehicle and upcoming, "monthly average" = YTD ÷ 12 |
| `Asset.isInMaintenance` | expose | nothing — no client could see maintenance mode at all |
| geofence names ×3 | rename producer | **every alert read "Violation"** |
| yard plate ×4 | expose | a dock door that could not name the trailer at it |
| `workcellName` ×2 | delete | a blank line for an association the schema lacks |
| fleet summary | rename client | six blanks under "GeoTab Live", two beside bare units |
| device ids ×2 | rename both ways | a "GeoTab Device ID" row that never appeared |
| carrier contact ×2 | delete | a "Contact" heading above two empty lines |

**The distribution matters more than the count.** A sweep that finds thirty "missing field"
entries and treats them all as bugs to fix would have added columns for carrier contacts and
a workcell relationship for dock doors — inventing product scope from a lint result. The
table-aware question (*does this entity's own table have a column, or a reference to one?*)
is what separates the three answers, and **delete was the most common one**.

Two entries stay on the list deliberately and are worth naming, because they look like
findings and are not: `LogisticsOverview.todayAppointments` is computed client-side by
filtering the appointments list, and the `Location` contact pair is a frontend-only shape a
caller may populate itself. The sweep cannot distinguish either from a fabrication, which is
exactly why the list is a baseline rather than a defect count.

**One gap recorded rather than closed:** carrier contact details have nowhere to live in this
schema. That is a real product hole — you cannot phone a carrier from this system — but
filling it is a migration plus CRUD plus data entry, not a sweep fix.

## Rule 36 — a request field checked against a response vocabulary is a false positive by construction

`ErrorListParams.sort` sat on the baseline as an unsourced field. It is not: `list_errors`
declares `sort: Literal["count", "last_seen", "first_seen"] = "count"` and the client sends
it correctly.

The sweep's vocabulary collected `AnnAssign` targets — class attributes — but function
**parameters** are `ast.arg` nodes, so every query parameter an endpoint accepts was
invisible to it. And a `*Params` interface on the frontend describes a **request**, whose
valid names are exactly those parameters. The sweep was checking what the backend *consumes*
against what it *produces*.

Fixed by adding parameter names to the vocabulary. Only one entry moved, so the gap was
narrow — but the cost of that class of false positive is not the entry, it is the reader who
investigates a working field and concludes the sweep is noisy. **A sweep gets one or two
false positives before people stop reading its output**, which is why every one found here
is removed at the source rather than exempted.

Nine of ten entries investigated so far were real. That ratio is the only thing that makes a
36-rule document worth keeping.

## FS-207: the CI quarantine now expires

`ci-cd.yml` passes three `--ignore` and two `--deselect` flags to pytest. Every one is
justified — the ignored files fail at **collection**, so without them the whole backend job
dies before running anything — but a flag in a workflow file has no expiry, no owner, and no
record of what would have to be true to remove it.

That is a suppression, and this document is largely a record of what suppressions do: they
convert a defect into a survivable condition, and survivable conditions are never revisited
(rule 22). Six tests were being skipped by a mechanism with no way to notice.

`test_ci_quarantine_expires.py` asserts four things:

1. **The list and CI are the same set** — in both directions. A new `--ignore` added to the
   workflow with no entry in the list fails the test, which is the only thing standing
   between "we skipped one broken file" and a job that quietly stops running half the suite.
2. **Each quarantined file still fails to collect.** A stale quarantine is worse than none:
   it hides a working test *and* makes the whole list untrustworthy. Run in a subprocess,
   because a broken import in-process would take the guard down with it.
3. **Each deselected test still fails.** Same question, one level finer; these fail on an
   assertion rather than at collection, so they can be run directly.
4. **The expiry has not passed**, and no expiry is more than a year out — a date far enough
   away is the same as no date.

Each entry carries the owner and the precise fix. The three collection errors are import
mismatches in the intake lane's scenario builders: two import `build_document_scenarios` /
`build_image_scenarios` where the modules export `build_scenarios`, and the third expects a
`CrossFileScenarioBuilder` class in a function-based module. **The code was deliberately not
touched** — that lane is still building those assertions, and renaming the import would
surface a body of expectations I would then be tempted to edit. Recording the mismatch makes
the owner's change a two-minute one; making it myself would make it somebody's afternoon.

Controlled both ways: an undocumented `--ignore` added to the real workflow is named, and a
back-dated expiry fails with the owner and the fix. **And the guard rejected its own first
draft** — one entry's `fix` field said only "as above.", which the `test_every_entry_says_who_and_how`
assertion refused as too thin to act on.

## The per-interface audit: DockDoor against its own table

Rule 34 says the global sweep credits a name that exists as a column on *any* table, so it
cannot tell whether a field belongs to the entity declaring it. `DockDoor` is what that
blind spot was hiding. The interface declared:

| declared | reality |
|---|---|
| `supportedEquipment: string[]` | the column is `equipment_capabilities`, a JSON **object** |
| `hasLoadingEquipment: boolean` | no column |
| `maxWeightCapacity: number` | no column |
| `currentAppointmentId` | no column — appointments reference doors, not the reverse |
| `estimatedReleaseAt` | no column, and **it rendered**: "Release: HH:MM" |

`dock_doors` carries `door_number`, `door_type`, `status`, `equipment_capabilities`,
`current_trailer_id`, `last_occupied_at` and `is_active`. Nothing else. Only
`estimatedReleaseAt` was reported by the global sweep, and only because no other table has a
column by that name.

**`last_occupied_at` exists and is not the same thing.** It records when the door was last
occupied — a fact about the past — where `estimatedReleaseAt` is a prediction. Mapping one
onto the other would have been the `currentMileage` defect exactly: the right number under
the wrong label, which is how that one shipped. The card shows "Last occupied" now.

The audit is pinned as an assertion rather than a one-off: `DockDoorResponse`'s declared
fields must all be columns of `dock_doors`, minus one explicitly-listed denormalised value
the handler resolves. That generalises to any response model, and is cheaper than the global
sweep because it needs no vocabulary — just the table.

## Rule 37 — prose about a defect gathers around the defect, so strip comments in every source assertion

`assert "currentMileage" not in logistics_ts` has now failed twice against **fixed** code.
First the comment explaining the deletion contained the word; then, months of work later in
the same session, a comment in the DockDoor audit cited `currentMileage` as the precedent for
*not* mapping `last_occupied_at` onto `estimatedReleaseAt`.

Method rule 14 said a substring match on source is satisfied by prose. Three occurrences in
one file say something stronger: **the prose density around a defect is highest exactly where
the assertion looks**, because that is where the explanation goes. Strip comments in every
source-text assertion as a matter of course, not when one fails.

## The narrow question beats the broad one: response models against their own tables

The wire-vocabulary sweep asks *does any backend file produce this name?* — a broad question
with a fuzzy answer, which is why it credited four of `DockDoor`'s five phantom fields (rule
34) and why it needed a request-vs-response correction (rule 36).

`test_response_models_match_their_tables.py` asks a narrow one instead: **is this field a
column of THIS entity's table, an alias of one, or an explicitly-listed value the handler
resolves?** No vocabulary, no heuristics, and the pairing is mechanical
(`DockDoorResponse` ↔ `DockDoor`). It covers 34 response models and it is *stronger* on every
model it covers, at the cost of covering nothing else.

It found **nothing new**, which is the result worth recording: the DockDoor audit was the last
of them, and 34 models are now proven rather than unexamined.

Two exceptions, both listed with who fills them: `DockDoorResponse.trailer_license_plate`
(denormalised by the handler in one batched query) and `TaskColumnResponse.task_count`
(computed with a batched `GROUP BY`). A third class needed crediting rather than exempting —
fourteen models expose the `meta_data` column as `metadata` through `AliasChoices`, and a
guard that reported all fourteen would have been ignored within a day.

**Both directions of the response-model trap are now guarded.** Declaring a field with no
source fails this test; failing to declare a field the handler resolves fails the per-feature
test that resolved it. The two defects look nothing alike and cost the same.

## Rule 38 — prefer the check with a definite answer, even if it covers less

Given a choice between a sweep that inspects everything approximately and one that inspects
part of the system exactly, the exact one is worth more per line. The broad sweep has produced
nine findings and needed three corrections (rules 34, 36, and its own vacuous baseline at rule
31); the narrow one was right first time and its false-positive surface is a two-entry list.

Breadth is not free: every heuristic that widens coverage also widens the space of results
nobody can act on, and a sweep is only useful while people still read its output.

## Fourteen handlers asked the caller which tenant to write to

The mirror of rule 38 — request models declaring fields no column holds — came back almost
clean: one finding, `UserCreate.password`, which is correct by design (hashed into
`password_hash`, never stored). But that clean result is misleading, and the reason matters
more than the result.

**The maintenance-schedule `priority` defect went through `payload: Dict[str, Any]`.** Twelve
route handlers take an untyped dict body, so there is no schema to check what they accept or
silently drop — the request-model sweep cannot see any of them. A sweep coming back clean over
the part of the system that *has* schemas says nothing about the part that does not.

Reading one of those handlers found this:

```python
organization_id=payload.get("organization_id")   # POST /transportation/vehicles
```

A guard written for that shape then found **thirteen more**, all identical
(`organization_id=data.organization_id`), plus `initialize_registries`, which did
`request.organization_id or current_user.organization_id` — preferring the client's value with
a fallback to the right one, so the fallback made it look safe.

**Thirteen of the fourteen were saved by row-level security, and one was not.** On an
RLS-covered table a FOR ALL policy's USING clause acts as the INSERT's WITH CHECK, so the
database refused the cross-tenant write and the caller got a 500 — bad error handling, not a
breach. `pg_class.relrowsecurity` is **false** for `vehicles`: migration 051's loop does not
cover it, nothing stood between the body and the row, and a create naming another organisation
succeeded. The mutation test confirms it.

That is the argument against leaning on RLS. Thirteen handlers were wrong and survived because
a policy caught them; the fourteenth was wrong in exactly the same way and shipped the defect,
and **nothing in the handler said which was which**.

## Rule 39 — six hand-fixes and no guard is a class that will come back

This shape had already been removed by hand from the yard trailer list, the dock doors, the
dock schedule, the maintenance schedule, the geofence zones and the dashboard overview. Each
carries a careful comment explaining *"From the TOKEN, never the payload"*. Fourteen more
instances were sitting in the same three files.

A comment records a fix; only a guard prevents the next one. The moment a defect is fixed for
the *second* time, the fix to write is the check — and the AST is worth the extra work over a
grep, because `organization_id=organization_id` and `organization_id=data.organization_id`
differ only in the value expression, and a substring search matches both plus every comment
explaining the defect (rule 37).

## Rule 40 — never act on truncated diagnostic output

The guard's first run printed thirteen offenders; `head -10` showed nine. Nine were fixed, the
guard was re-run, and four "new" ones appeared — which briefly looked like the fix having
caused them. They had been there all along, below the cut.

Pipe a guard's output to `cat`, or count the lines before believing the list is complete. This
cost one confused re-run here; on a longer list it would have meant shipping a partial fix and
believing it whole.

## Migration 055: the table that fell between two migrations

`vehicles` was the only fleet table without row-level security, and that is not a coincidence
about `vehicles` — it is what made it the one handler out of fourteen whose tenant-from-body
defect actually wrote a cross-tenant row instead of failing with a 500.

How the gap happened, and it is worth recording because it will happen again: 011 covered the
core tables. 033 extended that. 051 was written for *"the four fleet/maintenance tables that
had none"* and named them explicitly. `vehicles` arrived in 025 — too late for the first two,
not on the third's list. **A migration that enumerates its targets protects exactly those
targets, and the next table to arrive is unprotected by default.**

Migration 055 closes it, in the order 051 insists on: application layer first, policy second.
Verified before writing it — all seven functions that query `Vehicle` across `app/api` and
`app/services` already run on `get_tenant_db`, so no read was about to start returning zero
rows. `organization_id` is `varchar` here, as on 051's four, so the policy compares text with
no `::uuid` cast; copying 011's cast would raise on every row and leave the table looking
protected while every query against it errored.

**The change was caught by a guard the previous author wrote for exactly this.**
`test_vehicle_tenant_isolation_realdb.py` asserted `relrowsecurity is False` — recording that
the explicit filter was the *only* protection — with a failure message reading: *"vehicles now
has RLS enabled — good, but this test's premise no longer holds; check whether the sibling
logistics tables were covered too."*

That is a test written to fail when its own premise expires, firing across authors and months
apart, and handing the next person the exact question to answer. It is the same mechanism as
the CI-quarantine expiry and the pinned `get_db` debt counts, and this is the first time in
this session one of them has caught *me*.

## Rule 41 — a migration that enumerates its targets leaves the next arrival unprotected

011, 033 and 051 each named the tables they covered. Every table added afterwards starts
outside every policy, and nothing says so — `relrowsecurity` is simply false, which is
indistinguishable from a deliberate exemption.

The durable fix is not another enumerating migration. It is a test that asserts **every table
carrying an `organization_id` column has a policy**, so a new table fails the suite the day it
lands rather than the day someone reads a handler carefully. That is
`test_every_tenant_table_has_a_policy.py`, and running it for the first time was informative:

**61 tenant tables. Six with no policy, five with a policy that is not FORCEd.**

| state | tables |
|---|---|
| no RLS, exempt by necessity | `users`, `api_keys` — read *before* a tenant is known, so a policy keyed on `app.current_org_id` would lock out login |
| no RLS, real gap | `error_events`, `edge_agent_status`, `notification_subscriptions`, `notification_deliveries` |
| RLS without FORCE | five `erp_*` tables |

The unFORCEd ones are the more dangerous state, and `app/api/erp_integrations.py` already says
why in a comment: its background sync *"appeared to work only because no ERP table has FORCE
ROW LEVEL SECURITY and the dev connection owns them"*. `relrowsecurity = true` on those tables
reads as protected while the only connection that matters is exempt.

**None of the nine is closed here, deliberately.** Each needs a migration plus an audit of
every query against that table — application layer first, policy second, the order 051
insists on. `error_events` is written by an ingestion path with no user context;
`notification_deliveries` by a dispatcher running as a background task; the ERP tables by a
sync that may or may not bind a GUC on every path. Enabling FORCE on `users` without tracing
every auth query is how you take down login. So the baseline records each with **what closing
it requires**, and the guard's job is that the list cannot grow.

The two permanent exemptions are marked `EXEMPT BY NECESSITY` and a test asserts the count of
*real* gaps separately, so the two kinds cannot blur into each other over time — which is what
turns a gap list into an approval list.

## The notification router: a conditional tenant filter, four times

Auditing `notification_subscriptions` — one of the four tables the policy guard recorded as
having no RLS — to see whether a policy could be added found the reason it mattered. Four
defects in one router and its service, all the same shape:

```python
org = getattr(current_user, "organization_id", None)
stmt = select(...)
if org is not None:
    stmt = stmt.where(... == org)
```

**A user whose `organization_id` is NULL had the filter skipped and read everything.** Absence
read as unrestricted access — and precisely the case this codebase's own `get_tenant_org_id`
exists to refuse: it raises 403 there and its docstring explains *"we fail closed rather than
fail open"*. A local `_org` helper reimplemented the same idea with the opposite default, in a
router whose tables have no policy to fall back on.

| where | consequence |
|---|---|
| `list_subscriptions` | every tenant's subscriptions |
| `delivery_log` | every tenant's **alarm titles and detail text** — the most specific operational information in the system |
| `delete_subscription` | **no tenant clause at all**: any authenticated user could delete any tenant's subscription by id |
| `_load_rules` (dispatcher) | every tenant's subscriptions **dispatched to** — an outbound delivery of one tenant's alarm to another's webhook, Slack or mailbox |

The delete is the live destructive one: the endpoint's `rowcount == 0 -> 404` check already
existed and was measuring the wrong thing — it proved a row had been deleted, not that it was
yours.

**The dispatcher one is latent and worth separating.** Both callers pass a real organisation
today (the test endpoint and the RUL notifier), so the None path was unreachable. But
`organization_id` is `Optional` with a `None` default, so the next caller to omit it inherits
the fan-out and nothing in the signature says so. Fixed by refusing rather than by hoping.

Every handler now depends on `get_tenant_org_id` and scopes unconditionally. The RLS gap on
these two tables stays open: the handlers use `AsyncSessionLocal` and bind no GUC, so a FORCEd
policy would empty every read — the audit the baseline asked for turned out to be the
application layer itself, and that is now done. The migration is the next step, not this one.

## Rule 42 — a test asserting emptiness must be given something to find

`test_the_helper_is_strict_even_when_called_directly` called `_load_rules(None)` and asserted
`[]`. It omitted the fixture that seeds subscriptions, so the table was empty and the assertion
held whatever the filter did. Restoring the fan-out did not fail it.

The mutation check is the only reason that surfaced — the test passed, read sensibly, and
inspected nothing. This is rule 21 in its most ordinary clothing: not a clever regex or a
proximity window, just a fixture left off a parameter list. **Every negative assertion needs a
positive premise, and for a database test that means rows.**

## The second variant: a client-supplied tenant *parameter*

The body-tenant guard was clean, so the class looked closed. It was not — the guard checks for
a tenant **assigned** from a request, and eight handlers were **receiving** one as a query
parameter instead:

| handler | shape |
|---|---|
| `geotab.py` × 6 | `organization_id: Optional[UUID] = None`, on `Depends(get_db)` |
| `operations.get_active_operations` | optional param, and the tenant join only happened *if* one was sent |
| `yard.get_detention_alerts` | optional param, filter applied only when present |

Every one was **Optional**, which is the dangerous half: a request that simply omitted the
parameter filtered by nothing at all. Whether that leaked depended entirely on whether the
table carried a policy — the same coin-flip that decided the fourteen body-tenant handlers.

**The geotab six also escaped the existing `get_db` guard**, and the reason is instructive:
that guard inspects a handler's own body for references to RLS-protected models, and these
handlers pass `db` to `geotab_service` and query nothing directly. An indirection of one
function call was enough to hide six handlers from a check written specifically to find them —
rule 34's shape again, in a different guard.

Their failure mode was the empty one rather than the leaky one: `get_db` binds no tenant GUC,
so the policy filtered every row and those endpoints returned nothing to anybody, including for
their own organisation. `geotab.py` had already been *removed* from the `get_db` debt list when
`get_fleet_summary` was fixed — the file was marked done with six handlers still wrong.

`workcells.get_organization` is the one legitimate case and stays: `GET
/organizations/{organization_id}` must accept the id, and it compares against the token and
404s. It is allowlisted with that reason, and a further test asserts the comparison still
exists — an allowlist entry that claims a handler validates its input has to be checked, or it
is just a hole with a docstring.

## Rule 43 — a guard proves the absence of the shape it models, not of the class

Three guards have now been written for one class — tenant chosen by the caller — and each was
clean while the next variant sat in the same three files:

1. `organization_id=payload.get(...)` — assignment from a body. **14 handlers.**
2. `organization_id: Optional[UUID] = None` — a query parameter. **8 handlers.**
3. `if org is not None: stmt = stmt.where(...)` — a filter applied conditionally. **4 handlers.**

All three are "the caller decides which tenant", and no single check saw more than one of them.
After writing a guard, the useful question is not *did it pass* but **what shape does it model,
and what else could express the same defect?** Each variant here was found by reading code the
previous guard had just declared clean.

## Rule 44 — a hand-maintained number in prose is a claim that will be wrong

The README stated "206 backend test files". The measured figure was 201. Nobody lied: the
number had been incremented by hand at each milestone and drifted, the way every hand-maintained
count does. Two other claims in the same paragraph had drifted the same way — the rule range said
21–38 while the doc had reached 41, and the class count said thirty-seven while the table had
grown past it.

The method-rules index had drifted **three separate times**: rules 22–27 were written as
sections while the numbered list stopped at 21, then 28–31, then 33–43. Each repair was by hand,
which is precisely the situation rule 39 describes — a comment records a fix, only a guard
prevents the next one. `test_method_rules_are_indexed.py` now asserts the list is contiguous
from 1, that every `## Rule N` section has a list entry and vice versa, and that the README
cites the real range.

**Which numbers deserve a guard and which do not.** A rule range and a class count change rarely
and mean something, so they are worth asserting. A test count changes on every commit — pinning
it would make every new test fail the suite, which converts a documentation nicety into an
obstacle. Those stay hand-written and are re-measured at each milestone rather than trusted;
this document's own counts were re-measured to write this paragraph, and two of the three were
wrong.

Writing the guard also required scoping care worth recording: several prose sections in this file
enumerate with the identical `1. **…**` formatting — the five maintenance-mode defects, the four
things the CI-quarantine guard asserts — so a file-wide regex reports duplicate rules 1–5 and is
useless. The check reads only between the list's heading and the next `---`, and a separate
assertion proves that scoping is narrower than the whole file.

## Migration 056: closing two of the four recorded gaps

The policy-coverage baseline recorded `notification_subscriptions` and
`notification_deliveries` as REAL GAPS, and each entry said what closing them required: *"a
check of the dispatcher, which reads subscriptions from a background task with no request
behind it."* Doing that check found four defects rather than a clean bill (see the section
above), and fixing them was the actual precondition — every session in that router was an
unbound `AsyncSessionLocal`, so a FORCEd policy would have **emptied every read** instead of
protecting anything.

All six sessions now go through `core.tenant.tenant_session`, which binds the GUC and
re-asserts it per transaction, and migration 056 adds the policy. Two of the four real gaps are
closed; the guard's own staleness check named them for removal from the baseline, which is what
a baseline is for.

**The migration was wrong on its first run, loudly.** It omitted the `::uuid` cast and the whole
chain failed to build the test schema: `operator does not exist: uuid = text`. The ORM declares
`Column(UUIDString(), …)`, which reads like a varchar — and genuinely is one on the tables in
051 and 055 — but `022_notifications.sql` declares `organization_id UUID`. **The DDL is the
authority on a column's type, not the model**: a custom SQLAlchemy type can render as either.
Better to be loudly wrong than quietly wrong here — a policy comparing incompatible types raises
on every row rather than silently matching none.

## Rule 45 — a module-level copy of a patched name is a defect waiting for a new caller

`tenant_session` held `AsyncSessionLocal`, captured by `from app.db.database import …` at
import. The test harness rebinds that name **per module**, sweeping `sys.modules` for anything
carrying the attribute — and whether `app.core.tenant`'s copy is among the rebound ones varies
by test.

That was invisible for as long as the helper was only reached through the `get_tenant_db`
dependency, which the suite overrides wholesale. Pointing a **service** at it — the notification
dispatcher — surfaced it instantly as one failing RUL test whose error had been swallowed into a
warning log: `role "placeholder" does not exist`.

The helper now looks the name up on `app.db.database` at call time. There is one binding that
matters and it reads it, instead of holding a copy that may or may not have been patched.

**And the first test for this was too weak.** It compared engines, which passed under the
mutation as well as the fix — because in that test's context the module's copy *happened* to be
the patched one, and the entire defect is that this varies. The test now poisons
`app.core.tenant.AsyncSessionLocal` with a maker that raises and asserts `tenant_session` still
works. Simulate the broken state rather than hoping the test runs in it.

## Class 43: a scoped read against a column the write path never fills

`GET /api/v1/edge/fleet` backs the `/admin/collectors` page. It filtered on
`EdgeAgentStatus.organization_id` — and `POST /api/v1/edge/heartbeat`, the only writer of that
table, **never set that column**. Nothing else in the tree did either; the only three
occurrences of `organization_id` in `app/api/edge_fleet.py` were the two read filters and a
comment.

So the column was NULL on every row ever written, `NULL = '<uuid>'` is NULL, no row could
satisfy the predicate, and the fleet page was **empty for every tenant in every deployment since
the endpoint was written**. `/fleet/{agent_id}` 404'd for the same reason. An operator reads
that as "no agents are enrolled." The frontend even says so in as many words: *"No edge agents
have reported yet. Agents appear here once they enroll and send a heartbeat."*

**The filter was not the mistake.** It was added as a security fix, and the comment above it
still explains why: the read used to be unscoped, so every authenticated user saw every tenant's
agent ids, versions, certificate expiry and buffer depths. That fix was right. It scoped a read
against a column the write path never populated, and so converted a leak into a permanent
emptiness — and nothing failed, because there was no test on either endpoint. The only edge
fleet tests covered the pure liveness helper, which needs no database.

### The obvious fix would have been a hole

An agent's tenant belongs in its certificate: already verified, already the identity the
heartbeat trusts. But `sign_csr` did `.subject_name(csr.subject)` — it copied the CSR's entire
subject into the signed certificate and validated only the CN. Every other attribute was
client-supplied and came back CA-signed, indistinguishable from a server assertion.

Reading the organisation out of that subject would have been **the tenant-from-the-body defect
wearing a certificate**, and worse than the original: durable for the certificate's lifetime and
carrying the CA's signature. The CA now builds the subject itself, from the agent id it checked
and the organisation the *server* chose; anything else in the CSR is discarded. The guard
asserts the whole subject, not just the O — `{CN, O}` and nothing else — so the next attribute
somebody starts trusting is covered before it is trusted.

Enrolment decides the organisation server-side: `EDGE_ENROLLMENT_ORGANIZATION_ID` if set, else
the single organisation when there is exactly one, else **refuse**. There is deliberately no
`organization_id` on the enrolment request.

### Migration 057, and why unattributed rows are deleted rather than kept

Once the policy is on, a row with a NULL `organization_id` is readable by no tenant and
updatable by no tenant — and it makes its agent permanently broken, because the next heartbeat
cannot see the row through the policy, tries to INSERT, and hits the primary key. Deleting them
is what makes the upgrade self-healing: the next heartbeat recreates each row, attributed.
Nothing is lost that a thirty-second heartbeat does not restore.

A certificate issued before agents carried an organisation has no tenant to bind, so its
heartbeat is refused with a 409 naming the remedy rather than failing the policy check with a
500. Certificates are issued for `EDGE_CERT_TTL_DAYS` (30), so **the transition window closes
itself within one certificate lifetime** — which is the fact that made closing this gap safe.

## Rule 46 — a filter added to a read is a claim about the write path

Adding `WHERE organization_id = :org` asserts that something fills `organization_id`. Nobody
did, and nobody had to: the read got safer, the tests stayed green, and the page went blank.

A scoping fix is only half a change. Check the writer in the same commit — and when a column is
supposed to be populated, assert it **from the write side**, against the database, not by
reading the handler that is supposed to set it.

The tell is available statically and cheaply: a column that appears in `WHERE` clauses and never
on the left of an assignment is a column nobody writes.

## Rule 47 — fixing one half of a defect can arm the other half

`agent_id` is the primary key of `edge_agent_status` — one global namespace across every tenant
— and the CA signs a certificate for whatever id is asked for. While the organisation column was
never written, that was inert: a second tenant enrolling the same id overwrote counters on a row
nobody could read.

Attributing the row gives it teeth. The last heartbeat would win the *tenancy*, so B enrolling
`agent-of-a` moves A's agent onto B's fleet page and off A's. The fix for one defect created the
conditions for the next, in the same file, in the same commit.

Ask what a dormant defect was being kept dormant *by*, before removing it. The heartbeat now
refuses the rebind — and under the policy that check is unreachable (the other tenant's row is
filtered out of the lookup), so the collision surfaces as the primary-key violation, which is
handled too. Both paths, because the SQLite offline path has no policy at all.

## The last recorded gap is a grain problem, not an audit

`error_events` is the fourth entry, and working it produced no migration — deliberately. The
table is keyed on `fingerprint` ALONE: one row per distinct error for the whole platform, shared
by every tenant that hits the same bug, with `organization_id` naming only the last one to hit
it. A tenant policy over that column would hide errors that genuinely are the caller's, which is
worse than the disclosure it would fix.

`test_error_triage_sample_redaction_realdb.py` already recorded that finding and the decision it
led to — redact the two payload-bearing fields cross-tenant rather than pretend the table is
partitioned — with evidence: org A retrieved a row owned by org B whose message carried a
customer identifier and whose traceback carried a payment-card value. Re-deciding that quietly
would have been the wrong move; the baseline entry was corrected instead, because it said to
"check the ingestion path" and the ingestion path is fine. Closing this needs the primary key to
become `(fingerprint, organization_id)`, a composite foreign key from `error_event_buckets`, and
the upsert's `ON CONFLICT`/`COALESCE` rewritten — or a platform-admin role to gate the view on.

**An entry that names the wrong precondition is worse than one that names none**, because it
looks actionable. That is what a baseline is for.

## Two services had their own copy of the tenant session

`tenant_session` was extracted because the test harness held four hand-copied overrides of
`get_tenant_db`, each under a comment reading *"Mirrors the production get_tenant_db"* — and
each mirroring the RLS-after-commit defect as faithfully as the behaviour, which is why the suite
could not see it. A guard closed that for the test doubles.

**Production had two more, and that guard could not see them.**
`ExportProcessor._tenant_session` and `BulkProcessor._tenant_session`, both
`@asynccontextmanager`s yielding a bound session, both under the same *"Mirrors
app.core.tenant.get_tenant_db"* docstring. Found by asking a different question than the guard
asked: not "which test files override the dependency" but "which code in the whole tree binds
`app.current_org_id`" — thirty call sites, two of which were helpers rather than call sites.

They were not merely redundant. Both used a SESSION-scoped GUC (`set_config(..., false)`) so the
binding would survive intermediate commits, and reset it to `''` in a `finally` so it could not
ride a pooled connection into someone else's request. The reasoning is sound and the reset was
there — but it holds only while the reset runs. `tenant_session` gets the same
survive-the-commit property from an `after_begin` listener with a TRANSACTION-scoped GUC:
nothing outlives the transaction, so there is nothing to reset and no path where a leak depends
on cleanup running. Both now delegate.

The new guard also sweeps for the other way the thirty inline sites go wrong: a transaction-scoped
GUC, a commit, and more statements after it — every one of which runs unbound. There are none
today, and `run_erp_sync` is one `await db.commit()` away from being the first.

**The detector was wrong first, as usual.** With a bare `.get(` in its list of "still talking to
the database" it flagged `report_download_audit._insert_audit`, whose only line after the commit
is `logger.error(..., reason=details.get("reason"))` — a dict lookup in an exception handler.
The token list now names the receiver, and a negative control pins that exact shape.

## Rule 48 — a guard answers the question it was asked, so ask the broader one too

The duplicate-tenant-session guard asked *"which test files override `get_tenant_db`?"* and
answered it correctly, for years, while two production services held copies of the same helper.
Nothing was wrong with it. It was scoped to where the copies had been found, which is the natural
scope and the one that misses the next instance.

The broader question — *"what in the whole tree binds `app.current_org_id`?"* — is barely harder
to ask and returns thirty call sites instead of four files. Two of them were the helpers.

Related to rule 43 (a guard proves the absence of the shape it models) but distinct: there the
model was too narrow for the class, here the *search space* was. When a guard has been green for
a long time, re-derive its population from first principles rather than trusting the enumeration
it was born with.

## Migration 058: the five ERP tables that read as protected and were not

RLS enabled without FORCE is the more dangerous state, not a lesser one. The owner bypasses the
policy, and the application connects as the owner in several deployments — so
`relrowsecurity = true` answers the question, and answers it wrongly.
`app/api/erp_integrations.py` records what that cost in a comment: its background sync *"appeared
to work only because no ERP table has FORCE ROW LEVEL SECURITY and the dev connection owns
them."* The tenant GUC that sync now sets had never actually been under test.

Every live writer turned out to bind the tenant already: `run_erp_sync` sets it explicitly and
holds one transaction with a single commit, so the transaction-scoped GUC covers every statement;
the mapping routes run on `get_tenant_db`; the webhook path sets it after resolving the tenant
from the integration record. The dynamics, oracle and SAP `*_data_extraction` services and
`erp_database_replication` also write these tables and take their session as a parameter — but
**nothing imports them**: ~1,800 lines reachable from no router, no worker and no test but one
honesty check.

## Rule 49 — a suite that skipped is not a suite that passed

The baseline entry asked for "one real-DB run to confirm before the migration", and the run was
available: four real-Postgres ERP suites. They report **25 passed, 29 skipped** — and the 29 are
`test_erp_sync_e2e_realdb.py` and `test_erp_platform_integration_realdb.py` in full, skipped for
want of live Dataverse credentials. Every test that touches `run_erp_sync` is in that 29.

The migration header had already been written claiming those suites confirmed it. Green, from a
suite that never executed the code the change can break — the same shape as every "verdict from
absence" defect in this document, this time in the verification rather than the product.

The fix is not to acquire credentials. It is to notice which part actually needs them: the vendor
HTTP call, and nothing else. `test_erp_background_sync_under_force_realdb.py` stubs the connector
and drives the real `run_erp_sync` against real Postgres with the real policy — then asserts
FORCE is actually on first, because a successful write proves nothing while the owner is exempt.
Controlled by deleting the `_set_tenant_guc` call: three of its tests go red.

**Read the skip count, not just the pass count.** A skipped test is an unanswered question
wearing a green tick.

## An empty list that meant two different things

Found while writing the above. `GET /erp/integrations/{id}/sync-status` returned `200 []` for
another tenant's integration id — no leak; the explicit filter and the policy both held. But `[]`
also means *"this integration has never synced"*, which is the operator's answer to "did the sync
run?", and the ambiguity was there for the OWNER too: a wrong id and a never-synced integration
were the same response. The integration is now resolved first and an unknown one is a 404, so an
empty list has exactly one meaning.

404 rather than 403 for another tenant's id, matching the rest of that file: distinguishing them
would confirm the id exists.

## The eleventh finding: seven fields on one interface, and the value standing next to them

`RepairOrder` was the largest cluster the wire-vocabulary sweep had left. `repair_orders` has
thirteen columns and `_order_out` emits eleven of them; the TypeScript described a richer object
that no endpoint produces and no migration plans.

The sharpest of the seven is `assignedTechnician`, because everything around it worked.
`repair_orders.vendor` — the shop that actually did the repair — was sent on every response and
rendered **nowhere**, while the card offered a `Tech:` line that could never populate. The same
shape as the `geoTabDeviceId` finding: a row that cannot fill itself standing next to the value
it should have shown. `category` was in the same state, sent and unread.

The other six split across the sweep's three fixes:

  * **Deleted.** `workOrderNumber` — nothing in this product issues one. It had already been
    stripped from the panel; leaving the field optional kept the invitation open, and the mock
    `createRepairOrder` was still accepting it by minting `WO-YYYY-NNNN`. `actualCost` — a
    second cost on a table with one `cost` column, which IS the actual cost; two names for one
    number invites populating both. `laborHours` and `partsUsed` (with its `PartUsed` shape) —
    no columns, no tables, nothing pending.
  * **Renamed.** `issueDescription` and `reportedDate` were real data under invented names, and
    the adapter filled them from `title` and `openedAt`. Rule 35.

Renaming the type emptied the adapter: it had grown five fallbacks, four of which existed only
to bridge names the type had made up. What is left derives `vehicleNumber`, which the serializer
genuinely does not send.

## The twelfth finding: the first one fixed by making the server send it

`MaintenanceCosts` declared six figures and `/maintenance/costs` sent two. The client made up
four:

  * `monthlyAverage` was `ytd / 12` — computed in January as readily as in December, so a fleet
    three weeks into its year saw a twelfth of its spend labelled as a monthly average;
  * `costPerVehicle` and `upcomingEstimated` were hardcoded zeros, the second in a highlighted
    box reading **"Upcoming (Est.) $0"**, which reads as *nothing is coming up* rather than
    *nobody calculated this*;
  * `monthlyBreakdown` was a required array nothing sent, so the trend chart drew nothing.

An earlier pass removed the fabrications and left four blank rows. That was right, and it was
not the end of the job — **delete and rename are the cheap two of the three options, and the
third is the one that finishes the feature.** Every figure is a fact about data the endpoint
already had: spend per elapsed month, YTD over months elapsed, the sum of
`maintenance_schedules.estimated_cost` on work not yet done, and YTD over the fleet size. The
endpoint had been passing `[]` for schedules, which is where the cost of not-yet-done work lives.

`costPerVehicle` needed the one thing repair orders cannot supply: the fleet size. A vehicle
with no repairs this year has no row among them, and it is exactly the vehicle that makes the
average meaningful.

### None and zero, three times in one endpoint

* An empty fleet has **no** cost per vehicle. Not zero — and not a division by zero, which is
  how it became a hardcoded 0 in the first place.
* Outstanding work that nobody has costed has **no** estimate. Not an estimate of zero, which is
  what the highlighted box claimed. But a schedule explicitly costed at nothing is a real zero,
  and collapsing that to `None` would be the same error inverted — so both are pinned.
* A month in which nothing was repaired **did** cost zero. That one is a number, and dropping it
  from the breakdown shortens the year and moves every other bar.

## Rule 50 — a fixture in a shape no endpoint produces tests the fixture

The trend chart labelled its axis with `month.month.split(' ')[0]`. That is correct for
`"Jan 2024"`, which is what the mock contained, and it renders the server's `"2026-01"` as the
literal string `2026-01`.

The mock had never been wrong about anything else, so nothing pointed at it — and the panel test
used the same fixture, so the test agreed with the code about a format the server does not send.
Two artefacts agreeing with each other is not a check; they were copies of one assumption.

The same thing appeared twice more in this cluster: `MaintenancePanel.test.tsx` carried
`issueDescription` AND `title`, `reportedDate` AND `openedAt`, so it could not distinguish the
panel reading the wire from the panel reading names the adapter had invented. Fixtures now carry
exactly what the serializer emits, and the mock uses the wire's date format.

## The thirteenth finding: one cluster, all three fixes, and a hole in the sweep itself

Eight entries across `Vehicle`, `Driver`, `Shipment` and `HOSViolationAlert`, all about where
something is or what it is assigned to. Between them they needed every option the sweep offers.

**Renamed.** `Vehicle.currentLocation` is `vehicles.last_location`, which the serializer emits
as `lastLocation` with exactly the shape the panel reads. Every location block on the vehicle
panel was dead against a value arriving on every response.

**Served.** `Driver.currentVehicleId` and `.currentShipmentId` are not columns on `drivers` and
should not be: a vehicle names its driver, and a shipment names its driver. The driver's side of
both is a **reverse lookup**, which is why comparing the table to the type says "no such column"
about a field that is perfectly derivable. Two batched queries, and the shipment one excludes
terminal statuses — a delivered load is not what the driver is on now.

**Deleted.** `Shipment.currentLocation`, with the "Current Location (GeoTab)" card it fed. A
shipment has no position; the nearest real one belongs to the driver's vehicle, two hops away
through `shipments.driver_id` → `vehicles.current_driver_id`, and goes stale the moment a driver
changes vehicle. The heading was the most specific claim in it — GeoTab is not the source of a
shipment's position, because nothing is. `Shipment.estimatedDelivery` went too: it drove a
running-late warning (yellow when the ETA exceeded the schedule) that could never fire, because
nothing in this product predicts a delivery time.

`HOSViolationAlert` was deleted **whole**. One occurrence in the entire frontend: its own
declaration. Nothing constructed it, nothing rendered it, and none of its fields had a source. A
type nothing constructs is a plan, not a contract.

`Driver.lastLocation` went with them although the sweep never reported it — `drivers` has no
position column, and the global vocabulary credited the name from `vehicles`. Rule 34's blind
spot, found by auditing the interface against its own table rather than against the tree.

## Rule 51 — an upper-bound assertion is satisfied by zero

The N+1 guard for the driver lookups counted SELECTs and asserted `len(vehicle_reads) <= 1`. It
passed against a deliberate one-query-per-driver mutation, and the reason was two mistakes
stacked so that neither was visible:

  * the matcher was `" FROM vehicles" in statement` — **with a leading space**. SQLAlchemy
    renders the clause at the start of a line, so `FROM` is preceded by a newline and the count
    was always zero;
  * `0 <= 1` is true, so the bound could not tell "batched" from "matched nothing".

The file even had a non-vacuity check — `assert statements` — and it passed, because *something*
was recorded. It proved the listener was attached, not that the thing being counted was ever
found.

**Assert the exact count.** `== 1` fails at zero, which makes the matcher's silence a test
failure instead of a pass. An upper bound on a number you also have to discover is two claims in
one assertion, and the weaker one hides the stronger.

## Rule 52 — when a fix does not move the baseline, suspect the detector

`Driver.currentVehicleId` stayed on the declared-but-unsent list after the server started
sending it and the panel started rendering it. The obvious reading is that the fix did not work.
The actual reason: `_wire_vocabulary` collected string keys from dict LITERALS, and
`transportation.py` builds several responses by validating a model and then adding derived keys
by subscript — `row["carrierName"] = …`, the HOS remaining hours, the driver's vehicle and
shipment. Every one was invisible, and would have been reported as unsourced the moment a client
declared it.

A baseline that does not move when the code does is evidence about **one of the two**, and it is
worth a minute to find out which. The widening carries a positive control (`carrierName` is
credited) and a negative one (a variable subscript credits nothing) — a vocabulary that absorbs
names too freely stops reporting anything, which is the same failure as one that reads nothing.

## The fourteenth finding: the yard, and an interface that had drifted whole

Four entries, two joins and two deletions — and one of them turned out to be a twelve-field
interface with two fields right.

**Served.** `YardTrailer.driverPhone` and `DockAppointment.driverPhone`. Both tables carry
`driver_id` and `drivers.phone` is where the number lives, so this is the same join as
`trailerLicensePlate` one finding earlier in the same file. It is the number an operator calls
about a trailer sitting on the yard, rendered in three places and sent by nothing.

**Deleted.** `YardTrailer.contents`, with `poNumber` beside it. `yard_trailers` records what the
trailer IS — type, seal, weight, temperature setpoint — and nothing about what is inside it. The
inventory table printed a dash on every row under a column headed "Contents"; it shows the seal
number now, which exists. `YardTrailer.lastLocation` went too, unreported by the sweep for the
same reason as `Driver.lastLocation` — credited from `vehicles.last_location`, a different
table. It gated a "Current GPS Location (GeoTab)" card behind a condition that was never true.

**`DetentionAlert` had drifted entirely.** The banner appears only when a trailer is at risk or
already accruing charges — only when it matters — and it read `<trailer id>` above a bare
`" • "`, then `"$"` with no number and `"N/A excess"`. Every field it rendered was `undefined`,
including the React `key`, so every row shared one.

The numbers were all being sent under the endpoint's names (`detention_minutes`,
`current_charge`, `elapsed_minutes`, `free_minutes`) — renames. The identifying details were
genuinely absent and are real columns on the row the loop already held: `license_plate`,
`yard_location`, and the carrier's name one join away. The alert also has no `id`, because it is
computed rather than stored, and a four-value `severity` union nothing ever produced was
replaced by the `status` the builder really emits.

**Only `excessMinutes` was reported.** `carrierName`, `location` and `estimatedCost` all exist on
other interfaces, so the global vocabulary credits them and the sweep sees nothing — rule 34,
for the third time in this batch. The per-interface read against its own endpoint is what found
the rest.

## Rule 53 — a NULL a column can hold is a value the schema has to accept

`metadata: Dict[str, Any] = Field(default_factory=dict)` **rejects** `None`. The factory fires
only when the key is ABSENT — and `model_validate(orm_row)` does not omit the key, it supplies
the attribute's value. Seventeen of the twenty-one `meta_data` columns in the migrations are
declared with no DEFAULT, so any row not written through the ORM has `None` there, and
`model_validate` raises inside the list loop: the whole PAGE 500s for that tenant, not the row.

Twelve schemas were in that state. Three had already been changed to `Optional[...] = None`, one
table at a time, after the same defect was found on appointments — nobody had asked the question
across the file.

**Found by accident**, which is the part worth recording. A real-DB test for an unrelated fix
seeded its trailers with raw SQL, as every real-DB test here does, and seven of its eight
assertions failed on a validation error that had nothing to do with what was being tested. A
test that touches the database the way other systems touch it finds things no unit test can.

Coercion rather than `Optional`, deliberately: `Optional` changes the wire contract (clients that
received `{}` start receiving `null`), and NULL metadata and empty metadata genuinely mean the
same thing — a row with no extra attributes. That is **not** true of the other absences in this
session, which is why a missing cost, a missing estimate and a missing fleet size all stay
`None` while this one becomes `{}`.
