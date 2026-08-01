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

### The most serious thing it found: the audit trail had never recorded a row

Four `UndefinedFunctionError` 500s turned out to be `function digest(bytea, unknown) does
not exist`. `009_audit_logs.sql` triggers on every insert into `audit_logs` and calls
`calculate_audit_hash()`, whose body is `encode(digest(...), 'hex')` — **pgcrypto**. No
migration ever created the extension.

So the trigger raised on every insert, and `app/services/audit.py` catches it deliberately
("never fail the audited operation"), logs `audit_log_write_failed`, and lets the request
through. Every audited action succeeded; every audit row was rejected. Verified on a freshly
migrated database: a manual `INSERT` failed and `SELECT count(*)` returned **0**.

**It survived because the test harness was compensating for the missing migration.**
`tests/conftest.py:91` runs `CREATE EXTENSION IF NOT EXISTS pgcrypto` when building a test
container, so the real-DB suite exercised a working audit trail while a real deployment had
none. The tests were not wrong about the code — they were wrong about the *database*.

Fixed by migration `059`, which also probes `digest()` after creating the extension and
raises if it is still unusable: a failed migration is a better outcome than an audit trail
that silently discards rows. `test_schema_extensions_come_from_migrations.py` closes the
class — any extension created by `conftest` and by no migration now fails the build.

> **Note the length of the chain.** A gate that could not finish, made to finish; which then
> could not explain its own failures, made to explain them; and only then did a documented
> security feature turn out never to have worked. Each fix was a prerequisite for seeing the
> next problem — which is the argument for repairing a broken gate rather than routing
> around it.

---

## Why a ratchet

**368–370 of 452** operations conform (floor: 360). The remaining ~82 are dominated by
**one behaviour**: generated input reaching Postgres unvalidated and surfacing as a 500
where the contract promises a 4xx (`DataError`, `ForeignKeyViolationError`,
`CharacterNotInRepertoireError`). That is per-endpoint validation work spread across every
lane.

| check | count | nature |
|---|---|---|
| `ServerError` | 51 | real: unvalidated input reaching the database (was 84; typing 28 path params closed most of it) |
| `AcceptedNegativeData` | 24 | real: endpoint accepted input its own schema forbids |
| `UnsupportedMethodResponse` | 13 | routing shape — see below |
| `RejectedPositiveData` | 2 | endpoint refused input its schema permits |
| `UndefinedStatusCode` | 2 | was 49 before the status codes were documented |
| `UndefinedContentType` | 0 | was 307; the problem+json media type, then nine export/metrics routes |

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

**Re-audited 2026-07-31 and the characterisation holds**, which is worth recording because
"proven clean" and "never checked" look identical afterwards. The count had moved 24 → 27, so
the label was re-derived rather than trusted. Sampling the live failures shows the same two
shapes and no third:

    ?skip=0&x-schemathesis-unknown-property=42        -> ignored, as most clients rely on
    {"channel": "webhook", "enabled": 0}              -> pydantic lax mode coerces 0 to False

Of the 27, **25 are the same operations that were failing before this session began** — the
`skip`/`offset` endpoints among them were already here in run 1, so bounding those parameters
(above) neither caused nor cured this bucket. The other **2 are `POST /user/goals` and
`POST /twin/optimize`, which arrived here by being FIXED**: an endpoint that 500s never
reaches the negative-data check at all. Diffed operation-by-operation rather than inferred
from the totals.

**The 14 `UnsupportedMethodResponse`** are a routing shape. `GET /api/v1/alarms/acknowledge-all`
returns **422 rather than 405**, because the literal path is shadowed by
`GET /api/v1/alarms/{alarm_id}` and "acknowledge-all" is parsed as an alarm id. Getting a 405
would mean typed path converters (`{alarm_id:uuid}`) so a non-UUID fails to match at routing
time — a behaviour change across many routes.

**Audited 2026-07-31, and the claim needed one correction.** All 14 really are the shadowing
shape — checked mechanically, by resolving each probed method against the route table rather
than by reading the one example above. But **13 return 422 and one returns 500**, and the
difference says something the "not a defect" label would otherwise hide:

> The 422 is *evidence the path parameter is typed*. `revoke_api_key(key_id: UUID)` rejects
> the literal `"generate"` during validation, so the request **never reaches the handler**.
> `delete_document(doc_id: str)` accepts `"link"` as a perfectly good string, so
> `DELETE /api/v1/rag/documents/link` **does reach the deletion handler** and runs its path.

