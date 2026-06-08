"""
Spreadsheet Domain Mapper

Maps workbook tabs and columns to OmniusGrid DomainType enum values so that
uploaded spreadsheets/workbooks can be converted into CorrelationScenarios.

The mapper is deterministic: it first tries an explicit tab-name mapping
(matching the synthesized dataset tab structure and common ERP/MES tab names),
then falls back to keyword matching against column names. Tabs that cannot be
mapped to a domain are flagged as "context-only" and are not emitted as
operational metrics (but remain available as scenario metadata).
"""

from typing import Dict, List, Optional
import re

from app.models.domain_interaction import DomainType


# Explicit tab-name -> DomainType mapping (case-insensitive, substring match).
# Keys are normalized (lowercased, non-alnum stripped) before comparison.
TAB_NAME_DOMAIN_MAP: Dict[str, DomainType] = {
    # Synthesized dataset tab groups
    "productionoperations": DomainType.PROD,
    "production": DomainType.PROD,
    "manufacturingexecutionsystem": DomainType.MES,
    "mes": DomainType.MES,
    "logisticssupplychain": DomainType.LOG,
    "logistics": DomainType.LOG,
    "supplychain": DomainType.SUP,
    "warehouse": DomainType.WHS,
    "warehousemanagement": DomainType.WHS,
    "distribution": DomainType.DST,
    "materialreplenishment": DomainType.MAT,
    "maintenanceassets": DomainType.MNT,
    "maintenance": DomainType.MNT,
    "assetlifecycle": DomainType.ALF,
    "spareparts": DomainType.SPT,
    "toolmanagement": DomainType.TOL,
    "calibration": DomainType.CAL,
    "qualitycontrol": DomainType.QUA,
    "quality": DomainType.QUA,
    "safetycompliance": DomainType.SAF,
    "safety": DomainType.SAF,
    "complianceregistries": DomainType.COMP,
    "compliance": DomainType.COMP,
    "regulatoryaudit": DomainType.RGA,
    "environmental": DomainType.ENV,
    "esg": DomainType.ESG,
    "workforcehr": DomainType.WRK,
    "workforce": DomainType.WRK,
    "workforcemanagement": DomainType.WRK,
    "hrorganizational": DomainType.HRO,
    "itinfrastructure": DomainType.SYS,
    "systeminfrastructure": DomainType.SYS,
    "edgeaitelemetry": DomainType.EDGE,
    "telemetry": DomainType.EDGE,
    "cybersecurity": DomainType.CYB,
    "itotintegration": DomainType.IOT,
    "digitaltwin": DomainType.DTW,
    "businessoperations": DomainType.FIN,
    "finance": DomainType.FIN,
    "customerservice": DomainType.CUS,
    "projectmanagement": DomainType.PRJ,
    "contractmanagement": DomainType.CTR,
    "planninganalytics": DomainType.PLN,
    "planningscheduling": DomainType.PLN,
    "dataanalytics": DomainType.DAN,
    "businessintelligence": DomainType.BI,
    "inventoryoptimization": DomainType.INO,
    "continuousimprovement": DomainType.CIM,
    "processoptimization": DomainType.POP,
    "productlifecycle": DomainType.PLC,
    "innovationrd": DomainType.IRD,
    "supplierrelationship": DomainType.SRL,
    "changemanagement": DomainType.CHM,
    "knowledgemanagement": DomainType.KMG,
    "riskmanagement": DomainType.RSK,
    "facilitiesmanagement": DomainType.FAC,
    "documentmanagement": DomainType.DOC,
    "workflowmanagement": DomainType.WFM,
    "energymanagement": DomainType.ENG,
    "packaging": DomainType.PKG,
    "productionoutput": DomainType.OUT,
}


