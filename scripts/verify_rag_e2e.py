#!/usr/bin/env python3
"""
RAG end-to-end data-plane verification.

Unlike the /health endpoint (which only proves services are *reachable*), this
script proves data actually lands correctly in every store by inspecting each
data plane DIRECTLY, not through the backend:

  1. Preflight  - backend, rag-inference (models loaded), Qdrant, SeaweedFS up
  2. BGE        - call rag-inference /embed directly; assert dense[1024]+sparse
  3. Ingest     - POST a document through the backend API (202), then poll
                  /documents/{doc_id}/status until the worker finishes
  4. SeaweedFS  - boto3 HEAD+GET the blob at the expected key; assert bytes match
  5. Qdrant     - REST scroll by doc_id; assert points exist with a real 1024-d
                  dense vector (non-zero) + non-empty sparse + correct payload
  6. Retrieval  - POST /query (generate=false); assert our doc is the top hit
  7. Generation - POST /query (generate=true) IF Ollama is up (else skipped)
  8. Cleanup    - DELETE the doc; assert it is gone from BOTH Qdrant and SeaweedFS

Run from the host after `docker compose up qdrant seaweedfs rag-inference backend`.
Requires: httpx, boto3  (pip install httpx boto3)

Endpoints default to the compose host port mappings; override via env:
  BACKEND_URL (8000)  QDRANT_URL (6333)  S3_ENDPOINT (8333)  INFER_URL (8001)
"""

import os
import sys
import time
import uuid

import httpx

try:
    import boto3
    from botocore.config import Config
    from botocore.exceptions import ClientError
except ImportError:
    print("FATAL: boto3 required -> pip install boto3", file=sys.stderr)
    sys.exit(2)

BACKEND = os.getenv("BACKEND_URL", "http://localhost:8000")
QDRANT = os.getenv("QDRANT_URL", "http://localhost:6333")
S3_ENDPOINT = os.getenv("S3_ENDPOINT", "http://localhost:8333")
INFER = os.getenv("INFER_URL", "http://localhost:8001")
OLLAMA = os.getenv("OLLAMA_URL", "http://localhost:11434")

S3_KEY, S3_SECRET = "omniusgrid", "omniusgrid_dev_secret"
RAW_BUCKET = "raw-documents"
COLLECTION = "documents"
EMBED_DIM = 1024
DEV_TOKEN = "dev-token"  # backend auth.py creates a dev org/user for this token

GREEN, RED, YEL, RST = "\033[92m", "\033[91m", "\033[93m", "\033[0m"
_failures = 0


def ok(msg): print(f"  {GREEN}PASS{RST} {msg}")
def info(msg): print(f"  {YEL}··{RST}   {msg}")


def check(name, cond, detail=""):
    global _failures
    if cond:
        ok(name + (f"  {detail}" if detail else ""))
    else:
        print(f"  {RED}FAIL{RST} {name}  {detail}")
        _failures += 1
    return cond


def die(msg):
    print(f"{RED}ABORT:{RST} {msg}", file=sys.stderr)
    sys.exit(1)


def s3_client():
    return boto3.client(
        "s3",
        endpoint_url=S3_ENDPOINT,
        aws_access_key_id=S3_KEY,
        aws_secret_access_key=S3_SECRET,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, signature_version="s3v4"),
    )


def wait_for(name, fn, timeout=120, interval=3):
    """Poll fn() until it returns truthy or timeout. Returns the last value."""
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            val = fn()
            if val:
                return val
        except Exception:
            pass
        time.sleep(interval)
    return None


# --------------------------------------------------------------------------- #
def preflight():
    print(f"\n{'='*66}\n1. PREFLIGHT\n{'='*66}")

    be = wait_for("backend", lambda: httpx.get(f"{BACKEND}/health/live", timeout=5).status_code == 200)
    if not check("backend reachable", be):
        die("backend not up - `docker compose up backend` (and its deps)")

    def infer_ready():
        r = httpx.get(f"{INFER}/health", timeout=5)
        return r.status_code == 200 and r.json().get("models_loaded") is True
    info("waiting for rag-inference to load BGE weights (first run downloads ~5GB)...")
    ready = wait_for("infer", infer_ready, timeout=1800, interval=10)
    if not check("rag-inference models loaded", ready):
        die("rag-inference not ready - check `docker compose logs rag-inference`")

    qd = wait_for("qdrant", lambda: httpx.get(f"{QDRANT}/readyz", timeout=5).status_code == 200)
    check("qdrant ready", qd)

    def s3_up():
        try:
            s3_client().list_buckets(); return True
        except Exception:
            return False
    check("seaweedfs S3 reachable", wait_for("s3", s3_up))


