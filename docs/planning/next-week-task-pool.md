# Next week — task pool

**Week of Monday 2026-08-10.** Written 2026-08-08 for **Harsh as Product Manager**, grouped by
lane so it can be handed out as-is. Every item is independently assignable; reassign freely.

The previous pool (2026-07-26) is archived at
[`task-pool-2026-07-26.md`](task-pool-2026-07-26.md). Every figure below was re-derived from
the repository on 2026-08-08.

> ### 🔴 Corrected 2026-08-08, after review — the first draft of this pool was too SHORT
>
> It claimed *"several entries that pool listed as open have since closed — they are not
> repeated here."* **That was wrong, and it was not checked before it was written.** Auditing
> the old pool item by item found **at least twelve entries still open** that this document had
> silently dropped, and one that had regressed:
>
> | Old # | Claim then | Measured 2026-08-08 |
> |---|---|---|
> | #5–#9 | Alex's five intake items | **all five unchanged** since his last commit, 2026-07-22 |
> | #46 | 190 `USE_MOCK` forks | **249** — worse by 59 |
> | #47 | 0 `useTranslation` call sites | **still 0** |
> | #20 | `get_db` on RLS tables, 24 files | **13** — reduced, not closed |
> | #23 | no organisation-management CRUD | **still none** |
> | #34 | no ERP export definition | **still none** |
> | #35 | no ERP events over WebSocket | **still none** |
> | #42 | generated SDK unadopted | **still unadopted** |
>
> **And an entire lane was missing.** Alex is an active contributor with three commits on this
> branch, and the first draft had no section for him at all — so he would have been handed a
> pool with nothing in it.
>
> The cause is worth more than the correction. The old pools rotted by listing **more** work
> than existed. This one rotted the other way: it was built by asking *"what did I find this
> week?"* rather than *"what is open?"*, so it narrowed to its author's own footprint — and
> Alex's lane, which overlaps nothing I touched, vanished entirely. **A short pool looks like
> progress, which is why this direction is harder to catch.** It is the same shape as the three
> guards a document split silently disabled the same day: a derived list quietly narrowing,
> with nothing comparing it to what it is derived from.
>
> Every item below now carries **its age** — the pool it first appeared in. A repeat with no age
> on it reads as new work and hides how long it has been sitting.

> ### ⚠️ Verify before you start
>
> The last pool was re-audited four days after it was written, and **three of the four items
> picked up had already been partly or wholly done**. That is not a criticism of the pool; it
> is what a written snapshot does while sixty commits a day land against it.
>
> **Spend the first ten minutes of any item reproducing its claim.** If it does not reproduce,
> correct the entry in place with the date and what you found — that is worth more than the
> task was. Three plans in a row rotted by listing more work than existed, every time because
> the next plan was written from the previous pool instead of from the tree.

> ### Who does what
>
> This file is the **inventory**. [`assignments-2026-08-10.md`](assignments-2026-08-10.md) says
> who does what and in what order, derived from the branch's status rather than this file's
> ordering — and it opens with three items that come **before** any ticket here, because
> measuring the branch found nine of Hridyansh's commits on the backup remote only and three of
> htreinen's on an unpushed local branch.

Sizes: **S** under half a day · **M** 1–2 days · **L** 3+ days.

*Regenerate the print-ready PDF (not committed — it would go stale beside this file):*
`python3 tools/docs/md2pdf.py docs/planning/next-week-task-pool.md docs/planning/next-week-task-pool.pdf`

---

## Verified state, so nobody re-derives it

Measured 2026-08-08 on `hamad/converged-pre-main` at `e0c0815f`.

| Fact | Value |
|---|---|
| Backend suite | **3,956 passing**, 102 skipped |
| Edge-agent suite | **351 passing**, 1 skipped |
| Frontend suite | **886 passing** across 112 files; `tsc` clean |
| Frontend coverage | 45.51 / 46.24 / 41.28 / **46.94** against thresholds 44 / 45 / 40 / **46** |
| `response_model` coverage | **419 / 472 routes**; 53 undeclared, ratchet ceiling 53 |
| Contract gate | **402 of 471** measured 2026-08-08 with all three dependencies; floor stays **380** — see FS-593 |
| Alert rules | 51 total, **23 with no promtool test** |
| Migrations | 66; **4 cannot be re-run**, permanently — see FS-578 |
| Swallow surface | `MAX_SWALLOWING` 201 · `MIN_COUNTED` 11 |
| Ratchets at zero | 4 — unset adapter fields, unsignalled caps, phantom fields, unfed types |
| `main` vs this branch | **432 ahead, 7 behind** |
| Lane-failure register | empty |
| This pool | 31 tickets, 5 decisions; **17 carried from 2026-07-26** |

