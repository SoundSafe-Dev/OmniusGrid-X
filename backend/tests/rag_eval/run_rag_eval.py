#!/usr/bin/env python3
"""
RAG evaluation harness — SOP-QA-014 across document formats.

Funnels the SAME source document (SOP-QA-014, Allergen Control & Sanitation) in
five formats — pdf, docx, md, txt, csv — through the live RAG API and checks two
things at once:

  1. MECHANICS (architecture soundness): each format ingests, parses to blocks,
     chunks, and vector-indexes (stored=true, indexed=true, num_chunks>0).
  2. CORRECTNESS (query output): a fixed suite of ground-truth questions
     (see queries.py) returns the right facts — including the hard cases:
     near-duplicate numbers, table-row integrity, definition-vs-usage,
     revision lookups, and the two negative tests (out-of-corpus + scope
     boundary) that a compliance product must NOT fabricate through.

Design: each format is tested IN ISOLATION (wipe -> ingest one format -> query
-> wipe) so a pass/fail is attributable to that format's parser + how its tables
survive chunking. A final optional --combined phase funnels all five at once to
check cross-format robustness (near-duplicate passages, dedup) — that phase is
informational and not counted toward the pass/fail gate.

Zero third-party deps (stdlib urllib only) so it runs under any Python 3.7+.

Auth: pass --token, or --email/--password (defaults to the seeded dev user), or
set RAG_TEST_TOKEN / RAG_TEST_EMAIL / RAG_TEST_PASSWORD.

Usage:
  python3 backend/tests/rag_eval/run_rag_eval.py
  python3 backend/tests/rag_eval/run_rag_eval.py --combined
  python3 backend/tests/rag_eval/run_rag_eval.py --formats md,csv --email me@x.com --password ...

Exit code is non-zero if any non-manual assertion fails (CI-friendly).
"""

import argparse
import json
import mimetypes
import os
import sys
import time
import uuid
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from queries import QUERY_SETS  # noqa: E402
from corpus import DOC_BY_ID, PRIMARY  # noqa: E402

HERE = Path(__file__).resolve().parent
DOCS_DIR = HERE.parent / "docs"
REPORTS_DIR = HERE / "reports"

# These describe the ACTIVE document and are (re)bound in main() from --doc. They
# default to the primary corpus document so importing this module still works.
DOC = PRIMARY
BASENAME = PRIMARY.basename
FORMATS = {f: PRIMARY.file(f) for f in PRIMARY.formats}
QUERIES = QUERY_SETS[PRIMARY.id]

GREEN, RED, YEL, GREY, BOLD, RST = "\033[32m", "\033[31m", "\033[33m", "\033[90m", "\033[1m", "\033[0m"


def c(txt, color):
    return f"{color}{txt}{RST}" if sys.stdout.isatty() else str(txt)


# --------------------------------------------------------------------------- #
# Minimal HTTP client (stdlib only)
# --------------------------------------------------------------------------- #
class ApiError(Exception):
    def __init__(self, status, body):
        self.status, self.body = status, body
        super().__init__(f"HTTP {status}: {body[:400]}")


def _do(method, url, headers=None, data=None):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=180) as resp:
            raw = resp.read().decode("utf-8", "replace")
            return resp.status, raw
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", "replace"))
    except urllib.error.URLError as e:
        raise ApiError(0, f"connection error: {e.reason}")


def _json(method, url, token=None, body=None):
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = None
    if body is not None:
        data = json.dumps(body).encode()
        headers["Content-Type"] = "application/json"
    status, raw = _do(method, url, headers, data)
    return status, (json.loads(raw) if raw else {})


def login(base, email, password):
    """OAuth2 password grant -> access token."""
    form = urllib.parse.urlencode({"username": email, "password": password}).encode()
    headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
    status, raw = _do("POST", f"{base}/api/v1/auth/login", headers, form)
    return json.loads(raw)["access_token"]


def _multipart(fields, file_field, filename, file_bytes, content_type):
    """Build a multipart/form-data body (bytes) and its boundary."""
    boundary = f"----ragEval{uuid.uuid4().hex}"
    parts = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(f"{value}\r\n".encode())
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(
        f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode()
    )
    parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), boundary


def ingest(base, token, path, content_type, doc_id):
    body, boundary = _multipart(
        {"doc_id": doc_id}, "file", path.name, path.read_bytes(), content_type
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": f"multipart/form-data; boundary={boundary}",
    }
    status, raw = _do("POST", f"{base}/api/v1/rag/ingest", headers, body)
    return json.loads(raw)


