# OmniusGrid Hybrid Architecture Summary

## Implementation Complete

OmniusGrid now supports both operational models:

### Scenario A: Human-in-the-Loop (Dedicated Engineers)

**Components Added:**
1. **Grafana Loki** - Centralized log aggregation from all containers
2. **Prometheus + Alertmanager** - Metrics collection with intelligent routing
3. **Grafana Dashboards** - Visualization of logs and metrics
4. **Manual Override UI** - React components for engineer controls

**Alert Routing:**
- **Critical** (DB down, disk full) → PagerDuty/SMS
- **High** (API errors, memory pressure) → Slack #omniusgrid-alerts  
- **Medium** (data gaps, asset offline) → Slack #omniusgrid-info
- **Low** (slow queries) → Logged only

**Manual Controls Available:**
- Restart individual collectors (MQTT, Screen Scraper)
- Place assets in Maintenance Mode (blocks game-theoretic commands)
- Trigger database vacuum
- View system status and health metrics

### Scenario B: Lights Out (Self-Healing)

**Components Added:**
1. **K3s Health Probes** - Liveness/Readiness/Startup probes
2. **Patroni HA** - Automatic TimescaleDB failover (3-node cluster)
3. **Data Shedding** - Intelligent load shedding by priority
4. **systemd Watchdog** - Hardware-level restart if OS freezes
5. **HPA** - Auto-scale ingestion workers based on queue depth

**Self-Healing Behaviors:**
- Hung processes restarted within 30 seconds
- Database failover to replica within 5 seconds
- Low-priority data auto-shed when overloaded
- Hardware watchdog forces power-cycle if OS unresponsive

## Access Points

After `docker-compose up -d`:

| Service | URL | Purpose |
|---------|-----|---------|
| OmniusGrid Dashboard | http://localhost:3000 | Manufacturing UI |
| Grafana | http://localhost:3001 | Logs & Metrics |
| Prometheus | http://localhost:9090 | Alert rules |
| Alertmanager | http://localhost:9093 | Alert routing |
| API Docs | http://localhost:8000/docs | REST API |

## Key Files Created

```
OmniusGrid/
├── docker-compose.yml           # +Prometheus, Grafana, Loki
├── backend/
│   ├── app/services/
│   │   └── data_shedding.py     # Intelligent load shedding
│   └── app/api/health.py        # Health probes + metrics
├── frontend/
│   └── src/components/
│       └── AdminPanel.tsx       # Manual override UI
├── infra/
│   ├── prometheus/
│   │   ├── prometheus.yml       # Scrape configs
│   │   ├── alerts.yml           # 15 alerting rules
│   │   └── alertmanager.yml     # Routing to Slack/PagerDuty
│   ├── loki/
│   │   ├── loki.yml             # Log retention (30 days)
│   │   └── promtail.yml         # Container log collection
│   ├── grafana/
│   │   └── provisioning/        # Auto-config datasources
│   ├── k8s/
│   │   ├── backend-deployment.yml      # +Health probes
│   │   ├── ingestion-deployment.yml    # +HPA autoscaling
│   │   └── timescaledb-patroni.yml     # HA database
│   └── systemd/
│       ├── omniusgrid-watchdog.service    # Hardware watchdog
│       └── omniusgrid-backend.service     # Bare metal service
```

## Next Steps

1. **Run the stack:**
   ```bash
   docker-compose up -d
   ```

2. **Configure alert routing:**
   - Set `SLACK_WEBHOOK_URL` in alertmanager.yml
   - Set `PAGERDUTY_SERVICE_KEY` for critical alerts

3. **Deploy to production:**
   - For K3s: `kubectl apply -f infra/k8s/`
   - For bare metal: Copy systemd services to /etc/systemd/system/
   - Enable hardware watchdog: `modprobe softdog && systemctl enable omniusgrid-watchdog`

4. **Configure Grafana:**
   - Login: admin/opsgrid_admin
   - Import dashboards from grafana.com or create custom

The architecture is now resilient enough for lights-out operation while providing full observability for on-site engineers.
