"""
100-Company 10-Fiscal-Year Stress-Test Dataset Generator
========================================================

Generates, per company (100 total) and per fiscal year (FY2015-FY2024):
  - One Excel workbook per fiscal year (1,000 workbooks total) with hybrid tabs:
      * Full-timeline tabs (one row per shift): Production_Operations,
        Maintenance_Assets, Quality_Control, Logistics_Supply_Chain, and an
        industry-specialty tab.
      * Event-based tabs (sparse): Safety_Compliance, Business_Operations,
        Workforce_HR, IT_Infrastructure, Planning_Analytics, Continuous_Improvement.
  - Shared date/shift/asset_id keys across tabs for cross-tab correlation.
  - Seasonality, equipment degradation (cumulative across years), and clustered,
    co-timed anomalies.

Phase 6 (OmniusGrid compatibility) optional outputs:
  - Per-tab CSV export (--csv)
  - Long-format telemetry CSV (--telemetry)
  - CorrelationScenario JSONL via shared keys (--scenarios)
  - domain_mapping.json, company_manifest.csv, generation_summary.json

Robustness: deterministic per-company seeds, multiprocessing, checkpoint/resume
(skip companies whose workbooks already exist), structured logging, per-company
isolation.

Usage (examples):
    python generate_stress_test_dataset.py --out ./output --workers 8
    python generate_stress_test_dataset.py --out ./output --companies 2 --years 2 --csv --scenarios   # quick smoke test
"""

import argparse
import calendar
import json
import logging
import os
import random
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Dict, List, Any, Tuple, Optional

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from industry_profiles import all_companies, INDUSTRIES  # noqa: E402

SHIFTS = ["Day", "Night", "Weekend"]
FISCAL_YEARS = list(range(2015, 2025))  # FY2015..FY2024 (10 years)
BASE_SEED = 20260607

# Tab -> OmniusGrid DomainType (mirrors backend spreadsheet_domain_mapper)
TAB_DOMAIN = {
    "Production_Operations": "PRODUCTION_OEE",
    "Maintenance_Assets": "MAINTENANCE",
    "Quality_Control": "QUALITY_CONTROL",
    "Logistics_Supply_Chain": "LOGISTICS_FLEET",
    "Safety_Compliance": "SAFETY",
    "Business_Operations": "FINANCE",
    "Workforce_HR": "WORKFORCE_MANAGEMENT",
    "IT_Infrastructure": "SYSTEM_INFRASTRUCTURE",
    "Planning_Analytics": "PLANNING_SCHEDULING",
    "Continuous_Improvement": "CONTINUOUS_IMPROVEMENT",
}

FULL_TIMELINE_TABS = [
    "Production_Operations", "Maintenance_Assets",
    "Quality_Control", "Logistics_Supply_Chain",
]
EVENT_TABS = [
    "Safety_Compliance", "Business_Operations", "Workforce_HR",
    "IT_Infrastructure", "Planning_Analytics", "Continuous_Improvement",
]

logger = logging.getLogger("stressgen")


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #
def _year_dates(year: int) -> List[date]:
    days = 366 if calendar.isleap(year) else 365
    start = date(year, 1, 1)
    return [start + timedelta(days=i) for i in range(days)]


def _seasonal_factor(d: date) -> float:
    """Sinusoidal seasonality peaking mid-year (Q2-Q3)."""
    doy = d.timetuple().tm_yday
    return 1.0 + 0.15 * np.sin(2 * np.pi * (doy - 80) / 365.0)


def _shift_factor(shift: str) -> float:
    return {"Day": 1.0, "Night": 0.82, "Weekend": 0.55}[shift]


def _anomaly_windows(rng: random.Random, year: int) -> List[Tuple[date, date]]:
    """3-6 clustered anomaly windows per year, each 3-7 consecutive days."""
    n = rng.randint(3, 6)
    windows = []
    days = 366 if calendar.isleap(year) else 365
    for _ in range(n):
        start_doy = rng.randint(1, max(1, days - 8))
        length = rng.randint(3, 7)
        start = date(year, 1, 1) + timedelta(days=start_doy - 1)
        windows.append((start, start + timedelta(days=length - 1)))
    return windows


def _in_window(d: date, windows: List[Tuple[date, date]]) -> bool:
    return any(s <= d <= e for s, e in windows)


