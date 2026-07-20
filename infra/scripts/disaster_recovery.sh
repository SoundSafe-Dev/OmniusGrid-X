#!/bin/bash
# Disaster Recovery Scripts for OmniusGrid

# disaster_recovery.sh - Master script for backup and restore operations

set -euo pipefail

# Configuration — must match infra/pgbackrest/pgbackrest.conf, which is what the
# backup CronJob actually runs with. All three of these disagreed with it:
# STANZA was the Patroni CLUSTER name (omniusgrid-db) rather than the pgBackRest
# stanza (opsgrid-db), and the bucket and repo path were omniusgrid* against a
# repository configured as opsgrid*. Every command in this script therefore
# addressed a stanza and repository that do not exist.
STANZA="opsgrid-db"
S3_BUCKET="opsgrid-backups"
REPO_PATH="/pgbackrest/opsgrid"
LOG_FILE="/var/log/omniusgrid/disaster_recovery.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

log() {
    echo -e "${GREEN}[$(date +'%Y-%m-%d %H:%M:%S')]${NC} $1" | tee -a "$LOG_FILE"
}

warn() {
    echo -e "${YELLOW}[$(date +'%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1" | tee -a "$LOG_FILE"
}

error() {
    echo -e "${RED}[$(date +'%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" | tee -a "$LOG_FILE"
    exit 1
}

# Function: Initialize stanza
cmd_init() {
    log "Initializing pgBackRest stanza..."
    pgbackrest --stanza=$STANZA stanza-create
    log "Stanza created successfully"
}

# Function: Full backup
cmd_backup() {
    log "Starting full backup..."
    pgbackrest --stanza=$STANZA backup --type=full
    log "Full backup completed"
    
    # Verify backup
    log "Verifying backup integrity..."
    pgbackrest --stanza=$STANZA verify
    log "Backup verification passed"
}

# Function: Incremental backup
cmd_backup_incremental() {
    log "Starting incremental backup..."
    pgbackrest --stanza=$STANZA backup --type=incr
    log "Incremental backup completed"
}

# Function: Check backup status
cmd_check() {
    log "Checking backup status..."
    pgbackrest --stanza=$STANZA check
    pgbackrest --stanza=$STANZA info
}

# Function: List backups
cmd_list() {
    log "Listing available backups..."
    pgbackrest --stanza=$STANZA info
}

# Function: Restore to latest
cmd_restore() {
    log "Starting restore to latest backup..."
    
    # Stop database (requires manual intervention or orchestrator)
    warn "Database will be stopped for restore. Continue? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        error "Restore cancelled by user"
    fi
    
    # Restore
    pgbackrest --stanza=$STANZA restore \
        --delta \
        --process-max=4
    
    log "Restore completed. Start database to complete recovery."
}

# Function: Point-in-time recovery
cmd_pitr() {
    local target_time=$1
    
    log "Starting point-in-time recovery to: $target_time"
    
    warn "This will restore database to $target_time. Continue? (y/n)"
    read -r response
    if [[ ! "$response" =~ ^[Yy]$ ]]; then
        error "PITR cancelled by user"
    fi
    
    # Restore with target time
    pgbackrest --stanza=$STANZA restore \
        --type=time \
        --target="$target_time" \
        --target-action=promote \
        --delta
    
    log "PITR completed. Database will recover to target time on startup."
}

# Function: Emergency restore (drop table scenario)
cmd_emergency_restore() {
    local backup_set=$1
    
    error "EMERGENCY RESTORE PROCEDURE"
    warn "This will DESTROY current database and restore from backup!"
    warn "Backup set: $backup_set"
    warn "Continue? Type 'EMERGENCY RESTORE' to proceed:"
    read -r response
    
    if [[ "$response" != "EMERGENCY RESTORE" ]]; then
        error "Emergency restore cancelled"
    fi
    
    log "Starting emergency restore from backup set: $backup_set"
    
    # Force restore
    pgbackrest --stanza=$STANZA restore \
        --set=$backup_set \
        --force \
        --delta \
        --process-max=4
    
    log "Emergency restore completed"
}

# Function: Archive WAL manually
cmd_archive_push() {
    log "Pushing WAL segments to archive..."
    pgbackrest --stanza=$STANZA archive-push
}

# Function: Verify S3 connectivity
cmd_test_s3() {
    log "Testing S3 connectivity..."
    aws s3 ls s3://$S3_BUCKET$REPO_PATH/ || error "S3 connectivity failed"
    log "S3 connectivity verified"
}

# Function: Backup metrics for monitoring
cmd_metrics() {
    log "Collecting backup metrics..."
    
    # Get last backup time
    last_backup=$(pgbackrest --stanza=$STANZA info --output=json | \
        jq -r '.[0].backup[-1].timestamp.stop' 2>/dev/null || echo "unknown")
    
    # Get backup size
    backup_size=$(pgbackrest --stanza=$STANZA info --output=json | \
        jq -r '.[0].backup[-1].info.size' 2>/dev/null || echo "0")
    
    echo "last_backup_time $last_backup"
    echo "last_backup_size_bytes $backup_size"
}

# Main command dispatcher
case "${1:-help}" in
    init)
        cmd_init
        ;;
    backup|full)
        cmd_backup
        ;;
    incremental|incr)
        cmd_backup_incremental
        ;;
    check)
        cmd_check
        ;;
    list|info)
        cmd_list
        ;;
    restore)
        cmd_restore
        ;;
    pitr)
        cmd_pitr "$2"
        ;;
    emergency)
        cmd_emergency_restore "$2"
        ;;
    archive-push)
        cmd_archive_push
        ;;
    test-s3)
        cmd_test_s3
        ;;
    metrics)
        cmd_metrics
        ;;
    help|*)
        cat << EOF
Disaster Recovery Script for OpsGrid

Usage: $0 <command> [options]

Commands:
    init                    - Initialize pgBackRest stanza
    backup (full)           - Perform full backup
    incremental (incr)        - Perform incremental backup
    check                   - Check backup configuration and status
    list (info)             - List available backups
    restore                 - Restore to latest backup
    pitr <timestamp>        - Point-in-time recovery to specific time
                            Format: "2026-01-15 14:30:00"
    emergency <backup-set>  - Emergency restore (DESTROYS current data!)
    archive-push            - Manually push WAL segments
    test-s3                 - Test S3 connectivity
    metrics                 - Output backup metrics for monitoring
    help                    - Show this help message

Examples:
    # Full backup
    $0 backup

    # Restore to specific point in time
    $0 pitr "2026-01-15 14:30:00"

    # Emergency restore from specific backup
    $0 emergency 20260115-020000F

Environment Variables:
    AWS_ACCESS_KEY_ID         - S3 access key
    AWS_SECRET_ACCESS_KEY     - S3 secret key
    PGBACKREST_PASSPHRASE     - Backup encryption passphrase

EOF
        ;;
esac
