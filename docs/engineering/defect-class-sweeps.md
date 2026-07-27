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

## The four classes, all originally found in ERP

| Class | Swept | Found elsewhere | Guard |
|---|---|---|---|
| Response model stricter than its columns | all 61 API modules | **none** | `test_api_response_schema_matches_columns.py` |
| Pagination truncation | list endpoints | **3 ERP endpoints** | `test_erp_platform_integration_realdb.py` |
| Invented vendor endpoints | all 8 connectors | ERP only | `test_erp_no_invented_endpoints.py` |
| Silent success | all of `app/` | **1, live** | `test_logistics_sync_dashboard_honesty.py` |

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

**Extraction modules with no callers.** `sap_data_extraction.py`,
`oracle_data_extraction.py` and `dynamics_data_extraction.py` expose
`extract_all_entities`, which nothing calls. Together with `erp_database_replication.py`
(task #36 in the current pool) that is a meaningful volume of code that looks like a
feature. Probably one ticket rather than four: *ERP extraction/replication modules that no
code calls — delete or wire.*