def _spec_value(rng: random.Random, spec: Tuple[str, Any]) -> Any:
    kind, params = spec
    if kind == "float":
        return round(rng.uniform(*params), 3)
    if kind == "int":
        return rng.randint(*params)
    if kind == "choice":
        return rng.choice(params)
    if kind == "id":
        return f"{params}-{rng.randint(0, 99999):05d}"
    return None


# --------------------------------------------------------------------------- #
# Per-tab generators
# --------------------------------------------------------------------------- #
def _gen_production(dates, rng, state, windows, company) -> pd.DataFrame:
    rows = []
    for d in dates:
        season = _seasonal_factor(d)
        for shift in SHIFTS:
            anomaly = _in_window(d, windows) and rng.random() < 0.7
            sf = _shift_factor(shift)
            planned = int(rng.randint(800, 1500) * sf * season)
            base_oee = rng.uniform(75, 88)
            if anomaly:
                oee = max(20.0, base_oee - rng.uniform(20, 45))
                status = "critical" if oee < 45 else "warning"
                downtime = rng.randint(60, 400)
            else:
                oee = base_oee + rng.uniform(-4, 4)
                status = "normal"
                downtime = rng.randint(0, 60)
            actual = int(planned * (oee / 100.0) * rng.uniform(0.92, 1.0))
            rows.append({
                "date": d.isoformat(), "shift": shift,
                "facility": state["facility"], "production_line": state["line"],
                "asset_id": state["asset_id"], "asset_name": state["asset_name"],
                "planned_units": planned, "actual_units": actual,
                "downtime_minutes": downtime, "oee_score": round(oee, 1),
                "throughput_units_per_hour": round(actual / 8.0, 1),
                "cycle_time_seconds": round(rng.uniform(10, 60), 1),
                "production_order_id": f"PO-{rng.randint(0,999999):06d}",
                "customer_id": f"CUST-{rng.randint(1,500):03d}",
                "scrap_units": rng.randint(0, 60) if anomaly else rng.randint(0, 10),
                "status": status,
            })
    return pd.DataFrame(rows)


def _gen_maintenance(dates, rng, state, windows, company) -> pd.DataFrame:
    rows = []
    for d in dates:
        for shift in SHIFTS:
            anomaly = _in_window(d, windows) and rng.random() < 0.7
            # cumulative runtime continues across years
            state["runtime_hours"] += _shift_factor(shift) * 8.0
            age_factor = state["runtime_hours"] / 50000.0
            base_vib = 1.0 + age_factor * 1.5 + rng.uniform(-0.2, 0.2)
            if anomaly:
                vib = base_vib + rng.uniform(2.0, 3.5)
                mstatus = "critical" if vib > 4.0 else "warning"
            else:
                vib = base_vib
                mstatus = "ok"
            rows.append({
                "date": d.isoformat(), "shift": shift,
                "facility": state["facility"], "production_line": state["line"],
                "asset_id": state["asset_id"], "asset_name": state["asset_name"],
                "vibration_mm_s": round(max(0.3, vib), 2),
                "temperature_f": round(rng.uniform(65, 85) + (15 if anomaly else 0), 1),
                "pressure_psi": round(rng.uniform(100, 500), 1),
                "runtime_hours": round(state["runtime_hours"], 1),
                "health_score_0_100": round(max(20.0, 100 - age_factor * 40 - (30 if anomaly else 0)), 1),
                "remaining_useful_life_hours": int(max(0, 50000 - state["runtime_hours"])),
                "maintenance_status": mstatus,
                "next_pm_due_date": (d + timedelta(days=rng.randint(5, 90))).isoformat(),
                "status": mstatus,
            })
    return pd.DataFrame(rows)


def _gen_quality(dates, rng, state, windows, company) -> pd.DataFrame:
    rows = []
    for d in dates:
        for shift in SHIFTS:
            anomaly = _in_window(d, windows) and rng.random() < 0.6
            if anomaly:
                defects = rng.randint(40, 150)
                fpy = rng.uniform(70, 88)
                qstatus = "critical" if fpy < 80 else "warning"
            else:
                defects = rng.randint(0, 15)
                fpy = rng.uniform(95, 99.5)
                qstatus = "normal"
            rows.append({
                "date": d.isoformat(), "shift": shift,
                "facility": state["facility"], "production_line": state["line"],
                "asset_id": state["asset_id"], "asset_name": state["asset_name"],
                "defect_count": defects,
                "defect_rate_ppm": int(defects * rng.uniform(30, 80)),
                "first_pass_yield_percent": round(fpy, 1),
                "inspection_pass_rate_percent": round(rng.uniform(80, 100), 1),
                "scrap_units": defects // 2,
                "rework_units": defects // 3,
                "inspection_method": rng.choice(["Visual", "Automated", "Manual", "Destructive"]),
                "status": qstatus,
            })
    return pd.DataFrame(rows)


