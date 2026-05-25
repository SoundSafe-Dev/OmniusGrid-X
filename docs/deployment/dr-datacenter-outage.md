# Data Center Outage - Disaster Recovery Runbook

## Overview
This runbook covers the recovery procedures for complete data center outages in the OmniusGrid deployment. This is the most severe failure scenario requiring activation of the disaster recovery site and full service failover.

## Detection
**Automatic Detection:**
- Site-wide monitoring alerts (external monitoring)
- All services unreachable simultaneously
- DNS resolution failures
- Network connectivity loss to entire data center
- Power facility alerts
- Environmental alerts (fire, flood, etc.)

**Manual Detection:**
- External monitoring dashboards (Pingdom, UptimeRobot)
- Customer reports of complete outage
- Data center status page
- Network provider notifications
- Physical access denied

## Impact
**Business Impact:**
- **Critical**: Complete service outage
- **Critical**: All customer operations stopped
- **Critical**: Data ingestion stopped
- **High**: Extended downtime affects all customers
- **High**: Potential data loss if replication lag exists

**Data Impact:**
- **RPO**: 15 minutes (cross-region replication)
- **RTO**: 60 minutes (DR site activation + DNS failover)

## RTO/RPO Targets
| Metric | Target | Actual |
|--------|--------|--------|
| RPO (Recovery Point Objective) | 15 minutes | 15-30 minutes (cross-region replication) |
| RTO (Recovery Time Objective) | 60 minutes | 45-90 minutes (DR activation) |

## Contacts

### Internal (Deployment Company)
- **On-Call DevOps Engineer**: [PHONE] - [EMAIL]
- **On-Call Backend Engineer**: [PHONE] - [EMAIL]
- **On-Call Database Engineer**: [PHONE] - [EMAIL]
- **IT Manager**: [PHONE] - [EMAIL]
- **CTO**: [PHONE] - [EMAIL]
- **CEO**: [PHONE] - [EMAIL]

### External (SoundSafe - Vendor/Platform Provider)
- **SoundSafe Support**: support@soundsafe.ai
- **Platform Engineering**: platform@soundsafe.ai
- **Emergency Hotline**: [PHONE]
- **Executive Escalation**: exec@soundsafe.ai

### Data Center Provider
- **DC Support**: [PHONE] - [EMAIL]
- **Facility Manager**: [PHONE] - [EMAIL]
- **Emergency Hotline**: [PHONE]

### DNS Provider
- **DNS Support**: [PHONE] - [EMAIL]

## Manual Recovery Procedures

### Step 1: Assess the Situation
1. Confirm data center outage:
   ```bash
   # Check external monitoring
   curl https://api.pingdom.com/api/3.1/checks
   
   # Check data center status page
   curl https://status.datacenter-provider.com
   ```

2. Determine outage scope:
   - Power failure?
   - Network failure?
   - Physical damage?
   - Security incident?

3. Estimate recovery time:
   - Contact data center provider
   - Get ETA for service restoration
   - Decide if DR activation is warranted

### Step 2: Activate DR Site
1. **Verify DR Site Status:**
   ```bash
   # Check DR site connectivity
   ssh dr-admin@dr-site-omniusgrid.com
   
   # Check DR cluster status
   kubectl get nodes --context=dr-cluster
   kubectl get pods -n omniusgrid --context=dr-cluster
   ```

2. **Scale Up DR Services:**
   ```bash
   # Scale backend
   kubectl scale deployment backend --replicas=3 -n omniusgrid --context=dr-cluster
   
   # Scale TimescaleDB
   kubectl scale statefulset timescaledb --replicas=3 -n omniusgrid --context=dr-cluster
   
   # Scale Redpanda
   kubectl scale statefulset redpanda --replicas=3 -n omniusgrid --context=dr-cluster
   ```

