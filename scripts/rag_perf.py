#!/usr/bin/env python3
"""
RAG pipeline performance driver.

Ingestion is asynchronous: ``POST /rag/ingest`` stores the blob, writes a
``rag_documents`` row as ``queued``, and returns 202 — the actual parse/chunk/
embed/upsert happens later on ``rag-indexing-worker``, which claims rows with
``FOR UPDATE SKIP LOCKED``. That split is why "ingest performance" is really
two separate numbers (how fast the API accepts documents, and how fast the
worker drains them), not one — conflating them into a single "ingest time"
would hide whichever one is actually the bottleneck. This script keeps them
separate throughout.

What this measures, against a live stack (see verify_rag_e2e.py for the same
endpoint/env-var conventions this script reuses):

  1. Ingest throughput      - docs/min and MB/min, end to end (202 -> terminal)
  2. Queued -> indexed      - wall time from 202 to a terminal status row,
                              p50/p95 (not a mean — see percentile() below)
  3. Query latency          - p50/p95 over repeated POST /query calls. The API
                              returns only a final answer with no per-stage
                              timings, and this driver does NOT reimplement the
                              backend's hybrid Qdrant fusion to fake a
                              breakdown — that would not measure production
                              traffic. It DOES separately time direct
                              rag-inference /embed calls as an auxiliary,
                              clearly-labeled probe (see --no-embed-probe).
  4. Worker drain rate      - submit a backlog of N documents up front, then
                              measure how fast rag-indexing-worker clears it
  5. Quota-check overhead   - the ingest path runs one aggregate query
                              (rag_index_queue.quota_usage) before storing the
                              blob. This driver cannot isolate that single
                              query over HTTP; it reports the closest
                              available proxies and says so explicitly rather
                              than inventing a number.

Everything this script creates (perf-test documents + the corpus document used
for query timing) is deleted at the end; failures to delete are reported, not
swallowed.

Run against a stack already up (`docker compose up qdrant seaweedfs
rag-inference backend rag-indexing-worker`, or the k8s equivalent). Endpoints
default to the compose host port mappings, same as verify_rag_e2e.py:

  BACKEND_URL (8000)  INFER_URL (8001)

Requires: httpx (pip install httpx)

Examples:
  python3 scripts/rag_perf.py
  python3 scripts/rag_perf.py --num-docs 50 --doc-size-kb 256 --concurrency 8
  python3 scripts/rag_perf.py --json --output run1.json
  python3 scripts/rag_perf.py --skip-drain --skip-query   # ingest-only pass
"""

from __future__ import annotations

import argparse
import itertools
import json
import math
import os
import platform
import socket
import statistics
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

try:
    import httpx
except ImportError:
    print("FATAL: httpx required -> pip install httpx", file=sys.stderr)
    sys.exit(2)

from concurrent.futures import ThreadPoolExecutor, as_completed

REPO_ROOT = Path(__file__).resolve().parent.parent
RAG_EVAL_DIR = REPO_ROOT / "backend" / "tests" / "rag_eval"

TERMINAL_STATUSES = ("indexed", "skipped", "failed")

GREEN, RED, YEL, DIM, RST = "\033[92m", "\033[91m", "\033[93m", "\033[2m", "\033[0m"


def die(msg: str) -> None:
    print(f"{RED}ABORT:{RST} {msg}", file=sys.stderr)
    sys.exit(1)


