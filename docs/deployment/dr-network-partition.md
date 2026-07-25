# Network Partition - Disaster Recovery Runbook

## Overview
This runbook covers the recovery procedures for network partition events in the OmniusGrid deployment. Network partitions can occur between data centers, between services, or between edge agents and the cloud platform.

## Detection
**Automatic Detection:**
- Network latency alerts via Prometheus/Alertmanager
- Connection timeout alerts
- Split-brain detection in Patroni (TimescaleDB)
- Redpanda broker partition alerts
- Edge agent heartbeat failures
- Kubernetes node not ready alerts

**Manual Detection:**
- Check network connectivity: `ping`, `traceroute`
- Check service mesh status
- Check pod-to-pod connectivity
- Check external service connectivity
- Check DNS resolution

## Impact
**Business Impact:**
- **Critical**: Service degradation or outage
- **Critical**: Data inconsistency between partitions
- **High**: Edge agents cannot send data
- **High**: WebSocket connections drop
- **Medium**: Some services remain operational

**Data Impact:**
- **RPO**: Varies (depends on partition duration)
- **RTO**: 30 minutes (network recovery + data sync)

## RTO/RPO Targets
| Metric | Target | Actual |
|--------|--------|--------|
| RPO (Recovery Point Objective) | 15 minutes | 15-30 minutes (depends on partition) |
| RTO (Recovery Time Objective) | 30 minutes | 20-30 minutes (network recovery) |

## Contacts

### Internal (Deployment Company)
- **On-Call Network Engineer**: [PHONE] - [EMAIL]
- **On-Call DevOps Engineer**: [PHONE] - [EMAIL]
- **On-Call Backend Engineer**: [PHONE] - [EMAIL]
- **IT Manager**: [PHONE] - [EMAIL]
- **CTO**: [PHONE] - [EMAIL]

### External (SoundSafe - Vendor/Platform Provider)
- **SoundSafe Support**: support@soundsafe.ai
- **Platform Engineering**: platform@soundsafe.ai
- **Emergency Hotline**: [PHONE]

### Network Provider
- **ISP Support**: [PHONE] - [EMAIL]
- **Data Center Network Team**: [PHONE] - [EMAIL]

## Manual Recovery Procedures

### Step 1: Assess the Situation
1. Identify partition scope:
   ```bash
   # Check node connectivity
   kubectl get nodes -o wide
   kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, ready: .status.conditions[] | select(.type=="Ready") | .status}'
   ```

2. Check network latency between nodes:
   ```bash
   kubectl exec -it <pod> -n omniusgrid -- ping <other-node-ip>
   ```

3. Check service connectivity:
   ```bash
   kubectl exec -it backend-<pod> -n omniusgrid -- curl http://timescaledb:5432
   kubectl exec -it backend-<pod> -n omniusgrid -- curl http://redpanda:9092
   ```

4. Check DNS resolution:
   ```bash
   kubectl exec -it backend-<pod> -n omniusgrid -- nslookup timescaledb
   ```

### Step 2: Identify Partition Type
1. **Pod-to-Pod Partition:**
   - Check CNI plugin status
   - Check network policies
   - Check pod network interfaces

2. **Node-to-Node Partition:**
   - Check physical network
   - Check switch/router status
   - Check firewall rules

3. **Data Center Partition:**
   - Check inter-DC connectivity
   - Check VPN tunnels
   - Check BGP routes

4. **External Service Partition:**
   - Check internet connectivity
   - Check external API endpoints
   - Check DNS resolution

### Step 3: Recover Network Connectivity
1. **Restart Network Components:**
   ```bash
   # Restart CNI plugin (if applicable)
   kubectl delete pod -n kube-system -l k8s-app=<cni-plugin>
   
   # Reapply network policies. They live in ingress.yaml — there is no
   # network-policies.yaml, and infra/k8s/ was archived to
   # infrastructure/k8s/legacy-patroni/.
   kubectl apply -f infrastructure/k8s/base/ingress.yaml
   ```

2. **Check and Fix Network Policies:**
   ```bash
   kubectl get networkpolicies -A
   kubectl describe networkpolicy <policy-name> -n omniusgrid
   ```

3. **Restart Affected Pods:**
   ```bash
   kubectl delete pod -n omniusgrid -l app=backend
   kubectl delete pod -n omniusgrid -l app=timescaledb
   kubectl delete pod -n omniusgrid -l app=redpanda
   ```

4. **Verify Connectivity:**
   ```bash
   kubectl exec -it backend-<pod> -n omniusgrid -- curl http://timescaledb:5432
   kubectl exec -it backend-<pod> -n omniusgrid -- curl http://redpanda:9092
   ```

