# Runbook — branch protection

**Status: NOT ENABLED, and this is the open half of a real incident.**

On 2026-08-15 every branch on `origin` — all 17, including `main` — was force-pushed to a
single malicious commit. The branches were restored and the payload is guarded against
(`backend/tests/test_build_configs_are_not_executable_payloads.py`), but the two things that
would have *prevented* it are still open: the credential used has never been identified, and
**branch protection has never been enabled**.

This matters beyond the incident. `OG-CM-002` in the control catalogue covers NIST SP 800-171
**3.4.3** (track, review and approve changes) and **3.4.5** (enforce access restrictions
associated with change). There are 23 blocking CI jobs, which is a strong answer to "are
changes reviewed" — and without branch protection none of them is *enforced*, because any
credential with write access can push straight past all of them. The force-push is the proof
that this is not hypothetical.

That is why `OG-CM-002` is `partial` and not `implemented`, and why its remediation date is
one of the earliest in the catalogue.

---

## What to run

Requires an admin token for the `SoundSafe-ai` org. Neither `gh` nor an admin credential is
available to the development environment, which is why this is a runbook rather than a
script that has already run.

```bash
# Both remotes carry the same branches; protect both.
for repo in SoundSafe-ai/Omnius-Grid SoundSafe-Dev/OmniusGrid-X; do
  for branch in main hamad/converged-pre-main; do
    gh api -X PUT "repos/$repo/branches/$branch/protection" \
      -H "Accept: application/vnd.github+json" \
      -F "required_status_checks[strict]=true" \
      -F "required_status_checks[contexts][]=backend-full" \
      -F "required_status_checks[contexts][]=supply-chain" \
      -F "required_status_checks[contexts][]=k8s-manifests" \
      -F "enforce_admins=true" \
      -F "required_pull_request_reviews[required_approving_review_count]=1" \
      -F "required_pull_request_reviews[dismiss_stale_reviews]=true" \
      -F "restrictions=" \
      -F "allow_force_pushes=false" \
      -F "allow_deletions=false"
  done
done
```

`allow_force_pushes=false` is the line that would have stopped 2026-08-15. `enforce_admins=true`
matters as much: an attacker with an admin credential is exactly the case here, and protection
that admins can bypass protects against accidents rather than against attackers.

### Verify

```bash
gh api repos/SoundSafe-ai/Omnius-Grid/branches/main/protection \
  --jq '{force_push: .allow_force_pushes.enabled, admins: .enforce_admins.enabled,
         reviews: .required_pull_request_reviews.required_approving_review_count}'
# expected: {"force_push": false, "admins": true, "reviews": 1}
```

---

## Before you run it

**This changes how the team pushes.** Direct pushes to the protected branches stop working,
including the integration branch several lanes currently push to. Announce it, and expect the
first day to be noisy. That cost is the control working.

**It does not close the incident.** The credential is still unidentified, so it may still
have write access to other branches, other repositories, or the org itself. Branch protection
narrows what that credential can do to the two protected branches; it does not revoke it. The
remaining items are in `SECURITY-INCIDENT-2026-08-15.md` — rotate PATs, SSH keys and CI
tokens, review deploy keys and installed GitHub Apps, and read the org audit log around
2026-08-15 10:29 PDT.

**Then update the catalogue.** `OG-CM-002` moves toward `implemented` once protection is on
AND verified by the command above; paste the verification output into the evidence bundle so
the claim is evidenced rather than asserted. Until then the control stays `partial`, which is
the honest state — and this file exists so that state has a reason attached rather than
looking like an oversight.
