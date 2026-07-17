# OmniusGrid Data Flow Documentation

## Overview

This document describes the data flow across the OmniusGrid system. OmniusGrid's
differentiator is correlating the **document / ERP** world with the **machine**
world, so the flows are ordered accordingly:

1. **Textual / business surface (lead).** Documents (PDF / DOCX / XLSX / images)
   and ERP systems flow through parsers and the intake pipeline, get linked by
   shared keys into cross-file / cross-tab correlation scenarios, and are scored
   by the Correlation AI (Gemma) into actionable registries, Kanban tasks, and
   notifications.
2. **Machine surface.** Machines and sensors are read by the Edge Agent
   (10+ protocol collectors, a 24h store-and-forward buffer, PackML
   normalization), pushed outbound-only over mTLS to Redpanda, consumed by
   ingestion workers, and landed in TimescaleDB.
3. **Convergence.** Both surfaces meet at the FastAPI backend (REST + WebSocket,
   one error envelope, paginated lists), which the React frontend renders.

The Correlation-AI **inference** step needs the Gemma model; everything else —
including the fully-correlated offline demo seeded by
`backend/scripts/seed_demo_data.py` (see [`../DEMO.md`](../DEMO.md)) — runs with
no live edge, cloud, or external services.

The sections below start with the textual/ERP-first flows and the predictive /
historian / notification subsystems, then cover the machine telemetry, command,
alarm, OEE, and retention flows.

## Document / ERP Intake → Correlation Flow

Textual and business data is the lead surface. Documents and ERP records are
parsed, linked by shared keys (asset IDs, order/PO numbers, dates), assembled
into cross-file / cross-tab correlation scenarios, and scored by the Correlation
AI — which emits actionable registry items, Kanban tasks, and notifications.

```mermaid
flowchart LR
    subgraph SRC["Business data sources"]
        DOC["Documents<br/>PDF · DOCX · XLSX · images"]
        ERP["ERP systems<br/>SAP · NetSuite · ..."]
    end
    subgraph INTAKE["Parsers / Intake"]
        PDF["pdf_parser · docx_parser"]
        XLS["spreadsheet parser<br/>every workbook tab"]
        OCR["image_text_extractor<br/>vision OCR"]
        HOOK["ERP connectors + webhooks"]
    end
    subgraph CORR["Correlation"]
        SHARED["Shared-key detector<br/>asset · order · date"]
        SCEN["Scenario builders<br/>cross-file / cross-tab"]
        CAI["Correlation AI (Gemma)<br/>risk scoring"]
    end
    subgraph OUT["Actionable outputs"]
        REG["Actionable registries"]
        TASK["Kanban tasks"]
        NOTE["Notifications"]
    end
    DOC --> PDF
    DOC --> XLS
    DOC --> OCR
    ERP --> HOOK
    PDF --> SHARED
    XLS --> SHARED
    OCR --> SHARED
    HOOK --> SHARED
    SHARED --> SCEN
    SCEN --> CAI
    CAI --> REG
    CAI --> TASK
    CAI --> NOTE
```

**Endpoints:** `/api/v1/nlp/correlation/intake/*` (upload, analyze,
cross-correlate), `/api/v1/nlp/sessions/*` (analysis sessions),
`/api/v1/erp/integrations` + `/api/v1/erp/webhooks`,
`/api/v1/platform-correlation`, `/api/v1/registries`, `/api/v1/kanban`.

## Predictive Maintenance & Digital-Twin Flow

Machine telemetry feeds a health index, which feeds a remaining-useful-life
(RUL) estimate. The digital-twin optimizer runs recommendations over the
simulation engine; because they can drive machine changes, recommendations are
**approval-gated** before they become commands or work orders.

```mermaid
flowchart LR
    TEL["Telemetry<br/>TimescaleDB"] --> HI["Health Index<br/>/api/v1/health-index"]
    HI --> RUL["RUL estimator<br/>/api/v1/rul"]
    RUL --> RISK["Remaining useful life<br/>+ failure risk"]
    RISK --> TWIN["Digital-Twin Optimizer<br/>/api/v1/twin"]
    SIM["Simulation engine<br/>/api/v1/simulation"] --> TWIN
    TWIN --> REC["Recommendations<br/>approval-gated"]
    REC --> QUEUE{"Approval queue"}
    QUEUE -->|"approved"| CMD["Command / work order"]
    QUEUE -->|"rejected"| AUD["Audit log"]
    RISK --> API["Backend API"]
    API --> UI["Predictive Maintenance page"]
```

