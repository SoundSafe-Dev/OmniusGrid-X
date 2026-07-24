"""Markdown/JSON report writer for the pytest suite, tagged with the active
model so runs across models are directly comparable."""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

REPORTS_DIR = Path(__file__).resolve().parent / "reports"


def _model_slug(model_tag: Dict[str, Any]) -> str:
    llm = (model_tag.get("llm") or "no-llm").replace(":", "-").replace("/", "-")
    return llm


def write_pytest_report(results: List[Dict[str, Any]], model_tag: Dict[str, Any],
                        metrics: Dict[str, Any]) -> Path:
    REPORTS_DIR.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc)
    ts = now.strftime("%Y%m%d_%H%M%S")
    slug = _model_slug(model_tag)

    lines: List[str] = []
    lines.append(f"# RAG pytest report — model `{model_tag.get('llm')}`")
    lines.append("")
    lines.append(f"- **When:** {now.isoformat()}")
    lines.append(f"- **LLM:** {model_tag.get('llm')} (available={model_tag.get('llm_available')})")
    lines.append(f"- **Embedder:** {model_tag.get('embedder')}  ·  **Reranker:** {model_tag.get('reranker')}"
                 f"  ·  **Device:** {model_tag.get('device')}")
    lines.append("")

    # Outcomes grouped by category.
    by_cat: Dict[str, List[Dict[str, Any]]] = {}
    for r in results:
        by_cat.setdefault(r.get("category", "other"), []).append(r)
    lines.append("## Outcomes by category")
    lines.append("")
    lines.append("| category | passed | total |")
    lines.append("|---|---|---|")
    for cat in sorted(by_cat):
        rows = by_cat[cat]
        passed = sum(1 for r in rows if r.get("passed"))
        lines.append(f"| {cat} | {passed} | {len(rows)} |")
    lines.append("")

    scalar_metrics = {k: v for k, v in metrics.items() if k != "per_query"}
    if scalar_metrics or metrics.get("per_query"):
        lines.append("## Retrieval metrics (model-agnostic)")
        lines.append("")
        for k in sorted(scalar_metrics):
            lines.append(f"- **{k}:** {scalar_metrics[k]}")
        if metrics.get("per_query"):
            lines.append("")
            lines.append("| query | format | rank_of_gold |")
            lines.append("|---|---|---|")
            for row in metrics["per_query"]:
                lines.append(f"| {row['query']} | {row['format']} | {row['rank']} |")
        lines.append("")

    lines.append("## All results")
    lines.append("")
    lines.append("| category | test | format | passed | note |")
    lines.append("|---|---|---|---|---|")
    for r in results:
        mark = "✅" if r.get("passed") else "❌"
        lines.append(f"| {r.get('category')} | {r.get('name')} | {r.get('format','')} | "
                     f"{mark} | {r.get('note','')} |")
    lines.append("")

    text = "\n".join(lines)
    out = REPORTS_DIR / f"pytest_{slug}_{ts}.md"
    out.write_text(text)
    (REPORTS_DIR / f"pytest_latest_{slug}.md").write_text(text)
    (REPORTS_DIR / f"pytest_{slug}_{ts}.json").write_text(
        json.dumps({"model": model_tag, "metrics": metrics, "results": results},
                   indent=2, default=str)
    )
    return out
