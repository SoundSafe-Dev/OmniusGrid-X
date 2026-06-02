"""
NLP Correlation AI API Endpoints

API endpoints for natural language interaction with the correlation AI engine,
and Intake Inbox for data upload and analysis.
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks, UploadFile, File
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel, Field
import math
import structlog

from app.db.database import get_db
from app.api.auth import get_current_active_user
from app.db.models import User
from app.db.models import IntakeItem as IntakeItemModel
from app.services.correlation_ai_engine import correlation_ai_engine
from app.services.correlation_registry_integration import correlation_registry_integration
from sqlalchemy import select, func

logger = structlog.get_logger()

router = APIRouter(prefix="/api/v1/nlp/correlation", tags=["NLP Correlation"])


def _json_safe(value: Any) -> Any:
    """Convert pandas/numpy values into JSON-safe Python values."""
    if value is None:
        return None
    if hasattr(value, "item"):
        value = value.item()
    if isinstance(value, float) and (math.isnan(value) or math.isinf(value)):
        return None
    if hasattr(value, "isoformat") and not isinstance(value, (str, bytes)):
        return value.isoformat()
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_json_safe(item) for item in value]
    return value


def _round_metric(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(numeric) or math.isinf(numeric):
        return None
    return round(numeric, 3)


def _find_column(columns: List[str], keywords: List[str]) -> Optional[str]:
    lower_lookup = {str(column).lower(): column for column in columns}
    for keyword in keywords:
        for lower_name, original_name in lower_lookup.items():
            if keyword in lower_name:
                return original_name
    return None


def _records_for_model(df: Any, limit: int = 5) -> List[Dict[str, Any]]:
    if df.empty:
        return []
    return _json_safe(df.head(limit).where(df.notna(), None).to_dict(orient="records"))


def _numeric_profile(df: Any) -> Dict[str, Any]:
    profile: Dict[str, Any] = {}
    numeric_df = df.select_dtypes(include="number")
    for column in numeric_df.columns[:25]:
        series = numeric_df[column].dropna()
        if series.empty:
            continue

        first_value = series.iloc[0]
        last_value = series.iloc[-1]
        delta = last_value - first_value
        percent_change = None
        if first_value != 0:
            percent_change = (delta / abs(first_value)) * 100

        profile[str(column)] = {
            "count": int(series.count()),
            "min": _round_metric(series.min()),
            "max": _round_metric(series.max()),
            "mean": _round_metric(series.mean()),
            "median": _round_metric(series.median()),
            "sum": _round_metric(series.sum()),
            "first": _round_metric(first_value),
            "last": _round_metric(last_value),
            "first_to_last_delta": _round_metric(delta),
            "first_to_last_percent_change": _round_metric(percent_change),
        }
    return profile


def _categorical_profile(df: Any) -> Dict[str, Any]:
    profile: Dict[str, Any] = {}
    for column in df.columns[:30]:
        series = df[column].dropna()
        if series.empty:
            continue
        unique_count = int(series.nunique())
        if unique_count > 25 and not df[column].dtype == "object":
            continue
        counts = series.astype(str).value_counts().head(8)
        profile[str(column)] = {
            "unique_count": unique_count,
            "top_values": _json_safe(counts.to_dict()),
        }
    return profile


def _operational_profile(df: Any) -> Dict[str, Any]:
    columns = [str(column) for column in df.columns]
    planned_col = _find_column(columns, ["planned_units", "planned", "target"])
    actual_col = _find_column(columns, ["actual_units", "actual", "produced"])
    downtime_col = _find_column(columns, ["downtime"])
    defect_col = _find_column(columns, ["defect"])
    vibration_col = _find_column(columns, ["vibration"])
    loss_col = _find_column(columns, ["estimated_loss", "loss", "cost"])
    delay_col = _find_column(columns, ["delay_reason", "delay"])
    maintenance_col = _find_column(columns, ["maintenance"])
    priority_col = _find_column(columns, ["priority"])

    metrics: Dict[str, Any] = {}
    working_df = df.copy()

    if planned_col and actual_col:
        planned = working_df[planned_col]
        actual = working_df[actual_col]
        working_df["_actual_gap"] = planned - actual
        working_df["_attainment_pct"] = (actual / planned.replace(0, math.nan)) * 100
        metrics["planned_vs_actual"] = {
            "planned_total": _round_metric(planned.sum()),
            "actual_total": _round_metric(actual.sum()),
            "shortfall_total": _round_metric((planned - actual).sum()),
            "average_attainment_pct": _round_metric(working_df["_attainment_pct"].mean()),
            "worst_shortfall": _round_metric(working_df["_actual_gap"].max()),
        }

    for source_col, label in [
        (downtime_col, "downtime"),
        (defect_col, "defects"),
        (vibration_col, "vibration"),
        (loss_col, "estimated_loss"),
    ]:
        if not source_col:
            continue
        series = working_df[source_col].dropna()
        if series.empty:
            continue
        metrics[label] = {
            "total": _round_metric(series.sum()),
            "average": _round_metric(series.mean()),
            "min": _round_metric(series.min()),
            "max": _round_metric(series.max()),
            "first": _round_metric(series.iloc[0]),
            "last": _round_metric(series.iloc[-1]),
            "first_to_last_delta": _round_metric(series.iloc[-1] - series.iloc[0]),
        }

    for source_col, label in [
        (delay_col, "delay_reason_counts"),
        (maintenance_col, "maintenance_status_counts"),
        (priority_col, "priority_counts"),
    ]:
        if source_col:
            metrics[label] = _json_safe(
                working_df[source_col].dropna().astype(str).value_counts().head(8).to_dict()
            )

    return metrics


def _row_context_columns(df: Any) -> List[str]:
    keywords = [
        "date", "shift", "facility", "production_line", "line", "asset_id", "asset_name",
        "planned", "actual", "downtime", "defect", "temperature", "vibration",
        "maintenance", "delay", "priority", "estimated_loss", "loss",
    ]
    selected = [
        column for column in df.columns
        if any(keyword in str(column).lower() for keyword in keywords)
    ]
    return selected[:16] or list(df.columns[:12])


def _top_rows_by_signal(df: Any) -> Dict[str, List[Dict[str, Any]]]:
    top_rows: Dict[str, List[Dict[str, Any]]] = {}
    columns = [str(column) for column in df.columns]
    context_columns = _row_context_columns(df)
    signals = {
        "highest_downtime_rows": _find_column(columns, ["downtime"]),
        "highest_defect_rows": _find_column(columns, ["defect"]),
        "highest_vibration_rows": _find_column(columns, ["vibration"]),
        "highest_loss_rows": _find_column(columns, ["estimated_loss", "loss", "cost"]),
    }

    planned_col = _find_column(columns, ["planned_units", "planned", "target"])
    actual_col = _find_column(columns, ["actual_units", "actual", "produced"])
    working_df = df.copy()
    if planned_col and actual_col:
        working_df["_actual_gap"] = working_df[planned_col] - working_df[actual_col]
        signals["largest_actual_vs_planned_shortfall_rows"] = "_actual_gap"

    for label, column in signals.items():
        if not column or column not in working_df:
            continue
        ranked = working_df.sort_values(column, ascending=False).head(5).copy()
        display_columns = context_columns.copy()
        if column.startswith("_"):
            display_columns.append(column)
        top_rows[label] = _records_for_model(ranked[display_columns], limit=5)

    return top_rows


def _group_profile(df: Any) -> Dict[str, Any]:
    columns = [str(column) for column in df.columns]
    group_columns = [
        _find_column(columns, ["production_line", "line"]),
        _find_column(columns, ["asset_id", "asset"]),
        _find_column(columns, ["facility"]),
        _find_column(columns, ["shift"]),
    ]
    group_columns = [column for column in group_columns if column]

    downtime_col = _find_column(columns, ["downtime"])
    defect_col = _find_column(columns, ["defect"])
    vibration_col = _find_column(columns, ["vibration"])
    loss_col = _find_column(columns, ["estimated_loss", "loss", "cost"])
    planned_col = _find_column(columns, ["planned_units", "planned", "target"])
    actual_col = _find_column(columns, ["actual_units", "actual", "produced"])

    working_df = df.copy()
    if planned_col and actual_col:
        working_df["_actual_gap"] = working_df[planned_col] - working_df[actual_col]
        working_df["_attainment_pct"] = (working_df[actual_col] / working_df[planned_col].replace(0, math.nan)) * 100

    value_columns = [
        (downtime_col, "downtime_total", "sum"),
        (defect_col, "defect_total", "sum"),
        (vibration_col, "vibration_avg", "mean"),
        (loss_col, "estimated_loss_total", "sum"),
        ("_actual_gap", "actual_shortfall_total", "sum"),
        ("_attainment_pct", "attainment_pct_avg", "mean"),
    ]

    profile: Dict[str, Any] = {}
    for group_col in group_columns:
        rows = []
        for value, group in working_df.groupby(group_col, dropna=True):
            row: Dict[str, Any] = {"value": _json_safe(value), "rows": int(len(group))}
            for source_col, label, agg in value_columns:
                if not source_col or source_col not in group:
                    continue
                series = group[source_col].dropna()
                if series.empty:
                    continue
                metric_value = series.sum() if agg == "sum" else series.mean()
                row[label] = _round_metric(metric_value)
            rows.append(row)

        if rows:
            rows.sort(
                key=lambda item: (
                    item.get("downtime_total") or 0,
                    item.get("defect_total") or 0,
                    item.get("estimated_loss_total") or 0,
                    item.get("actual_shortfall_total") or 0,
                ),
                reverse=True,
            )
            profile[str(group_col)] = rows[:8]

    return profile


def _build_spreadsheet_profile(df: Any) -> Dict[str, Any]:
    return {
        "numeric_summary": _numeric_profile(df),
        "categorical_summary": _categorical_profile(df),
        "operational_summary": _operational_profile(df),
        "group_summary": _group_profile(df),
        "highest_risk_rows": _top_rows_by_signal(df),
        "first_rows": _records_for_model(df, limit=5),
        "last_rows": _records_for_model(df.tail(5), limit=5),
    }


def _build_numeric_comparison_findings(df: Any) -> List[str]:
    if df.empty:
        return []

    columns = [str(column) for column in df.columns]
    planned_col = _find_column(columns, ["planned_units", "planned", "target"])
    actual_col = _find_column(columns, ["actual_units", "actual", "produced"])
    defect_col = _find_column(columns, ["defect_count", "defect"])
    downtime_col = _find_column(columns, ["downtime_minutes", "downtime"])
    loss_col = _find_column(columns, ["estimated_cost", "estimated_loss", "loss", "cost"])
    vibration_col = _find_column(columns, ["vibration_level", "vibration"])
    asset_col = _find_column(columns, ["asset_id", "asset"])
    line_col = _find_column(columns, ["production_line", "line"])
    shift_col = _find_column(columns, ["shift"])

    findings: List[str] = []

    if defect_col and planned_col:
        total_defects = df[defect_col].sum()
        total_planned = df[planned_col].sum()
        defects_per_1000_planned = (total_defects / total_planned * 1000) if total_planned else None
        working_df = df.copy()
        working_df["_defects_per_1000_planned"] = (
            working_df[defect_col] / working_df[planned_col].replace(0, math.nan) * 1000
        )
        worst_row = working_df.sort_values("_defects_per_1000_planned", ascending=False).head(1)

        findings.append(
            "Numeric comparison: defect_count vs planned_units | "
            f"total_defect_count={_format_finding_value(total_defects)} | "
            f"total_planned_units={_format_finding_value(total_planned)} | "
            f"defects_per_1000_planned_units={_format_finding_value(_round_metric(defects_per_1000_planned))} | "
            f"worst_row={_row_label(_records_for_model(worst_row, limit=1)[0])}."
        )

        for group_col in [line_col, asset_col, shift_col]:
            if not group_col:
                continue
            rows = []
            for group_value, group in working_df.groupby(group_col, dropna=True):
                planned_sum = group[planned_col].sum()
                defect_sum = group[defect_col].sum()
                rows.append({
                    "group": group_value,
                    "planned_units": _round_metric(planned_sum),
                    "defect_count": _round_metric(defect_sum),
                    "defects_per_1000_planned_units": _round_metric(
                        defect_sum / planned_sum * 1000 if planned_sum else None
                    ),
                })
            rows.sort(key=lambda row: row.get("defects_per_1000_planned_units") or 0, reverse=True)
            top_groups = "; ".join(
                f"{group_col}={row['group']} defect_count={_format_finding_value(row['defect_count'])} "
                f"planned_units={_format_finding_value(row['planned_units'])} "
                f"defects_per_1000={_format_finding_value(row['defects_per_1000_planned_units'])}"
                for row in rows[:3]
            )
            findings.append(f"Numeric comparison by {group_col}: defect_count vs planned_units | {top_groups}.")

    if actual_col and planned_col:
        actual_total = df[actual_col].sum()
        planned_total = df[planned_col].sum()
        shortfall_total = planned_total - actual_total
        attainment = (actual_total / planned_total * 100) if planned_total else None
        findings.append(
            "Numeric comparison: actual_units vs planned_units | "
            f"total_actual_units={_format_finding_value(actual_total)} | "
            f"total_planned_units={_format_finding_value(planned_total)} | "
            f"shortfall_units={_format_finding_value(shortfall_total)} | "
            f"attainment_pct={_format_finding_value(_round_metric(attainment))}."
        )

    if loss_col and downtime_col:
        loss_total = df[loss_col].sum()
        downtime_total = df[downtime_col].sum()
        loss_per_downtime_minute = loss_total / downtime_total if downtime_total else None
        findings.append(
            "Numeric comparison: estimated cost impact vs downtime | "
            f"total_estimated_cost={_format_finding_value(loss_total)} | "
            f"total_downtime={_format_finding_value(downtime_total)} | "
            f"cost_per_downtime_minute={_format_finding_value(_round_metric(loss_per_downtime_minute))}."
        )

    if vibration_col and defect_col:
        working_df = df.copy()
        high_vibration_threshold = working_df[vibration_col].quantile(0.75)
        high_vibration = working_df[working_df[vibration_col] >= high_vibration_threshold]
        low_vibration = working_df[working_df[vibration_col] < high_vibration_threshold]
        findings.append(
            "Numeric comparison: vibration vs defects | "
            f"high_vibration_threshold={_format_finding_value(_round_metric(high_vibration_threshold))} | "
            f"avg_defects_high_vibration={_format_finding_value(_round_metric(high_vibration[defect_col].mean()))} | "
            f"avg_defects_lower_vibration={_format_finding_value(_round_metric(low_vibration[defect_col].mean()))}."
        )

    return findings[:8]


def _format_finding_value(value: Any) -> str:
    if value is None:
        return "n/a"
    if isinstance(value, float):
        return f"{value:,.1f}" if value % 1 else f"{value:,.0f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def _top_group_label(profile: Dict[str, Any], group_name: str, metric_name: str) -> Optional[str]:
    groups = profile.get("group_summary", {}).get(group_name) or []
    if not groups:
        return None
    top_group = groups[0]
    value = top_group.get("value")
    metric = top_group.get(metric_name)
    if value is None or metric is None:
        return None
    return f"{group_name}={value} ({metric_name}={_format_finding_value(metric)})"


def _row_label(row: Dict[str, Any]) -> str:
    preferred = [
        "date", "shift", "facility", "production_line", "asset_id", "asset_name",
        "planned_units", "actual_units", "downtime", "downtime_minutes",
        "defect_count", "vibration", "maintenance_status", "delay_reason",
        "priority", "estimated_loss",
    ]
    parts = []
    for key in preferred:
        if key in row and row[key] is not None:
            parts.append(f"{key}={_format_finding_value(row[key])}")
    if parts:
        return "; ".join(parts)
    return "; ".join(f"{key}={_format_finding_value(value)}" for key, value in list(row.items())[:10])


def _column_value(row: Dict[str, Any], column: Optional[str]) -> Any:
    if not column:
        return None
    return row.get(column)


def _owner_for_issue(issue_text: str, columns: List[str]) -> str:
    normalized = issue_text.lower()
    column_text = " ".join(columns).lower()
    if any(term in normalized for term in ("quality", "defect", "hold")):
        return "Quality + Production"
    if any(term in normalized for term in ("maintenance", "sensor", "vibration", "inspection", "equipment")):
        return "Maintenance + Operations"
    if any(term in normalized for term in ("material", "supplier", "inventory", "shortage")):
        return "Supply Planning + Operations"
    if any(term in normalized for term in ("changeover", "setup")):
        return "Production Supervisor"
    if "carrier" in column_text or "shipment" in column_text or "dock" in column_text:
        return "Logistics Operations"
    return "Operations Lead"


def _metric_watch_list(columns: List[str]) -> List[str]:
    candidates = [
        "estimated_loss",
        "estimated_cost_impact_usd",
        "downtime",
        "downtime_minutes",
        "defect_count",
        "actual_units",
        "planned_units",
        "vibration",
        "vibration_level",
        "maintenance_status",
        "delay_reason",
        "priority",
    ]
    lower_lookup = {str(column).lower(): str(column) for column in columns}
    watched = []
    for candidate in candidates:
        for lower_name, original in lower_lookup.items():
            if candidate in lower_name and original not in watched:
                watched.append(original)
    return watched[:5]


def _build_action_plan_for_group(
    group_label: str,
    group_value: Any,
    group: Any,
    columns: List[str],
    rank_col: Optional[str],
) -> Optional[Dict[str, Any]]:
    if group.empty:
        return None

    working_group = group.copy()
    if rank_col and rank_col in working_group:
        worst_row_df = working_group.sort_values(rank_col, ascending=False).head(1)
    else:
        worst_row_df = working_group.head(1)
    worst_row = _records_for_model(worst_row_df, limit=1)[0]

    loss_col = _find_column(columns, ["estimated_cost", "estimated_loss", "loss", "cost"])
    downtime_col = _find_column(columns, ["downtime"])
    defect_col = _find_column(columns, ["defect"])
    vibration_col = _find_column(columns, ["vibration"])
    maintenance_col = _find_column(columns, ["maintenance"])
    asset_col = _find_column(columns, ["asset_id", "asset"])
    asset_name_col = _find_column(columns, ["asset_name"])
    line_col = _find_column(columns, ["production_line", "line"])
    shift_col = _find_column(columns, ["shift"])
    priority_col = _find_column(columns, ["priority"])

    issue_text = f"{group_label} {group_value}"
    owner = _owner_for_issue(issue_text, columns)

    facts = {
        "rows": int(len(group)),
        "total_estimated_cost": _round_metric(group[loss_col].sum()) if loss_col else None,
        "total_downtime": _round_metric(group[downtime_col].sum()) if downtime_col else None,
        "total_defects": _round_metric(group[defect_col].sum()) if defect_col else None,
        "average_vibration": _round_metric(group[vibration_col].mean()) if vibration_col else None,
    }

    check_fields = {
        "asset_id": _column_value(worst_row, asset_col),
        "asset_name": _column_value(worst_row, asset_name_col),
        "production_line": _column_value(worst_row, line_col),
        "shift": _column_value(worst_row, shift_col),
        "maintenance_status": _column_value(worst_row, maintenance_col),
        "priority": _column_value(worst_row, priority_col),
        "estimated_cost": _column_value(worst_row, loss_col),
        "downtime": _column_value(worst_row, downtime_col),
        "defect_count": _column_value(worst_row, defect_col),
        "vibration": _column_value(worst_row, vibration_col),
    }
    check_fields = {key: value for key, value in check_fields.items() if value is not None}

    if owner.startswith("Quality"):
        first_action = (
            "Start with the highest-cost row for this issue, contain the affected output, "
            "and compare defect_count by asset, line, and shift before broad process changes."
        )
    elif owner.startswith("Maintenance"):
        first_action = (
            "Inspect the named asset/line first, using downtime, maintenance_status, and vibration "
            "to decide whether this is equipment wear, sensor reliability, or scheduling delay."
        )
    elif owner.startswith("Supply"):
        first_action = (
            "Check the affected line and shift against material availability, then isolate whether "
            "the loss is from shortage timing or downstream downtime."
        )
    elif owner.startswith("Production"):
        first_action = (
            "Review the exact changeover/setup rows by line and shift, then standardize the step "
            "that created the largest cost or downtime outlier."
        )
    else:
        first_action = (
            "Use the worst row as the starting point, assign one owner, and validate the highest "
            "cost, downtime, and quality signals before scaling the fix."
        )

    metrics_to_watch = _metric_watch_list(columns)

    return {
        "issue": f"{group_label}={group_value}",
        "why_it_matters": facts,
        "check_first": check_fields,
        "owner": owner,
        "first_next_shift_action": first_action,
        "metric_to_watch": metrics_to_watch,
        "worst_row": worst_row,
    }


def _build_concrete_action_plan(df: Any) -> List[Dict[str, Any]]:
    if df.empty:
        return []

    columns = [str(column) for column in df.columns]
    loss_col = _find_column(columns, ["estimated_cost", "estimated_loss", "loss", "cost"])
    downtime_col = _find_column(columns, ["downtime"])
    defect_col = _find_column(columns, ["defect"])
    vibration_col = _find_column(columns, ["vibration"])
    delay_col = _find_column(columns, ["delay_reason", "delay", "issue", "reason", "status"])
    maintenance_col = _find_column(columns, ["maintenance"])
    priority_col = _find_column(columns, ["priority", "severity"])
    asset_col = _find_column(columns, ["asset_id", "asset"])
    line_col = _find_column(columns, ["production_line", "line"])
    shift_col = _find_column(columns, ["shift"])

    rank_col = loss_col or downtime_col or defect_col or vibration_col
    action_items: List[Dict[str, Any]] = []

    primary_group_col = delay_col or maintenance_col or priority_col or asset_col or line_col or shift_col
    if primary_group_col:
        for group_value, group in df.groupby(primary_group_col, dropna=True):
            action = _build_action_plan_for_group(
                primary_group_col,
                group_value,
                group,
                columns,
                rank_col,
            )
            if action:
                action_items.append(action)

    def action_sort_key(action: Dict[str, Any]) -> tuple:
        facts = action.get("why_it_matters") or {}
        return (
            facts.get("total_estimated_cost") or 0,
            facts.get("total_downtime") or 0,
            facts.get("total_defects") or 0,
            facts.get("average_vibration") or 0,
        )

    action_items.sort(key=action_sort_key, reverse=True)
    return action_items[:6]


def _format_action_plan_findings(action_plan: List[Dict[str, Any]]) -> List[str]:
    findings = []
    for item in action_plan[:6]:
        facts = item.get("why_it_matters") or {}
        check_first = item.get("check_first") or {}
        check_text = ", ".join(
            f"{key}={_format_finding_value(value)}" for key, value in check_first.items()
        )
        metrics = ", ".join(item.get("metric_to_watch") or [])
        findings.append(
            f"Concrete action plan: issue={item.get('issue')} | owner={item.get('owner')} | "
            f"rows={facts.get('rows')} | total_estimated_cost={_format_finding_value(facts.get('total_estimated_cost'))} | "
            f"total_downtime={_format_finding_value(facts.get('total_downtime'))} | "
            f"total_defects={_format_finding_value(facts.get('total_defects'))} | "
            f"check_first={check_text} | first_next_shift_action={item.get('first_next_shift_action')} | "
            f"metric_to_watch={metrics}."
        )
    return findings


def _build_cost_delay_findings(df: Any) -> List[str]:
    """Deterministic cost-vs-delay facts for spreadsheet chat grounding."""
    columns = [str(column) for column in df.columns]
    delay_col = _find_column(columns, ["delay_reason", "delay"])
    loss_col = _find_column(columns, ["estimated_loss", "loss", "cost"])
    downtime_col = _find_column(columns, ["downtime"])
    defect_col = _find_column(columns, ["defect"])
    asset_col = _find_column(columns, ["asset_id", "asset"])
    line_col = _find_column(columns, ["production_line", "line"])
    shift_col = _find_column(columns, ["shift"])
    maintenance_col = _find_column(columns, ["maintenance"])

    if not delay_col or not loss_col:
        return []

    working_df = df.copy()
    working_df[delay_col] = working_df[delay_col].fillna("Unknown").astype(str)
    grouped = working_df.groupby(delay_col, dropna=False)
    findings: List[str] = []

    delay_totals = []
    for delay_reason, group in grouped:
        row = {
            "delay_reason": delay_reason,
            "rows": int(len(group)),
            "estimated_loss_total": _round_metric(group[loss_col].sum()),
        }
        if downtime_col:
            row["downtime_total"] = _round_metric(group[downtime_col].sum())
            row["downtime_avg"] = _round_metric(group[downtime_col].mean())
        if defect_col:
            row["defect_total"] = _round_metric(group[defect_col].sum())
            row["defect_avg"] = _round_metric(group[defect_col].mean())
        delay_totals.append(row)

    delay_totals.sort(
        key=lambda item: (
            item.get("estimated_loss_total") or 0,
            item.get("downtime_total") or 0,
            item.get("defect_total") or 0,
        ),
        reverse=True,
    )

    findings.append(
        "Cost-delay correlation: group results by delay_reason using estimated_loss, downtime, and defect_count."
    )
    for item in delay_totals[:6]:
        parts = [
            f"delay_reason={item['delay_reason']}",
            f"rows={item['rows']}",
            f"estimated_loss_total={_format_finding_value(item.get('estimated_loss_total'))}",
        ]
        if item.get("downtime_total") is not None:
            parts.append(f"downtime_total={_format_finding_value(item.get('downtime_total'))}")
            parts.append(f"downtime_avg={_format_finding_value(item.get('downtime_avg'))}")
        if item.get("defect_total") is not None:
            parts.append(f"defect_total={_format_finding_value(item.get('defect_total'))}")
            parts.append(f"defect_avg={_format_finding_value(item.get('defect_avg'))}")

        group = working_df[working_df[delay_col].astype(str) == str(item["delay_reason"])]
        context_cols = [column for column in [asset_col, line_col, shift_col, maintenance_col] if column]
        if context_cols and loss_col:
            worst = group.sort_values(loss_col, ascending=False).head(1)
            if not worst.empty:
                parts.append(f"worst_row={_row_label(_records_for_model(worst, limit=1)[0])}")
        findings.append(" | ".join(parts) + ".")

    return findings


def _build_spreadsheet_findings(df: Any, profile: Dict[str, Any]) -> List[str]:
    findings: List[str] = []
    findings.extend(_build_numeric_comparison_findings(df))
    findings.extend(_build_cost_delay_findings(df))
    action_plan = _build_concrete_action_plan(df)
    findings.extend(_format_action_plan_findings(action_plan))
    operational = profile.get("operational_summary", {})

    planned = operational.get("planned_vs_actual")
    if planned:
        findings.append(
            "Production shortfall: planned_total="
            f"{_format_finding_value(planned.get('planned_total'))}, actual_total="
            f"{_format_finding_value(planned.get('actual_total'))}, shortfall_total="
            f"{_format_finding_value(planned.get('shortfall_total'))}, average_attainment_pct="
            f"{_format_finding_value(planned.get('average_attainment_pct'))}."
        )

    for key, label in [
        ("downtime", "Downtime"),
        ("defects", "Defects"),
        ("vibration", "Vibration"),
        ("estimated_loss", "Estimated loss"),
    ]:
        metric = operational.get(key)
        if not metric:
            continue
        findings.append(
            f"{label}: total={_format_finding_value(metric.get('total'))}, "
            f"average={_format_finding_value(metric.get('average'))}, max={_format_finding_value(metric.get('max'))}, "
            f"first={_format_finding_value(metric.get('first'))}, last={_format_finding_value(metric.get('last'))}."
        )

    for key, label in [
        ("delay_reason_counts", "Delay reasons"),
        ("maintenance_status_counts", "Maintenance status"),
        ("priority_counts", "Priority"),
    ]:
        counts = operational.get(key)
        if counts:
            top_counts = ", ".join(f"{name}={count}" for name, count in list(counts.items())[:5])
            findings.append(f"{label}: {top_counts}.")

    group_summary = profile.get("group_summary", {})
    for group_name in ["production_line", "asset_id", "facility", "shift"]:
        if group_name not in group_summary:
            continue
        group_bits = []
        for metric_name in [
            "downtime_total",
            "defect_total",
            "estimated_loss_total",
            "actual_shortfall_total",
        ]:
            label = _top_group_label(profile, group_name, metric_name)
            if label:
                group_bits.append(label)
        if group_bits:
            findings.append(f"Worst {group_name} signals: " + " | ".join(group_bits[:3]) + ".")

    high_risk_rows = profile.get("highest_risk_rows", {})
    for key, label in [
        ("highest_downtime_rows", "Highest downtime row"),
        ("highest_defect_rows", "Highest defect row"),
        ("highest_vibration_rows", "Highest vibration row"),
        ("highest_loss_rows", "Highest loss row"),
        ("largest_actual_vs_planned_shortfall_rows", "Largest production shortfall row"),
    ]:
        rows = high_risk_rows.get(key) or []
        if rows:
            findings.append(f"{label}: {_row_label(rows[0])}.")

    findings.append(
        "Specific next-action guidance: tie actions to the worst production_line, asset_id, shift, "
        "delay_reason, maintenance_status, downtime, defect_count, vibration, and estimated_loss values above."
    )
    return findings[:24]


# ==================== Request/Response Schemas ====================

class NLPQueryRequest(BaseModel):
    """Request for NLP query to correlation AI"""
    query: str = Field(..., description="Natural language query")
    context: Optional[Dict[str, Any]] = Field(default={}, description="Additional context for the query")
    include_domains: Optional[List[str]] = Field(default=None, description="Specific domains to analyze")
    auto_integrate: bool = Field(default=True, description="Auto-integrate with registries/Kanban")


class NLPQueryResponse(BaseModel):
    """Response from NLP correlation AI query"""
    query: str
    analysis: str
    domains_analyzed: List[str]
    risk_score: float
    recommended_actions: List[Dict[str, Any]]
    kanban_tasks: List[Dict[str, Any]]
    compliance_implications: Optional[List[str]]
    integration_result: Optional[Dict[str, List[str]]]


class IntakeUploadRequest(BaseModel):
    """Request for Intake Inbox data upload"""
    title: str = Field(..., description="Title of the uploaded data")
    description: Optional[str] = Field(default="", description="Description of the data")
    data_type: str = Field(..., description="Type of data: spreadsheet, report, image, document")
    category: Optional[str] = Field(default="general", description="Category for organization")


class IntakeAnalysisRequest(BaseModel):
    """Request for analyzing uploaded data"""
    intake_id: UUID = Field(..., description="Intake item ID")
    query: Optional[str] = Field(default=None, description="Specific query for analysis")
    auto_integrate: bool = Field(default=True, description="Auto-integrate with registries/Kanban")


class IntakeItem(BaseModel):
    """Intake Inbox item"""
    id: UUID
    title: str
    description: str
    data_type: str
    category: str
    file_name: Optional[str]
    status: str
    analysis_result: Optional[Dict[str, Any]]
    created_at: datetime
    analyzed_at: Optional[datetime]


class IntakeListResponse(BaseModel):
    """Response for listing intake items"""
    items: List[IntakeItem]
    total: int


# ==================== NLP Query Endpoints ====================

@router.post("/query", response_model=NLPQueryResponse)
async def nlp_query(
    request: NLPQueryRequest,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Process natural language query to correlation AI.
    
    This endpoint:
    1. Parses the natural language query
    2. Determines relevant domains from the query
    3. Runs correlation AI analysis
    4. Returns actionable insights and recommendations
    5. Optionally auto-integrates with registries and Kanban
    """
    logger.info("nlp_query_received", user_id=str(current_user.id), query=request.query)
    
    # Parse query to extract domains and context
    domains = request.include_domains or _extract_domains_from_query(request.query)
    
    # Create a correlation scenario from the NLP query
    from app.models.domain_interaction import CorrelationScenario, DomainType, OperationalMetric
    from datetime import datetime
    
    domain_types = [DomainType(d) for d in domains] if domains else []
    
    # Extract operational context from query
    operational_metrics = _extract_metrics_from_query(request.query, request.context)
    
    scenario = CorrelationScenario(
        scenario_id=f"nlp-{current_user.id}-{int(datetime.utcnow().timestamp())}",
        active_domains=domain_types,
        operational_metrics=operational_metrics,
        domain_links=[]
    )
    
    # Run correlation AI analysis
    analysis_result = await correlation_ai_engine.analyze_scenario(
        scenario,
        db,
        organization_id=current_user.organization_id,
        user_id=current_user.id,
        auto_integrate=request.auto_integrate
    )
    
    # Extract results
    correlation_analysis = analysis_result.get("predicted_root_cause", "")
    risk_score = analysis_result.get("risk_score", 0)
    recommended_tasks = analysis_result.get("target_kanban_tasks", [])
    recommended_commands = analysis_result.get("remediation_commands", [])
    compliance_implications = analysis_result.get("compliance_implications")
    integration_result = analysis_result.get("integration_result")
    
    return NLPQueryResponse(
        query=request.query,
        analysis=correlation_analysis,
        domains_analyzed=domains,
        risk_score=risk_score,
        recommended_actions=recommended_commands,
        kanban_tasks=recommended_tasks,
        compliance_implications=compliance_implications,
        integration_result=integration_result
    )


