# Validating ERP connectors without a connected ERP

We have seven ERP connectors and access to none of the systems. This is how to get
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

Not one of them needed a live system. That is the argument for investing in the
lower tiers before chasing tenant access.

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

## Tier 2 — Spec-driven mock servers ← **highest value next step**

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

**This is systemic, and the harness only proves it for Odoo.** Every connector's
health check probes a business-module entity: NetSuite `invoice`, SAP
`PurchaseOrder`, Oracle `invoices`, Infor `invoice`, Epicor `Erp.BO.InvoiceSvc`.
Each will misreport in exactly the same way against a tenant that has not licensed
or enabled that module. Fixing them properly needs either their specs or their
sandboxes — the six remaining are unverified.

**Also empirically confirmed** (previously coded from documentation): Odoo reports
application faults in the response BODY with **HTTP 200**. A connector treating 200
as success turns an access-rights failure into an empty result set.

**Cannot tell us:** anything vendor-specific about the other six.

---

## Tier 4 — Vendor sandboxes and trials (no production system)

| Vendor | Route | Cost |
|---|---|---|
| SAP | **Business Accelerator Hub sandbox** — live OData endpoints with test data, just an API key | Free |
| SAP | BTP trial account | Free, time-limited |
| Dynamics 365 | Developer plan / 30-day trial with a Dataverse environment | Free |
| NetSuite | Partner or developer account (`TSTDRV*`) | Requires partner registration |
| Infor / Epicor | Partner programme | Commercial |

The SAP sandbox is the standout: it answers real OData, including `$batch`, so it
would exercise the multipart parser against genuine SAP output rather than the
fixture I wrote.

**Cannot tell us:** how a *customer's* system behaves — see below.

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
3. **Register for the SAP Business Accelerator Hub sandbox** — free, and it exercises
   the `$batch` parser against genuine SAP output.
4. **Adopt cassettes now**, so that whenever a tenant appears the traffic is captured
   rather than lost.

Tiers 0, 1 and 3 (Odoo) are done. Tier 2 — spec-driven Prism mocks for the vendors
we cannot host — is the next highest-value step, because the health-check defect
Odoo exposed almost certainly exists in the other six and nothing currently proves
otherwise.
