# Defect-class sweeps

A record of defect *classes* found in one subsystem and then checked across the whole
platform, with what each sweep found and which guard keeps it closed.

**Why this document exists.** "Proven clean" and "never checked" look identical
afterwards, and only one of them justifies not looking again. Several of these sweeps found
nothing; without a record, someone would eventually redo the work — or, worse, assume the
class had been handled when it had not.

**And a "clean" result is a claim that can be wrong.** Class 25 was swept, reported clean,
and recorded as deliberately unguarded. It was not clean: the reader covered a seventh of
its subject, and the class contained a feature that had returned 422 on every call since the
day it was written. The correction is kept in place rather than tidied away, because the
route to a wrong "clean" — a detector corrected twice, then trusted *because* it had been
corrected — is the most reusable thing in this document.

**Counting.** The heading counts rows in the table below. Not every row has a numbered
section: the sections are the ones whose reasoning was worth writing out. The heading said
"sixty" while the table held forty-two and the sections stopped at twenty-nine — a number
nobody had recounted since it was written.

The method throughout: find a class of bug where **code looks wired and cannot work**,
fix the instance, then ask whether the same shape exists elsewhere. Every guard listed is
mutation-tested — reverting the fix must fail the test, or the guard proves nothing.

---

## The one hundred numbered classes