@router.post("/chat")
async def nlp_chat(
    message: str,
    conversation_history: Optional[List[Dict[str, str]]] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Chat interface for correlation AI interaction.
    
    This provides a conversational interface for interacting with the correlation AI.
    Maintains conversation context for multi-turn queries.
    """
    logger.info("nlp_chat_message", user_id=str(current_user.id), message=message)
    
    # Process message with conversation history
    context = {
        "conversation_history": conversation_history or [],
        "user_id": str(current_user.id)
    }
    
    # Parse message as NLP query
    nlp_request = NLPQueryRequest(
        query=message,
        context=context,
        auto_integrate=False  # Don't auto-integrate in chat mode
    )
    
    # Run analysis
    response = await nlp_query(nlp_request, None, db, current_user)
    
    # Format as chat response
    chat_response = {
        "role": "assistant",
        "content": f"{response.analysis}\n\nRisk Score: {response.risk_score}/100",
        "analysis": response.analysis,
        "risk_score": response.risk_score,
        "domains": response.domains_analyzed,
        "actions": response.recommended_actions,
        "timestamp": datetime.utcnow().isoformat()
    }
    
    return chat_response


# ==================== Intake Inbox Endpoints ====================

@router.post("/intake/upload")
async def upload_to_intake(
    file: UploadFile = File(...),
    title: str = None,
    description: str = "",
    data_type: str = "document",
    category: str = "general",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Upload data to Intake Inbox for correlation AI analysis.
    
    Supports:
    - Spreadsheets (CSV, Excel)
    - Reports (PDF, Word)
    - Images (PNG, JPG) - if Gemma4 supports vision
    - Documents (Text files)
    """
    logger.info(
        "intake_upload",
        user_id=str(current_user.id),
        filename=file.filename,
        data_type=data_type
    )
    
    # Validate file type
    allowed_extensions = {
        "spreadsheet": [".csv", ".xlsx", ".xls"],
        "report": [".pdf", ".docx", ".doc"],
        "image": [".png", ".jpg", ".jpeg"],
        "document": [".txt", ".md"]
    }
    
    file_ext = file.filename.split(".")[-1].lower() if file.filename else ""
    if data_type in allowed_extensions and f".{file_ext}" not in allowed_extensions[data_type]:
        raise HTTPException(status_code=400, detail=f"Invalid file extension for type {data_type}")
    
    # Read file content
    content = await file.read()
    
    # Process file content based on type
    processed_data = await _process_uploaded_file(content, data_type, file.filename)
    
    # Store in database
    import base64
    file_content_b64 = base64.b64encode(content).decode('utf-8')
    
    intake_item = IntakeItem(
        user_id=current_user.id,
        organization_id=current_user.organization_id,
        title=title or file.filename,
        description=description,
        data_type=data_type,
        category=category,
        file_name=file.filename,
        file_content=file_content_b64,
        processed_data=processed_data,
        status="pending"
    )
    
    db.add(intake_item)
    await db.commit()
    await db.refresh(intake_item)
    
    logger.info("intake_upload_complete", intake_id=str(intake_item.id))
    
    return {
        "id": str(intake_item.id),
        "title": intake_item.title,
        "description": intake_item.description,
        "data_type": intake_item.data_type,
        "category": intake_item.category,
        "file_name": intake_item.file_name,
        "status": intake_item.status,
        "created_at": intake_item.created_at.isoformat(),
        "analyzed_at": intake_item.analyzed_at.isoformat() if intake_item.analyzed_at else None
    }


@router.post("/intake/analyze")
async def analyze_intake(
    intake_id: UUID,
    query: Optional[str] = None,
    auto_integrate: bool = True,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_active_user)
):
    """
    Analyze uploaded data in Intake Inbox with correlation AI.
    
    This endpoint:
    1. Retrieves the uploaded data
    2. Processes the data with correlation AI
    3. Returns actionable insights
    4. Optionally integrates with registries and Kanban
    """
    logger.info(
        "intake_analysis",
        user_id=str(current_user.id),
        intake_id=str(intake_id)
    )
    
    # In production, retrieve from database
    # For now, we'll simulate the analysis
    
    # Create NLP query from the data
    if query:
        nlp_request = NLPQueryRequest(
            query=query,
            auto_integrate=auto_integrate
        )
    else:
        # Generate a default query from the data type
        default_query = f"Analyze the uploaded {intake_id} data for operational anomalies and correlations"
        nlp_request = NLPQueryRequest(
            query=default_query,
            auto_integrate=auto_integrate
        )
    
    # Run analysis
    response = await nlp_query(nlp_request, None, db, current_user)
    
    analysis_result = {
        "intake_id": str(intake_id),
        "analysis": response.analysis,
        "risk_score": response.risk_score,
        "domains_analyzed": response.domains_analyzed,
        "recommended_actions": response.recommended_actions,
        "kanban_tasks": response.kanban_tasks,
        "compliance_implications": response.compliance_implications,
        "integration_result": response.integration_result,
        "analyzed_at": datetime.utcnow().isoformat()
    }
    
    return analysis_result


