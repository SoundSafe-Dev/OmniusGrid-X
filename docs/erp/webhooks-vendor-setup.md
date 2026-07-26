# Wiring an ERP vendor's webhooks into OmniusGrid

Inbound webhooks are how an ERP tells us something changed without waiting for the next
poll. This is what each vendor actually sends, how to configure it, and how to confirm
it before the vendor sends anything real.

```
POST /api/v1/erp/webhooks/{erp_type}
```

**Check your configuration first.** As an authenticated user of the owning tenant:

```
GET /api/v1/erp/integrations/{integration_id}/webhook-config
```

That reports the endpoint path, the header the credential must arrive in, the scheme,
and whether a secret is set — never the secret itself. It exists because the webhook
route answers a deliberately uninformative 401: telling an unauthenticated caller *why*
verification failed would let them discover whether an integration exists and how it is
configured. Correct, and useless to you while wiring up a vendor.

---

## The two schemes vendors actually use

**`hmac_sha256`** — the vendor signs the **raw request body** with a shared secret and
sends the digest in a header. Hex, base64 and `sha256=<hex>` are all accepted.

**`shared_secret`** — the vendor sends a **static value** in a header you nominate.
Dataverse works this way and offers no HMAC option at all, so pretending otherwise
would mean every Dynamics webhook failed.

Everything fails closed. **No secret configured means every webhook is rejected**, on
purpose: an integration without a secret would otherwise accept unauthenticated writes
into a tenant's business data, and this route is exempt from the platform's
authentication walk precisely because it is supposed to be protected here.

---

## Configuration

On `integration.configuration`:

| Key | Meaning | Default |
|---|---|---|
| `webhook_secret` | shared secret / verifier token | **required** |
| `webhook_auth_mode` | `hmac_sha256` or `shared_secret` | per vendor |
| `webhook_signature_header` | header carrying the credential | per vendor |
| `webhook_signature_encoding` | `auto`, `hex`, `base64` | `auto` |

The defaults mean a vendor's out-of-the-box wiring works with only `webhook_secret`
supplied.

| Vendor | Mode | Header | Encoding | Verified? |
|---|---|---|---|---|
| **Intuit QuickBooks** | `hmac_sha256` | `intuit-signature` | base64 | **Yes** — vendor docs |
| **Dynamics / Dataverse** | `shared_secret` | `x-omniusgrid-webhook-token` | — | Documented mechanism |
| **NetSuite** | `hmac_sha256` | `x-webhook-signature` | auto | Operator-defined at the sender |
| **SAP / Oracle / Infor / Epicor** | `hmac_sha256` | `x-webhook-signature` | auto | Operator-defined at the sender |
| **Odoo** | `shared_secret` | `x-omniusgrid-webhook-token` | — | Odoo sends no signature header |

---

## Per vendor

### Intuit QuickBooks — the one fully verified path

Developer portal → your app → **Webhooks**: set the endpoint URL, pick the entities,
and copy the **verifier token**. Put that token in `webhook_secret`; everything else
defaults correctly.

Intuit sends base64 HMAC-SHA256 of the raw body in `intuit-signature`. The Intuit
*connector* implements the same check for outbound-verification parity, so the two
cannot drift.

### Dynamics 365 / Dataverse

Dataverse has **no `webhooks` entity set** and no HMAC option. Register a
`serviceendpoint` record with `contract=Webhook` (normally via the Plug-in Registration
Tool), then add an `sdkmessageprocessingstep` for the messages you care about. The
authentication choice there is an **HTTP header** whose name and value you set, or a
query-string key.

Use the header form. Set the same value as `webhook_secret` here, and set the header
name on both sides (`x-omniusgrid-webhook-token` by default).

### NetSuite

No outbound-webhook REST API exists. A SuiteScript user-event or scheduled script calls
out with `N/https`, so **you** control the header and the signature. Compute
HMAC-SHA256 over the exact request body and send it in `x-webhook-signature`.

### SAP, Oracle, Infor, Epicor