def warn(msg: str) -> None:
    print(f"{YEL}WARN:{RST} {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- #
# Pure helpers (percentile math) — kept free of I/O so they can be unit-tested
# in isolation, e.g.:
#   python3 -c "from scripts.rag_perf import percentile; assert percentile([1,2,3,4,5],50)==3"
# --------------------------------------------------------------------------- #

def percentile(data: List[float], pct: float) -> Optional[float]:
    """Nearest-rank percentile. Correct for small N, no interpolation guesswork.

    p95 of an empty/short sample is still well-defined (falls back to max), so
    a small run never silently reports ``None`` where a number is expected.
    """
    if not data:
        return None
    s = sorted(data)
    n = len(s)
    k = max(1, min(n, math.ceil(pct / 100.0 * n)))
    return s[k - 1]


def stats_ms(seconds: List[float]) -> Dict[str, Optional[float]]:
    """Summarize a list of durations (seconds) into a millisecond stats block.

    Deliberately exposes p50/p95 alongside mean/min/max — a mean alone hides
    the tail, and the tail is what a queued document or a slow query actually
    feels like to a caller.
    """
    if not seconds:
        return {"count": 0, "min_ms": None, "mean_ms": None, "p50_ms": None,
                 "p95_ms": None, "max_ms": None}
    ms = [s * 1000.0 for s in seconds]
    return {
        "count": len(ms),
        "min_ms": round(min(ms), 1),
        "mean_ms": round(statistics.mean(ms), 1),
        "p50_ms": round(percentile(ms, 50), 1),
        "p95_ms": round(percentile(ms, 95), 1),
        "max_ms": round(max(ms), 1),
    }


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #

@dataclass
class Config:
    backend: str
    infer: str
    token: str
    num_docs: int
    doc_size_kb: int
    num_queries: int
    concurrency: int
    drain_docs: int
    drain_timeout: float
    query_generate: bool
    query_timeout: float
    ingest_timeout: float
    poll_interval: float
    embed_probe: bool
    embed_probe_count: int
    skip_ingest: bool
    skip_query: bool
    skip_drain: bool
    skip_quota: bool
    no_cleanup: bool
    as_json: bool
    output: Optional[str]

    @property
    def headers(self) -> Dict[str, str]:
        return {"Authorization": f"Bearer {self.token}"}


def build_arg_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="rag_perf.py",
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    p.add_argument("--backend-url", default=os.getenv("BACKEND_URL", "http://localhost:8000"),
                    help="backend base URL (env BACKEND_URL)")
    p.add_argument("--infer-url", default=os.getenv("INFER_URL", "http://localhost:8001"),
                    help="rag-inference base URL, used only for the auxiliary embed probe (env INFER_URL)")
    p.add_argument("--token", default=os.getenv("RAG_TEST_TOKEN", "dev-token"),
                    help="bearer token (env RAG_TEST_TOKEN; default is the dev-token bypass, "
                         "which requires ALLOW_DEV_TOKEN=true on the backend)")

    g_ingest = p.add_argument_group("ingest throughput + latency")
    g_ingest.add_argument("--num-docs", type=int, default=20,
                           help="documents to ingest for the throughput/latency measurement")
    g_ingest.add_argument("--doc-size-kb", type=int, default=64,
                           help="size of each synthetic document in KiB")
    g_ingest.add_argument("--ingest-timeout", type=float, default=300.0,
                           help="seconds to wait for a single document to reach a terminal status "
                                "before counting it as a timeout")

    g_query = p.add_argument_group("query latency")
    g_query.add_argument("--num-queries", type=int, default=30,
                          help="POST /query calls to time")
    g_query.add_argument("--query-generate", action="store_true",
                          help="include LLM generation in timed queries (default: retrieval-only, "
                               "generate=false, to isolate retrieval from generation latency)")
    g_query.add_argument("--query-timeout", type=float, default=60.0,
                          help="per-query HTTP timeout in seconds")
    g_query.add_argument("--no-embed-probe", dest="embed_probe", action="store_false",
                          help="skip the auxiliary direct rag-inference /embed timing probe")
    g_query.add_argument("--embed-probe-count", type=int, default=20,
                          help="calls to time in the auxiliary embed probe")

    g_drain = p.add_argument_group("worker drain / backlog")
    g_drain.add_argument("--drain-docs", type=int, default=20,
                          help="documents submitted up front to measure worker drain rate")
    g_drain.add_argument("--drain-timeout", type=float, default=600.0,
                          help="seconds to wait for the whole backlog to drain")

    g_conc = p.add_argument_group("concurrency + scope")
    g_conc.add_argument("--concurrency", type=int, default=4,
                         help="max in-flight requests for ingest submission, backlog submission, "
                              "and query firing")
    g_conc.add_argument("--poll-interval", type=float, default=1.0,
                         help="seconds between status-polling rounds")
    g_conc.add_argument("--skip-ingest", action="store_true", help="skip phase 1/2 (ingest throughput+latency)")
    g_conc.add_argument("--skip-query", action="store_true", help="skip phase 3 (query latency)")
    g_conc.add_argument("--skip-drain", action="store_true", help="skip phase 4 (backlog drain)")
    g_conc.add_argument("--skip-quota", action="store_true", help="skip phase 5 (quota-check proxy)")
    g_conc.add_argument("--no-cleanup", action="store_true",
                         help="leave ingested documents in place (debugging only — the run will "
                              "pollute the org's document count/quota)")

    g_out = p.add_argument_group("output")
    g_out.add_argument("--json", dest="as_json", action="store_true",
                        help="emit machine-readable JSON instead of the human-readable table")
    g_out.add_argument("--output", default=None,
                        help="write output to this file instead of stdout")

    return p


def make_config(args: argparse.Namespace) -> Config:
    return Config(
        backend=args.backend_url.rstrip("/"),
        infer=args.infer_url.rstrip("/"),
        token=args.token,
        num_docs=max(0, args.num_docs),
        doc_size_kb=max(1, args.doc_size_kb),
        num_queries=max(0, args.num_queries),
        concurrency=max(1, args.concurrency),
        drain_docs=max(0, args.drain_docs),
        drain_timeout=args.drain_timeout,
        query_generate=args.query_generate,
        query_timeout=args.query_timeout,
        ingest_timeout=args.ingest_timeout,
        poll_interval=max(0.1, args.poll_interval),
        embed_probe=args.embed_probe,
        embed_probe_count=max(1, args.embed_probe_count),
        skip_ingest=args.skip_ingest,
        skip_query=args.skip_query,
        skip_drain=args.skip_drain,
        skip_quota=args.skip_quota,
        no_cleanup=args.no_cleanup,
        as_json=args.as_json,
        output=args.output,
    )


# --------------------------------------------------------------------------- #
# Preflight
# --------------------------------------------------------------------------- #

def preflight(cfg: Config) -> Dict[str, Any]:
    """Confirm every dependency this run needs is actually reachable.

    Fails loudly and names the specific dependency, rather than letting the
    first phase fail 20 documents in with an ambiguous connection error.
    """
    try:
        r = httpx.get(f"{cfg.backend}/health/live", timeout=5)
    except httpx.HTTPError as exc:
        die(f"backend unreachable at {cfg.backend}: {exc}")
    if r.status_code != 200:
        die(f"backend at {cfg.backend} is up but unhealthy (GET /health/live -> {r.status_code})")

    try:
        r = httpx.get(f"{cfg.backend}/api/v1/rag/health", headers=cfg.headers, timeout=15)
    except httpx.HTTPError as exc:
        die(f"rag health endpoint unreachable: {exc}")
    if r.status_code != 200:
        die(f"GET /api/v1/rag/health -> {r.status_code}: {r.text[:200]}")
    health = r.json()

    for name, key in (("rag-inference", "inference"), ("qdrant", "vector_store"),
                       ("document store", "document_store")):
        block = health.get(key) or {}
        if not block.get("available"):
            die(f"{name} unavailable: {block.get('reason', 'unknown')} "
                f"(from GET /api/v1/rag/health -> {key})")

    if cfg.query_generate:
        llm = health.get("llm") or {}
        if not llm.get("available"):
            die(f"--query-generate requires the LLM, but it is unavailable: "
                f"{llm.get('reason', 'unknown')}")

    return health


# --------------------------------------------------------------------------- #
# Synthetic document generation
# --------------------------------------------------------------------------- #

def synthetic_document(size_bytes: int, sentinel: str) -> bytes:
    """Filler content sized to an exact byte count, so MB/min is meaningful.

    Real prose, not random bytes: a nonsense/binary blob would let the parser
    exit early on "no extractable text" and understate real ingest cost.
    """
    phrase = (
        f"OmniusGrid perf-test document {sentinel}. Torque specification for "
        "flange F-12 is 240 newton meters. Emergency shutdown for reactor unit "
        "R-7 requires two independent operators to confirm the interlock. "
    ).encode()
    reps = size_bytes // len(phrase) + 2
    return (phrase * reps)[:size_bytes]


# --------------------------------------------------------------------------- #
# Ingest phase (throughput + queued->terminal latency)
# --------------------------------------------------------------------------- #

@dataclass
class IngestOutcome:
    doc_id: str
    accepted: bool
    error: Optional[str]
    size_bytes: int
    t_submit: float
    t_accept: Optional[float]


def ingest_one(client: httpx.Client, cfg: Config, size_bytes: int) -> IngestOutcome:
    sentinel = uuid.uuid4().hex[:12]
    doc_id = f"perf-{sentinel}"
    content = synthetic_document(size_bytes, sentinel)
    files = {"file": (f"perf_{sentinel}.txt", content, "text/plain")}
    data = {"doc_id": doc_id}
    t0 = time.time()
    try:
        r = client.post(f"{cfg.backend}/api/v1/rag/ingest", files=files, data=data,
                         headers=cfg.headers, timeout=cfg.ingest_timeout)
    except httpx.HTTPError as exc:
        return IngestOutcome(doc_id, False, str(exc), len(content), t0, None)
    t1 = time.time()
    if r.status_code != 202:
        return IngestOutcome(doc_id, False, f"HTTP {r.status_code}: {r.text[:200]}", len(content), t0, t1)
    body = r.json()
    return IngestOutcome(body.get("doc_id", doc_id), True, None, len(content), t0, t1)


def await_terminal(client: httpx.Client, cfg: Config, doc_ids: List[str],
                    timeout: float) -> Dict[str, Dict[str, Any]]:
    """Poll a batch of doc_ids until every one hits a terminal status or ``timeout``.

    One GET per pending doc per round — fine at the scale this driver expects
    (tens of documents); it is a perf *measurement* client, not itself meant
    to be a high-throughput poller.
    """
    pending = set(doc_ids)
    results: Dict[str, Dict[str, Any]] = {}
    deadline = time.monotonic() + timeout
    while pending and time.monotonic() < deadline:
        for doc_id in list(pending):
            try:
                r = client.get(f"{cfg.backend}/api/v1/rag/documents/{doc_id}/status",
                                headers=cfg.headers, timeout=30)
            except httpx.HTTPError:
                continue
            if r.status_code == 200:
                body = r.json()
                if body.get("status") in TERMINAL_STATUSES:
                    results[doc_id] = {**body, "t_terminal": time.time()}
                    pending.discard(doc_id)
        if pending:
            time.sleep(cfg.poll_interval)
    for doc_id in pending:
        results[doc_id] = {"status": "timeout", "t_terminal": None}
    return results


def phase_ingest(client: httpx.Client, cfg: Config) -> Tuple[Dict[str, Any], List[str]]:
    print(f"\n{'='*72}\n1+2. INGEST THROUGHPUT + QUEUED->TERMINAL LATENCY "
          f"({cfg.num_docs} docs, {cfg.doc_size_kb} KiB each)\n{'='*72}")
    if cfg.num_docs == 0:
        return {"skipped": True}, []

    size_bytes = cfg.doc_size_kb * 1024
    phase_start = time.time()
    outcomes: List[IngestOutcome] = []
    with ThreadPoolExecutor(max_workers=cfg.concurrency) as pool:
        futures = [pool.submit(ingest_one, client, cfg, size_bytes) for _ in range(cfg.num_docs)]
        for fut in as_completed(futures):
            outcomes.append(fut.result())

    accepted = [o for o in outcomes if o.accepted]
    rejected = [o for o in outcomes if not o.accepted]
    if rejected:
        warn(f"{len(rejected)}/{len(outcomes)} ingest requests were not accepted "
             f"(first error: {rejected[0].error})")

    accept_latency = [o.t_accept - o.t_submit for o in accepted if o.t_accept is not None]

    term = await_terminal(client, cfg, [o.doc_id for o in accepted], cfg.ingest_timeout)
    indexed = [d for d, v in term.items() if v.get("status") == "indexed"]
    skipped = [d for d, v in term.items() if v.get("status") == "skipped"]
    failed = [d for d, v in term.items() if v.get("status") == "failed"]
    timed_out = [d for d, v in term.items() if v.get("status") == "timeout"]

    by_id = {o.doc_id: o for o in accepted}
    e2e_latency = []
    for doc_id, v in term.items():
        if v.get("t_terminal") is None:
            continue
        o = by_id.get(doc_id)
        if o and o.t_accept is not None:
            e2e_latency.append(v["t_terminal"] - o.t_accept)

    phase_end = max([v["t_terminal"] for v in term.values() if v.get("t_terminal")], default=time.time())
    elapsed_min = max(phase_end - phase_start, 1e-9) / 60.0
    total_mb = sum(o.size_bytes for o in accepted) / (1024 * 1024)
    terminal_ok = len(indexed) + len(skipped)

    result = {
        "docs_submitted": len(outcomes),
        "docs_accepted_202": len(accepted),
        "docs_rejected": len(rejected),
        "docs_indexed": len(indexed),
        "docs_skipped": len(skipped),
        "docs_failed": len(failed),
        "docs_timed_out": len(timed_out),
        "wall_seconds": round(phase_end - phase_start, 2),
        "throughput_docs_per_min": round(terminal_ok / elapsed_min, 2),
        "throughput_mb_per_min": round(total_mb / elapsed_min, 2),
        "total_mb": round(total_mb, 3),
        "accept_latency_ms": stats_ms(accept_latency),
        "queued_to_terminal_latency_ms": stats_ms(e2e_latency),
        "note": "accept_latency_ms is time-to-202 (upload transfer + quota check + blob store + "
                "row upsert combined, NOT isolated to any one of those — see the quota section).",
    }
    print(f"  accepted {len(accepted)}/{len(outcomes)}, indexed {len(indexed)}, "
          f"skipped {len(skipped)}, failed {len(failed)}, timed out {len(timed_out)}")
    print(f"  throughput: {result['throughput_docs_per_min']} docs/min, "
          f"{result['throughput_mb_per_min']} MB/min")
    print(f"  queued->terminal latency (ms): {result['queued_to_terminal_latency_ms']}")
    return result, [o.doc_id for o in accepted]


# --------------------------------------------------------------------------- #
# Query phase
# --------------------------------------------------------------------------- #

def load_corpus_queries() -> Tuple[Optional[Path], Optional[str], List[str], List[str]]:
    """Reuse backend/tests/rag_eval's corpus + ground-truth queries.

    Returns (doc_path, content_type, [query strings], [notes]). Falls back to a
    single synthetic query against a synthetic doc if the eval harness isn't
    importable — that keeps this script runnable standalone, but the fallback
    is reported explicitly since it is not "the corpus".
    """
    notes: List[str] = []
    sys.path.insert(0, str(RAG_EVAL_DIR))
    try:
        from corpus import PRIMARY  # noqa: E402
        from queries import QUERIES  # noqa: E402  (back-compat alias for PRIMARY's set)

        path = PRIMARY.path("txt")
        if not path.exists():
            notes.append(f"corpus fixture missing on disk ({path}); falling back to synthetic query doc")
            return None, None, [], notes
        query_strings = [q["query"] for q in QUERIES]
        if not query_strings:
            notes.append("QUERIES set was empty; falling back to synthetic query doc")
            return None, None, [], notes
        return path, PRIMARY.ctype("txt"), query_strings, notes
    except ImportError as exc:
        notes.append(f"backend/tests/rag_eval not importable ({exc}); falling back to synthetic query doc")
        return None, None, [], notes


def phase_query(client: httpx.Client, cfg: Config) -> Tuple[Dict[str, Any], List[str]]:
    print(f"\n{'='*72}\n3. QUERY LATENCY ({cfg.num_queries} queries, "
          f"generate={cfg.query_generate})\n{'='*72}")
    if cfg.num_queries == 0:
        return {"skipped": True}, []

    created: List[str] = []
    path, ctype, query_pool, notes = load_corpus_queries()

    if path is None:
        # Fallback: ingest one synthetic doc so there is SOMETHING to retrieve.
        sentinel = uuid.uuid4().hex[:12]
        doc_id = f"perf-query-{sentinel}"
        content = synthetic_document(8 * 1024, sentinel)
        files = {"file": (f"perf_query_{sentinel}.txt", content, "text/plain")}
        r = client.post(f"{cfg.backend}/api/v1/rag/ingest", files=files, data={"doc_id": doc_id},
                         headers=cfg.headers, timeout=cfg.ingest_timeout)
        if r.status_code != 202:
            notes.append(f"fallback query-corpus ingest failed: HTTP {r.status_code}")
        else:
            created.append(r.json().get("doc_id", doc_id))
            await_terminal(client, cfg, created, cfg.ingest_timeout)
        query_pool = ["What is the torque specification for flange F-12?"]
    else:
        sentinel = uuid.uuid4().hex[:12]
        doc_id = f"perf-corpus-{sentinel}"
        content = path.read_bytes()
        files = {"file": (path.name, content, ctype)}
        r = client.post(f"{cfg.backend}/api/v1/rag/ingest", files=files, data={"doc_id": doc_id},
                         headers=cfg.headers, timeout=cfg.ingest_timeout)
        if r.status_code != 202:
            notes.append(f"corpus doc ingest failed: HTTP {r.status_code}: {r.text[:200]}")
        else:
            created.append(r.json().get("doc_id", doc_id))
            term = await_terminal(client, cfg, created, cfg.ingest_timeout)
            status = term.get(created[0], {}).get("status")
            if status != "indexed":
                notes.append(f"corpus doc did not reach 'indexed' (got {status!r}); "
                              f"query latency numbers below are still real HTTP timings, but "
                              f"retrieval may be hitting an empty/partial index")

    pool = itertools.cycle(query_pool)
    latencies: List[float] = []
    errors = 0
    used_context_count = 0

    def run_one(q: str) -> Tuple[float, Optional[int], Optional[bool]]:
        body = {"query": q, "generate": cfg.query_generate}
        t0 = time.time()
        try:
            r = client.post(f"{cfg.backend}/api/v1/rag/query", json=body,
                             headers=cfg.headers, timeout=cfg.query_timeout)
        except httpx.HTTPError:
            return time.time() - t0, None, None
        t1 = time.time()
        used_context = None
        if r.status_code == 200:
            used_context = bool(r.json().get("used_context"))
        return t1 - t0, r.status_code, used_context

    with ThreadPoolExecutor(max_workers=cfg.concurrency) as tp:
        futures = [tp.submit(run_one, next(pool)) for _ in range(cfg.num_queries)]
        for fut in as_completed(futures):
            dt, status, used_context = fut.result()
            latencies.append(dt)
            if status != 200:
                errors += 1
            if used_context:
                used_context_count += 1

    embed_probe = None
    if cfg.embed_probe:
        embed_probe = probe_embed_latency(cfg, next(pool))

    result = {
        "queries_run": cfg.num_queries,
        "errors": errors,
        "used_context_count": used_context_count,
        "latency_ms": stats_ms(latencies),
        "generate": cfg.query_generate,
        "auxiliary_embed_probe_ms": embed_probe,
        "notes": notes + [
            "The API returns only a final answer with no per-stage timings, so "
            "embed/Qdrant-search/rerank cannot be broken out of the latency above. "
            "auxiliary_embed_probe_ms (if present) times a DIRECT rag-inference /embed "
            "call — it is NOT a decomposition of latency_ms; treat it only as an "
            "independent lower-bound signal on the embed service's responsiveness.",
        ],
    }
    print(f"  queries run: {cfg.num_queries}, errors: {errors}, "
          f"used_context: {used_context_count}/{cfg.num_queries}")
    print(f"  query latency (ms): {result['latency_ms']}")
    if embed_probe is not None:
        print(f"  auxiliary embed-probe latency (ms, NOT a decomposition): {embed_probe}")
    else:
        print("  auxiliary embed probe: skipped or rag-inference unreachable")
    return result, created


def probe_embed_latency(cfg: Config, sample_text: str) -> Optional[Dict[str, Any]]:
    try:
        with httpx.Client() as c:
            times: List[float] = []
            for _ in range(cfg.embed_probe_count):
                t0 = time.time()
                r = c.post(f"{cfg.infer}/embed", json={"texts": [sample_text], "is_query": True}, timeout=30)
                if r.status_code == 200:
                    times.append(time.time() - t0)
    except httpx.HTTPError as exc:
        warn(f"embed probe skipped: rag-inference unreachable at {cfg.infer}: {exc}")
        return None
    if not times:
        warn("embed probe skipped: no successful /embed calls")
        return None
    return stats_ms(times)


# --------------------------------------------------------------------------- #
# Drain / backlog phase
# --------------------------------------------------------------------------- #

def phase_drain(client: httpx.Client, cfg: Config) -> Tuple[Dict[str, Any], List[str]]:
    print(f"\n{'='*72}\n4. WORKER DRAIN RATE UNDER BACKLOG ({cfg.drain_docs} docs)\n{'='*72}")
    if cfg.drain_docs == 0:
        return {"skipped": True}, []

    size_bytes = cfg.doc_size_kb * 1024
    t_backlog_start = time.time()
    outcomes: List[IngestOutcome] = []
    with ThreadPoolExecutor(max_workers=cfg.concurrency) as pool:
        futures = [pool.submit(ingest_one, client, cfg, size_bytes) for _ in range(cfg.drain_docs)]
        for fut in as_completed(futures):
            outcomes.append(fut.result())
    t_backlog_loaded = time.time()  # full backlog now exists in rag_documents

    accepted = [o for o in outcomes if o.accepted]
    rejected = len(outcomes) - len(accepted)
    if rejected:
        warn(f"{rejected}/{len(outcomes)} backlog submissions were not accepted")

    term = await_terminal(client, cfg, [o.doc_id for o in accepted], cfg.drain_timeout)
    t_drain_end = max([v["t_terminal"] for v in term.values() if v.get("t_terminal")],
                       default=time.time())

    by_id = {o.doc_id: o for o in accepted}
    latencies = []
    for doc_id, v in term.items():
        if v.get("t_terminal") is None:
            continue
        o = by_id.get(doc_id)
        if o and o.t_accept is not None:
            latencies.append(v["t_terminal"] - o.t_accept)

    terminal_ok = sum(1 for v in term.values() if v.get("status") in ("indexed", "skipped"))
    timed_out = sum(1 for v in term.values() if v.get("status") == "timeout")
    drain_wall = max(t_drain_end - t_backlog_loaded, 1e-9)

    result = {
        "backlog_docs": len(outcomes),
        "docs_accepted": len(accepted),
        "docs_drained": terminal_ok,
        "docs_timed_out": timed_out,
        "submit_wall_seconds": round(t_backlog_loaded - t_backlog_start, 2),
        "drain_wall_seconds": round(drain_wall, 2),
        "drain_throughput_docs_per_min": round(terminal_ok / (drain_wall / 60.0), 2),
        "queued_to_terminal_latency_ms": stats_ms(latencies),
        "note": "drain_wall_seconds is measured from when the FULL backlog was already queued "
                "(t_backlog_loaded), not from the first submission — it isolates worker drain "
                "speed from client-side submission speed.",
    }
    print(f"  accepted {len(accepted)}/{len(outcomes)}, drained {terminal_ok}, timed out {timed_out}")
    print(f"  submit wall: {result['submit_wall_seconds']}s, drain wall: {result['drain_wall_seconds']}s")
    print(f"  drain throughput: {result['drain_throughput_docs_per_min']} docs/min")
    print(f"  queued->terminal latency under backlog (ms): {result['queued_to_terminal_latency_ms']}")
    return result, [o.doc_id for o in accepted]


# --------------------------------------------------------------------------- #
# Quota-check overhead (best-effort proxy — see module docstring item 5)
# --------------------------------------------------------------------------- #

def phase_quota(client: httpx.Client, cfg: Config, ingest_result: Dict[str, Any]) -> Dict[str, Any]:
    print(f"\n{'='*72}\n5. QUOTA-CHECK OVERHEAD (best-effort proxy)\n{'='*72}")
    n = 10
    times = []
    for _ in range(n):
        t0 = time.time()
        try:
            r = client.get(f"{cfg.backend}/api/v1/rag/documents", headers=cfg.headers, timeout=30)
        except httpx.HTTPError:
            continue
        if r.status_code == 200:
            times.append(time.time() - t0)

    accept_latency = (ingest_result or {}).get("accept_latency_ms")
    result = {
        "isolated_measurement_possible": False,
        "reason": (
            "check_ingest_quota() runs ONE aggregate query (rag_index_queue.quota_usage) "
            "inside the /ingest handler, but nothing over HTTP separates that query's time "
            "from the S3 put and row upsert that happen in the same request. Isolating it "
            "precisely needs server-side instrumentation (a timing log around "
            "check_ingest_quota) or an EXPLAIN ANALYZE on the aggregate query directly "
            "against rag_documents — neither is available from this black-box HTTP driver."
        ),
        "proxy_get_documents_latency_ms": stats_ms(times),
        "proxy_get_documents_note": (
            "GET /documents also calls quota_usage() (the same aggregate query), but "
            "ALSO calls list_documents() (an S3 listing) and list_for_org() (a second, "
            "different query) in the same request — so this is an upper bound on three "
            "operations combined, not the quota query alone."
        ),
        "proxy_ingest_accept_latency_ms": accept_latency,
        "proxy_ingest_accept_note": (
            "accept_latency_ms from the ingest phase (time to 202) also includes the quota "
            "check, but additionally includes the multipart upload transfer, the blob PUT, "
            "and the rag_documents row upsert — also not isolated."
        ) if accept_latency else "ingest phase was skipped; no accept-latency proxy available.",
    }
    print("  cannot isolate the quota query alone over HTTP (see 'reason' in JSON output)")
    print(f"  proxy: GET /documents latency (ms, includes quota query + S3 list + registry "
          f"query): {result['proxy_get_documents_latency_ms']}")
    return result


# --------------------------------------------------------------------------- #
# Cleanup
# --------------------------------------------------------------------------- #

def cleanup(client: httpx.Client, cfg: Config, doc_ids: List[str]) -> Dict[str, Any]:
    print(f"\n{'='*72}\nCLEANUP ({len(doc_ids)} documents created by this run)\n{'='*72}")
    if cfg.no_cleanup:
        print(f"  {YEL}--no-cleanup set — leaving {len(doc_ids)} documents in place{RST}")
        return {"attempted": 0, "deleted": 0, "failed": []}
    deleted, failed = [], []
    for doc_id in doc_ids:
        try:
            r = client.delete(f"{cfg.backend}/api/v1/rag/documents/{doc_id}",
                               headers=cfg.headers, timeout=60)
            if r.status_code == 200:
                deleted.append(doc_id)
            else:
                failed.append({"doc_id": doc_id, "error": f"HTTP {r.status_code}: {r.text[:150]}"})
        except httpx.HTTPError as exc:
            failed.append({"doc_id": doc_id, "error": str(exc)})
    print(f"  deleted {len(deleted)}/{len(doc_ids)}")
    if failed:
        print(f"  {RED}FAILED TO DELETE {len(failed)} document(s) — clean these up manually:{RST}")
        for f in failed:
            print(f"    {f['doc_id']}: {f['error']}")
    return {"attempted": len(doc_ids), "deleted": len(deleted), "failed": failed}


# --------------------------------------------------------------------------- #
# Run metadata
# --------------------------------------------------------------------------- #

def git_sha() -> Optional[str]:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO_ROOT,
                              capture_output=True, text=True, timeout=5)
        return out.stdout.strip() if out.returncode == 0 else None
    except Exception:
        return None


