# External Secrets Operator (ESO)

Materializes the platform's in-cluster `Secret`s from a central backing store
(Vault / AWS Secrets Manager / GCP Secret Manager). **No secret value ever lives
in git** — only the references in `externalsecrets.yaml`.

## Install ESO

```bash
helm repo add external-secrets https://charts.external-secrets.io
helm install external-secrets external-secrets/external-secrets \
  -n external-secrets --create-namespace
```

## Configure

1. **Provision the backing store** with the secrets under an `omniusgrid/*`
   layout (see the table in [`../README.md`](../README.md) for keys). Example for
   Vault KV v2:

   ```bash
   vault kv put secret/omniusgrid/database \
     url='postgresql+asyncpg://omniusgrid:...@omniusgrid-db-rw:5432/omniusgrid' \
     username=omniusgrid password='...' database=omniusgrid
   vault kv put secret/omniusgrid/jwt secret='...'
   vault kv put secret/omniusgrid/s3 access-key='...' secret-key='...'
   # ...and so on for signed-url, alertmanager, backup, cnpg-app, cnpg-backup
   ```

2. **Edit `secretstore.example.yaml`** for your provider and auth, save it as
   `secretstore.yaml`, then apply:

   ```bash
   kubectl apply -f secretstore.yaml
   kubectl apply -f externalsecrets.yaml
   ```

ESO reconciles each `ExternalSecret` into the Secret the workloads mount
(`database-credentials`, `jwt-secret`, …) and refreshes hourly. `s3-credentials`
and `cnpg-app-credentials` use `target.template` so the derived `s3config.json`
and the `kubernetes.io/basic-auth` type are produced from the stored values.

## Rotation

Rotate in the backing store; ESO picks it up at the next `refreshInterval`
(1h here — lower it for faster propagation). No workload edits, no re-apply.
