<!-- GENERATED FROM backend/compliance/catalog/ — DO NOT EDIT.
     Regenerate with `make compliance`. Edits here are overwritten and, worse, are
     invisible to the guards that keep control claims tied to tests. Change the
     catalogue instead. -->

# System Security Plan — control implementation

Framework: **NIST SP 800-171 Rev 2**, 110 practices.

Status is stated **per deployment profile**. OmniusGrid ships to commercial cloud, gov cloud, on-premises and air-gapped environments, and a control is a property of code *in a place*: physical protection is inherited from a provider in cloud and organizational on-premises; clock discipline is partial online and absent air-gapped. A single status would have to be wrong about at least one profile.

## Summary (commercial cloud profile)

| Status | Controls |
|---|---|
| Implemented | 9 |
| Partially implemented | 36 |
| Not implemented | 4 |
| Organizational (not satisfiable by code) | 9 |
| Inherited from provider | 1 |

59 controls covering all 110 practices. **Covered is not implemented** — every practice has an honest answer, and the answers are above.

---

## 03.01 — Access Control

### OG-AC-001 — Access requires an authenticated principal; anonymous access is refused

**Status.** Implemented

**Practices.** 03.01.01

**Also satisfies.** 800-53r5:AC-3, 800-53r5:IA-2, ISO27001:A.5.15, SOC2:CC6.1

**Owner.** platform-security

**Implementation.** `test_route_auth_walk.py` walks the whole route tree asserting each route's auth gate, so a new unauthenticated route fails the build rather than being found later.

**Implemented by.**

- `app/api/auth.py`
- `app/core/security.py`
- `app/middleware/rbac.py`

**Evidence — automated tests, run on every build.**

- `tests/test_public_probes_do_not_disclose.py`
- `tests/test_route_auth_walk.py`
- `tests/test_websocket_auth_hardening.py`


### OG-AC-002 — Every request is bound to its tenant, and the tenant is never taken from the request

**Status.** Implemented

**Practices.** 03.01.02, 03.01.03

**Also satisfies.** 800-53r5:AC-3, 800-53r5:AC-4, GDPR:Art32.1b, ISO27001:A.5.15, SOC2:CC6.1

**Owner.** platform-security

**Implementation.** The strongest control in the system. Organisation is derived from the JWT subject and fails closed; `app.current_org_id` is re-asserted at the start of every transaction by an `after_begin` listener, which is the fix for a real defect where a mid-request commit silently dropped the binding. `03.01.03` (CUI flow control) is claimed only for the tenant boundary — there is no CUI-specific labelling or flow enforcement, which is recorded against OG-AC-010.

**Implemented by.**

- `app/core/tenant.py`
- `app/core/tenant_refs.py`
- `app/middleware/tenant_isolation.py`
- `database/migrations/011_tenant_isolation_rls.sql`
- `database/migrations/033_rls_backfill.sql`

**Evidence — automated tests, run on every build.**

- `tests/test_a_tenant_reference_is_refused_realdb.py`
- `tests/test_every_tenant_table_has_a_policy.py`
- `tests/test_no_handler_takes_its_tenant_from_the_body.py`
- `tests/test_no_rls_claims_are_true_realdb.py`
- `tests/test_org_id_is_never_taken_from_the_client.py`
- `tests/test_tenant_isolation_api.py`
- `tests/test_tenant_session_guard.py`


### OG-AC-003 — Privileged functions are restricted to a defined role vocabulary

**Status.** Partially implemented

**Practices.** 03.01.05, 03.01.07

**Also satisfies.** 800-53r5:AC-6, ISO27001:A.8.2, SOC2:CC6.3

**Owner.** platform-security

**Assessment.** Three ranked roles (viewer < operator < admin), enforced with a CHECK constraint and a single source of truth that raises at import on an unknown name. PARTIAL because least privilege is coarse at this granularity — there is no per-resource permission model — and because privileged execution is only partly captured in the audit log (the middleware covers 18 route templates; see OG-AU-001). Kubernetes RBAC is separately thin: only the monitoring stack has Roles.

**Planned completion.** 2027-01-31

**Implemented by.**

- `app/core/roles.py`
- `app/middleware/rbac.py`
- `database/migrations/048_user_role_constraint.sql`

**Evidence — automated tests, run on every build.**

- `tests/test_rbac.py`
- `tests/test_role_vocabulary_parity.py`
- `tests/test_task10_rbac_api.py`


### OG-AC-004 — Unsuccessful logon attempts are limited

**Status.** Partially implemented

**Practices.** 03.01.08

**Also satisfies.** 800-53r5:AC-7, ISO27001:A.8.5, SOC2:CC6.1

**Owner.** platform-security

**Assessment.** Rate limiting is now REQUIRED in production — `validate_settings()` hard-fails at startup without it (FS-744), which closed a hole where production could run with the only brute-force control switched off and nothing would say so. Still PARTIAL because rate limiting is not lockout: there is no `failed_login_count`, no `locked_until`, and no progressive delay, so an attacker who paces below the limit is unbounded. 800-171 3.1.8 expects the account to lock.

**Planned completion.** 2026-12-31

**Implemented by.**

- `app/api/auth.py`
- `app/core/config.py`
- `app/middleware/rate_limit.py`

**Evidence — automated tests, run on every build.**

- `tests/test_config_validation.py`


### OG-AC-005 — Sessions terminate on a defined condition and can be revoked immediately

**Status.** Partially implemented

**Practices.** 03.01.11

**Also satisfies.** 800-53r5:AC-12, ISO27001:A.8.5, SOC2:CC6.1

**Owner.** platform-security

**Assessment.** Refresh tokens are stored as SHA-256 hashes with single-use rotation and `replaced_by_jti` lineage; a durable `revoked_tokens` denylist is checked on every request; access tokens carry `sid` binding them to a live session so deactivation propagates across replicas immediately; concurrent sessions are capped at 3. PARTIAL because termination is time-based (30 min access / 7 day refresh) with no inactivity-based expiry.

**Planned completion.** 2027-01-31

**Implemented by.**

- `app/core/session.py`
- `database/migrations/038_auth_session_hardening.sql`

**Evidence — automated tests, run on every build.**

- `tests/test_auth_sessions.py`


### OG-AC-006 — Session lock after inactivity

**Status.** Not implemented

**Practices.** 03.01.10

**Also satisfies.** 800-53r5:AC-11, ISO27001:A.8.1

**Owner.** platform-security

**Assessment.** No idle lock or auto-logout exists in the frontend. A named L2 practice and a visible one — an assessor sits at an unattended browser to check it.

**Planned completion.** 2027-01-31


### OG-AC-007 — Separation of duties, and use of non-privileged accounts for non-security functions

**Status.** Not implemented

**Practices.** 03.01.04, 03.01.06

**Also satisfies.** 800-53r5:AC-5, 800-53r5:AC-6, ISO27001:A.5.3

**Owner.** organisation

**Assessment.** Three roles with no duty-separation matrix: an admin both grants access and reviews the audit log of that grant. There is also no second, non-privileged account model — an admin operates as an admin for ordinary work. Part organizational (defining which duties must not combine) and part code (enforcing it), so it is `absent` rather than `organizational` — the code half is real work, not a policy statement.

**Planned completion.** 2027-03-31


### OG-AC-008 — Remote access is routed through managed, monitored, encrypted access points

**Status.** commercial-cloud: Partially implemented; gov-cloud: Partially implemented; on-prem: Partially implemented; air-gapped: Organizational (not satisfiable by code)

**Practices.** 03.01.12, 03.01.13, 03.01.14, 03.01.15

