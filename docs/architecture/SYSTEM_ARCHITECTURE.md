# OmniusGrid System Architecture

## Overview

OmniusGrid is a production-grade IIoT platform whose differentiator is
correlating the **document / ERP** world with the **machine** world. The textual
/ business surface is the lead: documents and ERP records are parsed, correlated,
and scored by the Correlation AI. The machine surface is the second: an edge
agent implements a two-speed brain — edge inference for tactical decisions
(<100ms latency) and cloud training for strategic optimization (seconds to
minutes). Both surfaces converge on one FastAPI backend.

## High-Level Architecture

```mermaid
graph TB
    subgraph "Business Data — lead surface"
        DOC["Documents: PDF / DOCX / XLSX / images"]
        ERPS["ERP systems (13 connectors)"]
        INTK["Parsers + Intake"]
        CORR["Correlation AI (Gemma) + RAG"]
        DOC --> INTK
        ERPS --> INTK
        INTK --> CORR
    end

    subgraph "Edge Layer — machine surface"
        A["Edge Agent"] --> B["Collectors"]
        B --> C["MQTT / OPC-UA / Modbus / EtherNet-IP"]
        B --> D["PROFINET / BACnet / CAN / SNMP"]
        B --> E["Sparkplug B / DNP3 / HTTP / OCR / File"]
        A --> H["24h Store-and-Forward Buffer"]
        A --> I["Local Analytics + PackML"]
        A --> J["Tactical AI Engine"]
    end

    subgraph "Cloud Gateway"
        K["Secure Gateway"]
        K --> L["Outbound-only mTLS"]
    end

    subgraph "Backend / Data Layer"
        M["Redpanda/Kafka"]
        IW["Ingestion Workers"]
        N["TimescaleDB"]
        PG["Postgres tables"]
        O["FastAPI — REST + WebSocket"]
        RED["Redis"]
    end

    subgraph "Predictive & Optimization"
        HIX["Health Index"]
        RULE["RUL"]
        TWIN["Digital-Twin Optimizer"]
        SIMU["Simulation Engine"]
    end

    subgraph "Fleet / MLOps"
        MR["Model Registry"]
        OTA["OTA Releases + Rollouts"]
        MM["Model Monitoring / Drift"]
        STRAT["Strategic AI Engine"]
    end

    subgraph "Operations"
        HIST["Historian"]
        NOTIF["Notifications"]
        KAN["Kanban + Registries"]
        LOGI["Yard / Transportation / GeoTab"]
    end

    subgraph "Observability"
        T["Prometheus"]
        U["Grafana"]
        V["Loki"]
        W["Alertmanager"]
    end

    H --> K
    I --> K
    J --> K
    K --> M
    M --> IW
    IW --> N
    CORR --> PG
    N --> O
    PG --> O
    O --> RED
    N --> HIX
    HIX --> RULE
    RULE --> TWIN
    SIMU --> TWIN
    MR --> J
    MR --> OTA
    MR --> MM
    MR --> STRAT
    OTA --> K
    STRAT --> O
    TWIN --> O
    HIST --> O
    NOTIF --> O
    KAN --> O
    LOGI --> O
    A --> T
    O --> T
    T --> U
    T --> W
    O --> V
    A --> V
```

## Component Details

### Edge Layer

#### Edge Agent
- **Purpose**: Coordinates collectors, buffering, and upstream communication
- **Technologies**: Python, asyncio, aiokafka, aiosqlite
- **Key Features**:
  - Multi-protocol data collection
  - Store-and-forward buffering (24h retention)
  - PackML state normalization
  - Local analytics and anomaly detection
  - Tactical AI inference (<100ms)

#### Collectors
- **MQTT**: Bambu 3D printers, generic IoT devices
- **OPC-UA**: Industrial PLCs, SCADA systems
- **Modbus**: Industrial sensors, actuators (TCP/RTU)
- **EtherNet/IP**: Rockwell Automation
- **PROFINET**: Siemens automation
- **BACnet**: Building automation
- **CAN Bus**: Vehicle telematics
- **SNMP**: Network gear and infrastructure devices
- **Sparkplug B**: MQTT-based unified namespace
- **DNP3**: Utility / SCADA telemetry (py3.11 driver pending an upstream wheel)
- **HTTP/REST**: Modern APIs
- **Screen Scraper / OCR**: Legacy systems without APIs
- **File Watcher**: Log files, CSV exports

#### Local Analytics
- **OEE Calculation**: Real-time Overall Equipment Effectiveness
- **Anomaly Detection**: Statistical Z-score analysis
- **Trend Analysis**: Moving averages, rate of change
- **Local Alerting**: Rule-based triggers, edge response

