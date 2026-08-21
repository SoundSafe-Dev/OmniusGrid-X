# Runbook: certificate expiry

Covers `IngressCertificateExpiringSoon`, `IngressCertificateExpiringCritical`,
`EdgeAgentCertExpiringSoon` and `EdgeAgentCertExpiryApproaching`.

## The two are not the same incident

They share a word and nothing else. Read the alert name before anything else.

| | **Ingress certificate** | **Edge agent certificate** |
|---|---|---|
| Issued by | cert-manager, Let's Encrypt (`letsencrypt-prod`) | the platform's own CA (`services/edge_ca.py`) |
| Blast radius | **every customer at once** — the product is unreachable | one device stops delivering; it buffers |
| Renewal | automatic, ~30 days before expiry | agent-initiated, over the link that may be down |
| If it lapses | total outage | DDIL, which the system is built for |
| Alert | `IngressCertificate*` | `EdgeAgentCert*` |

An expired ingress certificate is a SEV-1 in the terms of
[incident-response-plan.md](incident-response-plan.md). An expired edge certificate on one
device is a SEV-3 and can wait for business hours — the agent buffers and the conservation
law holds. **A thousand of them expiring the same week is a SEV-1 again**, because they were
all enrolled together and will all fail together.

---

## Ingress certificate

### Detection

`IngressCertificateExpiringSoon` fires at 14 days, `…Critical` at 3. Both read
`probe_ssl_earliest_cert_expiry` from the blackbox exporter — which means they see what a
*customer's* TLS handshake sees, not what the cluster believes it has issued. That distinction
matters: cert-manager can hold a perfectly valid renewed Secret while the ingress controller
still serves the old one.

```bash
kubectl get certificate -n omniusgrid
kubectl describe certificate backend-tls -n omniusgrid   # Status.conditions carries the reason
kubectl get certificaterequest,order,challenge -n omniusgrid
```

And what the outside world actually gets, which is the number the alert is computed from:

```bash
echo | openssl s_client -connect api.omniusgrid.local:443 -servername api.omniusgrid.local 2>/dev/null \
  | openssl x509 -noout -dates -subject -issuer
```

### Why an automatic renewal fails

Nearly always one of four, in rough order of likelihood:

1. **The HTTP-01 challenge cannot reach the pod.** `default-deny-all` applies to the
   namespace, so the ingress controller needs a path to the solver pod cert-manager creates.
   Check `kubectl get challenge -n omniusgrid` — a challenge stuck `pending` with a connection
   error is this.
2. **DNS moved.** The record no longer points at this ingress, so Let's Encrypt validates
   somebody else's endpoint or nothing.
3. **Rate limit.** Let's Encrypt allows 5 duplicate certificates per week. A crash-looping
   cert-manager burns that quota fast, and then renewal fails for days with a valid config.
   `kubectl logs -n cert-manager deploy/cert-manager | grep -i "rate limit"`.
4. **The issuer is unhealthy.** `kubectl describe clusterissuer letsencrypt-prod`.

### Recovery

Force a renewal:

```bash
kubectl cert-manager renew backend-tls -n omniusgrid      # if the plugin is installed
# otherwise: delete the Secret and let the Certificate reconcile
kubectl delete secret backend-tls -n omniusgrid
```

**If expiry is hours away and renewal is blocked**, do not keep retrying into a rate limit.
Issue from the staging issuer to confirm the challenge path works, fix that, then switch back
— a certificate that browsers reject is no better than an expired one, but it tells you
whether the problem is ACME or your networking, which is what you actually need to know.

### Verification

```bash
echo | openssl s_client -connect api.omniusgrid.local:443 -servername api.omniusgrid.local 2>/dev/null \
  | openssl x509 -noout -dates
```

The alert clears on its own within a scrape interval. **Do not silence it to close the
incident** — `probe_ssl_earliest_cert_expiry` is what an actual client sees, so if it still
reads the old expiry, customers are still getting the old certificate.

---

## Edge agent certificates

### Detection

`EdgeAgentCertExpiringSoon` at 48 hours, `EdgeAgentCertExpiryApproaching` at 14 days, both
labelled by `agent_id`. The gauge comes from the heartbeat, so **an agent that has already
stopped connecting reports nothing at all** — silence here is not health. Cross-check against
`EdgeAgentOffline` and the fleet page.

```promql
# How many, and when — the shape matters more than the count
min by (agent_id) (edge_agent_cert_expiry_seconds) < 14 * 24 * 3600
```

### The shape is the whole diagnosis

Certificates issued during a single enrolment campaign expire together. **Before touching
anything, plot the expiry distribution.** A handful spread over weeks is routine maintenance.
A cliff is a fleet-wide outage with a date on it, and it needs planning rather than a runbook
step — renewal happens over the uplink, and an agent whose certificate has already expired
cannot authenticate to ask for a new one.

That last point is the trap: **renewal must happen before expiry, not after.** An expired edge
certificate is not self-healing. Recovery is re-enrolment, which needs the enrolment token and,
for a device on a factory floor behind a denied link, possibly a site visit.

### Recovery

`scripts/certificate-rotation.sh` automates the mTLS rotation on a 90-day cycle. Read it
before running it: it writes to `/certs`, backs up to `/certs/backups` and logs to
`/var/log/certificate-rotation.log`, so it expects to run somewhere those paths mean
something — this is not a script to run from a laptop against production.

For agents still connecting, renewal is the normal path — the agent requests a new certificate
and the CA issues it. Confirm the CA is healthy first, because a failing CA turns "a few
expiring" into "all of them":

```bash
kubectl logs -n omniusgrid deploy/backend | grep -i "edge_ca\|certificate"
```

For agents already expired, re-enrol per
[`infrastructure/k8s/README.md`](../../infrastructure/k8s/README.md). Data is not lost while
this happens: the agent buffers to its local store-and-forward database and backfills on
reconnect, and `EdgeBufferDropping` / `EdgeAgentDroppingTelemetry` tell you if a buffer is
approaching its limit — that is the real deadline, not the certificate.

### After the incident

If the expiry distribution had a cliff, stagger the next issuance. Certificates that were
issued together will expire together for the life of the fleet unless somebody breaks the
pattern deliberately.