**Also satisfies.** 800-53r5:AC-17, ISO27001:A.6.7, SOC2:CC6.6

**Owner.** platform-infra

**Why this is not a code control.** In an air-gapped enclave there is no remote access to manage; the practice is met by the physical and procedural controls of the enclave itself, which this system cannot implement or evidence.

**Assessment.** A single ingress with TLS termination and HSTS is the managed access point, and privileged remote agent operations carry a `RemoteOperationAuditContext` recording who requested them. PARTIAL because in-cluster traffic is plaintext (see OG-SC-003) and there is no session monitoring beyond access logs.

**Planned completion.** 2027-02-28

**Implemented by.**

- `app/api/fleet_agents.py`
- `app/middleware/security_headers.py`
- `app/services/remote_operations.py`
- `infrastructure/k8s/base/ingress.yaml`

**Evidence — automated tests, run on every build.**

- `tests/test_remote_operations_unit.py`
- `tests/test_route_auth_walk.py`


### OG-AC-009 — Connections to external systems are verified and controlled

**Status.** commercial-cloud: Partially implemented; gov-cloud: Partially implemented; on-prem: Partially implemented; air-gapped: Implemented

**Practices.** 03.01.20

**Also satisfies.** 800-53r5:AC-20, ISO27001:A.5.19, SOC2:CC9.2

**Owner.** platform-infra

**Assessment.** Eight ERP connectors and GeoTab are the external systems; egress is constrained by default-deny NetworkPolicy with per-workload allow-lists. PARTIAL because there is no formal inventory or approval record of external system connections, which is what the practice asks for. `air-gapped` is `implemented` by construction: there are no external connections.

**Planned completion.** 2027-02-28

**Implemented by.**

- `app/api/erp_integrations.py`
- `app/services/erp_connectors`
- `infrastructure/k8s/base/ingress.yaml`

**Evidence — automated tests, run on every build.**

- `tests/test_erp_sync_correlation.py`


### OG-AC-010 — CUI on publicly accessible systems, and CUI-specific flow control

**Status.** Not implemented

**Practices.** 03.01.09, 03.01.22

**Also satisfies.** 800-53r5:AC-22, 800-53r5:AC-8

**Owner.** organisation

**Assessment.** There is no CUI marking, no CUI-aware flow control, and no privacy/security notice at logon. This is downstream of a decision nobody has made yet: whether CUI enters this system at all, and if so which fields carry it. Until the boundary is defined these practices cannot be designed, let alone implemented — recorded here so the dependency is visible rather than discovered during an assessment.

**Planned completion.** 2027-03-31


### OG-AC-011 — Wireless, mobile device and portable storage controls

**Status.** Organizational (not satisfiable by code)

**Practices.** 03.01.16, 03.01.17, 03.01.18, 03.01.19, 03.01.21

**Also satisfies.** 800-53r5:AC-18, 800-53r5:AC-19, ISO27001:A.8.1

**Owner.** organisation

**Why this is not a code control.** Wireless authorisation, mobile device enrolment, device encryption and portable-storage restriction are properties of the endpoints and networks the organisation operates, not of this application. OmniusGrid runs on servers and edge gateways it does not own or manage; asserting these here would claim control over customer infrastructure. They are satisfied by an MDM and a network policy, evidenced outside this repository.

**Assessment.** Needs an owner in the organisation and evidence held in the ISMS. Listed rather than omitted because an assessor will ask, and "not applicable" is a claim that has to be argued from the boundary definition.

**Planned completion.** 2027-03-31


---

## 03.02 — Awareness and Training

### OG-AT-001 — Security awareness and role-based training, including insider threat

**Status.** Organizational (not satisfiable by code)

**Practices.** 03.02.01, 03.02.02, 03.02.03

**Also satisfies.** 800-53r5:AT-2, 800-53r5:AT-3, ISO27001:A.6.3, SOC2:CC1.4

**Owner.** organisation

**Why this is not a code control.** Training is delivered to people and evidenced by completion records. No test can establish that a person understood a risk. The deleted SOC 2 document asserted "Security awareness training for all personnel" from inside a code repository, which is precisely the class of claim that costs credibility when an assessor asks for the attendance record.

**Assessment.** Needs a training programme with role-based content for privileged users, an insider threat module, and completion records retained for the assessment period. Evidence lives in an HR or LMS system, referenced from the SSP.

**Planned completion.** 2027-03-31


---

## 03.03 — Audit and Accountability

### OG-AU-001 — Audit records are created for security-relevant operations and retained

**Status.** Partially implemented

**Practices.** 03.03.01

**Also satisfies.** 800-53r5:AU-2, 800-53r5:AU-3, ISO27001:A.8.15, SOC2:CC7.2

**Owner.** platform-security

**Assessment.** PARTIAL for two measured reasons, not as a hedge. The middleware captures 18 hardcoded route templates (`SENSITIVE_OPERATIONS`) out of ~546 operations, and request/response bodies are never captured — `_get_request_body` is a documented no-op because reading the stream would consume it. Explicit `record_audit` writers cover ~38 further actions. No retention period is defined for `audit_logs` and nothing purges or archives it.

**Planned completion.** 2026-11-30

**Implemented by.**

- `app/middleware/audit.py`
- `app/services/audit.py`
- `app/services/user_audit.py`
- `database/migrations/009_audit_logs.sql`

**Evidence — automated tests, run on every build.**

- `tests/test_audit_sensitive_operations.py`
- `tests/test_audit_writers_bind_a_tenant_realdb.py`


### OG-AU-002 — Every audit record is attributable to an individual user

**Status.** Implemented

**Practices.** 03.03.02

**Also satisfies.** 800-53r5:AU-3, ISO27001:A.8.15, SOC2:CC7.2

**Owner.** platform-security

**Implemented by.**

- `app/db/models.py`
- `app/services/audit.py`

**Evidence — automated tests, run on every build.**

- `tests/test_audit_and_gdpr_tenant_scoping_realdb.py`
- `tests/test_audit_writers_bind_a_tenant_realdb.py`


### OG-AU-003 — An audit write that fails is visible rather than silent

**Status.** Implemented

**Practices.** 03.03.04

**Also satisfies.** 800-53r5:AU-5, SOC2:CC7.2

**Owner.** platform-security

**Implementation.** `AUDIT_WRITE_FAILURES` is a counter with an `AuditWriteFailing` alert rule, and the rule is unit-tested by promtool rather than merely written down.

**Implemented by.**

- `app/middleware/audit.py`
- `app/services/audit.py`
- `infra/prometheus/alerts.yml`

**Evidence — automated tests, run on every build.**

- `tests/test_a_failed_audit_write_is_visible.py`


### OG-AU-004 — Audit records are tamper-evident and the evidence can be verified

**Status.** Partially implemented

**Practices.** 03.03.08

**Also satisfies.** 800-53r5:AU-9, ISO27001:A.8.15, SOC2:CC7.2

**Owner.** platform-security

**Assessment.** The chain verifies and detects mutation, deletion and forgery (FS-743). It is still PARTIAL because tamper-EVIDENCE is not tamper-RESISTANCE: `audit_logs` grants no append-only enforcement, so a role with UPDATE/DELETE can still alter rows — the chain proves it happened, it does not prevent it. Needs `REVOKE UPDATE, DELETE` and a WORM export before this is `implemented`.

**Planned completion.** 2026-12-31

**Implemented by.**

- `app/api/audit.py`
- `database/migrations/069_audit_hash_chain_is_verifiable.sql`

**Evidence — automated tests, run on every build.**

