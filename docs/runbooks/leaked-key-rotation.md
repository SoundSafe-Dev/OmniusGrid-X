# Runbook — committed private key (HAMAD_IDE.pem)

**Status: local copy DELETED 2026-08-18. Revocation still outstanding. History purge still
deferred — and now sequenced behind branch protection, see the bottom of this file.**

## Update 2026-08-18

The working-tree copy was deleted. Its identity is recorded here first, because deleting the
file removes the only convenient way to work out *which* key to revoke:

| | |
|---|---|
| Type | RSA 3072-bit, no comment |
| SHA256 fingerprint | `SHA256:IpnNhMDmGEJkIbo8olbuPEIBU6SbFx+pNJSDfNzRc/w` |
| Public key prefix | `ssh-rsa AAAAB3NzaC1yc2EAAAADAQABAAABgQCy…` |
| Blob still in history | `52ce7526c89cdcfc139d0a520ca0ca9d1d3af58c` (2,494 bytes) |

Match that fingerprint against AWS EC2 key pairs, any `~/.ssh/authorized_keys` on hosts this
key reached, and any CI or IDE configuration. **Deleting the local copy did not revoke
anything** — a private key is compromised the moment it is published, and the file on this
machine was the least dangerous copy of it. It was not in `~/.ssh/config` and not loaded in
any ssh-agent, so nothing on this machine was actively using it.

The blob remains reachable from `acc35f92`. Anyone with clone access can still read the key,
which is why revocation is the fix and the purge is only cleanup.

## What happened

An RSA private key was committed as `HAMAD_IDE.pem` in `acc35f92`
("feat(frontend): implement complete UI…") and untracked in `8333b888`
("chore(security): untrack committed private key (FS-01)").

**Untracking removed it from the working tree, not from history.** It is still
retrievable today by anyone with clone access:

```sh
git cat-file -p acc35f92:HAMAD_IDE.pem
```

`.gitignore` now excludes `*.pem`, and a blocking `repo-hygiene` gate in
`quality-gates.yml` fails the build if any `*.pem`/`*.key`/`*.p12`/`*.pfx` is
ever tracked again. Neither of those helps with the copy already in history.

## Step 1 — Rotate the key (do this first; it is the actual fix)

Rotation is what closes the exposure. Once the old key is revoked, the copy
sitting in git history is worthless, which is why the purge below can be
scheduled rather than rushed.

1. Identify where the public half is trusted — SSH `authorized_keys` on any
   host, a cloud key pair, a CI/CD deploy key, an IDE remote-development host.
2. Generate a replacement and install the new public key.
3. Remove the old public key from every `authorized_keys` / trusted-keys list.
4. Verify the old key is rejected:
   ```sh
   ssh -i /path/to/HAMAD_IDE.pem -o IdentitiesOnly=yes <host>   # must fail
   ```
5. Review access logs on those hosts for use of the old key.
6. Delete the local copy at the repo root (it is untracked, so this is safe):
   ```sh
   rm HAMAD_IDE.pem
   ```

## Step 2 — Purge from history (deferred — requires team coordination)

**Do not run this unilaterally.** `acc35f92` is an ancestor of essentially every
branch on both remotes:

```
hamad/converged-pre-main, hamad/fixed-sprints, main,
hridyansh/{integration, integration-erp, tenant-isolation-middleware,
            package-renaming-fix, edge-command-dispatch, edge-agent-retry-logic},
htreinen, HARSH-CONTRIBUTION, feature/gemma-correlation-ai,
feature/RAG-Compliance-Doc-Pipeline
```

…on **both** `origin` (SoundSafe-ai/Omnius-Grid) and `backup`
(SoundSafe-Dev/OmniusGrid-X). A purge rewrites every one of those SHAs, so every
developer must re-clone or hard-reset; anyone who pushes from a stale clone
silently reintroduces the old history.

When the window is agreed:

1. Announce it; have everyone push outstanding work first.
2. Back up both remotes (mirror clone) before touching anything.
3. Rewrite:
   ```sh
   git clone --mirror <origin-url> omnius-mirror && cd omnius-mirror
   git filter-repo --invert-paths --path HAMAD_IDE.pem
   git push --force --all && git push --force --tags
   ```
4. Repeat against the `backup` remote (or re-push the same rewritten mirror to
   both so the two stay identical).
5. Ask GitHub Support to expire cached views of the old objects — a force-push
   does not immediately purge them from the API/UI.
6. Everyone re-clones. Confirm:
   ```sh
   git log --all --oneline -- HAMAD_IDE.pem    # must be empty
   ```

This is also the natural window to shrink `.git` (~278MB), since the tracked
`frontend/node_modules` blobs removed in the untracking commit are still in
history for the same reason this key is.

## Related

- `.github/workflows/quality-gates.yml` — `repo-hygiene` job (blocking)
- FS-190 — external secrets (SealedSecrets/ESO); secrets are currently created
  by hand via `kubectl` with no rotation story.


---

## Sequencing note added 2026-08-18 — the purge now conflicts with branch protection

`main` is protected on both remotes as of 2026-08-18, with `allow_force_pushes: false` and
`enforce_admins: true` (see `SECURITY-INCIDENT-2026-08-15.md`).

A `git filter-repo` purge rewrites every commit SHA on every branch and requires a
**force-push of all refs to both remotes** — which protection now refuses, by design. So the
purge is no longer just "coordinate with the team"; it is:

1. Announce, and get every lane to stop pushing and note their branch heads.
2. Temporarily set `allow_force_pushes: true` on `main` for both repositories.
3. Run the purge from a known-good clone, preserving `refs/rescue/*`.
4. Force-push all refs to both remotes.
5. **Re-enable protection immediately**, and verify with the command in
   `docs/runbooks/branch-protection.md`.
6. Every developer reclones. Their existing clones are unmergeable afterwards — every SHA
   changes, so a `pull` produces a duplicated history rather than a fast-forward.

**Weigh that against what it buys.** The purge does not reduce the exposure at all: the key
has been public in history since April and must be treated as compromised regardless.
Revoking it is what closes the risk. The purge removes an artefact an assessor would find and
ask about — worth doing, and worth doing on a planned day rather than opportunistically,
because step 2 deliberately re-opens the exact hole that this month's incident went through.

`git-filter-repo` is installed on the primary development machine, so the tooling is not the
blocker.