In this harness that surfaces as a 500 only because the vector store is unreachable
(`[Errno 8] nodename nor servname provided`), which is environmental like the 503s above. In
an environment where Qdrant resolves, the request would execute the delete path with
`doc_id="link"`. It deletes nothing, since no document has that id — but the operation is not
"rejected at routing" the way the other 13 are, and it is the same handler **FS-266** flags
for deleting vectors with no organisation filter. Left for that item's owner (`rag.py` is
another dev's lane); recorded here so the category label does not invite dismissing it.

### Known limitation: this gate runs with RLS inert

The contract job connects as the database superuser, and **a superuser bypasses row-level
security even where `FORCE ROW LEVEL SECURITY` is set**. So every tenant-isolation policy
in the schema is switched off for the duration of this suite.

That matters twice over. It means the gate cannot catch a contract failure that only
appears under RLS — and it means results from it must not be read as statements about
tenant isolation. Doing exactly that produced a false alarm during this work: a dock-door
create with someone else's `organization_id` in the body returned **200 and wrote the
row**, which looks like a cross-tenant write and is not one. The policy was present,
forced, and correct; the connection was simply exempt.

`tests/conftest.py:139` gets this right for the real-DB suite — it creates a
`NOSUPERUSER NOBYPASSRLS` role explicitly because "superusers bypass RLS even with
FORCE", so the isolation tests are sound. **This gate does not do the same yet.**

Two things follow, and the second is not answerable from this repository:

1. Give the contract job a restricted role, the way `conftest` does. Expect conformance
   to *drop* when it lands — endpoints that currently sail through will start meeting the
   policies — so it needs a deliberate re-baseline, which is a different act from
   lowering the floor to make a build pass and must be recorded as such.
2. **Check which role production connects as.** `DATABASE_URL` comes from the
   `database-credentials` secret, which is not in the repo, so the answer is
   operational. If that role is the cluster owner or otherwise carries `BYPASSRLS`, then
   every RLS policy in the schema is decorative in production too, and the tenant model
   rests on application-level scoping alone. Worth confirming rather than assuming — the
   check is one query: `SELECT rolsuper, rolbypassrls FROM pg_roles WHERE rolname =
   current_user;`

### So the realistic ceiling is not 451

Roughly **37 operations cannot pass without a deliberate policy change**, and 2 more are the
undeclared xlsx/Prometheus content types. The genuinely fixable population is the remaining
`ServerError`s: unvalidated input reaching Postgres. Treat ~412 as the target, not 451, and
do not let a future ratchet-raiser mistake the difference for remaining work.

Demanding a green suite would leave two bad options: stay advisory (how this job spent
weeks achieving nothing), or block every build until unrelated work lands. The ratchet is
the third: pin the measured number, fail on a drop, burn the rest down deliberately. Same
instrument as `--cov-fail-under=54`, and the same rule — **raise it, never lower it.**

### The floor carries a measured margin

Ten runs with no code change between them scored **294, 296, 297, 297, 297, 298, 299, 300,
302, 303**. `derandomize=True` did not remove the spread, and neither did a freshly migrated
database (two controlled fresh-DB runs scored 299 and 297).

The floor is **360**, raised from 290 in four steps on 2026-07-31, each time only after a fix
cleared the noise — the standard for moving this number is a gain larger than the spread,
measured twice:

| change | runs | floor |
|---|---|---|
| (baseline) | 294–303 | 290 |
| status codes the envelope emits declared | 327, 331 | 318 |
| 23 path params typed `UUID` not `str` | 348, 348 | 339 |
| nine export/metrics content types + 5 more UUID params | 360, 359 | 350 |
| 16 offset params bounded, `upcoming` bounded, 2 UUID path guards | 369, 370 | 360 |

The UUID row's two runs were **identical** (348, 348), which is a result in itself: several
of the 14 flapping operations were flapping because malformed ids left different rows behind
on different runs. Fixing the type removed variance as well as 500s. The margin is kept
anyway — two identical runs are not yet evidence the spread is gone, and the row below them
scored 360 and 359, so it is not.

It sits 8 below the observed minimum of 368 (four runs of the same tree spanned 368-370; see below). Pinned at the best observed score it would fail roughly
half of all builds, and *a gate that cries wolf is a gate somebody disables* — which is
precisely how its predecessor ended up advisory and killed at six hours.

### One endpoint failed; thirteen were equally broken (FS-259)

The raise to 360 is worth reading as a method, not a number, because the obvious version of
it would have been a raise by luck.

Schemathesis reported exactly one unbounded-offset failure:
`GET /api/v1/transportation/vehicles?skip=595044086785296213088411844608`. `OFFSET :skip`
binds to a Postgres **bigint**, so a value above 2**63-1 is not a large offset — it is one
asyncpg cannot encode, and the request 500s where the schema promises a 4xx.