- `tests/test_the_audit_chain_actually_verifies_realdb.py`
- `tests/test_the_audit_chain_survives_its_own_schema.py`


### OG-AU-005 — Audit log access is restricted to privileged users and scoped to one tenant

**Status.** Implemented

**Practices.** 03.03.09

**Also satisfies.** 800-53r5:AU-9, ISO27001:A.8.15, SOC2:CC6.1

**Owner.** platform-security

**Implementation.** All five audit endpoints are `require_admin` on a `get_tenant_db` session. The `organization_id` query parameter was deliberately removed — cross-tenant audit read would need a super-admin role that this system intentionally does not have.

**Implemented by.**

- `app/api/audit.py`
- `app/middleware/rbac.py`

**Evidence — automated tests, run on every build.**

- `tests/test_audit_and_gdpr_tenant_scoping_realdb.py`
- `tests/test_route_auth_walk.py`


### OG-AU-006 — Audit records carry a synchronised, unambiguous timestamp

**Status.** commercial-cloud: Partially implemented; gov-cloud: Partially implemented; on-prem: Partially implemented; air-gapped: Not implemented

**Practices.** 03.03.07

**Also satisfies.** 800-53r5:AU-8, ISO27001:A.8.17

**Owner.** platform-security

**Assessment.** Backend records are aware-UTC and a repo-wide guard forbids naive `utcnow`. There is no configured authoritative time source, and on the edge the skew estimator calibrates only while the cloud is reachable — so `air-gapped` is `absent` rather than `partial`: the one deployment where clock discipline matters most is the one with no correction at all (see the DDIL workstream, S8).

**Planned completion.** 2027-01-31

**Implemented by.**

- `app/db/models.py`
- `edge-agent/opsgrid_agent/timesync.py`

**Evidence — automated tests, run on every build.**

- `tests/test_no_naive_utcnow.py`


### OG-AU-007 — Audit review, analysis and reporting

**Status.** Not implemented

**Practices.** 03.03.03, 03.03.05, 03.03.06

**Also satisfies.** 800-53r5:AU-6, 800-53r5:AU-7, ISO27001:A.8.15

**Owner.** security-operations

**Assessment.** `GET /audit/summary` aggregates by action and period, which is a reporting surface but not a review PROCESS: nothing defines which events are reviewed, by whom, or how often, and no logged-event list is reviewed and updated. Log aggregation is also not deployed to Kubernetes — Loki exists in docker-compose only — so there is no correlation across components to review. Blocked on the SIEM decision.

**Planned completion.** 2027-02-28


---

## 03.04 — Configuration Management

### OG-CM-001 — Configuration is defined in version control and enforced at deploy time

**Status.** Partially implemented

**Practices.** 03.04.01, 03.04.02

**Also satisfies.** 800-53r5:CM-2, 800-53r5:CM-6, ISO27001:A.8.9, SOC2:CC8.1

**Owner.** platform-infra

**Assessment.** Every deployed setting is a manifest in git, and `check_backend_security_config.py` asserts the security-relevant ones actually reach the container — resolving `envFrom` the way the kubelet does, which exists because `validate_settings()` was once never armed: `ENVIRONMENT` appeared in zero manifests, so the production branch never ran. PARTIAL because there is no declared BASELINE — no golden configuration to compare a running system against, and no drift detection. Inventory is likewise implicit in the manifests rather than maintained as an artifact.

**Planned completion.** 2027-02-28

**Implemented by.**

- `app/core/config.py`
- `app/core/startup_checks.py`
- `infrastructure/k8s`

**Evidence — automated tests, run on every build.**

- `tests/test_config_validation.py`


### OG-CM-002 — Changes are tracked, reviewed and approved before they take effect

**Status.** Partially implemented

**Practices.** 03.04.03, 03.04.04, 03.04.05

**Also satisfies.** 800-53r5:CM-3, 800-53r5:CM-5, ISO27001:A.8.32, SOC2:CC8.1

**Owner.** platform-infra

**Assessment.** 23 blocking CI jobs gate every change and the count is itself asserted so it cannot go stale. The gap is not tooling, it is authority: **branch protection is not enabled** — an open item from the 2026-08-15 incident, where all 17 branches were force-pushed. Until it is on, "changes are reviewed before they take effect" describes intent rather than an enforced control, because any credential with write access pushes straight past all 23 jobs. The incident is the proof. `docs/runbooks/branch-protection.md` carries the exact API calls and the verification command; it needs an org admin token, which the development environment does not have, so this cannot be closed from inside the repository. Note what it still would NOT close: the credential used in August has never been identified, so protection narrows that credential's reach without revoking it.

**Planned completion.** 2026-12-31

**Implemented by.**

- `.github/workflows/ci-cd.yml`
- `.github/workflows/quality-gates.yml`
- `docs/runbooks/branch-protection.md`

**Evidence — automated tests, run on every build.**

- `tests/test_ci_gate_count_is_accurate.py`


### OG-CM-003 — Least functionality — nonessential functions are restricted or disabled

**Status.** Partially implemented

**Practices.** 03.04.06, 03.04.07

**Also satisfies.** 800-53r5:CM-7, ISO27001:A.8.19

**Owner.** platform-infra

**Assessment.** Pod Security Admission runs `restricted`, containers drop ALL capabilities with a read-only root filesystem and no privilege escalation, and `validate_settings()` refuses a production start with the dev-token bypass, open registration, wildcard CORS or simulated telematics enabled. PARTIAL because the DEFAULTS still invert the principle — `ALLOW_DEV_TOKEN` defaults True and is caught only by the production gate — and because the backend runtime image still carries `gcc` and `libpq-dev` from the build.

**Planned completion.** 2027-01-31

**Implemented by.**

- `app/core/config.py`
- `infrastructure/k8s/base/namespace.yaml`

**Evidence — automated tests, run on every build.**

- `tests/test_config_validation.py`


### OG-CM-004 — Software execution policy and control of user-installed software

**Status.** Partially implemented

**Practices.** 03.04.08, 03.04.09

**Also satisfies.** 800-53r5:CM-11, 800-53r5:CM-7(4)

**Owner.** platform-infra

**Assessment.** Dependencies are pinned with justifications, `pip-audit`, `npm audit` and a Trivy filesystem scan block the build, and a repo-hygiene gate refuses tracked key material or dependency directories. Two real gaps: **no image signing** (nothing verifies what runs is what CI built — cosign is absent) and **no base-image digest pinning** (every image uses a mutable tag). After a supply-chain compromise in this repository's own history, both are pointed questions rather than theoretical ones. Admission control that could enforce either is also absent — no Kyverno, no Gatekeeper.

**Planned completion.** 2027-02-28

**Implemented by.**

- `.github/workflows/quality-gates.yml`
- `backend/requirements.txt`

**Evidence — automated tests, run on every build.**

- `tests/test_build_configs_are_not_executable_payloads.py`


---

## 03.05 — Identification and Authentication

### OG-IA-001 — Users, services and devices are identified before access is granted

**Status.** Implemented

**Practices.** 03.05.01, 03.05.02

**Also satisfies.** 800-53r5:IA-2, 800-53r5:IA-3, ISO27001:A.5.16, SOC2:CC6.1

**Owner.** platform-security

**Implementation.** Three distinct identities: users (JWT with enforced `sub`/`jti`/`type`/`iat` claims), edge devices (X.509 issued by an internal EC P-256 CA, tenant encoded in the certificate subject), and service principals via SSO. Device enrolment is a one-time bootstrap token exchanged for a signed certificate.

**Implemented by.**