**Four ratchets are at zero.** Worth saying out loud, because a register that reaches zero and
stays on the page becomes a monument rather than an instrument — see D4.

`docs/engineering/open-decisions.md` has **one** entry, added 2026-08-08: the `pre-commit`
question below. It had been empty since 2026-08-05, and an empty decision register is a claim
that nothing is blocked on intent, which is a strong claim to leave unexamined.

---

# Decisions — Harsh, as PM

Each blocks or shapes engineering work below.

### D1. Promote `main`  ·  *carried from 2026-07-26 (#3, #39) — its THIRD pool*

`hamad/converged-pre-main` is **432 commits ahead of `main` and 7 behind**, and the 7 are
content-identical to the fork point — `git diff <merge-base> main` is empty, so nothing has to
come back. Meanwhile every developer is told to branch from `main`, which means branching from
a tree that predates the entire convergence.

This has been true and un-actioned across two pools. It is not an engineering task; it is a
window somebody has to pick.

**Done when:** the promotion has run, or a date is written down.

### D2. The contract gate's ceiling is a policy question  ·  *shapes FS-593*

**45 of the 471 operations cannot pass without a deliberate behaviour change** — 31 + 14,
measured 2026-08-08. Two shapes, both documented in `docs/engineering/api-contract-gate.md`:

* **31 `AcceptedNegativeData`** — Pydantic's lax mode coerces `{"is_enabled": 0}` to `False`
  and returns 201. Strict mode would satisfy the check and **break every client sending
  `1`/`"true"`**.
* **14 `UnsupportedMethodResponse`** — `GET /alarms/acknowledge-all` returns 422 rather than
  405 because the literal path is shadowed by `/alarms/{alarm_id}`. A 405 needs typed path
  converters across many routes.

Neither is a defect. Adopting either is a compatibility decision with a real cost.

**Done when:** the answer is written into the gate document, so the next person to raise the
ratchet knows whether the target is **~424** (leave both policies alone: 471 − 45 − the two
genuine defects) or **469**. Without it, somebody reads the 69-operation gap as 69 tickets and
spends a week on non-bugs. It is two — see FS-593b.

### D3. 1,777 lines of service code that production does not import  ·  *blocks FS-598*

Four modules, imported by **zero** application code:

| Module | Lines | What it is |
|---|---|---|
| `erp_error_handler.py` | 533 | the entire ERP dead-letter surface |
| `erp_security.py` | 483 | credential handling for connectors |
| `device_provisioning.py` | 465 | edge enrolment |
| `schema_registry.py` | 296 | telemetry schema validation |

Each has *tests* naming it, which is how it survived a dead-code sweep — a module with tests
and no callers reads as live to any importer-based check. They are inventoried in
`test_no_new_unreachable_modules.py`.

The decision is per module and it is **wire or delete**, not "leave for later": the DLQ surface
in particular is 533 lines that an operator would reasonably assume is running.

**Done when:** each of the four has an owner and a verdict recorded in the inventory.

### D4. Four ratchets are at zero — retire them or keep them  ·  S

`MAX_UNSET_FIELDS`, `MAX_UNSIGNALLED`, `MAX_UNREAD_PHANTOM_FIELDS` and `MAX_UNFED_FIELDS` are
all zero, and `docs/engineering/open-decisions.md` had no entries for three days before FS-574
added one.

A ratchet at zero should become a plain assertion (`assert not offenders`) and lose its
allowance, or it keeps inviting somebody to nudge it up. **Done when:** each is converted or
deliberately kept, with the reason.

### D5. `pre-commit` is advisory, and compliance is one 972-file commit  ·  *carried from 2026-07-26 (#57)*

The only entry in `docs/engineering/open-decisions.md`, pinned by
`backend/tests/test_the_precommit_decision_is_still_open.py`. Repeated here because a decision
in a register nobody opens is a decision nobody makes.

