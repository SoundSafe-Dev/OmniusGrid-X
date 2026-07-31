# `response_model` burn-down — pool #43, and the lane map that keeps it out of everyone's way

Started 2026-07-31 on `hamad/converged-pre-main`.

## Why this and not something else

Pool #43 is the prerequisite for #38 meaning what its name implies. The contract gate now
runs and blocks, but **schemathesis can only check what is declared** — so a gate over an API
where more than half the routes declare no response is validating well under half the surface.
Every route declared raises what the gate can see; every fix raises the ratchet.

**Measured 2026-07-31** (the pool's own instruction is to re-derive before starting, because it
drifts):

| Fact | Pool said | Actually |
|---|---|---|
| Undeclared routes in `app/api/` | 195/458 declared | **227 undeclared** of 419 |
| Contract ratchet floor | 290 | **350**, observed min 359 of 451 |
| Non-conforming operations | 152 | **~92** |

The other session moved 299 → 360 via the problem+json headers and UUID path params. The
remaining gap is smaller than the pool records and the shape is unchanged.

## The hazard this work carries

**Declaring a `response_model` is not additive — FastAPI filters the response through it.**
A model that omits a field the frontend reads deletes that field from the payload, and the UI
renders blank rather than erroring. That is this repository's most-documented defect class
(sweeps #19, #21) arriving through the front door.

So the method per route is fixed, and the second step is the one that matters:

1. Read what the handler actually returns — every branch, including error and empty paths.
2. **Grep the frontend for the consumer** and confirm every field it reads is in the model.
3. Declare the model, reusing an existing schema wherever one fits.
4. Prove it: a test that fails if a field is dropped.

A route whose real return shape cannot be pinned down gets **skipped and listed here**, not
guessed at. A wrong model is worse than none — none is honestly undeclared, wrong is a
contract that lies and a gate that certifies the lie.

## Lane map — measured, not assumed

Derived from each dev's **own commits** (`git log $(merge-base)..$branch`), not their branch
tips: every stale branch appears to touch 82 API files because it is 28–112 commits behind, so
tip-diffing is useless for this.

**Hands off — actively worked by someone else:**

| File | Contention | Owner |
|---|---|---|
| `auth.py` | 6/6 branches | Hridyansh (RBAC) |
| `kanban.py`, `telemetry.py` | 6/6 | shared / Harsh |
| `analysis_sessions.py` | 5/6, htreinen ×9 | htreinen |
| `nlp_correlation.py` | 5/6, htreinen ×7 | Harsh / htreinen |
| `model_monitoring.py` | 4/6 | Harsh (MLOps) |
| `logistics_correlation.py` | 6/6 | Harsh |
| `engines.py` | 6/6 | mixed — MLOps half is Harsh's |
| `rag.py` | — | htreinen |

**Safe — zero other branches touch them:** `fleet_health.py` (7), `notifications.py` (5),
`dashboard_analytics.py` (5), `simulation.py` (2), `fleet_agents.py` (1), `erp_webhooks.py` (1),
`alarm_rules.py` (1).

**Mine by lane, low contention** (platform / observability / schema / deploy, per the README
ownership table): `exports.py` (20), `query_performance.py` (12), `gdpr.py` (9),
`data_retention.py` (8), `compliance_reports.py` (8), `compliance.py` (8),
`feature_flags.py` (6), `bulk_operations.py` (6), `data_residency.py` (6), `audit.py` (5).

## The queue

| Batch | Files | Routes |
|---|---|---|
| Guard | ratchet test so new routes cannot land undeclared | — |
| 1 | the seven zero-contention files | 22 |
| 2 | `exports.py` | 20 |
| 3 | `query_performance`, `data_retention`, `gdpr` | 29 |
| 4 | `compliance_reports`, `compliance`, `audit` | 21 |
| 5 | `feature_flags`, `bulk_operations`, `data_residency` | 18 |

**110 routes available in-lane**, which is where the 100 comes from. The guard is first
deliberately: without it the ratio drifts back while the burn-down is still running, which is
exactly what happened between the pool being written and today (191/417 → 195/458 — the
absolute number rose while the ratio fell).

## Skipped, with reasons

*(appended as they are hit — a route listed here is a decision, not an oversight)*
