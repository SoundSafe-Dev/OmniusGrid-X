# Runbook — committed private key (HAMAD_IDE.pem)

**Status: rotation OUTSTANDING. History purge deferred (needs coordination).**

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
