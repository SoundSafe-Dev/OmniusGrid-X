# Fixed sprints FS-241 → FS-343

Written 2026-07-31 on `hamad/converged-pre-main`. Continues the FS series (highest prior: FS-240).

**Every number here was measured today, not carried forward.** The previous pool drifted in one
direction — `data_retention` was recorded as 8 routes and has 12; the contract floor was
recorded as 290 and is 350; `response_model` was recorded as 195/458 and was 203/453. Each
drift made the written state look *better* than reality. Re-derive before starting; if a claim
does not reproduce, correct the entry in place with the date.

---

## The weighting

Five waves, in order, because the order is the argument: build, harden what was built, prove
it, audit the proof, then build again on ground that holds.

| Wave | Kind | Count | Why here |
|---|---|---:|---|
| A | **Buildout** | 25 | Capability the platform lacks. Front-loaded so later waves have something real to harden. |
| B | **Fixes** | 21 | Known defects and debt, mostly enumerated backlogs where the work is countable. |
| C | **Testing** | 22 | Coverage where the code that runs in production is the code nothing exercises. |
| D | **Review** | 16 | Audits and decisions. Cheap to run, and each unblocks or deletes downstream work. |
| E | **Buildout II** | 20 | The second build wave, deliberately after C and D — these are the items that are unsafe to attempt until the guards exist. |