Each is configured on the vendor side (Event Mesh subscription, ION Desk, the Kinetic
environment). None was verifiable without a tenant, so these default to the generic
HMAC scheme and are marked unverified in the connector's
`EVENT_SUBSCRIPTION_MECHANISM`. Until one is confirmed, polling via the sync path is
the supported route.

### Odoo

Odoo's `base.automation` outgoing webhook sends **no signature header** — its secret
lives in the URL. If you can front it with a proxy that adds a header, use
`shared_secret`. Otherwise poll: Odoo is the one connector fully validated against a
real server, and its polling path is well covered.

---

## Signing correctly — the mistake that cost us

**Sign the bytes you send.** Not a re-serialisation of the parsed payload.

The verifier previously hashed `json.dumps(event_data, sort_keys=True)` — the parsed
body, re-serialised with sorted keys. No vendor produces that: they all sign the exact
bytes on the wire, and key order, whitespace, unicode escaping and float formatting all
differ. **Every genuine vendor webhook was rejected with 401**, and the tests passed
because they generated the signature the same wrong way — a fixture encoding the same
assumption as the code. One even asserted the property that made it broken:

```python
def test_signature_order_independent():
    assert compute_signature(secret, a) == compute_signature(secret, b)
```

Order independence reads like robustness. It is exactly what stops a signature binding
the request that was actually sent.

If you write a sender, serialise **once**:

```python
body = json.dumps(event).encode()
sig  = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
requests.post(url, data=body, headers={"X-Webhook-Signature": sig,
                                       "Content-Type": "application/json"})
```

Not `json=event` with a separately-computed signature — the HTTP client's serialisation
will differ from yours.

---

## Upgrading an existing deployment

The signature scheme changed from canonical-JSON to raw-body. **Any sender still using
the old scheme will get 401.** In this repository the only such sender was
`backend/scripts/smoke_e2e.py`, now fixed.

If a deployment has other senders, there is a transition switch:

```
ERP_WEBHOOK_ACCEPT_LEGACY_SIGNATURE=true
```

Off by default. While set, the legacy canonical-JSON signature is *also* accepted, and
**every** such acceptance logs a warning naming the integration. Read per request, so it
can be turned off without a restart.

It is not a security equivalent and should not live long: because it hashes a canonical
form, a body with reordered keys or different whitespace verifies against the same
signature — the signature stops binding the bytes received. Fix your senders and unset
it.

---

## Which tenant a webhook belongs to

The path carries only `erp_type`, so with several tenants running SAP there is nothing
in the request naming the organisation.

**The signature selects the tenant**: each active integration for that `erp_type` is
tried, and the one whose secret verifies these exact bytes wins. That is the same
evidence the signature already provides, so it grants nothing extra.

This previously took `.first()` across **all organisations** and verified against that
one integration's secret — so only whichever row the database happened to return first
could ever authenticate, and every other tenant's genuine events were rejected as
forged.

Practical consequence: **give each integration a distinct `webhook_secret`.** Shared
secrets across tenants make attribution ambiguous.

---

## Confirming it works

1. `GET /api/v1/erp/integrations/{id}/webhook-config` → `ready: true`
2. Send yourself a signed request:

```bash
BODY='{"event_id":"test-1","event_type":"po.created","entity_type":"PurchaseOrder"}'
SIG=$(printf '%s' "$BODY" | openssl dgst -sha256 -hmac "$WEBHOOK_SECRET" -hex | sed 's/^.*= //')
curl -sS -X POST "$BASE/api/v1/erp/webhooks/sap" \
  -H "Content-Type: application/json" -H "X-Webhook-Signature: $SIG" --data "$BODY"
```

Expect `{"status":"accepted"}`. Send it twice — the second returns
`{"status":"duplicate"}`, deduplicated on `(source_system, event_id)` by a unique
constraint rather than a check-then-insert, because providers retry aggressively and two
concurrent deliveries would both pass a pre-check.

3. Confirm it landed: `GET /api/v1/erp/integrations/{id}/events`

A 401 means the signature did not verify. Compare against `webhook-config`: the usual
causes are no `webhook_secret`, the credential in the wrong header, or a sender that
signed something other than the bytes it transmitted.
