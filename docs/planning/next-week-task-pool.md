# Next week — task pool, grouped by dev lane

Written 2026-07-26 for **Harsh as Product Manager**.

Grouped by lane so it can be handed out as-is, but **every ticket is independently
assignable** — the lane is where the context currently lives, not a claim on the work.
Reassign freely; nothing below depends on who does it except where a ticket says so.

**Every number here was verified against the repository today.** Where something is
reported but unverified it says so — those need a 15-minute check before scheduling,
because the shape of the fix depends on the answer.

Sizes: **S** = under half a day · **M** = 1–2 days · **L** = 3+ days.
Lanes follow the ownership table in the root [README](../../README.md).

**56 tickets.** Four are decisions, not work.

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
| `correlation_ai_engine.py` | 3,627 LOC, zero tests reach it |
| `CorrelationAIPane.tsx` | 843 LOC, no test |
| `geotab_service.py` | 16 `random.uniform` call sites |
| ERP tests | 488 with live vendors, 399 hermetic |

**Checked and found DONE — deliberately not in this pool**, because the previous plan
still listed both: Redis is deployed (`base/redis-statefulset.yaml`) and server-side
alarm rules exist (`AlarmRule` model + `AlarmRules.tsx` with a test).

---

# 0 · Decisions — Harsh, as PM

These block engineering work and cost a conversation, not a sprint. Everything in
brackets is waiting on them.

**P-01 · DECISION · The correlation-AI honesty story.** *(blocks P-10 → P-11; shapes P-12)*
The engine now returns `simulated: true` and a reason on both fallback paths, but
**nothing renders it**, and `CORRELATION_MODEL_ENABLED` is `False` by default — so today
every deployment shows heuristics styled as AI output. Label it, hide the tab when the
model is off, or ship the adapter enabled. A product call.

**P-02 · DECISION · Fix or delete the quarantined tests.** *(blocks P-14, P-15, P-16)*
Three test files are `--ignore`d and two tests deselected in `ci-cd.yml`. They fail at
collection, so the module and its tests disagree about the API. Either is defensible;
leaving them excluded indefinitely is not.

**P-03 · DECISION · The `main` promotion window.** *(pairs with P-50)*
`hamad/converged-pre-main` is well ahead of `main`. Needs a window, not engineering.

**P-04 · DECISION · The `super_admin` role.** *(blocks P-57, and `data_retention.py`)*
Two features need a role that spans tenants. Designing it is a security decision with a
blast radius, which is why neither has shipped.

---

# 1 · Alex — intake & spreadsheet parsing `[intake]`
*Under Harsh. Sequenced deliberately: P-05 and P-06 finish work he already started.*

His onboarding landed here — he fixed `normalize_key`, added `normalize_column_header`,
added a messy real-world CSV fixture, and wrote `docs/DATA_FLOW_OVERVIEW.md`.

**Two of those three code additions are not connected to anything.** That is the natural
next step, and it teaches the lesson this codebase keeps relearning.

**P-05 · S · Wire `normalize_column_header` into its callers.**
He added it with three passing tests and **no production caller** — `grep` finds it only
in its own test file. Eight modules consume `shared_key_detector`
(`multi_spreadsheet_correlator`, `pdf_parser`, `docx_parser`,
`document_scenario_builder`, `image_text_extractor`, `cross_file_scenario_builder`,
`image_scenario_builder`, `nlp_correlation`). Pick the one that ingests spreadsheet
headers, route them through the helper, and assert a real header set normalises.
*Acceptance:* a test that fails if the call is removed. A helper with a test and no
caller does nothing.

**P-06 · S · Make the messy fixture assert something.**
`tests/load/fixtures/messy_factory_upload.csv` is referenced by **no test**. He built it
to represent real-world mess; point a parser test at it and assert the keys and headers
that come out.
*Acceptance:* corrupting a column in the fixture fails the test.

**P-08 · S · Decide and test header-collision behaviour.**
`Serial #` and `Serial No.` may both normalise to `serial_number`. Today's behaviour is
**unknown** — determine it, then make it deliberate: last-wins, first-wins, or raise.
Silent overwrite of one column by another is a data-loss bug.
*Acceptance:* the chosen behaviour is asserted, with the reasoning in the docstring.

