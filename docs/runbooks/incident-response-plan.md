# Incident response plan

**Status: draft. Sections marked 🔲 need a named human before this is operational.**

This is the *plan* — who decides, who is told, and by when. It is deliberately separate from
the runbooks, which are recovery procedures for specific failures. The repository had the
second and not the first, and OG-IR-001 records the difference: a folder of runbooks tells you
how to restart a worker, not who declares an incident, who talks to the customer, or what the
72-hour regulatory clock is attached to.

Closes the documentation half of OG-IR-001 / 800-171 03.06.01. The half it does **not** close
is FS-929: none of this has been exercised.

---

## 1. Severity

Severity is set by **customer impact**, not by which component broke. A failed database is
SEV-1 if customers cannot use the product and SEV-3 if a standby took over and nobody noticed.

| | Definition | Examples | Declare within |
|---|---|---|---|
| **SEV-1** | Product unavailable, or data lost/exposed | `ProbeSignalMissing` + `BackendAPIDown`; a restore needed; any confirmed cross-tenant read | 5 min |
| **SEV-2** | Major function unavailable or degraded for many customers | Ingestion stopped (`IngestionDataLost`); alarms not evaluating; auth failing for a tenant | 15 min |
| **SEV-3** | Degraded, with a workaround; single tenant or single feature | One ERP connector failing; export delivery backing up | 1 h |
| **SEV-4** | No customer impact; fix during business hours | An inert alert; a filling volume with weeks of headroom | next working day |

**When in doubt, declare higher.** Downgrading costs a Slack message. Upgrading late costs the
notification deadlines in §4.

### Data loss and exposure are always SEV-1

Regardless of how few rows or how briefly. They carry statutory clocks (§4) that start at
*discovery*, not at confirmation, and the clock does not pause while you decide whether it
"really counts".

## 2. Roles

One person may hold several roles on a small incident; **IC and Comms should not be the same
person on a SEV-1**, because the two jobs interrupt each other at exactly the wrong moments.

| Role | Owns | Does not own |
|---|---|---|
| **Incident Commander** | The decision log, severity, who is doing what, when to declare resolved | Fixing it |
| **Operations** | Diagnosis and remediation | Talking to anyone outside the channel |
| **Comms** | Customer and internal updates on the §4 cadence, the status page | Technical decisions |
| **Scribe** | Timeline: what was observed, what was tried, what changed, with timestamps | Anything else |

**Declaration authority: anyone.** Any engineer may declare an incident at any severity. Only
the IC may downgrade or resolve one. A culture where declaring needs permission produces
incidents that are declared late, which is the failure this line exists to prevent.

🔲 **Standing IC rota** — see §7.

## 3. The first fifteen minutes

1. **Declare.** Post in `#incident-response`: severity, one sentence of symptom, and that you
   are IC until relieved.
2. **Check the instrument before the system.** If `ProbeSignalMissing` or
   `BackendMetricsMissing` is firing, *no availability figure from that period is valid* —
   monitoring is blind, which is a distinct state from the system being healthy. Establish
   what you can actually see before concluding anything.
3. **Open the matching runbook** from [README.md](README.md).
4. **Stop the bleeding before finding the cause.** Roll back, scale down the writer, fail over.
   Root cause is a post-incident activity.
5. **Start the timeline.** Every command that changes state, with a timestamp.

## 4. Notification

Internal notification is immediate and continuous in `#incident-response`. Customer
notification is on this cadence, and it is a commitment:

| Severity | Customer notified within | Updates until resolved |
|---|---|---|
| SEV-1 | 30 min | hourly |
| SEV-2 | 2 h | every 4 h |
| SEV-3 | next business day | at resolution |

### Statutory clocks, which are shorter than any of the above

These start at **discovery**, run in wall-clock hours including weekends, and are not
negotiable:

| Trigger | Deadline | To whom |
|---|---|---|
| Personal data breach | **72 hours** | The relevant supervisory authority (GDPR Art. 33) |
| Cyber incident on a covered contract | **72 hours** | DoD, via DIBNet (DFARS 252.204-7012) |

🔲 **Neither has a named owner or a filing account.** Establishing that is the single most
overdue item on this page: the deadline is useless if, on the day, nobody knows who logs in
where. Tracked as OG-IR-002.

## 5. Evidence

Before restarting anything on a SEV-1, capture what the restart will destroy:

```bash
kubectl logs <pod> -n omniusgrid --previous > incident-<id>-<pod>.log
kubectl describe pod <pod> -n omniusgrid > incident-<id>-<pod>.describe
```

Traces are retained for **7 days** (Jaeger on a PVC — before FS-792 they did not survive a
restart at all). Pod logs reach Loki, which is deployed in-cluster as of FS-789; before that,
"check the container logs" was not an executable instruction in production.

For suspected exposure, also capture the audit chain for the window and **do not delete
anything** — see [storage-exhaustion.md](storage-exhaustion.md) for why deleting audit rows
breaks the tamper-evidence.

## 6. Resolution and afterwards

Resolved means: customer impact ended, the alert cleared on its own rather than being silenced,
and the [RTO/RPO checklist](rto-rpo-checklist.md) is complete.

A **blameless review within 5 working days** for every SEV-1 and SEV-2. It produces:

- a timeline, from the scribe's log;
- what the monitoring saw, and what it missed — the second question is the more valuable one,
  and this sprint found nine alerts that could never fire, so it is not rhetorical;
- action items with owners and dates, which go into the sprint rather than a document.

Error budget: a SEV-1 or SEV-2 consumes it. When
`job:slo_error_budget_remaining:ratio28d` drops below 0.25, hold risky deploys —
`SLOErrorBudgetLow` fires at exactly that point.

## 7. What is not real yet

Stated plainly, because an untested plan that reads as operational is worse than an obvious
draft.

| Gap | Consequence | Tracked |
|---|---|---|
| 🔲 No named on-call rotation | "Who is IC at 3am" has no answer; PagerDuty has a destination and no rota | FS-830 |
| 🔲 `[PHONE]` / `[EMAIL]` placeholders in the runbook index | The escalation path is unfollowable | FS-830 |
| 🔲 No owner for the 72-hour statutory filings | The deadline is documented and unassignable | OG-IR-002 |
| 🔲 Never exercised | No measured time-to-detect; no tabletop | FS-929, OG-IR-003 |
| 🔲 No status page | Customers learn from us by email, one at a time | FS-832 |

The technical detection this plan assumes — that an outage is *noticed* — became true on
2026-08-20 and not before. Until then the availability SLI could not record a total outage and
both burn-rate alerts stayed silent through one.
