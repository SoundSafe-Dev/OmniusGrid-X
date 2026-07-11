# Incident Communication Templates

Copy-paste templates for communicating during an OmniusGrid incident. Fill in every
`[BRACKETED]` placeholder before sending. Keep messages factual, avoid speculation
about root cause until confirmed, and never include customer PII in public channels.

## Severity definitions (for consistent language)

Severity labels match the `severity:` values used in `infra/prometheus/alerts.yml`
(`critical`, `high`, `medium`, `low`).

| Severity | Meaning | Customer-facing? |
|----------|---------|------------------|
| Critical | Full outage / data loss risk | Yes — proactive |
| High | Major feature down, many users affected | Yes — proactive |
| Medium | Partial degradation, workaround exists | Status page only |
| Low | Minor issue, few/no users affected | Internal only |

## Cadence guideline

- **Critical/High:** update every **30 minutes** until resolved, even if "no change".
- **Medium:** update on status change.
- Always send a **resolution** message and a **post-incident summary**.

---

## 1. Incident declaration (internal — Slack `#incident-response`)

```
:rotating_light: INCIDENT DECLARED — [Critical/High/Medium]

Summary: [ONE-LINE DESCRIPTION OF IMPACT]
Component: [TimescaleDB / Redpanda / Backend / Deploy / Network / DC]
Detected: [TIME + TZ] (via [alert name / report])
Impact: [WHO/WHAT IS AFFECTED]
Runbook: [LINK TO RUNBOOK]

Incident Commander: [NAME]
Scribe: [NAME]
Channel: #incident-[SHORT-NAME]

Status: INVESTIGATING
```

## 2. Internal status update (Slack)

```
:large_yellow_circle: INCIDENT UPDATE — [HH:MM TZ]

Status: [INVESTIGATING / IDENTIFIED / MONITORING]
What we know: [CURRENT UNDERSTANDING]
Actions in progress: [WHAT THE TEAM IS DOING]
Next update: [TIME]

IC: [NAME]
```

## 3. Customer notification — initial (email / in-app)

```
Subject: [Investigating] OmniusGrid service disruption

Dear Customer,

We are currently investigating an issue affecting [AFFECTED FUNCTIONALITY] on the
OmniusGrid platform, first detected at [TIME + TZ].

Current impact: [PLAIN-LANGUAGE IMPACT].
Our engineering team is actively working on resolution.

We will provide our next update by [TIME]. We apologize for the inconvenience.

Status page: [STATUS PAGE URL]

— The OmniusGrid Team
```

## 4. Customer notification — update

```
Subject: [Update] OmniusGrid service disruption

Dear Customer,

Update as of [TIME + TZ]:

[WHAT HAS CHANGED — e.g. "We have identified the cause and are applying a fix" /
"Service is recovering and we are monitoring stability"].

Estimated time to resolution: [TIME or "under investigation"].
Next update by: [TIME].

Status page: [STATUS PAGE URL]

— The OmniusGrid Team
```

## 5. Customer notification — resolved

```
Subject: [Resolved] OmniusGrid service disruption

Dear Customer,

The issue affecting [AFFECTED FUNCTIONALITY] was resolved at [TIME + TZ]. All
services are operating normally.

Duration: [START] – [END] ([TOTAL])
What happened: [BRIEF, NON-TECHNICAL SUMMARY]
Data impact: [NONE / DESCRIPTION]

A full post-incident review will follow [if Critical/High]. Thank you for your patience.

— The OmniusGrid Team
```

## 6. Status page entries

**Investigating**
```
[Investigating] We are investigating reports of [ISSUE]. Some users may experience
[IMPACT]. Next update in 30 minutes.
```

**Identified**
```
[Identified] We have identified the cause of [ISSUE] and are working on a fix.
```

**Monitoring**
```
[Monitoring] A fix has been applied and we are monitoring service for stability.
```

**Resolved**
```
[Resolved] This incident has been resolved as of [TIME + TZ]. All systems
operational.
```

## 7. Executive escalation (Critical only)

```
To: [CTO / CEO]
Subject: CRITICAL ESCALATION — [COMPONENT]

A Critical incident has been active for [DURATION] and has crossed the escalation
threshold.

Impact: [BUSINESS IMPACT]
Customers affected: [SCOPE]
Status: [CURRENT STATE]
Actions taken: [SUMMARY]
Help needed: [DECISION / RESOURCE / VENDOR ENGAGEMENT]

IC: [NAME] — joining bridge: [LINK]
```

## 8. Vendor / platform engagement (SoundSafe)

```
To: support@soundsafe.ai / platform@soundsafe.ai
Subject: [Critical/High] OmniusGrid — [COMPONENT] incident, assistance requested

Environment: [PROD / DR site]
Incident start: [TIME + TZ]
Symptom: [DESCRIPTION + relevant alert names]
Steps taken: [SUMMARY + runbook used]
Logs/artifacts: [LINK]
Requested help: [SPECIFIC ASK]

Contact: [NAME] — [PHONE] — [EMAIL]
```

## 9. Post-incident summary (within 48h for Critical/High)

```
# Post-Incident Review — [INCIDENT ID]

Severity: [Critical/High/Medium/Low]
Duration: [START] – [END] ([TOTAL])
Components: [LIST]

## Impact
[Who/what was affected, for how long, measured RTO/RPO vs target]

## Timeline
- [TIME] — [EVENT]
- [TIME] — [EVENT]

## Root cause
[CONFIRMED ROOT CAUSE]

## What went well / what didn't
- [ ... ]

## Action items
| Action | Owner | Due |
|--------|-------|-----|
| [ ] [ACTION] | [NAME] | [DATE] |
```

---

## Contact list (keep current)

> Replace placeholders with real on-call contacts. These mirror the per-runbook
> contact sections.

| Role | Contact |
|------|---------|
| On-Call DevOps | `[PHONE]` / `[EMAIL]` |
| On-Call Backend | `[PHONE]` / `[EMAIL]` |
| On-Call DBA | `[PHONE]` / `[EMAIL]` |
| IT Manager | `[PHONE]` / `[EMAIL]` |
| CTO | `[PHONE]` / `[EMAIL]` |
| SoundSafe Support | support@soundsafe.ai |
| SoundSafe Platform Eng | platform@soundsafe.ai |

---

**Document Version:** 1.0
**Component:** Disaster Recovery — Incident Communication