def test_bge_direct():
    print(f"\n{'='*66}\n2. BGE (direct to rag-inference)\n{'='*66}")
    r = httpx.post(f"{INFER}/embed",
                   json={"texts": ["boiler pressure reading nominal"], "is_query": False},
                   timeout=60)
    check("POST /embed 200", r.status_code == 200, f"(status {r.status_code})")
    data = r.json()
    dense = data["dense"][0]
    sparse = data["sparse"][0]
    check("dense vector is 1024-d", len(dense) == EMBED_DIM, f"(got {len(dense)})")
    check("dense vector is non-zero", any(abs(x) > 1e-9 for x in dense))
    check("sparse vector non-empty", len(sparse["indices"]) > 0 and len(sparse["values"]) > 0,
          f"({len(sparse['indices'])} terms)")
    check("sparse indices/values aligned", len(sparse["indices"]) == len(sparse["values"]))


def ingest_document(headers):
    print(f"\n{'='*66}\n3. INGEST (through backend API)\n{'='*66}")
    sentinel = uuid.uuid4().hex[:8]
    # Distinctive content so retrieval is unambiguously verifiable.
    body = (
        f"OmniusGrid compliance test document {sentinel}. "
        "The emergency shutdown procedure for reactor unit R-7 requires two "
        "independent operators to confirm the interlock before venting. "
        "Torque specification for flange F-12 is 240 newton meters. "
    ) * 40
    content = body.encode()
    files = {"file": (f"compliance_{sentinel}.txt", content, "text/plain")}
    r = httpx.post(f"{BACKEND}/api/v1/rag/ingest", files=files, headers=headers, timeout=120)
    if not check("POST /ingest 202", r.status_code == 202, f"(status {r.status_code}: {r.text[:200]})"):
        die("ingest failed")
    accepted = r.json()
    check("stored=true", accepted.get("stored") is True)
    check("status=queued", accepted.get("status") == "queued")

    # Indexing is asynchronous now: poll until the worker reaches a terminal state.
    doc_id = accepted["doc_id"]
    deadline = time.monotonic() + 300
    res = {}
    while time.monotonic() < deadline:
        s = httpx.get(
            f"{BACKEND}/api/v1/rag/documents/{doc_id}/status",
            headers=headers, timeout=30,
        )
        if s.status_code == 200:
            res = s.json()
            if res.get("status") in ("indexed", "skipped", "failed"):
                break
        time.sleep(2)
    else:
        die("indexing did not finish within 300s")

    check("indexed", res.get("status") == "indexed",
          f"(status {res.get('status')}, reason: {res.get('reason')}, error: {res.get('error')})")
    check("chunks written > 0", res.get("num_chunks", 0) > 0, f"({res.get('num_chunks')} chunks)")
    res["s3_key"] = accepted["s3_key"]
    res["doc_id"] = doc_id
    return res, content, sentinel


def verify_seaweedfs(res, content):
    print(f"\n{'='*66}\n4. SEAWEEDFS (direct S3 inspection)\n{'='*66}")
    key = res["s3_key"]
    info(f"expected key: {RAW_BUCKET}/{key}")
    s3 = s3_client()
    try:
        head = s3.head_object(Bucket=RAW_BUCKET, Key=key)
    except ClientError as e:
        check("blob exists in SeaweedFS (HEAD)", False, str(e)); return
    check("blob exists in SeaweedFS (HEAD)", True)
    check("stored size == uploaded size", head["ContentLength"] == len(content),
          f"({head['ContentLength']} vs {len(content)})")
    got = s3.get_object(Bucket=RAW_BUCKET, Key=key)["Body"].read()
    check("stored bytes == uploaded bytes (exact)", got == content)
    # Prove tenant-scoped key layout: {org_id}/{doc_id}/{filename}
    parts = key.split("/")
    check("key is org/doc/filename scoped", len(parts) == 3 and parts[1] == res["doc_id"],
          f"(parts={parts})")


def verify_qdrant(res):
    print(f"\n{'='*66}\n5. QDRANT (direct REST inspection)\n{'='*66}")
    doc_id = res["doc_id"]
    # Scroll points filtered by our doc_id, WITH vectors, so we can inspect them.
    r = httpx.post(
        f"{QDRANT}/collections/{COLLECTION}/points/scroll",
        json={
            "filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]},
            "limit": 100, "with_payload": True, "with_vector": True,
        },
        timeout=30,
    )
    if not check("Qdrant scroll 200", r.status_code == 200, f"(status {r.status_code}: {r.text[:200]})"):
        return
    points = r.json()["result"]["points"]
    check("points exist for doc_id", len(points) > 0, f"({len(points)} points)")
    check("point count == chunks reported", len(points) == res["num_chunks"],
          f"({len(points)} vs {res['num_chunks']})")
    if not points:
        return
    p = points[0]
    vec = p["vector"]
    dense = vec.get("dense")
    sparse = vec.get("sparse")
    check("named dense vector present & 1024-d", dense is not None and len(dense) == EMBED_DIM,
          f"(len {len(dense) if dense else 'None'})")
    check("dense vector is real (non-zero)", dense and any(abs(x) > 1e-9 for x in dense))
    check("named sparse vector present & non-empty",
          sparse is not None and len(sparse.get("indices", [])) > 0)
    pl = p["payload"]
    for field in ("doc_id", "chunk_id", "org_id", "s3_key", "filename", "text", "source_type"):
        check(f"payload has '{field}'", field in pl and pl[field] not in (None, ""))
    check("payload.s3_key matches stored blob", pl.get("s3_key") == res["s3_key"])
    check("payload.text is non-empty chunk text", len(pl.get("text", "")) > 0,
          f"({len(pl.get('text',''))} chars)")