- `app/api/auth.py`
- `app/api/edge_enroll.py`
- `app/core/security.py`
- `app/services/device_provisioning.py`
- `app/services/edge_ca.py`

**Evidence — automated tests, run on every build.**

- `tests/test_auth_sessions.py`
- `tests/test_edge_enrollment.py`
- `tests/test_route_auth_walk.py`


### OG-IA-002 — Multifactor authentication for privileged and network access

**Status.** Partially implemented

**Practices.** 03.05.03, 03.05.04

**Also satisfies.** 800-53r5:IA-2(1), 800-53r5:IA-2(2), ISO27001:A.8.5, SOC2:CC6.1

**Owner.** platform-security

**Assessment.** RAISED absent -> partial (FS-750). TOTP (RFC 6238) is implemented for local accounts and **enforced at login**: a confirmed factor makes the correct password alone a 401. That distinction is the whole control — enrolment endpoints without enforcement would have reproduced exactly the defect they replaced, since `keycloak_service.enable_mfa` already existed and was called by nothing. Secrets are AES-256-GCM envelopes, recovery codes are single-use SHA-256 digests, and a code cannot be replayed inside its own window (RFC 6238 s5.2, the step most implementations skip). PARTIAL, not implemented, for two reasons that need decisions rather than code: MFA is currently OPT-IN per user, and 3.5.3 requires it for privileged accounts — enforcement for the `admin` role needs an enrolment grace period and a lockout story before it can be switched on. And it covers local password login only; SSO deployments inherit MFA from the identity provider, which is the right answer but is evidenced there rather than here. Superseded text follows for the record — this WAS the single largest named gap in this catalogue. 3.5.3 requires MFA for local and network access to privileged accounts and for network access to non-privileged accounts. Nothing here provides it. `enable_mfa`/`disable_mfa` exist in `app/services/keycloak_service.py` and are unreachable — this repository's own orphaned-definition guard lists them, so the code is present, untested and called by nothing. Two viable routes: wire the Keycloak TOTP required-action, or mandate SSO-with-MFA for CUI profiles and disable local password auth entirely (the stronger posture, and the one that also serves PIV/CAC). The second is the FIPS workstream's Phase 2 anyway, so these should be done together. `03.05.04` (replay-resistant authentication) rides on the same decision.

**Planned completion.** 2026-12-31

**Implemented by.**

- `app/api/auth.py`
- `app/api/mfa.py`
- `app/core/mfa.py`
- `database/migrations/070_user_mfa.sql`

**Evidence — automated tests, run on every build.**

- `tests/test_mfa_is_required_at_login_realdb.py`


### OG-IA-003 — Credentials are stored and transmitted only in cryptographically protected form

**Status.** Partially implemented

**Practices.** 03.05.10

**Also satisfies.** 800-53r5:IA-5(1), ISO27001:A.5.17, SOC2:CC6.1

**Owner.** platform-security

**Assessment.** New passwords are PBKDF2-HMAC-SHA256 at 600k iterations (FS-748) — the SP 800-132-approved KDF — and refresh tokens, API keys and invitation tokens are SHA-256 digests of high-entropy random secrets, which is correct: 800-132 governs passwords, not 128-bit random values. Login rehashes legacy hashes in place, so users migrate as they arrive with no reset. PARTIAL until the migration window CLOSES: bcrypt remains registered as a deprecated scheme so existing hashes still verify, and while it is registered the application can still read a non-approved format. `auth_password_hash_scheme_total` makes the remaining population a dashboard number. The window must close before the FIPS base image lands — in enforcing mode the bcrypt verify path may raise rather than return False, which would lock out every user who had not logged in since.

**Planned completion.** 2027-01-31

**Implemented by.**

- `app/api/auth.py`
- `app/core/password.py`
- `app/core/session.py`
- `app/core/sso.py`
- `app/services/user_invitations.py`

**Evidence — automated tests, run on every build.**

- `tests/test_auth_sessions.py`
- `tests/test_no_unapproved_primitive_is_reachable.py`
- `tests/test_passwords_use_an_approved_kdf.py`
- `tests/test_user_invitation_unit.py`


### OG-IA-004 — Authentication feedback does not disclose which factor failed

**Status.** Implemented

**Practices.** 03.05.11

**Also satisfies.** 800-53r5:IA-6, SOC2:CC6.1

**Owner.** platform-security

**Implementation.** A uniform 401 for bad credentials and for an inactive user, so login cannot be used to enumerate accounts. Auth metrics carry a reason label deliberately unlabelled by email or IP, so the counter cannot become the enumeration oracle the response is not.

**Implemented by.**

- `app/api/auth.py`

**Evidence — automated tests, run on every build.**

- `tests/test_public_probes_do_not_disclose.py`


### OG-IA-005 — Password composition, reuse and lifetime policy

**Status.** Partially implemented

**Practices.** 03.05.07, 03.05.08, 03.05.09

**Also satisfies.** 800-53r5:IA-5, ISO27001:A.5.17

**Owner.** platform-security

**Assessment.** `validate_new_password` enforces a 12-character minimum and a 72-byte ceiling — and **only on the invitation-accept path**. `POST /auth/register` and admin `POST /users/` do not call it, so two of the three ways an account gets a password apply no policy at all. There is no history, no expiry, and no breach-list check. The first fix is to route all three paths through one validator; the policy content is a second decision (NIST SP 800-63B argues against composition rules and expiry, while 800-171 3.5.7-3.5.9 asks for them — that tension needs a written position before an assessment, not during one).

**Planned completion.** 2027-01-31

**Implemented by.**

- `app/core/config.py`
- `app/services/user_invitations.py`

**Evidence — automated tests, run on every build.**

- `tests/test_user_invitation_unit.py`


### OG-IA-006 — Identifier reuse and inactivity management

**Status.** Partially implemented

**Practices.** 03.05.05, 03.05.06

**Also satisfies.** 800-53r5:IA-4, ISO27001:A.5.16

**Owner.** platform-security

**Assessment.** Identifiers are UUIDs and are never reused; deprovisioning is deactivation rather than deletion (deliberately — audit rows, alarm acknowledgements and rule ownership reference the user), and a last-active-admin guard prevents locking the tenant out. PARTIAL because nothing acts on inactivity: `last_login` is stored and displayed, and no job disables a dormant account. 3.5.6 asks for that to happen automatically.

**Planned completion.** 2027-02-28

**Implemented by.**

- `app/api/user_management.py`
- `app/api/users.py`

**Evidence — automated tests, run on every build.**

- `tests/test_user_management.py`


---

## 03.06 — Incident Response

### OG-IR-001 — An incident handling capability exists — preparation, detection, analysis, containment, recovery

**Status.** Partially implemented

**Practices.** 03.06.01

**Also satisfies.** 800-53r5:IR-4, ISO27001:A.5.24, SOC2:CC7.4

**Owner.** security-operations

**Assessment.** There are eleven runbooks, incident communication templates, and — unusually — a real worked incident: the 2026-08-15 supply-chain compromise is documented with IoCs, a restoration table, and a guard written afterwards to prevent the specific technique. That is stronger evidence of capability than an untested plan. It is PARTIAL for two reasons, and the second is uncomfortable: there is no formal Incident Response PLAN (the runbooks are recovery procedures, not a plan with roles, severity definitions and authority to declare), and **that incident is still open** — the credential used for the force-push was never identified, tokens are unrotated, and branch protection is unconfirmed. An open compromise with an unidentified credential is the first thing an assessor will read, and the date on this entry reflects that it should be closed before an assessment rather than after.

**Planned completion.** 2026-11-30

**Implemented by.**

