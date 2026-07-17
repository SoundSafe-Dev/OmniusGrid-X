# fixed-sprints ↔ integration convergence plan (task 25)

Both `hamad/fixed-sprints` and `hridyansh/integration` are large, independent,
**unmerged** stacks off `main`. They will eventually land together, and they
overlap on a handful of files. This document is the reconcile plan. **Nothing
here merges to `main`, and this plan lives on `fixed-sprints`.** Its purpose is
to make the eventual convergence mechanical rather than archaeological.

## Status (regenerate before acting)

```
git fetch origin
git merge-tree --write-tree --name-only origin/hridyansh/integration hamad/fixed-sprints
```

- **Migrations: no longer collide.** `fixed-sprints` was renumbered to
  `020_erp_integration_tables`, `021_intake_cross_correlation`,
  `022_notifications`, `023_edge_fleet`; `integration` owns `011–018`. Shared
  `001–010` are identical. Monotonic when both land.
- **Source conflicts: 9 files** (below). Everything else auto-merges.

## Pre-existing blocker discovered during this sprint

`edge-agent/opsgrid_agent/collectors/coordinator.py` and the mature collectors
(`mqtt`, `opcua_collector`, `modbus_collector`, `screen_scraper`, `file_watcher`,
`oee_tracker`) on `fixed-sprints` still use **stale absolute imports**
`from omniusgrid_agent...`. The package is `opsgrid_agent`, so
`import opsgrid_agent.collectors.coordinator` fails at runtime today. This is the
exact rename fixed on `integration` (via Hridyansh's package-renaming work).

**Resolution: take `integration`'s side for the import lines** — do not re-fix
the rename on `fixed-sprints` (redundant). New `fixed-sprints` edge code added
this sprint already uses rename-agnostic **relative** imports and is unaffected.

## File-by-file resolution

| File | Conflict | Resolution |
|------|----------|------------|
| `backend/app/main.py` | both add router imports/includes | **union** — keep both blocks; my `edge_enroll`/`edge_ingest`/`edge_fleet` includes + their `error_tracking`/`erp`/etc. No logic overlap. |
| `backend/app/db/models.py` | both extend shared models | **union** of the added columns/models; neither redefines the other's tables. Verify no duplicate `__tablename__`. |
| `backend/requirements.txt` | both append deps | **union**; dedupe `cryptography` (mine `46.0.6`, theirs may differ — take the higher, retest). |
| `edge-agent/opsgrid_agent/metrics.py` | add/add (both new metric blocks) | **union** of metric definitions; names are disjoint (`edge_quality_*` mine vs theirs). |
| `edge-agent/opsgrid_agent/collectors/coordinator.py` | rename + my quality wiring | **take integration's import lines** (the rename), then re-apply my quality hooks (`register_collector` pipeline build, `_on_collector_message` quality gate, `stop_collector`) on top. |
| `edge-agent/opsgrid_agent/main.py` | both wire startup | **union** — my security/heartbeat wiring + their resilience wiring. |
| `infra/grafana/.../dashboards.yml` | add/add provider list | **union** of dashboard providers. |
| `infra/prometheus/alerts.yml` | both append groups | **union** of alert groups (`opsgrid_edge_fleet` mine vs their groups). |
| `infra/prometheus/prometheus.yml` | both add scrape targets | **union** of scrape jobs. |

Every conflict is **additive/union** — there is no semantic contradiction to
arbitrate, only concatenation plus the one coordinator import swap.

## Recommended sequence

1. Land whichever stack is closer to review-ready first (likely `integration`'s
   PR-split), so the other rebases onto a moving-but-smaller target.
2. For the second stack, resolve the 9 files per the table (union + coordinator
   import swap).
3. Run both suites: `cd edge-agent && pytest` and `cd backend && pytest`.
4. Confirm migrations apply in order `001…010, 011…018, 020…023`.

## Ownership

- Shared hotspots (`config.py`, `requirements.txt`) stayed **append-only** this
  sprint — `config.py` still auto-merges; only `requirements.txt` needs a dedupe.
- ERP is canonical on `fixed-sprints` (full connector suite); `integration-erp`'s
  foundation is superseded and its `019_erp_integration_tables` should be dropped
  from the convergence.