# Column keyword -> DomainType fallback mapping.
COLUMN_KEYWORD_DOMAIN_MAP: Dict[DomainType, List[str]] = {
    DomainType.LOG: ["trailer", "truck", "dock", "yard", "detention", "carrier",
                     "driver", "shipment", "tracking_number", "freight", "transit"],
    DomainType.MNT: ["maintenance", "vibration", "work_order", "technician",
                     "downtime", "runtime_hours", "failure_probability", "pm_schedule"],
    DomainType.PROD: ["oee", "throughput", "cycle_time", "planned_units",
                      "actual_units", "production_order", "changeover"],
    DomainType.QUA: ["defect", "inspection", "first_pass_yield", "scrap",
                     "rework", "quality_rate", "recall"],
    DomainType.SAF: ["incident", "near_miss", "hazard", "injury", "safety_observation"],
    DomainType.COMP: ["audit", "iso_", "osha", "dot_", "fda", "epa", "compliance_score"],
    DomainType.WHS: ["bin_location", "putaway", "pick_time", "slot_utilization", "storage_bin"],
    DomainType.SYS: ["network_latency", "database_response", "system_availability",
                     "security_vulnerability", "data_transmission"],
    DomainType.FIN: ["revenue", "profit_margin", "invoice", "budget", "cost_center",
                     "account_code", "journal_entry", "depreciation"],
    DomainType.WRK: ["operator_count", "overtime", "absenteeism", "staff_", "shift_change"],
    DomainType.ENG: ["energy", "kwh", "peak_demand", "power_factor", "utility_meter"],
    DomainType.ENV: ["emissions", "water_usage", "air_quality", "waste_", "recycling"],
    DomainType.MAT: ["purchase_order", "material_id", "quantity_ordered", "reorder"],
    DomainType.SPT: ["spare_part", "part_location", "reorder_point", "lead_time_days"],
    DomainType.SUP: ["supplier_", "vendor_", "on_time_delivery", "sourcing"],
}


def _normalize(name: str) -> str:
    """Lowercase and strip non-alphanumeric characters for fuzzy matching."""
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def map_tab_to_domain(tab_name: str, columns: Optional[List[str]] = None) -> Optional[DomainType]:
    """
    Map a single tab to a DomainType.

    Resolution order:
    1. Exact/substring match on normalized tab name.
    2. Keyword match against the tab's column names.
    Returns None if the tab cannot be mapped (context-only).
    """
    normalized = _normalize(tab_name)

    # 1. Direct tab-name match (exact first, then substring).
    if normalized in TAB_NAME_DOMAIN_MAP:
        return TAB_NAME_DOMAIN_MAP[normalized]
    for key, domain in TAB_NAME_DOMAIN_MAP.items():
        if key in normalized or normalized in key:
            return domain

    # 2. Column keyword fallback (score by number of matching keywords).
    if columns:
        col_blob = " ".join(_normalize(c) for c in columns)
        best_domain: Optional[DomainType] = None
        best_score = 0
        for domain, keywords in COLUMN_KEYWORD_DOMAIN_MAP.items():
            score = sum(1 for kw in keywords if _normalize(kw) in col_blob)
            if score > best_score:
                best_score = score
                best_domain = domain
        if best_score > 0:
            return best_domain

    return None


def map_workbook_domains(
    tabs: Dict[str, List[str]]
) -> "WorkbookDomainMapping":
    """
    Map all tabs of a workbook to domains.

    Args:
        tabs: {tab_name: [column_name, ...]}

    Returns:
        WorkbookDomainMapping with tab->domain map and context-only tabs.
    """
    tab_domains: Dict[str, DomainType] = {}
    context_only: List[str] = []

    for tab_name, columns in tabs.items():
        domain = map_tab_to_domain(tab_name, columns)
        if domain is not None:
            tab_domains[tab_name] = domain
        else:
            context_only.append(tab_name)

    return WorkbookDomainMapping(tab_domains=tab_domains, context_only_tabs=context_only)


class WorkbookDomainMapping:
    """Result of mapping a workbook's tabs to domains."""

    def __init__(self, tab_domains: Dict[str, DomainType], context_only_tabs: List[str]):
        self.tab_domains = tab_domains
        self.context_only_tabs = context_only_tabs

    @property
    def active_domains(self) -> List[DomainType]:
        """Unique list of domains present in the workbook."""
        seen = []
        for domain in self.tab_domains.values():
            if domain not in seen:
                seen.append(domain)
        return seen

    def to_dict(self) -> Dict[str, object]:
        return {
            "tab_domains": {tab: domain.value for tab, domain in self.tab_domains.items()},
            "context_only_tabs": self.context_only_tabs,
            "active_domains": [d.value for d in self.active_domains],
        }
