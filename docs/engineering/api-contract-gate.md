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

**327–331 of 451** operations conform (floor: 318). The remaining ~124 are dominated by
**one behaviour**: generated input reaching Postgres unvalidated and surfacing as a 500
where the contract promises a 4xx (`DataError`, `ForeignKeyViolationError`,
`CharacterNotInRepertoireError`). That is per-endpoint validation work spread across every
lane.

| check | count | nature |
|---|---|---|
| `ServerError` | 80 | real: unvalidated input reaching the database |
| `AcceptedNegativeData` | 24 | real: endpoint accepted input its own schema forbids |
| `UnsupportedMethodResponse` | 13 | routing shape — see below |
| `UndefinedContentType` | 4 | xlsx and Prometheus-text responses, undeclared |
| `RejectedPositiveData` | 2 | endpoint refused input its schema permits |
| `UndefinedStatusCode` | 2 | was 49 before the status codes were documented |

### Two categories are policy disagreements, not defects

Worth reading before anyone spends a day "fixing" 37 non-bugs.

**The 24 `AcceptedNegativeData`** are schemathesis mutating a valid request to violate the
schema and expecting a 4xx. Sixteen mutate the body, seven add an unknown query parameter,
one sends a null body. Both underlying behaviours are deliberate:

* `{"is_enabled": 0}` where the schema says boolean returns **201**, because Pydantic's
  default lax mode coerces `0` → `False`. Verified directly: lax accepts it, `strict=True`
  rejects it. Adopting strict mode across the models would satisfy this check and break
  every client currently sending `1`/`"true"`.
* An unknown query parameter is ignored, which is ordinary REST practice and what most
  clients rely on for forward compatibility.

Neither is wrong. They encode a strictness policy this API has not adopted, and adopting it
is a product decision with a compatibility cost — not a defect fix.

**The 13 `UnsupportedMethodResponse`** are a routing shape. `GET /api/v1/alarms/acknowledge-all`
returns **422 rather than 405**, because the literal path is shadowed by
`GET /api/v1/alarms/{alarm_id}` and "acknowledge-all" is parsed as an alarm id. Getting a 405
would mean typed path converters (`{alarm_id:uuid}`) so a non-UUID fails to match at routing
time — a behaviour change across many routes.

### So the realistic ceiling is not 451

Roughly **37 operations cannot pass without a deliberate policy change**, and 2 more are the
undeclared xlsx/Prometheus content types. The genuinely fixable population is the ~80
`ServerError`s: unvalidated input reaching Postgres. Treat ~412 as the target, not 451, and
do not let a future ratchet-raiser mistake the difference for remaining work.

Demanding a green suite would leave two bad options: stay advisory (how this job spent
weeks achieving nothing), or block every build until unrelated work lands. The ratchet is
the third: pin the measured number, fail on a drop, burn the 152 down deliberately. Same
instrument as `--cov-fail-under=54`, and the same rule — **raise it, never lower it.**

### The floor carries a measured margin

Ten runs with no code change between them scored **294, 296, 297, 297, 297, 298, 299, 300,
302, 303**. `derandomize=True` did not remove the spread, and neither did a freshly migrated
database (two controlled fresh-DB runs scored 299 and 297).

The floor is **318**, raised from 290 on 2026-07-31 once a fix cleared the noise: documenting
the status codes the error envelope actually emits took conformance to 327 and 331, against
a pre-fix band of 294–303. That is the standard for moving this number — a gain larger than
the spread, measured twice.

It sits 9 below the observed minimum. Pinned at the best observed score it would fail roughly
half of all builds, and *a gate that cries wolf is a gate somebody disables* — which is
precisely how its predecessor ended up advisory and killed at six hours.

### The residual noise is 14 known operations

Diffing two runs against brand-new databases isolates it. 146 failures are identical; **14
operations flip verdict between runs**, and they are not random:

| operations | why they vary |
|---|---|
| `GET /api/v1/admin/query-performance/{index-usage,missing-indexes,table-bloat,table-performance}` | read live Postgres statistics, which change as the suite itself exercises the database |
| `GET /api/v1/model-monitoring/{data-drift,drift,performance}/history/{model_id}` | time-window queries whose window moves during the run |
| `POST /api/v1/auth/refresh` | token lifetime is time-dependent |
| `POST /api/v1/{data-residency/tag,data-residency/validate,gdpr/processing-records,notifications/test}`, `PUT /api/v1/user/context` | write endpoints whose result depends on what earlier operations in the same run created |

**This is the list to work through before tightening the floor** — raising the number
without addressing them installs exactly the flakiness the margin exists to avoid. The first
seven are the interesting ones: an endpoint whose response shape depends on live statistics
or on the current time cannot be contract-tested reproducibly, and that is worth knowing
independently of this gate.

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