**The count is the numbering, and it was already stale before this line was corrected.**
This heading read "forty-seven" while the document's own highest class was 60 — the summary
table below lists the early classes as rows, later ones got their own `## Class N` sections,
and nobody reconciled the two. Stated as the highest number assigned, which is the one thing
a reader can check against the document in front of them (rule 75).

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
| A modal that catches nothing over a store that re-raises | all 10 task mutations in `components/kanban/` | **10 of 10 silent — 6 of them pixel-identical to success** | `CreateTaskModal.test.tsx`, `TaskDetailModal.test.tsx` |
| A polled reading that cannot say it stopped arriving | every `refetchInterval` query and its consumers | **3 live: the alarm badge, the alarms page, kanban metrics** | `polledQueriesReportFailure.test.ts` |
| Two normalisers for one question, contracts differing | all 31 `x?.y \|\| <falsy>` sites in the frontend | **1 live of 31 — and it was in the shared API client** | `handleApiError.test.ts` |
| A gate in a workflow that branch pushes never reach | both workflows' triggers vs their blocking steps | **2 of 3 checks unreachable — every dev branch, since both existed** | `test_branch_pushes_reach_the_gates.py` |
| A query parameter sent in the body | all 22 bare-scalar routes vs their frontend callers | **1 live — the route 20 lines below the one FS-420 fixed** | `test_required_query_params_are_sent_as_params.py` |
| A scope that stops at a lane boundary, unrecorded | all 40 mounted mutation surfaces vs the middleware | **31 outside it, none of them written down** | `test_the_idempotency_seam_is_declared.py` |
| A field declared, returned, and dropped in between | yard's 12 mutating routes | **2 fields on the one route no test drove** | `test_a_checkpoint_records_who_inspected_it.py` |
| Two fabricated defaults compounding into a billed figure | 10 numeric fallbacks in `app/services/` | **2, in one call chain — $1,333.33 invented** | `test_freight_costs_say_what_they_invented.py` |
| A capped list that cannot say it was capped | every `limit`-bearing GET | **12 bare arrays; `/rul` fixed, the rest recorded** | `test_rul_truncation_is_reported_realdb.py` |
| An audit write with no tenant bound | every `audit_logs` writer | **4 of 8 — exports, bulk jobs and flag changes recorded nothing** | `test_audit_writers_bind_a_tenant_realdb.py` |
| A handler that builds its own unbound session | every inline `AsyncSessionLocal` in `app/api` | **5 live: 3 endpoints 404ing on your own asset, 2 reporting an empty fleet** | `test_tenant_session_guard.py` (second idiom) |
| A request body field the endpoint does not declare | every frontend POST/PUT/PATCH | **the 2026-08-02 sweep called this clean and was wrong — 1 live, and the feature had never worked** | `test_frontend_body_fields_are_declared.py` |
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
| An insert order no test can see | every model with an FK column | **62 models unorderable; the demo seed died on it and 3,200 tests could not** | `test_insert_ordering_is_possible.py` + FK enforcement in `conftest.py` |
| A naive `utcnow()` written to `timestamptz` | `app/` and `scripts/` | **12 in `scripts/`, one anchoring the entire demo dataset** | `test_no_naive_utcnow.py` (extended to `scripts/`) |
| A caveat that dies at a response boundary | the three transcript endpoints | **1 live: `simulated` set on every chat path, declared on none of the readers** | `test_transcript_keeps_its_provenance.py` |
| A field the client cannot store | write bodies vs. the column's FK target | **1 live: a vehicle id posted into a trailer foreign key** | `test_dispatch_is_callable_and_says_why.py` |
| Text rendered at its own background colour | every routed page | **1 live, and the detector was wrong about 38 more** | `pagesUseThemeTokens.test.ts` |
| A response model declaring a field its table lacks | 34 `*Response` models | **clean after the DockDoor audit — 5 fields deleted there** | `test_response_models_match_their_tables.py` |
| A TS field the wire never carries | every `types/*.ts` field a component reads | **3 live: a relabelled odometer, a UUID slice shown as a work-order number, 3 of 5 cost figures** | `test_frontend_fields_exist_on_the_wire.py` |
| A field the compliance check reads that nothing writes | `hos_drive_hours_remaining` and its neighbours | **1 live, and the worst of the session: every fleet cleared of HOS violations** | `test_hos_remaining_is_derived.py` |
| A container default that contradicts its column | every `field=x or {}` / `or []` in `app/` | **1 live, and I had shipped it an hour earlier: every load-plan create 500'd** | `test_json_defaults_match_their_column.py` |
| A field you can set once and never correct | every `*Create` against its `*Update` sibling | **26 live across driver, shipment and trailer, incl. a seal replaced at the gate that could be marked intact while naming the old seal** | `test_what_can_be_created_can_be_corrected.py` |
| A handler branching on a key its schema cannot carry | every key read off a dumped model, AST-followed | **1 live: a tenant-scoped workcell check that has never executed, so no asset could be moved between workcells** | `test_handlers_branch_on_keys_their_schema_carries.py` |
| A write field TS calls optional that the server requires | every TS interface named like a backend model | **1 live: `AssetCreate.workcellId?` against a NOT NULL column** | `test_optional_in_typescript_is_optional_on_the_server.py` |
| An async handler whose rejection has no owner | every awaiting async handler passed to a JSX prop | **1 live, found by an unhandled-rejection line under a green run rather than by any assertion** | `asyncHandlersOwnTheirRejections.test.ts` |
| A background task nobody holds and nobody watches | every `create_task` call in `app/` | **10 of 20 discarded, incl. one fired per request on the ingest path** | `test_background_tasks_have_an_owner.py` |
| A task created from a thread that is not the loop's | every `create_task` in the edge agent, by CALLER | **3 of 6 raise rather than schedule: every MQTT reading and every watched file was dropped** | `test_a_collectors_reading_reaches_the_callback.py` |
| A write schema no route ever wired | all 47 `*Create`/`*Update`/`*Request` models | **1 live: an update contract designed, written down, and never connected — the route took query parameters instead** | `test_a_correlation_can_be_completed.py` |
| An entity you can create and never update | every Create/Update schema pair, joined via the OpenAPI request bodies | **5 live: a dock appointment that could not be rescheduled, a load plan, a freight charge, a route that prices shipments, a dock door** | `test_what_can_be_created_can_be_updated.py` |
| A widened schema whose handler enumerates fields by hand | `update_task`, the one non-generic update handler | **19 kanban fields declared and dropped, caught before shipping** | `test_a_task_and_its_rule_can_be_corrected_realdb.py` |
| A call to a method that does not exist | 211 attribute accesses on module-level singletons | **clean — written after `broadcast_to_org`, which raised in a background task after the 200 had gone** | `test_singleton_calls_resolve.py` |
| A nullable value formatted as a date | 236 `new Date(x)` sites, via the TS type checker | **impossible by construction: `strict: true` makes it a compile error, and the typecheck is a blocking gate** | none needed — `test_branch_pushes_reach_the_gates.py` keeps the gate |
| A background task whose arguments do not fit | all 15 `add_task` sites, bound via `inspect.signature` | **clean, and mutation-verified from both ends — the call site and the target signature** | `test_background_tasks_are_callable.py` |
| A mutating route no test ever names | all 251 mutating routes vs every test file | **13 of 251; the 4 in this lane now driven or their unreachability recorded** | `test_the_unexercised_mutating_routes_realdb.py` |
| A non-null assertion on a nullable field | all 27 `!` assertions, via the TS checker | **24 flagged by type, 0 defects — every guard is upstream of a boundary narrowing cannot cross; not statically sweepable** | none, deliberately |
| A driver thread calling back into us | every collector with `loop_start(` or `Observer(` | **3 found; the third was already correct and the earlier API-keyed sweep was blind to it either way** | `test_a_collectors_reading_reaches_the_callback.py` |
| A ratchet with no margin left | the frontend coverage thresholds vs measured | **statements clearing by 0.02 points; restored to 0.38 by testing a 0%-covered client** | `vitest.config.ts` thresholds, enforced by `quality-gates.yml` |
| A rejected login that tells the user nothing | the live sign-in path, driven end to end | **1 live: the global 401 interceptor reloads the page, destroying the error before it renders** | `e2e/authenticated.spec.ts` |
| A test that has never reached its assertion | the live-backend e2e suite | **1: `ReferenceError` on every run since it was written, invisible because the file skips without a backend** | the same file, now with the name it referenced |
| A directory no compiler reads | every TS directory vs the tsconfig include | **1: `e2e/` was outside the typecheck entirely, which is why the above survived** | `everyTestDirectoryIsTypechecked.test.ts` |
| A codebase with no gate on a branch push | every tested directory in `ci-cd.yml` vs the branch-push workflow | **1: the whole edge agent, 386 tests; the guard for this class was blind to it because its list is hand-typed** | `test_branch_pushes_reach_the_gates.py`, now derived |
| Source outside every static checker | every directory of TS/Python vs the tsconfig include and the flake8 scopes | **528 Python and 7 TypeScript files read by nothing; all clean, all now gated** | `everyTestDirectoryIsTypechecked.test.ts` + the widened CI scopes |
| An env var read outside the settings object | every `os.environ`/`getenv` read in `app/` | **5 found, all deliberate and correct — recorded as examined rather than left open** | none needed |
| A source comment citing a guard that does not exist | 256 test filenames named in prose | **2 live: both guards real, both trails broken** | `test_cited_guards_exist.py` |
| A test the runner never collects | every test file on disk vs what pytest/vitest execute | **clean: 357/358 pytest (1 deliberate opt-in, job verified), 133/133 vitest; playwright already guarded** | `test_every_e2e_spec_is_run.py` (pre-existing) |
| A dependency failure that raises instead of reporting | the four health checkers and their aggregator | **clean, and now pinned — the swallow ratchet was tempting the opposite change** | `test_a_failing_dependency_is_reported_not_raised.py` |
| A response model that declares nothing | all 454 routes carrying a `response_model` | **23 permissive; 5 legitimately dynamic, the rest invisible to the coverage ratchet** | `test_a_permissive_response_model_is_not_a_contract.py` |
| A number in prose no guard reads | every count in the README | **2: the run-command block, one of which contradicted a guarded figure in the same document** | `test_readme_test_count_is_not_stale.py`, extended |
| A fix proven only against a test double | FS-675, re-run against a live mosquitto broker | **confirmed: 0 readings delivered before the fix, 3 after, same broker and publisher** | `test_a_collectors_reading_reaches_the_callback.py` + the live drive |
| A check-then-act split across an `await` | the file watcher's dedupe, driven by a real Observer | **1 live: every sliced file processed and emitted twice, invisible to any single-event double** | `test_a_collectors_reading_reaches_the_callback.py` |
| A failure reported to the log and to no instrument | 15 collectors, 59 `logger.error` sites, driven against a real 500 server | **`errors_total` incremented by nothing anywhere; a permanently-failing collector reads *up* and fires no alert** | `test_a_silent_collector_is_visible.py`, `test_every_collection_failure_is_counted.py` |
| A metric exported and fed by nothing | all 25 metrics vs. every call site in the package | **1: `opsgrid_edge_collector_messages_total`, published at zero since the merge that duplicated it** | `test_no_metric_is_exported_and_never_fed.py` |
| Health answered from the worker, not the work | every `.done()` / `is_alive()` in `app/`, then all 8 services `main.py` starts | **command dispatch reported `ok` while failing every iteration; 7 of 8 started services are in no health check at all** | `test_a_loop_that_achieves_nothing_is_not_healthy.py`, `test_a_started_service_is_a_service_somebody_watches.py` |
| A gauge whose writer died, still being read | every exported gauge vs what writes it, edge and backend | **2: `edge_buffer_messages` freezes if its loop fails, disarming both buffer alerts; `edge_agent_up` is never written 0, so EdgeAgentOffline could never fire** | `test_the_buffer_gauges_carry_a_freshness_stamp.py`, `test_edge_fleet.py` + staleness alerts |

