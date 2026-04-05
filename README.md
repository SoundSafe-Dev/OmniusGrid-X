# OmniusGrid - Universal Manufacturing Data Feed Dashboard

A production-grade, resilient manufacturing operations platform with edge inference, cloud training, and comprehensive observability for Industry 4.0.

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              CLOUD ENVIRONMENT                               │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐               │
│  │  Model Training │  │  Monte Carlo    │  │  Digital Twin   │               │
│  │  (PyTorch/GPU)  │  │  Simulations    │  │  Simulations    │               │
│  └────────┬────────┘  └────────┬────────┘  └────────┬────────┘               │
│           └────────────────────┴────────────────────┘                        │
│                              │                                              │
│  ┌───────────────────────────┴───────────────────────────┐                  │
│  │  Model Registry  ◄── Updated weights ──  Secure mTLS  │                  │
│  └───────────────────────────┬───────────────────────────┘                  │
└──────────────────────────────┼──────────────────────────────────────────────┘
                               │
                    ┌──────────┴──────────┐  Outbound-only mTLS
                    │  Secure Cloud Gateway │  Cloud never initiates
                    └──────────┬──────────────┘  connections to factory
┌─────────────────────────────┼─────────────────────────────────────────────┐
│           FACTORY FLOOR (Edge Rack with K3s/Patroni)                       │
│                                                                              │
│  ┌──────────────────────────┬──────────────────────────┐                 │
│  │  Observability Stack     │  AI Engine               │                 │
│  │  ├─ Prometheus (9090)   │  ├─ Tactical Engine      │                 │
│  │  ├─ Grafana (3001)      │  ├─ Strategic Engine      │                 │
│  │  ├─ Loki (logs)         │  ├─ MLOps Pipeline       │                 │
│  │  ├─ Alertmanager        │  ├─ Feature Extraction   │                 │
│  │  └─ TimescaleDB (HA)    │  └─ Cloud Gateway        │                 │
│  └──────────────────────────┴──────────────────────────┘                 │
│                                                                              │
│  ┌─────────────────────────────────────────────────────┐                   │
│  │  Edge Agents - 7 Data Source Types                  │                   │
│  │  ├─ MQTT (Bambu Labs)                              │                   │
│  │  ├─ Screen Scraper (QIDI/SOVOL with OCR)           │                   │
│  │  ├─ File Watcher (ORCA Slicer)                     │                   │
│  │  ├─ OPC-UA (Industrial PLCs)                     │                   │
│  │  ├─ Modbus TCP/RTU (VFDs/Sensors)                 │                   │
│  │  ├─ Store-and-Forward Buffer (24h)                │                   │
│  │  └─ Unified Collector Coordinator               │                   │
│  └─────────────────────────────────────────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────┘
```

## Features

### Data Collection (7 Protocols)
- **MQTT**: Bambu Labs printers with TLS authentication
- **Screen Scraping**: QIDI/SOVOL printers using OpenCV + Tesseract OCR
- **File System**: ORCA Slicer G-code output monitoring
- **OPC-UA**: Industrial PLCs and equipment
- **Modbus TCP/RTU**: VFDs, sensors, legacy equipment
- **Unified Coordinator**: Manages all collectors with health monitoring

### AI/ML Architecture (Gold Standard)
- **Edge Inference**: PyTorch TorchScript models for <100ms control loops
- **Cloud Training**: GPU-based model training and Monte Carlo simulations
- **Data Thinning**: Feature vectors (not raw telemetry) sent to cloud
- **MLOps Pipeline**: Automated model download, validation, hot-swap, rollback
- **Two-Speed Brain**: Tactical (real-time) vs Strategic (macro-optimization)

### Hybrid Operations
- **Human-in-the-Loop**: Grafana dashboards, manual overrides, maintenance mode
- **Lights Out**: K3s health probes, Patroni HA, systemd watchdogs, auto-scaling
- **Observability**: Prometheus metrics, Loki logs, Alertmanager routing

### Day 2 Operations
- **Schema Evolution**: Strict Pydantic contracts with Dead Letter Queue
- **Zero-Trust Security**: mTLS device provisioning with certificate revocation
- **Immutable Audit Trail**: Tamper-evident logging with hash chaining
- **Disaster Recovery**: pgBackRest WAL archiving to S3 with PITR

## Quick Start

### Prerequisites
- Docker & Docker Compose
- 8GB RAM minimum
- 50GB disk space

### Development Setup

```bash
# Clone and start
cd OmniusGrid
docker-compose up -d

# Wait for services
docker-compose ps

