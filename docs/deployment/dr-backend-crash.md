# Backend Service Crash - Disaster Recovery Runbook

## Overview
This runbook covers the recovery procedures for backend API service crashes in the OmniusGrid deployment. The backend is a FastAPI application that handles all API requests, WebSocket connections, and background workers.

## Detection
**Automatic Detection:**
- Health check endpoint failures (`/health` returns non-200)
- Kubernetes liveness/readiness probe failures
- Prometheus alert for backend downtime
- Grafana dashboard alerts for API error rate
- WebSocket connection failures

**Manual Detection:**
- Check pod status: `kubectl get pods -n omniusgrid -l app=backend`
- Check health endpoint: `curl http://localhost:8000/health`
- Check backend logs: `kubectl logs backend-<pod> -n omniusgrid`
- Check error rate in logs

## Impact
**Business Impact:**
- **Critical**: All API endpoints unavailable
- **Critical**: WebSocket real-time updates fail
- **High**: Dashboard displays error states
- **Medium**: Edge agents cannot send data
- **Low**: Historical data queries fail

**Data Impact:**
- **RPO**: 0 minutes (stateless service)
- **RTO**: 5 minutes (pod restart + health check)

## RTO/RPO Targets
| Metric | Target | Actual |
|--------|--------|--------|
| RPO (Recovery Point Objective) | 0 minutes | 0 minutes (stateless) |
| RTO (Recovery Time Objective) | 5 minutes | 2-5 minutes (auto-restart) |

## Contacts

### Internal (Deployment Company)
- **On-Call Backend Engineer**: [PHONE] - [EMAIL]
- **On-Call DevOps Engineer**: [PHONE] - [EMAIL]
- **IT Manager**: [PHONE] - [EMAIL]
- **CTO**: [PHONE] - [EMAIL]

### External (SoundSafe - Vendor/Platform Provider)
- **SoundSafe Support**: support@soundsafe.ai
- **Platform Engineering**: platform@soundsafe.ai
- **Emergency Hotline**: [PHONE]

## Manual Recovery Procedures

### Step 1: Assess the Situation
1. Check pod status:
   ```bash
   kubectl get pods -n omniusgrid -l app=backend
   ```
2. Check pod events:
   ```bash
   kubectl describe pod backend-<pod> -n omniusgrid
   ```
3. Check recent logs:
   ```bash
   kubectl logs backend-<pod> -n omniusgrid --tail=100
   ```
4. Check resource usage:
   ```bash
   kubectl top pod backend-<pod> -n omniusgrid
   ```

### Step 2: Restart Failed Pod
1. Delete failed pod (Kubernetes will recreate it):
   ```bash
   kubectl delete pod backend-<pod> -n omniusgrid
   ```
2. Wait for new pod to be ready:
   ```bash
   kubectl wait --for=condition=ready pod -l app=backend -n omniusgrid --timeout=300s
   ```
3. Verify pod is running:
   ```bash
   kubectl get pods -n omniusgrid -l app=backend
   ```

### Step 3: Check for Common Issues
1. **Out of Memory:**
   ```bash
   kubectl describe pod backend-<pod> -n omniusgrid | grep -i oom
   ```
   If OOM killed, increase memory limits in deployment.

2. **Database Connection Issues:**
   ```bash
   kubectl logs backend-<pod> -n omniusgrid | grep -i "database\|connection"
   ```
   Check TimescaleDB connectivity.

3. **Redpanda Connection Issues:**
   ```bash
   kubectl logs backend-<pod> -n omniusgrid | grep -i "redpanda\|kafka"
   ```
   Check Redpanda connectivity.

4. **Configuration Errors:**
   ```bash
   kubectl logs backend-<pod> -n omniusgrid | grep -i "error\|exception"
   ```
   Review error messages for configuration issues.

### Step 4: Scale Up if Needed
1. Scale up deployment for redundancy:
   ```bash
   kubectl scale deployment backend -n omniusgrid --replicas=3
   ```
2. Verify all pods are running:
   ```bash
   kubectl get pods -n omniusgrid -l app=backend
   ```

### Step 5: Verify Service Health
1. Check health endpoint:
   ```bash
   curl http://localhost:8000/health
   ```
2. Check API docs:
   ```bash
   curl http://localhost:8000/docs
   ```
3. Check WebSocket endpoint:
   ```bash
   wscat -c ws://localhost:8000/ws
   ```

## Automated Recovery Procedures

### Kubernetes Liveness/Readiness Probes
Kubernetes automatically restarts pods when:
- Liveness probe fails (container is unhealthy)
- Readiness probe fails (container not ready to serve traffic)

**Current Probes:**
```yaml
livenessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 30
  periodSeconds: 10
  timeoutSeconds: 5
  failureThreshold: 3

readinessProbe:
  httpGet:
    path: /health
    port: 8000
  initialDelaySeconds: 10
  periodSeconds: 5
  timeoutSeconds: 3
  failureThreshold: 3
```

### Horizontal Pod Autoscaler
HPA automatically scales based on CPU/memory:
```bash
kubectl get hpa backend -n omniusgrid
```

**Manual Scale Trigger:**
```bash
kubectl autoscale deployment backend --cpu-percent=70 --min=2 --max=10 -n omniusgrid
```

