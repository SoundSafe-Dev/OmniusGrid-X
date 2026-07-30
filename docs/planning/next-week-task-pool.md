# Next week — task pool

Written 2026-07-26 for **Harsh as Product Manager**. Grouped by lane so it can be handed
out as-is; every task is independently assignable, so reassign freely.

Numbers are stable references — a task keeps its number if it moves lane.
**Every figure below was verified against the repository on 2026-07-26.** Tasks marked
*verify first* may already be fixed; the shape of the work depends on what is actually true.

> ### ⚠️ Verify before you start — the pool drifts faster than it is read
>
> **Re-audited 2026-07-30.** Of the four items picked up since this was written, **three had
> already been partly or wholly done**:
>
> * **#31** — the seeder DID set a webhook secret; it was a shared literal, which was a
>   different and worse defect than the one recorded. Now done.
> * **#40** — the `ws://` socket helper had already been deleted and the scheme already derived
>   from the page protocol. The only missing half was a test. Now done.
> * **#55** — `overlays/dr` exists, builds, and is linted by two CI jobs. Entry corrected.
> * **#43** — the ratio had moved the wrong way (191/417 → 195/458) because new routes landed
>   undeclared. Baseline corrected.
>
> This is not a criticism of the pool; it is what a written snapshot does while sixty-odd
> commits a day land against it. **Spend the first ten minutes of any item reproducing the
> claim.** If it does not reproduce, correct the entry in place with the date and what you
> found — that is worth more than the task was.

Sizes: **S** under half a day · **M** 1–2 days · **L** 3+ days.

*A print-ready PDF (one lane per page) is not committed — it would go stale beside this
file. Regenerate:*
`python3 tools/docs/md2pdf.py docs/planning/next-week-task-pool.md docs/planning/next-week-task-pool.pdf`

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

**Checked and found DONE — deliberately absent from this pool**, because the previous plan
still listed both: Redis is deployed (`base/redis-statefulset.yaml`), and server-side alarm
rules exist (`AlarmRule` model + `AlarmRules.tsx` with a test).

---

# Decisions — Harsh, as PM

These cost a conversation, not a sprint, and each blocks real work.

1. **Correlation-AI honesty — what does the product claim?** · *blocks #13, #14; shapes #15*
   `CORRELATION_MODEL_ENABLED` is `False` by default and the engine falls back to a
   heuristic, so **every deployment today shows heuristics styled as AI output**. The engine
   now labels its own output `simulated: true`, but nothing carries or displays that. Three
   defensible answers: label it in the UI, hide the AI tab when the model is off, or ship
   the adapter enabled.

   Done when: the answer is written down, and #13/#14 are either scheduled or closed as
   won't-do.

2. **Quarantined tests — MOSTLY ANSWERED 2026-07-30. One left, and it is the real one.**
   Four of the five were fixed: the three scenario-builder files were rewritten against the
   API their modules actually export (8 + 6 + 7 tests) and
   `test_image_domain_mapper.py::test_map_image_domains` was repaired. All four `--ignore`
   /`--deselect` flags are out of `ci-cd.yml` and both registers are updated. **No production
   code changed** — every one was a test left asserting the API that merge `42ed66d8`
   replaced.

   The register had reasoned these were "written against an API that never shipped" and left
   them for the owning lane. Half right, and the wrong half mattered: the API they wanted
   never shipped, but the builders they cover are **live on the intake path** —
   `nlp_correlation.py:1594/1655/1794` and `analysis_sessions.py:972` call them on every
   intake — so CI was skipping coverage of shipped code, not of an unbuilt feature. Worth
   remembering the next time a quarantine entry says "not mine to touch": check whether the
   thing under test is running in production before deciding it is someone else's problem.

   **Still open, and it needs HARSH specifically:**
   `test_document_domain_mapper.py::test_map_section_to_domain_table_content`.
   `map_section_to_domain` returns `None` for a table whose header row is
   `["asset_id", "status"]` with a `"failed"` cell, where the test expects `MNT`. That is a
   disagreement about what the mapper *should* do — either table-content mapping has a gap or
   the expectation was never right — and it is the only one of the five that needs a decision
   about the intended taxonomy rather than a rewrite. It stays quarantined, expiring
   2026-09-23.

   Done when: HARSH decides which of the mapper and the test is wrong, and #12 is scheduled.

2b. **The quarantine is tracked in two files that duplicate the same list.** S
   `tests/test_quarantine.py` and `tests/test_ci_quarantine_expires.py` both hold a register
   of what CI excludes, both check it against `ci-cd.yml`, and both had to be edited by hand
   for the change above. Two sources of truth for "what is CI skipping" is the exact drift
   these registers exist to prevent — they just cannot catch it in each other. Collapse to
   one, with the other importing it.

   Done when: one register is the source of truth and removing an entry means editing one
   file.