- `SECURITY-INCIDENT-2026-08-15.md`
- `docs/runbooks`
- `docs/runbooks/incident-communication-templates.md`
- `docs/runbooks/leaked-key-rotation.md`

**Evidence — automated tests, run on every build.**

- `tests/test_build_configs_are_not_executable_payloads.py`


### OG-IR-002 — Incidents are tracked, documented and reported to designated authorities

**Status.** Partially implemented

**Practices.** 03.06.02

**Also satisfies.** 800-53r5:IR-6, GDPR:Art33, ISO27001:A.5.25

**Owner.** security-operations

**Assessment.** Documentation of the one real incident is thorough. Reporting is not defined: nobody has written down who is notified, within what deadline, for which severity. Two hard external deadlines already apply and neither is captured — GDPR Article 33 requires supervisory-authority notification within 72 hours of awareness, and DFARS 252.204-7012 requires DoD reporting within 72 hours for CUI incidents. Those are legal obligations that a missing runbook does not suspend.

**Planned completion.** 2027-01-31

**Implemented by.**

- `SECURITY-INCIDENT-2026-08-15.md`
- `docs/runbooks/incident-communication-templates.md`

**Evidence — automated tests, run on every build.**

- `tests/test_documented_files_exist.py`


### OG-IR-003 — The incident response capability is tested

**Status.** Partially implemented

**Practices.** 03.06.03

**Also satisfies.** 800-53r5:IR-3, ISO27001:A.5.24

**Owner.** security-operations

**Assessment.** One genuine automated drill: `test_backup_restore_drill.py` round-trips a real `pg_dump`/`pg_restore` on every CI run and asserts that rows, schema version AND tenant RLS isolation survive — a restore that silently drops RLS policies fails the build. That is a tested recovery capability. It is not an incident response exercise: no tabletop, no simulated compromise, no measured time-to-detect. The 2026-08-15 incident was an unplanned live test and its lessons are recorded, which is worth citing while being clear it was not a drill.

**Planned completion.** 2027-02-28

**Implemented by.**

- `backend/tests/test_backup_restore_drill.py`

**Evidence — automated tests, run on every build.**

- `tests/test_backup_restore_drill.py`


---

## 03.07 — Maintenance

### OG-MA-001 — System maintenance, maintenance tools, personnel and nonlocal maintenance

**Status.** Organizational (not satisfiable by code)

**Practices.** 03.07.01, 03.07.02, 03.07.03, 03.07.04, 03.07.05, 03.07.06

**Also satisfies.** 800-53r5:MA-2, 800-53r5:MA-4, ISO27001:A.7.13

**Owner.** organisation

**Why this is not a code control.** These practices govern the hardware lifecycle and the humans who touch it — sanitising equipment before off-site repair, checking diagnostic media for malicious code, supervising uncleared maintenance personnel. OmniusGrid runs on servers and edge gateways it does not own, and has no visibility into who opens the case.

**Assessment.** Note one that will become technical if a decision goes the other way: 3.7.5 requires MFA for nonlocal maintenance sessions. If remote support ever reaches an edge gateway through this platform's fleet operations surface, that practice moves from organizational to a control this system must implement — and the MFA gap in OG-IA-002 blocks it.

**Planned completion.** 2027-03-31


---

## 03.08 — Media Protection

### OG-MP-001 — Backup CUI is protected at rest at storage locations

**Status.** Partially implemented

**Practices.** 03.08.09

**Also satisfies.** 800-53r5:CP-9, ISO27001:A.8.13, SOC2:A1.2

**Owner.** platform-infra

**Assessment.** A nightly `pg_dump -Fc` uploads with `--sse AES256` and reads the object back to verify it, from a hardened pod. PARTIAL because retention and immutability are explicitly the operator's job — the manifest's own README says the job does not prune and that bucket versioning and object lock must be configured by hand, so neither is evidenced here. Note the recovery gap this shares with the DR runbooks: RPO is up to 24 hours because point-in-time recovery is not operational, which is documented and guarded rather than claimed.

**Planned completion.** 2027-02-28

**Implemented by.**

- `infrastructure/k8s/base/db-backup-cronjob.yaml`

**Evidence — automated tests, run on every build.**

- `tests/test_backup_restore_drill.py`
- `tests/test_recovery_claims_match_what_is_deployed.py`


### OG-MP-002 — Media handling — marking, transport, sanitisation, removable media

**Status.** Organizational (not satisfiable by code)

**Practices.** 03.08.01, 03.08.02, 03.08.03, 03.08.04, 03.08.05, 03.08.06, 03.08.07, 03.08.08

**Also satisfies.** 800-53r5:MP-2, 800-53r5:MP-6, ISO27001:A.7.10

**Owner.** organisation

**Why this is not a code control.** Marking, transporting, sanitising and destroying physical and removable media are acts performed by people on objects. An application cannot mark a disk, escort a courier or degauss a drive, and asserting these controls in a repository would claim custody of hardware the software does not own. In cloud profiles the underlying media controls are inherited from the provider; on-prem and air-gapped they are wholly the operator's.

**Assessment.** Needs an owner and evidence in the ISMS, plus a provider CRM reference for the cloud profiles. One technical dependency belongs to engineering and is tracked elsewhere: digital media confidentiality for CUI at rest — including the unencrypted edge buffer — is OG-SC-004, and the edge case is the one that makes 3.8 concrete rather than theoretical, because an edge gateway is media that can be carried away.

**Planned completion.** 2027-03-31


---

## 03.09 — Personnel Security

### OG-PS-001 — Personnel screening, and protection during termination and transfer

**Status.** Organizational (not satisfiable by code)

**Practices.** 03.09.01, 03.09.02

**Also satisfies.** 800-53r5:PS-3, 800-53r5:PS-4, ISO27001:A.6.1, SOC2:CC1.4

**Owner.** organisation

**Why this is not a code control.** Screening happens before an account exists. No code path observes a background check.

**Assessment.** The technical half of 3.9.2 IS available and is worth citing in the SSP narrative even though the practice is organizational: deprovisioning revokes sessions immediately through the `sid`-to-session binding, deactivation is preferred over deletion so audit history survives, and a last-active-admin guard prevents a departure from locking a tenant out (see OG-IA-006). What is missing is the process that triggers it on the day someone leaves.

**Planned completion.** 2027-03-31


---

## 03.10 — Physical Protection

### OG-PE-001 — Physical access is limited, monitored, logged and managed

**Status.** commercial-cloud: Inherited from provider; gov-cloud: Inherited from provider; on-prem: Organizational (not satisfiable by code); air-gapped: Organizational (not satisfiable by code)

**Practices.** 03.10.01, 03.10.02, 03.10.03, 03.10.04, 03.10.05

**Also satisfies.** 800-53r5:PE-2, 800-53r5:PE-3, 800-53r5:PE-6, ISO27001:A.7.1, ISO27001:A.7.2, SOC2:CC6.4

**Owner.** organisation

**Why this is not a code control.** Physical protection is performed at a facility. In cloud profiles it is inherited from the provider's authorised data centres, which is the normal and correct answer. On-prem and air-gapped it is inherited from nobody — the operator locks the room, escorts the visitor and keeps the access log, and in a tactical deployment the "facility" may be a vehicle.

**Inherited from.** TBD — the cloud provider for each deployment (customer responsibility matrix: TBD — provider customer responsibility matrix, section to be cited)

**Assessment.** `provider` and `crm_ref` are placeholders and are marked TBD rather than filled with a plausible-looking citation. Before an assessment they must name the actual provider authorisation and the section of its customer responsibility matrix that carries these controls; an invented reference is worse than an empty one, because it looks checked. This is the entry that most needs the deployment-boundary decision.

