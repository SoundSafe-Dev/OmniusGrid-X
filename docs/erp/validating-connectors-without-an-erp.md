# Validating ERP connectors without a connected ERP

We have eight ERP connectors and, at the outset, access to none of the systems. This is how to get
real confidence anyway, ordered by value-per-effort, with an honest note on what
each tier cannot tell us.

The framing matters: every defect found while building these connectors was a
**request-construction** defect, not a business-logic one.

| Defect | Would a live ERP have been needed to catch it? |
|---|---|
| NetSuite host `suitetalk.net` does not exist | No |
| `Bearer` sent where OAuth 1.0a TBA required | No |
| SAP/Oracle using the authorization-code grant | No |
| Epicor sending `company_id` in `X-API-Key` | No |
| Pagination ignored, results silently truncated | No |
| `$batch` parser reading HTTP headers as the body | No |
| Odoo doing REST against an RPC endpoint | No |
| SAP/Oracle/Dynamics not importable at all | No |
| A trailing slash on `base_url` breaking every request | No |
| Permanent auth failures retried 4x with backoff | No |
| `subscribe_to_events` reporting success for nothing | **Odoo proved it; no** |
| Intuit having no client-credentials grant at all | No |

Not one of them *required* a live system to be catchable. One of them —
`subscribe_to_events` returning `True` for a subscription that was never created —
was nonetheless only *actually found* by pointing the code at a real Odoo, because
nothing in the hermetic suite exercised that path at all. Both halves of that matter:
build the cheap tiers, and then still get a real server to vote.

---

## Tier 0 — Static guarantees (done)

`tests/test_erp_connectors.py` asserts every connector is importable, that the
factory's targets resolve, and that no connector imports a blocking HTTP/OAuth
library. Cheap, and it caught the single worst defect: three integrations that
could not be constructed.

**Cannot tell us:** anything about correctness of the requests themselves.

---

## Tier 1 — Request-shape assertions (done)

41 tests assert the exact request each connector builds: URL, method, auth scheme,
signature base string, query parameters, pagination arithmetic, and response
envelope handling. Signing is tested as a pure function with fixed
timestamp/nonce, so a signature is verified by known-input/known-output rather
than "it returned a string".

**Cannot tell us:** whether the vendor *accepts* what we send. We are asserting
against our reading of the documentation.

---

## Tier 2 — Spec-driven mock servers (**DONE for SAP** — and it found a defect)

Run a mock server generated **from the vendor's own API specification**, and point
the connector at it. The important property is that a good spec-driven mock
validates *inbound* requests too: it rejects a request that does not match the
spec, which is precisely the class of bug we keep finding.

