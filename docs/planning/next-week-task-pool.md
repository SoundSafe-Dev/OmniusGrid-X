# Next week — task pool for redistribution

Written 2026-07-26 for **Harsh as Product Manager**. Everything below is a pooled,
independently-assignable ticket: reassign freely. The per-dev slices are a *suggested*
cut based on who has context, not a claim on the work.

**Every number here was verified against the repository today.** Where something is
reported but unverified, it says so — those need a 15-minute check before they are
scheduled, because the shape of the fix depends on the answer.

Sizes: **S** = under half a day · **M** = 1–2 days · **L** = 3+ days.
Tags: `[erp]` `[intake]` `[ai]` `[edge]` `[rag]` `[platform]` `[frontend]` `[ci]` `[data]` `[docs]`

---

## Verified state, so nobody re-derives it

| Fact | Value |
|---|---|
| `response_model` coverage | **191 / 417 routes (45%)** |
| API files still using `get_db` | **24** |
| `kanban.py` | 10 `get_db` + 14 `get_tenant_db` — mixed |
| Frontend `USE_MOCK` forks in `src/api/` | **190** |
| `useTranslation` call sites | **0** (i18n scaffolded, unused) |
| `api-contract` CI gate | `continue-on-error: true` — advisory |
| Tests quarantined in `ci-cd.yml` | 3 files ignored, 2 tests deselected |
| `correlation_ai_engine.py` | 3,627 LOC |
| `CorrelationAIPane.tsx` | 843 LOC |
| `geotab_service.py` | 16 `random.uniform` call sites |
| ERP tests | 488 with live vendors, 399 hermetic |

---

## Suggested per-dev slice for next week

### Harsh — Product Manager (+ his lane until reassigned)

The PM work is the highest-leverage thing on this list, because four of the biggest
items below are **decisions**, not code, and they are blocking.

- **P-01** decide the correlation-AI honesty story (see P-10..P-13)
- **P-02** decide whether the quarantined tests get fixed or deleted (P-14..P-16)
- **P-03** set the `main` promotion window (P-50)
- **P-04** triage this pool and assign
- Then, from his own lane: **P-14** (unquarantine the scenario builders) is the one
  only he has context for.

### Alex — direct follow-ups to his onboarding

His onboarding landed in intake/spreadsheet parsing: he fixed `normalize_key`, added
`normalize_column_header`, added a messy real-world CSV fixture, and wrote
`docs/DATA_FLOW_OVERVIEW.md`.

**Two of those three additions are not connected to anything.** That is the natural next
step and it teaches the codebase's central lesson.

- **P-05** wire `normalize_column_header` into its callers — it has tests and **no
  production caller**
- **P-06** make `messy_factory_upload.csv` assert something — it is used by **no test**
- **P-07** extend the messy-header corpus from real customer spreadsheets
- **P-08** header-collision behaviour after normalisation

### Hridyansh — OTA / edge

- **P-20** edge backoff jitter (carry-forward FS-182)
- **P-21** collector tests (carry-forward FS-185)
- **P-22** `ORGANIZATION_ID: "dev-org"` hardcoded in the edge StatefulSet

### htreinen — RAG

Last work 2026-07-23 (multi-document corpus, hybrid + discrimination tests).

- **P-30** the 5 open items in `docs/rag_ingestion_followups.md`
- **P-31** `/rag/documents` returns a raw SeaweedFS connection error instead of 503
- **P-32** `rag_eval` is excluded from the default test run

### Hamad — ERP tail + the platform gaps ERP exposed

- **P-40** Intuit tier-4 (needs the one-time consent; everything else is built)
- **P-41** flip `api-contract` to blocking
- **P-45** ERP export definition
- **P-46** ERP events over WebSocket

---

# The pool

## Intake & spreadsheet parsing `[intake]`

**P-05 · S · Wire `normalize_column_header` into its callers.**
Alex added it with three passing tests and **no production caller** —
`grep` finds it only in its own test file. Meanwhile eight modules consume
`shared_key_detector` (`multi_spreadsheet_correlator`, `pdf_parser`, `docx_parser`,
`document_scenario_builder`, `image_text_extractor`, `cross_file_scenario_builder`,
`image_scenario_builder`, `nlp_correlation`). Pick the one that ingests spreadsheet
headers, route them through the helper, and assert a real header set normalises.
*Acceptance:* a test that fails if the call is removed. A helper with a test and no
caller does nothing — that is the lesson.

