#!/bin/bash
# Backend Service Disaster Recovery Script
# Automated recovery for backend service crashes

set -e

NAMESPACE="${NAMESPACE:-omniusgrid}"
DEPLOYMENT="${DEPLOYMENT:-backend}"

echo "=== Backend Service Disaster Recovery ==="
echo "Namespace: $NAMESPACE"
echo "Deployment: $DEPLOYMENT"
echo ""

echo "Step 1: Checking backend deployment status..."
kubectl get pods -n $NAMESPACE -l app=backend || {
    echo "Error: Failed to get pod status"
    exit 1
}

echo ""
echo "Step 2: Identifying unhealthy pods..."
# Get pods that are not running or not ready
UNHEALTHY_PODS=$(kubectl get pods -n $NAMESPACE -l app=backend -o json | jq -r '.items[] | select(.status.phase!="Running" or ([.status.containerStatuses[].ready] | contains(false))) | .metadata.name' || true)

if [ -n "$UNHEALTHY_PODS" ]; then
    echo "Unhealthy pods detected:"
    echo "$UNHEALTHY_PODS"
    
    echo ""
    echo "Step 3: Checking pod events for diagnosis..."
    for pod in $UNHEALTHY_PODS; do
        echo "=== Events for $pod ==="
        kubectl describe pod $pod -n $NAMESPACE | tail -20
    done
    
    echo ""
    echo "Step 4: Checking recent logs for errors..."
    for pod in $UNHEALTHY_PODS; do
        echo "=== Recent logs for $pod ==="
        kubectl logs $pod -n $NAMESPACE --tail=50 || true
    done
    
    echo ""
    echo "Step 5: Restarting unhealthy pods..."
    for pod in $UNHEALTHY_PODS; do
        echo "Deleting pod: $pod"
        kubectl delete pod $pod -n $NAMESPACE || {
            echo "Warning: Failed to delete pod $pod"
        }
    done
    
    echo ""
    echo "Step 6: Waiting for pods to be ready..."
    kubectl wait --for=condition=ready pod -l app=backend -n $NAMESPACE --timeout=300s || {
        echo "Error: Pods did not become ready within timeout"
        exit 1
    }
else
    echo "All pods are healthy"
fi

echo ""
echo "Step 7: Checking for OOM kills..."
OOM_KILLED=$(kubectl get pods -n $NAMESPACE -l app=backend -o json | jq -r '.items[] | select(.status.containerStatuses[].state.terminated.reason=="OOMKilled") | .metadata.name' || true)

if [ -n "$OOM_KILLED" ]; then
    echo "Warning: Pods were OOM killed: $OOM_KILLED"
    echo "Consider increasing memory limits in deployment YAML"
fi

echo ""
echo "Step 8: Verifying service health..."
HEALTH_CHECK=$(curl -s -o /dev/null -w "%{http_code}" http://localhost:8002/health || echo "000")

if [ "$HEALTH_CHECK" = "200" ]; then
    echo "Health check: PASSED"
else
    echo "Health check: FAILED (HTTP $HEALTH_CHECK)"
    echo "Please check backend logs for errors"
fi

echo ""
echo "Step 9: Verifying database connectivity..."
# This would typically check database connectivity
echo "Database connectivity check would go here"

echo ""
echo "Step 10: Verifying Redpanda connectivity..."
# This would typically check Redpanda connectivity
echo "Redpanda connectivity check would go here"

echo ""
echo "=== Backend Recovery Complete ==="
echo "Current pod status:"
kubectl get pods -n $NAMESPACE -l app=backend