### Backend Recovery Script
```bash
#!/bin/bash
# scripts/dr-backend-recovery.sh

NAMESPACE="omniusgrid"
DEPLOYMENT="backend"

echo "Checking backend deployment status..."
kubectl get pods -n $NAMESPACE -l app=backend

echo "Identifying unhealthy pods..."
UNHEALTHY_PODS=$(kubectl get pods -n $NAMESPACE -l app=backend -o json | jq -r '.items[] | select(.status.phase!="Running" or .status.containerStatuses[0].ready!=true) | .metadata.name')

if [ -n "$UNHEALTHY_PODS" ]; then
    echo "Unhealthy pods detected: $UNHEALTHY_PODS"
    echo "Restarting unhealthy pods..."
    for pod in $UNHEALTHY_PODS; do
        kubectl delete pod $pod -n $NAMESPACE
    done
    
    echo "Waiting for pods to be ready..."
    kubectl wait --for=condition=ready pod -l app=backend -n $NAMESPACE --timeout=300s
else
    echo "All pods are healthy"
fi

echo "Verifying service health..."
kubectl get pods -n $NAMESPACE -l app=backend
curl -f http://localhost:8000/health || echo "Health check failed"
```

### Log Analysis Script
```bash
#!/bin/bash
# scripts/dr-backend-log-analysis.sh

NAMESPACE="omniusgrid"
POD=$(kubectl get pods -n $NAMESPACE -l app=backend -o json | jq -r '.items[0].metadata.name')

echo "Checking for errors in backend logs..."
kubectl logs $POD -n $NAMESPACE --tail=500 | grep -i "error\|exception\|critical" || echo "No errors found"

echo "Checking for OOM kills..."
kubectl describe pod $POD -n $NAMESPACE | grep -i "oom" || echo "No OOM kills"

echo "Checking database connection errors..."
kubectl logs $POD -n $NAMESPACE | grep -i "database\|connection" || echo "No database errors"

echo "Checking Redpanda connection errors..."
kubectl logs $POD -n $NAMESPACE | grep -i "redpanda\|kafka" || echo "No Redpanda errors"
```

## Verification

### Health Checks
1. **Pod Status:**
   ```bash
   kubectl get pods -n omniusgrid -l app=backend
   ```

2. **Health Endpoint:**
   ```bash
   curl http://localhost:8000/health
   ```

3. **API Docs:**
   ```bash
   curl http://localhost:8000/docs
   ```

4. **Database Connectivity:**
   ```bash
   kubectl exec backend-<pod> -n omniusgrid -- python -c "from app.db.database import init_db; import asyncio; asyncio.run(init_db())"
   ```

### Smoke Tests
1. Test authentication:
   ```bash
   curl -X POST http://localhost:8000/api/v1/auth/login \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "username=admin@omniusgrid.com&password=dev"
   ```

> **Auth note:** `$OPS_TOKEN` is a real operator JWT — obtain one with
> `curl -sf $API/api/v1/auth/login -d 'username=<ops-user>&password=...'`
> and export the `access_token`. Production **rejects** the old `dev-token`
> bypass (`ALLOW_DEV_TOKEN` must be false there), so runbook steps must use a
> real credential.


2. Test assets endpoint:
   ```bash
   curl http://localhost:8000/api/v1/assets/ \
     -H "Authorization: Bearer $OPS_TOKEN"
   ```

3. Test WebSocket:
   ```bash
   wscat -c ws://localhost:8000/ws -H "Authorization: Bearer $OPS_TOKEN"
   ```

4. Test Kanban endpoint:
   ```bash
   curl http://localhost:8000/api/v1/kanban/board \
     -H "Authorization: Bearer $OPS_TOKEN"
   ```

## Post-Incident Actions

### Root Cause Analysis
1. Collect logs from crashed pod:
   ```bash
   kubectl logs backend-<pod> -n omniusgrid --previous > /tmp/backend-crash.log
   ```

2. Check system metrics:
   - CPU/Memory usage
   - Disk I/O
   - Network connectivity
   - Database connection pool

3. Review application logs:
   ```bash
   kubectl logs backend-<pod> -n omniusgrid --tail=1000
   ```

4. Check for memory leaks:
   ```bash
   kubectl top pod backend-<pod> -n omniusgrid
   ```

### Documentation
1. Update incident report with:
   - Crash timestamp
   - Root cause
   - Recovery time
   - Impact assessment
   - Lessons learned

2. Update runbook if new procedures were required

### Preventive Measures
1. Review resource limits (CPU, memory)
2. Enable HPA for auto-scaling
3. Add more replicas for redundancy
4. Review database connection pool settings
5. Add more comprehensive logging
6. Implement circuit breakers for external dependencies

## Escalation Matrix

| Time Since Detection | Action |
|---------------------|--------|
| 0-2 minutes | Automated restart, notify on-call |
| 2-5 minutes | Manual intervention if auto-restart fails |
| 5-10 minutes | Escalate to backend engineer |
| 10+ minutes | Escalate to CTO and SoundSafe support |

## Related Documentation
- [Backend Deployment](../../infra/k8s/base/backend-deployment.yaml)
- [Backend Service](../../infra/k8s/base/backend-service.yaml)
- [Backend Configuration](../../backend/app/core/config.py)
- [Health Check Implementation](../../backend/app/api/health.py)

## Common Error Patterns

### Out of Memory (OOM)
**Symptoms:** Pod killed with OOMKilled status
**Solution:** Increase memory limits in deployment YAML

### Database Connection Pool Exhaustion
**Symptoms:** "Connection pool exhausted" errors in logs
**Solution:** Increase pool size in config, add more replicas

### Redpanda Connection Timeout
**Symptoms:** "Connection timeout" errors for Redpanda
**Solution:** Check Redpanda health, increase timeout values

### Import Error
**Symptoms:** "ModuleNotFoundError" on startup
**Solution:** Check requirements.txt, rebuild image with correct dependencies

### Configuration Error
**Symptoms:** "ValidationError" or config errors
**Solution:** Review environment variables and config files

---

**Document Version:** 1.0  
**Last Updated:** 2026-05-25  
**Component:** Disaster Recovery - Backend Crash
