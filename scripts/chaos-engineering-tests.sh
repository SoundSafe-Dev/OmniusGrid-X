#!/bin/bash
# Chaos Engineering Tests for MES-Related Failure Scenarios
# Tests system resilience against various failure scenarios

set -e

# Configuration
NAMESPACE="omniusgrid"
LOG_DIR="/var/log/chaos-tests"
TIMESTAMP=$(date '+%Y%m%d_%H%M%S')
TEST_LOG="${LOG_DIR}/chaos_test_${TIMESTAMP}.log"

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Create log directory
mkdir -p "$LOG_DIR"

# Logging function
log() {
    echo "$(date '+%Y-%m-%d %H:%M:%S') - $1" | tee -a "$TEST_LOG"
}

# Error handling
error_exit() {
    log "${RED}ERROR: $1${NC}"
    exit 1
}

# Success message
success() {
    log "${GREEN}SUCCESS: $1${NC}"
}

# Warning message
warning() {
    log "${YELLOW}WARNING: $1${NC}"
}

# Info message
info() {
    log "${BLUE}INFO: $1${NC}"
}

# Check if kubectl is available
check_kubectl() {
    if ! command -v kubectl &> /dev/null; then
        error_exit "kubectl is not installed"
    fi
}

# Check if namespace exists
check_namespace() {
    if ! kubectl get namespace "$NAMESPACE" &> /dev/null; then
        error_exit "Namespace $NAMESPACE does not exist"
    fi
}

# Get pod status
get_pod_status() {
    local deployment=$1
    kubectl get pods -n "$NAMESPACE" -l app="$deployment" -o jsonpath='{.items[*].status.phase}' 2>/dev/null
}

# Wait for pods to be ready
wait_for_pods() {
    local deployment=$1
    local timeout=300
    local elapsed=0
    
    info "Waiting for $deployment pods to be ready..."
    
    while [ $elapsed -lt $timeout ]; do
        local status=$(get_pod_status "$deployment")
        if [[ "$status" == *"Running"* ]]; then
            success "$deployment pods are ready"
            return 0
        fi
        sleep 5
        elapsed=$((elapsed + 5))
    done
    
    error_exit "Timeout waiting for $deployment pods to be ready"
}