**Planned completion.** 2027-02-28


### OG-PE-002 — Safeguarding at alternate work sites

**Status.** Organizational (not satisfiable by code)

**Practices.** 03.10.06

**Also satisfies.** 800-53r5:PE-17, ISO27001:A.6.7

**Owner.** organisation

**Why this is not a code control.** An alternate work site is somebody's home or a customer's plant floor. The safeguards are physical and procedural, and the organisation defines them.

**Assessment.** Not inherited even in cloud profiles: a provider's data-centre authorisation says nothing about where an operator opens their laptop. Needs a remote-work policy, and it interacts with OG-AC-011 (mobile device controls) and OG-SC-010 (split tunnelling) — the three should be written as one section of the ISMS rather than three unrelated answers.

**Planned completion.** 2027-03-31


---

## 03.11 — Risk Assessment

### OG-RA-001 — Vulnerabilities are scanned for continuously and block the build

**Status.** Implemented

**Practices.** 03.11.02

**Also satisfies.** 800-53r5:RA-5, ISO27001:A.8.8, SOC2:CC7.1

**Owner.** platform-infra

**Implementation.** `pip-audit` on both Python trees, `npm audit --audit-level=high`, and Trivy across vuln, secret and misconfig scanners with `exit-code: 1` — all blocking, on every change, with zero suppressions: `.trivyignore` carries a written policy and no CVE entries. That is stronger than the periodic scan the practice asks for.

**Implemented by.**

- `.github/workflows/quality-gates.yml`
- `.trivyignore`

**Evidence — automated tests, run on every build.**

- `tests/test_ci_gate_count_is_accurate.py`


### OG-RA-002 — Vulnerabilities are remediated in accordance with risk

**Status.** Partially implemented

**Practices.** 03.11.03

**Also satisfies.** 800-53r5:RA-5, ISO27001:A.8.8, SOC2:CC7.1

**Owner.** security-operations

**Assessment.** Remediation is currently immediate-or-blocked, which sounds strict and is actually the gap: there is no severity-based SLA, so a HIGH finding and a CRITICAL finding are treated identically, and anything the scanners do not block has no defined response time at all. The image scan in `ci-cd.yml` sets no `exit-code`, so it cannot fail a deploy — findings there go to code scanning and nowhere else.

**Planned completion.** 2027-01-31

**Implemented by.**

- `.github/workflows/quality-gates.yml`

**Evidence — automated tests, run on every build.**

- `tests/test_ci_gate_count_is_accurate.py`


### OG-RA-003 — Periodic risk assessment

**Status.** Organizational (not satisfiable by code)

**Practices.** 03.11.01

**Also satisfies.** 800-53r5:RA-3, ISO27001:A.5.7

**Owner.** organisation

**Why this is not a code control.** A risk assessment weighs likelihood and business impact against the organisation's risk appetite, over a system boundary the organisation defines. No test can produce that judgement, and a repository asserting "risk assessments are performed annually" — as the deleted SOC 2 document did — is asserting something it cannot know.

**Assessment.** Needs an executive owner, a defined cadence, and evidence held in the ISMS. The threat-model gap noted against OG-SC-009 is the technical input this depends on.

**Planned completion.** 2027-03-31


---

## 03.12 — Security Assessment

### OG-CA-001 — Security controls are monitored continuously for continued effectiveness

**Status.** Partially implemented

**Practices.** 03.12.03

**Also satisfies.** 800-53r5:CA-7, ISO27001:A.5.35, SOC2:CC4.1

**Owner.** platform-security

**Assessment.** This catalogue IS the continuous-monitoring mechanism, and it is unusually literal about it: a control claiming to operate must cite tests that pytest can collect, so deleting a guard fails the build naming the control that lost its evidence. Every CI run re-establishes the evidence rather than an annual screenshot doing it. PARTIAL until coverage reaches 110 of 110 and the evidence bundle is produced and retained.

**Planned completion.** 2027-01-31

**Implemented by.**

- `.github/workflows/quality-gates.yml`
- `backend/app/core/compliance_catalog.py`
- `backend/compliance/catalog`

**Evidence — automated tests, run on every build.**

- `tests/test_a_claimed_control_is_proved.py`
- `tests/test_every_control_is_registered.py`


### OG-CA-002 — Plans of action are developed to correct deficiencies

**Status.** Partially implemented

**Practices.** 03.12.02

**Also satisfies.** 800-53r5:CA-5, ISO27001:A.5.35

**Owner.** platform-security

**Assessment.** Every `partial` and `absent` control in this catalogue carries an owner and a dated remediation note, and a guard fails the build if one does not — so the POA&M cannot acquire an undated line, which is how a POA&M turns into a list nobody revisits. PARTIAL because the renderer that emits it as a POA&M document does not exist yet.

**Planned completion.** 2026-12-31

**Implemented by.**

- `backend/compliance/catalog`

**Evidence — automated tests, run on every build.**

- `tests/test_every_control_is_registered.py`


### OG-CA-003 — A system security plan is developed, documented and periodically updated

**Status.** Partially implemented

**Practices.** 03.12.04

**Also satisfies.** 800-53r5:PL-2, ISO27001:A.5.1

**Owner.** platform-security

**Assessment.** The catalogue holds the control narratives an SSP is made of, per deployment profile. Missing: the renderer, and the parts of an SSP that are not control narratives — system description, boundary diagram, data flows, interconnections. The boundary in particular blocks several other controls (OG-AC-010) and is not this repository's to decide.

**Planned completion.** 2027-01-31

**Implemented by.**

- `backend/compliance/catalog`

**Evidence — automated tests, run on every build.**

- `tests/test_every_control_is_registered.py`


### OG-CA-004 — Controls are periodically assessed for effectiveness

**Status.** Organizational (not satisfiable by code)

**Practices.** 03.12.01

**Also satisfies.** 800-53r5:CA-2, ISO27001:A.5.35, SOC2:CC4.1

**Owner.** organisation

**Why this is not a code control.** An assessment is performed BY someone, against a scope, with an opinion at the end. The automated evidence here is an input to that — it is not a substitute for it, and a catalogue that marked its own controls "assessed" because its tests passed would be grading its own homework.

**Assessment.** Needs a scheduled internal assessment and, for CMMC L2, a C3PAO. The evidence bundle is designed to make that assessment cheap rather than to replace it.

**Planned completion.** 2027-03-31


---

## 03.13 — System and Communications Protection

### OG-SC-001 — Network communications are denied by default and allowed by exception

**Status.** Implemented

**Practices.** 03.13.01, 03.13.05, 03.13.06

**Also satisfies.** 800-53r5:SC-7, ISO27001:A.8.20, ISO27001:A.8.22, SOC2:CC6.6

**Owner.** platform-infra

**Implementation.** A `default-deny-all` NetworkPolicy on the namespace plus 29 per-workload allow-lists, and — unusually — the enforcement is tested rather than assumed: the `k8s-netpol` CI job applies them to a real Calico cluster and asserts DENY cases as well as ALLOW, while `check_netpol_coverage.py` fails if any workload in a default-deny namespace lacks both an ingress and an egress policy. The documented caveat is inherited honestly: kind's default CNI ignores NetworkPolicy, so production must run Calico or Cilium for any of this to take effect.

**Implemented by.**

- `infrastructure/k8s/base/ingress.yaml`
- `infrastructure/k8s/database-ha/networkpolicies.yaml`
- `infrastructure/k8s/monitoring/networkpolicies.yaml`

**Evidence — automated tests, run on every build.**