def _gen_logistics(dates, rng, state, windows, company) -> pd.DataFrame:
    rows = []
    for d in dates:
        for shift in SHIFTS:
            anomaly = _in_window(d, windows) and rng.random() < 0.5
            dwell = rng.randint(200, 480) if anomaly else rng.randint(30, 120)
            status = "delayed" if anomaly else "normal"
            rows.append({
                "date": d.isoformat(), "shift": shift,
                "facility": state["facility"], "location": state["facility"],
                "asset_id": state["asset_id"],
                "dwell_time_minutes": dwell,
                "detention_minutes": rng.randint(0, 300) if anomaly else rng.randint(0, 60),
                "yard_utilization_percent": round(rng.uniform(40, 95), 1),
                "trailer_queue_count": rng.randint(0, 20),
                "tracking_number": f"TRK-{rng.randint(0,99999999):08d}",
                "carrier_name": rng.choice(["FedEx", "UPS", "DHL", "USPS", "LTL"]),
                "inventory_level": rng.randint(100, 10000),
                "stockout_risk": status if anomaly else "low",
                "supplier_id": f"SUP-{rng.randint(1,200):03d}",
                "on_time_delivery_percent": round(rng.uniform(60, 100), 1),
                "status": status,
            })
    return pd.DataFrame(rows)


def _gen_specialty(dates, rng, state, windows, company) -> pd.DataFrame:
    cols = company["specialty_columns"]
    rows = []
    for d in dates:
        for shift in SHIFTS:
            anomaly = _in_window(d, windows) and rng.random() < 0.5
            row = {
                "date": d.isoformat(), "shift": shift,
                "facility": state["facility"], "asset_id": state["asset_id"],
            }
            for col, spec in cols.items():
                row[col] = _spec_value(rng, spec)
            row["status"] = "warning" if anomaly else "normal"
            rows.append(row)
    return pd.DataFrame(rows)


def _event_dates(dates, rng, rate: float) -> List[date]:
    """Sample a sparse set of event dates (rate = avg events per day)."""
    chosen = [d for d in dates if rng.random() < rate]
    return chosen or [rng.choice(dates)]


def _gen_safety(dates, rng, state, windows, company) -> pd.DataFrame:
    rows = []
    for d in _event_dates(dates, rng, 0.05):
        in_anom = _in_window(d, windows)
        sev = rng.choice(["high", "critical"]) if in_anom else rng.choice(["low", "medium"])
        rows.append({
            "date": d.isoformat(), "shift": rng.choice(SHIFTS),
            "facility": state["facility"], "asset_id": state["asset_id"],
            "incident_count": rng.randint(1, 3),
            "near_miss_count": rng.randint(0, 5),
            "incident_severity": sev,
            "safety_observation_id": f"OBS-{rng.randint(0,99999):05d}",
            "compliance_status": rng.choice(["Compliant", "Compliant", "Non-Compliant"]),
            "osha_record_status": rng.choice(["Clear", "Warning", "Citation"]),
            "status": "critical" if sev == "critical" else "warning",
        })
    return pd.DataFrame(rows)


def _gen_business(dates, rng, state, windows, company) -> pd.DataFrame:
    rows = []
    # monthly close + sampled invoices
    for month in range(1, 13):
        d = date(dates[0].year, month, 28)
        rows.append({
            "date": d.isoformat(), "shift": "Day",
            "facility": state["facility"],
            "revenue": round(rng.uniform(1e5, 5e6), 2),
            "cost": round(rng.uniform(8e4, 4e6), 2),
            "profit_margin": round(rng.uniform(-5, 35), 1),
            "invoice_number": f"INV-{rng.randint(0,99999):05d}",
            "invoice_status": rng.choice(["Paid", "Sent", "Overdue"]),
            "currency_code": "USD",
            "cost_center": f"CC-{rng.randint(1,50):03d}",
            "account_code": f"ACC-{rng.randint(10000,99999)}",
            "status": "normal",
        })
    return pd.DataFrame(rows)


