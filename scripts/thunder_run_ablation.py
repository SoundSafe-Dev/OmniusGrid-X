"""
Retrieval ablation runner - Thunder variant.

backend/tests/rag_eval/run_ablation.py recreates the backend via
`docker compose up -d backend` between configs. Thunder instances run the
backend as a bare process instead (see thunder_bootstrap.sh - Thunder's Docker
daemon can't build images or create networks), so this drives
`thunder_bootstrap.sh restart-backend` in its place. Same four configs, same
aggregation, same report format; only the process-recreation step differs.

Run this ON the Thunder box (it shells out to a local script and hits
localhost), after `thunder_bootstrap.sh start`:

    .venv/bin/python3 scripts/thunder_run_ablation.py
"""

import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

REPO_ROOT = Path(__file__).resolve().parents[1]
EVAL_DIR = REPO_ROOT / "backend" / "tests" / "rag_eval"
REPORTS_DIR = EVAL_DIR / "reports"
BOOTSTRAP = REPO_ROOT / "scripts" / "thunder_bootstrap.sh"
VENV_PY = REPO_ROOT / ".venv" / "bin" / "python"

METRIC_KEYS = ("recall@1", "recall@3", "recall@5", "mrr")

CONFIGS: List[Dict[str, str]] = [
    {"slug": "baseline", "name": "hybrid + rerank (baseline)",
     "RAG_SEARCH_MODE": "hybrid", "RAG_RERANK_ENABLED": "true"},
    {"slug": "hybrid_no_rerank", "name": "hybrid, no rerank",
     "RAG_SEARCH_MODE": "hybrid", "RAG_RERANK_ENABLED": "false"},
    {"slug": "dense_rerank", "name": "dense-only + rerank",
     "RAG_SEARCH_MODE": "dense", "RAG_RERANK_ENABLED": "true"},
    {"slug": "sparse_rerank", "name": "sparse-only + rerank",
     "RAG_SEARCH_MODE": "sparse", "RAG_RERANK_ENABLED": "true"},
]
BASELINE_SLUG = "baseline"

# NOTE on interpreting dense-only/sparse-only results: RAG_RETRIEVE_LIMIT
# (default 20, config.py) is the candidate pool handed to the reranker. If a
# document/format cell has fewer chunks than that (the current eval corpus
# runs ~7/cell), every search mode returns the SAME complete chunk set and the
# reranker - not the search mode - decides the final order, so dense/sparse/
# hybrid converge to identical numbers with rerank on. That's a corpus-scale
# ceiling, not a bug in this driver or in VectorStore.hybrid_search's `mode`
# param. The no-rerank config is unaffected and is what actually isolates the
# reranker's contribution.


def _restart_backend(search_mode: str, rerank_enabled: str) -> None:
    subprocess.run(
        ["bash", str(BOOTSTRAP), "restart-backend", search_mode, rerank_enabled],
        check=True,
    )


def _wait_for_health(timeout: float = 120.0) -> None:
    import urllib.request

    deadline = time.time() + timeout
    last_err: Optional[Exception] = None
    req = urllib.request.Request(
        "http://localhost:8000/api/v1/rag/health",
        headers={"Authorization": "Bearer dev-token"},
    )
    while time.time() < deadline:
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                data = json.loads(resp.read())
            vec_ok = bool((data.get("vector_store") or {}).get("available"))
            inf_ok = bool((data.get("inference") or {}).get("available"))
            if vec_ok and inf_ok:
                return
        except Exception as e:
            last_err = e
        time.sleep(2)
    raise RuntimeError(f"backend did not become healthy within {timeout:.0f}s: {last_err}")


def _run_metrics_marker() -> Dict[str, Any]:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in REPORTS_DIR.glob("pytest_*.json")}
    cmd = [str(VENV_PY), "-m", "pytest", str(EVAL_DIR), "-m", "metrics", "-q",
           "--rag-base-url=http://localhost:8000"]
    # No check=True: a degraded config (e.g. sparse-only) failing the
    # recall>=0.6 gate is a measurement, not a runner error.
    subprocess.run(cmd, cwd=EVAL_DIR)
    after = {p.name for p in REPORTS_DIR.glob("pytest_*.json")}
    new = after - before
    if not new:
        raise RuntimeError("metrics marker run produced no report - is the backend healthy?")
    report_path = max((REPORTS_DIR / n for n in new), key=lambda p: p.stat().st_mtime)
    return json.loads(report_path.read_text())


def _cell_metrics(metrics: Dict[str, Any]) -> Dict[str, Dict[str, float]]:
    cells: Dict[str, Dict[str, float]] = {}
    for key, val in metrics.items():
        if key == "per_query" or "[" not in key:
            continue
        name, _, rest = key.partition("[")
        cell = rest.rstrip("]")
        if name in METRIC_KEYS:
            cells.setdefault(cell, {})[name] = val
    return cells