## Historian Query & Retention Flow

The historian serves tenant-scoped time-series history with per-tenant retention
policies (hot / warm / cold tiers, continuous aggregates, compression, and
purge).

```mermaid
flowchart LR
    subgraph ING["Ingest"]
        TEL["Telemetry hypertable"]
    end
    subgraph RET["Per-tenant retention"]
        POL["HistorianRetentionPolicy<br/>hot · warm · cold"]
        CAGG["Continuous aggregates"]
        COMP["Compression + purge"]
    end
    subgraph SRV["Serve"]
        HAPI["Historian API<br/>/api/v1/historian"]
        DRAPI["Data-retention API<br/>/api/v1/data-retention"]
    end
    TEL --> CAGG
    CAGG --> HAPI
    TEL --> COMP
    POL --> COMP
    POL --> DRAPI
    HAPI --> UI["Historian page"]
```

## Notifications Dispatch Flow

The notifications center matches events (by severity and domain) against tenant
subscriptions and dispatches over webhook, email, or Slack, recording every
attempt in a delivery log.

```mermaid
flowchart LR
    subgraph EV["Event sources"]
        ALM["Alarms"]
        MNT["Maintenance / RUL"]
        YRD["Yard detention"]
        CAI2["Correlation AI"]
    end
    SVC["notification_service<br/>severity + domain match"]
    subgraph SUB["Subscriptions"]
        WH["webhook"]
        EM["email"]
        SL["slack"]
    end
    LOG["Delivery log<br/>NotificationDelivery"]
    ALM --> SVC
    MNT --> SVC
    YRD --> SVC
    CAI2 --> SVC
    SVC --> WH
    SVC --> EM
    SVC --> SL
    WH --> LOG
    EM --> LOG
    SL --> LOG
    LOG --> API["/api/v1/notifications"]
```

## Telemetry Data Flow

### End-to-End Flow

```mermaid
graph LR
    A[Industrial Asset] --> B[Collector]
    B --> C[Edge Agent]
    C --> D[Local Buffer]
    C --> E[Local Analytics]
    C --> F[Tactical AI]
    C --> G[Cloud Gateway]
    G --> H[Redpanda]
    H --> I[Ingestion Worker]
    I --> J[TimescaleDB]
    J --> K[Backend API]
    K --> L[WebSocket Manager]
    L --> M[Frontend Dashboard]
    
    style D fill:#FFC107
    style E fill:#4CAF50
    style F fill:#2196F3
    style G fill:#9C27B0
```

### Detailed Sequence

```mermaid
sequenceDiagram
    participant Asset as Industrial Asset
    participant Collector as Protocol Collector
    participant Edge as Edge Agent
    participant Buffer as SQLite Buffer
    participant Analytics as Local Analytics
    participant AI as Tactical AI
    participant Gateway as Cloud Gateway
    participant Kafka as Redpanda
    participant Ingestion as Ingestion Worker
    participant DB as TimescaleDB
    participant API as Backend API
    participant WS as WebSocket Manager
    participant UI as Frontend
    
    Asset->>Collector: Raw Sensor Data
    Collector->>Collector: Normalize to Standard Format
    Collector->>Edge: Normalized Telemetry
    Edge->>Buffer: Store (Always)
    Edge->>Analytics: Real-time Analysis
    Analytics->>Edge: Anomaly Alerts
    Edge->>AI: Feature Vectors
    AI->>Edge: Control Decisions
    Edge->>Gateway: mTLS Connection
    Gateway->>Kafka: Publish to telemetry topic
    Kafka->>Ingestion: Consume Messages
    Ingestion->>DB: Insert into Hypertable
    DB->>API: Query API
    API->>WS: Broadcast Update
    WS->>UI: Real-time Chart Update
    
    Note over Edge,Gateway: If Gateway Offline
    Edge->>Buffer: Buffer Messages
    Buffer->>Gateway: Backfill on Reconnect
```

### Data Format

#### Collector to Edge Agent
```json
{
  "timestamp_edge": "2026-05-25T12:00:00Z",
  "asset_id": "asset-001",
  "topic": "telemetry",
  "payload": {
    "temp_nozzle": 245.5,
    "temp_bed": 60.2,
    "print_speed": 50.0,
    "packml_state": "Execute"
  },
  "sequence_num": 1716633600000
}
```