`skip: int = Query(0, ge=0)` was declared **thirteen times**, identically, across the API.
The other twelve were equally broken and equally invisible: schemathesis draws five examples
per operation, and this is the only endpoint it happened to draw a large enough integer for.
**Fixing the one that failed would have raised the floor without fixing the defect** — the
next release would have "regressed" the moment a different draw landed.

So the bound is shared (`MAX_OFFSET` in `app/core/pagination.py`), applied to all sixteen
offset parameters, and `tests/test_generated_input_cannot_five_hundred.py` fails if a
fourteenth lands unbounded. Three of the sixteen were found by that sweep and not by grep,
because `historian`, `rul` and `error_tracking` spell the parameter `offset` rather than
`skip`.

`MAX_OFFSET` is deliberately the bigint ceiling rather than a smaller "sensible" number:
at 2**63-1 **no request that works today starts failing**, and the only behaviour that
changes is the 500 becoming the 422 the schema already documented.

Two smaller ones came from the same run, both the same shape — a declared type the code
cannot actually accept:

* `upcoming` on `/maintenance/schedules` is added to `now`, so `upcoming=10508090` is a date
  past year 9999 and `timedelta` raises `OverflowError` before any query runs.
* `PATCH /maintenance/repair-orders/{id}` was the only handler in `fleet_logistics.py` that
  did not call the `_uuid_or_404` guard its siblings all use, and
  `GET /fleet/safety/drivers/{id}` compared a free-form `str` to a UUID column. Both answered
  500 where a malformed id is a 404.

**What the four runs measured.** Pre-fix 363 and 367 (spread 4); post-fix 369 and 370
(spread 1). The ranges are disjoint, and the gain over the pre-fix minimum is 6 — larger
than the pre-fix spread, which is this document's standard. All of the movement is in
`ServerError` (47/43 → 41/40); `AcceptedNegativeData`, `UnsupportedMethodResponse`,
`RejectedPositiveData` and `UndefinedStatusCode` are **identical across all four runs**.
That is what rules out a lucky draw: noise would have moved the other checks too.

### Seven in-lane 500s remain, with the input that triggers each

Recorded so the next raiser does not re-derive them. All are the same class — unvalidated
input reaching the database — and all are reproducible from the run artefacts:

| operation | input that 500s it |
|---|---|
| ~~`POST /api/v1/commands/submit`~~ | `{"asset_id": ""}` reached a UUID column. **Fixed** — the body field is typed `UUID`, so it is the 422 the schema promised. |
| ~~`POST /api/v1/user/goals`~~ | `{"title": ""}`. **Fixed, and the input was irrelevant** — see below. |
| `POST /api/v1/fleet/releases` | `{"config_bundle": "0", ...}`. **Not an application defect**: `OTA_SIGNING_PRIVATE_KEY_PATH` is unset, so `sign_bundle` cannot load a key. Environmental, like the 503s, and OTA is another dev's lane. |
| ~~`POST /api/v1/transportation/load-plans`~~ | **Fixed.** `load_plans.planned_by` is `Column(String(36))`, not a `UUIDColumn`, so a UUID object was bound to a VARCHAR and asyncpg raised `expected str, got UUID`. |
| ~~`POST /api/v1/twin/optimize`~~ | **Fixed by the handler below** — its three `model_validator`s all raise `ValueError`. |
| ~~`POST /api/v1/bulk/assets/import`~~ | **Fixed.** `parse_asset_csv` converted a bad *encoding* into `BulkOperationError` (→ 400) but let `csv.Error` through, so an oversized field or a bare CR escaped as a 500 — against its own docstring's contract. |
| ~~`PUT /api/v1/data-retention/policies/{metric_name}`~~ | **Fixed by the handler below.** Not the endpoint at all. |

Three more (`/api/v1/logistics/logistics/*`) are in `logistics_correlation.py`, which is
another dev's lane.

### The find that justified the whole exercise: a feature that had never worked

`POST /api/v1/user/goals` was in the list above because it 500'd on `{"title": ""}`. It
500'd on **everything**, and always had:

```python
"id": str(UUID()),      # TypeError: one of the hex, bytes, bytes_le, fields, or int
                        #            arguments must be given
```

`uuid.UUID` has no zero-argument form. The endpoint could not create a goal for any input,
ever, since it was written; `userContext.ts:69` calls it from the UI; and because nothing
could be created, the PUT and DELETE beside it could only ever answer 404. **The whole
goals feature was dead behind an endpoint that looked wired.** It was the only `UUID()` in
the codebase, and a sweep now fails the build if another lands — walking the AST rather
than the source text, because the first version of that sweep flagged the comment
explaining the fix.

