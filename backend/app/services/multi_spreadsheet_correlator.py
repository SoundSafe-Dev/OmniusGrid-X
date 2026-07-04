"""
Multi-Spreadsheet Correlator

Links multiple Excel/CSV uploads in a session by shared assets, lines, and
date coverage. Built for long-horizon operational data (many files / years).

Uses linking_metadata captured at upload time (full-column scans, not 5-row samples).
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Set, Tuple
import re

from app.services.shared_key_detector import normalize_key


def _merge_date_ranges(ranges: List[Optional[Dict[str, str]]]) -> Optional[Dict[str, str]]:
    mins: List[str] = []
    maxs: List[str] = []
    for r in ranges:
        if not r:
            continue
        if r.get("min"):
            mins.append(r["min"])
        if r.get("max"):
            maxs.append(r["max"])
    if not mins or not maxs:
        return None
    return {"min": min(mins), "max": max(maxs)}


def _years_span(date_range: Optional[Dict[str, str]]) -> Optional[int]:
    if not date_range:
        return None
    try:
        y0 = int(str(date_range["min"])[:4])
        y1 = int(str(date_range["max"])[:4])
        return max(1, y1 - y0 + 1)
    except (TypeError, ValueError, KeyError):
        return None


def _asset_key(value: Any) -> str:
    return normalize_key(value)


def _linking_from_profile(processed: Dict[str, Any]) -> Dict[str, Any]:
    """Fallback for uploads stored before linking_metadata existed."""
    linking = processed.get("linking_metadata")
    if linking:
        return linking
    profile = processed.get("full_sheet_profile") or {}
    group = profile.get("group_summary") or {}
    assets: List[str] = []
    lines: List[str] = []
    for col, rows in group.items():
        col_l = str(col).lower()
        for row in rows or []:
            val = row.get("value")
            if val is None:
                continue
            if "asset" in col_l:
                assets.append(str(val))
            if "line" in col_l:
                lines.append(str(val))
    first = (profile.get("first_rows") or [{}])[0] if profile.get("first_rows") else {}
    last = (profile.get("last_rows") or [{}])[-1] if profile.get("last_rows") else {}
    date_range = None
    for row in (first, last):
        for key, val in (row or {}).items():
            if "date" in str(key).lower() and val:
                date_range = date_range or {"min": str(val)[:10], "max": str(val)[:10]}
                if date_range and str(val)[:10] < date_range["min"]:
                    date_range["min"] = str(val)[:10]
                if date_range and str(val)[:10] > date_range["max"]:
                    date_range["max"] = str(val)[:10]
    return {
        "row_count": processed.get("rows") or 0,
        "date_range": date_range,
        "year_labels": [],
        "distinct_assets": list(dict.fromkeys(assets))[:500],
        "distinct_lines": list(dict.fromkeys(lines))[:100],
    }


def _file_snapshot(source_id: str, file_name: str, processed: Dict[str, Any]) -> Dict[str, Any]:
    linking = _linking_from_profile(processed)
    profile = processed.get("full_sheet_profile") or {}
    operational = profile.get("operational_summary") or {}
    planned = operational.get("planned_vs_actual") or {}
    loss_block = operational.get("estimated_loss")
    downtime_block = operational.get("downtime") or {}

    has_cost_column = isinstance(loss_block, dict) and bool(loss_block)
    total_loss = loss_block.get("total") if has_cost_column else None
    total_downtime = downtime_block.get("total") if isinstance(downtime_block, dict) else None

    return {
        "source_id": source_id,
        "file_name": file_name or "spreadsheet",
        "rows": processed.get("rows") or linking.get("row_count") or 0,
        "date_range": linking.get("date_range"),
        "years": linking.get("year_labels") or [],
        "assets": linking.get("distinct_assets") or [],
        "lines": linking.get("distinct_lines") or [],
        "attainment_pct": planned.get("average_attainment_pct"),
        "shortfall_total": planned.get("shortfall_total"),
        "total_loss": total_loss,
        "total_downtime": total_downtime,
        "total_defects": (operational.get("defects") or {}).get("total"),
        "loss_delta": loss_block.get("first_to_last_delta") if isinstance(loss_block, dict) else None,
        "downtime_delta": downtime_block.get("first_to_last_delta") if isinstance(downtime_block, dict) else None,
        "has_cost_column": has_cost_column,
    }


def _sorted_snapshots(snapshots: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(snapshots, key=lambda s: (s.get("date_range") or {}).get("min") or s.get("file_name") or "")


def _year_label_from_snapshot(snap: Dict[str, Any]) -> str:
    date_range = snap.get("date_range") or {}
    if date_range.get("min"):
        return str(date_range["min"])[:4]
    match = re.search(r"\b((?:19|20)\d{2})\b", str(snap.get("file_name") or ""))
    return match.group(1) if match else str(snap.get("file_name") or "file")


def _trend_direction(metric: str, first: Optional[float], last: Optional[float]) -> Optional[str]:
    if first is None or last is None:
        return None
    delta = last - first
    if abs(delta) < 1e-9:
        return "flat"
    lower_is_better = metric in {
        "shortfall_total", "total_loss", "total_downtime", "total_defects",
    }
    if lower_is_better:
        return "improving" if delta < 0 else "worsening"
    return "improving" if delta > 0 else "worsening"


def compute_yoy_trends(snapshots: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Year-over-year trends across uploaded files (sorted by date)."""
    ordered = _sorted_snapshots(snapshots)
    if len(ordered) < 2:
        return {}

    labels = [_year_label_from_snapshot(s) for s in ordered]
    metrics = {
        "attainment_pct": "Attainment",
        "shortfall_total": "Planned shortfall (units)",
        "total_loss": "Estimated cost impact",
        "total_downtime": "Downtime",
        "total_defects": "Defects",
    }
    trend_rows: List[Dict[str, Any]] = []
    for key, label in metrics.items():
        values = [snap.get(key) for snap in ordered]
        if all(v is None for v in values):
            continue
        first = next((v for v in values if v is not None), None)
        last = next((v for v in reversed(values) if v is not None), None)
        direction = _trend_direction(key, first, last)
        trend_rows.append({
            "metric": key,
            "label": label,
            "values": values,
            "years": labels,
            "first": first,
            "last": last,
            "direction": direction,
            "delta": (last - first) if first is not None and last is not None else None,
        })

    return {
        "years": labels,
        "file_names": [s.get("file_name") for s in ordered],
        "metrics": trend_rows,
    }


