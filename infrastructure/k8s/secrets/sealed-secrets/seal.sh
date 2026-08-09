#!/usr/bin/env bash
# Seal the platform secrets into SealedSecret manifests that are SAFE to commit.
#
# Reads plaintext values from a local env file (default: ./secrets.env, which is
# gitignored), builds the corresponding Kubernetes Secrets, and pipes each
# through `kubeseal` so only the in-cluster sealed-secrets controller can decrypt
# them. The encrypted output goes to ./sealed/ — commit that, never the plaintext.
#
# Usage:
#   cp secrets.env.example secrets.env   # fill in real values (gitignored)
#   ./seal.sh                            # writes ./sealed/*.yaml
#   kubectl apply -f ./sealed/
#
# Requires: kubeseal + kubectl configured against the target cluster (the
# controller's public cert is fetched from it).
set -euo pipefail

NS="${NAMESPACE:-omniusgrid}"
ENV_FILE="${1:-secrets.env}"
OUT_DIR="sealed"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "error: $ENV_FILE not found. Copy secrets.env.example and fill it in." >&2
  exit 1
fi
command -v kubeseal >/dev/null || { echo "error: kubeseal not installed" >&2; exit 1; }

# shellcheck disable=SC1090
set -a; source "$ENV_FILE"; set +a
mkdir -p "$OUT_DIR"

# seal <secret-name> <kubectl-create-secret-args...>
seal() {
  local name="$1"; shift
  kubectl create secret generic "$name" -n "$NS" "$@" \
      --dry-run=client -o yaml \
    | kubeseal --format yaml > "$OUT_DIR/$name.yaml"
  echo "sealed $OUT_DIR/$name.yaml"
}

seal database-credentials \
  --from-literal=url="$DATABASE_URL" \
  --from-literal=username="$DATABASE_USERNAME" \
  --from-literal=password="$DATABASE_PASSWORD" \
  --from-literal=database="$DATABASE_NAME"

seal jwt-secret        --from-literal=secret="$JWT_SECRET"
seal signed-url-secret --from-literal=secret="$SIGNED_URL_SECRET"

# s3config.json is derived from the same access/secret keys.
S3CONFIG=$(cat <<JSON
{"identities":[{"name":"omniusgrid","credentials":[{"accessKey":"$S3_ACCESS_KEY","secretKey":"$S3_SECRET_KEY"}],"actions":["Admin","Read","Write","List","Tagging"]}]}
JSON
)
seal s3-credentials \
  --from-literal=access-key="$S3_ACCESS_KEY" \
  --from-literal=secret-key="$S3_SECRET_KEY" \
  --from-literal=s3config.json="$S3CONFIG"

seal alertmanager-secrets \
  --from-literal=slack-webhook-url="$SLACK_WEBHOOK_URL" \
  --from-literal=pagerduty-service-key="$PAGERDUTY_SERVICE_KEY"

seal backup-credentials \
  --from-literal=aws-access-key-id="$BACKUP_AWS_ACCESS_KEY_ID" \
  --from-literal=aws-secret-access-key="$BACKUP_AWS_SECRET_ACCESS_KEY" \
  --from-literal=region="$BACKUP_REGION" \
  --from-literal=bucket="$BACKUP_BUCKET"

# CNPG app role uses the basic-auth type.
kubectl create secret generic cnpg-app-credentials -n "$NS" \
    --type=kubernetes.io/basic-auth \
    --from-literal=username="$CNPG_APP_USERNAME" \
    --from-literal=password="$CNPG_APP_PASSWORD" \
    --dry-run=client -o yaml \
  | kubeseal --format yaml > "$OUT_DIR/cnpg-app-credentials.yaml"
echo "sealed $OUT_DIR/cnpg-app-credentials.yaml"

seal cnpg-backup-credentials \
  --from-literal=ACCESS_KEY_ID="$CNPG_BACKUP_ACCESS_KEY_ID" \
  --from-literal=ACCESS_SECRET_KEY="$CNPG_BACKUP_ACCESS_SECRET_KEY"

echo "Done. Commit $OUT_DIR/ — it is encrypted. NEVER commit $ENV_FILE."

# FS-514. Three secrets the workloads consume were sealed by nothing and had no
# ExternalSecret either — so an operator who ran this script and applied its output still
# hit CreateContainerConfigError on a secret no path had ever mentioned.
seal app-secrets \
  --from-literal=edge-bootstrap-token="$EDGE_BOOTSTRAP_TOKEN" \
  --from-literal=erp-encryption-key="$ERP_ENCRYPTION_KEY" \
  --from-literal=geotab-webhook-secret="$GEOTAB_WEBHOOK_SECRET"

seal smtp-credentials \
  --from-literal=host="$SMTP_HOST" \
  --from-literal=port="$SMTP_PORT" \
  --from-literal=username="$SMTP_USERNAME" \
  --from-literal=password="$SMTP_PASSWORD" \
  --from-literal=from-address="$SMTP_FROM_ADDRESS"

seal grafana-admin --from-literal=admin-password="$GRAFANA_ADMIN_PASSWORD"
