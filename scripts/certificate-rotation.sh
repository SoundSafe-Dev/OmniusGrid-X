#!/bin/bash
# Certificate Rotation Automation Script
# Rotates mTLS certificates with 90-day cycle

set -e

# Configuration
CERT_DIR="/certs"
BACKUP_DIR="/certs/backups"
CERT_VALIDITY_DAYS=90
ALERT_EMAIL="security@omniusgrid.com"
LOG_FILE="/var/log/certificate-rotation.log"

# Certificate file paths
CA_CERT="${CERT_DIR}/ca.crt"
CA_KEY="${CERT_DIR}/ca.key"
SERVER_CERT="${CERT_DIR}/server.crt"
SERVER_KEY="${CERT_DIR}/server.key"
CLIENT_CERT="${CERT_DIR}/edge-client.crt"
CLIENT_KEY="${CERT_DIR}/edge-client.key"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$LOG_FILE"
}

# Error handling
error_exit() {
    log "${RED}ERROR: $1${NC}"
    exit 1
}

# Check if certificate will expire soon (within 7 days)
check_cert_expiry() {
    local cert_file=$1
    local cert_name=$2
    
    if [ ! -f "$cert_file" ]; then
        log "${YELLOW}WARNING: $cert_name not found${NC}"
        return 1
    fi
    
    # Get expiry date
    expiry_date=$(openssl x509 -enddate -noout -in "$cert_file" | cut -d= -f2)
    expiry_epoch=$(date -d "$expiry_date" +%s)
    current_epoch=$(date +%s)
    days_until_expiry=$(( ($expiry_epoch - $current_epoch) / 86400 ))
    
    log "$cert_name expires in $days_until_expiry days"
    
    if [ $days_until_expiry -le 7 ]; then
        log "${YELLOW}WARNING: $cert_name will expire soon ($days_until_expiry days)${NC}"
        return 0
    elif [ $days_until_expiry -le 0 ]; then
        log "${RED}ERROR: $cert_name has already expired${NC}"
        return 0
    else
        return 1
    fi
}

# Backup existing certificates
backup_certificates() {
    log "Backing up existing certificates..."
    
    mkdir -p "$BACKUP_DIR"
    local backup_timestamp=$(date '+%Y%m%d_%H%M%S')
    local backup_path="${BACKUP_DIR}/backup_${backup_timestamp}"
    
    mkdir -p "$backup_path"
    
    for cert in "$CA_CERT" "$CA_KEY" "$SERVER_CERT" "$SERVER_KEY" "$CLIENT_CERT" "$CLIENT_KEY"; do
        if [ -f "$cert" ]; then
            cp "$cert" "$backup_path/"
            log "Backed up $(basename $cert)"
        fi
    done
    
    log "Certificates backed up to $backup_path"
}

# Generate new CA certificate (if needed)
generate_ca() {
    log "Generating new CA certificate..."
    
    # Check if CA exists
    if [ -f "$CA_CERT" ] && [ -f "$CA_KEY" ]; then
        log "CA certificate already exists, skipping generation"
        return 0
    fi
    
    # Generate CA private key
    openssl genrsa -out "$CA_KEY" 4096 || error_exit "Failed to generate CA key"
    
    # Generate CA certificate
    openssl req -new -x509 -days 3650 -key "$CA_KEY" -out "$CA_CERT" \
        -subj "/C=US/ST=State/L=City/O=OmniusGrid/OU=Security/CN=OmniusGrid-CA" \
        || error_exit "Failed to generate CA certificate"
    
    log "CA certificate generated successfully"
}

# Generate server certificate
generate_server_cert() {
    log "Generating server certificate..."
    
    # Generate private key
    openssl genrsa -out "$SERVER_KEY" 4096 || error_exit "Failed to generate server key"
    
    # Generate CSR
    openssl req -new -key "$SERVER_KEY" -out "/tmp/server.csr" \
        -subj "/C=US/ST=State/L=City/O=OmniusGrid/OU=Security/CN=*.omniusgrid.com" \
        || error_exit "Failed to generate server CSR"
    
    # Sign with CA
    openssl x509 -req -in "/tmp/server.csr" -CA "$CA_CERT" -CAkey "$CA_KEY" \
        -CAcreateserial -out "$SERVER_CERT" -days $CERT_VALIDITY_DAYS \
        || error_exit "Failed to sign server certificate"
    
    # Clean up
    rm -f "/tmp/server.csr"
    
    log "Server certificate generated successfully"
}

