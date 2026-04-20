#!/bin/bash
#
# Certificate Generation Script for OmniusGrid mTLS
# Generates CA, server, and client certificates for secure communication
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CERTS_DIR="${SCRIPT_DIR}/../certs"
CONFIG_DIR="${SCRIPT_DIR}/../infrastructure/tls"

# Configuration
CA_DAYS=3650        # 10 years for CA
SERVER_DAYS=365   # 1 year for server certs
CLIENT_DAYS=365   # 1 year for client certs
KEY_SIZE=4096

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log_info() {
    echo -e "${GREEN}[INFO]${NC} $1"
}

log_warn() {
    echo -e "${YELLOW}[WARN]${NC} $1"
}

log_error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

# Create directories
mkdir -p "${CERTS_DIR}"/{ca,server,client}
mkdir -p "${CONFIG_DIR}"

log_info "Certificate directories created"

# Generate OpenSSL CA config
cat > "${CONFIG_DIR}/ca.cnf" << 'EOF'
[ ca ]
default_ca = CA_default

[ CA_default ]
dir               = ./certs/ca
certs             = $dir
crl_dir           = $dir/crl
database          = $dir/index.txt
new_certs_dir     = $dir
serial            = $dir/serial
private_key       = $dir/ca.key
certificate       = $dir/ca.crt
crl               = $dir/crl.pem
crlnumber         = $dir/crlnumber
crl_extensions    = crl_ext
default_crl_days  = 30
default_md        = sha256
name_opt          = ca_default
cert_opt          = ca_default
default_days      = 365
preserve          = no
policy            = policy_strict

[ policy_strict ]
countryName             = match
stateOrProvinceName     = match
organizationName        = match
organizationalUnitName  = optional
commonName              = supplied
emailAddress            = optional

[ req ]
default_bits        = 4096
distinguished_name  = req_distinguished_name
string_mask         = utf8only
default_md          = sha256
x509_extensions     = v3_ca

[ req_distinguished_name ]
countryName                     = Country Name (2 letter code)
countryName_default             = US
stateOrProvinceName             = State or Province Name
stateOrProvinceName_default     = California
localityName                    = Locality Name
localityName_default            = San Francisco
organizationName                = Organization Name
organizationName_default        = OmniusGrid
organizationalUnitName          = Organizational Unit Name
organizationalUnitName_default  = Manufacturing
commonName                      = Common Name
commonName_default              = OmniusGrid CA
emailAddress                    = Email Address
emailAddress_default            = admin@omniusgrid.local

[ v3_ca ]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:true, pathlen:0
keyUsage = critical, digitalSignature, cRLSign, keyCertSign

[ v3_intermediate_ca ]
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid:always,issuer
basicConstraints = critical, CA:true, pathlen:0
keyUsage = critical, digitalSignature, cRLSign, keyCertSign

[ server_cert ]
basicConstraints = CA:FALSE
nsCertType = server
nsComment = "OpenSSL Generated Server Certificate"
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer:always
keyUsage = critical, digitalSignature, keyEncipherment
extendedKeyUsage = serverAuth
subjectAltName = @alt_names

[ client_cert ]
basicConstraints = CA:FALSE
nsCertType = client
nsComment = "OpenSSL Generated Client Certificate"
subjectKeyIdentifier = hash
authorityKeyIdentifier = keyid,issuer:always
keyUsage = critical, digitalSignature
extendedKeyUsage = clientAuth

[ crl_ext ]
authorityKeyIdentifier=keyid:always

[ alt_names ]
DNS.1 = localhost
DNS.2 = *.omniusgrid.local
DNS.3 = *.omniusgrid.svc.cluster.local
IP.1 = 127.0.0.1
IP.2 = ::1
EOF

log_info "OpenSSL configuration created"

# Initialize CA database files
touch "${CERTS_DIR}/ca/index.txt"
echo 1000 > "${CERTS_DIR}/ca/serial"

# ============================================================================
# GENERATE CA CERTIFICATE
# ============================================================================
log_info "Generating CA certificate..."