CI runs the formatting hooks with `continue-on-error: true`, above a comment reading *"Advisory
while the existing tree is brought into compliance."* The tree has not been brought into
compliance, and that sentence now describes a choice rather than a transition. Measured
2026-08-08 on a clean tree: **972 files, +55,068 / −40,118**.

Both answers are defensible. Making it blocking means one announced tree-wide reformat landed
when no branch is open — a 972-file diff conflicts with every branch that exists, and
`git blame` on all 972 then points at that commit instead of at whoever wrote the line. Keeping
it advisory means the comment stops claiming a transition, and the hooks keep the value that
needs no tree-wide change: merge conflicts and secrets.

**It lands in four lanes at once, which is why it is Harsh's call and not a developer's.**

**Done when:** either the reformat is scheduled with a date, or the workflow comment says the
job is advisory by choice and why.

---

# Hamad — platform, contract gate, frontend primitives

### FS-593. The contract floor cannot rise until the broker is guaranteed · M · *not the burn-down it looks like*

**Measured 2026-08-08, the first run with all three dependencies present: 402 of 471, against
a floor of 380.** That is the highest this gate has ever scored, and the floor is staying at
380 — which is the finding, not a failure of nerve.

    Postgres + Redis + a reachable broker    402 / 471
    Postgres + Redis, broker absent          387 / 471   (2026-08-07)

The broker step is `continue-on-error` and **removes its own container** if the advertised
address does not verify, because a half-working broker hangs the app and collects 1 operation
instead of the whole set. That fail-safe is correct. It also means the worst *legitimate* configuration
scores 387, and 387 minus the measured spread of 9 is 378 — below the floor already in force.
**Raising the floor toward 402 would fail every build in which the broker did not come up**,
which is exactly how this job's predecessor became advisory and got killed at six hours.

So the next raise is gated on a CI change, not a code fix.

**Done when:** either the broker is a required step whose failure fails the job — in which
case the floor moves to roughly 390 — or the job's score without a broker is measured
deliberately and the floor is set from *that*. Write down which, in the ratchet's own comments.

### FS-593b. The fixable bucket is 14, and none of it is in this lane · S · *reclassification*

`ServerError` is the only bucket that is entirely defects, and it is down to **14** from 23 at
the FS-307 re-baseline. Classified by reproducing each one against a live app:

| Count | What it actually is |
|---|---|
| 6 | `/admin/query-performance/*` — `pg_stat_statements` needs `shared_preload_libraries`, and Postgres is a service container that takes no command. Documented, environmental. |
| 4 | `/rag/*` — vector store unreachable in this harness; htreinen's lane either way |
| 2 | `/edge/enroll` and `/sso/login/callback` return a **correct 503**. Schemathesis counts any 5xx, so a properly-reported missing dependency is charged to the API. |
| 1 | `POST /fleet/releases` — see FS-609 |
| 1 | `POST /engines/correlation/integration/analyze` — see FS-608 |

**Done when:** nothing. This entry exists so the next person does not read "14 server errors" as
fourteen tickets. It is two.

### FS-594. `components/common/` — 346 lines, 5 components, zero test files · M

Every one is stubbed out of the page tests that mount it (`vi.mock('../components/common', () => ({ ExportButton: () => null }))` in
`pages/OEE.test.tsx:39` and `pages/AssetDetail.test.tsx:35`), so not one is ever rendered by anything. They
report as covered because nothing distinguishes "stubbed" from "exercised".

**Done when:** each renders in at least one test that asserts behaviour, and the page tests
that stub them either stop stubbing or say why in the mock.

### FS-595. `components/ui/` — 12 components, 2 test files · M

`a11y.test.tsx` covers `Button` and `Input`. `Select` was an unlabelled combobox app-wide until
FS-550 and reported **100% line coverage** throughout, because the a11y suite never rendered
it. `Table`, `Modal`, `Badge` and `Tooltip` are in the same position now.

**Done when:** the axe assertion covers every primitive in the directory, driven off a
directory listing rather than a hand-kept list — so a new primitive is covered on the day it
lands.

### FS-596. 23 of 51 alert rules cannot be shown to fire · M

`promtool check rules` proves an expression **parses** and says nothing about whether a series
exists that would make it true. `EdgeAgentBufferHigh` was syntactically perfect and unfirable
for its entire existence. The 23 are **named, not counted**, in
`test_every_alert_rule_is_provably_firable.py`, so the ratchet cannot be satisfied by deleting
a rule.