### Cloud Gateway

#### Secure Gateway
- **Purpose**: Outbound-only mTLS connection from edge to cloud
- **Security**: Zero-trust networking, mutual TLS
- **Data Thinning**: Feature vectors and discrete events only
- **Fallback**: Store-and-forward during outages

### Cloud Layer

#### Message Broker (Redpanda)
- **Purpose**: Kafka-compatible streaming platform
- **Topics**: telemetry, commands, alarms, correlation
- **Features**: High throughput, low latency, durability

#### Database (TimescaleDB)
- **Purpose**: Time-series data storage with PostgreSQL compatibility
- **Features**: Hypertables, compression, continuous aggregates
- **Retention**: Hot (7 days), Warm (30 days), Cold (1 year)

#### Backend API (FastAPI)
- **Purpose**: RESTful + WebSocket API for all operations (60+ routers behind one
  error envelope and pagination envelope)
- **Auth**: JWT via **PyJWT** (migrated off python-jose); RBAC route-roles on
  every router; websocket auth over `Sec-WebSocket-Protocol`. A dev-token bypass
  exists only when `ALLOW_DEV_TOKEN=true` and is rejected in production.
- **Features**: rate limiting, audit logging, idempotency keys, structured
  request-context logging
- **Endpoints**: Assets, telemetry, alarms, commands, OEE, Kanban, registries,
  AI engines, plus the subsystems below

#### Frontend Dashboard (React)
- **Purpose**: User interface for monitoring and control
- **Technologies**: React 18, TypeScript, Zustand, `@tanstack/react-query` v5,
  TailwindCSS
- **Features**: Real-time charts, asset management, Kanban boards, AI insights.
  Real backend by default; an opt-in mock layer (`VITE_USE_MOCK=true`) can drive
  the UI without a backend.

#### AI Engines
- **Tactical Engine** (`/api/v1/engines`): Edge deployment, real-time control
- **Strategic Engine** (`/api/v1/engines`): Cloud deployment, optimization
- **Correlation AI Engine** (`/api/v1/nlp`, `/api/v1/platform-correlation`):
  Cross-domain root cause analysis over documents/ERP + machine data (Gemma;
  inference needs the model)

#### Predictive Maintenance & Digital Twin
- **Health Index** (`/api/v1/health-index`): asset health scoring from telemetry
- **RUL** (`/api/v1/rul`): remaining-useful-life / failure-risk estimation
- **Simulation Engine** (`/api/v1/simulation`): digital-twin simulation
- **Digital-Twin Optimizer** (`/api/v1/twin`): approval-gated optimization
  recommendations run over the simulation engine

#### Historian & Notifications
- **Historian** (`/api/v1/historian`): tenant-scoped time-series history with
  per-tenant retention policies (`/api/v1/data-retention`)
- **Notifications** (`/api/v1/notifications`): severity/domain-matched dispatch
  over webhook / email / Slack with a persisted delivery log

#### RAG Compliance-Doc Pipeline
- **RAG** (`/api/v1/rag`): retrieval + ingestion over compliance documents,
  backed by a vector store (SeaweedFS/S3); bootstrapped best-effort at startup

#### Model Registry, OTA & Monitoring
- **Model Registry** (`/api/v1/models`, `/api/v1/fleet/model-releases`): model
  versioning, feature contracts, signed artifacts
- **OTA** (`/api/v1/fleet/agents`, `/releases`, `/rollouts`): agent + model
  release rollout orchestration with waves and soak windows
- **Model Monitoring** (`/api/v1/model-monitoring`): drift detection
- **MLOps**: automated training runs, deployment, rollback

### Observability Stack

#### Prometheus
- **Purpose**: Metrics collection and storage
- **Scrape Targets**: All services, edge agents
- **Features**: Multi-dimensional data, query language (PromQL)

#### Grafana
- **Purpose**: Visualization and dashboards
- **Features**: Real-time dashboards, alerting, plugins
- **Data Sources**: Prometheus, Loki, TimescaleDB

#### Loki
- **Purpose**: Log aggregation
- **Features**: Log streaming, full-text search, labels
- **Integration**: Promtail log collector

#### Alertmanager
- **Purpose**: Alert routing and management
- **Features**: Alert grouping, silencing, routing
- **Integrations**: Slack, email, PagerDuty

## Data Flow

Consistent with the platform's differentiator, the flows are ordered
textual/business first, then machine. See
[DATA_FLOW.md](DATA_FLOW.md) for the full set of flow diagrams (intake →
correlation, predictive maintenance, historian, notifications, plus telemetry,
command, alarm, OEE, and retention).

### Document / ERP Correlation Flow (lead surface)