def _series_direction(values: List[Optional[float]], lower_is_better: bool = True) -> Optional[str]:
    cleaned = [v for v in values if v is not None]
    if len(cleaned) < 2:
        return None
    delta = cleaned[-1] - cleaned[0]
    if abs(delta) < 1e-9:
        return "flat"
    if lower_is_better:
        return "improving" if delta < 0 else "worsening"
    return "improving" if delta > 0 else "worsening"


def enrich_asset_trends(asset_trends: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    enriched: List[Dict[str, Any]] = []
    for trend in asset_trends:
        files = sorted(trend.get("files") or [], key=lambda p: (p.get("period") or {}).get("min") or "")
        downtime_vals = [p.get("total_downtime") for p in files]
        loss_vals = [p.get("total_loss") for p in files]
        defect_vals = [p.get("total_defects") for p in files]
        enriched.append({
            **trend,
            "files": files,
            "downtime_direction": _series_direction(downtime_vals, lower_is_better=True),
            "loss_direction": _series_direction(loss_vals, lower_is_better=True),
            "defect_direction": _series_direction(defect_vals, lower_is_better=True),
        })
    return enriched


def correlate_spreadsheet_sources(
    sources: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Correlate multiple uploaded spreadsheets.

    Each source dict: {source_id, file_name, processed_data}.
    """
    snapshots: List[Dict[str, Any]] = []
    for src in sources:
        processed = src.get("processed_data") or {}
        if processed.get("type") != "spreadsheet":
            continue
        snapshots.append(
            _file_snapshot(
                str(src.get("source_id") or ""),
                str(src.get("file_name") or "spreadsheet"),
                processed,
            )
        )

    if len(snapshots) < 2:
        return {
            "file_count": len(snapshots),
            "linked": False,
            "narrative_summary": (
                "Upload at least 2 spreadsheet files to run cross-file correlation."
            ),
            "cross_file_findings": [],
        }

    asset_to_files: Dict[str, List[str]] = {}
    line_to_files: Dict[str, List[str]] = {}
    for snap in snapshots:
        for asset in snap["assets"]:
            key = _asset_key(asset)
            if key:
                asset_to_files.setdefault(key, []).append(snap["file_name"])
        for line in snap["lines"]:
            key = normalize_key(line)
            if key:
                line_to_files.setdefault(key, []).append(snap["file_name"])

    shared_assets = {
        k: sorted(set(v)) for k, v in asset_to_files.items() if len(set(v)) >= 2
    }
    shared_lines = {
        k: sorted(set(v)) for k, v in line_to_files.items() if len(set(v)) >= 2
    }

    merged_range = _merge_date_ranges([s["date_range"] for s in snapshots])
    years_span = _years_span(merged_range)
    all_years: Set[int] = set()
    for s in snapshots:
        all_years.update(s.get("years") or [])

    findings: List[str] = []
    findings.append(
        f"Linked {len(snapshots)} spreadsheet files covering "
        f"{merged_range['min']} to {merged_range['max']}"
        if merged_range
        else f"Linked {len(snapshots)} spreadsheet files."
    )
    if years_span:
        findings.append(f"Combined date span: ~{years_span} calendar year(s).")
    if shared_assets:
        top = list(shared_assets.items())[:8]
        asset_bits = ", ".join(f"{k} ({len(v)} files)" for k, v in top)
        findings.append(f"Shared assets across files: {asset_bits}.")
    else:
        findings.append(
            "No shared asset_id values detected across files — link by filename year, "
            "facility, or line, or ensure asset columns use the same IDs."
        )
    if shared_lines:
        line_bits = ", ".join(f"{k} ({len(v)} files)" for k, v in list(shared_lines.items())[:5])
        findings.append(f"Shared production lines: {line_bits}.")

    # Per-file roll-up for chat / UI
    file_rollups = []
    for snap in _sorted_snapshots(snapshots):
        period = ""
        if snap.get("date_range"):
            period = f"{snap['date_range']['min']} → {snap['date_range']['max']}"
        file_rollups.append({
            "file_name": snap["file_name"],
            "year_label": _year_label_from_snapshot(snap),
            "rows": snap["rows"],
            "period": period,
            "attainment_pct": snap.get("attainment_pct"),
            "shortfall_total": snap.get("shortfall_total"),
            "total_loss": snap.get("total_loss"),
            "total_downtime": snap.get("total_downtime"),
            "total_defects": snap.get("total_defects"),
            "has_cost_column": snap.get("has_cost_column"),
        })

    # Cross-file asset trend (when same asset in multiple files)
    asset_trends: List[Dict[str, Any]] = []
    for asset_key, file_names in list(shared_assets.items())[:12]:
        points = []
        for snap in snapshots:
            if snap["file_name"] not in file_names:
                continue
            if asset_key not in {_asset_key(a) for a in snap["assets"]}:
                continue
            points.append({
                "file_name": snap["file_name"],
                "period": snap.get("date_range"),
                "total_loss": snap.get("total_loss"),
                "total_downtime": snap.get("total_downtime"),
                "total_defects": snap.get("total_defects"),
            })
        if len(points) >= 2:
            asset_trends.append({"asset": asset_key, "files": points})

    asset_trends = enrich_asset_trends(asset_trends)
    yoy_trends = compute_yoy_trends(snapshots)

    narrative_parts = [findings[0]]
    if shared_assets:
        worst_asset = max(shared_assets.items(), key=lambda kv: len(kv[1]))[0]
        narrative_parts.append(
            f"**{worst_asset}** appears in the most files ({len(shared_assets[worst_asset])}) — "
            "use it as the anchor for cross-year comparisons."
        )
    if merged_range and years_span and years_span >= 2:
        narrative_parts.append(
            f"Treat each file as a time slice from {merged_range['min'][:4]}–{merged_range['max'][:4]}. "
            "Compare the same asset or line across files before drawing floor-wide conclusions."
        )
    for rollup in file_rollups[:6]:
        bits = [f"**{rollup['file_name']}** ({rollup['rows']} rows)"]
        if rollup.get("period"):
            bits.append(rollup["period"])
        if rollup.get("attainment_pct") is not None:
            bits.append(f"attainment {rollup['attainment_pct']}%")
        if rollup.get("shortfall_total") is not None:
            bits.append(f"shortfall {rollup['shortfall_total']} units")
        if rollup.get("total_loss") is not None:
            bits.append(f"cost impact {rollup['total_loss']}")
        if rollup.get("total_downtime") is not None:
            bits.append(f"downtime {rollup['total_downtime']}")
        findings.append(" | ".join(bits))

    return {
        "file_count": len(snapshots),
        "linked": bool(shared_assets or shared_lines or merged_range),
        "temporal_coverage": merged_range,
        "years_span": years_span,
        "year_labels": sorted(all_years),
        "shared_assets": shared_assets,
        "shared_lines": shared_lines,
        "file_rollups": file_rollups,
        "asset_trends": asset_trends,
        "yoy_trends": yoy_trends,
        "cross_file_findings": findings,
        "narrative_summary": "\n\n".join(narrative_parts),
    }


def keys_from_processed_spreadsheet(processed: Dict[str, Any]) -> List[str]:
    """Correlation keys from linking_metadata + group_summary (not sample rows only)."""
    keys: List[str] = []
    linking = processed.get("linking_metadata") or {}
    for asset in linking.get("distinct_assets") or []:
        k = _asset_key(asset)
        if k:
            keys.append(k)
    for line in linking.get("distinct_lines") or []:
        k = normalize_key(line)
        if k:
            keys.append(k)
    dr = linking.get("date_range") or {}
    if dr.get("min"):
        keys.append(normalize_key(dr["min"][:10]))
    if dr.get("max"):
        keys.append(normalize_key(dr["max"][:10]))
    for year in linking.get("year_labels") or []:
        keys.append(str(year))

    profile = processed.get("full_sheet_profile") or {}
    group = profile.get("group_summary") or {}
    for _col, rows in group.items():
        col_l = str(_col).lower()
        if not any(h in col_l for h in ("asset", "line", "facility", "shift")):
            continue
        for row in rows or []:
            val = row.get("value")
            if val is not None:
                keys.append(normalize_key(val))

    # Filename year hints: ops_2018.xlsx → 2018
    fname = str(processed.get("filename") or "")
    for match in re.findall(r"\b((?:19|20)\d{2})\b", fname):
        keys.append(match)

    return list(dict.fromkeys(k for k in keys if k))