**Done when:** a batch has promtool tests that drive each expression true **and** a
must-stay-quiet case, and the named set shrinks by that batch.

### FS-615. `USE_MOCK` forks went from 190 to 249 · M · *carried from 2026-07-26 (#46), and it REGRESSED*

The one number in this audit that moved the wrong way. 249 `USE_MOCK` references across
`frontend/src`, up 59 since the last pool. Every fork is a branch the test suite takes and a
user does not, or the reverse — FS-488 closed one instance of the harm (a mode that mocks half
a surface) and the population kept growing underneath it.

**Done when:** the count is ratcheted so it can only fall, whatever is decided about the
existing 249. A number that grows while nobody watches is the argument for the ratchet, not
against it.

### FS-616. i18n has zero `useTranslation` call sites · M · *carried from 2026-07-26 (#47)*

Still exactly zero, unchanged. The i18n scaffolding exists and no component uses it, so the
locale files are a claim the product does not honour.

**Done when:** either one screen is genuinely translated end to end, or the scaffolding is
removed and the README stops implying multi-language support. Half-built is the worst of the
three.

### FS-617. Adopt the generated SDK · M · *carried from 2026-07-26 (#42)*

`generate_sdk.sh` runs and nothing consumes its output — there is no `src/sdk` in the
frontend. So the hand-written API clients and the OpenAPI schema are two descriptions of one
contract, which is the problem the schema was generated to solve.

**Done when:** one client module is generated rather than hand-written, or the generator is
deleted with the reason.

### FS-597. The coverage thresholds have under one point of headroom · S · *carried from 2026-07-26 (#41), and INVERTED*

**The same knob, the opposite problem.** The 2026-07-26 pool listed this because the
thresholds sat 12 points *below* the measured figure and asserted nothing. FS-541/542 widened
the `include` to every component directory and re-baselined; the measured number fell as
10,566 previously-invisible lines came into scope, and the slack went with it.

Measured now: 46.94 lines against a threshold of **46**. That is 0.94 points, and an unrelated
refactor that adds one untested file fails the build.

Two defensible answers: add tests until there is room (FS-594/595 do this), or accept that the
threshold now tracks reality closely and treat a failure as a signal rather than noise. **Done
when:** one is chosen and written into `vitest.config.ts` beside the numbers.

### FS-598. Four live services with production callers and zero tests · M · *distinct from D3*

These **are** imported — which is what separates them from D3:

| Module | Lines | Production importers |
|---|---|---|
| `shop_floor_fanout.py` | 326 | **4** |
| `agent_release_storage.py` | 103 | **4** |
| `insight_activation.py` | 517 | 1 (a mounted router) |
| `inference_client.py` | 137 | 2 |

`insight_activation` is the one to start with: 517 lines behind a mounted router, so it is
reachable over HTTP today.

**Done when:** each has a test that exercises its main path, and the two with four importers
have one asserting behaviour at a caller.

### ~~FS-599. Six e2e skips nobody counts~~ — **measured while writing this, premise wrong** · S

Recorded rather than deleted, because *proven clean* and *never checked* look identical
afterwards, and because the mistake is instructive.

A grep for `test.skip` in `frontend/e2e` returns 6 hits. **Four are
`test.skip(!LIVE, 'needs a live backend; set E2E_LIVE_BACKEND=1')`** — a conditional guard with
a stated reason, which is exactly what this item would have asked for. **The other two are
comments**, describing the FS-386 defect where `test.skip(count === 0)` turned an empty page
into a silent pass. Rule 37 caught me again: prose about a defect gathers around the defect, so
a text search matches the description as readily as the thing.

There are **zero unconditional skips** in the e2e suite, and zero `@pytest.mark.skip` in the
backend. What *is* real: the live-backend suite runs 119 tests in CI and roughly 39 on a laptop
without a backend, and nothing counts the difference at the point of use.

**Left as:** no work. If somebody wants the residual, it is a one-line reporter that prints how
many specs the `!LIVE` guard skipped — worth an hour, not a ticket.

---

# Alex — intake & spreadsheet parsing

*Under Harsh. **This lane was missing from the first draft of this pool** — see the correction
at the top. All five items are carried from 2026-07-26 and **not one has moved**; his last
commit on this branch is `5f2d4244`, 2026-07-22.*