# Run database migrations
docker-compose exec timescaledb psql -U omniusgrid -d omniusgrid -f /docker-entrypoint-initdb.d/001_init.sql
docker-compose exec timescaledb psql -U omniusgrid -d omniusgrid -f /docker-entrypoint-initdb.d/002_continuous_aggregates.sql
```

### Access Points

| Service | URL | Description |
|---------|-----|-------------|
| Dashboard | http://localhost:3000 | React manufacturing UI |
| API | http://localhost:8000 | FastAPI REST + WebSocket |
| API Docs | http://localhost:8000/docs | Interactive Swagger docs |
| Grafana | http://localhost:3001 | Logs & metrics (admin/omniusgrid_admin) |
| Prometheus | http://localhost:9090 | Metrics & alerting rules |
| Alertmanager | http://localhost:9093 | Alert routing |
| Redpanda Console | http://localhost:9644 | Message broker UI |

## Project Structure

```
OmniusGrid/
├── backend/                      # FastAPI backend
│   └── app/
│       ├── api/                  # REST endpoints
│       │   ├── assets.py
│       │   ├── telemetry.py
│       │   ├── alarms.py
│       │   ├── engines.py        # AI engine APIs
│       │   └── health.py         # K8s probes
│       ├── services/             # Business logic
│       │   ├── tactical_engine.py      # Edge ML inference
│       │   ├── strategic_engine.py     # Cloud recommendations
│       │   ├── mlops_pipeline.py       # Model management
│       │   ├── feature_extraction.py   # Data thinning
│       │   ├── cloud_gateway.py        # Secure cloud bridge
│       │   ├── schema_registry.py      # Data contracts
│       │   ├── device_provisioning.py  # mTLS certificates
│       │   ├── audit_trail.py          # Compliance logging
│       │   └── data_shedding.py        # Load management
│       ├── core/                 # Config, security
│       ├── db/                   # Database models
│       ├── models/               # Pydantic schemas
│       └── workers/              # Ingestion workers
├── edge-agent/                   # Edge collector SDK
│   └── opsgrid_agent/
│       ├── buffer/               # SQLite store-and-forward
│       ├── packml.py             # State normalization
│       └── collectors/           # All 7 protocol implementations
│           ├── mqtt.py
│           ├── screen_scraper.py
│           ├── file_watcher.py
│           ├── opcua_collector.py
│           ├── modbus_collector.py
│           └── coordinator.py    # Unified management
├── frontend/                     # React dashboard
│   └── src/
│       ├── components/           # UI components
│       │   └── AdminPanel.tsx    # Manual overrides
│       ├── pages/                # Screen layouts
│       └── api/                  # Backend client
├── database/                     # Schema migrations
│   └── migrations/
│       ├── 001_init.sql          # Core tables
│       └── 002_continuous_aggregates.sql  # ML features
├── infra/                        # Deployment configs
│   ├── k8s/                     # Kubernetes manifests
│   │   ├── backend-deployment.yml
│   │   ├── ingestion-deployment.yml
│   │   ├── timescaledb-patroni.yml
│   │   └── pgbackrest-backup.yml
│   ├── prometheus/              # Alerting rules
│   ├── loki/                    # Log aggregation
│   ├── grafana/                 # Dashboards
│   ├── pgbackrest/              # DR configuration
│   └── scripts/                 # Disaster recovery
└── docs/                        # Architecture documentation
    ├── HYBRID_ARCHITECTURE.md
    ├── GOLD_STANDARD_ARCHITECTURE.md
    └── deployment/
```

## API Documentation

### Core Endpoints

```
GET  /api/v1/assets/                    # List all assets
GET  /api/v1/assets/{id}                # Get asset details
GET  /api/v1/telemetry/latest/{id}      # Latest telemetry
POST /api/v1/alarms/{id}/acknowledge    # Acknowledge alarm
GET  /api/v1/dashboard/oee              # Fleet OEE metrics
```

### AI Engine Endpoints

```
GET  /api/v1/engines/tactical/status
POST /api/v1/engines/tactical/infer
GET  /api/v1/engines/strategic/recommendations
POST /api/v1/engines/strategic/recommendations/{id}/approve
GET  /api/v1/engines/mlops/status
POST /api/v1/engines/mlops/deploy/{version}
POST /api/v1/engines/mlops/rollback
```

### Admin Endpoints

```
POST /admin/collectors/{id}/restart
POST /admin/assets/{id}/maintenance
POST /admin/database/vacuum
GET  /admin/system/status
```

## Security

- **Purdue Model**: Manufacturing zone isolated from enterprise/cloud
- **mTLS**: Mutual certificate authentication for all device connections
- **Zero-Trust**: Each device has unique cryptographic identity
- **JWT**: Bearer token authentication for API access
- **Audit Trail**: Every command logged with hash chaining for tamper detection

## License

MIT

## Documentation

- [Hybrid Architecture](HYBRID_ARCHITECTURE.md) - Human-in-the-Loop + Lights Out
- [Gold Standard Architecture](GOLD_STANDARD_ARCHITECTURE.md) - Edge AI + Cloud Training
- [Implementation Summary](IMPLEMENTATION_SUMMARY.md) - Complete feature inventory
