# OmniusGrid Deployment Guide

## Overview

This guide provides step-by-step instructions for deploying OmniusGrid to staging and production environments.

## Prerequisites

### Infrastructure Requirements

- **Kubernetes Cluster**: v1.28+ with kubectl configured
- **Container Registry**: GitHub Container Registry (ghcr.io) or equivalent
- **DNS**: Domain names configured for ingress
- **SSL/TLS Certificates**: Valid certificates for HTTPS
- **Secrets Management**: HashiCorp Vault or Kubernetes secrets
- **Monitoring**: Prometheus, Grafana, Loki, Alertmanager
- **Database**: TimescaleDB 2.10+ (PostgreSQL 15)

### Software Requirements

- **Docker**: 20.10+
- **kubectl**: 1.28+
- **Helm**: 3.12+ (optional, for Helm charts)
- **Git**: 2.40+
- **Python**: 3.11+ (for local development)
- **Node.js**: 20+ (for frontend builds)

### Access Requirements

- **GitHub**: Access to repository for CI/CD
- **Container Registry**: Push/pull access
- **Kubernetes**: Admin access to cluster
- **DNS**: Ability to configure DNS records
- **Secrets**: Access to secret management system

## Environment Setup

### 1. Clone Repository

```bash
git clone https://github.com/your-org/OmniusGrid.git
cd OmniusGrid
```

### 2. Configure Environment Variables

Create `.env` file for each environment:

```bash
# Staging
cp .env.staging.example .env.staging

# Production
cp .env.production.example .env.production
```

### 3. Configure Kubernetes Contexts

```bash
# Staging
kubectl config use-context staging-cluster

# Production
kubectl config use-context production-cluster
```

## Staging Deployment

### Step 1: Create Namespaces

```bash
kubectl create namespace omniusgrid-staging
kubectl create namespace omniusgrid-monitoring
```

### Step 2: Create Secrets

```bash
# Database credentials
kubectl create secret generic timescaledb-credentials \
  --from-literal=username=omniusgrid \
  --from-literal=password=your-password \
  --from-literal=database=omniusgrid \
  -n omniusgrid-staging

# JWT secret
kubectl create secret generic jwt-secret \
  --from-literal=secret-key=your-jwt-secret \
  -n omniusgrid-staging

# Redpanda credentials
kubectl create secret generic redpanda-credentials \
  --from-literal=username=admin \
  --from-literal=password=your-password \
  -n omniusgrid-staging

# Model registry credentials
kubectl create secret generic model-registry-credentials \
  --from-literal=api-key=your-api-key \
  -n omniusgrid-staging
```

### Step 3: Deploy Infrastructure

```bash
# Deploy TimescaleDB
kubectl apply -f infrastructure/k8s/base/timescaledb-statefulset.yaml
kubectl apply -f infrastructure/k8s/base/timescaledb-service.yaml

# Deploy Redpanda
kubectl apply -f infrastructure/k8s/base/redpanda-statefulset.yaml
kubectl apply -f infrastructure/k8s/base/redpanda-service.yaml

# Deploy Redis
kubectl apply -f infrastructure/k8s/base/redis-deployment.yaml
kubectl apply -f infrastructure/k8s/base/redis-service.yaml

# Wait for infrastructure to be ready
kubectl wait --for=condition=ready pod -l app=timescaledb -n omniusgrid-staging --timeout=300s
kubectl wait --for=condition=ready pod -l app=redpanda -n omniusgrid-staging --timeout=300s
```

### Step 4: Run Database Migrations

```bash
# Get TimescaleDB pod
TIMESCALE_POD=$(kubectl get pod -l app=timescaledb -n omniusgrid-staging -o jsonpath='{.items[0].metadata.name}')

# Copy migration files
kubectl cp database/migrations/ omniusgrid-staging/$TIMESCALE_POD:/tmp/migrations/

# Run migrations
kubectl exec -n omniusgrid-staging $TIMESCALE_POD -- psql -U omniusgrid -d omniusgrid -f /tmp/migrations/001_init.sql
kubectl exec -n omniusgrid-staging $TIMESCALE_POD -- psql -U omniusgrid -d omniusgrid -f /tmp/migrations/002_continuous_aggregates.sql
kubectl exec -n omniusgrid-staging $TIMESCALE_POD -- psql -U omniusgrid -d omniusgrid -f /tmp/migrations/003_kanban_tables.sql
```

### Step 5: Deploy Applications

```bash
# Apply Kustomize overlay for staging
kubectl apply -k infrastructure/k8s/overlays/staging/

# Wait for deployments to be ready
kubectl wait --for=condition=available deployment/backend -n omniusgrid-staging --timeout=300s
kubectl wait --for=condition=available deployment/frontend -n omniusgrid-staging --timeout=300s
kubectl wait --for=condition=available deployment/ingestion-worker -n omniusgrid-staging --timeout=300s
```

### Step 6: Deploy Monitoring Stack