- `tests/test_public_probes_do_not_disclose.py`


### OG-SC-002 — FIPS-validated cryptography is used to protect CUI

**Status.** Partially implemented

**Practices.** 03.13.11

**Also satisfies.** 800-53r5:SC-13, ISO27001:A.8.24

**Owner.** platform-security

**Assessment.** RAISED absent -> partial (FS-748). Two of the three deltas are closed: passwords moved to PBKDF2-HMAC-SHA256 with dual-read migration, and ERP field encryption moved from Fernet (AES-128-CBC, keyed by a bare unsalted SHA-256 — the actual defect) to AES-256-GCM with an HKDF-SHA256-derived per-organisation key. `app/core/secrets.py` was deleted rather than ported: unreachable code whose cipher is not approved is a trap for whoever wires it up next. A guard now fails the build if application code imports passlib, bcrypt or Fernet, or constructs an unapproved hash, cipher or curve. Still PARTIAL for the third delta — the base image. `python:3.11-slim` has no FIPS-validated OpenSSL, so backend, frontend and nginx images must move to UBI9, and a UBI image with FIPS mode OFF looks identical to one with it on, which needs a runtime assertion rather than a static check. The scope was measured before any of it was planned, and most of the inventory was already fine: Ed25519 OTA signing, EC P-256/SHA-256 X.509, HS256 JWTs (HMAC-SHA-256 IS approved — the JWT work is key rotation, a different concern), SHA-256 digests of high-entropy random tokens, and no MD5 or SHA-1 anywhere. Measuring first is what turned "FIPS is absent, everything must change" into three specific deltas.

**Planned completion.** 2027-03-31

**Implemented by.**

- `app/core/password.py`
- `app/services/erp_security.py`

**Evidence — automated tests, run on every build.**

- `tests/test_no_unapproved_primitive_is_reachable.py`
- `tests/test_passwords_use_an_approved_kdf.py`


### OG-SC-003 — Confidentiality of CUI in transit

**Status.** Partially implemented

**Practices.** 03.13.08, 03.13.15

**Also satisfies.** 800-53r5:SC-8, GDPR:Art32.1a, ISO27001:A.8.24, SOC2:CC6.7

**Owner.** platform-infra

**Assessment.** External traffic is TLS-terminated at the ingress with HSTS (1 year, includeSubDomains, preload), and the edge uplink has real mTLS with CA pinning, a TLS 1.2 floor and proof-of-possession request signing. PARTIAL because **in-cluster traffic is plaintext**: `sslmode` appears in no database URL, and Redpanda's internal listener, Redis, Qdrant and SeaweedFS are all unencrypted. Also honest about a live asymmetry the repo already documents — the production backend requires mTLS while the shipped edge-agent StatefulSet leaves `EDGE_REQUIRE_TLS` at a permissive default.

**Planned completion.** 2027-02-28

**Implemented by.**

- `app/middleware/security_headers.py`
- `edge-agent/opsgrid_agent/security/mtls.py`
- `edge-agent/opsgrid_agent/security/request_signing.py`
- `infrastructure/k8s/base/ingress.yaml`

**Evidence — automated tests, run on every build.**

- `tests/test_broker_cert.py`
- `tests/test_signed_urls.py`


### OG-SC-004 — Confidentiality of CUI at rest

**Status.** Partially implemented

**Practices.** 03.13.16

**Also satisfies.** 800-53r5:SC-28, GDPR:Art32.1a, ISO27001:A.8.24, SOC2:CC6.7

**Owner.** platform-infra

**Assessment.** RAISED absent -> partial (FS-749). The sharpest instance is closed: the edge store-and-forward buffer now encrypts payloads with AES-256-GCM under an HKDF-derived device key, so a gateway that is stolen, captured or returned as an RMA unit does not surrender up to 24 hours of readings to `strings buffer.db`. `BUFFER_ENCRYPTION_REQUIRED=true` refuses to start without a key rather than buffering CUI in the clear. Application-layer rather than SQLCipher on purpose — `cryptography` is already an agent dependency and cannot fail to build on an ARM gateway in the field, where a native extension can. The stated limits, which are asserted in tests rather than left implied: it defends the DISK, not a running process (an attacker with code execution reads the key file as the agent does), and metadata columns stay in the clear because the buffer orders and prunes by them. Still PARTIAL for the cloud side: nothing encrypts data at rest. The database storage class carries no encryption annotation and no KMS reference; there is no TDE and no column encryption outside the audit hash. Field-level encryption exists as a class (`ERPSecurityManager`) with **zero call sites**, so it protects nothing today. The finding that matters most is at the edge: the store-and-forward buffer is **unencrypted SQLite on the device**, so in a deployment where CUI telemetry is buffered during a comms outage it sits in cleartext on hardware that can be physically captured. That is the scenario the air-gapped and tactical profiles exist for, and it is the strongest argument for SQLCipher on the buffer ahead of the cloud-side work.

**Planned completion.** 2027-02-28

**Implemented by.**

- `app/services/erp_security.py`
- `edge-agent/opsgrid_agent/buffer/encryption.py`
- `edge-agent/opsgrid_agent/buffer/store_forward.py`

**Evidence — automated tests, run on every build.**

- `tests/test_no_unapproved_primitive_is_reachable.py`


### OG-SC-005 — Cryptographic keys are established and managed

**Status.** Partially implemented

**Practices.** 03.13.10

**Also satisfies.** 800-53r5:SC-12, ISO27001:A.8.24

**Owner.** platform-security

**Assessment.** There is real key management for device PKI — an internal CA issuing 30-day certificates with expiry alerting — and OTA artifacts are Ed25519-signed. PARTIAL for the application's own keys: `JWT_SECRET_KEY` is a single symmetric secret with no `kid`, no key ring and no rotation path, so rotating it invalidates every live session at once. Kubernetes offers two complete secret-provisioning paths (Sealed Secrets, External Secrets) and **neither is referenced by any kustomization or workflow**, so provisioning is an undocumented manual act per environment.

**Planned completion.** 2027-02-28

**Implemented by.**

- `app/services/agent_signing.py`
- `app/services/edge_ca.py`
- `app/utils/signed_urls.py`
- `infrastructure/k8s/secrets`

**Evidence — automated tests, run on every build.**

- `tests/test_edge_enrollment.py`
- `tests/test_signed_urls.py`


### OG-SC-006 — User functionality is separated from system management functionality

**Status.** Partially implemented

**Practices.** 03.13.03, 03.13.04

**Also satisfies.** 800-53r5:SC-2, 800-53r5:SC-4

**Owner.** platform-security

**Assessment.** Administrative routes are gated by role and admin surfaces are separate paths, but they share one application, one process and one origin with user functionality — separation is by authorisation, not by architecture. Resource isolation between tenants is strong (RLS); resource isolation between privilege levels is not a thing this design has.

**Planned completion.** 2027-03-31

**Implemented by.**

- `app/api/user_management.py`
- `app/middleware/rbac.py`

**Evidence — automated tests, run on every build.**

- `tests/test_rbac.py`
- `tests/test_route_auth_walk.py`


### OG-SC-007 — Session authenticity is protected

**Status.** Partially implemented

**Practices.** 03.13.09

**Also satisfies.** 800-53r5:SC-10, ISO27001:A.8.5

**Owner.** platform-security

**Assessment.** Connections terminate at token expiry and sessions are revocable immediately, but there is no inactivity-based termination (the same gap as OG-AC-005/OG-AC-006). CSRF middleware exists and is disabled by default, with a documented rationale — Bearer tokens rather than cookies — which is sound and should be written into the SSP rather than left as a code comment.

