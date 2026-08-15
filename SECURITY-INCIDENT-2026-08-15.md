# SECURITY INCIDENT — 2026-08-15 — READ BEFORE YOU PULL

**Every branch on `origin` (SoundSafe-ai/Omnius-Grid) was force-pushed to a malicious commit
at 10:29 PDT on 2026-08-15. All 17 branches have been restored. Your branch was affected.**

If you pulled or fetched from `origin` between **10:29 PDT and 12:05 PDT on 2026-08-15**, or
if you are not certain, treat your checkout as compromised and read this in full.

---

## Do this first

1. **Do not run anything in `frontend/`** on a checkout taken in that window — not
   `npm run dev`, not `npm run build`, not `npx vitest`, not `npm install`. The payload lived
   in a file Node executes on *every* one of those.
2. **Check your working copy:**
   ```bash
   wc -c frontend/postcss.config.js     # must be 80
   grep -c createRequire frontend/postcss.config.js   # must be 0
   ```
   80 bytes and zero matches means you are clean.
3. **If it is not 80 bytes**, do not "fix" the file and carry on. Assume the machine executed
   it. Rotate anything that machine holds — GitHub tokens and SSH keys, npm tokens, cloud and
   registry credentials, and any `.env` — then reclone from scratch.
4. **Reclone rather than pull.** The refs are restored, but a clean clone removes any doubt:
   ```bash
   git clone https://github.com/SoundSafe-ai/Omnius-Grid.git
   ```

---

## What happened

A single commit, `8d1b548d`, was force-pushed over **all 17 branches** on `origin` — every
developer branch, plus `main`. It impersonated an existing commit: it reused the subject and
author date of a real 2026-08-10 commit (`fix(ci): the coverage ratchet…`), so a glance at
`git log` showed nothing new. Its **committer** date is the giveaway: 2026-08-15 10:29:53.

It changed exactly two files.

**`frontend/postcss.config.js` — 80 bytes to 31,473 bytes.** Added
`createRequire(import.meta.url)` (the shim an ESM module needs before it can `require()` Node
builtins) followed by an obfuscated blob. Extracted indicators:

- `child_process` — arbitrary command execution
- `eth_blockNumber`, `eth_getBlockByNumber`, `eth_getTransaction*` against public Ethereum RPC
  endpoints (`drpc.org`, `1rpc.io`) — the command-and-control address is read **from the
  blockchain**, which is why there is no domain to block
- an address fragment `0xa322E5f3`, and `POST` to `:443/0x/cl`, `:443/0x/ls`

`postcss.config.js` is the ideal host for this: four lines nobody has read since the project
started, excluded from every sweep that covers `src/`, and executed by Node on every build,
dev server and test run.

**`.gitignore` — concealment.** Three entries added:
`temp_auto_push.bat`, `temp_interactive_push.bat`, `branch_structure.json`. Those are the
attacker's own tooling, hidden from `git status`. The `.bat` extension says the push came from
a **Windows** machine, and `temp_auto_push` explains how all 17 branches moved at once.

## What was NOT affected

- **The `backup` remote (SoundSafe-Dev/OmniusGrid-X) was never touched.** No branch there
  contains the payload; every `postcss.config.js` is 80 bytes.
- **No source code, test, migration or dependency was altered.** The commit touched two files
  and nothing else — verified by diff against the pre-attack tree.
- **No work was lost.** All 17 branches are restored to their exact pre-attack commits.

## Restoration

Every branch was restored from its pre-attack tip, preserved locally before any recovery began
(`refs/rescue/*`). All 34 branches across both remotes have since been verified to carry the
legitimate 80-byte `postcss.config.js`.

| branch | restored to |
|---|---|
| `main` | `cf2feba4` |
| `hamad/converged-pre-main` | `8d092bdf`, plus that day's work on top |
| `HARSH-CONTRIBUTION` | `84c91ead` |
| `feature/gemma-correlation-ai` | `c25ee452` |
| `alex` | `bddcb5a4` |
| `htreinen` | `2d7fb330` |
| `feature/RAG-Compliance-Doc-Pipeline` | `daa2a7ad` |
| `rag-rewrite` | `0bfc9cb7` |
| `hridyansh/*` (7 branches) | each to its own pre-attack tip |
| `hamad/fixed-sprints`, `hamad/integrate-hridyansh` | `2d77c60e`, `4e4fb4a6` |

## What still needs a human

**The push used valid credentials for this repository.** Restoring the branches does not
address that. Until the credential is found and rotated, the same push can happen again:

- Rotate GitHub PATs, SSH keys and any CI tokens with write access to `SoundSafe-ai`.
- Review the repository's Settings → Deploy keys, and Organization → Installed GitHub Apps,
  for anything unrecognised.
- Check the audit log (`Organization → Settings → Audit log`) around **2026-08-15 10:29 PDT**
  for the actor behind the force-push.
- Enable branch protection on `main` and the integration branch — this attack is exactly what
  "block force pushes" prevents.
- The Windows machine that ran `temp_auto_push.bat` is the strongest lead. If you know which
  machine that is, treat it as compromised.

## What now guards against a repeat

`backend/tests/test_build_configs_are_not_executable_payloads.py` fails the build if any
frontend build config gains the ability to spawn a process or open a socket
(`child_process`, `createRequire`, `eval`, `Function`, `atob`, sockets, DNS), or grows past
16 KB. Verified against the real payload: it fails on both axes.

That is a narrow guard for a narrow class — arbitrary code hidden in a file nobody reads. It
is not a substitute for branch protection or for rotating the credential.
