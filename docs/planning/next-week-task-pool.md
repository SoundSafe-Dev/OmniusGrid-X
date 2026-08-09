# Next week — task pool

**Week of Monday 2026-08-10, written against the promoted `main`.** For **Harsh as Product
Manager**, grouped by lane so it can be handed out as-is.

**`main` moved on 2026-08-09** — 595 commits, the whole convergence plus two developers' work
that had been stranded off the trunk. Every figure below was measured on `main` at `41a49e9b`,
not on a branch and not carried forward from the previous pool
([`task-pool-2026-08-08.md`](task-pool-2026-08-08.md), archived).

> ### ⚠️ Before you start anything
>
> **Read [`docs/DEVELOPER-SYNC.md`](../DEVELOPER-SYNC.md) first.** If you have local work, push
> it before you pull — two of the three branches in last week's integration existed in exactly
> one place, and one of them was a laptop.
>
> Then **spend ten minutes reproducing the claim in your item.** The pool before last listed
> more work than existed; the one before this listed *less*, and dropped an entire lane. Both
> failures are silent. If an entry does not reproduce, correct it in place with the date and
> what you found.

Sizes: **S** under half a day · **M** 1–2 days · **L** 3+ days. Items carried from an earlier
pool say so, with the pool they first appeared in — **a repeat with no age on it reads as new
work and hides how long it has been sitting.**

---

## Verified state of `main`

| Fact | Value |
|---|---|
| Promoted | **2026-08-09**, `41a49e9b` — 1,061 commits |
| Backend suite | **4,112 passing**, 103 skipped |
| Frontend suite | **894 passing** across 115 files; `tsc` clean |
| Edge-agent suite | **372 passing**, 1 skipped |
| CI | **23 of 24 jobs blocking**; only `pre-commit` advisory |
| `response_model` | **468 / 520 routes**; 52 undeclared, ratchet at 52 |
| Contract gate | floor **380**; 402/471 measured 2026-08-08 with all dependencies |
| Alert rules | 51; **23 with no promtool test** |
| Migrations | **70**; 4 cannot be re-run, permanently |
| Swallow surface | `MAX_SWALLOWING` 201 · `MIN_COUNTED` 13 |
| Ratchets at zero | 4 |
| Stranded work | **none** — both developers' branches are merged and preserved |

**The number that moved the right way:** the merge added 48 routes and the undeclared count
went **down**, 53 → 52, because 27 of them were declared rather than allowed.

---

# Decisions — Harsh, as PM

### D1. Two user-administration surfaces are mounted · **new, and it has already cost something**

`/api/v1/users` (FS-221) and `/api/v1/auth/users` (invitations, reactivate, per-user reads).
Both are live. Keeping both was recorded as a merge-time decision rather than made, and it has
already produced one bill: four **duplicate operationIds** the generated SDK cannot represent,
worked around by tagging one router `Tenant Users & Invitations`.

The invitation surface is the fuller one — it is tenant-scoped through `get_tenant_db`, and the
frontend's Users page is built against it.

**Done when:** one is the product's user API and the other is deleted or redirected. Two
surfaces for one noun is how a client library gets written twice.

### D2. 1,777 lines of service code that production does not import · *carried from 2026-08-08*

| Module | Lines |
|---|---|
| `erp_error_handler.py` | 533 — the entire ERP dead-letter surface |
| `erp_security.py` | 483 |
| `device_provisioning.py` | 465 |
| `schema_registry.py` | 296 |

**Zero production importers each**, re-measured on `main`. Each has tests, which is how they
survived a dead-code sweep — a module with tests and no callers reads as live to any
importer-based check. **Wire or delete, per module, with an owner.**

### D3. `pre-commit` is advisory · *carried from 2026-07-26 — its third pool*

The only job of 24 that does not block. Making it blocking reformats **972 files**
(+55,068 / −40,118) across every lane. Pinned by
`backend/tests/test_the_precommit_decision_is_still_open.py`, and the only entry in
`docs/engineering/open-decisions.md`.

### D4. The contract gate's ceiling · *carried from 2026-08-08*

