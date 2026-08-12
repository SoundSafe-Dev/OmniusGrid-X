# Assignments — week of 2026-08-10

Derived from the **status of `hamad/converged-pre-main` at `3bfe8127`**, measured 2026-08-08,
not from the order of the task pool. Ticket numbers refer to
[`next-week-task-pool.md`](next-week-task-pool.md), which stays the inventory; this document
says who does what and in what order.

**The status changed the answer.** Going in, the plan was to hand out tickets. Measuring the
branch first found something that makes most of those tickets premature — see P0.

---

## The branch, in eight lines

| | |
|---|---|
| Divergence from `main` | **434 ahead, 7 behind**; the 7 are content-identical to the fork point, so nothing has to come back |
| Size of that gap | **748 files, +126,472 / −5,883** |
| CI | **23 of 24 jobs blocking**; only `pre-commit` is advisory (D5) |
| Suites | backend **3,972** · frontend **886** · edge **351** · `tsc` clean |
| Contract gate | **402 / 471**, floor 380 — passing, and the floor is capped by a fail-safe (FS-593) |
| Ratchets | four at zero; lane-failure register empty |
| Commits in the last 21 days | Hamad **541** · Hridyansh 9 · htreinen 9 · Alex 6 · Harsh 0 |
| Work **not on this branch** | Hridyansh **9 commits**, backup remote only · htreinen **3 commits**, unpushed |

---

## P0 — nobody starts a ticket until this is done

These are one problem wearing three hats: **the branch is the product, and the team is not on
it.** Every other branch has been stale since 17–22 July, `main` is two months behind, and two
developers responded to that by continuing on the branches they already had.

### P0-a · Land Hridyansh's nine commits · **Hamad + Hridyansh, together** · L

`backup/hridyansh/integration` carries nine commits dated **23–27 July** that are on **no
`origin` branch and not on converged**:

```
8f5efc1e  Add signed agent self-update OTA with rollback
f247683f  Add fleet targeting and dynamic rollout cohorts
344f569b  Add maintenance windows and scheduled rollouts
3e111574  Add audited remote agent operations
51b2b310  Add tenant user administration and invitations
c6dd1245  Align fleet UI hooks with TanStack Query v5
18d24e71  Align weekly migrations with converged main
579e8fb7  Bridge integration history onto converged main
5655101f  Fix weekly feature integration on converged main
```

**Two of those messages say "onto converged main".** He was trying to land this, and it did not
land. It reached the *backup* mirror and stopped.

Converged has **no** file matching `rollout cohort`, `self-update`, `invitation` or
`maintenance_windows` — so this is unabsorbed work, not work the convergence superseded. The
commits touch 101 files and ~21k insertions, but that figure includes pre-convergence lineage:
**the first task is triage, not merge.** Separating genuinely-new from already-rewritten needs
both of us — he knows what he built, I know what the convergence replaced.

*Done when:* every one of the nine is either on `hamad/converged-pre-main` or recorded as
superseded with the commit that replaced it. Not "mostly".

### P0-b · Get `rag-rewrite` off one laptop · **htreinen** · S — **do this today**

htreinen's three most recent commits (20–23 July: structure-aware md/csv chunking, ingestion
guardrails, an eval suite, a compose fix) are on a local branch that exists on **no remote**.
One disk failure and it is gone.

It also has **no merge base** with converged — a disjoint lineage — so this is a cherry-pick,
not a merge, and the three commits are the unit.

*Done when:* the branch is pushed to `origin`, and each of the three is landed or recorded as
superseded. **Until this is done, FS-563–566 must not be started** — "structure-aware chunking,
ingestion guardrails, eval suite" plausibly overlaps them, and assigning work somebody may have
already done is how a pool wastes a week.

### P0-c · Promote `main` · **Harsh decides, Hamad executes** · S — *pool D1, its third pool*

This is the cause of P0-a and P0-b, not a separate item. Everyone is told to branch from `main`;
`main` is 434 commits and 126k insertions behind; so anyone who follows the instruction starts
from a tree that predates the product. Two people did the sensible thing instead and kept their
old branches, and that is what P0-a and P0-b are.

Technically unblocked: the 7 commits `main` has are content-identical to the fork point.

*Done when:* promotion has run, or a dated window is written in the pool. **Sequence it after
P0-a and P0-b** — a 748-file promotion while two branches are still outstanding makes their
integration harder, not easier.

---

## Then, per person

Deliberately small. If P0 takes the week, that **is** the week, and it is worth more than any
ticket below.

### Hamad — platform, contract gate, frontend primitives

1. ~~**P0-a and P0-c**~~ — **done 2026-08-09.** Both developers' stranded work is on `main`.
2. ~~**FS-593**~~ — **done 2026-08-11 (FS-654).** The floor could not rise because one number
   had to cover a healthy run (402) and a broker-less one (387), so it covered the worse. There
   are two floors now — **393 with a broker, 380 without** — and the run decides by *probing*
   the bootstrap address after the suite rather than being told. A flag would have been a
   claim, and the lower floor is the one somebody would want on a red build.
3. ~~**FS-594 / FS-595**~~ — **done 2026-08-11.** `common/`, `ui/` and the whole of
   `components/kanban/` now have tests. The 0.94 points of headroom FS-597 measured is
   **4.79**: lines 45.45 → 50.24 in a day, thresholds raised five times to 48/48/41/50, and
   functions past 40 for the first time. Every one of those lines was a `() => null` stub that
   coverage was already counting as exercised.
4. ~~**FS-596**~~ — **done 2026-08-11.** All 51 rules, not a batch. `UNTESTED` in the
   firability guard went 23 → 15 → 0 and is now closed; a new rule ships with its promtool
   test or it does not ship.

