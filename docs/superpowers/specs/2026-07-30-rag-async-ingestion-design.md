# Async RAG ingestion — durable status + indexing worker (design)

## Goal

Fix item #1 of `docs/rag_ingestion_followups.md`: `POST /api/v1/rag/ingest`
parses → chunks → embeds → upserts **inside the HTTP request**. A large
document produces hundreds of chunks and many sequential embed calls (each up
to `RAG_INFERENCE_TIMEOUT`, 180s in compose), so the request can run for
minutes and exceed the nginx `proxy-read-timeout`. The blob is stored, but the
caller sees a 504 and cannot tell whether indexing finished.

After this change the request stores the blob, records a `queued` document row,
and returns `202` immediately. A dedicated worker performs the slow indexing and
writes a terminal status the caller can poll.

## Scope

In scope:
- New `rag_documents` table (migration + ORM model + RLS), the canonical
  per-document record and the work queue.
- Split `IngestionPipeline.ingest_document` into `store_document` (fast,
  in-request) and `index_document` (slow, worker-side).
- New `app/services/rag_index_queue.py` for row lifecycle (upsert-queued,
  claim, finalize, recover-stale).
- New `app/workers/rag_indexing.py` polling worker + compose service + k8s
  deployment.
- `POST /ingest` returns `202`; new `GET /rag/documents/{doc_id}/status`;
  additive metadata on `GET /rag/documents`; `DELETE` also removes the row.
- `doc_id` input validation (tenant-isolation hardening, see below).
- Migrating the three existing callers to the async contract.

Out of scope (remain open in `rag_ingestion_followups.md`):
- #2 streaming upload / `Content-Length` cap before buffering.
- #3 separating ingest and query inference capacity.
- #4 `delete_by_doc` → re-upsert atomicity. This design adds the per-document
  status field that a later fix for #4 needs.
- #5 per-tenant ingest quotas / rate limits.

## Approach: DB queue, not a Kafka outbox

The three existing async workers (`compliance_reports`, `export_delivery`,
`ingestion`) consume from Redpanda. This one deliberately does not. The
`rag_documents` row **is** the queue; the worker claims `status='queued'` rows
with `SELECT … FOR UPDATE SKIP LOCKED`, the same idiom already used by
`compliance_report_queue.py:155-180`.

Reasons, in order of weight:

1. **No singleton on k8s.** A Kafka outbox needs two runtime roles: a
   *dispatcher* (DB → Kafka) that must be a singleton, or two of them race the
   same rows, plus a scalable consumer. That is why `ota-rollout-worker` is
   pinned to `replicas: 1` and asserted so at `test_ota_worker_topology.py:212`.
   Singletons roll badly (gap or overlap during updates) and cannot autoscale.
   `SKIP LOCKED` is precisely the primitive that makes concurrent claimers safe,
   so this worker is correct at any replica count.
2. **An outbox dispatcher exists to bridge the DB to a consumer that cannot
   read the DB.** Our consumer can read the DB. The Kafka hop would buy fan-out
   we do not need and cost a singleton we would rather not deploy.
3. **Fewer dependencies in the RAG lane.** No topic, producer, dispatcher
   singleton, or Redpanda dependency for RAG indexing.

Consistency is preserved at the code level even though the transport differs:
the worker module follows `ota_rollouts.py:16-56` (injectable collaborators,
`stop_event`, SIGTERM/SIGINT handling), org scoping uses
`set_config('app.current_org_id', …)` like every other worker, and the
claim/finalize helpers mirror `compliance_report_queue.py:155-212`.

Trade-offs accepted: pickup latency bounded by the poll interval rather than
near-instant, and backlog is observed via `count(*) WHERE status='queued'`
rather than a Kafka consumer-lag metric. For ingestion measured in minutes,
a 5s interval is noise.

### Note on an adjacent observation