**Planned completion.** 2027-01-31

**Implemented by.**

- `app/core/session.py`
- `app/middleware/csrf.py`

**Evidence — automated tests, run on every build.**

- `tests/test_auth_sessions.py`


### OG-SC-008 — Mobile code, collaborative computing devices and VoIP

**Status.** Partially implemented

**Practices.** 03.13.12, 03.13.13, 03.13.14

**Also satisfies.** 800-53r5:SC-15, 800-53r5:SC-18, 800-53r5:SC-19

**Owner.** platform-security

**Assessment.** Mobile code is controlled by a Content-Security-Policy — which still permits `unsafe-inline` and `unsafe-eval` for the Swagger UI, and that exception should be scoped to the docs route rather than applied globally. The build-config guard is genuine mobile-code control of a different kind: after the 2026-08-15 supply-chain compromise put an obfuscated dropper in `postcss.config.js`, no frontend build config may gain the ability to spawn a process or open a socket. There are no collaborative computing devices and no VoIP in this system; that is an argument to record in the boundary document, not a control to build.

**Planned completion.** 2027-03-31

**Implemented by.**

- `app/middleware/security_headers.py`
- `backend/tests/test_build_configs_are_not_executable_payloads.py`

**Evidence — automated tests, run on every build.**

- `tests/test_build_configs_are_not_executable_payloads.py`


### OG-SC-009 — Architectural and engineering principles promote effective information security

**Status.** Partially implemented

**Practices.** 03.13.02

**Also satisfies.** 800-53r5:SA-8, ISO27001:A.8.27

**Owner.** platform-security

**Assessment.** Unusually well evidenced for this practice: 250 numbered method rules, each written after a specific defect and indexed by a guard, plus architectural invariants enforced as tests rather than as review conventions (no SQL string interpolation, no naive UTC, no handler taking its tenant from the body). PARTIAL because there is no threat model or data-flow trust-boundary document — the practice asks for security engineering principles applied to a described architecture, and the description is the missing half.

**Planned completion.** 2027-03-31

**Implemented by.**

- `docs/CODING_STANDARDS.md`
- `docs/engineering/sweeps`

**Evidence — automated tests, run on every build.**

- `tests/test_method_rules_are_indexed.py`
- `tests/test_no_two_guards_keep_the_same_list.py`
- `tests/test_sql_is_not_built_by_interpolation.py`


### OG-SC-010 — Split tunnelling is prevented on remote devices

**Status.** Organizational (not satisfiable by code)

**Practices.** 03.13.07

**Also satisfies.** 800-53r5:SC-7(7)

**Owner.** organisation

**Why this is not a code control.** Split tunnelling is a property of a remote endpoint's network stack and VPN configuration. OmniusGrid neither configures nor observes the routing tables of the machines its operators use; claiming this control in an application would be claiming something the application cannot see, let alone enforce.

**Assessment.** Satisfied by endpoint and VPN policy, evidenced in the ISMS. Recorded here because an assessor will ask, and the answer needs an owner.

**Planned completion.** 2027-03-31


---

## 03.14 — System and Information Integrity

### OG-SI-001 — System flaws are identified, reported and corrected in a timely manner

**Status.** Partially implemented

**Practices.** 03.14.01

**Also satisfies.** 800-53r5:SI-2, ISO27001:A.8.8, SOC2:CC7.1

**Owner.** security-operations

**Assessment.** Identification is well covered — blocking dependency and container scanning, error tracking with a triage runbook, and 5,000+ tests that catch regressions before release. The gap is "timely": no SLA defines how quickly a flaw of a given severity must be corrected, so timeliness is currently whatever the next release happens to be. Same missing decision as OG-RA-002.

**Planned completion.** 2027-01-31

**Implemented by.**

- `.github/workflows/quality-gates.yml`
- `app/middleware/error_tracking.py`
- `docs/runbooks/error-triage.md`

**Evidence — automated tests, run on every build.**

- `tests/test_ci_gate_count_is_accurate.py`
- `tests/test_error_triage_sample_redaction_realdb.py`


### OG-SI-002 — Protection from malicious code

**Status.** Partially implemented

**Practices.** 03.14.02, 03.14.04, 03.14.05

**Also satisfies.** 800-53r5:SI-3, ISO27001:A.8.7

**Owner.** security-operations

**Assessment.** There is no anti-malware product, and adding one to an immutable read-only-rootfs container would be theatre. What genuinely applies is here and is unusually specific, because this repository was actually attacked: after the 2026-08-15 supply-chain compromise put an obfuscated blockchain-C2 dropper in `frontend/postcss.config.js`, a guard now fails the build if any frontend build config gains the ability to spawn a process or open a socket, and a second guard requires every `.gitignore` entry to explain what it hides — because the same commit added three bare filenames there to keep the attacker's tooling out of `git status`. Trivy scans images and filesystems for known malicious and vulnerable content on every run. PARTIAL because the boundary argument — why signature-based AV is not the right control for this architecture — is not written down, and an assessor will not accept it as folklore.

**Planned completion.** 2027-02-28

**Implemented by.**

- `.github/workflows/quality-gates.yml`
- `backend/tests/test_build_configs_are_not_executable_payloads.py`
- `infrastructure/k8s/base/namespace.yaml`

**Evidence — automated tests, run on every build.**

- `tests/test_build_configs_are_not_executable_payloads.py`
- `tests/test_gitignore_hides_nothing_unexplained.py`


### OG-SI-003 — Security alerts and advisories are monitored and acted upon

**Status.** Partially implemented

**Practices.** 03.14.03

**Also satisfies.** 800-53r5:SI-5, ISO27001:A.5.6, SOC2:CC7.2

**Owner.** security-operations

**Assessment.** ~57 alert rules including `AuthBruteForceSuspected`, `AuthFailureRatioHigh`, `AuditWriteFailing` and `EdgeAgentCertExpiryApproaching`, routed by severity to PagerDuty and Slack — and the rules are unit-tested with promtool rather than merely written, which is rarer than it should be. PARTIAL on the advisory half: nothing subscribes to vendor or CISA advisories, and there is no defined path from an advisory to an action.

**Planned completion.** 2027-02-28

**Implemented by.**

- `infra/prometheus/alerts.yml`
- `infrastructure/k8s/monitoring/alertmanager.yaml`

**Evidence — automated tests, run on every build.**

- `tests/test_ci_gate_count_is_accurate.py`


### OG-SI-004 — Systems are monitored to detect attacks and unauthorised use

**Status.** commercial-cloud: Partially implemented; gov-cloud: Partially implemented; on-prem: Partially implemented; air-gapped: Not implemented

**Practices.** 03.14.06, 03.14.07

**Also satisfies.** 800-53r5:SI-4, ISO27001:A.8.16, SOC2:CC7.2

**Owner.** security-operations

**Assessment.** Authentication anomalies are alerted on and every request carries a correlation id into structured logs. Three real gaps: there is **no IDS/IPS** (the deleted SOC 2 document claimed one), **log aggregation is not deployed to Kubernetes** — Loki exists in docker-compose only, so in a cluster the logs are whatever the node keeps — and there is no SIEM, so nothing correlates across components. `air-gapped` is `absent` rather than `partial`: with no uplink, alerts reach a Prometheus that nobody is scraping, which is the same problem the DDIL workstream records for local alarms.

**Planned completion.** 2027-02-28

**Implemented by.**

- `app/middleware/audit.py`
- `app/middleware/request_context.py`
- `infra/prometheus/alerts.yml`

**Evidence — automated tests, run on every build.**

- `tests/test_audit_sensitive_operations.py`