3. **Verify DR Database:**
   ```bash
   # Check replication status
   kubectl exec timescaledb-0 -n omniusgrid --context=dr-cluster -- psql -U omniusgrid -d omniusgrid -c "SELECT * FROM pg_stat_replication;"
   
   # Check replication lag
   kubectl exec timescaledb-0 -n omniusgrid --context=dr-cluster -- psql -U omniusgrid -d omniusgrid -c "SELECT now() - pg_last_xact_replay_timestamp() AS lag;"
   ```

4. **Promote DR Database if Needed:**
   ```bash
   # If primary is down, promote standby
   patronictl -c /etc/patroni/patroni.yml failover omniusgrid-db --force --context=dr-cluster
   ```

### Step 3: Update DNS Configuration
1. **Update DNS Records:**
   ```bash
   # Update A records to point to DR site
   # Using DNS provider API or web interface
   
   # Example with Route53
   aws route53 change-resource-record-sets \
     --hosted-zone-id Z1234567890ABC \
     --change-batch file://dns-failover.json
   ```

2. **Verify DNS Propagation:**
   ```bash
   # Check from multiple locations
   dig api.omniusgrid.com
   nslookup api.omniusgrid.com
   host api.omniusgrid.com
   ```

3. **Monitor DNS TTL:**
   - Ensure TTL is set to 60 seconds for quick failover
   - Monitor propagation across DNS servers

### Step 4: Verify Service Health
1. **Check DR Site Health:**
   ```bash
   curl https://dr-api.omniusgrid.com/health
   curl https://dr-api.omniusgrid.com/docs
   ```

2. **Test Critical Endpoints:**
   ```bash
   # Authentication
   curl -X POST https://dr-api.omniusgrid.com/api/v1/auth/login \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "username=admin@omniusgrid.com&password=dev"
   
   # Assets
   curl https://dr-api.omniusgrid.com/api/v1/assets/ \
     -H "Authorization: Bearer dev-token"
   
   # Kanban
   curl https://dr-api.omniusgrid.com/api/v1/kanban/board \
     -H "Authorization: Bearer dev-token"
   ```

3. **Check WebSocket Connectivity:**
   ```bash
   wscat -c wss://dr-api.omniusgrid.com/ws -H "Authorization: Bearer dev-token"
   ```

### Step 5: Handle Data Consistency
1. **Check for Data Gaps:**
   ```sql
   -- Check latest data timestamps
   SELECT MAX(time) FROM telemetry;
   SELECT MAX(occurred_at) FROM alarms;
   SELECT MAX(updated_at) FROM assets;
   ```

2. **Recover from Backups if Needed:**
   ```bash
   # Restore from pgBackRest if replication lag is too high
   pgbackrest --stanza=opsgrid-db --delta restore
   ```

3. **Verify Continuous Aggregates:**
   ```sql
   SELECT * FROM timescaledb_information.continuous_aggregates;
   ```

### Step 6: Notify Stakeholders
1. **Internal Notification:**
   - Email all staff
   - Slack incident channel
   - Status page update

2. **Customer Notification:**
   - Email customers
   - Status page update
   - Social media (if appropriate)

3. **External Notification:**
   - SoundSafe support
   - Data center provider
   - DNS provider

## Automated Recovery Procedures

### DNS Failover Script
```bash
#!/bin/bash
# scripts/dr-dns-failover.sh

DR_SITE_IP="dr-site-ip.example.com"
API_DOMAIN="api.omniusgrid.com"
HOSTED_ZONE_ID="Z1234567890ABC"

echo "Initiating DNS failover to DR site..."

# Create change batch
cat > dns-failover.json << EOF
{
  "Changes": [
    {
      "Action": "UPSERT",
      "ResourceRecordSet": {
        "Name": "$API_DOMAIN",
        "Type": "A",
        "TTL": 60,
        "ResourceRecords": [
          {
            "Value": "$DR_SITE_IP"
          }
        ]
      }
    }
  ]
}
EOF

# Apply DNS change
aws route53 change-resource-record-sets \
  --hosted-zone-id $HOSTED_ZONE_ID \
  --change-batch file://dns-failover.json

echo "DNS failover initiated"
echo "Monitoring propagation..."

# Monitor propagation
for i in {1..10}; do
  sleep 30
  DIG_RESULT=$(dig +short $API_DOMAIN)
  if [ "$DIG_RESULT" = "$DR_SITE_IP" ]; then
    echo "DNS propagation complete"
    break
  fi
  echo "Waiting for propagation... ($i/10)"
done
```

