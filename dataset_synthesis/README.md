# Stress-Test Dataset Synthesis (100 companies × 10 fiscal years)

Generates 1,000 Excel workbooks (one per company per fiscal year FY2015–FY2024)
for stress-testing the OmniusGrid correlation AI, plus OmniusGrid-native
compatibility outputs.

## Layout

- `industry_profiles.py` — 100 companies across 10 industries with industry-specific specialty tabs/columns.
- `generate_stress_test_dataset.py` — main generator (patterns, anomalies, cross-year continuity, Phase 6 outputs).
- `requirements.txt` — pandas/numpy/openpyxl.

## Each workbook

11 tabs: 5 full-timeline (`Production_Operations`, `Maintenance_Assets`,
`Quality_Control`, `Logistics_Supply_Chain`, + industry specialty) at ~1,095
rows each, and 6 sparse event tabs (`Safety_Compliance`, `Business_Operations`,
`Workforce_HR`, `IT_Infrastructure`, `Planning_Analytics`,
`Continuous_Improvement`). All tabs share `date`/`shift`/`asset_id` keys, with
clustered, co-timed anomalies for cross-tab correlation.

## Run

```bash
python -m pip install -r requirements.txt

# Full run (all 100 companies, 10 years) with all compatibility outputs
python generate_stress_test_dataset.py --out ./output --workers 8 --csv --telemetry --scenarios

# Quick smoke test
python generate_stress_test_dataset.py --out ./output_smoke --companies 2 --years 2 --scenarios --workers 1
```

### Flags
- `--companies N` limit companies (0 = all 100)
- `--years N` limit fiscal years (0 = all 10)
- `--workers N` CPU multiprocessing workers (GPU is NOT used; workload is CPU/IO-bound)
- `--csv` per-tab CSV (intake-safe; avoids first-sheet-only `read_excel`)
- `--telemetry` long-format telemetry CSV (TimescaleDB shape)
- `--scenarios` CorrelationScenario JSONL (validates against the real Pydantic model)
- `--overwrite` regenerate existing workbooks (default: resume/skip — checkpointing)

## Outputs

```
output/
  companies/company_NN_<slug>/
    company_NN_<slug>_FY2015.xlsx ... _FY2024.xlsx
    csv/        (with --csv)
    telemetry/  (with --telemetry)
    scenarios/  (with --scenarios)
  documentation/
    domain_mapping.json      # tab->DomainType, severity mapping, industries
    company_manifest.csv
    generation_summary.json
  generation.log
```

## OmniusGrid compatibility

- Tab names map to the 47 `DomainType` enum values (see `backend/app/services/spreadsheet_domain_mapper.py`).
- `--scenarios` emits `CorrelationScenario` objects validated by
  `backend/app/models/domain_interaction.py`.
- Severity mapping: `normal` 0.0–0.3, `warning` 0.3–0.7, `critical` 0.7–1.0.

## Azure VM execution

Intended to run on the Azure VM to avoid loading the local machine. See the
deploy commands in the session / plan; outputs are downloaded to
`/Users/hamaddada/Downloads/OmniusGrid/Stress Test Workbooks/`.