openssl req -x509 -new \
    -config "${CONFIG_DIR}/ca.cnf" \
    -newkey rsa:${KEY_SIZE} \
    -nodes \
    -keyout "${CERTS_DIR}/ca/ca.key" \
    -out "${CERTS_DIR}/ca/ca.crt" \
    -days ${CA_DAYS} \
    -sha256 \
    -extensions v3_ca

# Set restrictive permissions
chmod 600 "${CERTS_DIR}/ca/ca.key"
chmod 644 "${CERTS_DIR}/ca/ca.crt"

log_info "CA certificate generated: ${CERTS_DIR}/ca/ca.crt"

# ============================================================================
# GENERATE SERVER CERTIFICATE
# ============================================================================
log_info "Generating server certificate..."

# Server private key
openssl genrsa -out "${CERTS_DIR}/server/server.key" ${KEY_SIZE}

# Server CSR
openssl req -new \
    -config "${CONFIG_DIR}/ca.cnf" \
    -key "${CERTS_DIR}/server/server.key" \
    -out "${CERTS_DIR}/server/server.csr" \
    -subj "/C=US/ST=California/L=San Francisco/O=OmniusGrid/OU=Manufacturing/CN=omniusgrid-server"

# Sign server cert with CA
openssl ca -batch \
    -config "${CONFIG_DIR}/ca.cnf" \
    -policy policy_strict \
    -in "${CERTS_DIR}/server/server.csr" \
    -out "${CERTS_DIR}/server/server.crt" \
    -days ${SERVER_DAYS} \
    -md sha256 \
    -extensions server_cert

# Create server PEM bundle (cert + key)
cat "${CERTS_DIR}/server/server.crt" "${CERTS_DIR}/server/server.key" > "${CERTS_DIR}/server/server.pem"

chmod 600 "${CERTS_DIR}/server/server.key"
chmod 600 "${CERTS_DIR}/server/server.pem"
chmod 644 "${CERTS_DIR}/server/server.crt"

log_info "Server certificate generated: ${CERTS_DIR}/server/server.crt"

# ============================================================================
# GENERATE CLIENT CERTIFICATES
# ============================================================================
log_info "Generating client certificates..."

# Function to generate client cert
generate_client_cert() {
    local client_name=$1
    local cn=$2
    
    log_info "Generating client certificate for ${client_name}..."
    
    # Client directory
    local client_dir="${CERTS_DIR}/client/${client_name}"
    mkdir -p "${client_dir}"
    
    # Client private key
    openssl genrsa -out "${client_dir}/client.key" ${KEY_SIZE}
    
    # Client CSR
    openssl req -new \
        -config "${CONFIG_DIR}/ca.cnf" \
        -key "${client_dir}/client.key" \
        -out "${client_dir}/client.csr" \
        -subj "/C=US/ST=California/L=San Francisco/O=OmniusGrid/OU=Manufacturing/CN=${cn}"
    
    # Sign client cert with CA
    openssl ca -batch \
        -config "${CONFIG_DIR}/ca.cnf" \
        -policy policy_strict \
        -in "${client_dir}/client.csr" \
        -out "${client_dir}/client.crt" \
        -days ${CLIENT_DAYS} \
        -md sha256 \
        -extensions client_cert
    
    # Create client PEM bundle (cert + key)
    cat "${client_dir}/client.crt" "${client_dir}/client.key" > "${client_dir}/client.pem"
    
    # Export PKCS12 for browser import
    openssl pkcs12 -export \
        -in "${client_dir}/client.crt" \
        -inkey "${client_dir}/client.key" \
        -certfile "${CERTS_DIR}/ca/ca.crt" \
        -out "${client_dir}/client.p12" \
        -name "${cn}" \
        -passout pass:omniusgrid
    
    chmod 600 "${client_dir}/client.key"
    chmod 600 "${client_dir}/client.pem"
    chmod 644 "${client_dir}/client.crt"
    
    log_info "Client certificate generated: ${client_dir}/client.crt"
}

# Generate client certificates
generate_client_cert "edge-agent-001" "edge-agent-001.omniusgrid.local"
generate_client_cert "backend-api" "backend-api.omniusgrid.local"
generate_client_cert "admin-user" "admin@omniusgrid.local"

