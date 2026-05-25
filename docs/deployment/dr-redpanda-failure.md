# Redpanda Broker Failure - Disaster Recovery Runbook

## Overview
This runbook covers the recovery procedures for Redpanda broker failure in the OmniusGrid deployment. Redpanda is the message broker used for real-time data streaming, command execution, and WebSocket communication.

## Detection
**Automatic Detection:**
- Redpanda cluster health alerts via Prometheus/Alertmanager
- Consumer group lag alerts
- Topic partition offline alerts
- Backend connection errors to Redpanda
- WebSocket connection failures

**Manual Detection:**
- Check Redpanda cluster status: `rpk cluster info`
- Check broker status: `rpk cluster brokers`
- Check topic health: `rpk topic list`
- Check consumer lag: `rpk group list`

## Impact
**Business Impact:**
- **Critical**: Real-time telemetry streaming stops
- **Critical**: Command execution queue unavailable
- **High**: WebSocket real-time updates fail
- **Medium**: Backend can continue with cached data
- **Low**: Historical data queries unaffected

**Data Impact:**
- **RPO**: 0 minutes (replication factor >= 3)
- **RTO**: 10 minutes (broker replacement + recovery)

## RTO/RPO Targets
| Metric | Target | Actual |
|--------|--------|--------|
| RPO (Recovery Point Objective) | 0 minutes | 0 minutes (replication) |
| RTO (Recovery Time Objective) | 10 minutes | 5-10 minutes (broker replacement) |

## Contacts

### Internal (Deployment Company)
- **On-Call DevOps Engineer**: [PHONE] - [EMAIL]
- **On-Call Backend Engineer**: [PHONE] - [EMAIL]
- **IT Manager**: [PHONE] - [EMAIL]
- **CTO**: [PHONE] - [EMAIL]

### External (SoundSafe - Vendor/Platform Provider)
- **SoundSafe Support**: support@soundsafe.ai
- **Platform Engineering**: platform@soundsafe.ai
- **Emergency Hotline**: [PHONE]

## Manual Recovery Procedures

### Step 1: Assess the Situation
1. Check Redpanda cluster status:
   ```bash
   rpk cluster info
   ```
2. Identify failed broker:
   ```bash
   rpk cluster brokers
   ```
3. Check topic partition distribution:
   ```bash
   rpk topic describe telemetry --brokers localhost:9092
   ```
4. Check consumer group lag:
   ```bash
   rpk group list --brokers localhost:9092
   ```

### Step 2: Replace Failed Broker
1. Remove failed broker from cluster:
   ```bash
   rpk cluster broker delete <broker-id> --brokers localhost:9092
   ```
2. Scale down Kubernetes StatefulSet:
   ```bash
   kubectl scale statefulset redpanda -n omniusgrid --replicas=2
   ```
3. Delete failed pod:
   ```bash
   kubectl delete pod redpanda-<index> -n omniusgrid
   ```

### Step 3: Add New Broker
1. Scale up Kubernetes StatefulSet:
   ```bash
   kubectl scale statefulset redpanda -n omniusgrid --replicas=3
   ```
2. Wait for new broker to join cluster:
   ```bash
   kubectl get pods -n omniusgrid -l app=redpanda -w
   ```
3. Verify broker joined:
   ```bash
   rpk cluster brokers
   ```

### Step 4: Rebalance Partitions
1. Trigger partition rebalance:
   ```bash
   rpk cluster rebalance enable --brokers localhost:9092
   ```
2. Monitor rebalance progress:
   ```bash
   rpk cluster rebalance status --brokers localhost:9092
   ```
3. Verify partition distribution:
   ```bash
   rpk topic describe telemetry --brokers localhost:9092
   ```

### Step 5: Verify Consumer Groups
1. Check consumer group status:
   ```bash
   rpk group list --brokers localhost:9092
   ```
2. Reset consumer offsets if needed:
   ```bash
   rpk group reset telemetry-consumer --to-earliest --brokers localhost:9092
   ```
3. Verify lag is decreasing:
   ```bash
   rpk group describe telemetry-consumer --brokers localhost:9092
   ```

### Step 6: Verify Data Integrity
1. Consume from test topic:
   ```bash
   rpk topic consume test-topic --brokers localhost:9092
   ```
2. Produce test message:
   ```bash
   rpk topic produce test-topic --brokers localhost:9092
   ```
3. Verify message received

## Automated Recovery Procedures

### Kubernetes Operator Recovery
Redpanda Kubernetes Operator automatically handles:
- Pod restarts on failure
- Rolling updates
- Configuration changes