def query(base, token, q, generate, top_n=None):
    body = {"query": q, "generate": generate}
    if top_n:
        body["top_n"] = top_n
    _, resp = _json("POST", f"{base}/api/v1/rag/query", token, body)
    return resp


def list_doc_ids(base, token):
    try:
        _, resp = _json("GET", f"{base}/api/v1/rag/documents", token)
    except ApiError as e:
        # Fresh SeaweedFS: the bucket doesn't exist until the first ingest, and
        # the list endpoint currently 500s on NoSuchBucket instead of returning
        # empty. Treat "no bucket yet" as "nothing to wipe".
        if e.status in (500, 404, 503):
            return set()
        raise
    ids = set()
    for key in resp.get("keys", []):
        parts = key.split("/")
        if len(parts) >= 2:
            ids.add(parts[1])  # {org_id}/{doc_id}/{filename}
    return ids


def delete_doc(base, token, doc_id):
    _json("DELETE", f"{base}/api/v1/rag/documents/{urllib.parse.quote(doc_id)}", token)


def wipe_all(base, token):
    n = 0
    for doc_id in list_doc_ids(base, token):
        try:
            delete_doc(base, token, doc_id)
            n += 1
        except ApiError:
            pass
    return n


# --------------------------------------------------------------------------- #
# Assertion engine
# --------------------------------------------------------------------------- #
def _haystack(resp, generate):
    """Text to assert against: the answer for synthesis, snippets otherwise.

    For retrieval-only we also fold in each citation's ``source`` metadata (page
    / section / heading), so a structured format's heading like "6.6
    Post-Sanitation Verification" counts as evidence the right region was
    retrieved even when the chunk's 240-char preview truncates the key fact.
    """
    cits = resp.get("citations", [])
    parts = []
    for ct in cits:
        parts.append(ct.get("snippet", "") or "")
        src = ct.get("source", {})
        if isinstance(src, dict):
            parts.append(" ".join(str(v) for v in src.values()))
    retrieval_text = " \n ".join(parts)
    if generate and resp.get("answer"):
        return resp["answer"], retrieval_text
    return retrieval_text, retrieval_text  # retrieval-only: answer is None


def evaluate(spec, resp):
    """Return (passed, detail) for one query response."""
    answer_text, snippets = _haystack(resp, spec["generate"])
    hay = answer_text.lower()
    forbid_hay = (answer_text if spec["generate"] else snippets).lower()

    matched, missing = [], []
    for grp in spec["concepts"]:
        hit = next((s for s in grp["any"] if s.lower() in hay), None)
        (matched if hit else missing).append(grp["name"])

    # Bonus concepts are reported for completeness but never gate the verdict.
    bonus_matched, bonus_missing = [], []
    for grp in spec.get("bonus", []):
        hit = next((s for s in grp["any"] if s.lower() in hay), None)
        (bonus_matched if hit else bonus_missing).append(grp["name"])

    forbidden_hits = [f for f in spec.get("forbid", []) if f.lower() in forbid_hay]

    passed = not missing and not forbidden_hits
    detail = {
        "matched": matched,
        "missing": missing,
        "bonus_matched": bonus_matched,
        "bonus_missing": bonus_missing,
        "forbidden_hits": forbidden_hits,
        "num_citations": len(resp.get("citations", [])),
        "top_score": round(resp.get("citations", [{}])[0].get("score", 0.0), 3)
        if resp.get("citations") else None,
        "generated": resp.get("generated"),
        "used_context": resp.get("used_context"),
        "answer": resp.get("answer"),
        "citations": [
            {
                "filename": ct.get("filename"),
                "source": ct.get("source"),
                "score": round(ct.get("score", 0.0), 3),
                "snippet": (ct.get("snippet") or "")[:220],
            }
            for ct in resp.get("citations", [])[:4]
        ],
    }
    return passed, detail


# --------------------------------------------------------------------------- #
# Runner
# --------------------------------------------------------------------------- #
def run_query_suite(base, token, llm_available, top_n):
    """Run every query once against whatever is currently indexed."""
    results = {}
    for spec in QUERIES:
        if spec["generate"] and not llm_available:
            results[spec["id"]] = (None, {"skipped": "LLM unavailable"})
            continue
        try:
            resp = query(base, token, spec["query"], spec["generate"],
                         spec.get("top_n", top_n))
        except ApiError as e:
            results[spec["id"]] = (False, {"error": str(e)})
            continue
        results[spec["id"]] = evaluate(spec, resp)
    return results


