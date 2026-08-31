# An engineer leaves

**Why this exists.** The compliance catalogue's own 03.09.02 note said the technical half
of deprovisioning was available and *"what is missing is the process that triggers it on
the day someone leaves"*. On 2026-08-28 someone left and there was still no process. This
is that process, written the day it was needed rather than the day it was due.

---

## Constraints — read these before doing anything

The commands below are unremarkable. These are not, and they change what you do.

| | |
|---|---|
| **There are TWO remotes.** | `origin` (SoundSafe-ai/Omnius-Grid) and `backup` (SoundSafe-Dev/OmniusGrid-X). Access removed from one is access retained on the other, and the mirror is the one people forget. Several developers' work has only ever existed on `backup`. |
| **Branch protection is not enabled.** | `docs/runbooks/branch-protection.md` records it as outstanding: it needs an org admin token nobody has applied. So **any credential with write access can force-push any branch**, which is not hypothetical here — it is exactly what happened on 2026-08-15 across all 17 branches. A departing engineer's token is that threat model wearing a familiar name. |
| **Revoking the account does not revoke the session.** | Access tokens carry a `sid` bound to a live session, so deactivation propagates across replicas immediately — but **refresh tokens last 7 days**. The `revoked_tokens` denylist is checked on every request and is what actually ends a session early. Deactivating the user and walking away leaves a week-long window. |
| **Deactivate; do not delete.** | The audit trail references the user. Deletion severs the history that proves what they did, which is the opposite of what an offboarding is for. `is_active = false` is the operation. |
| **You cannot lock out the last admin.** | OG-IA-006's guard refuses to deactivate the final active admin of an organisation. If the departing engineer is that admin, promote someone first — the deactivation will refuse, and it is right to. |
| **Their API keys grant nothing, because nothing accepts them.** | Verified 2026-08-31: `/api/v1/api-keys` mints, lists and revokes keys, and **no request path anywhere authenticates with one**. `APIKey` appears only in its own CRUD module and in `models.py`. So key revocation is not on the critical path today — and the day someone wires API-key auth, it becomes the most important line on this page. `test_the_offboarding_runbook_is_accurate.py` fails when that happens. |
| **Their branches stay.** | Merged work is history. CI still matches `hridyansh/**` and friends, so anything pushed to one is still gated. Deleting them to "clean up" destroys the provenance of merged commits. |

---

## The steps

### 1. Access, within the hour

- [ ] Remove the collaborator/member from **both** GitHub organisations.
- [ ] Revoke any PAT, deploy key or SSH key issued to them. `docs/runbooks/leaked-key-rotation.md` covers the rotation mechanics.
- [ ] If they held an org admin role, review the audit log for force-pushes and branch-protection changes since their notice date, not since their last day.
- [ ] Revoke cloud/registry credentials (GHCR, S3/SeaweedFS, any vendor console).

### 2. The application account, same day

- [ ] `is_active = false` on their user. Promote a replacement admin first if OG-IA-006 refuses.
- [ ] Add their outstanding refresh tokens to `revoked_tokens`. Deactivation alone leaves up to 7 days.
- [ ] Reassign anything they own in-app that has an owner field.

### 3. The part everyone forgets: work that has stopped having an owner

Ownership is recorded in more places than the org chart, and a departure turns *deferrals*
into *orphans*. A deferral says "somebody else will decide"; when that somebody leaves, it
silently becomes "nobody will decide" while still reading as a considered position.

- [ ] `grep -ril "<their name>" --exclude-dir=.git --exclude-dir=node_modules .`
- [ ] Reassign every register entry that names them. In August 2026 that was four:
      `test_dispatched_commands_have_a_handler.py`, both repos'
      `test_no_new_unreachable_modules.py`, and two idempotency exemptions held on
      nothing but the lane name.
- [ ] Update `README.md`'s subsystem-ownership table and
      `backend/compliance/catalog/owners.yaml`.
- [ ] Read their stashes before dropping them (`git stash list`). Once they are gone,
      "nobody is left to ask" is not the same finding as "nothing in them is wanted", and
      only the second justifies deleting someone's work.

### 4. Record it

- [ ] Note the date and what was revoked. 03.09.02 is assessed as an organizational
      control: the evidence that it works is a record that it happened.

---

## What this page cannot do

It cannot revoke anything. Every step above needs a human with an admin credential, and
the repository has no path to one — which is the same constraint that has left branch
protection unapplied since 2026-08-15. If that is still true when you read this, the first
step of any offboarding is finding the person who can perform it, and that search is the
part that takes hours.