#### Edge Agent to Cloud Gateway
```json
{
  "timestamp_edge": "2026-05-25T12:00:00Z",
  "timestamp_cloud": "2026-05-25T12:00:01Z",
  "asset_id": "asset-001",
  "organization_id": "org-001",
  "agent_id": "edge-001",
  "feature_vector": [0.85, 0.32, 0.91, 0.45],
  "packml_state": "Execute",
  "sequence_num": 1716633600000,
  "backfilled": false
}
```

#### Cloud Gateway to Redpanda
```json
{
  "key": "asset-001",
  "value": {
    "timestamp": "2026-05-25T12:00:01Z",
    "asset_id": "asset-001",
    "organization_id": "org-001",
    "metrics": {
      "temp_nozzle": 245.5,
      "temp_bed": 60.2
    },
    "packml_state": "Execute"
  },
  "headers": {
    "organization_id": "org-001",
    "agent_id": "edge-001"
  }
}
```

#### Ingestion Worker to TimescaleDB
```sql
INSERT INTO telemetry (time, asset_id, metric_name, value, unit, packml_state, sequence_num)
VALUES 
  ('2026-05-25T12:00:01Z', 'asset-001', 'temp_nozzle', 245.5, '°C', 'Execute', 1716633600000),
  ('2026-05-25T12:00:01Z', 'asset-001', 'temp_bed', 60.2, '°C', 'Execute', 1716633600000);
```

## Command Data Flow

### End-to-End Flow

```mermaid
graph LR
    A[User] --> B[Frontend]
    B --> C[Backend API]
    C --> D[Command Queue]
    D --> E[Cloud Gateway]
    E --> F[Edge Agent]
    F --> G[Collector]
    G --> H[Industrial Asset]
    H --> G
    G --> F
    F --> E
    E --> C
    C --> B
    B --> A
    
    style D fill:#FFC107
    style E fill:#9C27B0
```

### Detailed Sequence

```mermaid
sequenceDiagram
    participant User as User
    participant UI as Frontend
    participant API as Backend API
    participant Queue as Command Queue
    participant Gateway as Cloud Gateway
    participant Edge as Edge Agent
    participant Collector as Collector
    participant Asset as Industrial Asset
    participant WS as WebSocket Manager
    
    User->>UI: Click Emergency Stop
    UI->>API: POST /api/v1/commands
    API->>API: Validate Permission
    API->>Queue: Enqueue Command
    Queue->>Gateway: Push via mTLS
    Gateway->>Edge: Command Message
    Edge->>Edge: Validate Command
    Edge->>Collector: Execute Command
    Collector->>Asset: Send Control Signal
    Asset->>Collector: Acknowledgment
    Collector->>Edge: Execution Result
    Edge->>Gateway: Result Message
    Gateway->>API: Update Command Status
    API->>WS: Broadcast Status Update
    WS->>UI: Real-time Status Update
    UI->>User: Show Success/Error
```

### Command Format

#### Frontend to Backend API
```json
{
  "asset_id": "asset-001",
  "command_type": "emergency_stop",
  "parameters": {},
  "priority": "critical",
  "timeout_seconds": 30
}
```

#### Backend API to Command Queue
```json
{
  "command_id": "cmd-001",
  "asset_id": "asset-001",
  "organization_id": "org-001",
  "command_type": "emergency_stop",
  "parameters": {},
  "priority": "critical",
  "status": "queued",
  "created_at": "2026-05-25T12:00:00Z",
  "timeout_seconds": 30,
  "retry_count": 0
}
```

#### Cloud Gateway to Edge Agent
```json
{
  "command_id": "cmd-001",
  "asset_id": "asset-001",
  "command_type": "emergency_stop",
  "parameters": {},
  "priority": "critical",
  "issued_at": "2026-05-25T12:00:00Z",
  "timeout_seconds": 30
}
```

#### Edge Agent to Collector
```json
{
  "command_id": "cmd-001",
  "command_type": "emergency_stop",
  "parameters": {},
  "timestamp": "2026-05-25T12:00:01Z"
}
```

## AI Inference Data Flow

### Tactical AI (Edge)

```mermaid
graph LR
    A[Telemetry] --> B[Feature Extraction]
    B --> C[Tactical Model]
    C --> D[Control Decision]
    D --> E[Edge Agent]
    E --> F[Collector]
    F --> G[Asset]
    
    style C fill:#2196F3
    style D fill:#4CAF50
```