**45 of 471 operations cannot pass without a behaviour change** — 31 `AcceptedNegativeData`
(Pydantic lax mode coerces `{"is_enabled": 0}`) and 14 `UnsupportedMethodResponse` (a literal
path shadowed by a `{param}` route). Adopting either is a compatibility decision.

**Done when:** the target is written into the gate document, so nobody reads the 69-operation
gap as 69 tickets. It is two.

### D5. Four ratchets are at zero · S

Convert each to a plain assertion or keep the allowance deliberately. A ratchet at zero that
keeps its allowance is an invitation to nudge it.

---

# Hamad — platform, contract gate, frontend primitives

### FS-620. The contract floor cannot rise until the broker is guaranteed · M · *carried (FS-593)*

402/471 with all three dependencies; **380** is the floor and stays there. The broker step is
`continue-on-error` and removes its own container when it cannot verify its advertised address,
so the worst legitimate configuration scores 387 — and 387 minus the measured spread of 9 is
below the floor already in force. **The next raise is a CI change, not a code fix.**

### FS-621. 23 of 51 alert rules cannot be shown to fire · M · *carried (FS-596)*

`promtool check rules` proves an expression parses and nothing about whether a series exists to
make it true. The 23 are **named, not counted**, so the ratchet cannot be satisfied by deleting
a rule.

### FS-622. `components/common/` and `components/ui/` · M · *carried (FS-594/595)*

346 lines across 5 components with no test file, and 12 primitives with 2. `Select` was an
unlabelled combobox app-wide while reporting **100% line coverage**, because the a11y suite
never rendered it.

### FS-623. Coverage headroom is under one point · S · *carried (FS-597)*

46.94 measured against a threshold of 46. An unrelated refactor that adds one untested file
fails the build. FS-622 is how the room gets bought.

### FS-624. Four live services with production callers and no tests · M · *carried (FS-598)*

`insight_activation.py` (517 lines, behind a mounted router), `shop_floor_fanout.py` (326),
`inference_client.py` (137), `agent_release_storage.py` (165, one test file). Start with the
first: it is reachable over HTTP today.

---

# Hridyansh — OTA, edge agent

*Your nine commits are on `main`. Everything below is what integrating them surfaced, plus the
two items that were already yours.*

### FS-625. The fleet edit affordances exist on the server and not in the product · M · **new**

`PATCH /api/v1/fleet/{sites,tags,groups,cohorts}/{id}` are all live and now carry response
models. `FleetTargeting.tsx` can create and deactivate — **it cannot edit**. Six hooks are
written and unconsumed, recorded in `noNewDeadHookExports`'s register:
`useUpdateFleetSite`, `useUpdateFleetTag`, `useUpdateFleetGroup`, `useUpdateFleetCohort`,
`useFleetCohort`, `useFleetTargetPreview`.

**Done when:** the page can edit what the API can edit, and those entries are deleted.

### FS-626. Two helpers that never run · S · **new**

`fleet_targeting._membership_exists` — a bulk pre-check the bulk route bypasses by validating
per row; wiring it replaces four round trips with one. `maintenance_windows.local_date_for_weekday`
— the landed half of a DST fix, while the scheduler still works in fixed UTC offsets. Both are
in `test_no_new_orphaned_definitions`'s register.

### FS-627. A target preview expiring is invisible to the page · S · **new**

`TargetPreviewResponse.expired` is computed and served. Nothing reads it, so a preview whose
window has closed still renders as current — and its membership set no longer reflects the
fleet.

### FS-628. `http_rest.py` is a registered collector with zero tests · M · *carried (FS-605)*

186 lines. It catches `httpx.HTTPError`, then bare `Exception`, and its poll loop wraps the same
call again — so it **cannot crash, restart, or tell supervision anything is wrong**. A poll that
raises every cycle is indistinguishable from one that works.

### FS-629. Supervision gives up after ~50 seconds · S · *carried (FS-606)* · *decision*

`_run_collector` retries with a fixed 5-second delay, capped at 10 restarts, then stops
permanently — that collector is dead for the life of the process.

---

# HARSH — MLOps, correlation-AI

### FS-630. `POST /engines/correlation/integration/analyze` has never returned successfully · S · **do this first** · *carried (FS-608)*