# Generate client certificate
generate_client_cert() {
    log "Generating client certificate..."
    
    # Generate private key
    openssl genrsa -out "$CLIENT_KEY" 4096 || error_exit "Failed to generate client key"
    
    # Generate CSR
    openssl req -new -key "$CLIENT_KEY" -out "/tmp/client.csr" \
        -subj "/C=US/ST=State/L=City/O=OmniusGrid/OU=Security/CN=edge-client" \
        || error_exit "Failed to generate client CSR"
    
    # Sign with CA
    openssl x509 -req -in "/tmp/client.csr" -CA "$CA_CERT" -CAkey "$CA_KEY" \
        -CAcreateserial -out "$CLIENT_CERT" -days $CERT_VALIDITY_DAYS \
        || error_exit "Failed to sign client certificate"
    
    # Clean up
    rm -f "/tmp/client.csr"
    
    log "Client certificate generated successfully"
}

# Verify certificates
verify_certificates() {
    log "Verifying certificates..."
    
    # Verify server certificate
    if [ -f "$SERVER_CERT" ] && [ -f "$CA_CERT" ]; then
        openssl verify -CAfile "$CA_CERT" "$SERVER_CERT" || error_exit "Server certificate verification failed"
        log "Server certificate verified"
    fi
    
    # Verify client certificate
    if [ -f "$CLIENT_CERT" ] && [ -f "$CA_CERT" ]; then
        openssl verify -CAfile "$CA_CERT" "$CLIENT_CERT" || error_exit "Client certificate verification failed"
        log "Client certificate verified"
    fi
}

# Reload services (graceful reload)
reload_services() {
    log "Reloading services with new certificates..."
    
    # Reload backend service
    if systemctl is-active --quiet omniusgrid-backend; then
        systemctl reload omniusgrid-backend || error_exit "Failed to reload backend service"
        log "Backend service reloaded"
    fi
    
    # Reload edge agent service
    if systemctl is-active --quiet omniusgrid-edge-agent; then
        systemctl reload omniusgrid-edge-agent || error_exit "Failed to reload edge agent service"
        log "Edge agent service reloaded"
    fi
    
    log "All services reloaded successfully"
}

# Send notification
send_notification() {
    local message=$1
    
    log "Sending notification: $message"
    
    # Send email (requires mail command)
    if command -v mail &> /dev/null; then
        echo "$message" | mail -s "Certificate Rotation Alert" "$ALERT_EMAIL"
    fi
    
    # Could also integrate with Slack, PagerDuty, etc.
}

# Main rotation function
rotate_certificates() {
    log "Starting certificate rotation..."
    
    # Check if rotation is needed
    rotation_needed=false
    
    if check_cert_expiry "$SERVER_CERT" "Server Certificate"; then
        rotation_needed=true
    fi
    
    if check_cert_expiry "$CLIENT_CERT" "Client Certificate"; then
        rotation_needed=true
    fi
    
    if [ "$rotation_needed" = false ]; then
        log "No certificates need rotation at this time"
        return 0
    fi
    
    log "Certificate rotation required"
    
    # Backup existing certificates
    backup_certificates
    
    # Generate CA if needed
    generate_ca
    
    # Generate new certificates
    generate_server_cert
    generate_client_cert
    
    # Verify certificates
    verify_certificates
    
    # Set proper permissions
    chmod 600 "$CA_KEY" "$SERVER_KEY" "$CLIENT_KEY"
    chmod 644 "$CA_CERT" "$SERVER_CERT" "$CLIENT_CERT"
    
    # Reload services
    reload_services
    
    # Send notification
    send_notification "Certificate rotation completed successfully on $(hostname)"
    
    log "Certificate rotation completed successfully"
}

# Main execution
main() {
    log "=========================================="
    log "Certificate Rotation Script Started"
    log "=========================================="
    
    # Check if running as root
    if [ "$EUID" -ne 0 ]; then
        error_exit "This script must be run as root"
    fi
    
    # Check if openssl is installed
    if ! command -v openssl &> /dev/null; then
        error_exit "openssl is not installed"
    fi
    
    # Create certificate directory if it doesn't exist
    mkdir -p "$CERT_DIR"
    
    # Run rotation
    rotate_certificates
    
    log "=========================================="
    log "Certificate Rotation Script Completed"
    log "=========================================="
}

# Run main function
main "$@"
