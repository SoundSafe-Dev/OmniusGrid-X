# Correlation-AI training dataset

The statistics and worked examples for the dataset behind the correlation engine —
single-domain and multi-domain scenarios, and how they feed Kanban and alerting.

**Moved out of `README.md` on 2026-08-02.** It was 261 lines of sample records in a document
whose job is to get someone running: whoever needs an example of a multi-domain training
scenario is not the same reader as whoever is trying to start the stack, and the samples were
sitting between them.

See also: [`GEMMA4_TRAINING_CURRICULUM.md`](GEMMA4_TRAINING_CURRICULUM.md) for the curriculum
these scenarios serve, and [`CORRELATION_AI_ENGINE.md`](CORRELATION_AI_ENGINE.md) for the
engine that consumes them.

---

## Correlation AI Training Dataset

The correlation AI model is trained on a comprehensive synthetic dataset of 499,986 scenarios (split into train/validation/test sets of 399,988/49,998/50,000). The dataset includes exhaustive state space variables across all operational domains, enabling the AI to provide detailed root cause analysis, risk scoring, and actionable recommendations with specific Kanban task creation and alerting system integration.

#### Dataset Statistics

- **Total Scenarios**: 499,986
- **Domain Coverage**: 47 operational domains (10,638 scenarios per domain)
- **Single/Multi-Domain Ratio**: 50/50 (249,993 single-domain, 249,993 multi-domain)
- **Severity Distribution**: Critical (20.1%), High (26.6%), Medium (26.6%), Low (26.7%)
- **Dataset Split**: 80% train, 10% validation, 10% test

#### Single-Domain Examples

**1. Logistics Fleet**
```
DATA INGEST:
/api/v1/logistics-fleet/metrics: {'category': 'appointment_adherence', 'item': '45%', 'value': 24.03, 'status': 'critical'}

**Correlation Analysis:** Logistics fleet issue detected: TRK-006 experiencing operational delays at DOCK-19. Dwell time exceeded threshold by 9.5 hours. Root cause analysis indicates Driver route deviation. Liability determination suggests Transport company scheduling error responsibility. Detention costs estimated at $20,000. Coordination required between transport management, yard operations, and receiving to resolve bottleneck. Yard utilization at 100%, appointment adherence at 85%.

**Risk Score:** 53.9/100

**Kanban Integration:**
- Creates 2 high-priority Kanban tasks: "Coordinate cross-domain response team" and "Investigate operational anomaly and root cause"
- Tasks auto-assigned to logistics operations team
- Triggers alert notification to yard manager and transport coordinator

**Alerting System:**
- Sends POST to /api/v1/notifications/alert with severity "critical"
- Notifies stakeholders: Transport Manager, Yard Operations Lead, Receiving Supervisor
- Sets escalation timer for 4-hour response window
```

**2. Maintenance**
```
DATA INGEST:
/api/v1/maintenance/metrics: {'category': 'work_order_status', 'item': 'Backlog', 'value': 99.81, 'status': 'critical'}

**Correlation Analysis:** Maintenance operations issue detected: Thermal imaging anomaly indicates equipment degradation on 0.1%. Predictive maintenance analysis suggests preventive maintenance window approaching. Resource coordination required. Vibration levels at 10mm/s (threshold: 5mm/s), temperature 200°C above normal. Estimated time to failure: 48 hours if not addressed. Maintenance backlog: 40 work orders, downtime cost: $7,500/hour. Technician availability: 3 technicians available.

**Risk Score:** 54.8/100

**Kanban Integration:**
- Creates high-priority Kanban task: "Implement corrective action plan"
- Task linked to equipment asset ID in CMMS
- Auto-schedules maintenance window based on 48-hour time-to-failure estimate
- Creates dependency: 3 technicians must be available

**Alerting System:**
- Sends POST to /api/v1/notifications/alert with equipment details
- Notifies: Maintenance Manager, Production Scheduler, Plant Manager
- Includes cost impact: $7,500/hour downtime cost
- Triggers automatic work order creation in CMMS via API
```

**3. Production OEE**
```
DATA INGEST:
/api/v1/production-oee/metrics: {'category': 'industrial_robots', 'item': 'AGV-002', 'value': 30.49, 'status': 'critical'}

**Correlation Analysis:** Production line degradation detected: asset Cell-H in Stopping state with ALM-004: Motor Overload. OEE metrics at 75% below threshold indicating equipment performance or scheduling inefficiency. Root cause analysis suggests Material handling equipment failure with 25% throughput reduction. Equipment cycle time increased by 10%, quality rate dropped to 95%. Maintenance intervention required within 24 hours to prevent production stop. Production loss: 200 units, scrap cost: $1,500.

**Risk Score:** 70.3/100

**Kanban Integration:**
- Creates medium-priority Kanban task: "Monitor recovery and verify resolution"
- Task assigned to production line supervisor
- Links to quality control for scrap cost tracking
- Creates subtask: Verify OEE metrics return to >85%

**Alerting System:**
- Sends POST to /api/v1/commands/execute to trigger equipment reset
- Notifies: Production Manager, Quality Manager, Maintenance Lead
- Includes production impact: 200 units lost, $1,500 scrap cost
- Sets 24-hour SLA for resolution
```

