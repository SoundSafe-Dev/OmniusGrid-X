# Restoring the RAG verification box from a Thunder snapshot

How to bring up a ready-to-test RAG stack on any machine, from the
`omniusgrid-rag-testready` snapshot. Roughly 10 minutes, most of it waiting on
the instance to provision.

The snapshot exists because compose cannot run on a Thunder box at all — see the
header of `scripts/thunder_bootstrap.sh` for why. Rebuilding this environment
from scratch means re-resolving FlagEmbedding against torch/transformers,
re-downloading ~5 GB of BGE weights, re-pulling an 8 GB Ollama model, and
re-running 47 migrations. The snapshot skips all of it.

## What is in the snapshot

| | |
|---|---|
| Name | `omniusgrid-rag-testready` |
| Minimum disk | 100 GB |
| Source instance | A6000, 6 vCPU, 48 GB RAM |

- `~/OmniusGrid-X` — the tree at branch `rag-async-ingest`, as an **rsync copy,
  not a git repo**. See "Updating the code" below.
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
tnr create --snapshot omniusgrid-rag-testready --gpu a6000 --vcpus 6 --disk 100
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

- `test_rag_ingest_quota.py` — 11 tests that have **never been run**. It uses
  testcontainers/Postgres, which will hit the `/dev/fd` entrypoint failure this
  sandbox has (see `thunder_bootstrap.sh`). Either patch the fixture's command
  to symlink `/dev/fd`, or point it at the already-running Postgres.
- `rag_eval/test_lifecycle.py` — re-ingest must reset status to `queued`.
- `rag_eval/test_isolation.py` — the first real `FOR UPDATE SKIP LOCKED`
  contention test.

## Updating the code

`~/OmniusGrid-X` is an rsync copy with no `.git`. To pick up newer commits,
either clone fresh alongside it:

```bash
git clone https://github.com/SoundSafe-Dev/OmniusGrid-X.git
cd OmniusGrid-X && git checkout rag-async-ingest
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
