# TimescaleDB Primary Node Failure - Disaster Recovery Runbook

## Overview
This runbook covers the recovery procedures for TimescaleDB primary node failure in the OmniusGrid deployment. TimescaleDB is the primary data store for all operational data including telemetry, alarms, assets, and Kanban tasks.

## Detection
**Automatic Detection:**
- Patroni alerts via Prometheus/Alertmanager
- Database connection failures in backend logs
- Health check endpoint failures (`/health` returns database error)
- Grafana dashboard alerts for database downtime

**Manual Detection:**
- Check Patroni status: `patronictl -c /etc/patroni/patroni.yml list`
- Check database connectivity: `psql -h timescaledb-master -U omniusgrid -d omniusgrid -c "SELECT 1"`
- Check Kubernetes pod status: `kubectl get pods -n omniusgrid -l app=timescaledb`

## Impact
**Business Impact:**
- **Critical**: All real-time data ingestion stops
- **Critical**: Historical data queries fail
- **High**: Kanban task management unavailable
- **High**: Asset telemetry unavailable
- **Medium**: Dashboard displays stale data

**Data Impact:**
- **RPO**: 5 minutes (WAL archiving to S3)
- **RTO**: 15 minutes (Patroni failover + recovery)

## RTO/RPO Targets
| Metric | Target | Actual |
|--------|--------|--------|
| RPO (Recovery Point Objective) | 5 minutes | 5 minutes (WAL archiving) |
| RTO (Recovery Time Objective) | 15 minutes | 10-15 minutes (Patroni auto-failover) |

## Contacts

### Internal (Deployment Company)
- **On-Call Database Engineer**: [PHONE] - [EMAIL]
- **On-Call DevOps Engineer**: [PHONE] - [EMAIL]
- **IT Manager**: [PHONE] - [EMAIL]
- **CTO**: [PHONE] - [EMAIL]

### External (SoundSafe - Vendor/Platform Provider)
- **SoundSafe Support**: support@soundsafe.ai
- **Platform Engineering**: platform@soundsafe.ai
- **Emergency Hotline**: [PHONE]

## Manual Recovery Procedures

### Step 1: Assess the Situation
1. Check Patroni cluster status:
   ```bash
   patronictl -c /etc/patroni/patroni.yml list
   ```
2. Identify failed node and current leader
3. Check replication lag on standby nodes:
   ```bash
   psql -h timescaledb-standby -U omniusgrid -d omniusgrid -c "SELECT * FROM pg_stat_replication;"
   ```

### Step 2: Promote Standby Node (if auto-failover didn't occur)
1. Manually promote standby using Patroni:
   ```bash
   patronictl -c /etc/patroni/patroni.yml restart omniusgrid-db timescaledb-standby-0
   ```
2. Verify promotion:
   ```bash
   patronictl -c /etc/patroni/patroni.yml list
   ```
3. Check database connectivity:
   ```bash
   psql -h timescaledb-standby -U omniusgrid -d omniusgrid -c "SELECT 1;"
   ```

### Step 3: Update Service Endpoints
1. Update Kubernetes service to point to new primary:
   ```bash
   kubectl patch svc timescaledb -n omniusgrid -p '{"spec":{"selector":{"node":"timescaledb-standby-0"}}}'
   ```
2. Update backend connection string if needed
3. Verify backend can connect:
   ```bash
   curl http://localhost:8002/health
   ```

### Step 4: Restore Failed Node
1. Replace or repair the failed node
2. Reinitialize from pgBackRest backup:
   ```bash
   pgbackrest --stanza=opsgrid-db --delta restore
   ```
3. Add node back to Patroni cluster:
   ```bash
   patronictl -c /etc/patroni/patroni.yml scaffold omniusgrid-db
   ```
4. Verify replication:
   ```bash
   psql -h timescaledb-master -U omniusgrid -d omniusgrid -c "SELECT * FROM pg_stat_replication;"
   ```

### Step 5: Verify Data Integrity
1. Check row counts on critical tables:
   ```sql
   SELECT COUNT(*) FROM assets;
   SELECT COUNT(*) FROM telemetry;
   SELECT COUNT(*) FROM alarms;
   SELECT COUNT(*) FROM task_boards;
   ```
2. Check for data gaps in telemetry:
   ```sql
   SELECT time, COUNT(*) FROM telemetry 
   WHERE time > NOW() - INTERVAL '1 hour'
   GROUP BY time ORDER BY time;
   ```