```mermaid
sequenceDiagram
    participant SRC as Documents / ERP
    participant INTK as Parsers / Intake
    participant SK as Shared-key Detector
    participant CAI as Correlation AI (Gemma)
    participant OUT as Registries / Kanban / Notifications
    participant API as Backend API
    participant UI as Frontend

    SRC->>INTK: Upload / sync (PDF, DOCX, XLSX, ERP records)
    INTK->>SK: Parsed structures + per-tab metadata
    SK->>CAI: Cross-file / cross-tab scenarios
    CAI->>OUT: Risk scores + recommended actions
    OUT->>API: Persist registry items / tasks
    API->>UI: Correlation results
```

### Telemetry Flow (machine surface)

```mermaid
sequenceDiagram
    participant Asset as Industrial Asset
    participant Collector as Collector
    participant Edge as Edge Agent
    participant Buffer as Local Buffer
    participant Gateway as Cloud Gateway
    participant Kafka as Redpanda
    participant DB as TimescaleDB
    participant API as Backend API
    participant WS as WebSocket
    participant UI as Frontend
    
    Asset->>Collector: Raw Data
    Collector->>Edge: Normalized Data
    Edge->>Buffer: Store (if offline)
    Edge->>Gateway: mTLS Connection
    Gateway->>Kafka: Telemetry Topic
    Kafka->>DB: Ingestion Worker
    DB->>API: Query
    API->>WS: Broadcast
    WS->>UI: Real-time Update
```

### Command Flow

```mermaid
sequenceDiagram
    participant UI as Frontend
    participant API as Backend API
    participant Queue as Command Queue
    participant Gateway as Cloud Gateway
    participant Edge as Edge Agent
    participant Collector as Collector
    participant Asset as Industrial Asset
    
    UI->>API: POST /commands
    API->>Queue: Enqueue Command
    Queue->>Gateway: Push via mTLS
    Gateway->>Edge: Command Message
    Edge->>Collector: Execute
    Collector->>Asset: Control Signal
    Asset->>Collector: Acknowledgment
    Collector->>Edge: Result
    Edge->>Gateway: Result Message
    Gateway->>API: Update Status
    API->>UI: WebSocket Update
```

### AI Inference Flow

```mermaid
sequenceDiagram
    participant Edge as Edge Agent
    participant Tactical as Tactical Engine
    participant Cloud as Cloud Gateway
    participant Strategic as Strategic Engine
    participant Correlation as Correlation AI
    participant DB as TimescaleDB
    participant UI as Frontend
    
    Edge->>Tactical: Real-time Telemetry
    Tactical->>Edge: Control Decision (<100ms)
    Edge->>Cloud: Feature Vectors
    Cloud->>Strategic: Batch Analysis
    Strategic->>DB: Optimization Results
    Cloud->>Correlation: Cross-Domain Data
    Correlation->>DB: Root Cause Analysis
    DB->>UI: AI Insights
```

## Security Architecture

### Authentication & Authorization

```mermaid
graph LR
    A[User] --> B[Keycloak IdP]
    B --> C[SSO Login]
    C --> D[JWT Token]
    D --> E[Backend API]
    E --> F[RBAC Check]
    F --> G[Resource Access]
    
    style B fill:#4CAF50
    style D fill:#2196F3
    style F fill:#FF9800
```

### Network Security

- **mTLS**: Mutual TLS for edge-cloud communication
- **Zero Trust**: No implicit trust, verify every request
- **Network Segmentation**: Separate zones for edge, cloud, observability
- **Firewall Rules**: Whitelist only necessary ports
- **Secrets Management**: HashiCorp Vault for secrets

### Data Security

- **Encryption at Rest**: All data encrypted (AES-256)
- **Encryption in Transit**: TLS 1.3 for all connections
- **Tenant Isolation**: Row-level security in database
- **Audit Logging**: All access logged and monitored
- **Data Residency**: Compliance-based data location

## Deployment Architecture

### Development

```mermaid
graph TB
    subgraph "Local Development"
        A[Docker Compose]
        A --> B[Redpanda]
        A --> C[TimescaleDB]
        A --> D[Backend]
        A --> E[Frontend]
        A --> F[Edge Agent Sim]
    end
```

### Staging

```mermaid
graph TB
    subgraph "Kubernetes Cluster"
        A[Ingress]
        A --> B[Backend Deployment]
        A --> C[Frontend Deployment]
        B --> D[TimescaleDB StatefulSet]
        B --> E[Redpanda StatefulSet]
        B --> F[Redis]
        G[Edge Agents] --> A
    end
```

### Production