def _gen_workforce(dates, rng, state, windows, company) -> pd.DataFrame:
    rows = []
    for d in _event_dates(dates, rng, 0.08):
        anomaly = _in_window(d, windows)
        rows.append({
            "date": d.isoformat(), "shift": rng.choice(SHIFTS),
            "facility": state["facility"], "department": rng.choice(["Prod", "Maint", "QA", "Logistics"]),
            "operator_count": rng.randint(5, 80),
            "overtime_hours": round(rng.uniform(0, 40), 1),
            "absenteeism_percent": round(rng.uniform(0, 30) + (15 if anomaly else 0), 1),
            "shift_change_count": rng.randint(0, 5),
            "training_compliance_percent": round(rng.uniform(70, 100), 1),
            "turnover_rate": round(rng.uniform(0, 25), 1),
            "status": "warning" if anomaly else "normal",
        })
    return pd.DataFrame(rows)


def _gen_it(dates, rng, state, windows, company) -> pd.DataFrame:
    rows = []
    for d in _event_dates(dates, rng, 0.1):
        anomaly = _in_window(d, windows)
        rows.append({
            "date": d.isoformat(), "shift": rng.choice(SHIFTS),
            "facility": state["facility"], "system_id": f"SYS-{rng.randint(1,20):02d}",
            "system_availability_percent": round(100 - (rng.uniform(2, 20) if anomaly else rng.uniform(0, 1)), 2),
            "network_latency_ms": round(rng.uniform(5, 300) + (200 if anomaly else 0), 1),
            "security_vulnerability_count": rng.randint(0, 15),
            "unauthorized_attempts": rng.randint(0, 50),
            "sensor_count": rng.randint(10, 5000),
            "status": "critical" if anomaly else "normal",
        })
    return pd.DataFrame(rows)


def _gen_planning(dates, rng, state, windows, company) -> pd.DataFrame:
    rows = []
    for week in range(0, 52):
        d = dates[0] + timedelta(weeks=week)
        if d.year != dates[0].year:
            break
        rows.append({
            "date": d.isoformat(), "shift": "Day",
            "facility": state["facility"],
            "schedule_adherence_percent": round(rng.uniform(60, 99), 1),
            "forecast_accuracy": round(rng.uniform(50, 98), 1),
            "capacity_utilization_percent": round(rng.uniform(50, 95), 1),
            "inventory_turnover": round(rng.uniform(2, 20), 1),
            "mape_percent": round(rng.uniform(2, 40), 1),
            "status": "normal",
        })
    return pd.DataFrame(rows)


def _gen_improvement(dates, rng, state, windows, company) -> pd.DataFrame:
    rows = []
    for month in range(1, 13):
        d = date(dates[0].year, month, 15)
        rows.append({
            "date": d.isoformat(), "shift": "Day",
            "facility": state["facility"],
            "improvement_idea_count": rng.randint(0, 30),
            "implemented_improvements": rng.randint(0, 10),
            "cost_savings_achieved": round(rng.uniform(0, 200000), 2),
            "process_efficiency_percent": round(rng.uniform(60, 98), 1),
            "waste_reduction_percent": round(rng.uniform(0, 40), 1),
            "status": "normal",
        })
    return pd.DataFrame(rows)


TAB_GENERATORS = {
    "Production_Operations": _gen_production,
    "Maintenance_Assets": _gen_maintenance,
    "Quality_Control": _gen_quality,
    "Logistics_Supply_Chain": _gen_logistics,
    "Safety_Compliance": _gen_safety,
    "Business_Operations": _gen_business,
    "Workforce_HR": _gen_workforce,
    "IT_Infrastructure": _gen_it,
    "Planning_Analytics": _gen_planning,
    "Continuous_Improvement": _gen_improvement,
}