`integration_result` is declared `Dict[str, List[str]]`; the single return path passes
`{"message": "<a string>"}`. Pydantic rejects it **while building the response**, so the
analysis runs, the background task is queued, and the caller gets a 500. There is no input that
makes it succeed and there never has been.

### FS-631. The response-model burn-down is entirely in other lanes · M · *carried (FS-600)*

**52 undeclared routes, none in Hamad's lane:** engines 11, model_monitoring 9,
logistics_correlation 8, analysis_sessions 7, nlp_correlation 6, auth 3,
correlation_integration 3, telemetry 3, kanban 2. An undeclared route is invisible to the
contract gate — this is also the cheapest way to move FS-620.

### FS-632. `components/kanban/` and `components/nlp/` · L · *carried (FS-601/602)*

1,811 lines across 7 kanban components with **zero** test files; 3,735 lines across 10 nlp
components with 2. The nlp directory is the intake surface and the largest untested tree here.

### FS-633. Correlation-AI honesty · S · *carried from 2026-07-26 — its fourth pool*

`CORRELATION_MODEL_ENABLED` is `False` by default, so every deployment shows heuristics styled
as AI output. The engine labels itself `simulated: true` and the AI tab does not display it.

---

# htreinen — RAG

*Your three commits are on `main`. Check what FS-634 leaves before starting the rest — your
chunking and guardrails work may already cover part of it.*

### FS-634. Re-scope the RAG items against what landed · S · **do this first** · **new**

Structure-aware md/csv chunking, ingestion guardrails and a multi-document eval corpus are now
on `main`. The four items below were written before that. **Reproduce each against the merged
tree before starting** — assigning work somebody has already done is the same waste as leaving
it undone.

* **FS-635. Streaming answers** · M — `stream_generate()` exists, no route.
* **FS-636. Async ingestion (202 + status)** · L — a large upload blocks the request.
* **FS-637. The document metadata record** · L — **unblocks the other three**.
* **FS-638. `DELETE /rag/documents/{doc_id}` takes `doc_id: str`** · S — a literal path segment
  reaches the deletion handler, and it is the same handler FS-266 flags for deleting vectors
  with no organisation filter.

---

# Alex — intake & spreadsheet parsing

*All five carried from 2026-07-26 and **none has moved**; last commit 2026-07-22. This lane has
no dependency on the promotion — it can start Monday regardless.*

* **FS-639. Wire `normalize_column_header` into its callers** · S — referenced only by its own
  test, so it normalises nothing. *Done when removing the call fails a test.*
* **FS-640. Make the messy fixture assert something** · S — `tests/load/fixtures/messy_factory_upload.csv`
  is referenced by no test.
* **FS-641. Decide and test header-collision behaviour** · S — `Serial #` and `Serial No.` both
  normalise to `serial_number`; today's behaviour is **unknown**, which means it may be silent
  data loss.
* **FS-642. Extend the messy-header corpus** · M — merged cells, title rows, unit suffixes,
  non-ASCII, Excel date coercion.
* **FS-643. Fold `docs/DATA_FLOW_OVERVIEW.md` into the architecture docs** · M — two
  descriptions of one flow.

---

# Infrastructure — unowned

* **FS-644. Nothing applies either secret-provisioning path** · L · *carried* — neither
  `external-secrets/` nor `sealed-secrets/` is referenced by any kustomization, while
  `strip_placeholder_secrets.py` states the intended failure is a `CreateContainerConfigError`.
  So the intended failure is the only thing that happens.
* **FS-645. PITR does not exist** · L · *carried* — `legacy-patroni/` is applied nowhere; what
  runs is a logical `pg_dump -Fc` with an RPO of up to 24 hours.
* **FS-646. The restore drill has never run against a real dump** · L · *carried* — a backup
  nobody has restored is a backup nobody has.

---

## Notes for redistribution

* **Every lane has work, and every lane's owner is named.** The previous pool dropped a lane
  entirely because it was built from what its author had touched. This one was built by asking
  what is open.
* **Nineteen of these are carried**, and three are on their third or fourth consecutive pool
  (D3, FS-633, and the infrastructure set). That is the number to look at when deciding what
  this team is actually going to finish.
* **Lane discipline holds.** Mechanical fixes are fine from any lane — a `response_model`, a
  type on a path parameter. Product and design decisions are not.