**P-07 · M · Extend the messy-header corpus.**
Cases from genuine customer spreadsheets: merged cells, a title row above the header,
trailing total rows, unit suffixes (`Temp (°C)`), duplicated names, non-ASCII, Excel date
coercion. Each gets a named test explaining what it represents.

**P-09 · M · Fold `docs/DATA_FLOW_OVERVIEW.md` into the architecture docs.** *(stretch)*
He wrote 114 lines living outside `docs/architecture/`. Reconcile with `DATA_FLOW.md` so
there is one description of the flow, not two that can disagree.

---

# 2 · Harsh — correlation AI, NLP, kanban, MLOps `[ai]` `[intake]`
*His own lane, until he reassigns it. P-14 is the one only he has the context for.*

**P-14 · M · Unquarantine the three scenario builders.** *(needs P-02)*
`test_document_scenario_builder.py`, `test_image_scenario_builder.py` and
`test_cross_file_scenario_builder.py` fail at **collection**:
`ImportError: cannot import name 'build_document_scenarios'`. The test and the module
disagree about the API, and only he knows which side is right.

**P-15 · S · Re-enable the two deselected tests** — *(needs P-02)*
`test_document_domain_mapper.py::test_map_section_to_domain_table_content` and
`test_image_domain_mapper.py::test_map_image_domains`.

**P-16 · S · Make the quarantine expire.**
A named marker plus a test that fails once an expiry date passes, so an exclusion cannot
quietly become permanent.

**P-10 · S · Plumb the `simulated` flag through the API.** *(needs P-01; blocks P-11)*
**The honesty fix currently stops at the service layer.** Verified today: no file in
`app/api/` reads the key at all. `nlp_correlation.py:1152-1155` cherry-picks exactly four
values out of the analysis — `predicted_root_cause`, `risk_score`,
`target_kanban_tasks`, `remediation_commands` — and `/query` returns
`response_model=NLPQueryResponse`, which declares no `simulated` field and would strip it
even if the handler copied it. So the engine labels its output and nothing downstream can
see the label.
*Acceptance:* a test asserting the flag survives the HTTP boundary with the model
disabled.

**P-11 · S · Render the `simulated` flag.** *(needs P-10)*
Only reachable once P-10 lands — `CorrelationAIPane.tsx` cannot display a key the API
does not return.

**P-12 · M · Make the Gemma adapter loadable in a dev environment.**
`CORRELATION_ADAPTER_PATH` defaults to `./checkpoints/best_lora_v2`. Document how a dev
obtains it, or make the load failure loud at startup rather than silent per request.

**P-18 · M · Kanban RLS-write-on-read.** *(verify first)*
`kanban.py` mixes 10 `get_db` and 14 `get_tenant_db`. One root cause was reported to 500
`/kanban/board`, `/metrics` and `/workload`. It may already be fixed — check, then convert
the handlers touching RLS-protected tables.

**P-19 · S · `/nlp/correlation/intake/{id}` 500.** *(reported; verify)*

**P-13 · L · First tests for `correlation_ai_engine.py`.**
3,627 lines, and `pytest -k correlation` deselects 1,245 tests and runs **none** against
it. Start with the pure scoring helpers — `_calculate_risk_score`,
`_simulate_root_cause`, `_generate_kanban_tasks` — which need no model.

**P-17 · L · Split `CorrelationAIPane.tsx`.**
843 lines, no test. Extract the data-fetching from the panel layout so the pieces become
testable.

---

# 3 · Hridyansh — tenant isolation, RBAC, OTA, edge `[edge]` `[platform]`

**P-51 · L · `get_db` on RLS-protected tables — 24 API files. ⭐ highest-value item here.**
The class of bug that made the ERP background sync write nothing on a non-owner role and
that hid the dashboard's data behind zeroes. Audit each file against the RLS tables in
migrations `011`/`033`. **Add the guard test first** — it matters more than the sweep,
because without it the next one ships too. Squarely his lane: RLS through the canonical
`app.current_org_id` GUC.

**P-22 · S · `ORGANIZATION_ID: "dev-org"` is hardcoded** at
`base/edge-agent-statefulset.yaml:62,64`. Every edge agent in every environment reports
into the same fake org.

**P-20 · S · Edge backoff jitter** (FS-182). Without jitter a fleet that loses the backend
reconnects in lockstep and stampedes it on recovery.