**[Prism](https://github.com/stoplightio/prism)** is the strongest fit:

```bash
prism mock --errors netsuite-rest-openapi.yaml   # --errors = reject invalid requests
```

Where the specs come from — none of these need a tenant:

| Vendor | Machine-readable spec | Availability |
|---|---|---|
| SAP S/4HANA | OData `$metadata` (EDMX/CSDL) + OpenAPI | **Public** on SAP Business Accelerator Hub |
| Dynamics 365 / Dataverse | OData CSDL `$metadata` | Public documentation; CSDL from any trial org |
| NetSuite | OpenAPI 3.0 for the REST Record Service | Downloadable from an account; schema is documented |
| Odoo | Runtime introspection (`fields_get`) | From a local instance — see Tier 3 |
| Infor ION | OpenAPI per ION API suite | Via ION API portal |
| Epicor Kinetic | OpenAPI/Swagger per environment | Via an environment's `/api/swagger` |

We already have **schemathesis** as a dependency (it drives `test_api_contract.py`).
The same tool can drive a vendor spec against a mock, so this needs no new stack.

### Built and proven for SAP

`tools/erp-mocks/fetch-spec.sh` pulls each vendor's spec **from the vendor's own
system**. It is a script rather than a doc because every vendor needs a DIFFERENT
`Accept` header, and getting it wrong returns 406 or HTML instead of a spec:

| Vendor | Metadata endpoint | Required `Accept` |
|---|---|---|
| SAP S/4HANA | `{service}/$metadata` | `application/xml` (**JSON returns 406**) |
| NetSuite | `/services/rest/record/v1/metadata-catalog` | `application/swagger+json` |
| Dataverse | `/api/data/v9.2/$metadata` (CSDL) | `application/xml` |
| Dataverse | `/api/data/v9.2/EntityDefinitions` (JSON) | `application/json` + `OData-MaxVersion: 4.0` + `OData-Version: 4.0` |
| Epicor | `/api/swagger/v1/swagger.json` | `application/json` |

The SAP path is **verified end to end**: 168KB of real EDMX → OpenAPI 3 via
`odata-openapi3` (29 paths, 28 schemas) → Prism with `--errors`. It also needs
`--compressed`: SAP gzips `$metadata` whether or not you ask, and `curl` only inflates
when told to, so without it you get gzip in a file named `.xml` and every converter
rejects it with an error mentioning nothing about compression.

**It found a defect on its first run, as every tier has.** Pointed at the mock, the
SAP connector's request arrived as `//A_PurchaseOrder` and matched no route. Cause: a
trailing slash on `base_url` — one of the most common ways a human writes a URL. Five
connectors build endpoints by concatenating `f"{base_url}/api/v1"`, yarl preserves the
empty segment, and the server answers 404 in a way that reads as a wrong entity or an
unactivated service rather than a stray character in configuration. Normalized once in
`ERPConfig.__post_init__`; 34 tests, mutation-verified.

Specs are gitignored — vendor material, large, and a per-tenant spec embeds that
tenant's custom fields.

**Cannot tell us:** whether the vendor's real behaviour matches its own spec. It
frequently does not — undocumented required headers, stricter validation, error
bodies that differ from the schema.

---

## Tier 3 — Run a real ERP locally (**DONE** — and it found a defect immediately)

**Odoo is self-hostable and free.** This is the one connector we can validate
end-to-end today, at zero cost, in CI:

```yaml
services:
  odoo:
    image: odoo:17
    depends_on: [odoo-db]
    ports: ["8069:8069"]
  odoo-db:
    image: postgres:15
    environment:
      POSTGRES_USER: odoo
      POSTGRES_PASSWORD: odoo
      POSTGRES_DB: postgres
```

That gives a genuine Odoo with a real database, real JSON-RPC, real authentication,
real access-rights errors and real pagination. It validates the whole path:
`common.authenticate` → `execute_kw` → domain translation → paging → error handling.

Doing this for Odoo also de-risks the others, because it proves the *shared*
machinery — token lifecycle, retry, circuit breaker, rate limiting — against a real
server rather than a mock we wrote.

### It is built, and it earned its keep on the first run

- `docker-compose.erp-sandbox.yml` — Odoo 17 + Postgres
- `backend/scripts/setup_odoo_sandbox.py` — waits, then creates a database **with
  demo data** (an empty Odoo would let every fetch test pass by returning nothing,
  which is the exact silent-empty-result failure these tests exist to catch)
- `backend/tests/test_erp_odoo_integration.py` — 10 tests, all passing against a
  real Odoo 17
- CI job `erp-odoo-integration`

**The defect it found:** `health_check` probed `sale.order`, which only exists when
the Sales module is installed. A customer running Odoo without Sales — an entirely
normal configuration — had a working integration reported permanently unhealthy,
because "that module is not installed" and "the connection is broken" produced the
same answer. It now probes authentication plus `res.users`, which exists in every
Odoo database.

**This was systemic, and the fix was claimed for all seven — which was wrong.**
Six connectors adopted `probe_health`; **Dynamics did not**, and kept the two-state
version that mapped any exception to `unhealthy`. The claim went unchecked for a
commit because nothing asserted it. `test_erp_no_invented_endpoints.py` now asserts
that every registered connector's `health_check` uses the shared probe, so the claim
is checkable rather than asserted in prose. Dynamics is fixed and covered. Rather than guess at every vendor's universally-present entity,
`ERPConnectorBase.probe_health` reports WHICH failure occurred:

| State | Meaning | Should it page? |
|---|---|---|
| `unhealthy` | cannot reach the system, or the credential is rejected | **yes** |
| `degraded` | authenticated fine; the probe entity was unavailable — often a module that is not installed | no |
| `healthy` | authenticated and the entity answered | no |

All four paths are verified empirically against the real Odoo (healthy, degraded on
a missing module, unhealthy on a bad credential, unhealthy on an unreachable host).
The other six inherit the same logic; their probe *entities* remain unverified,
but a tenant lacking that module now reports `degraded` instead of an outage.

**That fix's own first version was wrong, and the harness caught it.** The probe
initially trusted `get_auth_token()` to prove the credential. For static-credential
connectors — Odoo and Epicor accept a long-lived API key — `authenticate()` just
returns the value out of config without contacting anything, so a deliberately
wrong key "authenticated" and was reported `degraded`. Connectors now override
`verify_credentials()` with something that round-trips, plus an auth-error
classifier as a backstop. A mock could not have surfaced that.

**Also empirically confirmed** (previously coded from documentation): Odoo reports
application faults in the response BODY with **HTTP 200**. A connector treating 200
as success turns an access-rights failure into an empty result set.

### The same Odoo container then found the worst defect in the ERP layer

All seven connectors carried the same copy-pasted `subscribe_to_events`: POST to a
`/webhooks`-shaped URL with a `{name, url, event_type}` body. The payloads were
**byte-identical across seven unrelated vendors**, so at most one could have been
right. None was.

Run against the live Odoo, it returned **`True`**. `POST /webhooks` is a 404 on Odoo.
What actually happened is worse: the connector's URL resolved to `/xmlrpc/2/webhooks`,
Odoo's `/xmlrpc/2/<...>` route matches anything, and it answered **HTTP 200 with an
XML-RPC fault body containing a traceback**. The connector checked only
`status not in (200, 201)`, saw 200, and reported success for a subscription that was
never created — the same HTTP-200-fault trap noted above, surviving in a code path
nobody had exercised.

That is the worst failure shape available: an operator enables real-time ERP events,
the platform confirms it, and no event ever arrives, with no error anywhere to look
at. Nothing consumed `subscribe_to_events` yet, so it was latent rather than shipped.

**379 lines of fiction removed.** Connectors now DECLARE the real mechanism
(`EVENT_SUBSCRIPTION_MECHANISM`) and the base class returns False honestly. Returning
False is not a regression: there was never a working subscription to lose. Three
independent guards keep it out — the return value, an assertion that no HTTP request
is attempted at all, and a source-level check that no `/webhooks`-shaped URL is
constructed.

**One remaining weakness, recorded rather than papered over.** Five connectors (SAP,
Oracle, NetSuite, Infor, Epicor) still probe a *business* table for health, so a
least-privilege service account reports `degraded` forever. The three-state probe
means this is no longer a false **outage** — nobody is paged — but a
permanently-degraded healthy integration is still wrong. Each is listed in
`KNOWN_BUSINESS_TABLE_PROBES` with the specific vendor fact that is missing, and the
list is asserted not to grow. Resolved for the three where the answer is known: Odoo
(`res.users`), Dynamics (`systemusers`), Intuit (`CompanyInfo`). Guessing the other
five would just move the false report to a different tenant.

**Cannot tell us:** anything vendor-specific about the other six.

---

## Tier 4 — Vendor sandboxes and trials (no production system)

| Vendor | Route | Cost |
|---|---|---|
| SAP | **Business Accelerator Hub sandbox** — live OData endpoints with test data, just an API key | **Free — DONE** |
| **Intuit / QuickBooks** | **Developer account → sandbox company. Client credentials VERIFIED; needs the one-time consent (`scripts/intuit_authorize.py`)** | **Free — in progress** |
| SAP | BTP trial account | Free, time-limited |
| Dynamics 365 | **Power Apps Developer Plan** — 3 Dataverse environments, no approval queue. See [dynamics-dataverse-setup.md](dynamics-dataverse-setup.md) | Free |
| NetSuite | Partner or developer account (`TSTDRV*`) | Requires partner registration |
| Infor / Epicor | Partner programme | Commercial |

### DONE for SAP — and it corrected two of my assumptions

`backend/tests/test_erp_sap_sandbox.py` runs against the live sandbox
(`https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap`). Three tests, all
green. Auth is an `apikey:` **request header** — not OAuth, not Bearer; the
sandbox's 401 body names the variable it could not resolve, which is how that was
established rather than guessed.

**The valuable one passed:** `$batch` multipart parsing against **genuine SAP
bytes** rather than the fixture I wrote for it. `sap_batch.py` encoded my own
assumptions about boundary style, line endings, Content-ID presence and HTTP-part
framing; real SAP confirms them. It also confirmed the assumption the parser most
depends on — SAP picks its **own response boundary**, different from the one we
sent, so parsing with the sent boundary would match nothing and look exactly like
an empty result.

Two things real SAP taught that the documentation did not:

- **`$metadata` returns 406 for `Accept: application/json`.** The document is EDMX;
  SAP refuses rather than negotiating. `application/xml` and `*/*` both return 200.
  No connector fetches `$metadata`, so this is a property of the probe, not a
  connector defect — but it would bite immediately if metadata discovery is added.
- **Query options are rejected on the service root.** `$top` against the service
  document returns 400, "System query options ... are not allowed in the requested
  URI". They must target an entity set.

Both were errors in my *test*, found only because a real server got a vote — which
is the entire argument for this tier.

**Cannot tell us:** the OAuth2 flow (the sandbox uses an API key where a real
S/4HANA system uses client-credentials), nor how a *customer's* system behaves —
see below.

---

## Tier 5 — Record and replay (the moment any tenant exists)

When access to any real system appears — even once, even briefly — record the
traffic and replay it in CI forever. This converts a one-off into permanent
regression coverage.

- `pytest-recording` / `vcrpy` for cassettes
- `aioresponses` for aiohttp-level replay

Record on first contact, scrub credentials, commit the cassettes. Every subsequent
change is then tested against *real vendor responses* with no ongoing access.

---

## What NONE of this catches

Worth stating plainly so the confidence is not overclaimed:

- **Per-tenant customisation.** SAP Z-fields, NetSuite custom records and custom
  segments, Dynamics custom entities. Every real deployment is modified, and the
  extraction/transform layer is where that will bite.
- **Permissions and roles.** A correct request from an under-privileged service
  account fails in ways no mock reproduces.
- **Rate limits and throttling in practice.** Documented limits and enforced limits
  differ; back-off behaviour is only really exercised under real load.
- **Data volume.** Pagination correctness is tested; behaviour at hundreds of
  thousands of rows — timeouts, memory, cursor expiry — is not.
- **Eventual consistency.** Some ERP writes are not immediately readable.

---

## Recommendation

1. ~~**Stand up Odoo in Docker and wire it into CI.**~~ **DONE** — see Tier 3. It
   found a real defect on its first run.
2. **Add Prism mocks driven by the SAP and Dynamics `$metadata`/OpenAPI specs**, with
   `--errors` on so invalid requests are rejected. Highest coverage per unit of
   effort for the vendors we cannot host.
3. ~~**Register for the SAP Business Accelerator Hub sandbox.**~~ **DONE** — see
   Tier 4. The `$batch` parser is now validated against genuine SAP output, and the
   sandbox corrected two assumptions in the probe itself.
4. **Finish the Intuit authorization.** The client credentials are **verified
   working** — the token endpoint moved from `401 invalid_client` to
   `400 invalid_grant`, which means Intuit authenticated the client and rejected only
   a deliberately-bad refresh token. What remains is the one-time consent that yields
   a refresh token and realm id: `python backend/scripts/intuit_authorize.py`.
   QuickBooks has the most to gain from a real server, because refresh-token rotation
   is its most likely production failure and only Intuit decides when to rotate.
5. **Adopt cassettes now**, so that whenever a tenant appears the traffic is captured
   rather than lost.

Tiers 0, 1, 3 (Odoo) and 4 (SAP) are done. Tier 2 — spec-driven Prism mocks for the
vendors we cannot host — is the next highest-value step, because the health-check
defect Odoo exposed almost certainly exists in the other six and nothing currently
proves otherwise.

**Scoreboard: every tier we have stood up found a defect on its first run.** Tier 0
found three unimportable connectors; Tier 1 found a non-existent NetSuite host and
four wrong auth schemes; Tier 3 found the health check that reported a missing
module as an outage; Tier 4 found two wrong assumptions in the SAP probe. That is
the return on building the lower tiers instead of waiting for tenant access.