def run_metadata(cfg: Config, health: Dict[str, Any]) -> Dict[str, Any]:
    inference = health.get("inference") or {}
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "host": socket.gethostname(),
        "python": platform.python_version(),
        "git_sha": git_sha(),
        "backend_url": cfg.backend,
        "settings": {
            "embedding_model": inference.get("embedding_model"),
            "reranker_model": inference.get("reranker_model"),
            "device": inference.get("device"),
            "fp16": inference.get("fp16"),
            "RAG_EMBED_BATCH": os.environ.get("RAG_EMBED_BATCH", "32 (default; not set in this "
                                               "process's environment — the backend's actual "
                                               "value may differ)"),
        },
        "args": {
            "num_docs": cfg.num_docs, "doc_size_kb": cfg.doc_size_kb,
            "num_queries": cfg.num_queries, "concurrency": cfg.concurrency,
            "drain_docs": cfg.drain_docs, "query_generate": cfg.query_generate,
        },
    }


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #

def render_table(meta: Dict[str, Any], results: Dict[str, Any]) -> str:
    lines = []
    lines.append("RAG PERFORMANCE RUN")
    lines.append(f"  timestamp   {meta['timestamp']}")
    lines.append(f"  host        {meta['host']}")
    lines.append(f"  git_sha     {meta['git_sha'] or 'unknown'}")
    lines.append(f"  backend     {meta['backend_url']}")
    s = meta["settings"]
    lines.append(f"  embedder    {s['embedding_model']}  reranker  {s['reranker_model']}  device  {s['device']}")
    lines.append(f"  RAG_EMBED_BATCH  {s['RAG_EMBED_BATCH']}")

    def section(title: str, block: Dict[str, Any]):
        lines.append(f"\n-- {title} " + "-" * max(1, 60 - len(title)))
        if block.get("skipped"):
            lines.append("  (skipped)")
            return
        for k, v in block.items():
            if k == "note" or k == "notes":
                continue
            lines.append(f"  {k:32s} {v}")
        for note_key in ("note", "notes"):
            if note_key in block:
                notes = block[note_key] if isinstance(block[note_key], list) else [block[note_key]]
                for n in notes:
                    lines.append(f"  {DIM}note: {n}{RST}")

    section("1+2. INGEST throughput + latency", results.get("ingest", {}))
    section("3. QUERY latency", results.get("query", {}))
    section("4. DRAIN under backlog", results.get("drain", {}))
    section("5. QUOTA-check overhead", results.get("quota", {}))
    section("CLEANUP", results.get("cleanup", {}))
    return "\n".join(lines)