3. Verify continuous aggregates are up to date:
   ```sql
   SELECT * FROM timescaledb_information.continuous_aggregates;
   ```

## Automated Recovery Procedures

### Automated Failover (Patroni)
Patroni automatically handles failover when:
- Primary node becomes unresponsive (default: 30 seconds)
- Replication lag exceeds threshold
- Manual failover triggered via API

**Trigger Manual Failover:**
```bash
patronictl -c /etc/patroni/patroni.yml switchover omniusgrid-db --master timescaledb-master --candidate timescaledb-standby-0
```

### Kubernetes Recovery Script
```bash
#!/bin/bash
# scripts/dr-timescaledb-recovery.sh

NAMESPACE="omniusgrid"
CLUSTER_NAME="omniusgrid-db"

echo "Checking TimescaleDB cluster status..."
patronictl -c /etc/patroni/patroni.yml list

echo "Identifying failed node..."
FAILED_NODE=$(kubectl get pods -n $NAMESPACE -l app=timescaledb -o json | jq -r '.items[] | select(.status.phase!="Running") | .metadata.name')

if [ -n "$FAILED_NODE" ]; then
    echo "Failed node: $FAILED_NODE"
    echo "Attempting automatic failover..."
    patronictl -c /etc/patroni/patroni.yml failover $CLUSTER_NAME --candidate timescaledb-standby-0 --force
else
    echo "No failed nodes detected"
fi

echo "Verifying cluster health..."
patronictl -c /etc/patroni/patroni.yml list
```

### pgBackRest Restore Script
```bash
#!/bin/bash
# scripts/dr-timescaledb-restore.sh

STANZA="opsgrid-db"
PGDATA="/var/lib/postgresql/data/pgdata"

echo "Stopping PostgreSQL..."
systemctl stop postgresql

echo "Restoring from pgBackRest backup..."
pgbackrest --stanza=$STANZA --delta restore

echo "Starting PostgreSQL..."
systemctl start postgresql

echo "Verifying restore..."
psql -U omniusgrid -d omniusgrid -c "SELECT version();"
```

## Verification

### Health Checks
1. **Database Connectivity:**
   ```bash
   psql -h timescaledb-master -U omniusgrid -d omniusgrid -c "SELECT 1;"
   ```

2. **Patroni Cluster Status:**
   ```bash
   patronictl -c /etc/patroni/patroni.yml list
   ```

3. **Backend Health:**
   ```bash
   curl http://localhost:8002/health
   ```

4. **Replication Lag:**
   ```sql
   SELECT now() - pg_last_xact_replay_timestamp() AS lag;
   ```

### Smoke Tests
1. Create test asset:
   ```bash
   curl -X POST http://localhost:8002/api/v1/assets/ \
     -H "Authorization: Bearer dev-token" \
     -H "Content-Type: application/json" \
     -d '{"name":"test-asset","asset_type_id":"uuid","organization_id":"uuid"}'
   ```

2. Query telemetry:
   ```bash
   curl http://localhost:8002/api/v1/telemetry/{asset_id}/latest \
     -H "Authorization: Bearer dev-token"
   ```

3. Check Kanban board:
   ```bash
   curl http://localhost:8002/api/v1/kanban/board \
     -H "Authorization: Bearer dev-token"
   ```

## Post-Incident Actions

### Root Cause Analysis
1. Collect logs from failed node:
   ```bash
   kubectl logs timescaledb-master-0 -n omniusgrid > /tmp/timescaledb-failure.log
   ```

2. Check system metrics:
   - CPU/Memory usage
   - Disk I/O
   - Network connectivity

3. Review PostgreSQL logs:
   ```bash
   tail -f /var/log/postgresql/postgresql-*.log
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
2. Consider increasing monitoring thresholds
3. Review backup retention policies
4. Schedule additional failover drills

## Escalation Matrix

| Time Since Detection | Action |
|---------------------|--------|
| 0-5 minutes | Automated failover, notify on-call |
| 5-15 minutes | Manual intervention if auto-failover fails |
| 15-30 minutes | Escalate to database engineer |
| 30+ minutes | Escalate to CTO and SoundSafe support |

## Related Documentation
- [pgBackRest Configuration](../../infra/pgbackrest/pgbackrest.conf)
- [Patroni Configuration](../../infra/k8s/base/timescaledb-statefulset.yaml)
- [Database Schema](../../database/migrations/001_init.sql)

---

**Document Version:** 1.0  
**Last Updated:** 2026-05-25  
**Component:** Disaster Recovery - TimescaleDB Failure