# --------------------------------------------------------------------------- #
# Phase 6: CorrelationScenario emission (window mode)
# --------------------------------------------------------------------------- #
def _emit_scenarios(year_tabs: Dict[str, pd.DataFrame], company, year) -> List[dict]:
    """Build window-mode CorrelationScenario dicts from full-timeline tabs."""
    scenarios = []
    windows: Dict[str, Dict[str, dict]] = {}
    for tab in FULL_TIMELINE_TABS:
        df = year_tabs.get(tab)
        if df is None or df.empty or "date" not in df.columns:
            continue
        for rec in df.to_dict(orient="records"):
            key = f"{rec.get('date')}|{rec.get('shift','')}"
            windows.setdefault(key, {})[tab] = rec
    for i, (key, tabrows) in enumerate(windows.items()):
        domains, metrics = [], []
        max_sev = 0.2
        for tab, rec in tabrows.items():
            dom = TAB_DOMAIN[tab]
            if dom not in domains:
                domains.append(dom)
            status = str(rec.get("status", "normal")).lower()
            sev = 0.85 if status in ("critical",) else 0.5 if status in ("warning", "delayed") else 0.15
            max_sev = max(max_sev, sev)
            metrics.append({
                "endpoint": f"/intake/{dom.lower()}/{tab}",
                "payload_snapshot": rec,
                "timestamp": str(rec.get("date")),
            })
        links = [{
            "source_domain": domains[j], "target_domain": domains[j + 1],
            "interaction_key": str(tabrows[FULL_TIMELINE_TABS[0]]["asset_id"]) if FULL_TIMELINE_TABS[0] in tabrows else key,
            "severity_impact": round(max_sev, 2), "correlation_type": "temporal",
        } for j in range(len(domains) - 1)]
        scenarios.append({
            "scenario_id": f"{company['file_stub']}-FY{year}-win-{i:05d}",
            "active_domains": domains,
            "domain_links": links,
            "ingested_metrics": metrics,
        })
    return scenarios


# --------------------------------------------------------------------------- #
# Per-company generation
# --------------------------------------------------------------------------- #
def generate_company(company: Dict[str, Any], args) -> Dict[str, Any]:
    rng = random.Random(BASE_SEED + company["index"])
    np.random.seed((BASE_SEED + company["index"]) % (2**32))

    out_root = Path(args.out)
    comp_dir = out_root / "companies" / company["file_stub"]
    comp_dir.mkdir(parents=True, exist_ok=True)

    # Cross-year cumulative state
    state = {
        "facility": f"FAC-{company['index']:03d}",
        "line": f"LINE-{rng.randint(1,9)}",
        "asset_id": f"AST-{company['index']:03d}-{rng.randint(1,99):02d}",
        "asset_name": f"{company['slug']}_unit",
        "runtime_hours": rng.uniform(0, 8000),
    }

    years = FISCAL_YEARS[: args.years] if args.years else FISCAL_YEARS
    total_rows = 0
    files_written = 0
    scenarios_written = 0
    telemetry_rows = 0

    specialty_tab = company["specialty_tab"]

    for year in years:
        wb_path = comp_dir / f"{company['file_stub']}_FY{year}.xlsx"
        if wb_path.exists() and not args.overwrite:
            files_written += 1
            continue

        dates = _year_dates(year)
        windows = _anomaly_windows(rng, year)

        year_tabs: Dict[str, pd.DataFrame] = {}
        # Full-timeline + specialty
        year_tabs["Production_Operations"] = _gen_production(dates, rng, state, windows, company)
        year_tabs["Maintenance_Assets"] = _gen_maintenance(dates, rng, state, windows, company)
        year_tabs["Quality_Control"] = _gen_quality(dates, rng, state, windows, company)
        year_tabs["Logistics_Supply_Chain"] = _gen_logistics(dates, rng, state, windows, company)
        year_tabs[specialty_tab] = _gen_specialty(dates, rng, state, windows, company)
        # Event tabs
        for tab in EVENT_TABS:
            year_tabs[tab] = TAB_GENERATORS[tab](dates, rng, state, windows, company)

        # Write workbook
        with pd.ExcelWriter(wb_path, engine="openpyxl") as writer:
            for tab, df in year_tabs.items():
                total_rows += len(df)
                df.to_excel(writer, sheet_name=tab[:31], index=False)
        files_written += 1

        # Phase 6: per-tab CSV
        if args.csv:
            csv_dir = comp_dir / "csv"
            csv_dir.mkdir(exist_ok=True)
            for tab, df in year_tabs.items():
                df.to_csv(csv_dir / f"{company['file_stub']}_FY{year}__{tab}.csv", index=False)

        # Phase 6: long-format telemetry
        if args.telemetry:
            tel_rows = []
            for tab in FULL_TIMELINE_TABS:
                df = year_tabs[tab]
                dom = TAB_DOMAIN[tab]
                num_cols = [c for c in df.columns if pd.api.types.is_numeric_dtype(df[c])]
                for rec in df.to_dict(orient="records"):
                    for c in num_cols:
                        tel_rows.append({
                            "time": rec.get("date"), "asset_id": rec.get("asset_id"),
                            "metric_name": c, "value": rec.get(c), "unit": "",
                            "domain": dom, "organization_id": company["company_id"],
                        })
            if tel_rows:
                tdf = pd.DataFrame(tel_rows)
                tel_dir = comp_dir / "telemetry"
                tel_dir.mkdir(exist_ok=True)
                tdf.to_csv(tel_dir / f"{company['file_stub']}_FY{year}_telemetry.csv", index=False)
                telemetry_rows += len(tdf)

        # Phase 6: scenarios JSONL
        if args.scenarios:
            scen = _emit_scenarios(year_tabs, company, year)
            scen_dir = comp_dir / "scenarios"
            scen_dir.mkdir(exist_ok=True)
            with open(scen_dir / f"{company['file_stub']}_FY{year}_scenarios.jsonl", "w") as f:
                for s in scen:
                    f.write(json.dumps(s, default=str) + "\n")
            scenarios_written += len(scen)

    return {
        "company_id": company["company_id"],
        "slug": company["slug"],
        "industry": company["industry"],
        "files": files_written,
        "rows": total_rows,
        "scenarios": scenarios_written,
        "telemetry_rows": telemetry_rows,
    }