3. **`main` promotion window** · *pairs with #39*
   `hamad/converged-pre-main` is well ahead of `main`, and every dev is told to branch from
   `main`. The longer the gap, the more divergent everyone's starting point.

   Done when: a date is agreed and announced to the four active branches.

4. **The `super_admin` role** · *blocks #23, and `data_retention.py`*
   Two features need a role that spans tenants, which is a deliberate hole in the RLS model.
   `app/core/roles.py:48` documents the need; nothing implements it. It has a real blast
   radius, which is why neither feature shipped.

   Done when: scope is decided — which routes, which audit trail, who can grant it — and
   written into `roles.py` as the spec #23 builds against.

---

# Alex — intake & spreadsheet parsing
*Under Harsh. Sequenced: #5 and #6 finish work he already started.*

His onboarding landed here — he fixed `normalize_key`, added `normalize_column_header`,
added a messy real-world CSV fixture, and wrote `docs/DATA_FLOW_OVERVIEW.md`.
**Two of those three code additions are not connected to anything**, which is the natural
next step and teaches the lesson this codebase keeps relearning.

5. **Wire `normalize_column_header` into its callers** · S
   He added it with three passing tests and **no production caller** — `grep` finds it only
   in its own test file, so it currently normalises nothing. Eight modules consume
   `shared_key_detector`; the spreadsheet path (`multi_spreadsheet_correlator`) is the one
   that ingests headers.

   Do: route header ingestion through the helper, then assert a realistic header row
   normalises end to end rather than unit-testing the helper again.

   Done when: removing the call makes a test fail. A helper with a test and no caller does
   nothing.

6. **Make the messy fixture assert something** · S
   `tests/load/fixtures/messy_factory_upload.csv` is referenced by **no test**. He built it
   to represent real-world mess, and right now it is a file that proves nothing.

   Do: point a parser test at it and assert the keys and headers that come out.

   Done when: corrupting a column in the fixture fails the test.

7. **Decide and test header-collision behaviour** · S
   `Serial #` and `Serial No.` may both normalise to `serial_number`. Today's behaviour is
   **unknown** — one column may be silently overwriting another, which is data loss that
   looks like success.

   Do: find out what happens now, choose the behaviour (last-wins, first-wins, or raise),
   and implement it deliberately.

   Done when: the chosen behaviour is asserted by a test, with the reasoning in the
   docstring so nobody re-litigates it.

8. **Extend the messy-header corpus** · M
   The fixture covers one shape of mess. Real customer spreadsheets bring merged cells, a
   title row above the header, trailing total rows, unit suffixes (`Temp (°C)`), duplicate
   names, non-ASCII, and Excel coercing values to dates.

   Done when: each case has a named test saying what real situation it represents, and the
   parser either handles it or fails loudly rather than silently mis-parsing.

9. **Fold `docs/DATA_FLOW_OVERVIEW.md` into the architecture docs** · M · *stretch*
   He wrote 114 lines living outside `docs/architecture/`, alongside an existing
   `DATA_FLOW.md`. Two descriptions of one flow will disagree, and nobody will know which
   is current.

   Done when: one document describes the flow and the other is gone, not left as a stale
   copy.

---

# Harsh — correlation AI, NLP, kanban, MLOps
*His own lane until he reassigns it. #10 is the one only he has the context for.*

10. **Unquarantine the three scenario builders** · M · *needs #2*
    `test_document_scenario_builder.py`, `test_image_scenario_builder.py` and
    `test_cross_file_scenario_builder.py` fail at collection with
    `ImportError: cannot import name 'build_document_scenarios'`. The test and the module
    disagree about the API; only he knows which side is right.

    Done when: the three files are passing and un-ignored in `ci-cd.yml`, or deleted with a
    one-line note saying why.

11. **Re-enable the two deselected tests** · S · *needs #2*
    `test_document_domain_mapper.py::test_map_section_to_domain_table_content` and
    `test_image_domain_mapper.py::test_map_image_domains` are `--deselect`ed.

    Done when: both run in CI, or are deleted.

12. **Make the quarantine expire** · S
    Nothing stops an exclusion becoming permanent — a `--ignore` is invisible in a green
    build, which is how these five survived.

    Do: add a named marker plus a test that fails once an expiry date passes.

    Done when: adding a new exclusion without an expiry date fails CI.