**P-57 · M · Organisation management CRUD.** *(needs P-04)*
`AdminPages.tsx` sets `USER_MGMT_ENABLED = false`. Blocked on the `super_admin` design
that `data_retention.py` also needs.

**P-21 · M · Collector tests** (FS-185).

---

# 4 · htreinen — RAG `[rag]`
*Last work 2026-07-23: multi-document corpus, hybrid + discrimination tests.*

**P-31 · S · `/rag/documents` leaks a raw SeaweedFS connection error** instead of 503. An
infrastructure error surfaced verbatim to a client is both confusing and an information
leak.

**P-32 · S · `rag_eval` is excluded from the default run**, so it has zero coverage in CI.
Either include it or state why not.

**P-30 · M · The 5 open items** in `docs/rag_ingestion_followups.md`.

**P-33 · M · Containerisation seam** in `docs/RAG_CONTAINERIZATION.md`.

---

# 5 · Hamad — ERP connectors `[erp]`
*The tail of the ERP slice. Everything here is small except P-47.*

**P-40 · S · Intuit tier 4.** Everything is built — connector, 87 hermetic tests, 16
live-ready tests, `scripts/intuit_authorize.py`, a CI job. It needs the one-time consent:
register `http://localhost:8399/callback` on the app, run the script, store the refresh
token and realm id. **The refresh token rotates**, so two people running it against the
same sandbox company will fight.

**P-49 · S · Rotate the three credentials** shared during development (SAP key, Intuit
client secret, Dataverse client secret) and move them to repository secrets so the three
CI jobs stop skipping.

**P-43 · S · Set `webhook_secret` on the demo/seeded integrations.** Migration 049
enforces uniqueness; the seeder should generate distinct values so the demo actually
exercises the webhook path.

**P-44 · M · Verify a real vendor webhook end to end.** The Intuit sandbox can send real
webhooks, and Intuit is the only scheme verified against vendor documentation — so it is
the one place the raw-body HMAC can be proven against a genuine sender.

**P-42 · M · Correlation transformers for a second vendor.**
`erp_sync_correlation.CORRELATION_ROUTES` routes only SAP, because
`transform_purchase_order` reads SAP field names. Dataverse and Odoo purchase orders are
reported as `skipped: unrouted` — honest, but no correlations.

**P-45 · M · ERP export definition.** `EXPORT_DEFINITIONS` has `telemetry`,
`kanban_tasks` and `registries`. ERP entities are exactly what an operator wants for
reconciliation, and nothing claims it exists yet.

**P-46 · M · ERP events over WebSocket.** No ERP event reaches `websocket_manager`, so the
hub never updates live. The webhook receiver is the natural producer.

**P-48 · M · `erp_database_replication.py`** — 491 lines. *(verify)* Reported as entirely
no-op. Delete it or make it real.

**P-47 · L · ERP → Kafka.** No ERP producer exists. An architectural call: does ERP data
belong on the bus alongside telemetry?

---

# 6 · Hamad — platform, frontend, CI `[platform]` `[frontend]` `[ci]`

**P-41 · S · Flip `api-contract` to blocking.** `continue-on-error: true`, with a comment
saying both blockers are fixed and it needs one green run. ~400 property-checked
operations for near-zero cost.

**P-50 · S · Promote `main`.** *(needs P-03)*

**P-58 · S · Frontend WebSocket defaults to `ws://`** at `api/fleetHealth.ts:156`, so
fleet-health sockets break on any HTTPS deployment. Audit the other hardcoded `localhost`
fallbacks with it.

**P-56 · S · Coverage thresholds.** None exist, and `vitest.config.ts` narrows coverage
`include` to 3 paths, so the number is decorative.

**P-59 · S · Adopt the generated SDK.** It exists with **zero importers**.

**P-52 · M · `response_model` coverage: 191/417 (45%).** Undeclared responses make the
OpenAPI schema fiction for more than half the API — which also weakens P-41.

**P-55 · M · GeoTab is 100% synthetic** — 16 `random.uniform` sites in
`geotab_service.py`, including DOT-regulated HOS numbers. Being fake is defensible;
**presenting fabricated compliance figures as real is not.** Label them or gate the
surface.

**P-60 · M · Migration chain hygiene** (FS-158/159/160): idempotency, test fixtures
(005/006/008/009) in the production chain, duplicate prefixes at 004/005/007/009, the
missing 019.

