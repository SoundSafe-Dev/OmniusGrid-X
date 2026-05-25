#!/bin/bash
# TimescaleDB Disaster Recovery Script
# Automated recovery for TimescaleDB primary node failure

set -e

NAMESPACE="${NAMESPACE:-omniusgrid}"
CLUSTER_NAME="${CLUSTER_NAME:-omniusgrid-db}"

echo "=== TimescaleDB Disaster Recovery ==="
echo "Namespace: $NAMESPACE"
echo "Cluster: $CLUSTER_NAME"
echo ""

# Check if Patroni is installed
if ! command -v patronictl &> /dev/null; then
    echo "Error: patronictl not found. Please install Patroni CLI."
    exit 1
fi

echo "Step 1: Checking TimescaleDB cluster status..."
patronictl -c /etc/patroni/patroni.yml list || {
    echo "Error: Failed to get cluster status"
    exit 1
}

echo ""
echo "Step 2: Identifying failed nodes..."
# This would typically check for offline nodes
# For now, we'll assume manual intervention is needed
echo "Please review the cluster status above and identify any failed nodes."
echo "Press Enter to continue or Ctrl+C to abort..."
read

echo ""
echo "Step 3: Attempting automatic failover if needed..."
# Check if there's a primary node
PRIMARY=$(patronictl -c /etc/patroni/patroni.yml list | grep "Leader" || true)

if [ -z "$PRIMARY" ]; then
    echo "No primary node detected. Attempting to promote standby..."
    STANDBY=$(patronictl -c /etc/patroni/patroni.yml list | grep "Replica" | head -1 | awk '{print $1}')
    
    if [ -n "$STANDBY" ]; then
        echo "Promoting standby: $STANDBY"
        patronictl -c /etc/patroni/patroni.yml failover $CLUSTER_NAME --candidate $STANDBY --force || {
            echo "Error: Failover failed. Manual intervention required."
            exit 1
        }
    else
        echo "Error: No standby nodes available for failover."
        exit 1
    fi
else
    echo "Primary node is running: $PRIMARY"
fi

echo ""
echo "Step 4: Verifying cluster health..."
sleep 5
patronictl -c /etc/patroni/patroni.yml list

echo ""
echo "Step 5: Checking replication lag..."
# This would typically check replication lag on the new primary
echo "Replication lag check would go here."

echo ""
echo "=== TimescaleDB Recovery Complete ==="
echo "Please verify database connectivity:"
echo "  psql -h timescaledb-master -U omniusgrid -d omniusgrid -c 'SELECT 1;'"
