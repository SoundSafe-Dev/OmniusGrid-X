# Cross-Tab Workbook Correlation

How OmniusGrid ingests multi-tab spreadsheets/workbooks and builds cross-tab
correlation scenarios for the Correlation AI engine.

## Overview

Operational data often lives in **multi-tab Excel workbooks** — e.g. one tab for
production, one for maintenance, one for quality, etc. Previously the intake
system only read the first sheet and never converted the data into correlation
scenarios. The cross-tab workbook correlation feature:

1. Parses **every tab** of an uploaded workbook (CSV is treated as a single tab).
2. Maps each tab to one of the 47 `DomainType` operational domains.
3. Builds `CorrelationScenario` objects that **link tabs together** so the AI can
   discover correlations *across* domains (e.g., a maintenance vibration spike
   correlated with a quality defect cluster on the same shift and asset).
4. Runs every scenario through the correlation AI engine and aggregates results.

## Components

| Component | File | Responsibility |
|-----------|------|----------------|
| Multi-sheet parser | `backend/app/api/nlp_correlation.py` (`_process_uploaded_file`) | `pd.read_excel(..., sheet_name=None)`; stores per-tab metadata |
| Domain mapper | `backend/app/services/spreadsheet_domain_mapper.py` | Tab name / column keywords → `DomainType` |
| Scenario builder | `backend/app/services/spreadsheet_scenario_builder.py` | Groups rows into scenarios; builds `CrossDomainLink`s |
| Analyze endpoint | `backend/app/api/nlp_correlation.py` (`/intake/analyze`) | Orchestrates parse → build → analyze → persist |
| Engine | `backend/app/services/correlation_ai_engine.py` | Consumes `CorrelationScenario`, returns risk/root-cause/tasks |
| Schema | `backend/app/models/domain_interaction.py` | `OperationalMetric`, `CrossDomainLink`, `CorrelationScenario` |

## Data flow

```
Upload (.xlsx/.csv)
   │  pd.read_excel(sheet_name=None)  -> {tab: DataFrame}
   ▼
Tab → DomainType mapping  (47-domain enum; column-keyword fallback)
   ▼
Scenario builder (mode = window | tab | row)
   • group rows by shared date[/shift] window
   • OperationalMetric per contributing tab (endpoint + payload_snapshot)
   • CrossDomainLink between co-occurring domains (interaction_key = asset_id)
   • severity_impact from status columns (normal/warning/critical)
   ▼
correlation_ai_engine.analyze_scenario(scenario)  (per scenario, full coverage)
   ▼
Aggregate (peak risk, union of domains/tasks/commands/compliance) → persist on IntakeItem
```

## Tab → Domain mapping

The mapper (`spreadsheet_domain_mapper.py`) resolves a tab in this order:

1. **Tab-name match** (normalized, substring-aware), e.g.
   `Production_Operations → PRODUCTION_OEE`, `Maintenance_Assets → MAINTENANCE`,
   `Quality_Control → QUALITY_CONTROL`, `Logistics_Supply_Chain → LOGISTICS_FLEET`,
   `Safety_Compliance → SAFETY`, `Business_Operations → FINANCE`,
   `Workforce_HR → WORKFORCE_MANAGEMENT`, `IT_Infrastructure → SYSTEM_INFRASTRUCTURE`,
   `Planning_Analytics → PLANNING_SCHEDULING`, `Continuous_Improvement → CONTINUOUS_IMPROVEMENT`.
2. **Column-keyword fallback** — if the tab name is unknown, columns are scored
   against keyword sets (e.g. `trailer`/`dock` → `LOGISTICS_FLEET`,
   `vibration`/`work_order` → `MAINTENANCE`).
3. **Context-only** — tabs that match nothing are flagged and excluded from metrics
   (still available as metadata).

## Scenario modes

`POST /api/v1/nlp/correlation/intake/analyze?intake_id=...&mode=window`

| Mode | Behavior | Use case |
|------|----------|----------|
| `window` (default) | One scenario per shared `date`(+`shift`) window across all tabs. Each contributing tab adds an `OperationalMetric`; pairwise `CrossDomainLink`s connect co-occurring domains. **All windows processed (full coverage).** | Cross-tab / cross-domain correlation discovery |
| `tab` | One scenario for the whole workbook; `active_domains` = all mapped tabs, aggregated metric per tab. | Fast, coarse overview |
| `row` | One scenario per row (capped), tagged to its tab's domain. | Fine-grained single-domain triage |

### Cross-tab linkage

The mechanism that makes correlation possible is the **shared `interaction_key`**
(typically `asset_id`) plus **co-timed anomalies**. In `window` mode, rows from
different tabs that share the same `date`/`shift` are grouped, and links are created
between their domains. Severity is derived from status-like columns:

| Status value | `severity_impact` |
|--------------|-------------------|
| normal / ok / passed / healthy | ~0.15 |
| warning / medium / delayed / degraded | ~0.5 |
| critical / high / failed / down | ~0.85 |

## Analyze response (spreadsheet)

```jsonc
{
  "intake_id": "…",
  "analysis": "Analyzed 1095 cross-tab scenarios across 10 domains …",
  "mode": "window",
  "tab_count": 11,
  "tab_domain_mapping": { "tab_domains": {…}, "active_domains": [...], "context_only_tabs": [] },
  "scenarios_analyzed": 1095,
  "cross_domain_links": 4380,
  "domains_analyzed": ["PRODUCTION_OEE", "MAINTENANCE", "QUALITY_CONTROL", ...],
  "risk_score": 88.0,
  "recommended_actions": [ … ],
  "kanban_tasks": [ … ],
  "compliance_implications": [ … ],
  "scenario_samples": [ { "scenario_id", "domains", "risk_score", "root_cause" }, … ]
}
```

## Performance & limits

- Scenarios are built **lazily** and capped (`DEFAULT_MAX_SCENARIOS`) to bound
  compute; `window` mode still covers all distinct windows.
- `payload_snapshot` fields are capped per metric to keep payloads compact.
- Large workbooks should prefer `window` mode (one scenario per shift) over `row`.

## Dependencies

`pandas` and `openpyxl` are required for workbook parsing (added to
`backend/requirements.txt`).

## Tests

`backend/tests/test_spreadsheet_intake.py` covers tab→domain mapping, window/tab/row
scenario building, severity mapping, Pydantic validity, and a multi-sheet `.xlsx`
round-trip.

```bash
cd backend && venv/bin/python tests/test_spreadsheet_intake.py
```

## Related

- Stress-test dataset generator: `dataset_synthesis/README.md`
- Correlation engine: `docs/CORRELATION_AI_ENGINE.md`
- Domain model: `backend/app/models/domain_interaction.py`