**P-06 · S · Make the messy fixture assert something.**
`tests/load/fixtures/messy_factory_upload.csv` is referenced by **no test**. Alex built
it to represent real-world mess; point a parser test at it and assert the keys and
headers that come out.
*Acceptance:* corrupting a column in the fixture fails the test.

**P-07 · M · Extend the messy-header corpus.**
Add cases from genuine customer spreadsheets: merged cells, a title row above the
header, trailing total rows, unit suffixes (`Temp (°C)`), duplicated names, non-ASCII,
Excel date coercion. Each case gets a named test explaining what it represents.

**P-08 · S · Decide and test header-collision behaviour.**
`Serial #` and `Serial No.` may both normalise to `serial_number`. Today's behaviour is
unknown — determine it, then make it deliberate: last-wins, first-wins, or raise.
Silent overwrite of one column by another is a data-loss bug.
*Acceptance:* the chosen behaviour is asserted, with the reasoning in the docstring.

**P-09 · M · Fold `docs/DATA_FLOW_OVERVIEW.md` into the architecture docs.**
Alex wrote 114 lines that live outside `docs/architecture/`. Reconcile with
`DATA_FLOW.md` so there is one description of the flow, not two that can disagree.

## Correlation AI `[ai]` — needs PM decisions first

**P-10 · DECISION · Does the UI label simulated analyses?**
The engine now returns `simulated: true` and a reason on both fallback paths, but
**nothing renders it**. `CORRELATION_MODEL_ENABLED` is `False` by default, so today every
deployment shows heuristics styled as AI output. Options: label it, hide the tab when the
model is off, or ship the adapter enabled. This is a product call, not an engineering one.

**P-11 · S · Render the `simulated` flag** (once P-10 is decided). `CorrelationAIPane.tsx`
reads the analysis payload; the key is already there.

**P-12 · M · Make the Gemma adapter loadable in a dev environment.**
`CORRELATION_ADAPTER_PATH` defaults to `./checkpoints/best_lora_v2`. Document how a dev
obtains it, or make the load failure loud at startup rather than per request.

**P-13 · L · First tests for `correlation_ai_engine.py`.**
3,627 lines, and `pytest -k correlation` deselects 1,245 tests and runs **none** against
it. Start with the pure scoring helpers — `_calculate_risk_score`,
`_simulate_root_cause`, `_generate_kanban_tasks` — which need no model.

**P-14 · M · Unquarantine the three scenario builders.**
`test_document_scenario_builder.py`, `test_image_scenario_builder.py` and
`test_cross_file_scenario_builder.py` are `--ignore`d in `ci-cd.yml` and fail at
**collection**: `ImportError: cannot import name 'build_document_scenarios'`. The test
and the module disagree about the API. Only Harsh knows which side is right.

**P-15 · S · Re-enable the two deselected tests** —
`test_document_domain_mapper.py::test_map_section_to_domain_table_content` and
`test_image_domain_mapper.py::test_map_image_domains`.

**P-16 · S · Make the quarantine expire.**
Add a named marker plus a test that fails once an expiry date passes, so an exclusion
cannot quietly become permanent.

**P-17 · L · Split `CorrelationAIPane.tsx`.**
843 lines, no test. Extract the data-fetching and the panel layout so the pieces are
testable.

**P-18 · M · Kanban RLS-write-on-read.**
`kanban.py` mixes 10 `get_db` and 14 `get_tenant_db`. One root cause was reported to
500 `/kanban/board`, `/metrics` and `/workload`. **Verify first** — it may already be
fixed — then convert the handlers that touch RLS-protected tables.

**P-19 · S · `/nlp/correlation/intake/{id}` 500** (reported; verify).

## Edge & OTA `[edge]`

**P-20 · S · Edge backoff jitter** (FS-182). Without jitter, a fleet that loses the
backend reconnects in lockstep and stampedes it on recovery.

**P-21 · M · Collector tests** (FS-185).

**P-22 · S · `ORGANIZATION_ID: "dev-org"` is hardcoded** at
`base/edge-agent-statefulset.yaml:62,64`. Every edge agent in every environment reports
into the same fake org.