**45 of 104 are build.** It was 100 before four items were added from a review of this
session's own findings — FS-303/304/305 (the three defect *classes*, since the instances are
fixed and the classes are not), FS-284b (393 tests that cannot run locally) and FS-317 (the
planning docs' numbers drifting in one direction). Those five are the highest-leverage entries
in the document, which is an argument for reviewing a plan before executing it. Sizes: **S** under half a day · **M** 1–2 days · **L** 3+ days.

## Lane discipline

Derived from each dev's own commits, not branch tips. **Hands off**: `auth.py` (all 6 branches),
`kanban.py`, `telemetry.py`, `analysis_sessions.py` (htreinen ×9), `nlp_correlation.py`,
`model_monitoring.py`, `logistics_correlation.py`, `engines.py`, `rag_*.py` internals.

Tasks below marked **⚠ coordinate** touch another lane and need the owner's agreement first.
Everything unmarked is clear.

---

# Wave A — Buildout (FS-241 … FS-265)

### RAG / Compliance Assistant

The pipeline is complete and now has one consumer. These are the gaps that consumer exposed.

- **FS-241 · Document metadata record** · L · ⚠ coordinate (htreinen)
  There is no document row anywhere — everything lives in the Qdrant payload and S3 object
  metadata. That is why `is_form` is a filename regex, why `GET /rag/documents` can only return
  raw S3 keys, and why ingestion has no status. One table unblocks four separate items.
  *Done when:* a `documents` row exists per ingest with `doc_type`, `status`, `filename`,
  `uploaded_by`, `uploaded_at`, and `GET /rag/documents` returns it instead of keys.

- **FS-242 · `doc_type` at ingest** · M · needs FS-241
  Replace `_FORM_PATTERN` with a stored classification (`policy | sop | form | standard |
  agreement`), declared by the uploader and defaulted by the current heuristic.
  *Done when:* `SourceDoc.is_form` reads a field, and the Compliance Assistant can group by type.

- **FS-243 · Async ingestion (202 + status)** · L · ⚠ coordinate (htreinen)
  Pool #27 item 1. Parse→chunk→embed→upsert all run inside the POST; a large document exceeds
  the ingress read timeout and the caller cannot tell whether indexing finished.
  *Done when:* ingest returns 202 with a `doc_id`, the worker indexes, and
  `GET /rag/documents/{doc_id}/status` reports pending/indexing/indexed/failed.

- **FS-244 · Streaming answers** · M
  `LLMClient.stream_generate()` exists and no route uses it, so the Compliance Assistant shows
  nothing for the whole generation.
  *Done when:* an SSE route streams tokens and the page renders them as they arrive.

- **FS-245 · Answer feedback loop** · M
  Nothing records whether an answer was useful, so retrieval quality has no signal outside the
  eval suite.
  *Done when:* thumbs up/down persists with the query, the citations shown, and the ERP row
  count — the last one is what makes the operational leg's contribution measurable.

- **FS-246 · Saved questions** · S
  Compliance questions repeat across shifts. The suggestion chips are hardcoded.
  *Done when:* an org can save a question, and saved ones replace the hardcoded chips.

### ERP

- **FS-247 · ERP export definition** · M — pool #34
  `EXPORT_DEFINITIONS` has telemetry, kanban_tasks, registries. ERP entities are what an
  operator actually reconciles against and there is no way to get them out.
  *Done when:* ERP entities export tenant-scoped, with a test proving a second tenant's rows are
  absent from the file.

- **FS-248 · ERP events over WebSocket** · M — pool #35
  No ERP event reaches `websocket_manager`, so the hub needs a manual refresh.
  *Done when:* an inbound webhook produces a WebSocket message to that tenant only.

- **FS-249 · Dataverse purchase-order transformer** · M — pool #33
  `CORRELATION_ROUTES` routes only SAP. Do **not** reuse the SAP transformer — it reads SAP
  field names and would produce empty records and a confident report of zero anomalies.
  *Done when:* a synced Dataverse PO produces a correlation and the routing test covers the pair.

- **FS-250 · Odoo purchase-order transformer** · M — pool #33, same shape as FS-249.

- **FS-251 · ERP entity search API** · M
  `GET /entities` returns up to 1000 raw rows with no filter beyond `entity_type`. Anything
  operator-facing needs predicate search.
  *Done when:* status/date/supplier filters are server-side and the truncation header still tells
  the truth.

### Platform

- **FS-252 · Adopt the generated SDK** · S — pool #42
  Generated, committed, zero importers — so neither used nor verified, and free to drift.
  *Done when:* at least one real caller uses it, or it is deleted. Both are acceptable outcomes.

- **FS-253 … FS-258 · `response_model` burn-down, six batches** · M each
  **184 undeclared remain** (from 250). Continue the method in
  `docs/planning/hamad-response-model-burndown.md`; the AST sweep makes each batch safe.
  - FS-253 `compliance_reports` (9) + `compliance` (8)
  - FS-254 `audit` (5) + `feature_flags` (6)
  - FS-255 `bulk_operations` (6) + `data_residency` (6)
  - FS-256 `geotab` (8) + `fleet_logistics` first half
  - FS-257 `fleet_logistics` second half (23 total in that file — the largest single offender)
  - FS-258 `health` (17) — note these are probes; check what k8s reads before declaring.

- **FS-259 · Contract-gate ratchet raise** · M
  ~92 operations still non-conforming, mostly one behaviour: generated input reaching Postgres
  unvalidated and surfacing as 500 where the contract promises 4xx (64 `DataError` + 32
  `IntegrityError` at last count).
  *Done when:* the floor is raised with a measured margin, and the raise is justified by fixes
  rather than by luck.

- **FS-260 · Coverage thresholds** · S — pool #41
  None exist, and `vitest.config.ts` narrows coverage `include` to three paths, so the reported
  number is decorative and cannot regress.
  *Done when:* both suites have a threshold at today's real number.

### Infrastructure

- **FS-261 · Wire `monitoring/`, `autoscaling/`, `database-ha/` into an overlay** · M — pool #50
  Reviewed YAML that has run nowhere but a kind cluster.
  *Done when:* `kustomize build overlays/production` contains them, or `ci-cd.yml` applies the
  operator-gated stacks in a documented step, with the four k8s gates still green.

- **FS-262 · Probes, limits and `securityContext` for the seven workloads** · M — pool #54
  Four workers, otel and jaeger. Without probes a wedged worker is never restarted.

- **FS-263 · Placeholder-secret gate** · M — pool #53
  `base/object-store.yaml` and the two monitoring manifests ship DEV-ONLY credentials, honestly
  labelled in comments. **A comment is not a control.**
  *Done when:* a production build containing a known placeholder fails a CI gate.

- **FS-264 · Contract-gate observability** · S
  The gate's score is in a JUnit file nobody reads between runs.
  *Done when:* conformance and the undeclared-route count are visible as a trend, so a drift is
  noticed before the ratchet fails.

- **FS-265 · Compliance Assistant: ERP context admin view** · M
  The operational leg is invisible by design and traceable only in structlog. An admin-only view
  of what it contributed to a given answer closes the auditability gap without exposing it to
  ordinary users.
  *Done when:* an admin can see, for one answer, the rows the ERP leg supplied.

---

# Wave B — Fixes (FS-266 … FS-285)

- **FS-266 · `DELETE /rag/documents/{doc_id}` deletes vectors with no org filter** · S · ⚠ coordinate
  `rag_ingestion.py:513`. Cross-tenant if a doc_id is guessed; only the blob delete is scoped.
  The Compliance Assistant never calls it, so it is unreached — not fixed.

- **FS-267 · GeoTab presents fabricated HOS figures as measured** · M — pool #44
  16 `random.uniform` sites, including **DOT-regulated hours-of-service numbers**. Being a stub
  is defensible; presenting invented compliance figures as real is not.
  *Done when:* nobody can mistake a generated HOS figure for a measured one.

- **FS-268 · Migration chain hygiene** · M — pool #45
  Test fixtures (005/006/008/009) sit in the production chain, prefixes duplicate at
  004/005/007/009, 019 is missing, and not every migration is idempotent.
  *Done when:* the chain applies cleanly twice on an empty database.

- **FS-269 · Rotate the three development credentials** · S — pool #30
  SAP key, Intuit client secret, Dataverse client secret were all shared in conversation. None is
  in the repo; all three should be treated as compromised.

- **FS-270 · Rotate `HAMAD_IDE.pem`** · S — pool #49
  Untracked in FS-01 but **still in git history on both remotes**. Untracking does not revoke a
  key. Rotate first; decide the history purge separately.

- **FS-271 · `erp_database_replication.py`** · M — pool #36, *verify first*
  491 lines reported as entirely no-op. *Done when:* it does something with a test proving it, or
  it is deleted.

- **FS-272 … FS-279 · Contract non-conformance, eight batches** · M each
  The ~92 remaining operations, grouped by router. Each batch is per-endpoint input validation:
  a generated value reaching Postgres unvalidated becomes a 500 where the contract promises 4xx.
  Each batch raises the ratchet by its own measured amount.

- **FS-280 · The two unfixable `ruff` errors** · S — pool #57
  `pre-commit run --all-files` rewrites 781 files; 260 of 262 ruff errors auto-fix. The two that
  do not are the only non-mechanical part and need reading before the freeze window.

- **FS-281 · `test_document_domain_mapper` table-content mapping** · S · ⚠ coordinate (Harsh)
  The last quarantined test. `map_section_to_domain` returns `None` for a table whose header is
  `["asset_id","status"]` with a `"failed"` cell where the test expects `MNT`. A taxonomy
  decision, not a rewrite — it has been failing every run of this suite all session.

- **FS-282 · Frontend `USE_MOCK` drift audit** · M
  190 forks, and until FS-238 none was exercised in real mode. Sweep for mock branches whose
  shape no longer matches the real client.

- **FS-283 · Nullable-response audit on the pages that render blank** · M
  The `info`-badge class (defect 60) was one instance of "renders nothing, reports nothing".
  Sweep for others: fields the UI reads that the API never sends.

- **FS-284 · `GET /rag/documents` returns raw S3 keys** · S · needs FS-241
  No filenames, dates, or status. Callers must parse `key.split("/")[1]`.

- **FS-284b · 393 tests cannot run locally** · M · **schedule this early**
  Every `*_realdb*` and testcontainers-backed test errors at setup on a Mac/colima host:
  `error while creating mount source path '/Users/…/.colima/default/docker.sock': operation not
  supported` — Ryuk cannot bind-mount the socket. **1975 tests pass and 393 never execute**, and
  the ones that do not are precisely the tenant-isolation, RLS and real-schema tests: the suite
  is strongest exactly where a developer cannot run it.
  That gap has a history here. `test_audit_hash` passed for months against a `conftest`-created
  pgcrypto extension no migration installed, and the whole class was "the tests were not wrong
  about the code, they were wrong about the database". A local suite that silently skips its
  database half invites the same mistake.
  *Done when:* `TESTCONTAINERS_RYUK_DISABLED` (or a documented colima socket path) makes them run
  on a developer machine, **or** `make test` states plainly how many tests it is not running and
  why — the honest fallback, since a green run over 83% of the suite reads as a green suite.

- **FS-285 · Export delivery failure surfacing** · M
  `ExportDeliveryJob.error` is stored and the deliveries list returns it; confirm a failed
  scheduled export is visible to the operator who scheduled it rather than only in the row.

---

# Wave C — Testing (FS-286 … FS-305)

- **FS-286 … FS-291 · Real-mode frontend tests, six batches** · M each — pool #46
  `test/setup.ts` stubs `VITE_USE_MOCK=true`, so **the branch that runs in production is the
  branch nothing covers**. `loadInRealMode` exists and four clients use it.
  Batches: dashboard · assets/alarms · ERP · logistics · admin · analytics.
  *Done when:* each page's real path has coverage and new API clients are expected to have it.

- **FS-292 · `rag_eval` in CI** · S · ⚠ coordinate (htreinen) — pool #26
  Excluded from the default run, so the suite validating retrieval quality never runs on a PR.
  *Done when:* it runs, or the exclusion carries a written reason and an expiry.

- **FS-293 · Compliance Assistant end-to-end against the live stack** · M
  The presign path and the ERP leg are verified; the full query path through embeddings,
  reranking and generation is **not** — `rag-inference` needs ~5 GB of weights and the local
  Docker VM had 2.7 GB free.
  *Done when:* a real question returns a real cited answer, and the A/B with
  `RAG_ERP_CONTEXT_ENABLED` on and off is recorded. If the answers do not differ, the routing
  keywords are not earning their place.

- **FS-294 · Contrast/legibility guard beyond `STATUS_COLORS`** · M
  Rule 67: the suite has no opinion about what the screen looks like. Defect 60 reached ten call
  sites because nothing compares a foreground to its background.
  *Done when:* the rule covers buttons and badges, not just the status palette.

- **FS-295 · Visual regression on the five highest-traffic pages** · L
  Follows FS-294. The screenshot harness in `frontend/e2e/compliance-assistant.visual.ts` is the
  prototype.

- **FS-296 · RTO/RPO drill** · M — pool #51
  `docs/runbooks/rto-rpo-checklist.md` still has `[DURATION]` where the measured figures belong.
  **Measured numbers or it is not a DR plan.** Needs a drill, not a doc edit.

- **FS-297 · KEDA scale drill** · M — pool #52
  Thresholds have never been observed against real load. Schedule with FS-296.

- **FS-298 · `overlays/dr` against a second cluster** · M — pool #55
  The overlay exists and lints; its own header says it is unverified against a real cluster. Note
  it does not create cross-region replication — that is pgBackRest's job and it is what
  determines the RPO.

- **FS-299 · Cross-org RAG isolation test, unskipped** · S · ⚠ coordinate (htreinen)
  `test_isolation.py` skips the cross-org case unless `RAG_TEST_ORG_B_TOKEN` is supplied, because
  there is no create-org endpoint. That is the test that matters most.

- **FS-300 · ERP webhook end-to-end with a real vendor** · M — pool #32
  The raw-body HMAC scheme is proven against our own sender only. Intuit's sandbox sends genuine
  webhooks.

- **FS-301 · Migration idempotency test** · S · pairs with FS-268.

- **FS-302 · Tenant-isolation test for every new `response_model` route** · M
  63 routes were declared this session. Declaring what a route returns is not the same as
  proving it returns only your org's rows.

- **FS-303 · A response model's field TYPES must accept what the handler returns** · M
  *Closes the class behind the `SubscriptionDeleted` defect.*
  `test_response_models_match_their_returns` compares **key names** and would have passed the
  bug that nearly shipped: `DELETE /notifications/subscriptions/{id}` returns the path parameter
  — already a `UUID` — into a field typed `str`, and pydantic v2 does not coerce, so every
  successful delete would have 500'd on a route that worked the day before. The key was named
  correctly; only the type was wrong.
  *Done when:* the sweep also instantiates each model against representative values from its
  handler, and a `str` field fed a UUID fails. Mutation-verify by re-typing that field.

- **FS-304 · A declared media type must match what the handler actually returns** · M
  *Closes the class behind the `text/csv` defect, in both directions.*
  #38 fixed nine routes whose schema promised JSON while the handler sent xlsx/PDF/CSV. The
  inverse survived it: `GET /exports/jobs/{job_id}` declared `text/csv` and has only ever
  returned JSON, because that sweep looked for handlers *returning* binaries and not for
  declarations *claiming* one. It then fooled the new coverage ratchet, which believed the
  declaration and excluded a JSON route from its count — **a guard that reads a lie inherits
  it**, and that is the reusable lesson.
  *Done when:* one sweep checks both directions — every declared non-JSON content type has a
  handler returning a `Response`, and every handler returning one declares it.

- **FS-305 · Extend the returned-keys sweep to helper-built returns** · M
  The AST sweep sees only literal `return {...}`. `exports`, `fleet_health` and `data_retention`
  build payloads in shaping helpers, so they are covered by hand-written pairings in
  `test_declared_models_do_not_drop_fields` — which does not scale to the 184 routes left, and
  is exactly where the `count` defect hid (seven `query_performance` lists returning
  `{<items>, "count"}` against models declaring only the items key).
  *Done when:* a handler returning `_helper(...)` is resolved to that helper's literal dict, so
  the two files' coverage stops depending on which shape a route happened to use.

- **FS-306 · Worker restart/idempotency tests** · M
  Four workers with no probes (FS-262) and no test that a mid-job restart does not double-write.

- **FS-307 · Contract gate against a non-superuser role** · S
  The gate connects as a superuser, and **a superuser bypasses RLS even where FORCE is set** — so
  its results are not evidence about tenant isolation, and `api-contract-gate.md` says so.
  `conftest.py:139` already creates a `NOSUPERUSER NOBYPASSRLS` role for the real-DB suite.

---

# Wave D — Review (FS-308 … FS-323)

Cheap to run. Each either unblocks work or deletes it.

- **FS-308 · Decide the eight stale branches** · S — pool #62
  Eight branches, 28–112 commits ahead, none moved since 17 July while converged took 70+. The
  `origin` and `backup` copies have drifted apart from each other.
  *Done when:* each has a recorded decision — merge, re-cut, or delete. A branch nobody will
  merge should be deleted, not left as a decision somebody keeps re-making.

- **FS-309 · Strip `node_modules` from four branches** · M — pool #61
  19,048 files each. Any merge tries to bring 2.3M lines; `git diff` reports 20,000 changed files,
  so nobody can review what the branch contains. **Preserve first, clean second, let the owner
  do the cleaning.**

- **FS-310 · `main` promotion window** · S — pool #3/#39
  Every dev is told to branch from `main`, which is well behind converged, so each new branch
  starts from a stale base and inherits fixed bugs.

- **FS-311 · The `super_admin` role** · M — pool #4
  Two features need a cross-tenant role; `roles.py:48` documents the need and nothing implements
  it. Real blast radius, which is why neither shipped. *Done when:* scope is written into
  `roles.py` as the spec.

- **FS-312 · Correlation-AI honesty decision** · S · ⚠ coordinate (Harsh) — pool #1
  `CORRELATION_MODEL_ENABLED` defaults False, so **every deployment shows heuristics styled as AI
  output**. The engine labels itself `simulated: true`; nothing carries or displays it.

- **FS-313 · Collapse the two quarantine registers** · S — pool #2b
  `test_quarantine.py` and `test_ci_quarantine_expires.py` both hold the list and both must be
  hand-edited. Two sources of truth for "what is CI skipping" is the exact drift they exist to
  prevent.

- **FS-314 · Audit the 14 flapping contract operations** · M
  Named in `api-contract-gate.md`; four read live Postgres statistics the suite itself perturbs.
  Reducing the spread lets the ratchet's 9-point margin shrink.

- **FS-315 · i18n scope decision** · S — pool #47
  Full scaffold, 0 `useTranslation` call sites, ~560 hardcoded strings. Decide languages and
  surfaces, or remove the scaffold so it stops implying support.

- **FS-316 · Review the 190 `USE_MOCK` forks for deletion** · M
  Some exist only because there was no backend when they were written.

- **FS-317 · ERP → Kafka architectural decision** · M — pool #37
  Whether ERP belongs on the bus beside telemetry is an architecture question, not only an
  implementation one. *Done when:* the decision is recorded either way.

- **FS-318 · Security review of the 63 newly-declared routes** · M
  A declared schema is a published one. Confirm nothing now documents a field that should not
  leave the tenant.

- **FS-319 · Make the planning docs' own numbers checkable** · M
  **Every drift found this week made the written state look better than reality**, never worse:
  `data_retention` recorded as 8 routes and it has 12 across two routers; the contract floor
  recorded as 290 and it is 350; `response_model` recorded as 195/458 and it was 203/453. Drift
  in one direction is not noise — it is what happens when numbers are written once, by whoever
  did the work, and never re-derived.
  The repository already solves this for one document: `test_method_rules_are_indexed` fails when
  `defect-class-sweeps.md` and the README disagree about the rule count, and it caught me this
  week doing exactly that.
  *Done when:* the figures these planning docs quote — undeclared routes, contract floor and
  total, route count, quarantined tests — are asserted against the live measurement by a test, so
  a stale plan fails the build instead of misleading the next reader. Numbers a machine cannot
  check should be marked as estimates rather than stated as facts.

- **FS-320 · Dependency and supply-chain review** · S
  pip-audit/npm-audit/Trivy run in CI; nobody has read the accepted findings recently.

- **FS-321 · Read the `rag_ingestion_followups` list for deletion** · S · ⚠ coordinate (htreinen)
  Six items now. The list should not outlive its usefulness — pool #27's own framing.

- **FS-322 · Ownership-table rebalance** · S
  The pool noted Hamad holds 28 of 56 because the table gives him backend platform, frontend,
  deploy/CI, schema, observability and docs. That is still true and still the most obvious thing
  to rebalance.

- **FS-323 · Post-mortem: the commit-sweep incident** · S
  A concurrent session ran broad `git add` three times and swept an entire feature into commits
  labelled for unrelated work. Recoverable, and recovered — but worth a written rule about
  `git add -A` on a shared branch.

---

# Wave E — Buildout II (FS-324 … FS-343)

Deliberately after C and D: each needs a guard, a decision, or a measurement that Waves B–D
produce.

- **FS-324 · CNPG cutover and a real PITR** · L — pool #56 · needs FS-296
  The runbook still says *"Restoring PITR (not yet done)"*. Point-in-time recovery is a plan, not
  a capability. *Done when:* three healthy instances, a PITR restore performed, and that runbook
  section deleted because it is finally false.

- **FS-325 · Cross-region replication for the DR overlay** · L · needs FS-298
  Applying the overlay to an empty cluster gives running pods with no data.

- **FS-326 · Flip `pre-commit` to blocking** · M · needs FS-280 + FS-306
  The reformat touches every lane's files at once, so it must land as ONE commit in an agreed
  freeze window with every open branch rebasing after.

- **FS-327 · `super_admin` implementation** · L · needs FS-309.

- **FS-328 · Data-retention enforcement on a schedule** · M
  `/enforce` exists and nothing calls it. Same shape as the ERP `sync_schedule` gap — a cron
  string stored and never read.

- **FS-329 · ERP sync scheduler** · M
  `sync_schedule` and `sync_frequency_minutes` are stored on the integration row and **nothing
  reads them**. Sync is manual/API-triggered only, which is not what the UI implies.

- **FS-330 · Compliance Assistant: multi-turn follow-ups** · M · needs FS-244
  Strictly single-shot today, deliberately. A follow-up that keeps the prior citations in scope is
  the smallest useful step beyond it, and is still not a chat.

- **FS-331 · Cited-passage highlighting in the source document** · L · needs FS-241
  Open the PDF at the cited page with the passage highlighted, rather than at page 1.

- **FS-332 · Compliance corpus admin** · M · needs FS-241/242
  Upload, retire, and re-index from the UI — currently curl only.

- **FS-333 · ERP reconciliation report** · M · needs FS-247
  The export is the input; the report is what an operator actually wants.

- **FS-334 · Alarm-rule templates** · M
  Rules are defined one at a time; a fleet of identical assets needs a template.

- **FS-335 · Asset-health explainability** · M
  The score is computed by a pure function nobody can inspect from the UI.

- **FS-336 · Frontend SDK adoption, second consumer** · M · needs FS-252.

- **FS-337 · i18n first surface** · L · needs FS-313.

- **FS-338 · Contract conformance to 400+** · L · needs FS-272…279
  The practical ceiling is ~412 of 451 without a policy change (Pydantic strict mode, typed path
  converters). Getting there is the endgame of #38 and #43 together.

- **FS-339 · `response_model` coverage to zero undeclared** · L · needs FS-253…258
  184 remain. Zero is reachable because 204s and binary routes are already excluded from the
  count — the target is real, not aspirational.

- **FS-340 · Observability for the RAG pipeline** · M
  Retrieval latency, rerank scores, and generation time per query. The eval suite measures
  quality offline; nothing measures it live.

- **FS-341 · Edge-agent OTA staged rollout dashboard** · M · ⚠ coordinate (Hridyansh).

- **FS-342 · Tenant self-service org creation** · M · needs FS-309
  Also unblocks FS-299 — the cross-org isolation test skips because there is no way to make a
  second org.

- **FS-343 · Demo-path hardening** · M
  `seed_demo_data.py` covers every page; confirm it still does after 100 sprints of change, and
  make that a CI check rather than a manual one.

---

## Sequencing that actually matters

- **FS-241 before 242, 284, 328, 329** — the document record unblocks four items.
- **FS-280 + FS-308 before FS-326** — do not flip `pre-commit` until the freeze window is agreed
  and the branches are decided.
- **FS-296 before FS-324** — measure the RTO before claiming PITR works.
- **FS-311 before FS-327 and FS-342**.
- **FS-244 before FS-330**.
- **FS-253…258 before FS-339**, **FS-272…279 before FS-338** — the burn-downs are the endgames.
- **FS-294 before FS-295** — the rule before the screenshots, or the baseline bakes in the bug.

## What needs a decision before it can be scheduled

FS-312 (Harsh), FS-315, FS-317, FS-311, FS-320, and the freeze window for FS-326. Five of the six
are conversations, not sprints.
