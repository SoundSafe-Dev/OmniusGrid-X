# ERP integrations — start here

Eight connectors: **SAP S/4HANA, Oracle Fusion, Dynamics 365, NetSuite, Odoo, Infor
ION, Epicor Kinetic, Intuit QuickBooks**.

You can do useful ERP work with **zero credentials**. Most of the suite is hermetic
and everything needing a live system skips cleanly when its variables are absent. Add
credentials only for the tier you're actually working on.

| I want to… | Read |
|---|---|
| Understand how we get confidence without owning these systems | [validating-connectors-without-an-erp.md](validating-connectors-without-an-erp.md) |
| Set up Dynamics / Dataverse (free, ~20 min) | [dynamics-dataverse-setup.md](dynamics-dataverse-setup.md) |
| Run a spec-driven mock of a vendor API | [../../tools/erp-mocks/README.md](../../tools/erp-mocks/README.md) |
| **Wire a vendor's webhooks in** (what each vendor sends, and how to verify it) | [webhooks-vendor-setup.md](webhooks-vendor-setup.md) |
| Copy the env var names | [`backend/.env.erp.example`](../../backend/.env.erp.example) |

---

## Day one: run the tests you already can

```bash
cd backend
venv/bin/python -m pytest tests/test_erp_*.py -q
```

~300 tests, no credentials, no network, no Docker. That covers request shape, auth
construction, pagination arithmetic, response envelopes, query escaping, webhook
signatures, and the guards below.

Everything requiring a live system skips with a reason telling you exactly what to
set. `-rs` prints those reasons:

```bash
venv/bin/python -m pytest tests/test_erp_*.py -q -rs
```

---

## The five tiers, and what each costs you

| Tier | What it proves | Cost | Status |
|---|---|---|---|
| **0 — static** | every connector imports; the factory resolves | free | ✅ |
| **1 — request shape** | the exact request we build | free | ✅ |
| **2 — spec-driven mocks** | the vendor's own spec rejects malformed requests | free (needs an account for the spec) | ✅ SAP, Dynamics |
| **3 — real ERP locally** | a real server gets a vote | free (Docker) | ✅ Odoo |
| **4 — vendor sandbox** | the actual vendor answers | free | ✅ SAP, Dynamics · ⬜ Intuit |

Every tier we have stood up **found a defect on its first run**. That is the argument
for using them rather than waiting for tenant access.

---

## Tier 3 — Odoo, the one you can run right now

Fully self-hosted, no account, no credentials:

```bash
docker compose -f docker-compose.erp-sandbox.yml up -d
cd backend && venv/bin/python scripts/setup_odoo_sandbox.py     # idempotent
RUN_ODOO_INTEGRATION=1 venv/bin/python -m pytest tests/test_erp_odoo_integration.py -q
```

12 tests against a real Odoo 17 with demo data. Separate compose file, so it never
starts with the normal stack. Port 8169 to avoid colliding with anything.

This is the highest-value thing a new dev can run, because it exercises the *shared*
machinery — token lifecycle, retry, circuit breaker, rate limiting, error handling —
against a real server rather than a mock we wrote.

---

## Tier 4 — the live vendors

Each needs credentials that are **personal or tenant-scoped**, so they are not in the
repo and never will be. Get your own (all free) or ask for the team values.

### SAP — free API key, instant

<https://api.sap.com> → sign in → profile → **API Key** → Show/Copy.

```bash
export SAP_SANDBOX_API_KEY='...'
venv/bin/python -m pytest tests/test_erp_sap_sandbox.py -q
```

Validates the `$batch` multipart parser against genuine SAP bytes — the one thing our
own fixture cannot do, since the fixture encodes the same assumptions as the code.

### Dynamics — free Developer Plan, ~20 minutes

Follow [dynamics-dataverse-setup.md](dynamics-dataverse-setup.md), then:

```bash
export DATAVERSE_ORG DATAVERSE_TENANT_ID DATAVERSE_CLIENT_ID DATAVERSE_CLIENT_SECRET
venv/bin/python scripts/dynamics_verify.py     # diagnoses setup BEFORE the tests
venv/bin/python -m pytest tests/test_erp_dynamics_sandbox.py -q
```

**Run `dynamics_verify.py` first.** Dataverse's own failure message for the most common
setup mistake is `403 0x80072560 "The user is not a member of the organization."`,
which says nothing about the actual cause. The script names it.

### Intuit — free sandbox, but needs a one-time human consent

QuickBooks advertises no client-credentials grant, so a client id and secret cannot
mint a token. Someone must approve access to a company once:

```bash
export INTUIT_CLIENT_ID INTUIT_CLIENT_SECRET
venv/bin/python scripts/intuit_authorize.py    # prints refresh_token + realm_id
```

Register `http://localhost:8399/callback` as a redirect URI on the app first, or it
fails after sign-in. That cannot be pre-flighted — Intuit returns byte-identical
sign-in pages for registered and unregistered URIs.

---

## Where credentials live

**Not in the repo.** No exceptions — several are tenant-scoped and one rotates itself.

- **Locally**: `backend/.env.erp` (gitignored). Copy `.env.erp.example` and fill in
  only what you need.
- **CI**: repository secrets. The `erp-sap-sandbox`, `erp-intuit-sandbox` and
  `erp-odoo-integration` jobs are no-ops when their secrets are absent, so a fork or a
  contributor without them gets a green build rather than a red one.
- **Sharing**: your team password manager, never Slack or a PR comment.

**Intuit refresh tokens rotate.** Intuit issues a new one on every refresh and retires
the previous one, so a shared static value goes stale the moment anyone uses it. If
two people run the Intuit harness against the same company, the second gets
`invalid_grant`. Use separate sandbox companies, or accept that the token needs
re-issuing.

---

## Inbound webhooks — check your config before the vendor sends anything

```
GET /api/v1/erp/integrations/{id}/webhook-config
```

Reports the endpoint path, the header the credential must arrive in, the scheme, and
whether a secret is set. Never the secret. It exists because the webhook route answers
a deliberately uninformative 401 — telling an unauthenticated caller *why* it failed
would let them probe your configuration — which leaves an operator with nothing to
debug.

**Vendors do not agree on any of this.** `X-Webhook-Signature` was a header *we*
invented; no vendor sends it. Intuit sends base64 HMAC in `intuit-signature`; Dataverse
sends a static header and has no HMAC option at all. Header and scheme are therefore
per-integration configuration with per-vendor defaults, so wiring up Intuit needs only
the verifier token. Full matrix in
[webhooks-vendor-setup.md](webhooks-vendor-setup.md).

**Sign the bytes you send.** The verifier used to hash a key-sorted re-serialisation of
the parsed payload, which no vendor produces — so every genuine webhook was rejected,
and the tests passed because they signed the same wrong way. If you write a sender,
serialise once and sign those exact bytes.

Upgrading a deployment with an old-scheme sender: `ERP_WEBHOOK_ACCEPT_LEGACY_SIGNATURE=true`
accepts the legacy form during a transition, logging loudly every time. It weakens the
binding between signature and body, so it should not live long.

---

## The guards — read these before changing a connector

These encode defects that already happened. Each is mutation-tested: reverting the fix
fails the test.

| Guard | Stops |
|---|---|
| `test_erp_connectors.py` | a connector that cannot be imported, or a factory target that does not resolve. Derived from the registry, so a new connector gets coverage automatically |
| `test_erp_no_invented_endpoints.py` | claiming success for work not done; inventing vendor endpoints; a `health_check` that skips the three-state probe |
| `test_erp_retry_classification.py` | retrying a permanently-dead credential |
| `test_erp_base_url_normalization.py` | a trailing slash on `base_url` silently breaking every request |
| `test_erp_shared_machinery.py` | token stampedes; a rate limiter that only works for sequential callers |
| `test_erp_response_schema.py` | a response model stricter than its columns, which 500s on a valid row |
| `test_erp_sync_correlation.py` | routing one vendor's records through another vendor's field mapping |
| `test_erp_webhook_auth.py` | a webhook scheme no vendor can satisfy; failing open on a missing secret |
| `test_reporting_honesty.py` | logging `..._persisted` from a function that writes nothing |
| `test_api_response_schema_matches_columns.py` | the same defect anywhere else in the API — the ERP models were the only offenders, and this proves the other routers clean rather than untested |
| `test_correlation_reporting_honesty.py` | a heuristic presented as a model inference |