Twenty-nine of these carry a numbered section below. **Response-shape mismatch is the
exception**: it was swept in the same pass as the `get_db` work and came back clean, so
it is written up inside class 10 rather than given a heading of its own. The row stays in
this table because a clean result that is not listed is indistinguishable from a check
nobody ran — which is the whole reason this document exists.

---

## The parts

This document was split at 7,239 lines (FS-584). The index above and the table below
stay here, at the path everything already cites; the sections moved.

No line counts in this table. Rule 44 — a hand-maintained number in prose is a claim
that will be wrong — and it would be wrong by the end of the commit that added it.

| Part | Covers |
|------|--------|
| [Part 1](sweeps/part-1-the-first-twenty-nine-classes.md) | the first twenty-nine classes |
| [Part 2](sweeps/part-2-writing-a-sweep-worth-trusting.md) | writing a sweep that is worth trusting |
| [Part 3](sweeps/part-3-the-tenant-and-audit-era.md) | the tenant and audit era |
| [Part 4](sweeps/part-4-the-contract-gate-slice.md) | the contract-gate slice |
| [Part 5](sweeps/part-5-the-carry-across-era.md) | the carry-across era |

`## Rule N` sections live in parts 3, 4 and 5; the canonical numbered list is in part 2.
`test_method_rules_are_indexed.py` reads the index and every part together, so the two
still have to agree — splitting the file did not split the check.