def check_mechanics(ing, fmt):
    """Assert ingestion mechanics for one format. Returns (ok, problems)."""
    problems = []
    if not ing.get("stored"):
        problems.append("not stored")
    if not ing.get("indexed"):
        problems.append(f"not indexed (reason: {ing.get('reason')})")
    if ing.get("kind") not in ("pdf", "docx", "text", "markdown", "csv"):
        problems.append(f"unexpected kind={ing.get('kind')}")
    if ing.get("num_blocks", 0) < 1:
        problems.append("0 blocks parsed")
    if ing.get("num_chunks", 0) < 1:
        problems.append("0 chunks indexed")
    return (not problems), problems


def status_cell(res):
    if res is None:
        return c("SKIP", GREY)
    passed, detail = res
    if passed is None:
        return c("n/a", GREY)
    if "error" in detail:
        return c("ERR", RED)
    return c("PASS", GREEN) if passed else c("FAIL", RED)


def main():
    ap = argparse.ArgumentParser(description="RAG eval harness — matrix report for one corpus document.")
    ap.add_argument("--doc", default=PRIMARY.id,
                    help=f"corpus document id to evaluate (default {PRIMARY.id}); "
                         f"choices: {', '.join(DOC_BY_ID)}")
    ap.add_argument("--base-url", default=os.environ.get("RAG_BASE_URL", "http://localhost:8000"))
    ap.add_argument("--token", default=os.environ.get("RAG_TEST_TOKEN"),
                    help="bearer token; defaults to the 'dev-token' bypass (needs ALLOW_DEV_TOKEN)")
    ap.add_argument("--email", default=os.environ.get("RAG_TEST_EMAIL"),
                    help="login email (used only if --token not given and --password is set)")
    ap.add_argument("--password", default=os.environ.get("RAG_TEST_PASSWORD"))
    ap.add_argument("--formats", default="pdf,docx,md,txt,csv",
                    help="comma-separated subset of: pdf,docx,md,txt,csv")
    ap.add_argument("--top-n", type=int, default=None)
    ap.add_argument("--combined", action="store_true",
                    help="also run an all-formats-at-once phase (informational)")
    ap.add_argument("--no-cleanup", action="store_true", help="leave docs indexed at the end")
    args = ap.parse_args()

    # Bind the active document: rebind the module globals the phases read from.
    if args.doc not in DOC_BY_ID:
        print(f"unknown --doc {args.doc!r}; choices: {', '.join(DOC_BY_ID)}", file=sys.stderr)
        return 2
    global DOC, BASENAME, FORMATS, QUERIES
    DOC = DOC_BY_ID[args.doc]
    BASENAME = DOC.basename
    FORMATS = {f: DOC.file(f) for f in DOC.formats}
    QUERIES = QUERY_SETS[DOC.id]

    base = args.base_url.rstrip("/")
    fmts = [f.strip() for f in args.formats.split(",") if f.strip()]
    for f in fmts:
        if f not in FORMATS:
            print(f"unknown format: {f}", file=sys.stderr)
            return 2
        if not (DOCS_DIR / FORMATS[f][0]).exists():
            print(f"missing corpus file: {DOCS_DIR / FORMATS[f][0]}", file=sys.stderr)
            return 2

    run_id = uuid.uuid4().hex[:8]
    started = datetime.now(timezone.utc)
    print(c(f"\n=== RAG eval  [{DOC.id}]  (run {run_id})  {base}  ===", BOLD))

    # --- auth --- token > email/password login > dev-token bypass (default)
    token = args.token
    if not token and args.email and args.password:
        try:
            token = login(base, args.email, args.password)
            print(f"authenticated as {args.email}")
        except ApiError as e:
            print(c(f"LOGIN FAILED ({e}). Pass --token or valid --email/--password.", RED))
            return 2
    if not token:
        token = "dev-token"  # ALLOW_DEV_TOKEN self-provisions the dev org+user
        print("using dev-token bypass (ALLOW_DEV_TOKEN)")

    # --- preflight: RAG health / LLM availability ---
    llm_available = True
    try:
        _, health = _json("GET", f"{base}/api/v1/rag/health", token)
        llm = health.get("llm", health.get("generator", {}))
        llm_available = bool(llm.get("available", True)) if isinstance(llm, dict) else True
        print(f"rag health: vectors={health.get('vector_store', health.get('vectors'))} "
              f"llm_available={llm_available}")
        if not llm_available:
            gen_ids = ", ".join(q["id"] for q in QUERIES if q["generate"])
            print(c(f"  ! LLM unavailable — synthesis queries ({gen_ids}) will SKIP. "
                    "Start Ollama with the configured model to test synthesis.", YEL))
    except ApiError as e:
        print(c(f"  ! could not read /rag/health ({e}); assuming LLM available.", YEL))

    per_format = {}   # fmt -> {"mechanics": (ok, problems, ing), "queries": {...}}

    # --- per-format isolation phase ---
    for fmt in fmts:
        filename, ctype = FORMATS[fmt]
        path = DOCS_DIR / filename
        doc_id = f"eval-{fmt}-{run_id}"
        print(c(f"\n--- format: {fmt} ---", BOLD))
        wipe_all(base, token)  # clean slate so retrieval is attributable to this format

        try:
            ing = ingest(base, token, path, ctype, doc_id)
        except ApiError as e:
            print(c(f"  ingest ERROR: {e}", RED))
            per_format[fmt] = {"mechanics": (False, [f"ingest error: {e}"], {}), "queries": {}}
            continue

        ok, problems = check_mechanics(ing, fmt)
        print(f"  mechanics: kind={ing.get('kind')} stored={ing.get('stored')} "
              f"indexed={ing.get('indexed')} blocks={ing.get('num_blocks')} "
              f"chunks={ing.get('num_chunks')}  -> " +
              (c("OK", GREEN) if ok else c("PROBLEM " + "; ".join(problems), RED)))

        qres = run_query_suite(base, token, llm_available, args.top_n)
        for spec in QUERIES:
            res = qres[spec["id"]]
            line = f"  {spec['id']:<20} {status_cell(res)}"
            if res and res[0] is not None and "error" not in res[1] and "skipped" not in res[1]:
                d = res[1]
                if d["missing"]:
                    line += c(f"  missing={d['missing']}", YEL)
                if d["forbidden_hits"]:
                    line += c(f"  FORBIDDEN={d['forbidden_hits']}", RED)
            print(line)
        per_format[fmt] = {"mechanics": (ok, problems, ing), "queries": qres}

        if not args.no_cleanup:
            wipe_all(base, token)

    # --- combined phase (informational) ---
    combined = None
    if args.combined:
        print(c("\n--- combined: all formats indexed at once (informational) ---", BOLD))
        wipe_all(base, token)
        for fmt in fmts:
            filename, ctype = FORMATS[fmt]
            try:
                ingest(base, token, DOCS_DIR / filename, ctype, f"eval-combined-{fmt}-{run_id}")
            except ApiError as e:
                print(c(f"  ingest {fmt} ERROR: {e}", RED))
        combined = run_query_suite(base, token, llm_available, args.top_n)
        for spec in QUERIES:
            print(f"  {spec['id']:<20} {status_cell(combined[spec['id']])}")
        if not args.no_cleanup:
            wipe_all(base, token)

    # --- summary matrix + gate ---
    print(c("\n=== SUMMARY  (rows=query, cols=format) ===", BOLD))
    header = "query".ljust(22) + "".join(f.ljust(7) for f in fmts)
    print(header)
    hard_fail = False
    for spec in QUERIES:
        row = spec["id"].ljust(22)
        for fmt in fmts:
            res = per_format.get(fmt, {}).get("queries", {}).get(spec["id"])
            row += status_cell(res).ljust(7 + (len(status_cell(res)) - len(_plain(status_cell(res)))))
            if res and res[0] is False and not spec["manual"] and "skipped" not in res[1]:
                hard_fail = True
        tag = c(" (manual)", GREY) if spec["manual"] else ""
        print(row + tag)

    mech_fail = any(not per_format[f]["mechanics"][0] for f in per_format)
    if mech_fail:
        hard_fail = True

    report_path = write_report(run_id, started, base, fmts, per_format, combined, llm_available)
    print(f"\nreport: {report_path}")
    print(c("\nRESULT: " + ("FAIL (see report)" if hard_fail else "PASS"),
            RED if hard_fail else GREEN))
    return 1 if hard_fail else 0