Real-system suites (skipped without credentials):

| Suite | Proves |
|---|---|
| `test_erp_odoo_integration.py` | the shared machinery against a real Odoo 17 |
| `test_erp_sap_sandbox.py` | `$batch` parsing against genuine SAP bytes |
| `test_erp_dynamics_sandbox.py` | `@odata.nextLink` paging and three-state health against live Dataverse |
| `test_erp_intuit_sandbox.py` | refresh-token rotation — only Intuit decides when |
| `test_erp_sync_e2e_realdb.py` | live vendor → real sync → RLS-protected rows, read back as a second tenant |
| `test_erp_platform_integration_realdb.py` | the operator-facing HTTP surface, both tenants |
| `test_erp_webhook_secret_uniqueness_realdb.py` | two tenants cannot share a webhook secret |

### Three rules that come from real incidents

**Never invent an endpoint.** All seven original connectors POSTed to a
`/webhooks`-shaped URL with byte-identical payloads across seven unrelated vendors.
Against a real Odoo it returned `True` for a subscription that was never created —
`/xmlrpc/2/<anything>` matches, and Odoo answers HTTP 200 with a fault in the *body*.
If you cannot verify a vendor's mechanism, declare it in
`EVENT_SUBSCRIPTION_MECHANISM` and return `False`.

**A full page must be distinguishable from the whole set — and someone has to see it.**
The hub's list endpoints returned exactly `limit` rows and nothing else, and the UI passed
no limit, so a tenant with 5,000 entities would have been shown the first 200 as
everything. The Entities/Events/AI tabs now render those endpoints and a truncated result
says "showing the most recent N of more than N" instead of a confident partial answer.

Those endpoints also clamped silently (`min(limit, 1000)` with no declared bound), so asking for 5,000
returned 1,000 with nothing saying the request had been changed. Now the bound is on the
query parameter (an over-limit request gets 422 rather than a quiet substitution) and
`X-Result-Truncated` reports whether more exists — detected by fetching `limit + 1`, not
a COUNT. The API client returns `ListResult<T>` rather than a bare array so the flag
cannot be dropped by accident.

**Never report zero rows for a response you did not understand.** A missing envelope
must raise, not return `[]`. An empty result and a misunderstood response look
identical to a caller, and one of them is a silent data-loss bug. Related: **follow
pagination to completion** — every connector that skipped this truncated silently, and
it is the most repeated defect in the subsystem.

**A response model must never be stricter than its columns.** A required field over a
nullable column means a valid row cannot be serialised, and the 500 names a validation
error in our schema rather than the data — so nobody looks at the row. It cost four
endpoints at once, because create, list, get and update all built the same model.

---

## Adding a connector

1. `ERPType` in `erp_connector_base.py`, and the `_REGISTRY` in
   `erp_connector_factory.py`. Tier 0 coverage is then automatic.
2. Put pure logic — signing, query building, escaping, envelope parsing — in its own
   module (`intuit_qbo.py`, `netsuite_auth.py`, `sap_batch.py`) so it is testable by
   known-input/known-output rather than against a mock that shares its assumptions.
3. Follow pagination to completion. **Every** connector that skipped this truncated
   silently, and it is the single most repeated defect in this subsystem.
4. Set `HEALTH_PROBE_ENTITY` to something present in *every* tenant — not a business
   table. A least-privilege service account cannot read invoices, and probing one
   reports a permissions gap as an outage.
5. Set `EVENT_SUBSCRIPTION_MECHANISM` describing how events really work.
6. Run the guards.