13. **Plumb the `simulated` flag through the API** · S · *needs #1; blocks #14*
    **The honesty fix currently stops at the service layer.** Verified: no file in
    `app/api/` reads the key. `nlp_correlation.py:1152-1155` cherry-picks exactly four
    values out of the analysis, and `/query` returns `response_model=NLPQueryResponse`,
    which declares no `simulated` field and would strip it even if the handler copied it. So
    the engine labels its output and nothing downstream can see the label.

    Done when: a test asserts the flag survives the HTTP boundary with
    `CORRELATION_MODEL_ENABLED=False`.

14. **Show the user when an analysis is simulated** · S · *needs #13*
    Once the flag reaches the client, `CorrelationAIPane.tsx` has to render it — a badge, a
    banner, whatever #1 decided.

    Done when: with the model disabled the UI visibly distinguishes a heuristic from an
    inference, and a test covers it.

15. **Make the Gemma adapter loadable in a dev environment** · M
    `CORRELATION_ADAPTER_PATH` defaults to `./checkpoints/best_lora_v2`, which no
    documentation explains how to obtain. The load failure is caught per request and
    swallowed into the fallback, so a misconfigured path looks like a working system.

    Do: document how a dev gets the adapter, and make a failed load loud at startup rather
    than silent on every request.

    Done when: a dev can follow written steps to a real inference, and a bad
    `CORRELATION_ADAPTER_PATH` fails visibly instead of silently degrading.

16. **Kanban RLS-write-on-read** · M · *verify first*
    `kanban.py` mixes 10 `get_db` and 14 `get_tenant_db`. One root cause was reported to
    500 `/kanban/board`, `/metrics` and `/workload` — the same class as the ERP sync that
    wrote nothing on a non-owner role.

    Do: reproduce on real Postgres as a non-owner role first, since it may already be fixed.
    Then convert the handlers that touch RLS-protected tables.

    Done when: those three endpoints return data on real Postgres as a non-owner role, with
    a test that fails if a handler regresses to `get_db`.

17. **`/nlp/correlation/intake/{id}` 500** · S · *reported; verify*
    Reported as a 500. Unverified.

    Done when: either a fix with a regression test, or a note that it no longer reproduces.

18. **First tests for `correlation_ai_engine.py`** · L
    3,627 lines, and `pytest -k correlation` deselects 1,245 tests and runs **none** against
    it. Every change to it is currently unverifiable.

    Do: start with the pure scoring helpers that need no model — `_calculate_risk_score`,
    `_simulate_root_cause`, `_generate_kanban_tasks`.

    Done when: the scoring helpers have known-input/known-output tests, so a change to risk
    scoring cannot land silently.

19. **Split `CorrelationAIPane.tsx`** · L
    843 lines with no test. Data-fetching and layout are entangled, so neither can be
    tested without the other.

    Done when: data-fetching is extracted from presentation, and at least the fetching layer
    has tests.

---

# Hridyansh — tenant isolation, RBAC, OTA, edge

20. **`get_db` on RLS-protected tables — 24 API files** · L · ⭐ *highest-value task here*
    The class of bug that made the ERP background sync write nothing on a non-owner role and
    hid the dashboard's data behind zeroes. A handler using `get_db` never sets
    `app.current_org_id`, so an RLS predicate evaluates NULL and rows silently vanish —
    reads return empty, writes are rejected. Invisible in dev, because the dev connection
    owns the tables and owners bypass RLS.

    Do: **write the guard test first** — one that fails when a handler depending on `get_db`
    queries an RLS-protected model. Then work the 24 files against the RLS tables in
    migrations `011`/`033`.

    Done when: the guard exists and passes, and every handler touching an RLS-protected
    table uses `get_tenant_db`. The guard matters more than the sweep; without it the next
    one ships too.

21. **`ORGANIZATION_ID` is hardcoded in the edge StatefulSet** · S
    `base/edge-agent-statefulset.yaml:62,64` sets `"dev-org"`, so **every edge agent in
    every environment reports into the same fake organisation** — production included.

    Done when: the value comes from per-environment configuration, and no overlay ships
    `dev-org`.

22. **Edge backoff jitter** · S
    Without jitter, a fleet that loses the backend reconnects in lockstep and stampedes it
    the moment it returns, turning a brief outage into a longer one.

    Done when: reconnect delay is randomised, and a test shows N agents do not retry in the
    same instant.

23. **Organisation management CRUD** · M · *needs #4*
    `AdminPages.tsx` sets `USER_MGMT_ENABLED = false`, so the UI exists and is switched off.
    Only `GET /users` is implemented.

    Do: add create/update/deactivate/role-change with `require_admin` and tenant scoping,
    then turn the flag on.

    Done when: an admin can manage users in their own org through the UI, an operator
    cannot, and a cross-tenant attempt is refused by a test.

