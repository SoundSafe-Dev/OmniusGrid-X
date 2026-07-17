#!/usr/bin/env bash
# Bare-metal installer for the OmniusGrid edge agent (FS-36).
# Usage: sudo ./install.sh
# Installs the full driver set (dependencies come from requirements.txt,
# the same list the Docker image uses — one source of truth).
set -euo pipefail

INSTALL_DIR=/opt/opsgrid-agent
STATE_DIR=/var/lib/opsgrid-agent
CONF_DIR=/etc/opsgrid-agent
SRC_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

echo ">> creating opsgrid system user"
id -u opsgrid >/dev/null 2>&1 || useradd --system --home-dir "$STATE_DIR" --shell /usr/sbin/nologin opsgrid

echo ">> creating directories"
mkdir -p "$INSTALL_DIR" "$STATE_DIR" "$CONF_DIR"
chown opsgrid:opsgrid "$STATE_DIR"

echo ">> installing into a venv at $INSTALL_DIR/venv"
python3 -m venv "$INSTALL_DIR/venv"
"$INSTALL_DIR/venv/bin/pip" install --upgrade pip >/dev/null
"$INSTALL_DIR/venv/bin/pip" install "$SRC_DIR"

echo ">> installing config template + systemd unit"
if [[ ! -f "$CONF_DIR/agent.env" ]]; then
  cat > "$CONF_DIR/agent.env" <<'ENV'
# OmniusGrid edge agent environment. See edge-agent/.env.example for all knobs.
ORGANIZATION_ID=
AGENT_ID=
REDPANDA_URL=
CLOUD_URL=
EDGE_BOOTSTRAP_TOKEN=
# Production posture:
# EDGE_REQUIRE_TLS=true
# KAFKA_SECURITY_PROTOCOL=SSL
# EDGE_REQUIRE_EXPLICIT_SOURCES=true
# ENROLLMENT_CA_FINGERPRINT=<sha256 hex of the CA cert DER>
ENV
  chmod 640 "$CONF_DIR/agent.env"
fi
cp "$SRC_DIR/deploy/opsgrid-agent.service" /etc/systemd/system/opsgrid-agent.service
systemctl daemon-reload

echo ">> done. Configure $CONF_DIR/agent.env, then: systemctl enable --now opsgrid-agent"