**4. Safety**
```
DATA INGEST:
/api/v1/safety/metrics: {'category': 'incident_location', 'item': 'Parking lot', 'value': 75.2, 'status': 'warning'}

**Correlation Analysis:** Security scenario detected: Insider threat detected affecting operations. Multi-factor analysis indicates security protocol enhancement required. Incident response team activation recommended. Security breach detected at 3 access points, 1 unauthorized access attempt logged. Data exposure: 1,000 records. Remediation time: 40 hours. Regulatory fine: $1,000,000. Contributing factors: 5 contributing factors identified. Corrective actions: 3 corrective actions recommended.

**Risk Score:** 73.0/100

**Kanban Integration:**
- Creates medium-priority Kanban task: "Monitor recovery and verify resolution"
- Task assigned to Security Operations Center
- Creates security incident ticket in incident management system
- Links to compliance tracking for regulatory fine monitoring

**Alerting System:**
- Sends GET to /api/v1/operations/status to check current security posture
- Notifies: CISO, HR Director, Legal Counsel, CEO
- Escalation: Immediate notification for insider threat
- Triggers audit trail logging for forensic investigation
```

**5. Quality Control**
```
DATA INGEST:
/api/v1/quality-control/metrics: {'category': 'process_variation', 'item': '15%', 'value': 12.29, 'status': 'critical'}

**Correlation Analysis:** Quality degradation alert: 4 quality gates failing product lines showing quality issues. First pass yield dropped to 94% (target: 98%+). Analysis indicates process variation or equipment calibration issue. CAPA (Corrective and Preventive Action) required per ISO 22000: Food Safety Management standards. 4 non-conformances logged. Inspection backlog: 2,000 units, inspection cycle time increased by 25%.

**Risk Score:** 50.0/100

**Kanban Integration:**
- Creates 2 Kanban tasks: "Monitor recovery and verify resolution" (medium) and "Implement corrective action plan" (high)
- High-priority task linked to CAPA workflow
- Creates quality hold on affected product lines
- Assigns to Quality Manager with Production Manager as stakeholder

**Alerting System:**
- Sends GET to /api/v1/metrics/current for continuous monitoring
- Notifies: Quality Manager, Production Manager, Compliance Officer
- Includes compliance reference: ISO 22000: Food Safety Management
- Triggers automatic quality hold in ERP system
```

#### Multi-Domain Examples

**1. Logistics + Production**
```
DATA INGEST:
/api/v1/logistics-fleet/metrics + /api/v1/production-oee/metrics

**Correlation Analysis:** Logistics delays with TRK-004 at DOCK-29 causing production line inefficiencies. Detention analysis identifies Yard equipment unavailability with Driver staff unavailable responsibility. Material starvation impacting production OEE. Production throughput reduced by 40%, 15 production orders delayed. Cross-domain coordination required between logistics, production planning, and yard management. Dwell time: 6 hours, detention cost: $5,000.

**Risk Score:** 58.5/100

**Kanban Integration:**
- Creates 3 high-priority Kanban tasks across domains:
  1. Logistics: "Coordinate cross-domain response team"
  2. Production: "Investigate operational anomaly and root cause"
  3. Yard: "Implement corrective action plan"
- Tasks linked with dependencies: Logistics task must complete before Production task
- Creates cross-domain Kanban board view for coordinated response

**Alerting System:**
- Sends POST to /api/v1/kanban/tasks to create remediation task
- Sends POST to /api/v1/commands/execute for immediate action
- Notifies across domains: Logistics Manager, Production Manager, Yard Manager
- Escalation to Plant Manager if not resolved in 2 hours
- Includes financial impact: $5,000 detention cost + production loss
```

**2. Logistics + Warehouse**
```
DATA INGEST:
/api/v1/logistics-fleet/metrics + /api/v1/warehouse-management/metrics

**Correlation Analysis:** Logistics-warehouse coordination failure: TRK-006 experiencing delays at DOCK-19 due to Driver route deviation. Receiving bottleneck in warehouse operations causing detention. Cross-functional process integration required. Warehouse receiving throughput degraded by 45%, dock utilization at 95%. 8 trailers queued for unloading. Detention accumulation: $100/hour.

**Risk Score:** 62.3/100

**Kanban Integration:**
- Creates coordinated Kanban tasks:
  1. Logistics: "Resolve trailer detention issue"
  2. Warehouse: "Clear receiving bottleneck"
  3. Cross-domain: "Optimize dock appointment scheduling"
- Tasks tracked on shared Kanban board for logistics-warehouse coordination
- Automatic reassignment based on real-time dock availability

**Alerting System:**
- Sends POST to /api/v1/notifications/alert with real-time queue status
- Notifies: Logistics Coordinator, Warehouse Manager, Dock Supervisor
- Includes cost accumulation: $100/hour detention cost
- Triggers automated appointment rescheduling when queue exceeds threshold
```