**P-53 · L · 190 `USE_MOCK` forks, and `setup.ts` forces mock mode for every test.** So
the real client path is never exercised and can drift from the API undetected. Start with
the pages that have real backends.

**P-54 · L · i18n: 0 `useTranslation` call sites** against a full scaffold and ~560
hardcoded strings. Needs a scope decision before it is an engineering task.

---

# 7 · Hamad — deploy & infrastructure `[platform]`

**P-67 · S · Wire `check_migrations.py` into CI.** A `Makefile` target referenced by no
workflow, so nothing checks the migration chain on a PR.

**P-65 · S + COORDINATION · `HAMAD_IDE.pem` rotation.** The key was untracked (FS-01) but
**remains in git history on both remotes** — untracking does not revoke it. Rotate first,
then decide whether to purge history in one coordinated window, since a rewrite affects
everyone's clones.

**P-61 · M · `monitoring/`, `autoscaling/` and `database-ha/` are referenced by NO
overlay.** `overlays/production/kustomization.yaml` builds `../../base` plus `hpa.yaml` and
nothing else — so the in-cluster Prometheus/Grafana, the KEDA scalers and the CloudNativePG
HA stack are reviewed YAML that has run nowhere but a kind cluster.
*Acceptance:* `kustomize build overlays/production` contains them, or `ci-cd.yml` applies
the operator-dependent stacks in a documented step.

**P-62 · M · RTO/RPO checklist is still a template.** `docs/runbooks/rto-rpo-checklist.md`
has `[DURATION]` where the measured RTO and RPO go. **Measured numbers or it is not a DR
plan** — needs a drill, not a doc edit.

**P-64 · M · KEDA scale drill.** Run `tests/load/ingestion_load.py` against staging and
observe the HPA actually scale on consumer lag. Pairs with P-62.

**P-66 · M · Placeholder secrets can reach production.** `base/object-store.yaml`,
`monitoring/grafana.yaml` and `monitoring/alertmanager.yaml` ship DEV/CI-ONLY credentials,
including a placeholder Grafana admin password with anonymous Viewer enabled. They are
honestly labelled in comments; nothing *enforces* that production overrides them. Make it
a gate, not a comment.

**P-23 · M · Probes, resource limits and `securityContext` for the 4 workers**, otel and
jaeger (FS-173/214).

**P-24 · M · `overlays/dr` does not exist**, so
`docs/deployment/dr-datacenter-outage.md` is unexecutable.

**P-63 · L · CNPG cutover, which is what makes PITR real.**
`docs/runbooks/database-backup-restore.md` still says *"Restoring PITR (not yet done)"* and
marks itself not operational. Build the TimescaleDB-enabled CNPG image, install the
operator, run the cutover, repoint `DATABASE_URL` at the pooler — then delete that
section, because it will finally be false.

---

## Notes for redistribution

**Lane totals:** decisions 4 · Alex 5 · Harsh 10 · Hridyansh 5 · htreinen 4 ·
Hamad ERP 9 · Hamad platform 10 · Hamad infra 9. **56 total.**

Hamad's three sections hold 30 of the 56 because the ownership table currently gives him
backend platform, frontend, deploy/CI, schema, observability and docs. **That is the most
obvious thing to rebalance** — P-52, P-56, P-58, P-59 and P-67 are self-contained and need
no ERP or deploy context.

**Two reassignments from the previous version, both from the README ownership table:**
P-51 (`get_db` on RLS tables) and P-57 (organisation management) moved to **Hridyansh** —
tenant isolation and RBAC are his lane, and P-51 is the same GUC mechanism he already owns.

**Sequencing that actually matters:**
- P-02 before P-14/P-15/P-16 — no point fixing tests that may be deleted.
- P-01 → P-10 → P-11, in that order. The flag is not even in the API response yet, so
  building the UI first would have nothing to read.
- P-04 before P-57.
- P-05/P-06 before P-07 — finish the wiring before widening the corpus.
- P-51's guard test before its sweep.

**Five are "verify, then fix"** — P-18, P-19, P-48, and anything marked *reported*. Some
may already be fixed, and the shape of the work depends on what is true.

**Ticket IDs are stable.** They are not priority order, so moving one between lanes keeps
its number and any reference to it.
