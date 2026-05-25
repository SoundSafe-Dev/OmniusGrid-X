#!/bin/bash
# Redpanda Disaster Recovery Script
# Automated recovery for Redpanda broker failure

set -e

NAMESPACE="${NAMESPACE:-omniusgrid}"
BROKER_COUNT="${BROKER_COUNT:-3}"

echo "=== Redpanda Disaster Recovery ==="
echo "Namespace: $NAMESPACE"
echo "Target broker count: $BROKER_COUNT"
echo ""

# Check if rpk is installed
if ! command -v rpk &> /dev/null; then
    echo "Error: rpk not found. Please install Redpanda CLI."
    exit 1
fi

echo "Step 1: Checking Redpanda cluster status..."
rpk cluster info || {
    echo "Error: Failed to get cluster status"
    exit 1
}

echo ""
echo "Step 2: Checking broker status..."
rpk cluster brokers || {
    echo "Error: Failed to get broker status"
    exit 1
}

echo ""
echo "Step 3: Identifying failed brokers..."
# Check for offline or unreachable brokers
FAILED_BROKERS=$(rpk cluster brokers 2>/dev/null | grep -i "offline\|unreachable" || true)

if [ -n "$FAILED_BROKERS" ]; then
    echo "Failed brokers detected"
    echo "$FAILED_BROKERS"
    
    echo ""
    echo "Step 4: Scaling down StatefulSet..."
    kubectl scale statefulset redpanda -n $NAMESPACE --replicas=2 || {
        echo "Error: Failed to scale down StatefulSet"
        exit 1
    }
    
    echo "Waiting for scale down..."
    sleep 10
    
    echo ""
    echo "Step 5: Removing failed brokers from cluster..."
    for broker in $FAILED_BROKERS; do
        echo "Removing broker: $broker"
        rpk cluster broker delete $broker --brokers localhost:9092 || {
            echo "Warning: Failed to remove broker $broker"
        }
    done
    
    echo ""
    echo "Step 6: Scaling up StatefulSet..."
    kubectl scale statefulset redpanda -n $NAMESPACE --replicas=$BROKER_COUNT || {
        echo "Error: Failed to scale up StatefulSet"
        exit 1
    }
    
    echo "Waiting for brokers to join..."
    sleep 30
    
    echo ""
    echo "Step 7: Enabling partition rebalance..."
    rpk cluster rebalance enable --brokers localhost:9092 || {
        echo "Warning: Failed to enable rebalance"
    }
    
    echo "Monitoring rebalance progress..."
    rpk cluster rebalance status --brokers localhost:9092 || true
else
    echo "No failed brokers detected"
fi

echo ""
echo "Step 8: Verifying cluster health..."
sleep 5
rpk cluster info
rpk cluster brokers

echo ""
echo "Step 9: Checking consumer group lag..."
rpk group list --brokers localhost:9092 || {
    echo "Warning: Failed to get consumer group list"
}

echo ""
echo "Step 10: Resetting lagging consumer groups if needed..."
for group in $(rpk group list --brokers localhost:9092 2>/dev/null | tail -n +2); do
    LAG=$(rpk group describe $group --brokers localhost:9092 2>/dev/null | grep "lag" | awk '{print $2}' || echo "0")
    if [ "$LAG" -gt 1000 ]; then
        echo "Resetting consumer group: $group (lag: $LAG)"
        rpk group reset $group --to-earliest --brokers localhost:9092 || {
            echo "Warning: Failed to reset consumer group $group"
        }
    fi
done

echo ""
echo "=== Redpanda Recovery Complete ==="
echo "Please verify cluster health:"
echo "  rpk cluster info"
echo "  rpk cluster brokers"