**P-23 · M · Probes, resource limits and `securityContext` for the 4 workers**, otel and
jaeger (FS-173/214).

**P-24 · M · `overlays/dr` does not exist**, so
`docs/deployment/dr-datacenter-outage.md` is unexecutable.

## RAG `[rag]`

**P-30 · M · The 5 open items** in `docs/rag_ingestion_followups.md`.

**P-31 · S · `/rag/documents` leaks a raw SeaweedFS connection error** instead of 503.
An infrastructure error surfaced verbatim to a client is both confusing and an
information leak.

**P-32 · S · `rag_eval` is excluded from the default run**, so it has zero coverage in
CI. Either include it or state why not.

**P-33 · M · Containerisation seam** in `docs/RAG_CONTAINERIZATION.md`.

## ERP `[erp]` — the tail

**P-40 · S · Intuit tier 4.** Everything is built: connector, 87 hermetic tests, 16
live-ready tests, `scripts/intuit_authorize.py`, a CI job. It needs the one-time consent
— register `http://localhost:8399/callback` on the app, run the script, store the
refresh token and realm id. **Note the refresh token rotates**, so two people running it
against the same sandbox company will fight.

**P-41 · S · Flip `api-contract` to blocking.** `continue-on-error: true` with a comment
saying both blockers are fixed and it needs one green run. ~400 property-checked
operations for near-zero cost.

**P-42 · M · Correlation transformers for a second vendor.**
`erp_sync_correlation.CORRELATION_ROUTES` only routes SAP, because
`transform_purchase_order` reads SAP field names. Dataverse and Odoo purchase orders are
currently reported as `skipped: unrouted` — honest, but no correlations. Needs a
transformer per vendor.

**P-43 · S · Set `webhook_secret` on the demo/seeded integrations.** Migration 049
enforces uniqueness; the seeder should generate distinct values so the demo exercises the
webhook path.

**P-44 · M · Verify a real vendor webhook end to end.** The Intuit sandbox can send real
webhooks. Ours is the only scheme verified against vendor documentation, so this is the
one place the raw-body HMAC can be proven against a genuine sender.

**P-45 · M · ERP export definition.** `EXPORT_DEFINITIONS` has `telemetry`,
`kanban_tasks` and `registries`. ERP entities are exactly what an operator wants for
reconciliation, and nothing claims it exists yet.

**P-46 · M · ERP events over WebSocket.** No ERP event reaches `websocket_manager`, so
the hub never updates live. The webhook receiver is the natural producer.

**P-47 · L · ERP → Kafka.** No ERP producer exists. Larger architectural call: does ERP
data belong on the bus alongside telemetry?

**P-48 · M · `erp_database_replication.py`** — 491 lines. Verify whether it does anything;
it was reported as entirely no-op. Delete it or make it real.

**P-49 · S · Rotate the three credentials** shared during development (SAP key, Intuit
client secret, Dataverse client secret) and move them to repository secrets so the three
CI jobs stop skipping.

## Platform, data & CI `[platform]` `[data]` `[ci]`

**P-50 · DECISION + S · Promote `main`.** `hamad/converged-pre-main` is well ahead. Needs
a window, not engineering.

**P-51 · L · `get_db` on RLS-protected tables — 24 API files.** The class of bug that
made the ERP background sync write nothing on a non-owner role, and that hid the
dashboard's data. Audit each against the RLS tables in migrations `011`/`033`. **Add the
guard test first** so the next one cannot ship.

**P-52 · M · `response_model` coverage: 191/417 (45%).** Undeclared responses mean the
OpenAPI schema is fiction for more than half the API, which also weakens P-41.

**P-53 · L · 190 `USE_MOCK` forks, and `setup.ts` forces mock mode for every test.**
So the real client path is never exercised and can drift from the API undetected.
Start with the pages that have real backends.

**P-54 · L · i18n: 0 `useTranslation` call sites** against a full scaffold and ~560
hardcoded strings. A decision about scope before it is an engineering task.

**P-55 · M · GeoTab is 100% synthetic** — 16 `random.uniform` sites in
`geotab_service.py`, including DOT-regulated HOS numbers. Being fake is defensible;
**presenting fabricated compliance figures as real is not.** Either label them or gate
the surface.

