# 📢 Team update — `main` has been updated (2026-07-17)

*(Safe to delete this file once you've read it — it's a one-time heads-up.)*

The convergence branch has been promoted to **`main`**. Everyone now has the
updated **backend** (real-mode auth, edge telemetry chain, observability +
error-triage, contract hardening, real-DB CI guards, k8s egress policies) and
the refreshed **frontend / UI + brand system**.

## Please update your branch off the new base

From your feature branch:

```bash
git fetch origin
git merge origin/main        # or: git rebase origin/main
```

*(On the SoundSafe-Dev remote instead? Same thing with your remote — `main` is
in parity on both origin and backup.)*

## ⚠️ Reinstall deps after pulling — required, not optional

```bash
# backend: python-jose was swapped for PyJWT — the app won't import without it
pip install -r backend/requirements.txt

# frontend: brand assets + deps changed
cd frontend && npm install
```

If your local backend throws `ModuleNotFoundError: No module named 'jwt'`, that's
the PyJWT swap — the reinstall fixes it.

## Workflow going forward

Keep working on your own branches as normal. New work keeps landing on
`hamad/converged-pre-main` and gets promoted to `main` periodically — just pull
`main` whenever you want the latest integrated base. No change to how you branch.

— Hamad