```bash
# Deploy Prometheus
kubectl apply -f infra/prometheus/prometheus.yml
kubectl apply -f infra/prometheus/alerts.yml

# Deploy Grafana
kubectl apply -f infra/grafana/provisioning/

# Deploy Loki
kubectl apply -f infra/loki/loki.yml

# Deploy Promtail
kubectl apply -f infra/loki/promtail.yml
```

### Step 7: Configure Ingress

```bash
# Apply ingress configuration
kubectl apply -f infrastructure/k8s/base/ingress.yaml

# Verify ingress
kubectl get ingress -n omniusgrid-staging
```

### Step 8: Verify Deployment

```bash
# Check pod status
kubectl get pods -n omniusgrid-staging

# Check services
kubectl get svc -n omniusgrid-staging

# Health check
curl https://staging.omniusgrid.local/health
curl https://staging.omniusgrid.local/api/v1/health/db
```

### Step 9: Smoke Tests

```bash
# Test authentication
curl -X POST https://staging.omniusgrid.local/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username": "dev", "password": "dev"}'

# Test API
curl https://staging.omniusgrid.local/api/v1/assets \
  -H "Authorization: Bearer dev-token"

# Test WebSocket
wscat -c wss://staging.omniusgrid.local/ws
```

## Production Deployment

### Step 1: Create Namespaces

```bash
kubectl create namespace omniusgrid
kubectl create namespace omniusgrid-monitoring
```

### Step 2: Create Secrets (Production)

```bash
# Use strong, unique passwords for production
kubectl create secret generic timescaledb-credentials \
  --from-literal=username=omniusgrid \
  --from-literal-password=$(openssl rand -base64 32) \
  --from-literal=database=omniusgrid \
  -n omniusgrid

# Generate secure JWT secret
kubectl create secret generic jwt-secret \
  --from-literal=secret-key=$(openssl rand -base64 64) \
  -n omniusgrid

# Other secrets...
```

### Step 3: Deploy Infrastructure with High Availability

```bash
# Deploy TimescaleDB with Patroni HA
kubectl apply -f infrastructure/k8s/overlays/production/timescaledb-ha.yaml

# Deploy Redpanda with replication
kubectl apply -f infrastructure/k8s/overlays/production/redpanda-ha.yaml

# Deploy Redis with persistence
kubectl apply -f infrastructure/k8s/overlays/production/redis-ha.yaml
```

### Step 4: Configure Resource Limits

```bash
# Apply production resource limits
kubectl apply -f infrastructure/k8s/overlays/production/backend-resources.yaml
kubectl apply -f infrastructure/k8s/overlays/production/frontend-resources.yaml
```

### Step 5: Configure Auto-scaling

```bash
# Enable Horizontal Pod Autoscaler
kubectl apply -f infrastructure/k8s/overlays/production/hpa.yaml
```

### Step 6: Deploy Applications

```bash
# Apply Kustomize overlay for production
kubectl apply -k infrastructure/k8s/overlays/production/

# Wait for deployments
kubectl wait --for=condition=available deployment/backend -n omniusgrid --timeout=600s
kubectl wait --for=condition=available deployment/frontend -n omniusgrid --timeout=600s
```

### Step 7: Configure Backup

```bash
# Deploy pgBackRest
kubectl apply -f infra/pgbackrest/pgbackrest.conf
kubectl apply -f infra/pgbackrest/backup-cronjob.yaml
```

### Step 8: Configure Monitoring Alerts

```bash
# Configure Alertmanager routes
kubectl apply -f infra/prometheus/alertmanager-production.yml

# Configure Slack webhook
kubectl create secret generic slack-webhook \
  --from-literal=url=https://hooks.slack.com/services/your-webhook \
  -n omniusgrid-monitoring
```

### Step 9: Verify Production Deployment

```bash
# Comprehensive health check
kubectl get pods -n omniusgrid
kubectl get hpa -n omniusgrid
kubectl get pvc -n omniusgrid

# Application health
curl https://omniusgrid.local/health
curl https://omniusgrid.local/api/v1/health/db
curl https://omniusgrid.local/api/v1/health/redis
curl https://omniusgrid.local/api/v1/health/kafka
```

### Step 10: Post-Deployment Checklist

- [ ] All pods running and healthy
- [ ] Database migrations completed
- [ ] SSL certificates valid
- [ ] Monitoring dashboards configured
- [ ] Alert rules active
- [ ] Backup jobs scheduled
- [ ] Log aggregation working
- [ ] Ingress routing correct
- [ ] Rate limiting enabled
- [ ] Security headers configured
- [ ] Audit logging enabled
- [ ] Secret rotation scheduled

## Rolling Updates

### Backend Update

```bash
# Update image tag
kubectl set image deployment/backend backend=ghcr.io/your-org/omniusgrid-backend:v1.2.0 -n omniusgrid

# Watch rollout status
kubectl rollout status deployment/backend -n omniusgrid

# If issues, rollback
kubectl rollout undo deployment/backend -n omniusgrid
```