@router.get("/intake/list")
async def list_intake_items(
    limit: int = 50,
    offset: int = 0,
    status: Optional[str] = None,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    List items in Intake Inbox.
    
    Returns paginated list of uploaded data items with their analysis status.
    """
    logger.info(
        "intake_list",
        user_id=str(current_user.id),
        limit=limit,
        offset=offset,
        status=status
    )
    
    # Build query
    query = select(IntakeItemModel).where(IntakeItemModel.user_id == current_user.id)
    
    if status:
        query = query.where(IntakeItemModel.status == status)
    
    # Get total count
    count_query = select(func.count()).select_from(query.subquery())
    count_result = await db.execute(count_query)
    total = count_result.scalar()
    
    # Get items
    query = query.order_by(IntakeItemModel.created_at.desc())
    query = query.limit(limit).offset(offset)
    result = await db.execute(query)
    items = result.scalars().all()
    
    return {
        "items": [
            {
                "id": str(item.id),
                "title": item.title,
                "description": item.description,
                "data_type": item.data_type,
                "category": item.category,
                "file_name": item.file_name,
                "status": item.status,
                "created_at": item.created_at.isoformat(),
                "analyzed_at": item.analyzed_at.isoformat() if item.analyzed_at else None
            }
            for item in items
        ],
        "total": total
    }


@router.get("/intake/{intake_id}")
async def get_intake_item(
    intake_id: UUID,
    current_user: User = Depends(get_current_active_user),
    db: AsyncSession = Depends(get_db)
):
    """
    Get details of a specific Intake Inbox item.
    """
    logger.info("intake_get_item", user_id=str(current_user.id), intake_id=str(intake_id))
    
    # Retrieve from database
    from sqlalchemy import select
    query = select(IntakeItem).where(
        IntakeItem.id == intake_id,
        IntakeItem.user_id == current_user.id
    )
    result = await db.execute(query)
    item = result.scalar_one_or_none()
    
    if not item:
        raise HTTPException(status_code=404, detail="Intake item not found")
    
    return {
        "id": str(item.id),
        "title": item.title,
        "description": item.description,
        "data_type": item.data_type,
        "category": item.category,
        "file_name": item.file_name,
        "status": item.status,
        "processed_data": item.processed_data,
        "analysis_result": item.analysis_result,
        "created_at": item.created_at.isoformat(),
        "analyzed_at": item.analyzed_at.isoformat() if item.analyzed_at else None
    }


# ==================== Helper Functions ====================

def _extract_domains_from_query(query: str) -> List[str]:
    """Extract relevant domains from natural language query"""
    query_lower = query.lower()
    
    domain_keywords = {
        "LOGISTICS_FLEET": ["trailer", "truck", "dock", "yard", "detention", "carrier", "driver", "shipment", "logistics"],
        "MAINTENANCE": ["maintenance", "equipment", "vibration", "temperature", "work order", "technician", "repair"],
        "PRODUCTION_OEE": ["production", "oee", "throughput", "cycle time", "quality rate", "asset", "cell", "manufacturing"],
        "QUALITY_CONTROL": ["quality", "inspection", "defect", "first pass yield", "capa", "non-conformance"],
        "SAFETY": ["safety", "incident", "security", "hazard", "compliance", "near-miss", "accident"],
        "COMPLIANCE_REGISTRIES": ["compliance", "audit", "regulatory", "iso", "osha", "dot", "violation"],
        "WAREHOUSE_MANAGEMENT": ["warehouse", "inventory", "slot", "storage", "fulfillment", "stockout"],
        "SYSTEM_INFRASTRUCTURE": ["network", "database", "latency", "infrastructure", "availability", "error rate", "it"]
    }
    
    detected_domains = []
    for domain, keywords in domain_keywords.items():
        if any(keyword in query_lower for keyword in keywords):
            detected_domains.append(domain)
    
    return detected_domains


def _extract_metrics_from_query(query: str, context: Dict[str, Any]) -> List:
    """Extract operational metrics from query and context"""
    from app.models.domain_interaction import OperationalMetric
    from datetime import datetime
    
    metrics = []
    
    # Extract numeric values from query
    import re
    numbers = re.findall(r'\d+\.?\d*', query)
    
    if numbers:
        for i, num in enumerate(numbers):
            metric = OperationalMetric(
                metric_name=f"query_metric_{i}",
                value=float(num),
                unit=None,
                timestamp=datetime.utcnow(),
                meta_data={"source": "nlp_query", "context": context}
            )
            metrics.append(metric)
    
    # Add context metrics if available
    if context:
        for key, value in context.items():
            if isinstance(value, (int, float)):
                metric = OperationalMetric(
                    metric_name=f"context_{key}",
                    value=float(value),
                    unit=None,
                    timestamp=datetime.utcnow(),
                    meta_data={"source": "nlp_query_context"}
                )
                metrics.append(metric)
    
    return metrics


async def _process_uploaded_file(content: bytes, data_type: str, filename: str) -> Dict[str, Any]:
    """Process uploaded file content based on type"""
    
    try:
        if data_type == "spreadsheet":
            # For CSV/Excel files
            import pandas as pd
            import io
            
            if filename.lower().endswith('.csv'):
                df = pd.read_csv(io.BytesIO(content))
            elif filename.lower().endswith('.xlsx'):
                df = pd.read_excel(io.BytesIO(content), engine='openpyxl')
            elif filename.lower().endswith('.xls'):
                df = pd.read_excel(io.BytesIO(content), engine='xlrd')
            else:
                df = pd.read_csv(io.StringIO(content.decode('utf-8')))
            
            full_sheet_profile = _build_spreadsheet_profile(df) if not df.empty else {}
            concrete_action_plan = _build_concrete_action_plan(df) if not df.empty else []
            numeric_comparisons = _build_numeric_comparison_findings(df) if not df.empty else []
            distilled_findings = _build_spreadsheet_findings(df, full_sheet_profile) if full_sheet_profile else []

            return {
                "type": "spreadsheet",
                "rows": len(df),
                "columns": len(df.columns),
                "column_names": [str(column) for column in df.columns.tolist()],
                "sample_data": _records_for_model(df, limit=5),
                "tail_sample_data": _records_for_model(df.tail(5), limit=5),
                "summary": _json_safe(df.describe().to_dict()) if not df.empty else {},
                "full_sheet_profile": full_sheet_profile,
                "concrete_action_plan": concrete_action_plan,
                "numeric_comparisons": numeric_comparisons,
                "distilled_findings": distilled_findings,
            }
        
        elif data_type == "image":
            # For image files - extract text if possible (OCR)
            # This would require integration with OCR service
            return {
                "type": "image",
                "size": len(content),
                "format": filename.split('.')[-1],
                "note": "Image processing requires vision model integration"
            }
        
        elif data_type in ["report", "document"]:
            # For text documents
            text_content = content.decode('utf-8')
            return {
                "type": data_type,
                "size": len(content),
                "content": text_content,
                "word_count": len(text_content.split())
            }
        
        else:
            return {
                "type": data_type,
                "size": len(content)
            }
    
    except Exception as e:
        logger.error("file_processing_error", error=str(e), data_type=data_type)
        return {
            "type": data_type,
            "size": len(content),
            "error": str(e)
        }
