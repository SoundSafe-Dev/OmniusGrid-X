# Sealed Secrets

Encrypts the platform's secrets into `SealedSecret` custom resources that are
**safe to commit** — only the in-cluster controller holds the private key that
can decrypt them into real `Secret`s. Self-contained: no external secret store.

## Install the controller

```bash
helm repo add sealed-secrets https://bitnami-labs.github.io/sealed-secrets
helm install sealed-secrets sealed-secrets/sealed-secrets \
  -n kube-system

# CLI (macOS):
brew install kubeseal
```

## Seal and apply

```bash
cp secrets.env.example secrets.env    # fill in REAL values — gitignored
./seal.sh                             # writes encrypted ./sealed/*.yaml
kubectl apply -f ./sealed/            # controller decrypts into real Secrets
```

`seal.sh` builds each Secret with the exact name + keys the workloads mount (see
the table in [`../README.md`](../README.md)) and pipes it through `kubeseal`. The
`./sealed/` output is encrypted against **this cluster's** controller key, so:

- **Commit `sealed/`** — it is ciphertext, useless without the cluster key.
- **Never commit `secrets.env`** — `.gitignore` blocks it and any `*.env`.
- Sealed secrets are cluster-specific; re-seal for a new cluster (or back up and
  restore the controller's sealing key).

## Rotation

Edit `secrets.env`, re-run `./seal.sh`, re-apply `sealed/`. The controller
updates the underlying Secret; restart the consuming pods if they read it at
boot.