His onboarding landed here: he fixed `normalize_key`, added `normalize_column_header`, added a
messy real-world CSV fixture, and wrote `docs/DATA_FLOW_OVERVIEW.md`. **Two of those three code
additions are still connected to nothing**, seventeen days later — which is the natural next
step and the lesson this codebase keeps relearning.

### FS-610. Wire `normalize_column_header` into its callers · S · *carried from 2026-07-26 (#5)*

Defined at `backend/app/services/shared_key_detector.py:58`. Re-measured 2026-08-08: it is
named in **exactly one place outside its own definition — its own test file**. It normalises
nothing in production. Eight modules consume `shared_key_detector`; the spreadsheet path
(`multi_spreadsheet_correlator`) is the one that ingests headers.

**Done when:** removing the call makes a test fail. A helper with a test and no caller does
nothing, and this repository has a guard for that exact shape
(`test_no_new_orphaned_definitions.py`) — worth pointing at this one.

### FS-611. Make the messy fixture assert something · S · *carried from 2026-07-26 (#6)*

`tests/load/fixtures/messy_factory_upload.csv` — note the path is repo-root, not `backend/`,
which the old entry had slightly wrong. Referenced by **no test**, still. It was built to
represent real-world mess and currently proves nothing.

**Done when:** corrupting a column in the fixture fails a test.

### FS-612. Decide and test header-collision behaviour · S · *carried from 2026-07-26 (#7)*

`Serial #` and `Serial No.` both normalise to `serial_number`. Today's behaviour is **still
unknown**, because nothing asserts it — one column may be silently overwriting another, which
is data loss that looks like success.

**Done when:** the behaviour is chosen deliberately (last-wins, first-wins, or raise), asserted
by a test, with the reasoning in the docstring so nobody re-litigates it.

### FS-613. Extend the messy-header corpus · M · *carried from 2026-07-26 (#8)*

The fixture covers one shape of mess. Real customer spreadsheets bring merged cells, a title
row above the header, trailing total rows, unit suffixes (`Temp (°C)`), duplicate names,
non-ASCII, and Excel coercing values to dates.

**Done when:** each case has a named test saying what real situation it represents, and the
parser either handles it or **fails loudly rather than silently mis-parsing**.

### FS-614. Fold `docs/DATA_FLOW_OVERVIEW.md` into the architecture docs · M · *carried (#9)*

Both files still exist: `docs/DATA_FLOW_OVERVIEW.md` (114 lines, outside `docs/architecture/`)
and `docs/architecture/DATA_FLOW.md`. Two descriptions of one flow will disagree, and nobody
will know which is current — the same problem that put a rotted line-number citation into the
sweeps document this week.

**Done when:** one document describes the flow and the other is **gone**, not left as a stale
copy.

---

# HARSH — MLOps, correlation-AI

### FS-600. The response-model burn-down is now entirely in other lanes · M · *carried from 2026-07-26 (#43)*

**419 of 472 routes declare a `response_model`; 53 do not, and not one of the 53 is in Hamad's
lane.** An undeclared route is a route the contract gate cannot check, so this is also the
cheapest way to move FS-593.

| Router | Undeclared |
|---|---|
| `engines` | 11 |
| `model_monitoring` | 9 |
| `logistics_correlation` | 8 |
| `analysis_sessions` | 7 |
| `nlp_correlation` | 6 |
| `auth` | 4 |
| `correlation_integration` | 3 |
| `telemetry` | 3 |
| `kanban` | 2 |

History and method are in [`hamad-response-model-burndown.md`](hamad-response-model-burndown.md).
The ratchet ceiling is 53, so **any new undeclared route now fails the build** — this is
burn-down, not containment.

**Done when:** a router reaches zero and `MAX_UNDECLARED` drops by that many.

### FS-608. `POST /engines/correlation/integration/analyze` has never returned successfully · S · **do this first**

Found by the contract gate on 2026-08-08 and reproduced against a live app. The handler has
**one** return path, and it cannot be serialised:

```
1 validation error for CorrelationAnalysisResponse
integration_result.message
  Input should be a valid list [type=list_type,
                                input_value='Integration processing in background']
```

`CorrelationAnalysisResponse.integration_result` is declared `Dict[str, List[str]]`
(`correlation_integration.py:52`). The handler returns
`integration_result={"message": "Integration processing in background"}` — a `Dict[str, str]` —
at `correlation_integration.py:150`. Pydantic rejects it while *building the response*, so the
analysis runs, the background task is queued, and the caller gets a **500 every time**.

