"""
Generate suggested questions from uploaded session data.

Questions are personalized to the files, tabs, domains, date coverage, and
cross-source links in the session — not static templates.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from app.models.domain_interaction import DomainType
from app.services.multi_spreadsheet_correlator import correlate_spreadsheet_sources
from app.services.presentation_labels import humanize_label
from app.services.spreadsheet_domain_mapper import map_tab_to_domain, map_workbook_domains

_FINANCE_HINTS = ("finance", "financial", "budget", "revenue", "cost", "p&l", "margin", "expense")
_PRODUCTION_HINTS = ("production", "manufacturing", "mes", "oee", "output", "operations")
_QUALITY_HINTS = ("quality", "defect", "yield", "inspection")
_LOGISTICS_HINTS = ("logistics", "warehouse", "shipping", "supply", "inventory")


def _norm(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(text or "").lower())


def _contains_any(text: str, hints: Tuple[str, ...]) -> bool:
    lower = str(text or "").lower()
    return any(h in lower for h in hints)


def _classify_sheet(name: str, columns: List[str]) -> str:
    domain = map_tab_to_domain(name, columns)
    if domain == DomainType.FIN:
        return "finance"
    if domain in (DomainType.PROD, DomainType.MES, DomainType.PLN):
        return "production"
    if domain == DomainType.QUA:
        return "quality"
    if domain in (DomainType.LOG, DomainType.WHS, DomainType.SUP):
        return "logistics"

    joined = " ".join([name] + columns).lower()
    if _contains_any(joined, _FINANCE_HINTS):
        return "finance"
    if _contains_any(joined, _PRODUCTION_HINTS):
        return "production"
    if _contains_any(joined, _QUALITY_HINTS):
        return "quality"
    if _contains_any(joined, _LOGISTICS_HINTS):
        return "logistics"
    return "other"


def _document_snippet(processed: Dict[str, Any], limit: int = 400) -> str:
    if processed.get("content"):
        return str(processed["content"])[:limit]
    pages = processed.get("pages") or []
    chunks: List[str] = []
    for page in pages[:3]:
        text = str(page.get("text") or "").strip()
        if text:
            chunks.append(text)
    return " ".join(chunks)[:limit]


def _document_topics(processed: Dict[str, Any]) -> List[str]:
    text = _document_snippet(processed, 1200).lower()
    topics: List[str] = []
    patterns = [
        (r"\b(production line\s*[a-z0-9-]+)\b", "production line"),
        (r"\b(line\s*[0-9]+)\b", "production line"),
        (r"\b(q[1-4]\s*\d{4})\b", "quarter"),
        (r"\b(high season|peak season|busy season)\b", "seasonality"),
        (r"\b(budget|revenue|margin|cost)\b", "finance"),
        (r"\b(maintenance|downtime|oee)\b", "maintenance"),
        (r"\b(orders?|demand|capacity)\b", "demand"),
        (r"\b(meeting|transcript|discussion|agenda)\b", "meeting"),
    ]
    for pattern, label in patterns:
        if re.search(pattern, text) and label not in topics:
            topics.append(label)
    for key in processed.get("shared_keys") or []:
        key_str = str(key).strip()
        if 3 <= len(key_str) <= 40 and key_str not in topics:
            topics.append(key_str)
    return topics[:6]


def _build_session_intelligence(
    data_sources: List[Dict[str, Any]],
    multi_spreadsheet_analysis: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    spreadsheets: List[Dict[str, Any]] = []
    documents: List[Dict[str, Any]] = []
    sheet_roles: Dict[str, List[str]] = {
        "finance": [],
        "production": [],
        "quality": [],
        "logistics": [],
        "other": [],
    }
    lines: List[str] = []
    assets: List[str] = []
    years: Set[int] = set()
    file_names: List[str] = []

    for source in data_sources:
        processed = source.get("processed_data") or {}
        file_name = str(source.get("file_name") or processed.get("filename") or "upload")
        if processed.get("type") == "spreadsheet":
            spreadsheets.append(source)
            file_names.append(file_name)
            linking = processed.get("linking_metadata") or {}
            lines.extend(linking.get("distinct_lines") or [])
            assets.extend(linking.get("distinct_assets") or [])
            years.update(linking.get("year_labels") or [])
            tabs = processed.get("tabs") or []
            if tabs:
                for tab in tabs:
                    role = _classify_sheet(
                        str(tab.get("name") or "Sheet"),
                        tab.get("column_names") or [],
                    )
                    label = f"{humanize_label(file_name)} → {humanize_label(tab.get('name'))}"
                    sheet_roles[role].append(label)
            else:
                role = _classify_sheet(
                    file_name,
                    processed.get("column_names") or [],
                )
                sheet_roles[role].append(humanize_label(file_name))
        elif processed.get("type") in ("report", "document") or source.get("data_type") in ("report", "document"):
            documents.append({"file_name": file_name, "processed": processed})

    multi = multi_spreadsheet_analysis
    if not multi and len(spreadsheets) >= 2:
        payloads = [
            {
                "source_id": str(src.get("source_id") or src.get("id") or idx),
                "file_name": src.get("file_name"),
                "processed_data": src.get("processed_data") or {},
            }
            for idx, src in enumerate(spreadsheets)
        ]
        multi = correlate_spreadsheet_sources(payloads)

    shared_assets = list((multi or {}).get("shared_assets") or {})[:3]
    date_range = (multi or {}).get("temporal_coverage")
    if not date_range and spreadsheets:
        ranges = []
        for src in spreadsheets:
            linking = (src.get("processed_data") or {}).get("linking_metadata") or {}
            if linking.get("date_range"):
                ranges.append(linking["date_range"])
        if ranges:
            date_range = {"min": min(r["min"] for r in ranges), "max": max(r["max"] for r in ranges)}

    doc_topics: List[str] = []
    for doc in documents:
        doc_topics.extend(_document_topics(doc["processed"]))

    return {
        "spreadsheet_count": len(spreadsheets),
        "document_count": len(documents),
        "file_names": file_names,
        "sheet_roles": sheet_roles,
        "lines": list(dict.fromkeys(lines))[:5],
        "assets": list(dict.fromkeys(assets))[:5],
        "years": sorted(years),
        "date_range": date_range,
        "shared_assets": shared_assets,
        "multi": multi or {},
        "documents": documents,
        "doc_topics": list(dict.fromkeys(doc_topics))[:8],
    }


def _pick_line(intel: Dict[str, Any]) -> Optional[str]:
    lines = intel.get("lines") or []
    return humanize_label(lines[0]) if lines else None


def _pick_asset(intel: Dict[str, Any]) -> Optional[str]:
    shared = intel.get("shared_assets") or []
    if shared:
        return str(shared[0])
    assets = intel.get("assets") or []
    return assets[0] if assets else None


def _year_span_label(intel: Dict[str, Any]) -> Optional[str]:
    years = intel.get("years") or []
    if len(years) >= 2:
        return f"{years[0]}–{years[-1]}"
    date_range = intel.get("date_range") or {}
    if date_range.get("min") and date_range.get("max"):
        return f"{date_range['min'][:4]}–{date_range['max'][:4]}"
    return None


def generate_suggested_questions(
    data_sources: List[Dict[str, Any]],
    multi_spreadsheet_analysis: Optional[Dict[str, Any]] = None,
    exclude: Optional[List[str]] = None,
    limit: int = 3,
) -> Dict[str, Any]:
    """
    Return personalized suggested questions for the session.

    Each question includes a short rationale for debugging/UI tooltips.
    """
    exclude_norm = {_norm(q) for q in (exclude or []) if q}
    intel = _build_session_intelligence(data_sources, multi_spreadsheet_analysis)
    candidates: List[Tuple[int, str, str]] = []

    finance_sheets = intel["sheet_roles"]["finance"]
    production_sheets = intel["sheet_roles"]["production"]
    quality_sheets = intel["sheet_roles"]["quality"]
    pdf_names = [d["file_name"] for d in intel["documents"]]
    line = _pick_line(intel)
    asset = _pick_asset(intel)
    year_label = _year_span_label(intel)

    has_cross_tabs = bool(finance_sheets and production_sheets)
    has_cross_files = intel["spreadsheet_count"] >= 2
    has_pdf = bool(pdf_names)
    has_docs = intel["document_count"] > 0

    if has_cross_tabs or (has_cross_files and (finance_sheets or production_sheets)):
        line_bit = f" on {line}" if line else ""
        pdf_bit = ", including the uploaded operating documents" if has_pdf else ""
        candidates.append((
            100,
            f"If we increase orders or ramp production{line_bit}, how should we plan for growth using "
            f"our finance and production data{pdf_bit}?",
            "cross_source_growth",
        ))

    if has_pdf and (finance_sheets or production_sheets):
        candidates.append((
            95,
            "Where do the operating documents and the finance or production data align or drift?",
            "pdf_cross_reference",
        ))

    if year_label or len(intel.get("years") or []) >= 2:
        candidates.append((
            90,
            f"Looking at our data from {year_label or 'multiple seasons'}, how should we prepare for the next high season?",
            "seasonal_prep",
        ))

    if line or asset or has_cross_files:
        target = f"{line}" if line else (f"asset {asset}" if asset else "our operation")
        candidates.append((
            88,
            f"Everything looks steady on {target} — what bottlenecks do you foresee if demand picks up?",
            "hidden_bottleneck",
        ))

    if production_sheets or quality_sheets:
        candidates.append((
            85,
            "What is going well in operations, and how do we do more of it without creating new bottlenecks?",
            "amplify_strengths",
        ))

    if intel["doc_topics"]:
        topic = intel["doc_topics"][0]
        candidates.append((
            82,
            f"Based on the uploaded documents, what should we prioritize around {humanize_label(topic)} in the next planning cycle?",
            "document_topic",
        ))

    if has_cross_files and year_label:
        candidates.append((
            93,
            f"What trends do you see across all files from {year_label}?",
            "cross_file_trends",
        ))

    if asset and has_cross_files:
        candidates.append((
            80,
            f"Compare {asset} across our uploaded files — where is performance improving and where is it slipping?",
            "asset_trend",
        ))

    if finance_sheets and not has_cross_tabs:
        candidates.append((
            70,
            "Where are we leaving money on the table, and what is the fastest fix?",
            "finance_focus",
        ))

    if production_sheets:
        candidates.append((
            68,
            "Which production line or shift is hurting throughput the most?",
            "production_drilldown",
        ))

    if quality_sheets:
        candidates.append((
            66,
            "Which defect pattern should we contain first before it spreads?",
            "quality_focus",
        ))

    # Spreadsheet drill-down fallbacks — still slightly personalized
    first_sheet = humanize_label(intel["file_names"][0]) if intel["file_names"] else "the uploaded data"
    candidates.extend([
        (50, f"Give me a consultant-style rundown of {first_sheet} — what's working, what's at risk, and why.", "executive_rundown"),
        (45, f"What should we tackle first on the next shift based on {first_sheet}?", "next_shift"),
        (40, f"Which line or asset in {first_sheet} shows the strongest cost or downtime signal?", "signal_hunt"),
    ])

    selected: List[Dict[str, str]] = []
    used_categories: Set[str] = set()
    used_questions: Set[str] = set()
    for priority, question, category in sorted(candidates, key=lambda item: item[0], reverse=True):
        question_norm = _norm(question)
        if question_norm in exclude_norm or question_norm in used_questions:
            continue
        if category in used_categories:
            continue
        selected.append({"question": question, "category": category})
        used_categories.add(category)
        used_questions.add(question_norm)
        if len(selected) >= limit:
            break

    context_bits = []
    if finance_sheets and production_sheets:
        context_bits.append("finance + production")
    elif intel["spreadsheet_count"]:
        context_bits.append(f"{intel['spreadsheet_count']} spreadsheet(s)")
    if has_pdf:
        context_bits.append(f"{len(pdf_names)} document(s)")
    if year_label:
        context_bits.append(f"data through {year_label}")

    return {
        "questions": [item["question"] for item in selected],
        "items": selected,
        "context_summary": (
            f"Suggestions based on {' · '.join(context_bits)}."
            if context_bits
            else "Upload spreadsheets or documents to get tailored suggestions."
        ),
        "intelligence": {
            "spreadsheet_count": intel["spreadsheet_count"],
            "document_count": intel["document_count"],
            "sheet_roles": {k: v[:3] for k, v in intel["sheet_roles"].items() if v},
            "lines": intel["lines"][:3],
            "years": intel["years"][:6],
        },
    }