def render_json(meta: Dict[str, Any], results: Dict[str, Any]) -> str:
    return json.dumps({"run": meta, **results}, indent=2, default=str)


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #

def main() -> None:
    args = build_arg_parser().parse_args()
    cfg = make_config(args)

    print(f"RAG perf driver\n  backend={cfg.backend}  infer={cfg.infer}")
    health = preflight(cfg)

    created_doc_ids: List[str] = []
    results: Dict[str, Any] = {}

    with httpx.Client() as client:
        if not cfg.skip_ingest:
            ingest_result, ids = phase_ingest(client, cfg)
            results["ingest"] = ingest_result
            created_doc_ids += ids
        else:
            results["ingest"] = {"skipped": True}

        if not cfg.skip_query:
            query_result, ids = phase_query(client, cfg)
            results["query"] = query_result
            created_doc_ids += ids
        else:
            results["query"] = {"skipped": True}

        if not cfg.skip_drain:
            drain_result, ids = phase_drain(client, cfg)
            results["drain"] = drain_result
            created_doc_ids += ids
        else:
            results["drain"] = {"skipped": True}

        if not cfg.skip_quota:
            results["quota"] = phase_quota(client, cfg, results.get("ingest", {}))
        else:
            results["quota"] = {"skipped": True}

        results["cleanup"] = cleanup(client, cfg, created_doc_ids)

    meta = run_metadata(cfg, health)
    output = render_json(meta, results) if cfg.as_json else render_table(meta, results)

    if cfg.output:
        Path(cfg.output).write_text(output, encoding="utf-8")
        print(f"\nwrote {'JSON' if cfg.as_json else 'table'} output to {cfg.output}")
    else:
        print(f"\n{output}")

    any_delete_failed = bool(results.get("cleanup", {}).get("failed"))
    sys.exit(1 if any_delete_failed else 0)


if __name__ == "__main__":
    main()