### DR Site Activation Script
```bash
#!/bin/bash
# scripts/dr-site-activation.sh

DR_CONTEXT="dr-cluster"
NAMESPACE="omniusgrid"

echo "Activating DR site..."

# Check DR cluster status
kubectl get nodes --context=$DR_CONTEXT
kubectl get pods -n $NAMESPACE --context=$DR_CONTEXT

# Scale up services
echo "Scaling up backend..."
kubectl scale deployment backend --replicas=3 -n $NAMESPACE --context=$DR_CONTEXT

echo "Scaling up TimescaleDB..."
kubectl scale statefulset timescaledb --replicas=3 -n $NAMESPACE --context=$DR_CONTEXT

echo "Scaling up Redpanda..."
kubectl scale statefulset redpanda --replicas=3 -n $NAMESPACE --context=$DR_CONTEXT

# Wait for pods to be ready
echo "Waiting for pods to be ready..."
kubectl wait --for=condition=ready pod -l app=backend -n $NAMESPACE --context=$DR_CONTEXT --timeout=300s
kubectl wait --for=condition=ready pod -l app=timescaledb -n $NAMESPACE --context=$DR_CONTEXT --timeout=300s
kubectl wait --for=condition=ready pod -l app=redpanda -n $NAMESPACE --context=$DR_CONTEXT --timeout=300s

# Verify database replication
echo "Checking database replication..."
kubectl exec timescaledb-0 -n $NAMESPACE --context=$DR_CONTEXT -- psql -U omniusgrid -d omniusgrid -c "SELECT now() - pg_last_xact_replay_timestamp() AS lag;"

echo "DR site activation complete"
```

### Data Consistency Check Script
```bash
#!/bin/bash
# scripts/dr-data-consistency.sh

DR_CONTEXT="dr-cluster"
NAMESPACE="omniusgrid"

echo "Checking data consistency..."

# Check latest telemetry timestamp
kubectl exec timescaledb-0 -n $NAMESPACE --context=$DR_CONTEXT -- psql -U omniusgrid -d omniusgrid -c "SELECT MAX(time) as latest_telemetry FROM telemetry;"

# Check latest alarm timestamp
kubectl exec timescaledb-0 -n $NAMESPACE --context=$DR_CONTEXT -- psql -U omniusgrid -d omniusgrid -c "SELECT MAX(occurred_at) as latest_alarm FROM alarms;"

# Check latest asset update
kubectl exec timescaledb-0 -n $NAMESPACE --context=$DR_CONTEXT -- psql -U omniusgrid -d omniusgrid -c "SELECT MAX(updated_at) as latest_asset FROM assets;"

# Check replication lag
kubectl exec timescaledb-0 -n $NAMESPACE --context=$DR_CONTEXT -- psql -U omniusgrid -d omniusgrid -c "SELECT now() - pg_last_xact_replay_timestamp() AS lag;"

echo "Data consistency check complete"
```

## Verification

### Health Checks
1. **DR Site Status:**
   ```bash
   kubectl get nodes --context=dr-cluster
   kubectl get pods -n omniusgrid --context=dr-cluster
   ```

2. **Service Health:**
   ```bash
   curl https://dr-api.omniusgrid.com/health
   curl https://dr-api.omniusgrid.com/docs
   ```

3. **Database Health:**
   ```bash
   kubectl exec timescaledb-0 -n omniusgrid --context=dr-cluster -- psql -U omniusgrid -d omniusgrid -c "SELECT 1;"
   ```

