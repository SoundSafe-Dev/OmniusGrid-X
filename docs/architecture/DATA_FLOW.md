# OmniusGrid Data Flow Documentation

## Overview

This document describes the data flow across the OmniusGrid system, from edge data collection to cloud processing and user visualization.

## File Intake and Correlation Flow

Uploaded CSV, Excel, PDF, DOCX, and image files follow a separate intake path before
they contribute to cross-domain analysis.

```text
Upload
  ↓
Intake item and metadata
  ↓
Parser
  ↓
Domain and shared-key detection
  ↓
Correlation scenario builder
  ↓
Correlation engine
  ↓
Analysis session
```

1. **Upload and intake** — The intake API records the file name, type, owner,
   metadata, and processed data for the uploaded item.
2. **Parse** — The file-type parser produces structured spreadsheet rows, tables,
   document text, and metadata as applicable.
3. **Detect domains and shared keys** — The system identifies operational domains
   (for example Production, Maintenance, Quality, and Logistics) and keys such as
   asset IDs, serial numbers, work orders, purchase orders, and dates.
4. **Build correlation scenarios** — Sources sharing keys form scenarios containing
   active domains, operational metrics, interaction keys, and cross-domain links.
5. **Run correlation and present results** — The correlation engine produces findings,
   risk scores, and detected relationships, which are collected in an analysis session
   with the contributing source files.

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

**Document Version:** 1.0  
**Last Updated:** 2026-05-25  
**Component:** Data Flow Documentation