This is not a generated-input problem. There is no input that makes this endpoint succeed, and
there never has been. Same class as FS-486: a capability that ships and cannot be reached.

**It needs a decision, which is why it is here and not fixed.** Either the annotation is wrong
(the message branch is a plain string) or the message branch is wrong (it should be
`{"message": ["Integration processing in background"]}`, and the field is meant to carry
category → created-ids). The background task suggests the second, but that is a call for
whoever owns the shape.

**Done when:** the endpoint returns 200 for a valid request, and a test asserts it — the gate
will confirm it independently on the next run.

### FS-609. `POST /fleet/releases` raises `PermissionError` instead of reporting unavailable · S · *OTA*

Also from the 2026-08-08 run. The OTA artifact directory defaults to
`/var/lib/omniusgrid/ota`, which does not exist and is not writable outside a container, and
the handler lets the `PermissionError` escape:

```
[Errno 13] Permission denied: '/private/var/lib/omniusgrid'
[Errno  2] No such file or directory: '/private/var/lib/omniusgrid/ota'
```

In a real deployment the path exists, so this is *mostly* environmental — but an endpoint whose
storage is unavailable should answer 503 with a reason, the way `/edge/enroll` and
`/sso/login/callback` already do. Those two also appear in the gate's 5xx list and are
**correct**; this one is an unhandled exception wearing the same clothes.

**Done when:** a missing or unwritable artifact directory produces a 503 naming the path, and
the gate's server-error list drops by one.

### FS-619. Three ERP capabilities that were listed, dropped, and still do not exist · M · *carried from 2026-07-26 (#23, #34, #35)*

Measured 2026-08-08, all three still absent:

* **Organisation-management CRUD** — `organizations.py` has **0** write routes. There is no way
  to create, rename or deactivate a tenant through the API.
* **ERP export definition** — **0** export routes on `erp_integrations.py`. Data goes in and
  cannot be got out in a defined shape.
* **ERP events over WebSocket** — **0** ERP references in the websocket surface, so the
  integrations page polls.

Grouped because they are one question — which ERP surface is actually finished — and because
listing them as three separate tickets is what let all three fall out of the pool at once.

**Done when:** each is either built or explicitly deferred with a reason in this file. A
capability nobody has decided against is not the same as one nobody has built.

### FS-601. `components/kanban/` — 1,811 lines, 7 components, zero test files · L

`KanbanColumn` (252) and `KanbanCard` (239) have no test; `TaskDetailModal` (604),
`KanbanBoard`, `CreateTaskModal` and `KanbanFilters` exist in the page test only as
`() => null` stubs. `stores/kanbanStore.tsx` (367 lines, board loading and every task mutation)
is mocked wholesale at `pages/Kanban.test.tsx`.

**Done when:** the store has direct tests and the two leaf components render in one.

### FS-602. `components/nlp/` — 3,735 lines, 10 components, 2 test files · L

The largest untested component directory in the repository, and it is the intake surface.

**Done when:** the four largest components have a test that asserts behaviour rather than
mounting.

### FS-603. The correlation-AI honesty question is still open · S · *carried from 2026-07-26 (#1) — its THIRD pool*

`CORRELATION_MODEL_ENABLED` is `False` by default and the engine falls back to a heuristic, so
every deployment shows heuristics styled as AI output. The engine now labels its own output
`simulated: true` and the transcript endpoints carry it (FS-479), but the **AI tab does not
display it**.

**Done when:** the answer is written down — label it, hide the tab when the model is off, or
ship the adapter enabled.

---

# htreinen — RAG

Four items, unchanged and unstarted. Each was measured on 2026-08-06 and none has moved.

* **FS-563. Streaming answers** · M — `stream_generate()` exists and no route exposes it.
* **FS-564. Async ingestion (202 + status)** · L — a large upload blocks the request today.
* **FS-565. The document metadata record** · L — **unblocks four other items**; do this first.
* **FS-566. Answer feedback loop** · M.

One more, found by the contract gate and left for this lane deliberately:

### FS-604. `DELETE /api/v1/rag/documents/{doc_id}` reaches its handler with a literal path · S