def verify_retrieval(headers, res, sentinel):
    print(f"\n{'='*66}\n6. RETRIEVAL (generate=false, no LLM)\n{'='*66}")
    q = {"query": "What is the torque specification for flange F-12?",
         "top_n": 5, "generate": False}
    r = httpx.post(f"{BACKEND}/api/v1/rag/query", json=q, headers=headers, timeout=60)
    if not check("POST /query 200", r.status_code == 200, f"(status {r.status_code}: {r.text[:200]})"):
        return
    ans = r.json()
    check("used_context=true", ans.get("used_context") is True)
    check("generated=false (no LLM used)", ans.get("generated") is False)
    cites = ans.get("citations", [])
    check("citations returned", len(cites) > 0, f"({len(cites)} citations)")
    if cites:
        top = cites[0]
        check("top citation is our document", top.get("doc_id") == res["doc_id"],
              f"(got {top.get('doc_id')})")
        check("citation carries s3_key + score + snippet",
              top.get("s3_key") and "score" in top and top.get("snippet"))


def verify_generation(headers):
    print(f"\n{'='*66}\n7. GENERATION (generate=true, needs Ollama)\n{'='*66}")
    try:
        up = httpx.get(f"{OLLAMA}/api/tags", timeout=3).status_code == 200
    except Exception:
        up = False
    if not up:
        info("Ollama not reachable on host - SKIPPING generation "
             "(run `ollama serve` + `ollama pull gemma2:2b` to enable)")
        return
    q = {"query": "What is the torque specification for flange F-12?", "generate": True}
    r = httpx.post(f"{BACKEND}/api/v1/rag/query", json=q, headers=headers, timeout=180)
    if not check("POST /query (generate) 200", r.status_code == 200, f"(status {r.status_code})"):
        return
    ans = r.json()
    check("generated=true", ans.get("generated") is True)
    check("answer text returned", bool(ans.get("answer")), f"(len {len(ans.get('answer') or '')})")
    info(f"answer: {(ans.get('answer') or '')[:160]}...")


def verify_cleanup(headers, res):
    print(f"\n{'='*66}\n8. CLEANUP (delete removes from BOTH planes)\n{'='*66}")
    doc_id, key = res["doc_id"], res["s3_key"]
    r = httpx.delete(f"{BACKEND}/api/v1/rag/documents/{doc_id}", headers=headers, timeout=60)
    check("DELETE 200", r.status_code == 200, f"(status {r.status_code})")

    scroll = httpx.post(
        f"{QDRANT}/collections/{COLLECTION}/points/scroll",
        json={"filter": {"must": [{"key": "doc_id", "match": {"value": doc_id}}]}, "limit": 10},
        timeout=30,
    ).json()["result"]["points"]
    check("Qdrant points gone after delete", len(scroll) == 0, f"({len(scroll)} remain)")

    try:
        s3_client().head_object(Bucket=RAW_BUCKET, Key=key)
        check("SeaweedFS blob gone after delete", False, "(still present)")
    except ClientError:
        check("SeaweedFS blob gone after delete", True)


def main():
    print(f"RAG E2E verification\n  backend={BACKEND}  qdrant={QDRANT}\n"
          f"  s3={S3_ENDPOINT}  infer={INFER}")
    headers = {"Authorization": f"Bearer {DEV_TOKEN}"}
    preflight()
    test_bge_direct()
    res, content, sentinel = ingest_document(headers)
    verify_seaweedfs(res, content)
    verify_qdrant(res)
    verify_retrieval(headers, res, sentinel)
    verify_generation(headers)
    verify_cleanup(headers, res)

    print(f"\n{'='*66}")
    if _failures == 0:
        print(f"{GREEN}ALL DATA-PLANE CHECKS PASSED{RST} - "
              "SeaweedFS, Qdrant, and BGE verified end to end.")
        sys.exit(0)
    print(f"{RED}{_failures} CHECK(S) FAILED{RST}")
    sys.exit(1)


if __name__ == "__main__":
    main()