24. **Collector tests** · M
    The collector has no tests, so its parsing and batching behaviour is unverified.

    Done when: the happy path and at least malformed-input handling are covered.

---

# htreinen — RAG

25. **`/rag/documents` leaks a raw SeaweedFS error** · S
    An infrastructure connection error is surfaced verbatim to the client instead of a 503 —
    unreadable for the caller, and an information leak about internal topology.

    Done when: the endpoint returns 503 with a generic message, the detail is logged
    server-side, and a test covers the storage-unavailable path.

26. **`rag_eval` is excluded from the default test run** · S
    So it has zero coverage in CI, and the suite that validates retrieval quality never runs
    on a PR.

    Done when: it runs in CI, or the exclusion carries a written reason and an expiry
    (see #12).

27. **The five open items in `docs/rag_ingestion_followups.md`** · M
    Carried from the ingestion work and not yet scheduled.

    Done when: each is done or removed from the list with a reason — the list should not
    outlive its usefulness.

28. **RAG containerisation seam** · M
    `docs/RAG_CONTAINERIZATION.md` describes a seam that is not yet realised, so the RAG
    backend cannot be deployed the way the document says.

    Done when: the documented topology is what actually runs, or the document is corrected
    to match reality.

---

# Hamad — ERP connectors

29. **Intuit tier 4** · S
    Everything is built — connector, 87 hermetic tests, 16 live-ready tests,
    `scripts/intuit_authorize.py`, a CI job. It needs the one-time human consent, because
    QuickBooks offers no client-credentials grant.

    Do: register `http://localhost:8399/callback` on the app, run the authorize script,
    store the refresh token and realm id as CI secrets.

    Done when: `test_erp_intuit_sandbox.py` runs green against a real sandbox company. Note
    the refresh token **rotates**, so two people using the same company will fight over it.

30. **Rotate the three development credentials** · S
    The SAP key, Intuit client secret and Dataverse client secret were all shared in
    conversation during development. None is in the repository, but all three should be
    treated as compromised.

    Done when: all three are rotated and stored as repository secrets, and the
    `erp-sap-sandbox`, `erp-intuit-sandbox` and `erp-dynamics-sandbox` jobs stop skipping.

31. **Give seeded ERP integrations a `webhook_secret`** · S · ✅ DONE
    *Partly stale when picked up: the seeder DID set one, but as the literal `"demo-secret"` —
    which is two problems in one string. Migration 049's unique index means a second seeded
    integration (or a second demo organisation) is rejected by a constraint rather than
    anything readable; and a signing key committed to the repository would let anyone who has
    cloned this forge a webhook against a demo deployment. Now derived per integration id:
    distinct between integrations, stable across re-seeds, since the seeder deletes and
    reinserts on every run and an operator wiring up a real sender needs the value to survive
    that. `test_demo_can_receive_a_signed_webhook_realdb.py` proves a webhook signed with the
    seeded secret is ACCEPTED end to end, with a wrong-signature control — the seeder writing a
    well-formed secret proves nothing if the receiver would reject it.*
    Migration 049 enforces uniqueness and the demo seeder sets no secret — so the demo
    cannot exercise the webhook path at all, and two seeded integrations would collide if it
    did.

    Done when: `seed_demo_data.py` generates a distinct secret per integration, and the demo
    can receive a signed webhook.

32. **Verify a real vendor webhook end to end** · M
    The raw-body HMAC scheme is proven against our own sender only. Intuit is the one vendor
    whose scheme is verified against vendor documentation, and its sandbox sends genuine
    webhooks.

    Done when: a real Intuit webhook is accepted, stored as an `ERPIntegrationEvent`, and a
    replay of it is deduplicated.

33. **Correlation transformers for a second vendor** · M
    `erp_sync_correlation.CORRELATION_ROUTES` routes only SAP, because
    `transform_purchase_order` reads SAP field names. Dataverse and Odoo purchase orders are
    reported as `skipped: unrouted` — honest, but no correlations are produced for either.

    Do: write a transformer that reads that vendor's field names and register the route. Do
    **not** reuse the SAP transformer; it would produce empty records and a confident report
    of zero anomalies.

    Done when: a synced Dataverse or Odoo purchase order produces a correlation, and the
    routing test covers the new pair.

34. **ERP export definition** · M
    `EXPORT_DEFINITIONS` has `telemetry`, `kanban_tasks` and `registries`. ERP entities are
    exactly what an operator wants for reconciliation, and there is no way to get them out.

    Done when: ERP entities are exportable and tenant-scoped, with a test proving a second
    tenant's rows are absent from the file.

35. **ERP events over WebSocket** · M
    No ERP event reaches `websocket_manager`, so the ERP hub never updates live — a synced
    or webhook-delivered change needs a manual refresh.

    Done when: an inbound webhook results in a WebSocket message to that tenant only.

36. **`erp_database_replication.py`** · M · *verify*
    491 lines, reported as entirely no-op. If true, it is 491 lines that look like a feature
    and are not.

    Done when: either it does something, with a test proving it, or it is deleted.

37. **ERP → Kafka** · L
    No ERP producer exists. Whether ERP data belongs on the bus alongside telemetry is an
    architectural question, not only an implementation one.

    Done when: a decision is recorded, and if yes, ERP events are produced and consumed with
    the same idempotency guarantees as telemetry.

---

# Hamad — platform, frontend, CI

38. **Flip `api-contract` to blocking** · ~~S~~ **M** · ⚠️ *three premises tested 2026-07-30, all false*
    The job says it is "ready to flip pending one green CI run". It is not, and it could not
    have been. I ran it.

    **(a) "schemathesis can't be run locally" — false.** It is pinned in
    `requirements-dev.txt` and installs and runs fine. That sentence is the stated reason the
    job stayed advisory, and it had stopped being true.

    **(b) The job cannot finish.** Measured: **~2.5 minutes per operation** (21 health
    operations, 4 verdicts in 10 minutes) × **451 operations ≈ 19 hours**. Nothing caps it —
    there is no `max_examples`, no registered hypothesis profile anywhere in the repo, and no
    `timeout-minutes` on the job, so it runs into GitHub's 6-hour limit and gets killed. With
    `continue-on-error: true` that kill is invisible. **This job has never passed and cannot,
    so "observed green in CI" was never reachable.**

    **(c) It also genuinely failed.** ✅ **FIXED** — the first real defect it found is now
    closed: the problem+json envelope discarded `exc.headers`, so **every 405 the API has ever
    returned lacked `Allow` (RFC 9110 §15.5.6) and every 401 lacked `WWW-Authenticate`
    (§11.6.1)** — both mandatory, both needed by a client to act on the response. One defect,
    but it failed on all 451 operations, because schemathesis probes each with an undeclared
    method. Fixed in `app/core/errors.py` and mutation-verified by
    `tests/test_error_envelope_keeps_required_headers.py`.

    **And note what a green run would prove.** Only **195/457 routes (43%) declare a
    `response_model`** (#43), and schemathesis can only check what is declared — so this gate
    validates well under half the API even when it works. #43 is a prerequisite for this gate
    meaning what its name implies, not a separate nice-to-have.

    Do: cap the property search (a hypothesis profile with a small `max_examples` for CI),
    add `timeout-minutes` so a runaway fails loudly instead of silently, re-run to enumerate
    what remains, then flip. The cap is a real trade-off — fewer examples find fewer bugs —
    so it wants a deliberate number, not a default.

    Done when: the job completes inside its timeout, is blocking, and green.

39. **Promote `main`** · S · *needs #3*
    The mechanical half of #3. Every dev is told to branch from `main`, which is well behind
    the converged branch — so each new branch starts from a stale base and inherits bugs
    already fixed.

    Done when: `main` matches the converged branch, CI is green on it, and every dev has been
    told to rebase.

40. **Frontend WebSocket defaults to `ws://`** · S · ✅ DONE
    *Was already half-fixed when picked up: `fleetHealth.ts`'s socket helper had been removed
    (it opened `/ws/fleet-health`, a route the backend does not serve, and defaulted to
    `ws://`), and `websocket.ts` already derived the scheme from `window.location.protocol`.
    The unfinished half was the test — the derivation was correct and NOTHING asserted it, so a
    regression would have been silent until an operator on HTTPS noticed the fleet had stopped
    updating, which reads as a quiet fleet rather than a broken socket. `getWsUrl` and
    `getApiUrl` are exported and covered by `src/api/urlDerivation.test.ts`; reverting the
    scheme turns three of its nine red. The localhost audit found two fallbacks, both
    dev-gated and both correct.*
    `api/fleetHealth.ts:156` defaults to the insecure scheme, so **fleet-health sockets
    break on any HTTPS deployment** — production included.

    Do: derive the scheme from the page protocol, and audit the other hardcoded `localhost`
    fallbacks while there.

    Done when: an HTTPS deployment gets `wss://` with no configuration, and a test covers
    the derivation.

41. **Coverage thresholds** · S
    None exist, and `vitest.config.ts` narrows coverage `include` to three paths — so the
    reported number is decorative and cannot regress.

    Done when: both suites have a threshold set at today's real number, so coverage can only
    go up.

42. **Adopt the generated SDK** · S
    It is generated, committed, and has **zero importers** — so it is neither used nor
    verified, and will drift from the API silently.

    Done when: at least one real caller uses it, or it is deleted.

43. **`response_model` coverage: 195/458 (42%)** · M · ⚠️ *baseline was stale*
    **Re-measured 2026-07-30.** The entry said 191/417 (45%). The route count has grown since
    it was written, so the ratio has gone DOWN while the absolute number went up — new routes
    are landing without a declared response. Measure before claiming progress against this one.

    Undeclared responses make the OpenAPI schema fiction for more than half the API, which also
    weakens #38 — schemathesis can only check what is declared.

    Done when: coverage is meaningfully above 42%, prioritising the routes the frontend
    actually calls, AND new routes cannot land undeclared (otherwise the ratio drifts back).

44. **GeoTab is 100% synthetic** · M
    16 `random.uniform` sites in `geotab_service.py`, including **DOT-regulated
    hours-of-service numbers**. Being a stub is defensible; presenting fabricated compliance
    figures as real is not.

    Do: label the data as simulated at the API and in the UI, or gate the surface behind a
    flag that is off by default.

    Done when: nobody can mistake a generated HOS figure for a measured one.

45. **Migration chain hygiene** · M
    Test fixtures (005/006/008/009) sit in the production chain, prefixes are duplicated at
    004/005/007/009, 019 is missing, and not every migration is idempotent.

    Done when: the chain applies cleanly twice in a row on an empty database, and
    `check_migrations.py` passes (see #48).

46. **190 `USE_MOCK` forks, and every test runs in mock mode** · L
    `frontend/src/test/setup.ts` stubs `VITE_USE_MOCK=true`, so **no test ever exercises the
    real client path** — the branch that runs in production is the branch nothing covers,
    and it can drift from the API undetected.

    Do: add real-mode tests (MSW against the OpenAPI schema), starting with pages that have
    real backends.

    Done when: the real path has coverage for at least the dashboard and ERP pages, and new
    API clients are expected to have it.

47. **i18n: 0 `useTranslation` call sites** · L
    A full i18n scaffold with locale files, and roughly 560 hardcoded strings. The scaffold
    implies a capability the product does not have.

    Do: decide scope first — which languages, which surfaces, whether this is wanted at all
    — then extract.

    Done when: either a first surface is genuinely translated end to end, or the scaffold is
    removed so it stops implying support.

---

# Hamad — deploy & infrastructure

60. **`backup/alex` exists on NO origin remote** · S · ✅ DONE 2026-07-30
    89 commits of Alex's work lived on the mirror only; `origin` had no `alex` branch at all.
    Pushed to `origin/alex` at `d5286f1c` — additive, creating a new ref, nothing rewritten and
    nothing on the mirror touched.

    Still worth Alex knowing: the two remotes drifted because pushes went to one of them. The
    branch is safe now, but keeping it that way means pushing both.

61. **Four branches carry `node_modules` in git** · M · *re-measured 2026-07-30*
    `backup/alex` (19,048), `origin/alex` (19,048), `origin/HARSH-CONTRIBUTION` (19,056) and
    `origin/htreinen` (19,048). Converged tracks zero.

    **`origin/alex` is on this list because of #60, deliberately.** Pushing Alex's 89
    single-homed commits to `origin` mirrored the branch as it stood, `node_modules` and all.
    Stripping them would have rewritten his history without asking him, which is a worse thing
    to do to someone's only remaining copy than carrying the files for a few more days. The
    ordering matters if this comes up again: *preserve first, clean second, and let the owner
    do the cleaning.*

    Two consequences, and the second is the expensive one: any merge from them tries to bring
    2.3 M lines with it, and their real diffs are unreadable — `git diff` against converged
    reports 20,000 changed files, so nobody can see what the branch actually contains. That is
    a review nobody will do.

    Do: the branch owners strip `node_modules` (it is already in `.gitignore` on converged) and
    force-push, or the branches are re-cut from converged with only the real changes cherry-picked.

    Done when: `git ls-tree -r <branch> | grep -c node_modules/` is 0 on all three.

62. **Eight branches have not moved since 17 July** · S · *measured 2026-07-30*
    `HARSH-CONTRIBUTION`, `htreinen`, `feature/gemma-correlation-ai` and five `hridyansh/*`
    branches, each 28–112 commits ahead of converged, all last committed 2026-07-17 — while
    converged has taken 70+ commits since. The `origin` and `backup` copies have also drifted
    apart from each other (`backup/hridyansh/integration` is 38 commits ahead of `origin`'s;
    `backup/feature/RAG-Compliance-Doc-Pipeline` is 282 ahead).

    Every day this holds, the eventual merge gets harder and the chance the work is re-done by
    someone else goes up — which is the concrete form of "devs working uselessly".

    Do: for each, decide merge / re-cut / delete. A branch nobody will merge should be deleted,
    not left as a decision somebody has to keep re-making.

    Done when: each of the eight has a recorded decision.

57. **`pre-commit` cannot be made blocking by flipping the flag** · M · *measured 2026-07-30*
    The job is `continue-on-error: true` under a comment reading *"Advisory while the existing
    tree is brought into compliance."* The tree is **not** in compliance, and the gap is much
    larger than that comment implies.

    `pre-commit run --all-files` rewrites **781 files — 45,405 insertions, 33,106 deletions**:
    ruff (262 errors, 260 auto-fixed, 2 remaining), ruff-format, prettier, trailing-whitespace
    and end-of-file-fixer, across `backend/tests` (191), `backend/app` (131), `frontend/src`
    (~90), `edge-agent` (40) and `database/migrations` (14).

    **Do not just flip the flag.** The compliance commit touches every lane's files at once, so
    it will conflict with all eleven outstanding branches — the eight that have not moved since
    17 July would each need a manual rebase through a whole-tree reformat.

    Do: agree a freeze window, land the reformat as ONE commit that changes nothing else, have
    every open branch rebase, and only then flip the flag. The 2 unfixable ruff errors need
    reading first — they are the only part that is not mechanical.

    Done when: the job is blocking and green, and `git log` shows the reformat as a single
    isolated commit.

    *(Verified by running it. The working tree was reverted; nothing was reformatted.)*

58. **Two CI jobs are advisory and one is deliberately so** · S · *measured 2026-07-30*
    Beyond #38's `api-contract`:

    * `pre-commit` — see #57, and it is the substantial one.
    * `load-test` (k6, `--vus 5 --duration 30s`) — `continue-on-error: true` and pointed at
      `BASE_URL: http://localhost:8000`, which CI does not stand up, so it is a smoke run
      against nothing. Either stand the app up for it or delete the job; a load test that
      cannot fail and has no target is a green tick for no work.
    * SBOM generation (`ci-cd.yml`) — **deliberate and correctly reasoned**, under a comment
      saying *"generation failure must not block a deploy."* Leave it. Recorded here so the
      next audit does not re-flag it.

    Done when: `load-test` either runs against a real target or is gone.

59. **`backend/dataset`: 1.5 GB on disk, 41 MB packed** · S · ✅ MOSTLY DONE · ⚠️ *my own figure was wrong*
    **Corrected and largely fixed 2026-07-30.** The original entry said "1.57 GB of the 1.59 GB
    repository — 99% of every clone". That measured the WORKING TREE. Git stores the corpus
    compressed and deduplicated: the whole repository packs to **96 MB**, of which the dataset
    is **41 MB**. The clone was never the problem — the checkout is.

    **Do not delete it.** `generate_dataset_enhanced.py` sets no random seed and can call an LLM,
    so the corpus is *generated* but **not reproducible**: deleting it loses ~500,000 scenarios
    that cannot be regenerated identically, and the fine-tuning results stop being explicable.

    Done: all 28 `actions/checkout` steps now sparse-checkout without it (no job read it, so
    every CI run was writing 1.5 GB for nothing); `make lean` / `make unlean` do the same for a
    developer's working tree, measured at 1.6 GB → 104 MB; `.gitignore` now stops the NEXT
    corpus landing in git.

    Left open, and small: getting 41 MB out of history needs a rewrite, which breaks every
    outstanding branch — same coordinated window as #49, not a separate one. See
    `docs/engineering/large-assets.md`.

48. **Wire `check_migrations.py` into CI** · S · ✅ **ALREADY DONE** · ⚠️ *entry was stale, verified 2026-07-30*
    This was closed by FS-203 and the entry was never updated. `quality-gates.yml:147-169`
    runs it as the `migration-hygiene` job — blocking (no `continue-on-error`), on every push
    to the branch namespaces that exist and on every PR to `main`.

    Checked because a stale "do this" is more expensive than a stale "done": it costs
    somebody the whole investigation before they find the work already exists. Both stale
    entries found this way so far (#55, #48) were stale in that direction.

49. **Rotate `HAMAD_IDE.pem`** · S · *needs coordination*
    The key was untracked in FS-01 but **remains in git history on both remotes**.
    Untracking does not revoke a key.

    Do: rotate the key first. Decide separately whether to purge the history, since a
    rewrite invalidates everyone's clones and needs a scheduled window.

    Done when: the old key is revoked, and the history decision is recorded either way.

50. **`monitoring/`, `autoscaling/` and `database-ha/` are referenced by no overlay** · M
    `overlays/production/kustomization.yaml` builds `../../base` plus `hpa.yaml` and nothing
    else. The in-cluster Prometheus/Grafana, the KEDA scalers and the CloudNativePG HA stack
    are reviewed YAML that **has run nowhere but a kind cluster**.

    Done when: `kustomize build overlays/production` contains them, or `ci-cd.yml` applies
    the operator-dependent stacks in a documented step — and the four blocking k8s gates
    stay green.

51. **RTO/RPO checklist is still a template** · M
    `docs/runbooks/rto-rpo-checklist.md` has `[DURATION]` where the measured RTO and RPO
    belong. **Measured numbers or it is not a DR plan** — an untested recovery procedure is
    a guess.

    Do: run a restore drill and time it. This needs a drill, not a doc edit.

    Done when: both figures are real measurements, with the date they were taken.

52. **KEDA scale drill** · M
    The autoscalers have never been observed scaling on real load, so the thresholds are
    theoretical.

    Do: run `tests/load/ingestion_load.py` against staging and watch the HPA.

    Done when: `kubectl get hpa` shows an observed scale-up under load and scale-down after,
    recorded alongside #51.

53. **Placeholder secrets can reach production** · M
    `base/object-store.yaml`, `monitoring/grafana.yaml` and `monitoring/alertmanager.yaml`
    ship DEV/CI-ONLY credentials — including a placeholder Grafana admin password with
    anonymous Viewer enabled. They are honestly labelled in comments; **nothing enforces
    that production overrides them.**

    Done when: a production build containing a known placeholder fails a CI gate. A comment
    is not a control.

54. **Probes, resource limits and `securityContext` for the four workers, otel and jaeger** · M
    Without probes a wedged worker is never restarted; without limits one can starve the
    node; without `securityContext` they run more privileged than they need.

    Done when: all seven workloads have liveness/readiness probes, requests and limits, and
    a non-root `securityContext`.

55. **`overlays/dr` — the overlay EXISTS; what is left is verifying it** · M · ⚠️ *entry was stale*
    **Corrected 2026-07-30.** The overlay was written (FS-230): distinct namespace, DR
    hostnames, cold-site replica counts. It builds, and `quality-gates.yml` already lints it
    alongside base/staging/production in two separate jobs. Do not write it again.

    Its own header states the part that IS still open, and states it accurately: *"UNVERIFIED
    AGAINST A REAL CLUSTER. There is no second cluster to try it on."* It also does not create
    cross-region replication — that is pgBackRest's job and it is what actually determines the
    RPO, so applying this overlay to an empty cluster gives you running pods with no data.

    Done when: the runbook's steps have been executed against a second cluster, including the
    restore step — which is the one that matters and which the overlay does not replace.

56. **CNPG cutover — what makes PITR real** · L
    `docs/runbooks/database-backup-restore.md` still says *"Restoring PITR (not yet done)"*
    and marks itself not operational. Point-in-time recovery is a plan, not a capability.

    Do: build the TimescaleDB-enabled CNPG image, install the operator, run the documented
    cutover, repoint `DATABASE_URL` at the pooler.

    Done when: `kubectl cnpg status` shows three healthy instances, a PITR restore has been
    performed, and that runbook section is deleted because it is finally false.

---

## Notes for redistribution

**Lane totals:** decisions 4 · Alex 5 · Harsh 10 · Hridyansh 5 · htreinen 4 ·
Hamad ERP 9 · Hamad platform 10 · Hamad infra 9. **56 total.**

Hamad's three sections hold 28 of 56, because the ownership table currently gives him
backend platform, frontend, deploy/CI, schema, observability and docs. **That is the most
obvious thing to rebalance** — #40, #41, #42, #43 and #48 are self-contained and need no
ERP or deploy context.

**Sequencing that actually matters:**

- #2 before #10/#11/#12 — no point fixing tests that may be deleted.
- #1 → #13 → #14, in that order. The flag is not in the API response yet, so building the
  UI first would have nothing to read.
- #4 before #23.
- #5/#6 before #8 — finish the wiring before widening the corpus.
- #20's guard test before its 24-file sweep.
- #48 before #45 — get the check running, then fix what it finds.
- #51 and #52 are one drill, scheduled together.

**Verify before scheduling:** #16, #17, #36. Some may already be fixed.

**The single highest-value task is #20.** It is the root cause behind at least three
separate user-visible bugs found so far, and its guard test matters more than the sweep —
without it the next one ships too.
