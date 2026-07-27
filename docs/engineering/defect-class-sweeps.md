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

## The seven classes

The first five were all originally found in ERP. The sixth came out of the fifth,
and the seventh out of two failing tests that turned out to share a cause.

| Class | Swept | Found elsewhere | Guard |
|---|---|---|---|
| Response model stricter than its columns | all 61 API modules | **none** | `test_api_response_schema_matches_columns.py` |
| Pagination truncation | list endpoints | **3 ERP endpoints** | `test_erp_platform_integration_realdb.py` |
| Invented vendor endpoints | all 8 connectors | ERP only | `test_erp_no_invented_endpoints.py` |
| Silent success | all of `app/` | **1, live** | `test_logistics_sync_dashboard_honesty.py` |
| A name that claims a side effect | all of `app/` | **1, in the control path** | `test_helper_names_match_behaviour.py` |
| Data reported as kept, but discarded | quarantine/DLQ paths | **1, live, on ingestion** | `test_edge_ingest_quarantine_retention.py` |
| A test double that reimplements what it stands in for | every `get_tenant_db` override | **4 copies, hiding an RLS bug** | `test_tenant_guc_survives_commit_realdb.py` |

---

## 1. A response model stricter than its columns — **clean**

A required response field over a nullable, defaultless column means a valid row cannot be
serialised: pydantic raises inside the handler and FastAPI returns 500, naming a
validation error in *our schema* rather than the data. It cost four ERP endpoints at once,
because create, list, get and update all built the same model.

**Swept:** every response model in `app/api/` paired to its own ORM model — 11 pairs
across 7 routers, 124 fields.
**Found:** nothing. The ERP models were the only offenders.

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
never mattered, and it is one line from mattering — the other six engines are all
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

---

## Open observations, not yet tickets

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
