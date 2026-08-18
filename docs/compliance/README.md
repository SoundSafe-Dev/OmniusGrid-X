# Compliance — what is claimed here, and what backs it

**Target frameworks.** CMMC Level 2 (NIST SP 800-171) is the first assessment target, with
SOC 2 Type II, ISO 27001, GDPR and FedRAMP Moderate mapped alongside. Deployment profiles
span commercial cloud, gov cloud, on-prem and air-gapped, and a control's status can differ
between them — physical controls are inherited from a cloud provider and organizational
on-prem, so a single global status would have to be wrong about one of them.

## The rule this directory now follows

**Every control claim names the code that implements it and the test that proves it, or it
is not written down as implemented.**

That rule exists because the opposite was here. `SOC2_COMPLIANCE.md` (392 lines) and
`ISO27001_COMPLIANCE.md` (576 lines) were removed on 2026-08-17, and the reason is recorded
rather than quietly buried: they asserted controls this system does not have. Verbatim:

| The document said | What is actually true |
|---|---|
| "Multi-factor authentication required" | MFA does not exist. TOTP helpers sit in `keycloak_service.py` and are unreachable — the orphaned-definition guard lists them |
| "Quarterly access reviews" | No access review or recertification exists anywhere |
| "Intrusion detection system (IDS)" | There is none |
| "Password Policy: Minimum 12 characters, complexity requirements" | Length only, and not applied on the register or admin-create paths |
| "Quarterly incident response drills" | No drill has evidence |
| "Quarterly internal audits" | Same |

Between them, 314 control claims, and **not one cited an implementation file or a test.**
They also asserted organizational facts — board oversight, personnel training, disciplinary
process — that a code repository has no standing to attest to at all.

This is worse than having no documentation. An assessor who reads "MFA required", asks for
the evidence, and is told the feature is unreachable does not just strike that control; they
lose their reason to believe anything else in the package. The rest of this repository is
unusually well evidenced — 5,000+ tests written as named guards, 23 blocking CI jobs — and
these two files put all of it at risk to say things nobody had checked.

## What is here and is accurate

- **[ACCESS_CONTROL.md](ACCESS_CONTROL.md)** — the role × capability matrix. Matches
  `app/core/roles.py` and `app/middleware/rbac.py`, and is enforced by `test_rbac.py`,
  `test_role_vocabulary_parity.py` and `test_route_auth_walk.py`.
- **[GDPR_COMPLIANCE.md](GDPR_COMPLIANCE.md)** — names endpoints that exist in
  `app/api/gdpr.py`. Read its own caveats: erasure is pseudonymisation of the `users` row,
  and export covers the user record and consents only.

## The generated package

`docs/compliance/generated/` — rendered from the catalogue by `make compliance`, never
hand-edited, and held byte-for-byte against their source by
`test_generated_compliance_docs_are_current.py`:

| File | What it is |
|---|---|
| `system-security-plan.md` | Control implementation narrative, per deployment profile |
| `statement-of-applicability.md` | ISO 27001 Annex A mapping — **partial, and says so** |
| `poam.csv` | 158 dated lines with owners, sorted by scheduled completion |

The current position, from the catalogue rather than from anybody's summary: **59 controls
covering all 110 practices — 9 implemented, 36 partial, 4 absent, 9 organizational, 1
inherited** (commercial-cloud profile). Covered means every practice has an honest answer.
It does not mean a good one.

## What replaces the documents that were removed

A machine-readable control catalogue under `backend/compliance/catalog/`, from which the
SSP, Statement of Applicability and POA&M are **generated** — so a control cannot be
claimed without naming the test that proves it, and deleting that test fails the build.
Generated output lands in `docs/compliance/generated/` and is never hand-edited.

**The honest statement of position: no framework compliance is claimed here.** No
assessment has been performed, no C3PAO engaged, no ATO sought. What exists is a set of
technical controls, each named, each with an owner, and each either evidenced by a test that
runs on every build or recorded as a dated POA&M line.

That distinction is the point of this directory. A repository can honestly say "these
controls operate and here is what proves it". It cannot say "we are compliant" — that word
belongs to an assessor, and claiming it early is what made the two removed documents a
liability rather than an asset.
