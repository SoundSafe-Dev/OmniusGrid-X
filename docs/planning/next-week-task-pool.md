# Next week — task pool

**Week of Monday 2026-08-10**, re-derived from `main` at `d233389a` on 2026-08-09 — after the
promotion, not before it. For **Harsh as Product Manager**, grouped by lane.

Every figure was measured again for this document rather than carried across from
[`task-pool-2026-08-08.md`](task-pool-2026-08-08.md), and **re-measuring changed three of
them**, one by a factor of four. That is the reason to re-derive rather than edit.

> ### ⚠️ Before you start
>
> **Read [`docs/DEVELOPER-SYNC.md`](../DEVELOPER-SYNC.md).** `main` moved 595 commits on
> 2026-08-09. If you have local work, **push it before you pull** — two of the three branches
> in last week's integration existed in exactly one place, and one of them was a laptop.
>
> Then **spend ten minutes reproducing your item's claim.** One pool listed more work than
> existed. The next listed less, and dropped a whole lane. This one corrected a 1,777-line
> figure to 8,101. All three failures were silent.

Sizes: **S** under half a day · **M** 1–2 days · **L** 3+ days. Carried items name the pool they
first appeared in — a repeat with no age on it reads as new work.

---

## What re-measuring corrected

| Claim in the last pool | Measured on `main` |
|---|---|
| "1,777 lines of service code production does not import" | **6,955 lines across 16 modules** — the register is four times the four I named. *(An intermediate figure of 8,101/19 was published for an hour and was also wrong: the count had swept in the guard's positive-control list, which names modules asserted to be REACHABLE. Corrected by reading the register variable instead of grepping the file.)* |
| `feature_extraction.py` has a production importer | **Zero.** It is named only in the *comments* of two other modules |
| Frontend coverage "has under one point of headroom" | **The thresholds were breached and no gate was reading them** — see FS-650 |

---

## Verified state of `main`

| Fact | Value |
|---|---|
| Promoted | **2026-08-09**, `d233389a` · 1,062 commits |
| Backend suite | **4,112 passing**, 103 skipped |
| Frontend suite | **894 passing** across 115 files; `tsc` clean |
| Edge-agent suite | **372 passing**, 1 skipped |
| CI | `quality-gates.yml`: **23 of 24 jobs blocking**; only `pre-commit` advisory |
| Frontend coverage | 44.14 / 44.65 / 37.90 / **45.45** — thresholds now set to that floor **and enforced** |
| `response_model` | **468 / 520 routes**; 52 undeclared, ratchet at 52 |
| Contract gate | floor **380**; 402/471 measured with all dependencies present |
| Alert rules | 51; **23 with no promtool test** |
| Migrations | **70**; 4 permanently not re-runnable |
| Dead modules | **16 recorded, 6,955 lines** |
| Orphaned definitions | **52 recorded** — 30 in `services/`, 16 in `erp_connectors/` |
| Stranded work | **none** |

---

# Decisions — Harsh, as PM

### D1. 6,955 lines the product does not import · L · *corrected upward from 1,777*

Sixteen modules, in `test_no_new_unreachable_modules.py`'s `UNREACHABLE` register:

| Module | Lines |
|---|---|
| `erp_connectors/dynamics_data_extraction.py` | 737 |
| `erp_connectors/sap_data_extraction.py` | 664 |
| `erp_connectors/oracle_data_extraction.py` | 575 |
| `services/erp_error_handler.py` | 533 — the entire ERP dead-letter surface |
| `erp_connectors/sap_webhook_integration.py` | 532 |
| `services/erp_security.py` | 483 |
| `erp_middleware/rabbitmq_integration.py` | 467 |
| `services/device_provisioning.py` | 465 |
| `erp_middleware/azure_service_bus_integration.py` | 420 |
| `erp_middleware/kafka_connect_integration.py` | 415 |
| `erp_middleware/boomi_integration.py` | 394 |
| `erp_middleware/mulesoft_integration.py` | 301 |
| `services/schema_registry.py` | 296 |
| `services/feature_extraction.py` | 293 |
| `workers/export_delivery.py` | 234 |
| `core/secrets.py` | 146 |

**It is one question, not sixteen.** Five `erp_middleware/*` integrations (1,997 lines) are five
transports for one job, and none is wired; three `*_data_extraction` modules (1,976 lines) are
superseded by the store-raw-and-transform-at-analysis-time path this product actually uses.
**Answering "which ERP transport does this product support" retires roughly 4,000 of the 6,955.**

The two worth separate attention are `core/secrets.py` (146 lines — a secrets helper nothing
calls, next to a deployment where nothing applies either secret-provisioning path, FS-675) and
`workers/export_delivery.py` (234 — while `/admin/export-deliveries` serves attempt history).

**Done when:** the ERP transport question is answered once, and the remaining four have owners.

### D2. Two user-administration surfaces are mounted · M · *new with the merge*

`/api/v1/users` and `/api/v1/auth/users`. Keeping both has already cost four **duplicate
operationIds** the generated SDK cannot represent, worked around by tagging one router
separately. The invitation surface is the fuller one and is tenant-scoped through
`get_tenant_db`.

**Done when:** one is the product's user API. Two surfaces for one noun is how a client library
gets written twice.

### D3. `pre-commit` is advisory · M · *carried from 2026-07-26 — its fourth pool*

The only job of 24 that does not block. Blocking it reformats **972 files**
(+55,068 / −40,118) across every lane.

### D4. The contract gate's ceiling · M · *carried from 2026-08-08*

**45 of 471 operations cannot pass without a behaviour change** — 31 where Pydantic's lax mode
coerces, 14 where a literal path is shadowed by a `{param}` route. Adopting either is a
compatibility decision.

**Done when:** the target is in the gate document, so nobody reads the 69-operation gap as 69
tickets. It is two.

---

# Hamad — platform, contract gate, frontend primitives

### FS-650. The coverage ratchet was enforced by nothing, and had already gone false · **done 2026-08-09**, recorded here because it is the finding

`ci-cd.yml` runs `npx vitest run`; `quality-gates.yml` ran `npm run test`. **Both are
`vitest run` without `--coverage`**, so the thresholds in `vitest.config.ts` were read by no
job in either workflow.

They had already been breached. The merge added ~700 lines of untested pages and lines fell to
**45.45 against a threshold of 46** — with nothing reporting it, because nothing was looking.
Exactly the "number in a config file" that config's own comment warns about.

Fixed by setting the thresholds to the measured floor **and wiring `npm run coverage` into the
blocking job in the same change**. The numbers went down; the enforcement went up. The way back
up is FS-651 and FS-652, not another edit to the config.

### FS-652. `components/common/` and the dialog primitives · ~~M~~ **done 2026-08-11**

Five components that no test had ever rendered — each stubbed as `() => null` in every page
test that mounts them — plus `DialogProvider`, 181 lines that became load-bearing when the
admin Users page moved off `window.confirm`. **Lines 45.45 → 46.40** and the thresholds are
back above where the merge pushed them under.

### FS-651. `components/kanban/` — 1,811 lines, 7 components, **zero** test files · L · *carried (FS-632)*

The largest untested component tree, and the one that pulls coverage down hardest.

### FS-652b. The remaining `ui/` primitives · S · *what FS-652 left*

`Card`, `ChartContainer`, `Skeleton`, `Tooltip` and `Wordmark` still have no test. Small, and
the a11y suite already covers the six that carry semantics.

### FS-653. 23 of 51 alert rules cannot be shown to fire · M · *carried (FS-621)*

`promtool check rules` proves an expression parses and nothing about whether a series exists to
make it true. Named, not counted — the ratchet cannot be satisfied by deleting a rule.

### FS-654. The contract floor cannot rise until the broker is guaranteed · M · *carried (FS-620)*

402/471 with all dependencies; the floor stays at 380 because the broker step is
`continue-on-error` and removes its own container when it cannot verify its address. **The next
raise is a CI change, not a code fix.**

### FS-655. Four live services with production callers and no tests · M · **two done, two left**

`insight_activation.py` and `shop_floor_fanout.py` now have tests — and the second one **found
a defect**: `all([])` is True, so a shop-floor event that reached no target at all reported
`fully_posted: true`. The operator is told the work went through when it went nowhere.

**Left:** `inference_client.py` (137 lines, 2 importers) and `agent_release_storage.py`
(165, 4 importers).

---

# Hridyansh — OTA, edge agent

*Your nine commits are on `main`. The first three items are what integrating them surfaced.*

### FS-656. The fleet resources can be edited by the API and not by the product · M

`PATCH /api/v1/fleet/{sites,tags,groups,cohorts}/{id}` are live and carry response models. The
page assigns workcells and updates group *members* — it cannot edit a site, tag, group or cohort
itself. Six hooks are written and unconsumed: `useUpdateFleetSite`, `useUpdateFleetTag`,
`useUpdateFleetGroup`, `useUpdateFleetCohort`, `useFleetCohort`, `useFleetTargetPreview`.

**Done when:** the page can edit what the API can, and those entries leave the dead-export
register.

### FS-657. A target preview expiring is invisible · S

`TargetPreviewResponse.expired` is computed and served; **nothing reads it**. A preview whose
window has closed renders as current, and its membership set no longer reflects the fleet.

### FS-658. Two helpers that never run · S

`fleet_targeting._membership_exists` — a bulk pre-check the bulk route bypasses by validating per
row; wiring it replaces four round trips with one. `maintenance_windows.local_date_for_weekday` —
the landed half of a DST fix, while the scheduler still works in fixed UTC offsets.

### FS-659. `http_rest.py` is a registered collector with zero tests · M · *carried (FS-628)*

186 lines that catch `httpx.HTTPError`, then bare `Exception`, inside a poll loop that wraps the
same call again. It **cannot crash, restart, or tell supervision anything is wrong** — a poll
that raises every cycle is indistinguishable from one that works.

### FS-660. Supervision gives up after ~50 seconds · S · *carried* · *decision*

Fixed 5-second retry, capped at 10 restarts, then stops permanently. That collector is dead for
the life of the process.

---

# HARSH — MLOps, correlation-AI

### FS-661. `POST /engines/correlation/integration/analyze` has never returned successfully · S · **first** · *carried (FS-630)*

`integration_result` is declared `Dict[str, List[str]]`; the single return path passes a string.
Pydantic rejects it **while building the response** — the analysis runs, the background task is
queued, and the caller gets a 500. There is no input that makes it succeed.

### FS-662. 52 undeclared routes, none in Hamad's lane · M · *carried (FS-631)*

engines 11 · model_monitoring 9 · logistics_correlation 8 · analysis_sessions 7 ·
nlp_correlation 6 · auth 3 · correlation_integration 3 · telemetry 3 · kanban 2. An undeclared
route is invisible to the contract gate, so this is also the cheapest way to move FS-654.

### FS-663. `components/nlp/` — 3,735 lines, 10 components, 2 test files · L · *carried*

The intake surface, and the second-largest untested tree.

### FS-664. Correlation-AI honesty · S · *carried from 2026-07-26 — its fourth pool*

`CORRELATION_MODEL_ENABLED` is `False` by default, so every deployment shows heuristics styled as
AI output. The engine labels itself `simulated: true`; the AI tab does not display it.

---

# htreinen — RAG

### FS-665. Re-scope the RAG items against what landed · S · **first**

Your structure-aware chunking, ingestion guardrails and multi-document eval corpus are on `main`.
The four below were written before that. **Reproduce each against the merged tree before
starting** — assigning work somebody has already done is the same waste as leaving it undone.

* **FS-666. Streaming answers** · M — `stream_generate()` exists, no route.
* **FS-667. Async ingestion (202 + status)** · L — a large upload blocks the request.
* **FS-668. The document metadata record** · L — **unblocks the other three**.
* **FS-669. `DELETE /rag/documents/{doc_id}` takes `doc_id: str`** · S — a literal path segment
  reaches the deletion handler, and it is the handler FS-266 flags for deleting vectors with no
  organisation filter.

---

# Alex — intake & spreadsheet parsing

*All five carried from 2026-07-26; **none has moved**, re-confirmed on `main`. Last commit
2026-07-22. No dependency on the promotion — this lane can start Monday.*

* **FS-670. Wire `normalize_column_header` into its callers** · S — named in exactly two files:
  its own module and its own test. It normalises nothing. *Done when removing the call fails a
  test.*
* **FS-671. Make the messy fixture assert something** · S — `tests/load/fixtures/messy_factory_upload.csv`
  is referenced by **zero** tests.
* **FS-672. Decide and test header-collision behaviour** · S — `Serial #` and `Serial No.` both
  normalise to `serial_number`. Today's behaviour is **unknown**, which means it may be silent
  data loss.
* **FS-673. Extend the messy-header corpus** · M — merged cells, title rows, unit suffixes,
  non-ASCII, Excel date coercion.
* **FS-674. Fold `docs/DATA_FLOW_OVERVIEW.md` into the architecture docs** · M — both files still
  exist.

---

# Infrastructure — unowned

* **FS-675. Nothing applies either secret-provisioning path** · L · *carried* — neither
  `external-secrets/` nor `sealed-secrets/` is referenced by any kustomization, while
  `strip_placeholder_secrets.py` states the intended failure is a `CreateContainerConfigError`.
  So the intended failure is the only thing that happens.
* **FS-676. PITR does not exist** · L · *carried* — `legacy-patroni/` is applied nowhere; what
  runs is a logical `pg_dump -Fc` with an RPO of up to 24 hours.
* **FS-677. The restore drill has never run against a real dump** · L · *carried* — a backup
  nobody has restored is a backup nobody has.

---

## Notes for redistribution

* **The lead item is FS-650 and it is already done**, listed because the finding matters more
  than the fix: a ratchet this repository built, documented and cited was enforced by no job in
  either workflow, and had already gone false without a sound. Worth asking of every other
  number in a config file here.
* **Nineteen items are carried**, and four are on their fourth consecutive pool (D3, FS-664, and
  the infrastructure set). That number is the honest input to what this team will finish.
* **Lane discipline holds.** Mechanical fixes are fine from any lane — a `response_model`, a
  bound on a path parameter. Product and design decisions are not.