### Strategic AI (Cloud)

```mermaid
graph LR
    A[Feature Vectors] --> B[Batch Accumulation]
    B --> C[Strategic Model]
    C --> D[Optimization Recommendations]
    D --> E[Backend API]
    E --> F[Frontend]
    E --> G[Command Queue]
    
    style C fill:#2196F3
    style D fill:#4CAF50
```

### Correlation AI (Cross-Domain)

```mermaid
graph TB
    subgraph "Data Sources"
        A[Edge Telemetry]
        B[OEE Metrics]
        C[Logistics Data]
        D[Compliance Data]
        E[Infrastructure Health]
    end
    
    subgraph "Correlation Engine"
        F[Domain Interaction]
        G[Scenario Generation]
        H[Gemma 4 Model]
        I[Risk Scoring]
        J[Recommendations]
    end
    
    subgraph "Outputs"
        K[Root Cause Analysis]
        L[Kanban Tasks]
        M[Remediation Commands]
        N[Compliance Alerts]
    end
    
    A --> F
    B --> F
    C --> F
    D --> F
    E --> F
    F --> G
    G --> H
    H --> I
    I --> J
    J --> K
    J --> L
    J --> M
    J --> N
    
    style H fill:#9C27B0
    style I fill:#FF9800
```

## Alarm Data Flow

### Alarm Generation Flow

```mermaid
sequenceDiagram
    participant Asset as Industrial Asset
    participant Collector as Collector
    participant Edge as Edge Agent
    participant Analytics as Local Analytics
    participant Gateway as Cloud Gateway
    participant Kafka as Redpanda
    participant API as Backend API
    participant WS as WebSocket Manager
    participant UI as Frontend
    participant Alertmanager as Alertmanager
    
    Asset->>Collector: Alarm Condition
    Collector->>Edge: Alarm Event
    Edge->>Analytics: Local Processing
    Analytics->>Edge: Local Alert
    Edge->>Gateway: Forward Alarm
    Gateway->>Kafka: Publish to alarms topic
    Kafka->>API: Consume Alarm
    API->>API: Correlation Check
    API->>WS: Broadcast Alarm
    WS->>UI: Real-time Alert
    API->>Alertmanager: Trigger Alert
    Alertmanager->>Alertmanager: Route to Slack/Email
```

### Alarm Format

```json
{
  "alarm_id": "alarm-001",
  "asset_id": "asset-001",
  "organization_id": "org-001",
  "alarm_type": "temperature_high",
  "severity": "critical",
  "message": "Nozzle temperature exceeded threshold",
  "value": 260.5,
  "threshold": 250.0,
  "timestamp": "2026-05-25T12:00:00Z",
  "acknowledged": false,
  "acknowledged_by": null,
  "acknowledged_at": null,
  "resolved": false,
  "resolved_at": null
}
```

## OEE Calculation Data Flow

### Real-time OEE (Edge)

```mermaid
graph LR
    A[PackML States] --> B[State Duration]
    B --> C[Availability]
    D[Production Count] --> E[Performance]
    E --> F[Quality Rate]
    C --> G[OEE Calculation]
    F --> G
    G --> H[Local OEE]
    H --> I[Cloud Gateway]
    I --> J[TimescaleDB]
    
    style G fill:#4CAF50
```

### Historical OEE (Cloud)

```mermaid
graph LR
    A[PackML States] --> B[TimescaleDB]
    C[Production Data] --> B
    B --> D[Continuous Aggregates]
    D --> E[OEE API]
    E --> F[Frontend]
    
    style D fill:#FFC107
```

## Data Retention Flow

### Tiered Storage

```mermaid
graph TB
    A[Telemetry Data] --> B{Age < 7 Days?}
    B -->|Yes| C[Hot Storage]
    B -->|No| D{Age < 30 Days?}
    D -->|Yes| E[Warm Storage]
    D -->|No| F{Age < 1 Year?}
    F -->|Yes| G[Cold Storage]
    F -->|No| H[Purge]
    
    C --> I[High Performance SSD]
    E --> J[Standard SSD]
    G --> K[S3/Object Storage]
    
    style C fill:#4CAF50
    style E fill:#FFC107
    style G fill:#FF9800
    style H fill:#F44336
```

### Compression Flow

