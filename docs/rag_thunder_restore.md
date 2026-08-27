# Restoring the RAG verification box from a Thunder snapshot

How to bring up a ready-to-test RAG stack on any machine, from the
`omniusgrid-rag-dev-20260827` snapshot. Roughly 10 minutes, most of it waiting
on the instance to provision.

The snapshot exists because compose cannot run on a Thunder box at all — see the
header of `scripts/thunder_bootstrap.sh` for why. Rebuilding this environment
from scratch means re-resolving FlagEmbedding against torch/transformers,
re-downloading ~5 GB of BGE weights, re-pulling an 8 GB Ollama model, and
re-running 47 migrations. The snapshot skips all of it.

## What is in the snapshot

| | |
|---|---|
| Name | **`omniusgrid-rag-dev-20260827`** (newest — use this one) |
| Minimum disk | 100 GB |
| Source instance | A6000, 6 vCPU, 48 GB RAM |

Older snapshots `omniusgrid-rag-testready`, `omniusgrid-rag-verified`, and
`omniusgrid-rag-dev-20260814` are earlier points on the same lineage; prefer
the newest unless you specifically want to go back before FS-666 (streaming)
or the CI-job/dedup work.

**State frozen in `omniusgrid-rag-dev-20260827`** — taken 2026-08-27 after a
full verification pass on `feature/RAG-Compliance-Doc-Pipeline` at `14e16b2f`
(FS-669 fix + FS-666 SSE streaming + the RAG CI job/dedup + the empty-SSE-
error-detail fix), with the async `rag-indexing-worker` in the loop for the
first time since it was built (closes the gap `docs/RAG_DEVELOPMENT.md` §8
flagged — the prior snapshot's e2e pass predated async ingestion entirely):

- Tree matches `feature/RAG-Compliance-Doc-Pipeline` at `14e16b2f` (rsync'd
  from a workstation checkout, not cloned — see "Updating the code" below).
- `verify_rag_e2e.py` **PASS**, worker-in-the-loop (queued→indexed via
  `rag-indexing-worker`, not inline).
- `POST /query/stream` (FS-666) verified live against real GPU generation:
  citations→32 deltas→done, correct grounded answer with citations. Caught
  and fixed one real bug in the process — `httpx`'s `*Timeout` exceptions
  stringify to `""`, so a mid-stream LLM timeout was surfacing as
  `{"detail": ""}`; now falls back to the exception's type name.
- RAG unit/queue tests (11 files, the same ones the new `rag-ci.yml` reusable
  CI job runs) via `TEST_DATABASE_URL`: **61/62 pass.** The 1 failure
  (`test_recover_stale_requeues_abandoned_indexing_rows`, expected
  `recovered==1` got `5`) is confirmed scratch-DB pollution — this snapshot's
  `omniusgrid_hatch` carries 4 leftover `indexing`-status rows from prior
  sessions' runs, not a code bug. A fresh CI Postgres container won't have
  this. **Not cleaned up in this snapshot** — truncate `rag_documents` in
  `omniusgrid_hatch` before trusting that specific test's count, or ignore it.
- `rag_eval` **121 passed, 4 failed, 2 skipped** (37 min). Same 3
  pre-existing content-quality misses as 2026-08-14 (`test_synthesis[*_twice_fail_flow]`
  on `sop-qa-014` txt and `sop-wh-021` pdf/md, missing concepts
  `hold_disposition`/`deviation`/`escalate_dql`/`escalate_pqm` — **still the
  open bug to pick up**). Plus one *new*, different-in-kind failure:
  `test_synthesis[sop-qa-014-pdf-Q3_acid_rinse_time]` hit an HTTP 500 — traced
  to `httpcore.ReadTimeout` at exactly `LLM_TIMEOUT=120s` on the
  non-streaming `/query` route. `gemma4:12b` emits substantial chain-of-
  thought reasoning before its final answer (observed directly on a plain
  "say hi" prompt too), and apparently ran long enough on this one query to
  blow past 120s. Real intermittent tail-latency risk with this
  model+timeout combo, but it's pre-existing `/query` code untouched this
  session, not a regression. Worth raising `LLM_TIMEOUT` or picking a
  less reasoning-verbose model if this recurs.
- Performance: `scripts/rag_perf.py` still has not been re-run against this
  tree; the 2026-08-14 numbers (see memory, not frozen in this doc) predate
  FS-666/the CI work and are not necessarily still representative.
- A scratch database `omniusgrid_hatch` exists for `TEST_DATABASE_URL` runs
  (see the pollution note above — inherited, not reset, by this snapshot).

- `.venv` with FlagEmbedding 1.4.0 resolved against torch 2.13.0+cu130 and
  transformers 5.15.0, with no downgrade. This resolution is the fiddly part.
- `~/hf-models` — BGE-M3 + `bge-reranker-v2-m3` weights.
- Ollama installed with `gemma4:12b` pulled.
- Docker volumes for TimescaleDB (all 47 migrations applied, including 043 and
  044), Qdrant, and SeaweedFS. Postgres was checkpointed before the snapshot.
- `~/rag.env` — localhost-mapped environment, and `~/ragstack.sh`.

**Not** in scope: this verifies application code against real
Qdrant/SeaweedFS/Postgres/BGE. It does **not** verify the Dockerfiles, the
compose service wiring, or the k8s manifests — those need a box that can build
images, which a Thunder instance cannot.

## 1. Install the CLI

Get it from https://github.com/Thunder-Compute/thunder-cli/releases — Windows
`.msi`, macOS installer, or the Linux shell script.

> Do **not** `pip install tnr`. That package is the abandoned v1 CLI; its API
> endpoints return 404, and installing it downgrades `click` and `rich`.

```bash
tnr login          # opens a browser
tnr snapshot list  # confirm omniusgrid-rag-testready shows status READY
```

Wait for `READY`. A snapshot still `CREATING` cannot be used as a template.

## 2. Create an instance from it

```bash
tnr create --snapshot omniusgrid-rag-dev-20260827 --gpu a6000 --vcpus 6 --disk 100
```

`--disk` must be at least the snapshot's 100 GB minimum. The GPU matters: the
stack runs rag-inference natively at fp16, loading both models in ~36 s, versus
the 600 s CPU budget the compose healthcheck assumes.

```bash
tnr status            # note the new instance id
tnr connect <id>      # writes the ssh config entry and connects
```

`tnr connect` is what creates the `tnr-N` host alias — you cannot ssh to the box
until you have run it at least once on this machine.

**If `tnr connect <id> --json` (non-interactive) is used to grab connection
details instead of the interactive flow** — e.g. to script around it — its
own `ssh_command` field (`root@` + a key file with no extension) did not
actually work when tested 2026-08-27: the box only accepted `ubuntu@` with
the matching `.pem`-suffixed key from `~/.thunder/keys/`. Check
`~/.thunder/keys/` for both a bare and a `.pem`-suffixed file with the same
UUID prefix and try `ubuntu@` first if the reported command fails. Also:
killing `tnr connect` mid-process (e.g. to stop it before it opens an
interactive shell) can truncate `~/.ssh/config` — back it up first if you're
scripting this rather than running `tnr connect <id>` interactively and
leaving it to finish on its own.

## 3. Start the stack

```bash
cd ~/OmniusGrid-X
./scripts/thunder_bootstrap.sh start    # datastores + migrations + services
./scripts/thunder_bootstrap.sh status
```

Expect four datastore containers up, `/health` 200 on both 8001
(rag-inference) and 8000 (backend), and the worker running.

If you only need the Python services — the datastores survive a reboot via
`--restart unless-stopped` — skip the restart and launch them directly:

```bash
set -a; . ~/rag.env; set +a
cd ~/OmniusGrid-X/backend
setsid nohup ../.venv/bin/uvicorn app.main:app --host 0.0.0.0 --port 8000 \
  > /tmp/backend.log 2>&1 < /dev/null &
setsid nohup ../.venv/bin/python -m app.workers.rag_indexing \
  > /tmp/worker.log 2>&1 < /dev/null &
```

Logs: `/tmp/{rag-inference,backend,worker}.log`.

**Expected noise:** the backend logs `KafkaConnectionError` against
`localhost:29092` on a reconnect backoff. Redpanda is deliberately not running —
it dies inside Thunder's proot layer, and the RAG path has no Kafka dependency
(the `rag_documents` row *is* the queue). `/health` still returns 200.

## 4. Run the tests

```bash
set -a; . ~/rag.env; set +a
cd ~/OmniusGrid-X

./.venv/bin/python scripts/verify_rag_e2e.py        # end-to-end path
./.venv/bin/python -m pytest backend/tests/test_rag_ingest_quota.py -v
./.venv/bin/python -m pytest backend/tests/test_rag_upload_limit.py -v
./.venv/bin/python -m pytest backend/tests/rag_eval/ -v
```

Watch for these:

Testcontainers cannot run on a Thunder box at all — it publishes ports, which
needs bridge networking, and only `host`/`none` exist. Use the escape hatch
instead; this is how the 32 queue/quota/migration tests are run here:

```bash
export TEST_DATABASE_URL="postgresql://omniusgrid:omniusgrid_dev_password@localhost:5432/omniusgrid_hatch"
./.venv/bin/python -m pytest -q \
  backend/tests/test_rag_index_queue.py \
  backend/tests/test_rag_ingest_async_api.py \
  backend/tests/test_rag_documents_migration.py \
  backend/tests/test_rag_ingest_quota.py
```

`TEST_DATABASE_URL` is destructive — it runs the whole migration chain against
whatever it names, so keep it pointed at a scratch database.
- `rag_eval/test_lifecycle.py` — re-ingest must reset status to `queued`.
- `rag_eval/test_isolation.py` — the first real `FOR UPDATE SKIP LOCKED`
  contention test.

## Updating the code

`~/OmniusGrid-X` is an rsync copy with no `.git`. To pick up newer commits,
either clone fresh alongside it:

```bash
git clone https://github.com/SoundSafe-Dev/OmniusGrid-X.git
cd OmniusGrid-X && git checkout feature/RAG-Compliance-Doc-Pipeline
```

reusing `../OmniusGrid-X/.venv` and `~/rag.env`, or rsync from a workstation
that has the branch checked out:

```bash
rsync -av --exclude .git --exclude .venv --exclude node_modules \
  ./ tnr-N:~/OmniusGrid-X/
```

## Cost

The instance bills for every minute it is `RUNNING`. **Stopping the containers
does not stop billing.** When you are done, snapshot anything worth keeping and
delete the instance:

```bash
tnr snapshot create --instance-id <id> --name <name>
tnr delete <id>
```

Run `tnr status` periodically — it lists every instance on the account, and it
is easy to leave one running for days without noticing.