**Trigger Manual Rollout:**
```bash
kubectl rollout restart statefulset redpanda -n omniusgrid
```

### rpk Recovery Script
```bash
#!/bin/bash
# scripts/dr-redpanda-recovery.sh

NAMESPACE="omniusgrid"
BROKER_COUNT=3

echo "Checking Redpanda cluster status..."
rpk cluster info

echo "Identifying failed brokers..."
FAILED_BROKERS=$(rpk cluster brokers | grep -i "offline\|unreachable" || true)

if [ -n "$FAILED_BROKERS" ]; then
    echo "Failed brokers detected"
    echo "Scaling down StatefulSet..."
    kubectl scale statefulset redpanda -n $NAMESPACE --replicas=2
    
    echo "Removing failed brokers..."
    for broker in $FAILED_BROKERS; do
        rpk cluster broker delete $broker --brokers localhost:9092
    done
    
    echo "Scaling up StatefulSet..."
    kubectl scale statefulset redpanda -n $NAMESPACE --replicas=$BROKER_COUNT
    
    echo "Waiting for brokers to join..."
    sleep 30
    
    echo "Enabling partition rebalance..."
    rpk cluster rebalance enable --brokers localhost:9092
else
    echo "No failed brokers detected"
fi

echo "Verifying cluster health..."
rpk cluster info
rpk cluster brokers
```

### Consumer Lag Recovery Script
```bash
#!/bin/bash
# scripts/dr-redpanda-consumer-recovery.sh

echo "Checking consumer group lag..."
rpk group list --brokers localhost:9092

echo "Resetting lagging consumer groups..."
for group in $(rpk group list --brokers localhost:9092 | tail -n +2); do
    LAG=$(rpk group describe $group --brokers localhost:9092 | grep "lag" | awk '{print $2}')
    if [ "$LAG" -gt 1000 ]; then
        echo "Resetting consumer group: $group (lag: $LAG)"
        rpk group reset $group --to-earliest --brokers localhost:9092
    fi
done

echo "Verifying consumer groups..."
rpk group list --brokers localhost:9092
```

## Verification

### Health Checks
1. **Cluster Health:**
   ```bash
   rpk cluster info
   ```

2. **Broker Status:**
   ```bash
   rpk cluster brokers
   ```

3. **Topic Health:**
   ```bash
   rpk topic list
   rpk topic describe telemetry
   ```

4. **Consumer Lag:**
   ```bash
   rpk group list
   ```

### Smoke Tests
1. Produce test message:
   ```bash
   echo "test message" | rpk topic produce test-topic --brokers localhost:9092
   ```

2. Consume test message:
   ```bash
   rpk topic consume test-topic --brokers localhost:9092
   ```

3. Verify backend connectivity:
   ```bash
   curl http://localhost:8002/health
   ```

4. Test WebSocket connection:
   ```bash
   wscat -c ws://localhost:8002/ws -H "Authorization: Bearer dev-token"
   ```

## Post-Incident Actions

### Root Cause Analysis
1. Collect logs from failed broker:
   ```bash
   kubectl logs redpanda-<index> -n omniusgrid > /tmp/redpanda-failure.log
   ```

2. Check system metrics:
   - CPU/Memory usage
   - Disk I/O
   - Network connectivity
   - Disk space

3. Review Redpanda logs:
   ```bash
   kubectl logs redpanda-0 -n omniusgrid --tail=100
   ```

### Documentation
1. Update incident report with:
   - Failure timestamp
   - Root cause
   - Recovery time
   - Data loss (if any)
   - Lessons learned

2. Update runbook if new procedures were required

### Preventive Measures
1. Review hardware health (disk, memory, network)
2. Consider increasing replication factor
3. Review monitoring thresholds
4. Schedule additional failover drills

## Escalation Matrix

| Time Since Detection | Action |
|---------------------|--------|
| 0-5 minutes | Automated recovery, notify on-call |
| 5-10 minutes | Manual intervention if auto-recovery fails |
| 10-20 minutes | Escalate to DevOps engineer |
| 20+ minutes | Escalate to CTO and SoundSafe support |

## Related Documentation
- [Redpanda Configuration](../../docker-compose.yml)
- [Kubernetes StatefulSet](../../infra/k8s/base/redpanda-statefulset.yaml)
- [Topic Configuration](../../edge-agent/opsgrid_agent/collectors/coordinator.py)

## Common Topics
- `telemetry` - Real-time sensor data
- `commands` - Command execution queue
- `alarms` - Alarm notifications
- `state_changes` - PackML state transitions
- `websocket` - WebSocket message distribution