# ============================================================================
# GENERATE REDPANDA/KAFKA CERTIFICATES
# ============================================================================
log_info "Generating Redpanda/Kafka certificates..."

mkdir -p "${CERTS_DIR}/redpanda"

# Redpanda broker cert
openssl genrsa -out "${CERTS_DIR}/redpanda/broker.key" ${KEY_SIZE}

openssl req -new \
    -config "${CONFIG_DIR}/ca.cnf" \
    -key "${CERTS_DIR}/redpanda/broker.key" \
    -out "${CERTS_DIR}/redpanda/broker.csr" \
    -subj "/C=US/ST=California/L=San Francisco/O=OmniusGrid/OU=Manufacturing/CN=redpanda.omniusgrid.local"

openssl ca -batch \
    -config "${CONFIG_DIR}/ca.cnf" \
    -policy policy_strict \
    -in "${CERTS_DIR}/redpanda/broker.csr" \
    -out "${CERTS_DIR}/redpanda/broker.crt" \
    -days ${SERVER_DAYS} \
    -md sha256 \
    -extensions server_cert

chmod 600 "${CERTS_DIR}/redpanda/broker.key"
chmod 644 "${CERTS_DIR}/redpanda/broker.crt"

log_info "Redpanda certificate generated"

# ============================================================================
# CREATE KUBERNETES SECRETS MANIFEST
# ============================================================================
log_info "Creating Kubernetes secrets manifest..."

cat > "${CERTS_DIR}/../infrastructure/k8s/secrets/tls-secrets.yaml" << EOF
---
# CA Certificate Secret
apiVersion: v1
kind: Secret
metadata:
  name: ca-certificate
  namespace: omniusgrid
type: Opaque
data:
  ca.crt: $(base64 -w 0 "${CERTS_DIR}/ca/ca.crt")
---
# Backend API Server Certificate
apiVersion: v1
kind: Secret
metadata:
  name: backend-tls
  namespace: omniusgrid
type: kubernetes.io/tls
data:
  tls.crt: $(base64 -w 0 "${CERTS_DIR}/server/server.crt")
  tls.key: $(base64 -w 0 "${CERTS_DIR}/server/server.key")
---
# Edge Agent Client Certificate
apiVersion: v1
kind: Secret
metadata:
  name: edge-agent-client-cert
  namespace: omniusgrid
type: Opaque
data:
  client.crt: $(base64 -w 0 "${CERTS_DIR}/client/edge-agent-001/client.crt")
  client.key: $(base64 -w 0 "${CERTS_DIR}/client/edge-agent-001/client.key")
---
# Redpanda Broker Certificate
apiVersion: v1
kind: Secret
metadata:
  name: redpanda-tls
  namespace: omniusgrid
type: kubernetes.io/tls
data:
  tls.crt: $(base64 -w 0 "${CERTS_DIR}/redpanda/broker.crt")
  tls.key: $(base64 -w 0 "${CERTS_DIR}/redpanda/broker.key")
EOF

log_info "Kubernetes secrets manifest created"

# ============================================================================
# SUMMARY
# ============================================================================
echo ""
echo "============================================================"
echo "  Certificate Generation Complete"
echo "============================================================"
echo ""
echo "Certificate locations:"
echo "  CA Certificate:     ${CERTS_DIR}/ca/ca.crt"
echo "  Server Certificate: ${CERTS_DIR}/server/server.crt"
echo "  Client Certs:       ${CERTS_DIR}/client/*/"
echo "  Redpanda Certs:     ${CERTS_DIR}/redpanda/"
echo ""
echo "Kubernetes Secrets:   ${CERTS_DIR}/../infrastructure/k8s/secrets/tls-secrets.yaml"
echo ""
echo "To verify certificates:"
echo "  openssl x509 -in ${CERTS_DIR}/ca/ca.crt -text -noout"
echo "  openssl verify -CAfile ${CERTS_DIR}/ca/ca.crt ${CERTS_DIR}/server/server.crt"
echo ""
echo "To enable mTLS:"
echo "  1. Set MTLS_ENABLED=True in backend/app/core/config.py"
echo "  2. Mount certs in docker-compose.yml or K8s manifests"
echo "  3. Restart services"
echo ""
echo "============================================================"