While tracing dispatch ownership, the compose topology appeared to leave the
**compliance** outbox undrained: `backend` sets `SCHEDULERS_IN_API=false`
(`docker-compose.yml:105`) so `compliance_report_dispatcher.start()` never runs
(`main.py:72-75`), and `compliance-reports-worker` runs only the consumer
`run()`. This was inferred from reading the wiring, not observed at runtime. It
is **out of scope** here and needs separate verification — recorded because it
is a failure mode this design deliberately cannot reproduce.

## Data model

`rag_documents` is a **plain Postgres table**, not a hypertable. The database is
one TimescaleDB instance (`timescale/timescaledb:latest-pg15`), and only six
append-only time-series tables are hypertables (`telemetry`, `packml_states`,
`alarms`, `reward_metrics`, `audit_trail`, and `034`'s historian table). Every
job/state table — `compliance_report_jobs`, `export_delivery_jobs` — is plain.

Beyond convention there is a hard blocker: TimescaleDB requires every UNIQUE
constraint on a hypertable to include the partitioning column, so
`UNIQUE (organization_id, doc_id)` would be rejected. Satisfying it would mean
adding a timestamp to the key, which would permit the same `doc_id` twice and
destroy the one-row-per-document invariant the status endpoint depends on.
Hypertables also optimize append-only inserts, while this row's entire life is
`UPDATE`s.

Migration `database/migrations/043_rag_documents.sql`, structured like
`015_compliance_report_jobs.sql`: `CREATE TABLE IF NOT EXISTS` → `ALTER`
reconcile for the `init_db()` bootstrap path → drop/add constraints → indexes →
RLS.

```
id              UUID PK DEFAULT gen_random_uuid()
organization_id UUID NOT NULL      -- FK organizations ON DELETE CASCADE
doc_id          TEXT NOT NULL      -- caller-supplied free text, NOT a uuid
uploaded_by     UUID               -- FK users ON DELETE SET NULL
filename        VARCHAR(255) NOT NULL
s3_key          TEXT NOT NULL
kind            VARCHAR(20) NOT NULL
status          VARCHAR(20) NOT NULL DEFAULT 'queued'
attempts        INTEGER NOT NULL DEFAULT 0
num_blocks      INTEGER NOT NULL DEFAULT 0
num_chunks      INTEGER NOT NULL DEFAULT 0
reason          TEXT               -- non-error explanation (skipped/partial)
error           TEXT               -- infra fault detail
created_at, updated_at, started_at, completed_at  TIMESTAMPTZ
```

`doc_id` is `TEXT`, not `UUID`: it is caller-supplied and the eval suite sends
values like `eval-pdf-<run_id>` (`run_rag_eval.py:377`).

Constraints:
- `ck_rag_documents_status CHECK (status IN ('queued','indexing','indexed','skipped','failed'))`
- `ck_rag_documents_kind CHECK (kind IN ('pdf','docx','markdown','csv','image','text','unsupported'))`
- `uq_rag_documents_org_doc UNIQUE (organization_id, doc_id)`
- `fk_rag_documents_organization … ON DELETE CASCADE`
- `fk_rag_documents_uploaded_by … ON DELETE SET NULL`

Indexes:
- `idx_rag_documents_org_created (organization_id, created_at DESC)` — listing,
  mirroring its `compliance_report_jobs` counterpart.
- `idx_rag_documents_claimable (organization_id, created_at) WHERE status='queued'`
- `idx_rag_documents_stale (updated_at) WHERE status='indexing'`

The last two are **partial** indexes, sized to the queue rather than the table —
the standard Postgres treatment when the interesting states are a small minority
of rows.

RLS is copied verbatim from `015`: `ENABLE` + `FORCE ROW LEVEL SECURITY` and a
`tenant_isolation` policy on `app.current_org_id` for both `USING` and
`WITH CHECK`.

Because `FORCE ROW LEVEL SECURITY` applies to the worker too, the worker cannot
see rows without a tenant context. It therefore enumerates organizations and
polls per-org with `set_config('app.current_org_id', …)` — exactly what
`compliance_report_queue.py:144-153` does. This is the established shape, and it
keeps tenant isolation intact inside the worker.

## State machine

```
POST /ingest ──► queued ──claim (SKIP LOCKED)──► indexing ──┬──► indexed
                   ▲                                        ├──► skipped
   re-ingest ──────┤                                        └──► failed
   stale recovery ─┘                     (retry: back to queued if attempts left)
```

Terminal classification preserves today's semantics exactly:

| Outcome | Status | Retried | Carries |
|---|---|---|---|
| unsupported type, parse raised, 0 blocks, 0 chunks | `skipped` | no | `reason` |
| chunk cap hit, remainder indexed | `indexed` | — | `reason` + `num_chunks` |
| embed timeout, inference/vector store down, blob unreadable | `queued` → … → `failed` | yes | `error` |
| all chunks upserted | `indexed` | — | `num_chunks` |

`skipped` and `failed` are distinct so the worker never spends retries on a
document that will never parse, and never gives up on a transient infra fault.

The chunk-cap row matters: `rag_ingestion.py:437-445` currently truncates and
*still indexes*, setting `reason`. Because `reason` is independent of `status`,
that behavior survives unchanged.

## Concurrency and failure handling

**Claim.** `… WHERE organization_id=:org AND status='queued' ORDER BY created_at
LIMIT 1 FOR UPDATE SKIP LOCKED`, then set `indexing`, `attempts += 1`,
`started_at = now()`, commit.

**Finalize is conditional**: `UPDATE … WHERE status='indexing' AND
attempts=:claimed_attempts AND started_at=:claimed_started_at`. If a re-ingest
resets the row to `queued` while a pass is in flight, the stale finalize matches
nothing and is discarded, and the fresh row is claimed cleanly. This extends the
guard `_finish_publication` uses at `compliance_report_queue.py:197`.

`started_at` is load-bearing, not decoration. An earlier draft of this design
guarded on `status` and `attempts` alone, which is **insufficient**: because
`upsert_queued` resets `attempts` to 0 and the next `claim_next` returns it to
1, the guard value recycles across re-ingest generations. The resulting ABA
collision was reproduced against a real database:

1. Worker W1 claims doc X (`attempts=1`, `indexing`) and starts a long embed.
2. The user re-uploads X — `upsert_queued` sets `queued`, `attempts=0`.
3. Worker W2 claims the new generation — `attempts` is back to `1`.
4. W1 finishes the OLD content and finalizes with `attempts=1` — which now
   matches **W2's live claim**. The stale write lands: the row reports
   `indexed` with the previous upload's chunk count while W2 is still writing
   vectors for the new one.

`claim_next` writes a microsecond-precision `started_at` inside the locking
transaction and `upsert_queued` nulls it, so `started_at` uniquely identifies
one claim without a second migration. `requeue_or_fail` carries the same guard —
there, a stale requeue would flip a live claim back to `queued`, letting a third
worker index the same document concurrently with W2.

**`requeue_or_fail` reports only what it wrote.** Its return value is derived
from the UPDATE's `rowcount`, not from the Python-side `attempts` argument: a
stale call whose guard matched nothing must not report `failed` for a document
that is actually sitting healthy in `queued`, or the worker emits terminal
failure logs and alerts for a live row.

**Crash mid-index** leaves a row in `indexing`. `recover_stale()` runs at the top
of each poll and returns rows older than `RAG_INDEX_STALE_INDEXING_SECONDS` to
`queued`, or to `failed` once attempts are spent — mirroring
`recover_stale_jobs()` (`workers/compliance_reports.py:119-162`).

**Write ordering is blob-then-row.** A crash between them orphans a blob and
returns 500; the client retries the same `doc_id`, overwrites the same `s3_key`,
and the row appears. Idempotent. Row-first would instead create a queued row
pointing at a blob that does not exist, which the worker could only resolve as
`failed`.

**Delete ordering** keeps the existing vectors → blobs sequence
(`rag_ingestion.py:511-528`) and appends the row delete **last**, so an
interrupted delete never leaves queryable vectors behind.

## Settings (`app/core/config.py`)

| Setting | Default | Purpose |
|---|---|---|
| `RAG_INDEX_WORKER_ENABLED` | `True` | Master gate for the worker loop |
| `RAG_INDEX_POLL_INTERVAL_SECONDS` | `5` | Idle sleep between passes |
| `RAG_INDEX_MAX_ATTEMPTS` | `3` | Retries before `failed` |
| `RAG_INDEX_STALE_INDEXING_SECONDS` | `900` | Must exceed worst-case indexing; compose runs `RAG_INFERENCE_TIMEOUT=180` per batch |

The per-pass claim cap stays a module constant mirroring compliance's
`range(100)`, to avoid growing the config surface.

## API contract

**`POST /ingest` → `202 Accepted`.** `IngestionResult` gains a `status` field;
the response becomes `stored=true, indexed=false, status="queued"`. `doc_id` is
validated before anything is written; existing 400/413/503 behavior is
unchanged.

**`GET /documents/{doc_id}/status` — new.** Org-scoped projection of
`doc_id, status, kind, filename, num_blocks, num_chunks, reason, error,
attempts, created_at, started_at, completed_at`. Returns 404 when no row exists
for `(org, doc_id)`, so one tenant probing another's `doc_id` is
indistinguishable from a genuine miss.

**`GET /documents` — additive only.** `count` and `keys` keep their exact
current meaning and source (S3), because `rag_eval/client.py:138-150` parses
`keys`. A new `documents` array carries the Postgres metadata alongside. This
mirrors how `core/errors.py:72-84` layered RFC-9457 members onto the existing
envelope. Keeping `keys` sourced from S3 is also honest: documents ingested
before this migration have blobs but no row, and that divergence should be
visible rather than hidden.

**`DELETE /documents/{doc_id}`** additionally removes the row, ordered last.

### `doc_id` validation (tenant-isolation hardening)

`build_document_key` (`document_store.py:40-46`) builds
`f"{org_id}/{doc_id}/{filename}"` with no sanitization, and `doc_id` is
caller-supplied free text. A `doc_id` of `../victim-org` writes outside the
tenant prefix; a `doc_id` containing `/` also silently breaks the three-part key
contract asserted at `verify_rag_e2e.py:182`.

This is pre-existing, but this change makes `doc_id` half of a uniqueness
constraint and a URL path segment, so it becomes load-bearing. `doc_id` is
therefore validated against `^[A-Za-z0-9._-]{1,128}$`, rejected as 422 through
the standard error envelope, before any write occurs.

## Components

New:

| File | Purpose |
|---|---|
| `database/migrations/043_rag_documents.sql` | Table, indexes, RLS |
| `app/services/rag_index_queue.py` | Row lifecycle: upsert-queued, claim, finalize, recover-stale |
| `app/workers/rag_indexing.py` | Poll loop + signal handling |
| `infrastructure/k8s/base/rag-indexing-worker-deployment.yaml` | Fifth worker deployment |

Modified: `app/db/models.py` (`RagDocument`), `app/services/rag_ingestion.py`
(the split), `app/api/rag.py`, `app/core/config.py`, `docker-compose.yml`,
`infrastructure/k8s/base/kustomization.yaml`, and the three callers.

`rag_index_queue.py` is separate from `rag_ingestion.py` because the pipeline
module is already 535 lines and currently has **zero** database awareness — it
talks only to S3, inference, and Qdrant. The codebase already draws this line:
`compliance_report_queue.py` (persistence + dispatch) sits beside
`compliance_report_service.py` (the work itself).

### Pipeline split

- **`store_document(...)`** — in-request. Detect kind, build `s3_key`,
  `ensure_bucket`, `put_document`, UPSERT the row as `queued`. This is the
  existing code through `rag_ingestion.py:395`, which is already the natural
  seam: the blob is durable and nothing slow has happened yet.
- **`index_document(org_id, doc_id)`** — worker-side. Re-reads the blob via
  `docs.get_document(s3_key)`, then parse → chunk → embed → upsert exactly as
  today, then writes the terminal status.

The worker re-fetching the blob (rather than carrying bytes in a queue payload)
keeps the row small and makes retries free.

### Worker shape

```python
async def run(*, stop_event=None, poll_interval=None, indexer=None) -> None:
    # SIGTERM/SIGINT register/remove — ota_rollouts.py:26-56
    while not stop_event.is_set():
        await recover_stale()
        for org_id in await list_org_ids():
            await drain_org(org_id)        # bounded claim → index → finalize
        await _wait_or_stop(poll_interval)
```

Collaborators are injectable, matching
`ota_rollouts.run(*, stop_event, command_service, rollout_service)` and
`compliance_reports.run(max_messages)` — that is what makes these workers
testable without a broker or a cluster. `drain_org` is bounded per pass so one
busy tenant cannot starve the others.

## Deployment

**Compose:** service `rag-indexing-worker`,
`command: python -m app.workers.rag_indexing`, `SCHEDULERS_IN_API: "false"`,
`depends_on` migrate (`service_completed_successfully`), timescaledb, seaweedfs,
qdrant. **No redpanda dependency** — the payoff of the DB-queue approach.

**k8s:** `rag-indexing-worker-deployment.yaml` copying
`export-worker-deployment.yaml`'s security context (`runAsNonRoot`,
`readOnlyRootFilesystem`, `capabilities: drop: [ALL]`) and
`backend-deployment.yaml:88-108`'s RAG env block verbatim, including its caveat
that those `omniusgrid-rag` FQDNs only resolve where the standalone rag base is
also applied. One `kustomization.yaml` entry.