def _worker(args_tuple):
    company, args = args_tuple
    try:
        res = generate_company(company, args)
        logger.info("company_done %s rows=%s files=%s", res["company_id"], res["rows"], res["files"])
        return res
    except Exception as e:  # per-company isolation
        logger.exception("company_failed %s: %s", company["company_id"], e)
        return {"company_id": company["company_id"], "error": str(e)}


def main():
    parser = argparse.ArgumentParser(description="100-company stress-test dataset generator")
    parser.add_argument("--out", default="./output", help="Output directory")
    parser.add_argument("--companies", type=int, default=0, help="Limit number of companies (0=all 100)")
    parser.add_argument("--years", type=int, default=0, help="Limit number of fiscal years (0=all 10)")
    parser.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    parser.add_argument("--csv", action="store_true", help="Also export per-tab CSV")
    parser.add_argument("--telemetry", action="store_true", help="Also export long-format telemetry CSV")
    parser.add_argument("--scenarios", action="store_true", help="Also export CorrelationScenario JSONL")
    parser.add_argument("--overwrite", action="store_true", help="Regenerate existing workbooks")
    args = parser.parse_args()

    out_root = Path(args.out)
    (out_root / "companies").mkdir(parents=True, exist_ok=True)
    (out_root / "documentation").mkdir(parents=True, exist_ok=True)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(),
                  logging.FileHandler(out_root / "generation.log")],
    )

    companies = all_companies()
    if args.companies:
        companies = companies[: args.companies]

    # documentation: domain mapping + manifest
    with open(out_root / "documentation" / "domain_mapping.json", "w") as f:
        json.dump({
            "tab_domain": TAB_DOMAIN,
            "full_timeline_tabs": FULL_TIMELINE_TABS,
            "event_tabs": EVENT_TABS,
            "severity_mapping": {"normal": "0.0-0.3", "warning": "0.3-0.7", "critical": "0.7-1.0"},
            "industries": {k: v["specialty_tab"] for k, v in INDUSTRIES.items()},
        }, f, indent=2)

    logger.info("starting generation companies=%d workers=%d", len(companies), args.workers)

    results = []
    if args.workers > 1 and len(companies) > 1:
        from multiprocessing import Pool
        with Pool(args.workers) as pool:
            results = pool.map(_worker, [(c, args) for c in companies])
    else:
        for c in companies:
            results.append(_worker((c, args)))

    # manifest + summary
    manifest = pd.DataFrame(companies)[["company_id", "slug", "industry", "specialty_tab", "file_stub"]]
    manifest.to_csv(out_root / "documentation" / "company_manifest.csv", index=False)

    summary = {
        "companies": len(companies),
        "fiscal_years": args.years or len(FISCAL_YEARS),
        "total_files": sum(r.get("files", 0) for r in results),
        "total_rows": sum(r.get("rows", 0) for r in results),
        "total_scenarios": sum(r.get("scenarios", 0) for r in results),
        "total_telemetry_rows": sum(r.get("telemetry_rows", 0) for r in results),
        "failures": [r for r in results if "error" in r],
        "results": results,
    }
    with open(out_root / "documentation" / "generation_summary.json", "w") as f:
        json.dump(summary, f, indent=2, default=str)

    logger.info("generation complete files=%s rows=%s failures=%s",
                summary["total_files"], summary["total_rows"], len(summary["failures"]))
    print(json.dumps({k: summary[k] for k in
                      ["companies", "fiscal_years", "total_files", "total_rows",
                       "total_scenarios", "total_telemetry_rows"]}, indent=2))


if __name__ == "__main__":
    main()