```mermaid
graph LR
    A[Raw Data] --> B[7 Days Old]
    B --> C[Compress]
    C --> D[Compressed Data]
    D --> E[30 Days Old]
    E --> F[Archive to S3]
    F --> G[1 Year Old]
    G --> H[Purge]
    
    style C fill:#2196F3
    style F fill:#9C27B0
    style H fill:#F44336
```

## WebSocket Data Flow

### Connection Flow

```mermaid
sequenceDiagram
    participant UI as Frontend
    participant WS as WebSocket Manager
    participant Auth as Auth Middleware
    participant Topic as Topic Manager
    
    UI->>WS: WebSocket Connect
    WS->>Auth: Validate Token
    Auth->>WS: Token Valid
    WS->>Topic: Subscribe to Topics
    Topic->>WS: Subscription Confirmed
    WS->>UI: Connection Established
    
    loop Real-time Updates
        Topic->>WS: New Message
        WS->>UI: Broadcast Message
    end
```

### Subscription Topics

- `telemetry/{asset_id}` - Real-time telemetry for specific asset
- `alarms/{organization_id}` - Alarms for organization
- `commands/{asset_id}` - Command status updates
- `oee/{workcell_id}` - OEE updates for workcell
- `connection_status` - Connection status updates

## Data Synchronization Flow

### Edge to Cloud Sync

```mermaid
graph LR
    A[Edge Buffer] --> B{Network Available?}
    B -->|Yes| C[Backfill Worker]
    B -->|No| D[Continue Buffering]
    C --> E[Send Buffered Data]
    E --> F{Success?}
    F -->|Yes| G[Mark as Sent]
    F -->|No| H[Increment Retry]
    H --> I{Retry > 5?}
    I -->|Yes| J[Mark as Failed]
    I -->|No| C
    
    style C fill:#4CAF50
    style G fill:#4CAF50
    style J fill:#F44336
```

### Cloud to Edge Sync

```mermaid
graph LR
    A[Model Registry] --> B[New Model Version]
    B --> C[Cloud Gateway]
    C --> D[Edge Agent]
    D --> E[Download Model]
    E --> F{Validation?}
    F -->|Success| G[Activate Model]
    F -->|Failure| H[Rollback]
    
    style G fill:#4CAF50
    style H fill:#F44336
```

## Data Quality Flow

### Validation Pipeline

```mermaid
graph TB
    A[Raw Data] --> B[Schema Validation]
    B --> C{Valid?}
    C -->|Yes| D[Range Check]
    C -->|No| E[Reject & Log]
    D --> F{In Range?}
    F -->|Yes| G[Duplicate Check]
    F -->|No| H[Flag Anomaly]
    G --> I{Duplicate?}
    I -->|No| J[Store]
    I -->|Yes| K[Drop]
    H --> L[Alert]
    
    style E fill:#F44336
    style H fill:#FF9800
    style J fill:#4CAF50
    style K fill:#FFC107
```

## Compliance Data Flow

### Audit Trail

```mermaid
graph LR
    A[User Action] --> B[Event Capture]
    B --> C[Audit Middleware]
    C --> D[Audit Log Table]
    D --> E[Compliance Report]
    D --> F[SIEM Integration]
    
    style C fill:#9C27B0
    style E fill:#4CAF50
```

### Data Subject Request (GDPR)

```mermaid
graph TB
    A[User Request] --> B[Identity Verification]
    B --> C{Request Type}
    C -->|Access| D[Data Retrieval]
    C -->|Deletion| E[Data Anonymization]
    C -->|Portability| F[Data Export]
    D --> G[Response to User]
    E --> G
    F --> G
    
    style E fill:#FF9800
    style G fill:#4CAF50
```

## Performance Metrics Flow

### Metrics Collection

```mermaid
graph LR
    A[Application] --> B[Prometheus Client]
    B --> C[Metrics Endpoint]
    C --> D[Prometheus Server]
    D --> E[Scrape Interval]
    E --> F[Time Series DB]
    F --> G[Grafana Dashboard]
    F --> H[Alertmanager]
    
    style B fill:#2196F3
    style G fill:#4CAF50
    style H fill:#FF9800
```

### Metric Types

- **Counter**: Monotonically increasing values (request count, error count)
- **Gauge**: Values that go up and down (memory usage, active connections)
- **Histogram**: Distribution of values (request latency)
- **Summary**: Similar to histogram with quantiles (response time)

---

**Document Version:** 1.1  
**Last Updated:** 2026-07-17  
**Component:** Data Flow Documentation