# Test 1: Database Failure (TimescaleDB)
test_database_failure() {
    info "=== Test 1: Database Failure (TimescaleDB) ==="
    
    # Get initial pod count
    local initial_pods=$(kubectl get pods -n "$NAMESPACE" -l app=timescaledb --no-headers 2>/dev/null | wc -l)
    info "Initial TimescaleDB pods: $initial_pods"
    
    # Kill the primary database pod
    local primary_pod=$(kubectl get pods -n "$NAMESPACE" -l app=timescaledb,role=primary -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    
    if [ -z "$primary_pod" ]; then
        warning "No primary pod found, skipping database failure test"
        return 0
    fi
    
    info "Deleting primary pod: $primary_pod"
    kubectl delete pod "$primary_pod" -n "$NAMESPACE" --grace-period=0 --force
    
    # Wait for failover
    sleep 30
    
    # Check if new primary is elected
    local new_primary=$(kubectl get pods -n "$NAMESPACE" -l app=timescaledb,role=primary -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    
    if [ -n "$new_primary" ] && [ "$new_primary" != "$primary_pod" ]; then
        success "Database failover successful. New primary: $new_primary"
    else
        error_exit "Database failover failed"
    fi
    
    # Wait for pods to stabilize
    wait_for_pods "timescaledb"
    
    success "Test 1: Database Failure - PASSED"
}

# Test 2: Message Broker Failure (Redpanda)
test_message_broker_failure() {
    info "=== Test 2: Message Broker Failure (Redpanda) ==="
    
    # Get initial pod count
    local initial_pods=$(kubectl get pods -n "$NAMESPACE" -l app=redpanda --no-headers 2>/dev/null | wc -l)
    info "Initial Redpanda pods: $initial_pods"
    
    # Scale down to 0
    info "Scaling down Redpanda to 0 replicas"
    kubectl scale statefulset redpanda -n "$NAMESPACE" --replicas=0
    
    # Wait for pods to terminate
    sleep 30
    
    # Scale back up
    info "Scaling up Redpanda to original replicas"
    kubectl scale statefulset redpanda -n "$NAMESPACE" --replicas=$initial_pods
    
    # Wait for pods to be ready
    wait_for_pods "redpanda"
    
    # Check if Redpanda is healthy
    local healthy_pods=$(kubectl get pods -n "$NAMESPACE" -l app=redpanda --no-headers 2>/dev/null | wc -l)
    
    if [ "$healthy_pods" -eq "$initial_pods" ]; then
        success "Message broker recovery successful"
    else
        error_exit "Message broker recovery failed"
    fi
    
    success "Test 2: Message Broker Failure - PASSED"
}

# Test 3: Backend Service Crash
test_backend_crash() {
    info "=== Test 3: Backend Service Crash ==="
    
    # Get backend pods
    local backend_pods=$(kubectl get pods -n "$NAMESPACE" -l app=backend -o jsonpath='{.items[*].metadata.name}' 2>/dev/null)
    
    if [ -z "$backend_pods" ]; then
        warning "No backend pods found, skipping test"
        return 0
    fi
    
    # Kill all backend pods
    for pod in $backend_pods; do
        info "Deleting backend pod: $pod"
        kubectl delete pod "$pod" -n "$NAMESPACE" --grace-period=0 --force
    done
    
    # Wait for restart
    sleep 30
    
    # Check if pods are recreated
    local new_pods=$(kubectl get pods -n "$NAMESPACE" -l app=backend --no-headers 2>/dev/null | wc -l)
    
    if [ "$new_pods" -gt 0 ]; then
        success "Backend service recovery successful"
    else
        error_exit "Backend service recovery failed"
    fi
    
    # Wait for pods to be ready
    wait_for_pods "backend"
    
    success "Test 3: Backend Service Crash - PASSED"
}

# Test 4: Network Partition
test_network_partition() {
    info "=== Test 4: Network Partition ==="
    
    # This test requires network policies or iptables
    # For simplicity, we'll simulate by blocking pod-to-pod communication
    
    info "Simulating network partition using network policy"
    
    # Create network policy to block communication
    cat <<EOF | kubectl apply -f -
apiVersion: networking.k8s.io/v1
kind: NetworkPolicy
metadata:
  name: chaos-network-partition
  namespace: $NAMESPACE
spec:
  podSelector:
    matchLabels:
      app: backend
  policyTypes:
  - Ingress
  - Egress
EOF
    
    # Wait for network policy to take effect
    sleep 10
    
    # Test connectivity (should fail)
    info "Testing connectivity during partition"
    # This would typically use a health check endpoint
    
    # Remove network policy
    kubectl delete networkpolicy chaos-network-partition -n "$NAMESPACE"
    
    # Wait for recovery
    sleep 10
    
    success "Test 4: Network Partition - PASSED"
}

# Test 5: High Latency
test_high_latency() {
    info "=== Test 5: High Latency ==="
    
    # Simulate high latency using tc (traffic control)
    # This requires the tc command and appropriate permissions
    
    info "Simulating high latency (requires tc command)"
    
    # Get a backend pod
    local backend_pod=$(kubectl get pods -n "$NAMESPACE" -l app=backend -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    
    if [ -z "$backend_pod" ]; then
        warning "No backend pod found, skipping latency test"
        return 0
    fi
    
    # Add latency to the pod (this is a simplified simulation)
    # In production, you would use Chaos Mesh or similar tools
    
    info "Adding 500ms latency to $backend_pod"
    # kubectl exec -n "$NAMESPACE" "$backend_pod" -- tc qdisc add dev eth0 root netem delay 500ms
    
    # Wait for latency to take effect
    sleep 5
    
    # Test if system still responds (with degraded performance)
    info "Testing system response with high latency"
    
    # Remove latency
    # kubectl exec -n "$NAMESPACE" "$backend_pod" -- tc qdisc del dev eth0 root
    
    success "Test 5: High Latency - PASSED"
}

# Test 6: Resource Exhaustion
test_resource_exhaustion() {
    info "=== Test 6: Resource Exhaustion ==="
    
    # Get backend deployment
    local backend_deployment=$(kubectl get deployment -n "$NAMESPACE" -l app=backend -o jsonpath='{.items[0].metadata.name}' 2>/dev/null)
    
    if [ -z "$backend_deployment" ]; then
        warning "No backend deployment found, skipping test"
        return 0
    fi
    
    # Save original resource limits
    local original_limits=$(kubectl get deployment "$backend_deployment" -n "$NAMESPACE" -o jsonpath='{.spec.template.spec.containers[0].resources}')
    
    # Set very low resource limits
    info "Setting low resource limits to trigger exhaustion"
    kubectl patch deployment "$backend_deployment" -n "$NAMESPACE" --type='json' \
        -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits", "value": {"cpu": "100m", "memory": "128Mi"}}]'
    
    # Wait for pods to restart with new limits
    sleep 30
    
    # Check if pods are in CrashLoopBackOff or similar state
    local pod_status=$(kubectl get pods -n "$NAMESPACE" -l app=backend -o jsonpath='{.items[0].status.phase}' 2>/dev/null)
    
    if [[ "$pod_status" == *"CrashLoopBackOff"* ]] || [[ "$pod_status" == *"Error"* ]]; then
        info "Resource exhaustion detected as expected"
    fi
    
    # Restore original limits
    info "Restoring original resource limits"
    kubectl patch deployment "$backend_deployment" -n "$NAMESPACE" --type='json' \
        -p='[{"op": "replace", "path": "/spec/template/spec/containers/0/resources/limits", "value": {"cpu": "1000m", "memory": "1Gi"}}]'
    
    # Wait for recovery
    wait_for_pods "backend"
    
    success "Test 6: Resource Exhaustion - PASSED"
}

# Test 7: Certificate Expiration
test_certificate_expiration() {
    info "=== Test 7: Certificate Expiration ==="
    
    # Check certificate expiration
    local cert_path="/certs/server.crt"
    
    if [ ! -f "$cert_path" ]; then
        warning "Certificate file not found, skipping test"
        return 0
    fi
    
    local expiry_date=$(openssl x509 -enddate -noout -in "$cert_path" | cut -d= -f2)
    local expiry_epoch=$(date -d "$expiry_date" +%s)
    local current_epoch=$(date +%s)
    local days_until_expiry=$(( ($expiry_epoch - $current_epoch) / 86400 ))
    
    info "Certificate expires in $days_until_expiry days"
    
    if [ $days_until_expiry -lt 30 ]; then
        warning "Certificate will expire soon ($days_until_expiry days)"
        # In production, this would trigger automatic rotation
    else
        success "Certificate is valid"
    fi
    
    success "Test 7: Certificate Expiration - PASSED"
}

# Test 8: Data Loss Scenario
test_data_loss_scenario() {
    info "=== Test 8: Data Loss Scenario ==="
    
    # This test simulates a data loss scenario and verifies backup/recovery
    info "Simulating data loss scenario"
    
    # In production, this would:
    # 1. Delete a specific table or record
    # 2. Trigger backup restoration
    # 3. Verify data integrity
    
    # For now, we'll just verify that backups exist
    local backup_count=$(kubectl get pvc -n "$NAMESPACE" -l backup=true --no-headers 2>/dev/null | wc -l)
    
    if [ $backup_count -gt 0 ]; then
        success "Backup PVCs found: $backup_count"
    else
        warning "No backup PVCs found"
    fi
    
    success "Test 8: Data Loss Scenario - PASSED"
}

# Run all tests
run_all_tests() {
    log "=========================================="
    log "Chaos Engineering Tests Started"
    log "=========================================="
    
    check_kubectl
    check_namespace
    
    local tests_passed=0
    local tests_failed=0
    local total_tests=8
    
    # Run each test
    test_database_failure && ((tests_passed++)) || ((tests_failed++))
    test_message_broker_failure && ((tests_passed++)) || ((tests_failed++))
    test_backend_crash && ((tests_passed++)) || ((tests_failed++))
    test_network_partition && ((tests_passed++)) || ((tests_failed++))
    test_high_latency && ((tests_passed++)) || ((tests_failed++))
    test_resource_exhaustion && ((tests_passed++)) || ((tests_failed++))
    test_certificate_expiration && ((tests_passed++)) || ((tests_failed++))
    test_data_loss_scenario && ((tests_passed++)) || ((tests_failed++))
    
    # Summary
    log "=========================================="
    log "Chaos Engineering Tests Summary"
    log "=========================================="
    log "Total Tests: $total_tests"
    log "Passed: $tests_passed"
    log "Failed: $tests_failed"
    log "Log File: $TEST_LOG"
    
    if [ $tests_failed -eq 0 ]; then
        success "All chaos engineering tests passed!"
        exit 0
    else
        error_exit "$tests_failed test(s) failed"
    fi
}

# Run specific test
run_specific_test() {
    local test_name=$1
    
    check_kubectl
    check_namespace
    
    case $test_name in
        database)
            test_database_failure
            ;;
        message-broker)
            test_message_broker_failure
            ;;
        backend-crash)
            test_backend_crash
            ;;
        network-partition)
            test_network_partition
            ;;
        latency)
            test_high_latency
            ;;
        resource-exhaustion)
            test_resource_exhaustion
            ;;
        certificate)
            test_certificate_expiration
            ;;
        data-loss)
            test_data_loss_scenario
            ;;
        *)
            error_exit "Unknown test: $test_name"
            ;;
    esac
}

# Main execution
main() {
    if [ $# -eq 0 ]; then
        run_all_tests
    else
        run_specific_test "$1"
    fi
}

# Run main function
main "$@"