4. **DNS Resolution:**
   ```bash
   dig api.omniusgrid.com
   nslookup api.omniusgrid.com
   ```

### Smoke Tests
1. Test authentication:
   ```bash
   curl -X POST https://dr-api.omniusgrid.com/api/v1/auth/login \
     -H "Content-Type: application/x-www-form-urlencoded" \
     -d "username=admin@omniusgrid.com&password=dev"
   ```

2. Test assets endpoint:
   ```bash
   curl https://dr-api.omniusgrid.com/api/v1/assets/ \
     -H "Authorization: Bearer dev-token"
   ```

3. Test telemetry endpoint:
   ```bash
   curl https://dr-api.omniusgrid.com/api/v1/telemetry/{asset_id}/latest \
     -H "Authorization: Bearer dev-token"
   ```

4. Test WebSocket:
   ```bash
   wscat -c wss://dr-api.omniusgrid.com/ws -H "Authorization: Bearer dev-token"
   ```

## Post-Incident Actions

### Root Cause Analysis
1. Collect data center incident report
2. Review monitoring data from outage period
3. Analyze DR activation timeline
4. Review DNS failover performance
5. Assess data loss (if any)

### Documentation
1. Update incident report with:
   - Outage start/end time
   - Root cause
   - DR activation time
   - DNS failover time
   - Data loss (if any)
   - Recovery time
   - Lessons learned

2. Update runbook if new procedures were required

### Preventive Measures
1. Review DR site capacity
2. Implement automated DNS failover
3. Improve cross-region replication
4. Reduce DNS TTL for faster failover
5. Schedule DR drills quarterly
6. Review data center provider SLA
7. Consider multi-region active-active setup

## Escalation Matrix

| Time Since Detection | Action |
|---------------------|--------|
| 0-5 minutes | Notify on-call, confirm outage |
| 5-15 minutes | Activate DR site, notify management |
| 15-30 minutes | DNS failover, notify customers |
| 30-60 minutes | Verify services, update status page |
| 60+ minutes | Escalate to CEO and SoundSafe executive |

## Return to Primary Site

### Pre-Failback Checklist
- [ ] Primary site fully recovered
- [ ] Database replication synced
- [ ] Data consistency verified
- [ ] Load testing complete
- [ ] Stakeholders notified

### Failback Procedure
1. Sync data from DR to primary
2. Scale up primary site services
3. Update DNS to point to primary
4. Monitor for issues
5. Scale down DR site
6. Verify primary site stability

## Related Documentation
- [DR Site Configuration](../../infra/k8s/overlays/dr/)
- [DNS Configuration](../../infra/k8s/base/ingress.yaml)
- [Cross-Region Replication](../../infra/pgbackrest/pgbackrest.conf)
- [Monitoring Setup](../../infra/grafana/provisioning/)

## Communication Templates

### Customer Notification
```
Subject: Service Outage - OmniusGrid Platform

Dear Customer,

We are currently experiencing a service outage affecting the OmniusGrid platform. Our team is actively working to restore service using our disaster recovery site.

Estimated recovery time: [TIME]

We apologize for any inconvenience and will provide updates as they become available.

Best regards,
OmniusGrid Team
```

### Internal Notification
```
Subject: CRITICAL: Data Center Outage - DR Activation

Team,

We are activating the DR site due to a data center outage at [PRIMARY_DC].

Current status:
- Outage detected: [TIME]
- DR activation initiated: [TIME]
- DNS failover: [IN PROGRESS/COMPLETE]

All hands on deck. Please join the incident channel: #incident-dc-outage

On-call: [NAME]
```

### Status Page Update
```
[OUTAGE] Service Outage - DR Site Activation

We are currently experiencing a service outage. Disaster recovery site activation is in progress.

Status: DR Activation In Progress
Started: [TIME]
ETA: [TIME]
```
