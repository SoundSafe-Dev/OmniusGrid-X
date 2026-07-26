# Spec-driven ERP mocks (Tier 2)

Run a vendor's API as a mock **generated from the vendor's own specification**, with
request validation switched on.

```bash
./tools/erp-mocks/run-mock.sh sap 4010
```

## Why this is different from a hand-written mock

`--errors` makes Prism **reject inbound requests that do not conform to the spec**.
That is the entire value. A mock we author encodes the same assumptions as the code
it is testing, so it cannot disconfirm them — which is precisely how these
connectors accumulated a non-existent NetSuite host, a `Bearer` header where OAuth
1.0a was required, an authorization-code grant on a background job, and a company
identifier in an API-key header. Every one of those would have been rejected by a
mock built from the vendor's own contract.

Verified working: Prism 5.16.0 mounted a 372-path spec and served a validating mock.

## Specs are NOT committed — here is where each comes from

None of these can be downloaded anonymously, which is why the `specs/` directory
ships empty. Each needs an account; most are free.

| Vendor | Where | Format | Cost |
|---|---|---|---|
| **SAP S/4HANA** | api.sap.com → the API → *Download Specification* → OpenAPI 3 | JSON/YAML | Free account |
| | Or fetch `$metadata` from the sandbox with your API key (EDMX → convert) | EDMX | Free account |
| **Dynamics 365** | `GET {org}/api/data/v9.2/$metadata` from any trial or dev org | CSDL | Free dev plan |
| **NetSuite** | Account → *SuiteTalk REST Web Services* → OpenAPI 3 schema | JSON | Account required |
| **Infor ION** | ION API portal → the suite → *Download Swagger* | OpenAPI | Tenant required |
| **Epicor Kinetic** | `{env}/api/swagger/v1/swagger.json` | OpenAPI | Environment required |
| **Odoo** | Not applicable — Odoo is JSON-RPC, not REST. Use the real thing instead: `docker-compose.erp-sandbox.yml` | — | Free |

Drop the file in as `specs/<vendor>.json` (or `.yaml`) and the runner picks it up.

## A note on SAP specifically

If you have an SAP API key, **the sandbox is better than a mock**: it is a live SAP
OData service answering real `$metadata`, real entity sets and real `$batch`. A mock
of SAP is a fallback for when you do not have the key; the sandbox is the real
thing. See `backend/tests/test_erp_sap_sandbox.py`.

## What a spec-driven mock still cannot tell you

Vendors routinely diverge from their own published specs — undocumented required
headers, stricter validation than the schema states, error bodies with a different
shape. A green run here means "we conform to the documented contract", not "the
vendor will accept this". Only a sandbox or a real tenant closes that gap.