*Not FS-598 or D3 until D3 is decided; wiring or deleting 1,777 lines is not mine to choose.*

**Every item in this lane is now closed.** What follows is what the closures cost, kept
because the next pool gets written from this file and none of it was in the last one.

**Eleven defects found by finishing the four items above** — every one invisible until
something rendered or called the code:

| what | where | consequence |
|---|---|---|
| ten task writes that could not report a failure | `components/kanban/` | class 93 |
| a polled reading that cannot say it stopped arriving | alarm badge, alarms page, kanban metrics | **an alarm feed that never answered rendered as "no active alarms"** |
| a request that never reached the server, reported as a server 500 | `api/client.ts` | class 95 |
| **the gates ran where nobody pushes** | `quality-gates.yml` | no typecheck, lint, flake8 or build on ANY dev branch |
| a dispatch that succeeded and answered 500 | `api/transportation.py` | the shipment WAS dispatched |
| status updates that 422'd on every call | same file, 20 lines below FS-420's fix | "Mark Delivered" had never worked |
| a checkpoint that could not say who inspected it | `api/yard.py` | class 99 |
| a check-in that could not say the seal was broken | same file | five fields dropped |
| a carrier the compliance check could never call compliant | `api/transportation.py` | every API-created carrier reported **invalid** |
| a driver that could never be dispatched | same file | four DOT-regulated HOS fields dropped |
| **$1,333.33 of invented freight cost** | `services/transportation_management.py` | class 100, pinned not fixed |

**Three still open and named, because a register entry is a place for a decision, not a doubt:**

* the `500.0`/`2.50` billing fallbacks — needs a contract that can say *not estimated*;
* `seal_status: str = "intact"` — an unstated seal recorded as a positive claim; the honest
  fix is a migration to a nullable column, not a schema tweak that moves the fabrication down
  a layer;
* nine routes declaring body fields their handlers never read — four in Harsh's lane, and the
  rest split between *lifecycle state wrongly on a Create schema* and *creation input being
  lost*. `test_declared_body_fields_reach_the_service.py` holds them; the register only shrinks.

**Rules 130–147 came out of this**, and two of them are about my own errors: the check I
skipped was the one that found my mistake, and a register entry whose stated reason was wrong
twice, resolved both times by reading rather than deciding.

### Hridyansh — OTA, edge agent

1. **P0-a with me.** Nothing else until his own work is on the branch.
2. **FS-605** · `http_rest.py` — 186 lines, a registered collector type, zero tests, and it
   catches twice over so it cannot crash, restart, or tell supervision anything is wrong.
3. **FS-618** · `get_db` on RLS-protected tables, **13 files left** (was 24) — his lane, and the
   remaining half of a burn-down he already moved.
4. **FS-606 / FS-607** · two small decisions in his own lane: whether supervision should give up
   after ~50 seconds, and whether synthetic sources should stay opt-out.

### htreinen — RAG

1. **P0-b today.** Unpushed work is the only genuinely urgent thing in this document.
2. **FS-565** · the document metadata record — **unblocks four other items**, so it is first
   among the RAG tickets whatever survives the P0-b triage.
3. **FS-604** · `DELETE /rag/documents/{doc_id}` takes `doc_id: str`, so a literal path segment
   reaches the deletion handler. Small, and it is the same handler FS-266 flags for deleting
   vectors with no organisation filter.
4. FS-563/564/566 **only after** P0-b establishes what is already built.

### Alex — intake & spreadsheet parsing

Five items, **all carried from 2026-07-26 and none moved**. Sequenced so each one makes the
next possible:

1. **FS-610** · wire `normalize_column_header` into its callers — it currently normalises
   nothing, and everything below depends on it being on the path.
2. **FS-611** · make the messy fixture assert something.
3. **FS-612** · decide and test header-collision behaviour — `Serial #` and `Serial No.` both
   normalise to `serial_number` and today's behaviour is **unknown**, which means it may be
   silent data loss.
4. **FS-613** · extend the corpus. **FS-614** · fold the duplicate data-flow doc — stretch.

*This lane was missing from the first draft of the pool. It is the one lane with no dependency
on P0, so it can start Monday regardless of how the integration goes.*

### Harsh — as PM

1. **D1** · pick the promotion window (P0-c).
2. **D3** · the four modules with zero production importers — 1,777 lines including the whole
   ERP dead-letter surface. Wire or delete, per module, with an owner.
3. **D5** · `pre-commit`: 972 files. It lands in four lanes at once, which is why it is not a
   developer's call.
4. **D2** · whether the API adopts strict validation and typed path converters — 45 contract
   operations hang on it, and without an answer somebody will spend a week on non-bugs.
5. **FS-603** · correlation-AI honesty, **its third pool**.

*As a developer, Harsh's lane items (FS-600, FS-601, FS-602, FS-608, FS-619) are listed in the
pool. **FS-608 first if any of them:** `POST /engines/correlation/integration/analyze` declares
`Dict[str, List[str]]` and returns a string, so it has 500'd on every call since it was written.*

---

## What this assignment assumes, so it can be corrected

* **That the four other developers are working this week.** Commits in the last 21 days:
  Hridyansh 9, htreinen 9, Alex 6, Harsh 0, me 541. If that ratio holds, P0-a and P0-b will not
  happen without me driving them, and the honest plan is that I do the integration alone and
  the per-person lists slip. Said plainly because a plan that assumes availability it does not
  have is the same fiction as a pool that lists work that does not exist.
* **That P0-a's triage finds real work.** If most of the nine commits turn out superseded, that
  is a good outcome and the week opens up. It is not knowable without doing it.
* **That nothing else is stranded.** Two branches were found by checking where each developer's
  last commit lives. That check is now worth running before every pool — it took one command and
  it found two weeks of two people's work.