Worth being precise about what found it: the input schemathesis sent was irrelevant. **Any
test that had called this endpoint once, with anything, would have caught it.** There was
none. The gate's value here was not clever input generation — it was being the first thing
ever to make the request.

Fixing that exposed a second defect underneath, which is the more interesting one because
it fails silently rather than loudly. `users.user_goals` is a plain `Column(JSON)` with no
`MutableList`, and the handler did `user.user_goals.append(...)`. SQLAlchemy does not see
an in-place mutation, so the attribute is never marked dirty, no UPDATE is emitted, and the
`refresh()` that follows reloads the row without the goal — **200, and the write is gone**.
`update_user_goal` had it too, and its symptom is worse: a 200 carrying the operator's
previous values, which reads as an edit that accepted itself and then reverted.

The handler guarded `if user.user_goals is None: user.user_goals = []` first, which reads
like it rescues the case. It does not: the column is `default=[]`, so every user created
through the ORM already holds `[]` and that branch never runs. Measured, not reasoned —
reverting the fix loses the FIRST goal, not merely the second, and the test was corrected
to say so. `delete_user_goal`, in the same file, reassigns the list and was right all along.

Both are pinned by `tests/test_user_goals_roundtrip_realdb.py`, which reads every goal back
through a **separate request**, because the silent half is invisible in the response that
created it.

### The 500 that was in the error handler, not in any endpoint

`PUT /data-retention/policies/{metric_name}` was in the list above. Reproducing it directly
returned **422**, which is what made it worth chasing rather than guessing at: the shrunk
body schemathesis reported was not the one that failed.

The app's own `unhandled_exception` record gave the answer:

    Object of type ValueError is not JSON serializable

`@model_validator` raising a bare `ValueError` is the documented pydantic v2 way to express
a cross-field rule. Pydantic puts the **live exception object** in the error's `ctx`, the
envelope handler passed `exc.errors()` straight to `JSONResponse`, `json.dumps` raised, and
the generic handler turned that into a 500.

**The validator worked perfectly; reporting it was what failed.** Every request that broke
a cross-field rule got a server error where the schema promises 422 — four validators
today, across `data_retention` and `twin_optimizer`, and any that land later. It also
explains the second entry above: `POST /twin/optimize` has three such validators and was
failing for the same reason, not for one of its own.

The fix stringifies the exception before encoding rather than reaching for
`jsonable_encoder` alone, which stops the crash but renders `ctx` as `{}` — dropping the
only text that says *which* rule was broken and leaving a 422 nobody can act on.

Pinned by `tests/test_validation_errors_are_422_not_500.py`, mutation-verified against the
original handler. Writing it also caught a trap worth recording: the test module uses
`from __future__ import annotations`, so mounting the model with `payload: model` made the
annotation the *string* `"model"`, FastAPI fell back to treating it as a query parameter,
and the assertions failed against the wrong error — looking exactly like a broken fix
rather than a broken harness.

### Six real fixes moved the number by nothing, and the floor stayed at 360

Recorded because the obvious reading of it is wrong, and because the next person to fix
something here will see the same thing.

After the raise to 360, six more defects from the list above were fixed and verified
individually — including `POST /user/goals`, which had **never worked once since it was
written**. Two runs on the settled tree scored **368 and 370**, against 369 and 370 before
them. Conformance did not improve. A reader tracking only the headline number would
conclude the six fixes were worthless.

Diffing the runs operation-by-operation says otherwise. Every fix landed:

| operation | before | after |
|---|---|---|
| `POST /bulk/assets/import` | ServerError | **pass** |
| `POST /commands/submit` | ServerError | **pass** |
| `POST /transportation/load-plans` | ServerError | **pass** |
| `PUT /data-retention/policies/{metric_name}` | ServerError | **pass** |
| `POST /rag/ingest` | ServerError | **pass** (the validation-handler fix, not its own) |
| `POST /twin/optimize` | ServerError | AcceptedNegativeData |
| `POST /user/goals` | ServerError | AcceptedNegativeData |

**Two of them moved SIDEWAYS rather than to passing, and that is not a regression.** An
endpoint that 500s never reaches the negative-data check; once it works, schemathesis
mutates a valid body to violate the schema and gets a 2xx — landing in the
`AcceptedNegativeData` bucket, which the section above explains is a strictness *policy*
this API has not adopted (pydantic's lax mode coerces `0` to `False`; unknown query params
are ignored, as most clients rely on). So `AcceptedNegativeData` rose 25 → 27 for exactly
the reason `ServerError` fell.