def _mean(values: List[float]) -> Optional[float]:
    return round(sum(values) / len(values), 3) if values else None


def _aggregate(cells: Dict[str, Dict[str, float]]) -> Dict[str, Optional[float]]:
    return {m: _mean([c[m] for c in cells.values() if m in c]) for m in METRIC_KEYS}


def _per_format(cells: Dict[str, Dict[str, float]]) -> Dict[str, Dict[str, Optional[float]]]:
    by_fmt: Dict[str, List[Dict[str, float]]] = {}
    for cell, m in cells.items():
        _, _, fmt = cell.partition("/")
        by_fmt.setdefault(fmt or cell, []).append(m)
    return {
        fmt: {m: _mean([row[m] for row in rows if m in row]) for m in METRIC_KEYS}
        for fmt, rows in by_fmt.items()
    }


def _delta(value: Optional[float], base: Optional[float]) -> Optional[float]:
    if value is None or base is None:
        return None
    return round(value - base, 3)


def _fmt_delta(d: Optional[float]) -> str:
    return "n/a" if d is None else f"{'+' if d > 0 else ''}{d}"


def _write_reports(run: Dict[str, Any]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    ts = run["timestamp"]
    (REPORTS_DIR / f"thunder_ablation_{ts}.json").write_text(json.dumps(run, indent=2, default=str))

    lines: List[str] = ["# RAG retrieval ablation report (Thunder)", "",
                        f"- **When:** {run['generated_at']}",
                        "- **Marker:** `pytest -m metrics` (model-agnostic, no LLM call in any config)",
                        "- **Cells:** see per-cell detail below", ""]
    lines.append("## Aggregate, vs. baseline")
    lines.append("")
    lines.append("| config | recall@1 | recall@3 | recall@5 | mrr | Δr@1 | Δr@3 | Δr@5 | Δmrr |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for cfg in run["configs"]:
        a, d = cfg["aggregate"], cfg["delta_vs_baseline"]
        lines.append(f"| {cfg['name']} | {a['recall@1']} | {a['recall@3']} | {a['recall@5']} | "
                     f"{a['mrr']} | {_fmt_delta(d['recall@1'])} | {_fmt_delta(d['recall@3'])} | "
                     f"{_fmt_delta(d['recall@5'])} | {_fmt_delta(d['mrr'])} |")
    lines.append("")
    out = REPORTS_DIR / f"thunder_ablation_{ts}.md"
    out.write_text("\n".join(lines))
    return out


def main() -> None:
    now = datetime.now(timezone.utc)
    run: Dict[str, Any] = {
        "timestamp": now.strftime("%Y%m%d_%H%M%S"),
        "generated_at": now.isoformat(),
        "configs": [],
    }
    baseline_aggregate: Optional[Dict[str, Optional[float]]] = None
    baseline_per_format: Optional[Dict[str, Dict[str, Optional[float]]]] = None

    try:
        for cfg in CONFIGS:
            print(f"[ablation] {cfg['name']} ...")
            _restart_backend(cfg["RAG_SEARCH_MODE"], cfg["RAG_RERANK_ENABLED"])
            _wait_for_health()

            report = _run_metrics_marker()
            cells = _cell_metrics(report.get("metrics", {}))
            aggregate = _aggregate(cells)
            per_format = _per_format(cells)

            if cfg["slug"] == BASELINE_SLUG:
                baseline_aggregate = aggregate
                baseline_per_format = per_format

            delta = {m: _delta(aggregate[m], (baseline_aggregate or aggregate)[m])
                     for m in METRIC_KEYS}
            delta_per_format = {
                fmt: {m: _delta(per_format[fmt][m], (baseline_per_format or per_format)
                                .get(fmt, per_format[fmt])[m]) for m in METRIC_KEYS}
                for fmt in per_format
            }

            run["configs"].append({
                "slug": cfg["slug"], "name": cfg["name"],
                "search_mode": cfg["RAG_SEARCH_MODE"],
                "rerank_enabled": cfg["RAG_RERANK_ENABLED"] == "true",
                "cells": cells, "aggregate": aggregate, "per_format": per_format,
                "delta_vs_baseline": delta, "delta_vs_baseline_per_format": delta_per_format,
            })
            print(f"  aggregate: {aggregate}")
    finally:
        print("[ablation] restoring backend to baseline config ...")
        try:
            _restart_backend("hybrid", "true")
            _wait_for_health()
        except Exception as exc:
            print(f"[ablation] WARNING: failed to restore baseline config: {exc}")

    out = _write_reports(run)
    print(f"\n[ablation] report written: {out}")


if __name__ == "__main__":
    main()
