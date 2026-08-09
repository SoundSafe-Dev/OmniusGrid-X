# Running an offline OmniusGrid demo

`backend/scripts/seed_demo_data.py` populates a fresh database so **every page of
the platform shows realistic, correlated data with no live edge agents, cloud
gateway, or external services**. Use it for demos, screenshots, and local UI work.

The single exception is the **Correlation-AI *inference*** — a ready
`AnalysisSession` ("Demo: Spindle failure investigation") is seeded, but producing
new AI answers still requires the Gemma model to be served. Everything else is
static demo data and works fully offline.

## What gets seeded

One demo plant (`OmniusGrid Demo Plant (CHI-01)`), the `dev` admin user, and:

| Area | Data |
|------|------|
| Assets & workcells | 2 workcells, 5 sensor assets (CNC, vibration, audio, camera, conveyor) |
| Telemetry | 14 days of **correlated** signals (a spindle degradation → fault → repair story) |
| Alarms | vibration-high, acoustic-anomaly tied to the degradation window |
| OEE / dashboard / health-index / RUL | **computed** from the telemetry + operations |
| ERP | a fully-synced integration (entities, mappings, sync status, events, correlations) |
| Yard (YMS) | dock doors, carriers, trailers, dwell/detention, appointments |
| Transportation (TMS) | drivers, vehicles, shipments, geofence zones + alerts, maintenance/repairs |
| Kanban | a board with columns + tasks (some tied to the seeded alarms/assets) |
| Operations | production runs feeding OEE |
| Fleet / OTA | an agent release + rollout with targets/events |
| MLOps | model-registry entries |
| Compliance | actionable registries + items, scheduled + completed reports |
| Notifications | subscriptions + a delivery log |
| Error triage | error events + buckets |
| Exports / Historian | export templates, retention policies |

Re-running is **idempotent** — it wipes its own demo rows (fixed IDs / org scope)
and reseeds, so counts stay stable.

## Run it

```bash
cd backend

# 1. point at a database (a fresh Postgres is recommended; the app also runs on SQLite)
export DATABASE_URL="postgresql+asyncpg://<user>:<pass>@localhost:5432/omnius_demo"

# 2. build the schema (production path — the real migration chain)
DATABASE_URL="postgresql://<user>:<pass>@localhost:5432/omnius_demo" python scripts/migrate.py

# 3. seed
python scripts/seed_demo_data.py            # seeds + prints a per-area count summary
python scripts/seed_demo_data.py --verify   # re-checks the seeded data is present
```

Then run the stack against that data and open the UI in **real mode**:

```bash
# backend
DATABASE_URL="postgresql+asyncpg://<user>:<pass>@localhost:5432/omnius_demo" \
  ALLOW_DEV_TOKEN=true uvicorn app.main:app --port 8000

# frontend (separate shell)
cd frontend && VITE_USE_MOCK=false VITE_DEV_MODE=true npm run dev
```

Log in as `dev` / any password.

**The skip-login demo needs BOTH variables, and this page used to name only one.**
They gate different halves and neither works alone:

| | set on | what it does | without it |
|---|---|---|---|
| `ALLOW_DEV_TOKEN=true` | backend | accepts the `dev-token` bearer as an admin | every API call returns 401 |
| `VITE_DEV_MODE=true` | frontend | offers the bypass at all — `Login.tsx` requires `import.meta.env.DEV && VITE_DEV_MODE === 'true'` | typing `dev` falls through to the real login form and returns **401** |

The frontend gate is also why a production bundle cannot enable this: `import.meta.env.DEV`
is false in a build, so the bypass is compiled out regardless of the variable.

`make demo` + `make demo-ui` set both for you, and are the recommended path — the two
commands were documented separately and drifted, so the pair now lives in the Makefile
where `test_demo_mode_instructions_work.py` can check it against what the code requires.

## The seed ages — re-run it if a page looks empty

**`seed_demo_data.py` writes timestamps relative to the moment it runs**, so a database
seeded yesterday is a day out of date and several endpoints legitimately return nothing.
Re-run `make seed-demo` (it is idempotent) before deciding a page is broken.

The sharpest case is **Alarms**. `GET /api/v1/alarms/` defaults to the last 24 hours when no
range is given — documented behaviour — and the seeder places its nine alarms across the
previous four days. Right after seeding, four fall inside the window and the page is
populated. About a day later, none do, and the Alarms page is empty with no error anywhere.
`/yard/dock/appointments` behaves the same way.

Recorded because a full functional sweep on 2026-08-02 flagged both as "200 but empty with
rows in the table" and they looked exactly like tenancy filter bugs. They were not: a fresh
seed returns 4 alarms and 2 appointments. **An empty page on stale demo data is
indistinguishable from a broken filter until you check the seed's age.**

## Notes & known offline gaps

- **OEE availability reads "no signal"** for live-state metrics that come from
  in-memory PackML fed by real agents — expected with no live edge. Historical
  OEE, health-index, and RUL still compute from the seeded telemetry.
- **`aggregation=1hour` telemetry** reads a TimescaleDB continuous aggregate; it
  populates on a real migration-built TimescaleDB, not on a plain `create_all`
  schema. Raw + other aggregations work regardless.
- **query-performance** and **feature-flags** legitimately need `pg_stat_statements`
  and Redis; they return a graceful `503` offline, by design.
- The seeder writes across essentially every table via the ORM, so a clean run is
  also a useful **write-path / schema sanity** check.