### Step 4: Handle Split-Brain Scenarios
1. **TimescaleDB Split-Brain:**
   ```bash
   # Check Patroni status
   patronictl -c /etc/patroni/patroni.yml list
   
   # Force promote correct primary if needed
   patronictl -c /etc/patroni/patroni.yml failover omniusgrid-db --force
   ```

2. **Redpanda Partition:**
   ```bash
   # Check cluster status
   rpk cluster info
   
   # Re-enable partition recovery
   rpk cluster partition recover enable
   ```

3. **Resolve Data Conflicts:**
   - Identify conflicting data
   - Determine authoritative source
   - Apply conflict resolution strategy
   - Re-sync data from primary

### Step 5: Verify Data Consistency
1. **Check Database Replication:**
   ```sql
   SELECT * FROM pg_stat_replication;
   SELECT now() - pg_last_xact_replay_timestamp() AS lag;
   ```

2. **Check Redpanda Consumer Lag:**
   ```bash
   rpk group list
   rpk group describe telemetry-consumer
   ```

3. **Check Edge Agent Sync:**
   ```bash
   # Check edge agent buffer status
   kubectl logs edge-agent-<pod> -n omniusgrid | grep "buffer"
   ```

4. **Verify Continuous Aggregates:**
   ```sql
   SELECT * FROM timescaledb_information.continuous_aggregates;
   ```

## Automated Recovery Procedures

### Network Policy Recovery
```bash
#!/bin/bash
# scripts/dr-network-recovery.sh

NAMESPACE="omniusgrid"

echo "Checking network policies..."
kubectl get networkpolicies -A

echo "Testing pod-to-pod connectivity..."
BACKEND_POD=$(kubectl get pods -n $NAMESPACE -l app=backend -o json | jq -r '.items[0].metadata.name')
TIMESCALEDB_POD=$(kubectl get pods -n $NAMESPACE -l app=timescaledb -o json | jq -r '.items[0].metadata.name')

if kubectl exec $BACKEND_POD -n $NAMESPACE -- curl -s http://timescaledb:5432 > /dev/null 2>&1; then
    echo "Backend to TimescaleDB: OK"
else
    echo "Backend to TimescaleDB: FAILED - restarting pods"
    kubectl delete pod -n $NAMESPACE -l app=backend
    kubectl delete pod -n $NAMESPACE -l app=timescaledb
fi

if kubectl exec $BACKEND_POD -n $NAMESPACE -- curl -s http://redpanda:9092 > /dev/null 2>&1; then
    echo "Backend to Redpanda: OK"
else
    echo "Backend to Redpanda: FAILED - restarting pods"
    kubectl delete pod -n $NAMESPACE -l app=redpanda
fi

echo "Waiting for pods to recover..."
kubectl wait --for=condition=ready pod -l app=backend -n $NAMESPACE --timeout=300s
kubectl wait --for=condition=ready pod -l app=timescaledb -n $NAMESPACE --timeout=300s
kubectl wait --for=condition=ready pod -l app=redpanda -n $NAMESPACE --timeout=300s
```

### Split-Brain Recovery Script
```bash
#!/bin/bash
# scripts/dr-split-brain-recovery.sh

echo "Checking for split-brain scenarios..."

# Check Patroni split-brain
patronictl -c /etc/patroni/patroni.yml list
PATRONI_STATUS=$?

if [ $PATRONI_STATUS -ne 0 ]; then
    echo "Patroni cluster issue detected"
    echo "Attempting to resolve..."
    patronictl -c /etc/patroni/patroni.yml restart omniusgrid-db --force
fi

# Check Redpanda partition
rpk cluster info
REDPANDA_STATUS=$?

if [ $REDPANDA_STATUS -ne 0 ]; then
    echo "Redpanda cluster issue detected"
    echo "Enabling partition recovery..."
    rpk cluster partition recover enable
fi

echo "Verifying cluster health..."
patronictl -c /etc/patroni/patroni.yml list
rpk cluster info
```

### Edge Agent Reconnection Script
```bash
#!/bin/bash
# scripts/dr-edge-agent-reconnect.sh

echo "Checking edge agent connectivity..."

# Check edge agent buffer status
kubectl logs edge-agent-0 -n omniusgrid | grep "buffer" | tail -20

# Restart edge agents if disconnected
if kubectl logs edge-agent-0 -n omniusgrid | grep -q "connection.*failed"; then
    echo "Edge agent connection failed - restarting"
    kubectl delete pod edge-agent-0 -n omniusgrid
    kubectl wait --for=condition=ready pod -l app=edge-agent -n omniusgrid --timeout=300s
fi

echo "Verifying edge agent connectivity..."
kubectl logs edge-agent-0 -n omniusgrid --tail=50
```

