# The API contract gate

Schemathesis drives all 451 operations in the app's own OpenAPI schema with generated
input and checks the responses against what the schema promises. The generated
TypeScript SDK is built from that same schema, so drift here is a client that is wrong
at runtime.

It runs as the `api-contract` job in `quality-gates.yml`, takes about 8 minutes, and
**blocks** — as a ratchet, not a pass/fail gate.

```bash
cd backend
# what CI runs
pytest tests/test_api_contract.py -q --junitxml=contract-report.xml || true
python scripts/contract_ratchet.py contract-report.xml
```

It needs `RUN_CONTRACT_TESTS=1` (it is opt-in, so the normal suite stays fast) and a
**migrated** database. Schema and role both matter — see below.

---

## It never once completed, and the reason is worth keeping

For weeks this job was `continue-on-error: true` under a comment saying it was ready to
flip "pending one green CI run". That run was unreachable. Measured: **~2.5 minutes per
operation × 451 ≈ 19 hours**, against GitHub's 6-hour limit. Every run was killed, and
`continue-on-error` meant the kill was invisible.

The interesting part is that **nothing was slow**:

| measured in isolation | |
|---|---|
| one HTTP request | 45 ms |
| one `call_and_validate` | 0.1 s |
| building the strategy | 0.14 s |
| drawing an example | 0.0 s |

Every component fast and the whole impossible is the signature of a feedback loop, not a
slow part. There were two, and they compounded:

**1. A new event loop per example.** `from_asgi` drives the app in-process. Each generated
example ran on a fresh event loop, while the app's module-level singletons — the websocket
manager's queue, its Kafka consumer, the tasks `connect()` starts — bound to the *first*
loop that touched them. From the second example onward, every call raised
`RuntimeError: Event loop is closed`.

**2. An error path with no delay.** `_process_message_queue` caught those, logged, and
re-entered the loop immediately. That is safe only while every failure is transient. A
queue bound to a dead loop can *never* succeed, so the loop span at full CPU emitting the
same line forever.

> **The rule, and it is not test-only:** an error path with no delay is a spin, and a
> failure that cannot change is not something to retry. Any `while running` worker will do
> this in production the first time a fault stops being transient. Both properties are now
> pinned by `tests/test_ws_queue_processor_cannot_spin.py`, one test per failure kind.

**The fix is to stop pretending.** The suite now serves the app under uvicorn on a real
port: one long-lived event loop for the app's whole lifetime, the same shape as production,
and the real HTTP stack rather than an in-process shortcut.

## It could not have been green either

Two more faults, either of which alone would have failed every DB-backed operation:

* **No schema.** The job never ran migrations, so the suite ran against an empty database
  and every DB-backed operation 500'd.
* **Wrong role.** It set `POSTGRES_USER=test`, while `004_query_optimization.sql` and others
  `GRANT` to the `omniusgrid` role *by name*. The whole chain rolls back without it, so
  migrations could not have run even if the step had existed.

## What it found immediately

One fix closed **304 of 355 failures**. `_resp()` in `app/core/responses.py` declared
`model` only, so FastAPI defaulted the media type to `application/json` — while every error
is emitted as `application/problem+json` (RFC 9457). The OpenAPI document was wrong for
every 4xx/5xx on every route.

The `$ref` is spelled out explicitly there, because FastAPI attaches the model's schema to
the *default* media type only. Without it, `problem+json` would be declared but schema-less:
the content-type check would pass while validating nothing.

Separately, the gate found that **every 405 lacked `Allow` and every 401 lacked
`WWW-Authenticate`** — both mandatory under RFC 9110, both discarded when the problem+json
envelope rebuilt the response from `exc.headers`. Fixed in `c1e3ef56`.

---

## Why a ratchet

299 of 451 operations conform. The remaining 152 are mostly **one behaviour**: generated
input reaching Postgres unvalidated and surfacing as a 500 where the contract promises a
4xx — **64 `DataError` + 32 `IntegrityError`**. That is per-endpoint validation work spread
across every lane.

Demanding a green suite would leave two bad options: stay advisory (how this job spent
weeks achieving nothing), or block every build until unrelated work lands. The ratchet is
the third: pin the measured number, fail on a drop, burn the 152 down deliberately. Same
instrument as `--cov-fail-under=54`, and the same rule — **raise it, never lower it.**

### The floor carries a measured margin

Four consecutive runs scored **294, 296, 297, 300** with no code change between them —
including two with `derandomize=True` and one against a freshly migrated database, so the
spread is neither hypothesis's seed nor accumulated DB state. A few health endpoints
genuinely report a dependency's timing.

The floor is **290**: below the observed minimum of 294, still catching any structural loss.
Pinned at the best observed score it would fail roughly half of all builds, and *a gate that
cries wolf is a gate somebody disables* — which is precisely how its predecessor ended up
advisory and killed at six hours.

Tightening it means making those endpoints deterministic **first**, not raising the number
and hoping.

### What stops the ratchet being fooled

It reads junit XML and rejects a report whose operation count has collapsed. Otherwise a
crashed or truncated run — which collects almost nothing and therefore fails almost nothing
— would sail past a check that only compares a pass count. Exit codes are verified:
regression → 1, healthy → 0, missing report → 1.

## Settings, and why each is explicit

In `tests/test_api_contract.py`:

| setting | reason |
|---|---|
| `deadline=None` | A per-example wall-clock deadline measures the runner's load, not the API's correctness. At the 200 ms default, real HTTP round trips land either side of the line at random, and each breach costs a re-run plus a shrink. |
| `max_examples=5` | 451 operations cannot afford 100 draws each. Fewer examples find fewer bugs — stated plainly; raise it deliberately if something escapes. |
| `derandomize=True` | A ratchet on a number that moves by itself is a gate that fails for no reason. Trades exploration for a result an engineer can reproduce. |
| `suppress_health_check` | `too_slow` fires on the same wall-clock basis as `deadline`; `filter_too_much` fires on narrow enums, which is a property of the API, not a fault. |