**3. Maintenance + Production**
```
DATA INGEST:
/api/v1/maintenance/metrics + /api/v1/production-oee/metrics

**Correlation Analysis:** Maintenance-production conflict: Scheduling conflicts causing production OEE degradation. Vibration analysis indicates equipment requiring maintenance. Coordination between maintenance and production scheduling required. Production stop risk: 6 hours if maintenance deferred. Equipment efficiency at 65%, quality rate dropping to 88%. OEE metrics at 60%. Maintenance backlog: 15 work orders, downtime cost: $2,000/hour.

**Risk Score:** 67.8/100

**Kanban Integration:**
- Creates 2 high-priority Kanban tasks:
  1. Maintenance: "Schedule preventive maintenance window"
  2. Production: "Adjust production schedule for maintenance"
- Tasks linked with time dependencies: Production schedule adjusts based on maintenance window
- Creates shared calendar view for maintenance-production coordination

**Alerting System:**
- Sends POST to /api/v1/commands/execute to execute schedule adjustment
- Notifies: Maintenance Manager, Production Scheduler, Plant Manager
- Includes cost impact: $2,000/hour if deferred beyond 6 hours
- Triggers automatic ERP work order for maintenance scheduling
```

**4. Compliance + Production**
```
DATA INGEST:
/api/v1/compliance-registries/metrics + /api/v1/production-oee/metrics

**Correlation Analysis:** Compliance violation for ISO 9001: Quality Management detected in production operations. Operational procedures not meeting regulatory requirements. Process re-engineering required. Audit findings: 5 findings, 3 areas non-compliant. Corrective action timeline: 30 days. Compliance status: Under Review, violation severity: Major Violation. Compliance score: 70/100 (passing: 85+). Production throughput reduced by 20% due to compliance restrictions.

**Risk Score:** 75.2/100

**Kanban Integration:**
- Creates coordinated Kanban tasks:
  1. Compliance: "Implement corrective action plan"
  2. Production: "Adjust processes for compliance"
  3. Quality: "Update quality documentation"
- Tasks linked to compliance audit timeline (30-day deadline)
- Creates compliance tracking board with production impact visibility

**Alerting System:**
- Sends POST to /api/v1/kanban/tasks to create remediation task
- Sends GET to /api/v1/metrics/current for compliance monitoring
- Notifies: Compliance Officer, Production Manager, Quality Manager
- Includes regulatory deadline: 30 days for corrective action
- Triggers automatic compliance reporting to regulatory body
```

**5. System Infrastructure + Multiple Domains**
```
DATA INGEST:
/api/v1/system-infrastructure/metrics + multiple domain metrics

**Correlation Analysis:** Infrastructure degradation affecting production, logistics, and compliance. Network latency or database performance issues causing downstream operational impacts. Database query response time increased by 500%, network latency averaging 100ms above baseline. System availability at 94% (target: 99.9%+). Error rate 2.1% (baseline: <0.1%). 8 services experiencing degraded performance.

**Risk Score:** 82.5/100

**Kanban Integration:**
- Creates 5 high-priority Kanban tasks across domains:
  1. IT: "Resolve network latency issue"
  2. Production: "Monitor production system availability"
  3. Logistics: "Verify logistics system connectivity"
  4. Compliance: "Ensure compliance system access"
  5. Cross-domain: "Coordinate infrastructure recovery"
- Tasks tracked on infrastructure incident board
- Automatic escalation based on system availability metrics

**Alerting System:**
- Sends POST to /api/v1/notifications/alert with severity "critical"
- Sends GET to /api/v1/operations/status for system health check
- Notifies: IT Director, Plant Manager, CIO, CEO
- Escalation: Immediate for critical infrastructure
- Triggers automatic failover to backup systems if availability < 95%
- Includes SLA breach notification: 99.9% target vs 94% actual
```

#### Kanban and Alerting Integration

The correlation AI model seamlessly integrates with OmniusGrid's Kanban task management and alerting systems:

- **Automatic Task Creation**: When risk score exceeds threshold (50+), AI automatically creates Kanban tasks with appropriate priority (high: >50, medium: 40-50, low: <40)
- **Cross-Domain Coordination**: Multi-domain scenarios create coordinated Kanban tasks across teams with dependency tracking
- **Alert Routing**: AI determines appropriate stakeholders based on domain, severity, and impact
- **API Command Execution**: Recommended actions include specific API endpoints for automated remediation
- **Progress Tracking**: Kanban board tracks task completion, allowing AI to update risk scores based on resolution status
- **Escalation Management**: Alert system includes escalation timers and automatic escalation to higher-level management
- **Cost Impact Tracking**: All scenarios include quantified financial impacts for prioritization and ROI analysis