## Verification

### Health Checks
1. **Node Connectivity:**
   ```bash
   kubectl get nodes -o wide
   kubectl get nodes -o json | jq '.items[] | {name: .metadata.name, ready: .status.conditions[] | select(.type=="Ready") | .status}'
   ```

2. **Pod Connectivity:**
   ```bash
   kubectl exec -it backend-<pod> -n omniusgrid -- ping timescaledb
   kubectl exec -it backend-<pod> -n omniusgrid -- ping redpanda
   ```

3. **Service Connectivity:**
   ```bash
   kubectl exec -it backend-<pod> -n omniusgrid -- curl http://timescaledb:5432
   kubectl exec -it backend-<pod> -n omniusgrid -- curl http://redpanda:9092
   ```

4. **DNS Resolution:**
   ```bash
   kubectl exec -it backend-<pod> -n omniusgrid -- nslookup timescaledb
   kubectl exec -it backend-<pod> -n omniusgrid -- nslookup redpanda
   ```

### Smoke Tests
1. Test API connectivity:
   ```bash
   curl http://localhost:8000/health
   ```

2. Test database connectivity:
   ```bash
   kubectl exec backend-<pod> -n omniusgrid -- python -c "from app.db.database import init_db; import asyncio; asyncio.run(init_db())"
   ```

3. Test Redpanda connectivity:
   ```bash
   kubectl exec backend-<pod> -n omniusgrid -- rpk cluster info
   ```

> **Auth note:** `$OPS_TOKEN` is a real operator JWT — obtain one with
> `curl -sf $API/api/v1/auth/login -d 'username=<ops-user>&password=...'`
> and export the `access_token`. Production **rejects** the old `dev-token`
> bypass (`ALLOW_DEV_TOKEN` must be false there), so runbook steps must use a
> real credential.


4. Test WebSocket connectivity:
   ```bash
   wscat -c ws://localhost:8000/ws -H "Authorization: Bearer $OPS_TOKEN"
   ```

## Post-Incident Actions

### Root Cause Analysis
1. Collect network metrics:
   ```bash
   kubectl top nodes
   kubectl get events --sort-by='.lastTimestamp' -A
   ```

2. Check network device logs:
   - Switch logs
   - Router logs
   - Firewall logs

3. Review CNI plugin logs:
   ```bash
   kubectl logs -n kube-system -l k8s-app=<cni-plugin>
   ```

4. Check network policy logs:
   ```bash
   kubectl get networkpolicies -A
   kubectl describe networkpolicy <policy> -n omniusgrid
   ```

### Documentation
1. Update incident report with:
   - Partition start/end time
   - Root cause
   - Affected services
   - Data loss (if any)
   - Recovery time
   - Lessons learned

2. Update runbook if new procedures were required

### Preventive Measures
1. Implement network monitoring
2. Add network redundancy (multi-homing)
3. Implement service mesh for better visibility
4. Add circuit breakers for external dependencies
5. Implement automatic failover for critical services
6. Schedule network drills

## Escalation Matrix

| Time Since Detection | Action |
|---------------------|--------|
| 0-5 minutes | Automated recovery, notify on-call |
| 5-15 minutes | Manual intervention if auto-recovery fails |
| 15-30 minutes | Escalate to network engineer |
| 30+ minutes | Escalate to CTO, SoundSafe, and network provider |

## Related Documentation
- [Network Policies](../../infrastructure/k8s/base/ingress.yaml) (the NetworkPolicy objects live in `ingress.yaml`; there is no `network-policies.yaml`)
- [Service Configuration](../../infrastructure/k8s/base/backend-service.yaml)
- [Patroni Configuration](../../infra/pgbackrest/pgbackrest.conf)
- [Redpanda Configuration](../../docker-compose.yml)

## Common Partition Scenarios

### Pod-to-Pod Partition
**Symptoms:** Pods cannot communicate within cluster
**Solution:** Check CNI plugin, network policies, restart affected pods

### Node-to-Node Partition
**Symptoms:** Nodes cannot communicate
**Solution:** Check physical network, switch/router status, restart network services

### Data Center Partition
**Symptoms:** Complete DC isolation
**Solution:** Activate DR site, DNS failover, cross-region replication

### External Service Partition
**Symptoms:** Cannot reach external APIs
**Solution:** Check internet connectivity, DNS, firewall rules, implement fallback

---

**Document Version:** 1.0  
**Last Updated:** 2026-05-25  
**Component:** Disaster Recovery - Network Partition