def _plain(s):
    for code in (GREEN, RED, YEL, GREY, BOLD, RST):
        s = s.replace(code, "")
    return s


# --------------------------------------------------------------------------- #
# Markdown report
# --------------------------------------------------------------------------- #
def _md_cell(res, manual):
    if res is None:
        return "—"
    passed, detail = res
    if "skipped" in detail:
        return "skip"
    if "error" in detail:
        return "ERR"
    if passed is None:
        return "n/a"
    mark = "✅" if passed else ("⚠️" if manual else "❌")
    return mark


def write_report(run_id, started, base, fmts, per_format, combined, llm_available):
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = started.strftime("%Y%m%d_%H%M%S")
    lines = []
    lines.append(f"# RAG eval — {DOC.id} — run {run_id}")
    lines.append("")
    lines.append(f"- **Document:** {DOC.title} (`{DOC.basename}`)")
    lines.append(f"- **When:** {started.isoformat()}")
    lines.append(f"- **Endpoint:** {base}")
    lines.append(f"- **Formats:** {', '.join(fmts)}")
    lines.append(f"- **LLM available:** {llm_available}")
    lines.append("")

    lines.append("## Ingestion mechanics")
    lines.append("")
    lines.append("| format | kind | stored | indexed | blocks | chunks | status | reason |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for fmt in fmts:
        ok, problems, ing = per_format.get(fmt, {}).get("mechanics", (False, ["not run"], {}))
        lines.append(
            f"| {fmt} | {ing.get('kind','—')} | {ing.get('stored','—')} | "
            f"{ing.get('indexed','—')} | {ing.get('num_blocks','—')} | "
            f"{ing.get('num_chunks','—')} | {'OK' if ok else 'PROBLEM'} | "
            f"{'; '.join(problems) or ing.get('reason') or ''} |"
        )
    lines.append("")

    lines.append("## Correctness matrix")
    lines.append("")
    lines.append("| query | " + " | ".join(fmts) + " | manual |")
    lines.append("|---" * (len(fmts) + 2) + "|")
    for spec in QUERIES:
        cells = []
        for fmt in fmts:
            res = per_format.get(fmt, {}).get("queries", {}).get(spec["id"])
            cells.append(_md_cell(res, spec["manual"]))
        lines.append(f"| {spec['id']} | " + " | ".join(cells) + f" | {'yes' if spec['manual'] else ''} |")
    lines.append("")
    lines.append("Legend: ✅ pass · ❌ fail · ⚠️ manual-review (heuristic) · skip (LLM off) · — not run")
    lines.append("")

    # Per-query detail: answers + matched/missing concepts, per format.
    lines.append("## Query detail")
    for spec in QUERIES:
        lines.append("")
        lines.append(f"### {spec['id']} — {spec['label']}")
        lines.append(f"> {spec['query']}")
        lines.append("")
        for fmt in fmts:
            res = per_format.get(fmt, {}).get("queries", {}).get(spec["id"])
            if not res:
                continue
            passed, d = res
            if "skipped" in d:
                lines.append(f"- **{fmt}**: skipped ({d['skipped']})")
                continue
            if "error" in d:
                lines.append(f"- **{fmt}**: ERROR {d['error']}")
                continue
            verdict = "PASS" if passed else "FAIL"
            extra = ""
            if d.get("missing"):
                extra += f" · missing={d['missing']}"
            if d.get("bonus_missing"):
                extra += f" · bonus_missing={d['bonus_missing']}"
            if d.get("forbidden_hits"):
                extra += f" · FORBIDDEN={d['forbidden_hits']}"
            lines.append(f"- **{fmt}**: {verdict} (cits={d['num_citations']}, "
                         f"top_score={d['top_score']}){extra}")
            if spec["generate"] and d.get("answer"):
                ans = d["answer"].replace("\n", " ").strip()
                lines.append(f"  - answer: {ans[:500]}")
    lines.append("")

    if combined is not None:
        lines.append("## Combined phase (all formats indexed at once — informational)")
        lines.append("")
        lines.append("| query | result |")
        lines.append("|---|---|")
        for spec in QUERIES:
            lines.append(f"| {spec['id']} | {_md_cell(combined[spec['id']], spec['manual'])} |")
        lines.append("")

    text = "\n".join(lines)
    out = REPORTS_DIR / f"rag_eval_{ts}_{run_id}.md"
    out.write_text(text)
    (REPORTS_DIR / "latest.md").write_text(text)
    # raw JSON for debugging
    raw = {
        "run_id": run_id, "started": started.isoformat(), "base": base,
        "formats": fmts, "llm_available": llm_available,
        "per_format": {
            f: {
                "mechanics_ok": per_format[f]["mechanics"][0],
                "mechanics_problems": per_format[f]["mechanics"][1],
                "ingestion": per_format[f]["mechanics"][2],
                "queries": {qid: per_format[f]["queries"][qid][1]
                            for qid in per_format[f]["queries"]},
            } for f in per_format
        },
    }
    (REPORTS_DIR / f"rag_eval_{ts}_{run_id}.json").write_text(json.dumps(raw, indent=2, default=str))
    return out


if __name__ == "__main__":
    sys.exit(main())
