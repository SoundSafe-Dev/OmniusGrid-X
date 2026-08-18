<!-- GENERATED FROM backend/compliance/catalog/ — DO NOT EDIT.
     Regenerate with `make compliance`. Edits here are overwritten and, worse, are
     invisible to the guards that keep control claims tied to tests. Change the
     catalogue instead. -->

# Statement of Applicability — ISO/IEC 27001 Annex A

Derived from the Annex A references carried by each OmniusGrid control. **This is a partial SoA and says so**: it lists the Annex A controls this system's technical controls map to, not the full Annex A set. A complete SoA must state applicability for every Annex A control including those excluded, with justification, and that requires the ISMS scope — which is an organizational decision, not a repository one. Generating a full-looking SoA from partial data would be the same class of claim that got two documents deleted in FS-745.

| Annex A | Applicable | Implementing control | Status (commercial cloud) |
|---|---|---|---|
| A.5.1 | Yes | OG-CA-003 — A system security plan is developed, documented and periodically updated | Partially implemented |
| A.5.15 | Yes | OG-AC-001 — Access requires an authenticated principal; anonymous access is refused | Implemented |
| A.5.15 | Yes | OG-AC-002 — Every request is bound to its tenant, and the tenant is never taken from the request | Implemented |
| A.5.16 | Yes | OG-IA-001 — Users, services and devices are identified before access is granted | Implemented |
| A.5.16 | Yes | OG-IA-006 — Identifier reuse and inactivity management | Partially implemented |
| A.5.17 | Yes | OG-IA-003 — Credentials are stored and transmitted only in cryptographically protected form | Partially implemented |
| A.5.17 | Yes | OG-IA-005 — Password composition, reuse and lifetime policy | Partially implemented |
| A.5.19 | Yes | OG-AC-009 — Connections to external systems are verified and controlled | Partially implemented |
| A.5.24 | Yes | OG-IR-001 — An incident handling capability exists — preparation, detection, analysis, containment, recovery | Partially implemented |
| A.5.24 | Yes | OG-IR-003 — The incident response capability is tested | Partially implemented |
| A.5.25 | Yes | OG-IR-002 — Incidents are tracked, documented and reported to designated authorities | Partially implemented |
| A.5.3 | Yes | OG-AC-007 — Separation of duties, and use of non-privileged accounts for non-security functions | Not implemented |
| A.5.35 | Yes | OG-CA-001 — Security controls are monitored continuously for continued effectiveness | Partially implemented |
| A.5.35 | Yes | OG-CA-002 — Plans of action are developed to correct deficiencies | Partially implemented |
| A.5.35 | Yes | OG-CA-004 — Controls are periodically assessed for effectiveness | Organizational (not satisfiable by code) |
| A.5.6 | Yes | OG-SI-003 — Security alerts and advisories are monitored and acted upon | Partially implemented |
| A.5.7 | Yes | OG-RA-003 — Periodic risk assessment | Organizational (not satisfiable by code) |
| A.6.1 | Yes | OG-PS-001 — Personnel screening, and protection during termination and transfer | Organizational (not satisfiable by code) |
| A.6.3 | Yes | OG-AT-001 — Security awareness and role-based training, including insider threat | Organizational (not satisfiable by code) |
| A.6.7 | Yes | OG-AC-008 — Remote access is routed through managed, monitored, encrypted access points | Partially implemented |
| A.6.7 | Yes | OG-PE-002 — Safeguarding at alternate work sites | Organizational (not satisfiable by code) |
| A.7.1 | Yes | OG-PE-001 — Physical access is limited, monitored, logged and managed | Inherited from provider |
| A.7.10 | Yes | OG-MP-002 — Media handling — marking, transport, sanitisation, removable media | Organizational (not satisfiable by code) |
| A.7.13 | Yes | OG-MA-001 — System maintenance, maintenance tools, personnel and nonlocal maintenance | Organizational (not satisfiable by code) |
| A.7.2 | Yes | OG-PE-001 — Physical access is limited, monitored, logged and managed | Inherited from provider |
| A.8.1 | Yes | OG-AC-006 — Session lock after inactivity | Not implemented |
| A.8.1 | Yes | OG-AC-011 — Wireless, mobile device and portable storage controls | Organizational (not satisfiable by code) |
| A.8.13 | Yes | OG-MP-001 — Backup CUI is protected at rest at storage locations | Partially implemented |
| A.8.15 | Yes | OG-AU-001 — Audit records are created for security-relevant operations and retained | Partially implemented |
| A.8.15 | Yes | OG-AU-002 — Every audit record is attributable to an individual user | Implemented |
| A.8.15 | Yes | OG-AU-004 — Audit records are tamper-evident and the evidence can be verified | Partially implemented |
| A.8.15 | Yes | OG-AU-005 — Audit log access is restricted to privileged users and scoped to one tenant | Implemented |
| A.8.15 | Yes | OG-AU-007 — Audit review, analysis and reporting | Not implemented |
| A.8.16 | Yes | OG-SI-004 — Systems are monitored to detect attacks and unauthorised use | Partially implemented |
| A.8.17 | Yes | OG-AU-006 — Audit records carry a synchronised, unambiguous timestamp | Partially implemented |
| A.8.19 | Yes | OG-CM-003 — Least functionality — nonessential functions are restricted or disabled | Partially implemented |
| A.8.2 | Yes | OG-AC-003 — Privileged functions are restricted to a defined role vocabulary | Partially implemented |
| A.8.20 | Yes | OG-SC-001 — Network communications are denied by default and allowed by exception | Implemented |
| A.8.22 | Yes | OG-SC-001 — Network communications are denied by default and allowed by exception | Implemented |
| A.8.24 | Yes | OG-SC-002 — FIPS-validated cryptography is used to protect CUI | Partially implemented |
| A.8.24 | Yes | OG-SC-003 — Confidentiality of CUI in transit | Partially implemented |
| A.8.24 | Yes | OG-SC-004 — Confidentiality of CUI at rest | Partially implemented |
| A.8.24 | Yes | OG-SC-005 — Cryptographic keys are established and managed | Partially implemented |
| A.8.27 | Yes | OG-SC-009 — Architectural and engineering principles promote effective information security | Partially implemented |
| A.8.32 | Yes | OG-CM-002 — Changes are tracked, reviewed and approved before they take effect | Partially implemented |
| A.8.5 | Yes | OG-AC-004 — Unsuccessful logon attempts are limited | Partially implemented |
| A.8.5 | Yes | OG-AC-005 — Sessions terminate on a defined condition and can be revoked immediately | Partially implemented |
| A.8.5 | Yes | OG-IA-002 — Multifactor authentication for privileged and network access | Partially implemented |
| A.8.5 | Yes | OG-SC-007 — Session authenticity is protected | Partially implemented |
| A.8.7 | Yes | OG-SI-002 — Protection from malicious code | Partially implemented |
| A.8.8 | Yes | OG-RA-001 — Vulnerabilities are scanned for continuously and block the build | Implemented |
| A.8.8 | Yes | OG-RA-002 — Vulnerabilities are remediated in accordance with risk | Partially implemented |
| A.8.8 | Yes | OG-SI-001 — System flaws are identified, reported and corrected in a timely manner | Partially implemented |
| A.8.9 | Yes | OG-CM-001 — Configuration is defined in version control and enforced at deploy time | Partially implemented |