### Frontend Update

```bash
# Update image tag
kubectl set image deployment/frontend frontend=ghcr.io/your-org/omniusgrid-frontend:v1.2.0 -n omniusgrid

# Watch rollout status
kubectl rollout status deployment/frontend -n omniusgrid

# If issues, rollback
kubectl rollout undo deployment/frontend -n omniusgrid
```

### Database Migration

```bash
# Run migration script
kubectl exec -n omniusgrid timescaledb-0 -- psql -U omniusgrid -d omniusgrid -f /tmp/migrations/004_new_feature.sql

# Verify migration
kubectl exec -n omniusgrid timescaledb-0 -- psql -U omniusgrid -d omniusgrid -c "\dt"
```

## Troubleshooting

### Pod Not Starting

```bash
# Check pod logs
kubectl logs <pod-name> -n omniusgrid

# Check pod events
kubectl describe pod <pod-name> -n omniusgrid

# Check resource limits
kubectl top pod <pod-name> -n omniusgrid
```

### Database Connection Issues

```bash
# Check database pod
kubectl get pod -l app=timescaledb -n omniusgrid

# Check database logs
kubectl logs timescaledb-0 -n omniusgrid

# Test connection
kubectl exec -n omniusgrid backend-xxx -- psql -h timescaledb -U omniusgrid -d omniusgrid
```

### High Memory/CPU Usage

```bash
# Check resource usage
kubectl top nodes
kubectl top pods -n omniusgrid

# Check HPA status
kubectl get hpa -n omniusgrid

# Adjust resource limits
kubectl edit deployment backend -n omniusgrid
```

### Network Issues

```bash
# Check services
kubectl get svc -n omniusgrid

# Check endpoints
kubectl get endpoints -n omniusgrid

# Test connectivity
kubectl exec -n omniusgrid backend-xxx -- curl http://timescaledb:5432
```

## Disaster Recovery

### Database Recovery

```bash
# List backups
kubectl exec -n omniusgrid timescaledb-0 -- pgbackrest info

# Restore from backup
kubectl exec -n omniusgrid timescaledb-0 -- pgbackrest restore --delta --repo=1 --target="2026-05-25 12:00:00"
```

### Cluster Recovery

```bash
# Restore from etcd backup (if using etcd)
etcdctl snapshot restore backup.db

# Reapply manifests
kubectl apply -k infrastructure/k8s/overlays/production/
```

## Security Hardening

### Network Policies

```bash
# Apply network policies
kubectl apply -f infrastructure/k8s/base/network-policies.yaml
```

### Pod Security Policies

```bash
# Apply pod security standards
kubectl apply -f infrastructure/k8s/base/pod-security-standards.yaml
```

### Secrets Rotation

```bash
# Rotate database password
kubectl create secret generic timescaledb-credentials-new \
  --from-literal=username=omniusgrid \
  --from-literal-password=$(openssl rand -base64 32) \
  --from-literal=database=omniusgrid \
  -n omniusgrid

# Update deployment
kubectl set env deployment/backend \
  --from=secret/timescaledb-credentials-new \
  -n omniusgrid
```

## Monitoring

### Grafana Dashboards

- **System Overview**: CPU, memory, network, disk
- **Application Metrics**: Request rate, error rate, latency
- **Database Metrics**: Connections, queries, locks
- **Kafka Metrics**: Throughput, lag, consumer lag
- **AI Engine Metrics**: Model accuracy, drift, latency

### Alert Rules

- **High Error Rate**: >5% error rate for 5 minutes
- **High Latency**: p95 latency >1s for 5 minutes
- **Pod Crash**: Pod restart count >5 in 10 minutes
- **Database Connection**: Connection pool >80% for 5 minutes
- **Disk Space**: Disk usage >80%
- **Memory Usage**: Memory usage >90%

## Maintenance Windows

### Scheduled Maintenance

```bash
# Scale down to zero
kubectl scale deployment backend --replicas=0 -n omniusgrid
kubectl scale deployment frontend --replicas=0 -n omniusgrid

# Perform maintenance
# ...

# Scale back up
kubectl scale deployment backend --replicas=3 -n omniusgrid
kubectl scale deployment frontend --replicas=2 -n omniusgrid
```

### Blue-Green Deployment

```bash
# Deploy new version to green namespace
kubectl apply -k infrastructure/k8s/overlays/production-green/

# Test green environment
# ...

# Switch ingress to green
kubectl patch ingress omniusgrid -p '{"spec":{"rules":[{"host":"omniusgrid.local","http":{"paths":[{"path":"/","backend":{"serviceName":"backend-green","servicePort":8000}}]}}]}}'

# Scale down blue
kubectl scale deployment backend --replicas=0 -n omniusgrid-blue
```

---

**Document Version:** 1.0  
**Last Updated:** 2026-05-25  
**Component:** Deployment Guide