**P-56 · S · Coverage thresholds.** None exist, and `vitest.config.ts` narrows coverage
`include` to 3 paths, so the number is decorative.

**P-57 · M · Organisation management CRUD.** `AdminPages.tsx` sets
`USER_MGMT_ENABLED = false`. Blocked on the `super_admin` design question that
`data_retention.py` also needs — a decision before code.

**P-58 · S · Frontend WebSocket defaults to `ws://`** at `api/fleetHealth.ts:156`, so
fleet-health sockets break on any HTTPS deployment. Audit the other hardcoded
`localhost` fallbacks with it.

**P-59 · S · Adopt the generated SDK.** It exists with **zero importers**.

**P-60 · M · Migration chain hygiene** (FS-158/159/160): idempotency, test fixtures
(005/006/008/009) in the production chain, duplicate prefixes at 004/005/007/009, the
missing 019, and `check_migrations.py` is a `Makefile` target in no workflow.

## Deploy & infrastructure `[platform]`

Verified today, so this list contains no finished work: **Redis IS deployed**
(`base/redis-statefulset.yaml`) and **alarm rules exist** (model + `AlarmRules.tsx` with a
test). Both were open in the previous plan; neither is listed here.

**P-61 · M · `monitoring/`, `autoscaling/` and `database-ha/` are referenced by NO
overlay.** `overlays/production/kustomization.yaml` builds `../../base` plus `hpa.yaml` —
nothing else. So the in-cluster Prometheus/Grafana, the KEDA scalers and the CloudNativePG
HA stack exist as reviewed YAML that has run nowhere but a kind cluster.
*Acceptance:* `kustomize build overlays/production` contains them, or `ci-cd.yml` applies
the operator-dependent stacks in a documented step.

**P-62 · M · RTO/RPO checklist is still a template.** `docs/runbooks/rto-rpo-checklist.md`
has `[DURATION]` where the measured RTO and RPO go. **Measured numbers or it is not a DR
plan** — needs a drill, not a doc edit.

**P-63 · L · CNPG cutover, which is what makes PITR real.**
`docs/runbooks/database-backup-restore.md` still says *"Restoring PITR (not yet done)"* and
marks itself not operational. Build the TimescaleDB-enabled CNPG image, install the
operator, run the cutover, repoint `DATABASE_URL` at the pooler — then delete that section,
because it will finally be false.

**P-64 · M · KEDA scale drill.** Run `tests/load/ingestion_load.py` against staging and
observe the HPA actually scale on consumer lag. Pairs with P-62.

**P-65 · S + COORDINATION · `HAMAD_IDE.pem` rotation.** The key was untracked (FS-01) but
**remains in git history on both remotes**. Untracking does not revoke it. Rotate the key
first, then decide whether to purge the history in one coordinated window — a rewrite
affects everyone's clones, so it is a scheduling decision.

**P-66 · M · Placeholder secrets can reach production.** `base/object-store.yaml`,
`monitoring/grafana.yaml` and `monitoring/alertmanager.yaml` ship DEV/CI-ONLY credentials —
including a placeholder Grafana admin password with anonymous Viewer enabled. They are
honestly labelled in comments; nothing *enforces* that production overrides them. Make it a
gate, not a comment.

**P-67 · S · Wire `check_migrations.py` into CI.** It is a `Makefile` target referenced by
no workflow, so nothing checks the migration chain on a PR.

---

---

## Notes for whoever redistributes

**Four of these are decisions, not tickets** — P-01/P-10, P-02, P-03/P-50, P-57. They
block real work and cost a conversation, not a sprint.

**Five are "verify, then fix"** — P-18, P-19, P-48, and anything marked *reported*. The
shape of the fix depends on what is actually true, and some may already be fixed.

**Alex's four (P-05..P-08) are deliberately small and sequenced.** P-05 and P-06 finish
work he already started, and both teach the same lesson: code with a test but no caller,
and a fixture with no assertion, do nothing. Good ground to stand on before P-07 widens
the corpus.

**The highest-value platform item is P-51.** It is the root cause behind at least three
separate user-visible bugs found so far, and the guard matters more than the sweep —
without it the next one ships too.