```mermaid
graph TB
    subgraph "Multi-Region"
        A[Region 1]
        B[Region 2]
        A --> C[Global Load Balancer]
        B --> C
    end
    
    subgraph "Region 1"
        D[Kubernetes Cluster]
        D --> E[High Availability]
        E --> F[Patroni HA]
        E --> G[Auto-scaling]
    end
```

## Scalability Architecture

### Horizontal Scaling

- **Backend**: Kubernetes HPA based on CPU/memory
- **Frontend**: CDN with edge caching
- **Edge Agents**: Auto-scaling based on asset count
- **Database**: Patroni for PostgreSQL HA

### Vertical Scaling

- **Tactical AI**: GPU acceleration for inference
- **Strategic AI**: Distributed training across GPUs
- **TimescaleDB**: Partitioning by time and organization

### Caching Strategy

- **Redis**: Session storage, query caching
- **CDN**: Static assets, frontend bundles
- **Browser**: Local storage for UI state
- **Edge**: Local analytics cache

## Disaster Recovery

### Backup Strategy

- **Database**: pgBackRest with incremental backups
- **Configuration**: Git version control
- **Models**: Model registry with versioning
- **Logs**: Loki with long-term storage

### Recovery Procedures

- **RTO**: 1 hour for critical systems
- **RPO**: 5 minutes for data loss
- **Failover**: Automatic for HA components
- **Drill**: Monthly disaster recovery tests

## Performance Architecture

### Latency Targets

- **Edge Inference**: <100ms
- **Cloud Inference**: <1s
- **API Response**: <200ms (p95)
- **WebSocket**: <50ms message delivery
- **Database Query**: <100ms (p95)

### Throughput Targets

- **Telemetry Ingestion**: 100k events/sec
- **Command Execution**: 1k commands/sec
- **API Requests**: 10k requests/sec
- **WebSocket Connections**: 10k concurrent

### Resource Allocation

- **Edge Agent**: 2 CPU, 4GB RAM
- **Backend Pod**: 1 CPU, 2GB RAM (scales to 10)
- **Frontend Pod**: 0.5 CPU, 1GB RAM (scales to 20)
- **Database**: 8 CPU, 32GB RAM (scales to 64)

## Monitoring Architecture

### Metrics

- **System Metrics**: CPU, memory, disk, network
- **Application Metrics**: Request rate, error rate, latency
- **Business Metrics**: OEE, asset uptime, anomaly count
- **AI Metrics**: Model accuracy, drift, latency

### Logging

- **Structured Logs**: JSON format with context
- **Log Levels**: DEBUG, INFO, WARNING, ERROR, CRITICAL
- **Correlation IDs**: Trace requests across services
- **Sensitive Data**: Redacted from logs

### Tracing

- **Distributed Tracing**: Jaeger/Tempo
- **Span Context**: Propagated across services
- **Performance Analysis**: Identify bottlenecks
- **Error Tracking**: Root cause analysis

## Compliance Architecture

### SOC 2

- **Security**: Access controls, encryption, monitoring
- **Availability**: HA, DR, monitoring
- **Processing Integrity**: Data validation, audit trails
- **Confidentiality**: Data classification, access controls
- **Privacy**: GDPR compliance, data subject rights

### GDPR

- **Data Mapping**: Inventory of personal data
- **Consent Management**: User consent tracking
- **Data Subject Rights**: Access, deletion, portability
- **Data Breach**: Notification procedures
- **DPIA**: Data protection impact assessments

### ISO 27001

- **ISMS**: Information security management system
- **Risk Management**: Risk assessment and treatment
- **Asset Management**: Asset inventory and classification
- **Access Control**: Role-based access control
- **Compliance**: Regular audits and assessments

## Technology Stack Summary

| Layer | Technology | Purpose |
|-------|-----------|---------|
| Edge | Python, asyncio | Edge agent runtime |
| Collectors | paho-mqtt, pymodbus, opcua | Protocol support |
| Database | TimescaleDB | Time-series storage |
| Message Broker | Redpanda | Streaming platform |
| Backend | FastAPI, SQLAlchemy | REST API |
| Frontend | React, TypeScript, Zustand | User interface |
| Charts | Recharts, Plotly.js | Data visualization |
| Auth | PyJWT (JWT), optional SSO/Keycloak | Identity management |
| Monitoring | Prometheus, Grafana, Loki | Observability |
| Infrastructure | Kubernetes, Docker | Container orchestration |
| CI/CD | GitHub Actions | Automation |
| Secrets | HashiCorp Vault | Secret management |
| AI | PyTorch, Gemma 4 | Machine learning |

---

**Document Version:** 1.1  
**Last Updated:** 2026-07-17  
**Component:** System Architecture
