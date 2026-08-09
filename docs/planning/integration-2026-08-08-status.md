# Integration status — 2026-08-08

Bringing two developers' stranded work onto `hamad/converged-pre-main`, before promoting that
branch to `main`. Written while the work is in flight so the next person — most likely
Hridyansh — can pick it up from a written state rather than from a diff.

## Preservation — done, and it was the urgent part

| Whose | What | Was | Now |
|---|---|---|---|
| htreinen | `rag-rewrite` — 3 commits, 35 files, +4,433 lines: structure-aware md/csv chunking, ingestion guardrails, eval suite and its multi-format SOP corpus | **no remote at all** | `origin/rag-rewrite` and `backup/rag-rewrite` at `ee19defb` |
| Hridyansh | 9 commits, 23–27 July, the OTA/tenancy work | `backup` mirror only | also `origin/hridyansh/integration-2026-07-27` |

`origin` already had an older, diverged `hridyansh/integration`, so the newer tip went in under
its own name rather than force-overwriting anything.

## The merge — on `hamad/integrate-hridyansh`, both remotes

Not on `converged-pre-main` yet, deliberately: that branch has 23 blocking CI gates and
everything green, and this merge is not green yet.

His branch had bridged onto **`main`**, not onto converged, so there was a real merge base and
a proper three-way merge — **20 conflict hunks across 14 files**. All five features verified
present afterwards by grep and by file:

* signed agent self-update OTA with rollback
* fleet targeting and dynamic rollout cohorts
* maintenance windows and scheduled rollouts
* audited remote agent operations
* tenant user administration and invitations

**The rule applied throughout:** where both sides are additive, keep both; where one is a
strict superset, keep it and say so; **never delete another lane's field to make a merge
quiet.** Three resolutions are worth knowing about:

* **`auth.py`'s `GET /users` is gone.** His `users.router` serves the same path with the same
  wire shape, `get_tenant_db` instead of `get_db`, and invitations beside it. Two handlers
  cannot share one path.
* **Both user routers are mounted** — `/api/v1/users` (FS-221) and `/api/v1/auth/users` (his).
  Which one the product keeps is a design call for his lane, not a merge decision.
* **His heartbeat payload survived whole**, though FS-466 had narrowed it — because his
  `_process_agent_heartbeat` now consumes `collector_status`, so that argument no longer holds.
  The three fields that still have no reader are named in the docstring rather than dropped.

His four migrations collided with converged's 046–049, which landed after he diverged.
Renumbered **064–067** — permitted precisely because they have never been applied anywhere,
which is the distinction the README's "never rename an applied migration" rule turns on. The
full chain applies from empty: 66 migrations.

## Where the suites stand

| Suite | Result |
|---|---|
| Edge agent | **372 passing** (was 351) |
| `tsc` | clean |
| Frontend | **21 failing**, 865 passing — down from 41 |
| Backend | one line was costing **719**; re-running after the fix |

**The 719 were a single unresolved relationship.** His composite `fk_assets_workcell_org`
also pins `organization_id`, so an asset cannot reference another tenant's workcell — a better
constraint than the single-column FK converged already had. Both are wanted, and together they
give SQLAlchemy two foreign-key paths it refuses to guess between. Every fixture that touches
an Asset builds that mapper.

## What is left, and who it needs

### 14 — `AdminPages.test.tsx` against his `Users.tsx` · **needs Hridyansh**

My UsersPage tests now point at his page. They pin behaviours worth keeping:

* a failed write must not read as a success,
* deactivation must be worded as deactivation rather than deletion,
* a capped list must say it was capped.

His page is untested and implements these differently. **They are deliberately left red.**
Deleting them to make the merge green is exactly the trade this repository keeps documenting —
and the tests are the only written record of what the old page guaranteed.

### 7 — guards reporting on merged code · mechanical, any lane

* **6 fleet mutations whose failure reaches nobody** — `useResumeAgentRollout`,
  `useDeactivateFleetSite` and four siblings: no caller reads `isError`, awaits `mutateAsync`,
  or passes `onError`, so a failed request leaves the screen exactly as it was.
* an api client that invents a default the server did not send
* his new pages have no test file
* two ratchets moved

Every one is a real finding about code that has never been through this branch's gates. That is
what the gates are for.

## Then, and only then

1. Land `hamad/integrate-hridyansh` on `hamad/converged-pre-main` once green.
2. Triage htreinen's three commits — a **cherry-pick, not a merge**: `rag-rewrite` has no merge
   base with converged. Do this before anyone starts FS-563–566, which it plausibly overlaps.
3. Promote to `main`. A dry-run merge of converged into main was already run and **is clean** —
   `main`'s tree is byte-identical to the fork point, so the 434-commit gap carries no
   divergent content. The promotion is ready; it is sequenced last on purpose, because a
   748-file merge in front of this integration makes the integration harder, not easier.