Thirteen of the fourteen `UnsupportedMethodResponse` operations return 422 because their path
parameter is typed, so the request never reaches the handler. This one takes `doc_id: str`,
accepts the literal `"link"` as a perfectly good id, and **runs the deletion path**. It deletes
nothing today, but it is the same handler FS-266 flags for deleting vectors with no
organisation filter.

**Done when:** the id is typed, or the handler scopes its delete by organisation. Preferably
both.

---

# Hridyansh — OTA, edge agent

### FS-605. `http_rest.py` is a registered collector type with zero tests · M

186 lines, registered at `coordinator.py`, and it catches `httpx.HTTPError` then bare
`Exception` while its poll loop wraps the same call in a second handler. It **cannot crash,
cannot restart, and cannot tell supervision anything is wrong** — a poll that raises every
cycle is indistinguishable from one that works, and the asset just goes quiet. Rule 125.

**Done when:** a test drives one successful poll and one failing poll, and the failing one is
visible to something.

### FS-618. `get_db` on RLS-protected tables — 13 files left · M · *carried from 2026-07-26 (#20)*

Was 24, now **13**. Real progress, and the entry should have said so rather than disappearing.
`get_db` does not bind the tenant GUC, so every policy on the tables those handlers touch is
inert for the duration of the request — `kanban.py` alone still has 6.

**Done when:** the count reaches zero, or the remainder are exempted by name with a reason the
way the other registers in this repository do.

### FS-606. The coordinator's supervision gives up after ~50 seconds · S · *decision*

`_run_collector` retries with a fixed 5-second delay, capped at 10 restarts, then stops
permanently — leaving that collector dead for the life of the process. This is recorded as the
reason for its backoff exemption (FS-580) rather than as a defect, because whether a supervisor
should give up is a policy question for this lane.

**Done when:** the cap is deliberate and documented, or replaced with backoff that does not
terminate.

### FS-607. Synthetic sources are opt-out, not opt-in · S

`collectors/base.py` refuses a synthetic default only when `EDGE_REQUIRE_EXPLICIT_SOURCES=true`,
which is set nowhere except a **commented-out line** in `deploy/install.sh`. Stamped, so not
dishonest — but on by default in every shipped deployment. Rule 124: a commented line documents
an intention and configures nothing.

**Done when:** the default is inverted, or the deployment sets it.

---

# Infrastructure — unowned, needs a cluster or a decision

### FS-514. Nothing applies either secret-provisioning path · L · *carried from 2026-07-26 (#50, #53)*

`secrets/external-secrets/` and `secrets/sealed-secrets/` are referenced by **no kustomization
and no workflow** — confirmed again 2026-08-08. Meanwhile `strip_placeholder_secrets.py` states
the intended failure mode is a `CreateContainerConfigError` if the real secret was never
provisioned. So the intended failure is the *only* thing that happens.

**Done when:** one path is wired into an overlay and the CI manifest job builds it.

### FS-513. PITR does not exist · L · *carried from 2026-07-26 (#51)*

`legacy-patroni/` holds the pgBackRest CronJob, is in no kustomization, and is applied nowhere,
while the root README presents it as live. What runs is a logical `pg_dump -Fc` with an RPO of
up to 24 hours. `test_the_recovery_promise_matches_the_deployment.py` pins the gap so the
README cannot quietly re-inflate the claim.

**Done when:** either an image shipping `pgbackrest` plus an `archive_command` is deployed, or
the README states the real RPO.

### FS-522. The restore drill has never been run against a real dump · L

`test_backup_restore_drill.py` exists. A backup nobody has restored is a backup nobody has.

**Done when:** one drill has run end-to-end and its output is recorded with a date.

---

## Notes for redistribution

* **Lane discipline holds.** `auth.py`, `kanban.py`, `telemetry.py`, `analysis_sessions.py`,
  `nlp_correlation.py`, `model_monitoring.py`, `logistics_correlation.py`, `engines.py` and
  `rag_*.py` belong to the owners above. Mechanical fixes (a `response_model`, a type on a path
  parameter) are fine from any lane; product and design decisions are not.
* **Every item names its evidence.** If a claim does not reproduce, the entry is wrong — say so
  in it, with the date. That is the single habit that stops the next pool inheriting this one's
  mistakes.
* **Nothing here is a guess about severity.** Sizes are effort. Where an item is dangerous
  rather than merely undone, the entry says why in its own words — FS-598's mounted router,
  D3's dead-letter surface, FS-604's unscoped delete.
