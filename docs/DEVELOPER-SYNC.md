# Syncing to the promoted `main`

**Read this before your next commit.** `main` has moved by **436 commits and ~126,000
insertions** — the whole convergence, plus two developers' work that had been stranded off the
branch. Anything you have that predates the promotion needs deliberate handling, not a `git
pull`.

---

## Why this is not a routine pull

`main` had not moved since **2026-07-24**. Every developer was told to branch from it, so anyone
who followed the instruction started from a tree that predated the product. Two people sensibly
kept their own branches instead — and that is exactly what nearly got lost:

* **Hridyansh** had nine commits (23–27 July) on the `backup` mirror only, two of them titled
  *"onto converged main"*. He was trying to land them and they reached the mirror and stopped.
* **htreinen** had three commits on a local branch that existed on **no remote at all**.

Both are now on `main`. Both are also still preserved on their own branches — see the table at
the bottom — because a merge is not a backup.

**The lesson is the instruction:** branch from `main`, and push the branch the same day you
create it. A branch that exists only on your machine is one disk failure from gone, and a branch
that exists only on the mirror is invisible to everyone who looks at `origin`.

---

## If you have no local work

```bash
git checkout main
git fetch origin
git reset --hard origin/main
```

Then reinstall — dependency manifests moved:

```bash
cd backend  && python -m venv venv && venv/bin/pip install -r requirements-dev.txt
cd ../frontend && npm ci
cd ../edge-agent && ../backend/venv/bin/pip install -e '.[dev]'
```

## If you have local work

**Do not rebase 400 commits.** Push what you have first, so it exists somewhere other than your
laptop, and only then decide what to carry forward:

```bash
git push origin <your-branch>            # FIRST. Before anything else.
git fetch origin
git log --oneline origin/main..<your-branch>   # what is actually yours
```

Then, for each commit that is genuinely yours and not superseded:

```bash
git checkout -b <your-branch>-on-main origin/main
git cherry-pick <sha>                     # one at a time, running tests between
```

**Expect a lot of it to be superseded.** Of Hridyansh's 150-commit branch, nine commits were
genuinely new; the rest had been rewritten during the convergence. Checking is cheaper than
re-merging: `git log --oneline origin/main -- <the file you changed>` usually answers it.

If you are unsure whether something is superseded, **ask before discarding and ask before
merging.** The expensive mistake in both directions is silent.

---

## What changed that will affect your branch

| Area | What moved |
|---|---|
| **Migrations** | Now at **067**. Four were renumbered 046–049 → 064–067 when they collided with migrations that landed after Hridyansh's branch diverged. If you wrote one, **check your prefix is still free** — `python backend/scripts/check_migrations.py`. |
| **User administration** | Two surfaces are mounted: `/api/v1/users` and `/api/v1/auth/users` (invitations, reactivate). Which one the product keeps is an open decision — do not build new callers against either without asking. |
| **`UsersPage`** | Moved out of `pages/admin/AdminPages.tsx` into `pages/admin/Users.tsx`. |
| **`audit_logs.resource_id`** | Is `VARCHAR(36)`, not UUID — it is polymorphic and holds route names and config keys. **Pass `str(...)`**, or asyncpg rejects the insert. |
| **Fleet targeting** | New: sites, tags, groups, cohorts, target previews, maintenance windows, signed agent self-update. |
| **RAG** | Structure-aware md/csv chunking, ingestion guardrails, and a multi-document eval corpus. |

## The gates you now have to pass

`quality-gates.yml` runs **24 jobs, 23 of them blocking**, on every push to a `hamad/**` branch
and on pull requests. The ones that most often surprise people:

* **`response_model` ratchet** — a route without one is invisible to the contract gate and
  absent from the SDK. The number **only goes down**; a new undeclared route fails the build.
* **Swallow surface** — broad `except` handlers are counted and the total only shrinks. If your
  new one is deliberate, *count* it or narrow another.
* **Schema parity** — the ORM and the migrated schema must agree on every column type.
* **Contract gate** — a ratchet at 380 of 471 operations, not a pass/fail.
* **Frontend coverage** — 44/45/40/46, with under one point of headroom. An untested new file
  can fail the build on its own.

Run them locally before pushing:

```bash
cd backend  && venv/bin/python -m pytest tests/ -q --ignore=tests/rag_eval -p no:randomly
cd frontend && npx tsc --noEmit && npx vitest run
cd edge-agent && ../backend/venv/bin/python -m pytest tests/ -q
```

---

## Branches kept as the record

Nothing was deleted. If you think something was lost in the promotion, it is in one of these:

| Branch | What it is |
|---|---|
| `hamad/converged-pre-main` | The integration branch `main` was promoted from |
| `hamad/integrate-hridyansh` | The merge of his nine commits, with every conflict resolution in one place |
| `hridyansh/integration-2026-07-27` | His branch tip as it was, on `origin` — the older `hridyansh/integration` is a *different, diverged* commit and was not overwritten |
| `rag-rewrite` | htreinen's branch, pushed to both remotes on 2026-08-08 |
| `task-pool-2026-07-26.md` | The previous task pool, archived beside the current one |

Both remotes carry all of it: `origin` (SoundSafe-ai/Omnius-Grid) and `backup`
(SoundSafe-Dev/OmniusGrid-X).