The rest of the difference is the documented flappers firing. The three
`model-monitoring/*/history/{model_id}` operations read time-window queries whose window
moves during the run, and they flip across the six runs measured so far:

    runs 1,2,3,4,7,8   F P P P P F

**Two lessons, and the second is the one to keep.** First, the 9-point margin is earning
its keep: four runs of the same tree have now spanned 368–370, so the spread is not the 1
that runs 3 and 4 suggested. Second, and more important:

> **"Conformance went up" is not a sound proxy for "the code got better."** A feature that
> had been dead since it was written now works, and the number did not move. Judge a fix by
> reproducing it, not by the gate's headline.

The floor therefore stays at **360**. Raising it on runs 3–4's minimum of 369 would have
been the mistake this document warns about in the other direction — pinning to a lucky pair
and failing builds on the next honest run.

### The ~20 `503`s are the harness, not the API

Worth knowing before anyone counts them as debt. The `api-contract` job provisions **only
Postgres**, and `REDIS_URL` / `REDPANDA_URL` are `redis:6379` / `redpanda:29092` — docker
network names that resolve from neither a CI runner nor a developer's host. So every
endpoint whose dependency is Redis or the broker answers 503: feature flags, bulk jobs,
export jobs, the query-performance surface, `/health/kafka`, `/health/ready`.

Those 503s are the endpoints reporting a missing dependency **correctly**. They are counted
as failures because schemathesis treats any 5xx as a server error. Do not "fix" them in
application code.

**Measured 2026-07-31, and the two halves are very different jobs.** Against a throwaway
database:

| services reachable | conforming |
|---|---|
| postgres only (what the job had) | 368–370 |
| + Redis | **383** |
| + Redis + broker | **387** |

So Redis alone was costing ~14 operations that were never the API's fault, and it needs no
`command:` — it is now a service block on the job. **The broker is the awkward half for a
specific reason worth recording:** Redpanda must advertise an address the client can reach
(`redpanda start --advertise-kafka-addr ...`), and GitHub service containers accept
image/env/ports/options and **no command**. Point the app at a broker that advertises its
internal hostname and the client connects to the bootstrap address, is redirected somewhere
it cannot resolve, and hangs — the app then never serves `/openapi.json` inside the suite's
120-second window and the run collects **1 operation instead of 452**.

That is not a thought experiment; it happened on the first attempt here, and the ratchet
caught it as a collapsed collection rather than reporting a pass. With a correctly-advertised
broker the app starts in **3.3 seconds**. The remaining ~4 operations therefore need a
`docker run` step rather than a service block — tracked as FS-259b.

**The floor was deliberately NOT raised in the same change.** Even the no-services baseline
(368) clears 360, so if Redis misbehaves on a runner the gate reports the old number and
still passes; it cannot turn red for an infrastructure reason. Raise the floor once CI has
shown the new number across a couple of runs — the raise wants CI's measurement, not a
workstation's.

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

### Reading the score between runs (FS-264)

`contract_ratchet.py` answers one question — did conformance drop below the floor — and the
floor sits 8–9 points below the observed minimum. **A regression of five operations is
therefore invisible** until a sixth arrives and the build fails, by which point the change
that caused it is several commits back.

`scripts/contract_summary.py` runs alongside it and writes to `$GITHUB_STEP_SUMMARY`, so
every run shows its own numbers in the Actions UI without anyone downloading a JUnit file.
It never fails the build; the ratchet is still the gate. It reports:

* conformance, the floor, and the **headroom** between them — with a warning when the
  headroom drops to 3 or fewer, which is the early signal the floor cannot give;
* a **per-check breakdown**, marked defect vs policy;
* the **undeclared-route count** against its own ratchet;
* the list of operations returning 5xx, folded away.

**The per-check breakdown is the whole point, and 2026-07-31 is why.** Six defects were
fixed and verified individually that day and the total went 369 → 368. The headline said the
work was worthless. The categories said what actually happened:

    ServerError            41/40 -> 40/38     the fixes landing
    AcceptedNegativeData   25    -> 27        two of them moving SIDEWAYS

An endpoint that 500s never reaches the negative-data check, so fixing it can move an
operation from one failing bucket to another rather than to passing. A trend of the total
alone reports that as nothing happening — and one of those six restored a feature that had
never worked since the day it was written.

The undeclared-route count sits next to conformance deliberately, not in its own job:
schemathesis can only check what a route declares, so conformance is a statement about the
declared surface only. Read alone it rises when routes are declared **and** when routes are
deleted, and those are not the same news.

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