Ships `replicas: 1` for consistency with its siblings, but carries a comment
recording that — unlike `ota-rollout-worker` — it is safe to raise or place
behind an HPA, because claims use `SKIP LOCKED`.

## Testing

New modules, each modeled on an existing one:

- **`test_rag_documents_migration.py`** — clone of
  `test_compliance_report_migration.py`: fresh schema, re-apply over an
  `init_db()`-created table, constraints/indexes present, RLS blocks both
  no-context and cross-tenant reads *and* writes, plus an ORM-contract test
  asserting the model's checks and FK `ondelete` match the SQL.
- **`test_rag_index_queue.py`** — two concurrent claimers never take the same
  row; stale `indexing` rows recover; a finalize is discarded when a re-ingest
  re-queued the row mid-flight; attempts exhaustion lands in `failed`.
- **`test_rag_indexing_worker.py`** — one pass end-to-end with fake
  inference/vector/document stores: `queued → indexed`; parse failure →
  `skipped` + reason; injected infra error → re-`queued`, then `failed` at max
  attempts.
- **`test_rag_ingest_async_api.py`** — `POST /ingest` returns 202 and writes a
  `queued` row; status endpoint round-trips; unknown `doc_id` → 404; org B
  cannot read org A's status; malformed `doc_id` → 422.
- A compose/k8s topology assertion in the style of
  `test_ota_worker_topology.py:147-222`, pinning command, env, and `depends_on`.

Existing guards that must stay green: `test_realdb_endpoint_smoke.py` (the new
GET is walked automatically and must not 5xx), `test_route_auth_walk.py` (the
new GET must reject anonymous requests), `test_schema_migration_contract.py`.

## Caller migration

The polling lives **inside the eval client**, so assertions do not move.
`rag_eval/client.py::ingest()` posts, polls `/status` until terminal, then
returns a dict shaped exactly as today (`indexed`, `num_blocks`, `num_chunks`,
`reason`). `run_rag_eval.py:278-285` therefore needs **no changes**.
`verify_rag_e2e.py:157-161` becomes `202` + poll + the same `indexed=true`
check.
