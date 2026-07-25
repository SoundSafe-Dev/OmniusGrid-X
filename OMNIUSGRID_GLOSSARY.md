# OmniusGrid System Glossary

**Backend & Frontend Combined Terminology Reference**

---

## Table of Contents

- [Architecture & Infrastructure](#architecture--infrastructure)
- [Manufacturing & Assets](#manufacturing--assets)
- [Telemetry & Data Collection](#telemetry--data-collection)
- [PackML State Machine](#packml-state-machine)
- [OEE (Overall Equipment Effectiveness)](#oee-overall-equipment-effectiveness)
- [AI/ML Engines](#aiml-engines)
- [Command Execution](#command-execution)
- [Yard Management System (YMS)](#yard-management-system-yms)
- [Transportation Management System (TMS)](#transportation-management-system-tms)
- [GeoTab Integration](#geotab-integration)
- [Kanban Task Management](#kanban-task-management)
- [Actionable Registries & Compliance](#actionable-registries--compliance)
- [Correlation AI Engine](#correlation-ai-engine)
- [Cross-Tab Workbook Correlation & Intake](#cross-tab-workbook-correlation--intake)
- [Intake Cross-Correlation Enhancement](#intake-cross-correlation-enhancement)
- [Frontend Architecture](#frontend-architecture)
- [Security & Authentication](#security--authentication)
- [Compliance Frameworks](#compliance-frameworks)
- [Testing Infrastructure](#testing-infrastructure)
- [Observability & Monitoring](#observability--monitoring)

---

## Architecture & Infrastructure

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **OmniusGrid** | Universal Manufacturing Data Feed Dashboard - Production-grade IIoT platform with edge AI inference, cloud training, and comprehensive observability | Both |
| **Edge Rack** | Factory floor deployment environment running K3s with CloudNativePG for high availability | Backend |
| **Cloud Environment** | Remote infrastructure for model training, Monte Carlo simulations, and digital twin simulations | Backend |
| **K3s** | Lightweight Kubernetes distribution for edge deployment | Backend |
| **CloudNativePG** | Kubernetes operator running the HA TimescaleDB cluster (3 instances, automatic failover, synchronous replication, S3 WAL archiving for PITR). Supersedes the earlier Patroni approach. See `infrastructure/k8s/database-ha/` | Backend |
| **Patroni** | Earlier HA PostgreSQL approach (archived under `infrastructure/k8s/legacy-patroni/`), superseded by CloudNativePG | Backend |
| **KEDA** | Kubernetes Event-Driven Autoscaler — scales the ingestion/export/compliance workers on Redpanda consumer-group lag rather than CPU. See `infrastructure/k8s/autoscaling/` | Backend |
| **SeaweedFS** | S3-compatible object store; shared, multi-pod-safe home for generated export/compliance artifacts and the RAG document store (a worker writes on one pod, the API serves the download from another) | Backend |
| **Sealed Secrets** | Bitnami controller that decrypts committed, encrypted `SealedSecret` CRs into real Secrets in-cluster — lets secrets live safely in git | Backend |
| **External Secrets Operator (ESO)** | Syncs in-cluster Secrets from a central store (Vault / AWS Secrets Manager / GCP SM) via `ExternalSecret` CRs — no secret material in git | Backend |
| **Redpanda** | Kafka-compatible streaming platform for real-time data pipelines | Backend |
| **TimescaleDB** | PostgreSQL extension for time-series data storage | Backend |
| **mTLS** | Mutual TLS authentication for secure device-to-cloud communication | Both |
| **Zero-Trust Networking** | Security model where no device is trusted by default, requiring continuous verification | Backend |
| **Purdue Model** | Industrial cybersecurity reference model isolating manufacturing zones from enterprise/cloud | Backend |
| **Dead Letter Queue (DLQ)** | Queue for failed messages that cannot be processed, supporting schema evolution | Backend |
| **Store-and-Forward** | 24-hour local buffering mechanism for offline resilience at edge agents | Backend |

---

## Manufacturing & Assets

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Asset** | Individual manufacturing equipment (3D printers, CNC machines, conveyors, PLCs) with unique identity and telemetry | Both |
| **Asset Type** | Category defining asset capabilities, PackML configuration, telemetry schema, and action space | Both |
| **Asset ID** | Unique UUID identifier for each asset | Both |
| **Workcell** | Logical grouping of assets within a production line or manufacturing cell | Both |
| **Organization** | Hierarchical entity representing a company, facility, or division with multi-tenant isolation | Both |
| **Serial Number** | Manufacturer-assigned unique identifier for physical equipment tracking | Both |
| **Connection Config** | Protocol-specific configuration (MQTT broker, OPC-UA endpoint, Modbus registers) for asset communication | Backend |
| **Asset Type ID** | Reference to asset type definition defining capabilities and behavior | Both |
| **Maintenance Mode** | Operational state that blocks automated AI commands and requires manual intervention | Both |
| **Vendor** | Equipment manufacturer or supplier | Both |
| **Model** | Specific equipment model number or designation | Both |

---

## Telemetry & Data Collection

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Telemetry** | Time-series sensor data from assets (temperature, pressure, speed, vibration, power) | Both |
| **Telemetry Point** | Single metric reading with timestamp, value, unit, and optional PackML state | Backend |
| **Telemetry Batch** | Collection of telemetry points for efficient bulk ingestion | Backend |
| **Metric Name** | Identifier for specific measurement (e.g., `temp_nozzle_mean`, `spindle_rpm`) | Both |
| **Feature Vector** | Normalized set of telemetry features used as input to AI inference models | Backend |
| **Feature Extraction** | Process of transforming raw telemetry into feature vectors for ML models | Backend |
| **Data Thinning** | Reducing data volume by transmitting feature vectors instead of raw telemetry to cloud | Backend |
| **Collector** | Edge agent component implementing a specific industrial protocol: MQTT, OPC-UA, Modbus, HTTP/REST, EtherNet/IP, PROFINET, BACnet, CAN bus, Screen Scraping, File Watching | Backend |
| **Collector Coordinator** | `UnifiedCollectorCoordinator` — starts/stops all collectors, routes their readings to the store-and-forward buffer and Kafka, and supervises restarts. Selects a collector class per asset by `collector_type` | Backend |
| **Collector Adapter** | Thin wrapper (`collectors/adapter.py`) that bridges `BaseCollector`-style collectors (config-dict init, `emit()` delivery, background-task `start()`) to the coordinator's `on_message_callback` + blocking-`start()` contract | Backend |
| **Ingestion Worker** | Backend service processing incoming telemetry from collectors | Backend |
| **Edge Agent** | Lightweight SDK deployed at edge for data collection and local buffering | Backend |

---

## PackML State Machine

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **PackML** | ISA-TR88 standard state machine for manufacturing equipment control and monitoring | Both |
| **PackML State** | Current operational state of an asset (Idle, Starting, Execute, Held, Suspended, Aborted, Stopped, Completing, Complete, Clearing, Resetting) | Both |
| **State Transition** | Event triggering change from one PackML state to another with duration tracking | Both |
| **Production State** | PackML states contributing to OEE availability calculation (Execute, Running, Processing) | Both |
| **Planned Stop** | Intentional downtime states (Idle, Stopped, Complete, Starting, Clearing, Stopping) | Both |
| **Unplanned Stop** | Unintended downtime states (Aborted, Held, Suspended, Aborting, Holding, Suspending) | Both |
| **State Duration** | Time spent in a specific PackML state, used for OEE calculations | Backend |
| **State Entered At** | Timestamp when asset entered current PackML state | Both |
| **State Exited At** | Timestamp when asset left current PackML state | Both |

---

## OEE (Overall Equipment Effectiveness)

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **OEE** | Overall Equipment Effectiveness - metric measuring manufacturing productivity as Availability × Performance × Quality | Both |
| **Availability** | Percentage of planned production time equipment is actually running (Run Time / Planned Production Time) | Both |
| **Performance** | Ratio of actual cycle time to ideal cycle time (Ideal Cycle Time / Actual Cycle Time) | Both |
| **Quality** | Percentage of good parts produced (Good Parts / Total Parts) | Both |
| **Run Time** | Total time asset spent in production states | Backend |
| **Planned Production Time** | Total time minus planned downtime | Backend |
| **Planned Downtime** | Time in planned stop states (Idle, Stopped, Complete) | Backend |
| **Unplanned Downtime** | Time in unplanned stop states (Aborted, Held, Suspended) | Backend |
| **Ideal Cycle Time** | Target time to produce one part based on asset configuration | Backend |
| **Actual Cycle Time** | Measured time to produce one part (Run Time / Total Parts) | Backend |
| **Part Counter** | Telemetry metric tracking total parts produced, good parts, and rejected parts | Backend |
| **OEE Loss Breakdown** | Analysis of availability, performance, and quality losses for improvement targeting | Backend |
| **OEE Metrics** | Dataclass containing availability, performance, quality, OEE percentage, and supporting metrics | Backend |

---

## AI/ML Engines

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Tactical Engine** | Local edge inference engine for sub-100ms real-time control decisions | Both |
| **Strategic Engine** | Cloud-based engine for macro-optimization and what-if scenario analysis | Both |
| **MLOps Pipeline** | Automated model lifecycle management including download, validation, hot-swap, and rollback | Both |
| **Cloud Gateway** | Secure outbound-only mTLS connection for edge-to-cloud communication | Both |
| **TorchScript** | PyTorch model format optimized for inference at edge | Backend |
| **Model Version** | Identifier for specific model weights and architecture | Both |
| **Hot Swap** | Zero-downtime model replacement without service interruption | Backend |
| **Safety Thresholds** | Hard limits (temperature, vibration, RPM) triggering immediate emergency actions | Backend |
| **Confidence Score** | Probability estimate (0-1) of AI decision correctness | Both |
| **Latency** | Time elapsed from feature vector input to decision output (target <100ms for tactical) | Both |
| **Inference Queue** | Async queue for feature vectors awaiting tactical engine processing | Backend |
| **Recommendation** | Strategic engine proposal requiring operator approval before implementation | Both |
| **Expected Impact** | Predicted outcomes of strategic recommendation (OEE improvement, cost savings) | Both |
| **Model Registry** | Cloud repository storing trained model versions and metadata; OTA release + rollout orchestration to the fleet (`/api/v1/models`, `/api/v1/fleet/releases`) | Backend |
| **Digital Twin** | Simulation model of physical assets for what-if analysis | Backend |
| **Monte Carlo Simulation** | Probabilistic modeling technique for strategic optimization scenarios (`/api/v1/simulation`) | Backend |
| **Health Index** | 0–100 per-asset health score derived from telemetry + anomaly signals; the input to RUL (`/api/v1/health-index`) | Both |
| **Remaining Useful Life (RUL)** | Predictive-maintenance estimate of time-to-failure per asset — the health index mapped onto a Weibull curve; raises a maintenance task when low (`/api/v1/rul`) | Both |
| **Digital-Twin Optimizer** | Generates **approval-gated** strategic recommendations by running the simulation over candidate parameter changes and ranking expected throughput impact; feeds the existing cloud-relay approve/reject queue rather than replacing it (`/api/v1/twin`) | Backend |
| **Historian** | Tenant-scoped time-series query + retention over stored telemetry, independent of live agents (`/api/v1/historian`) | Both |
| **Notifications Center** | Subscribable notification rules (org / severity / channel) with multi-channel delivery (webhook / email / slack) and a delivery log (`/api/v1/notifications`) | Both |
| **Model Monitoring** | Drift / data-drift / prediction-performance tracking for deployed models (`/api/v1/model-monitoring`) | Backend |

---

## Command Execution

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Command** | Instruction sent to asset to perform action (start, stop, adjust parameters) | Both |
| **Command Executor** | Service managing command queuing, execution tracking, and status updates | Backend |
| **Command Status** | State of command execution (pending, executing, completed, failed, cancelled, timeout) | Both |
| **Command Type** | Source category of command (tactical, operator, system) | Backend |
| **Action ID** | Specific command to execute (set_speed, pause_job, emergency_stop) | Backend |
| **Command Queue** | Async queue for commands awaiting execution | Backend |
| **Timeout** | Maximum allowed time for command execution before failure | Backend |
| **Retry** | Automatic re-queuing of failed commands with exponential backoff | Backend |
| **Emergency Stop** | Immediate halt command with highest priority for safety-critical situations | Both |
| **Command History** | Log of all commands executed on an asset with results and timestamps | Both |
| **Issued By** | User or system that initiated the command | Backend |
| **Issued At** | Timestamp when command was submitted | Backend |
| **Executed At** | Timestamp when command began execution | Backend |
| **Command Result** | Outcome of command execution including success status and data/error | Backend |

---

## Yard Management System (YMS)

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Yard Trailer** | Trailer tracked within yard facility with status, location, and detention risk | Both |
| **Trailer Number** | Unique identifier for trailer (license plate or fleet number) | Both |
| **Trailer Type** | Category of trailer (dry_van, reefer, flatbed, tanker, container) | Both |
| **Yard Location** | Physical position of trailer within yard (e.g., "DOCK_3", "ROW_A_12") | Both |
| **Check In** | Process of recording trailer entry to yard facility | Both |
| **Check Out** | Process of recording trailer exit from yard facility | Both |
| **Dock Door** | Loading/unloading bay with equipment capabilities and occupancy status | Both |
| **Dock Door Status** | Current state of door (available, occupied, maintenance, blocked) | Both |
| **Dock Assignment** | Process of assigning trailer to specific dock door | Both |
| **Dock Appointment** | Scheduled time slot for trailer at specific dock door | Both |
| **Appointment Type** | Purpose of appointment (pickup, delivery, transfer) | Both |
| **Detention** | Charge for exceeding free time at facility (typically after 2 hours) | Both |
| **Demurrage** | Charge for excessive unloading time after docking (typically after 1 hour) | Both |
| **Detention Rate** | Hourly charge rate for detention time | Backend |
| **Free Time** | Grace period before detention charges apply | Backend |
| **Yard Move** | Record of trailer repositioning within yard (check_in, dock, yard_relocate, check_out) | Both |
| **Yard Jockey** | Equipment or personnel responsible for moving trailers within yard | Backend |
| **Driver Wait Time** | Tracking of driver time from check-in to check-out for detention calculation | Both |
| **Dwell Time** | Total time trailer spends in yard facility | Both |
| **Yard Checkpoint** | Inspection point (gate_in, guard_shack, weigh_station, gate_out) with pass/fail status | Backend |
| **Seal Number** | Security seal identifier for container integrity verification | Both |
| **Seal Status** | Condition of security seal (intact, broken, missing) | Backend |

---

## Transportation Management System (TMS)

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Carrier** | Transportation company with DOT/MC numbers, insurance, and compliance status | Both |
| **DOT Number** | US Department of Transportation identifier for carrier | Both |
| **MC Number** | Motor Carrier number for interstate commerce authority | Both |
| **CTPAT Certified** | Customs-Trade Partnership Against Terrorism security certification status | Both |
| **Safety Rating** | DOT safety assessment (satisfactory, conditional, unsatisfactory) | Both |
| **CSA Score** | Compliance, Safety, Accountability score for carrier safety performance | Both |
| **Driver** | Individual truck driver with license, endorsements, and HOS tracking | Both |
| **CDL Class** | Commercial Driver License class (A, B, C) | Both |
| **HOS** | Hours of Service - federal regulations limiting driver driving and duty hours | Both |
| **HOS Status** | Current driver duty status (off_duty, sleeper, driving, on_duty) | Both |
| **Hazmat Endorsed** | Certification for transporting hazardous materials | Both |
| **ELD Device** | Electronic Logging Device for automated HOS compliance tracking | Both |
| **Shipment** | Freight movement with origin, destination, schedule, and status tracking | Both |
| **PRO Number** | Progressive Routing Number for shipment tracking | Both |
| **BOL Number** | Bill of Lading document number | Both |
| **PO Number** | Purchase Order reference for shipment | Both |
| **Route** | Planned path with waypoints, distance, duration, and cost estimates | Both |
| **Route Optimization** | Algorithm to find optimal route based on criteria (fastest, cheapest, balanced) | Both |
| **Load Plan** | Arrangement of freight within trailer with weight distribution and space utilization | Both |
| **Freight Charge** | Cost breakdown (linehaul, fuel, detention, demurrage, accessorial) | Both |
| **Vehicle** | Truck or tractor with specifications, maintenance status, and current assignment | Both |
| **VIN** | Vehicle Identification Number | Both |
| **Odometer** | Total distance traveled by vehicle | Both |
| **Engine Hours** | Total operating time of vehicle engine | Both |

---

## GeoTab Integration

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **GeoTab** | Commercial fleet management platform providing GPS tracking, diagnostics, and HOS monitoring | Both |
| **GeoTab Device** | Hardware unit installed in vehicle for telematics data collection | Both |
| **GeoTab Trip** | Recorded journey with start/end locations, distance, duration, and driver behavior events | Both |
| **GeoTab Diagnostic** | Vehicle diagnostic trouble code (DTC) with severity and source system | Both |
| **GeoTab Exception** | Rule violation event (speeding, harsh braking, idling) with location and duration | Both |
| **GeoTab Webhook** | Real-time event notification from GeoTab to OmniusGrid | Backend |
| **DTC Code** | Diagnostic Trouble Code indicating vehicle system malfunction | Both |
| **Harsh Braking** | Safety event indicating sudden deceleration exceeding threshold | Both |
| **Harsh Acceleration** | Safety event indicating rapid acceleration exceeding threshold | Both |
| **Speeding Event** | Violation of posted speed limit | Both |
| **Idle Time** | Duration vehicle engine running while stationary | Both |
| **Geofence** | Virtual geographic boundary triggering alerts on entry/exit | Both |
| **Geofence Alert** | Notification when vehicle crosses geofence boundary | Both |
| **Fleet Summary** | Aggregated status overview of all GeoTab-connected vehicles | Both |

---

## Kanban Task Management

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Kanban Board** | Visual task management interface with columns representing workflow stages | Both |
| **Task Board** | Database entity storing board configuration and metadata | Backend |
| **Board Type** | Category of board (unified, production, maintenance, quality, safety, logistics) | Both |
| **Task Column** | Vertical swimlane representing workflow stage (backlog, triage, in_progress, review, rejected, done) | Both |
| **Column Type** | Workflow stage category | Both |
| **WIP Limit** | Work In Progress limit restricting maximum tasks in column | Both |
| **Task** | Work item with title, description, priority, assignee, and status | Both |
| **Task Type** | Category of work (production_job, maintenance_pm, maintenance_cm, quality_inspection, safety_check, alarm_response, command_execution, material_request, changeover, custom) | Both |
| **Task Priority** | Urgency level (low, medium, high, critical, emergency) | Both |
| **Task Status** | Current state in workflow (draft, ready, in_progress, blocked, completed, cancelled) | Both |
| **Task Assignment** | User or team responsible for completing task | Both |
| **Task Position** | Ordering index within column for drag-and-drop positioning | Both |
| **Checklist Item** | Sub-task within task with completion checkbox | Both |
| **Approval Status** | State of approval workflow (pending, approved, rejected) | Both |
| **Approval Workflow** | Process requiring manager approval before task execution | Both |
| **Task Rule** | Automated trigger creating tasks based on conditions (alarm, schedule, event) | Backend |
| **Trigger Type** | Event category that activates task rule (alarm, schedule, telemetry_threshold) | Backend |
| **Auto-approve Emergency** | Configuration to automatically approve high-priority emergency tasks | Backend |
| **Escalation** | Automatic notification escalation for overdue or blocked tasks | Backend |
| **Task Timer** | Time tracking for task execution with start/stop functionality | Backend |
| **Task Comment** | Discussion thread attached to task for collaboration | Both |
| **Kanban Metrics** | Aggregated statistics (total tasks, by column, by priority, overdue, cycle time) | Both |
| **Workload** | Distribution of tasks across team members for capacity planning | Both |
| **Cycle Time** | Time from task creation to completion | Backend |

---

## Actionable Registries & Compliance

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Actionable Registry** | Structured checklist of compliance or operational requirements with tracking | Both |
| **Registry Type** | Category of registry (safety, quality, environmental, operational, regulatory) | Both |
| **Registry Category** | Sub-category within type for organization (e.g., ISO, OSHA, internal) | Both |
| **Registry Item** | Individual requirement within registry with completion status and verification method | Both |
| **Compliance Registry** | Registry tracking external regulatory requirements (OSHA, ISO, DOT, CTPAT, FSMA) | Both |
| **Operational Registry** | Registry tracking internal operational procedures and best practices | Both |
| **Frequency** | How often registry item must be completed (daily, weekly, monthly, quarterly, annually, as_needed) | Both |
| **Due Date** | Deadline for registry item completion | Both |
| **Compliance Score** | Percentage of registry items completed (0-100) | Both |
| **Risk Score** | Assessment of risk associated with incomplete registry items (0-100) | Both |
| **Priority Level** | Urgency of registry item (low, medium, high, critical) | Both |
| **Assigned Owner** | Person responsible for registry item completion | Both |
| **Assigned Team** | Team responsible for registry item completion | Backend |
| **Severity Level** | Impact level of registry item (minor, major, critical) | Backend |
| **Completion Criteria** | Conditions that must be met to mark item as complete | Backend |
| **Verification Method** | How completion is verified (inspection, audit, documentation, automated) | Backend |
| **Reference URL** | Link to external documentation or standard | Both |
| **Checklist Requirements** | List of sub-steps required for registry item completion | Backend |
| **Data Correlation** | Mapping relationships between tasks, assets, and registry items | Both |
| **Correlation Link** | Connection between entities with severity impact and description | Backend |
| **Cross-Domain Link** | Relationship between different operational domains (e.g., logistics to production) | Backend |

---

## Correlation AI Engine

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Correlation AI Engine** | AI service analyzing cross-domain scenarios to identify root causes and recommend actions | Both |
| **Domain Type** | Operational domain category (47 domains including EDGE_AI_TELEMETRY, PRODUCTION_OEE, LOGISTICS_FLEET, COMPLIANCE_REGISTRIES, SYSTEM_INFRASTRUCTURE, and 42 additional operational domains) | Backend |
| **Correlation Scenario** | Structured representation of operational event across multiple domains with links | Backend |
| **Cross-Domain Link** | Relationship between domains with severity impact and causal description | Backend |
| **Operational Metric** | Key performance indicator within a domain (e.g., OEE, detention rate, alarm count) | Backend |
| **Domain Interaction Component** | Pydantic-based schema validation for 47 operational domains | Backend |
| **Synthetic Data Generation** | LLM-powered creation of training scenarios using state space rules | Backend |
| **State Space** | Collection of valid entities (assets, errors, logistics, compliance, maintenance, safety, production, client yard) for realistic scenario generation | Backend |
| **Gemma 4** | Google AI model used for correlation inference (placeholder in current implementation) | Backend |
| **Fine-Tuning Dataset** | JSONL format training data with system prompts, user inputs, and model outputs | Backend |
| **Root Cause Analysis** | AI identification of primary trigger in cascading failure scenarios with multi-perspective analysis | Backend |
| **Multi-Perspective Analysis** | Root cause analysis considering multiple viewpoints (driver, client, transport, yard) for liability determination | Backend |
| **Liability Determination** | Process of identifying responsible party for operational issues (driver, client, transport management, yard management) | Backend |
| **Risk Scoring** | AI assessment of scenario severity based on domain criticality and link severity | Backend |
| **Target Kanban Tasks** | AI-recommended tasks to address identified issues | Backend |
| **Remediation Commands** | AI-recommended API commands to execute for resolution | Backend |
| **Compliance Implications** | AI-identified regulatory standards impacted by scenario | Backend |
| **Scenario Validation** | Pydantic schema verification of scenario data structure | Backend |
| **State Space Loader** | Utility loading state space JSON files for scenario generation with nested category support | Backend |
| **Scenario Generator** | Component creating synthetic scenarios using state space data with enhanced narrative templates | Backend |
| **Detention Scenario** | Logistics scenario identifying root cause of trailer delay with liability assignment | Backend |
| **Yard Bottleneck** | Operational constraint in yard operations (dock congestion, gate delays, parking constraints) | Backend |
| **Shop Floor Impact** | Production line effect from logistics delays (material starvation, production stop, OEE degradation) | Backend |
| **Predictive Indicator** | Early warning sign of equipment failure (vibration analysis, thermal analysis, oil analysis, performance degradation) | Backend |
| **Preventive Trigger** | Condition requiring preventive maintenance (time-based, usage-based, condition-based) | Backend |
| **Maintenance Conflict** | Scheduling or resource constraint preventing maintenance (production schedule conflict, resource unavailability) | Backend |
| **Maintenance Escalation** | Transition from predictive to preventive to corrective to emergency maintenance | Backend |
| **Safety Incident Causation** | Root cause analysis of safety events (human factors, equipment factors, environmental factors, organizational factors) | Backend |
| **Safety Protocol Violation** | Breach of safety procedures (LOTO violations, confined space violations, hot work violations) | Backend |
| **Operational Efficiency** | Performance metrics and barriers affecting productivity (cycle time, throughput, resource utilization) | Backend |
| **Security Scenario** | Physical, cyber, or operational security event (unauthorized access, phishing, trade secret exposure) | Backend |
| **Production Constraint** | Limitation affecting production output (capacity constraints, scheduling conflicts, process constraints) | Backend |
| **Shift Handover** | Process of transferring information between shift changes with potential communication gaps | Backend |
| **Client Yard Scenario** | External yard management scenario with liability types and receiving capacity issues | Backend |
| **Narrative Template** | Pre-defined text pattern for generating realistic root cause descriptions with multiple variations | Backend |
| **Severity Context** | Contextual description based on severity level (critical, high, medium, low) for actionable recommendations | Backend |

---

## Cross-Tab Workbook Correlation & Intake

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Intake Inbox** | Upload area where operational files (spreadsheets, reports, images, documents) are stored and analyzed by the correlation AI | Both |
| **Multi-Tab Workbook Parsing** | Reading every sheet of an Excel workbook (`pd.read_excel(sheet_name=None)`), not just the first; CSV is treated as a single tab | Backend |
| **Tab → Domain Mapping** | Deterministic mapping of each workbook tab to one of the 47 `DomainType` values, by tab name with a column-keyword fallback (`spreadsheet_domain_mapper.py`) | Backend |
| **Context-Only Tab** | A tab that cannot be mapped to a domain; retained as metadata but not emitted as operational metrics | Backend |
| **Cross-Tab Correlation** | Discovery of correlations *between* tabs/domains within one workbook via shared keys and co-timed anomalies | Both |
| **Spreadsheet Scenario Builder** | Service converting parsed tabs into `CorrelationScenario` objects (`spreadsheet_scenario_builder.py`) | Backend |
| **Scenario Mode** | Strategy for turning tabs into scenarios: `window` (per date/shift, default), `tab` (one per workbook), `row` (one per row) | Backend |
| **Window Scenario** | A scenario grouping rows from all tabs that share the same `date`(+`shift`) key, enabling cross-domain links | Backend |
| **Interaction Key** | The unifying token (e.g. `asset_id`) used by `CrossDomainLink` to relate metrics from different domains | Backend |
| **Severity Mapping** | Mapping of status values to `severity_impact` (normal 0.0–0.3, warning 0.3–0.7, critical 0.7–1.0) | Backend |
| **Full Coverage** | Guarantee that all date/shift windows are emitted as scenarios (no sampling) in `window` mode | Backend |
| **Stress-Test Dataset** | Synthetic 100-company × 10-fiscal-year corpus (1,000 multi-tab workbooks) with clustered, co-timed anomalies, generated under `dataset_synthesis/` | Backend |
| **Industry Specialty Tab** | An industry-specific workbook tab (e.g. biogas methane output, t-shirt screen count, tractor engine specs) included per company type | Backend |
| **Compatibility Outputs** | OmniusGrid-native exports derived from workbooks: per-tab CSV, long-format telemetry, and `CorrelationScenario` JSONL | Backend |

---

## Intake Cross-Correlation Enhancement

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **PDF Parser** | Service extracting structure (pages, headers, tables, text blocks, metadata) from PDF files using `pdfplumber` and `PyPDF2` | Backend |
| **DOCX Parser** | Service extracting heading hierarchy, sections, tables, and metadata from DOCX files using `python-docx` | Backend |
| **Image Text Extractor** | Service extracting text from images using Google Gemini multimodal vision model | Backend |
| **Shared Key** | Normalized identifier (asset_id, order_number, date) extracted from filename, metadata, or content for cross-file correlation | Backend |
| **Shared Key Detector** | Service extracting and normalizing shared keys from text, filenames, metadata, and structured records | Backend |
| **Key Normalization** | Process converting keys to uppercase, replacing underscores/hyphens, trimming whitespace for consistent matching | Backend |
| **Document Domain Mapper** | Service mapping document sections to operational domains based on header, table content, and body text keyword matching | Backend |
| **Image Domain Mapper** | Service mapping image text and metadata to domains with image-specific keywords | Backend |
| **Document Scenario Builder** | Service converting parsed document structures into CorrelationScenario objects (section, document, table modes) | Backend |
| **Image Scenario Builder** | Service converting image extractions into scenarios (image, batch modes) | Backend |
| **Cross-File Scenario Builder** | Service building scenarios linking multiple intake items/data sources by shared keys | Backend |
| **Cross-File Correlation** | Process of linking multiple intake items by shared keys for cross-file analysis | Both |
| **Section Mode** | Scenario building mode creating one scenario per document section | Backend |
| **Document Mode** | Scenario building mode creating one scenario for entire document | Backend |
| **Table Mode** | Scenario building mode creating one scenario per table | Backend |
| **Image Mode** | Scenario building mode creating one scenario per image | Backend |
| **Batch Mode** | Scenario building mode creating one scenario for all images | Backend |
| **Structure Metadata** | JSON field storing document structure info (page_count, section_count, tables, headers) | Backend |
| **Processing Time Estimate** | Estimated time in seconds to process a document based on type and size | Backend |
| **Scenario Cap** | Maximum number of scenarios generated for large documents to prevent excessive processing | Backend |
| **Vision Model** | AI model for image text extraction (Google Gemini) | Backend |
| **Vision Model Enabled** | Configuration flag to enable/disable image text extraction | Backend |
| **Vision Model Provider** | Provider of vision model (gemini) | Backend |
| **Vision Model Name** | Specific model name (gemini-1.5-pro) | Backend |
| **Max Image Bytes** | Maximum image size in bytes for vision model processing (10MB default) | Backend |
| **Correlation Group** | Group of data sources linked by shared keys for cross-file analysis | Backend |
| **Manual Shared Keys** | User-specified keys to force correlation when auto-detection fails | Backend |
| **Auto-Detection** | Automatic detection of shared keys across multiple data sources | Backend |
| **Domain Aggregation** | Process of aggregating domains across all correlated sources | Backend |
| **Cross-File Link** | Connection between different files/data sources via shared keys | Backend |
| **Session Correlation** | Correlation of all data sources within an analysis session by shared keys | Backend |
| **Intake Cross-Correlation Endpoint** | API endpoint for correlating arbitrary intake items by shared keys | Backend |
| **Session Correlation Endpoint** | API endpoint for correlating all session data sources by shared keys | Backend |

---

## Frontend Architecture

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **React 18** | Frontend UI library using functional components and hooks | Frontend |
| **TypeScript** | Typed superset of JavaScript for type safety | Frontend |
| **Vite** | Build tool and development server for fast hot module replacement | Frontend |
| **Zustand** | Lightweight state management library replacing Redux | Frontend |
| **React Query** | Data fetching and caching library for API calls | Frontend |
| **React Router** | Client-side routing for single-page application navigation | Frontend |
| **TailwindCSS** | Utility-first CSS framework for styling | Frontend |
| **Lucide React** | Icon library for UI components | Frontend |
| **Recharts** | Charting library for data visualization | Frontend |
| **Leaflet** | Open-source mapping library for fleet tracking | Frontend |
| **React Leaflet** | React wrapper for Leaflet integration | Frontend |
| **Axios** | HTTP client for API requests | Frontend |
| **WebSocket** | Real-time bidirectional communication for live updates | Both |
| **API Client** | Frontend service encapsulating HTTP requests to backend API | Frontend |
| **Mock API** | Development mode using simulated data instead of backend | Frontend |
| **Component** | Reusable UI building block (Button, Card, Input, Badge, Table, etc.) | Frontend |
| **Page** | Route-level component representing full-screen view (Dashboard, Assets, Alarms, etc.) | Frontend |
| **Hook** | Custom React function encapsulating reusable logic (useAuth, useWebSocket, useTelemetry) | Frontend |
| **Store** | Zustand state container for global state management (authStore, kanbanStore, realtimeStore) | Frontend |
| **Type Definition** | TypeScript interface defining data structure (Asset, Alarm, Telemetry, etc.) | Frontend |
| **Protected Route** | Route requiring authentication and authorization check | Frontend |
| **Sidebar** | Navigation component with collapsible menu items | Frontend |
| **Header** | Top navigation bar with user menu and notifications | Frontend |
| **Layout** | Component wrapping pages with consistent structure (Sidebar, Header) | Frontend |

---

## Security & Authentication

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **JWT** | JSON Web Token for stateless authentication | Both |
| **Bearer Token** | Authorization header format for API requests | Both |
| **RBAC** | Role-Based Access Control for permission management | Both |
| **User Role** | Permission level (admin, operator, viewer, maintenance) | Both |
| **Permission** | Granular access right (resource + action: create, read, update, delete, manage) | Frontend |
| **mTLS Certificate** | X.509 certificate for mutual TLS authentication | Backend |
| **Certificate Revocation** | Process of invalidating compromised device certificates | Backend |
| **Device Provisioning** | Workflow for generating and distributing mTLS certificates to edge devices | Backend |
| **Audit Trail** | Tamper-evident logging with cryptographic hash chaining | Backend |
| **Hash Chaining** | Method of linking log entries cryptographically to prevent tampering | Backend |
| **Zero-Trust** | Security model assuming no implicit trust, requiring continuous verification | Backend |
| **Purdue Model** | Network segmentation isolating manufacturing from enterprise zones | Backend |
| **API Key** | Secret token for programmatic API access (e.g., GeoTab integration) | Backend |
+(d1031146, 6d8893b3, b7d2e2c6)| **API Key Hash** | SHA256 hash of API key stored in database for security | Backend |
| **API Key Scope** | Permission scope assigned to API key (read, write, admin) | Backend |
| **API Key Expiration** | Date when API key becomes invalid | Backend |
| **Rate Limiting** | API request rate control (100 req/min per user, 1000 req/min global) | Backend |
| **Slowapi** | Python library for rate limiting with Redis backend | Backend |
| **CSRF Protection** | Cross-site request forgery prevention middleware for state-changing operations | Backend |
| **CSRF Token** | Security token validating request origin | Backend |
| **Session Management** | User session tracking with refresh, invalidation, and limits | Backend |
| **Session Timeout** | Maximum session duration (30 minutes) | Backend |
| **Concurrent Sessions** | Maximum simultaneous sessions per user (3) | Backend |
| **Session Invalidation** | Process of revoking active user sessions | Backend |
| **Secrets Management** | Secure storage and encryption of sensitive configuration | Backend |
| **Fernet** | Symmetric encryption algorithm (AES-128) for secrets | Backend |
| **Key Rotation** | Periodic replacement of encryption keys | Backend |
| **Security Headers** | HTTP response headers for security (CSP, HSTS, X-Frame-Options) | Backend |
| **Content Security Policy** | CSP header controlling resource loading sources | Backend |
| **HSTS** | HTTP Strict Transport Security header enforcing HTTPS | Backend |
| **X-Frame-Options** | Header preventing clickjacking attacks | Backend |
| **Permissions-Policy** | Header controlling browser feature access | Backend |
| **Session** | User authentication state with expiration and refresh capability | Frontend |
| **Login Credentials** | Email and password for user authentication | Frontend |
| **Remember Me** | Option to persist session across browser restarts | Frontend |
| **Dev Token** | Development mode authentication bypass token | Frontend |

---

## Compliance Frameworks

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **GDPR** | General Data Protection Regulation - EU data protection law | Both |
| **Right to be Forgotten** | GDPR right allowing users to request deletion of personal data | Backend |
| **Data Portability** | GDPR right allowing users to export their data in machine-readable format | Backend |
| **Consent Management** | System for tracking user consent for data processing activities | Backend |
| **Consent Record** | Database record of user consent with type, date, method, and withdrawal status | Backend |
| **Data Processing Record** | GDPR documentation of data processing activities, categories, purposes, and legal basis | Backend |
| **SOC 2** | Service Organization Control 2 - security compliance framework for service providers | Both |
| **Vendor Risk Assessment** | Evaluation of third-party vendor security posture and compliance | Backend |
| **Security Asset** | ISO 27001 tracked asset with classification, owner, and location | Backend |
| **Asset Classification** | ISO 27001 categorization (public, internal, confidential, restricted) | Backend |
| **Asset Inventory** | ISO 27001 comprehensive list of all organizational assets | Backend |
| **ISO 27001** | International standard for information security management systems | Both |
| **Cryptography** | ISO 27001 encryption standards and key management practices | Backend |
| **Key Rotation** | Periodic replacement of encryption keys (90-day cycle for certificates) | Backend |
| **Access Control** | ISO 27001 policies for granting and revoking system access | Backend |
| **Data Residency** | Geographic location control for data storage (USA compliance) | Backend |
| **Data Residency Tag** | Database record linking data to geographic region for compliance | Backend |
| **Compliance Report** | Automated generation of compliance status across frameworks | Backend |
| **Compliance Summary** | Aggregated view of compliance metrics across GDPR, SOC 2, and ISO 27001 | Backend |

---

## Testing Infrastructure

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Offline Demo Seeder** | `backend/scripts/seed_demo_data.py` — populates every page with correlated demo data so the whole platform runs with no live edge/cloud/services (idempotent). Only Correlation-AI *inference* still needs its model. See `docs/DEMO.md` | Backend |
| **Schema-parity check** | Guard that ORM `Base.metadata` matches the migrated Postgres schema (columns, nullability, types **and server defaults**) — prevents the ORM↔migration drift that only surfaces on a real DB (SQLite `create_all` hides it) | Backend |
| **Tenant session (`get_tenant_db`)** | The FastAPI dependency that opens a session AND sets the `app.current_org_id` GUC that RLS policies read. Using plain `get_db` on an RLS-protected table returns ZERO rows without erroring — the failure mode behind the empty dashboard and the silently empty audit trail. Enforced by `test_tenant_session_guard.py` | Backend |
| **Quiet-failure bug class** | A defect that returns empty/NULL instead of raising, so tests and UIs look healthy: RLS filtering every row when the tenant GUC is unset, or a raw INSERT writing NULL `created_at` so the row drops out of time-ordered queries. Both are now guarded | Backend |
| **Server default (timestamps)** | `DEFAULT NOW()` in the DATABASE, as opposed to an ORM-side `default=utcnow` that only fires through SQLAlchemy. Migrations 044/045 added the defaults and back-filled existing NULLs from each row's own event timestamp | Backend |
| **Demo-data gating** | Four `*_populate_*` migrations insert sample rows and used to run on every deployment; `migrate.py` now skips them unless `--with-dev-fixtures`. `backend/scripts/seed_demo_data.py` is the sanctioned source of demo data | Backend |
| **k6** | Modern load testing tool for HTTP API performance testing | Backend |
| **Ingestion Load Generator** | `tests/load/ingestion_load.py` — async Kafka producer that floods the telemetry topics (the ingestion worker's exact contract) to drive KEDA ingestion-worker scaling and the TimescaleDB write path under load | Backend |
| **Load Test** | Performance test simulating high user load (1000 concurrent users, 10k req/sec) | Backend |
| **backend-realdb** | The blocking CI gate that runs the real-DB guards against an ephemeral TimescaleDB (testcontainers): schema parity, tenant isolation + RLS, dashboard tenancy, timestamp defaults, backup/restore drill. Exists because RLS and server defaults are no-ops on SQLite, so a green SQLite run proves nothing | Backend |
| **migration-hygiene** | Blocking CI gate running `check_migrations.py` (no new duplicate prefixes) plus the chain guards: no data-only migrations, the 019 gap pinned, demo fixtures still gated | Backend |
| **k8s-manifests / k8s-smoke** | Blocking CI gates: `k8s-manifests` builds + kubeconform-validates every kustomization; `k8s-smoke` spins a kind cluster, applies the monitoring stack, and validates the CNPG + KEDA custom resources against the real operators' webhooks | Backend |
| **Concurrent Users** | Number of simultaneous users during load test | Backend |
| **Requests Per Second** | Target throughput metric for load testing | Backend |
| **Response Time Threshold** | Performance target (95% under 500ms, 99% under 1s) | Backend |
| **Error Rate Threshold** | Maximum acceptable error rate (<1%) | Backend |
| **Chaos Engineering** | Practice of testing system resilience by introducing failures | Backend |
| **Failure Scenario** | Specific test case for chaos engineering (database failure, network partition) | Backend |
| **Database Failover** | Chaos test simulating primary database failure | Backend |
| **Message Broker Failure** | Chaos test simulating Redpanda unavailability | Backend |
| **Backend Crash** | Chaos test simulating backend service termination | Backend |
| **Network Partition** | Chaos test simulating network connectivity loss | Backend |
| **High Latency** | Chaos test simulating degraded network performance | Backend |
| **Resource Exhaustion** | Chaos test simulating CPU/memory constraints | Backend |
| **Certificate Expiration** | Chaos test simulating expired TLS certificates | Backend |
| **Data Loss Scenario** | Chaos test simulating data corruption or deletion | Backend |
| **RTO** | Recovery Time Objective - target time to restore service after failure | Backend |
| **RPO** | Recovery Point Objective - maximum acceptable data loss | Backend |

---

## Observability & Monitoring

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Prometheus** | Time-series database for metrics collection and alerting. In-cluster it discovers targets via the Kubernetes API (backend `/metrics`, the four background workers on :9109, Redpanda, kube-state-metrics, CloudNativePG) | Backend |
| **Grafana** | Visualization platform for metrics dashboards; deployed in the k8s monitoring stack with a provisioned "Platform / Infra" dashboard (HA-DB / autoscaling / backups) | Backend |
| **kube-state-metrics** | Exposes Kubernetes object state (pod/replica/HPA/PVC status, Job/CronJob success, restart counts) as Prometheus metrics — the source for autoscaling and backup alerts | Backend |
| **Platform / Infra Dashboard** | Grafana dashboard for the enterprise stacks: CNPG instances/replication lag, worker replicas current-vs-max, consumer lag, backup age + failures | Backend |
| **Loki** | Log aggregation system for centralized logging | Backend |
| **Alertmanager** | Alert routing and notification management for Prometheus; k8s secrets (Slack/PagerDuty) injected via `*_file` refs, routing by severity | Backend |
| **Metrics** | Numerical measurements of system behavior (request rate, error rate, latency) | Backend |
| **Structured Logging** | JSON-formatted logs with consistent schema for parsing and analysis | Backend |
| **Structlog** | Python library for structured logging | Backend |
| **Health Probe** | HTTP endpoint for service liveness and readiness checks | Backend |
| **Role vocabulary** | The ordered set viewer < operator < admin, defined once in `app/core/roles.py` and enforced by a CHECK constraint (migration 048). Previously a bare `String(50)` with no constraint and three duplicated copies of the list, so a typo stored fine and then matched no permission check | Backend |
| **`require_at_least`** | Dependency expressing a privilege FLOOR rather than an enumerated set. An enumerated set has no ordering, which is how two read-only endpoints ended up denying `operator` while allowing `viewer` | Backend |
| **Last-admin guard** | Refuses to demote or deactivate the final active admin in an organization. Losing it is unrecoverable through the product — nobody left can manage users | Backend |
| **Deactivate (not delete)** | `DELETE /users/{id}` sets `is_active = false`. Users are referenced by `alarms.acknowledged_by` and `alarm_rules.created_by`, so removing the row would break those references or erase who did what | Both |
| **Alarm Rule** | An operator-defined threshold evaluated server-side against incoming telemetry (metric, comparator, threshold, duration, hysteresis, severity, target). Before these existed, severity was whatever the edge agent sent and nothing evaluated telemetry, so "alert when temperature > 80 for 5 minutes" was unexpressible | Both |
| **Duration window** | How long a breach must persist before a rule fires. 0 fires on the first breaching reading. Non-zero makes a rule a statement about a window rather than one sample, which is why evaluation keeps per-(rule, asset) state in Redis | Backend |
| **Hysteresis** | Clear band in the metric's own units. The value must return past the threshold by this much before the breach counts as over, so a reading sitting on the threshold does not raise and clear an alarm on every sample | Backend |
| **Breach store** | Redis-backed per-(rule, asset) record of when a breach began and whether it already fired, shared across ingestion replicas. Degrades to per-process on a Redis outage — never fails the telemetry write | Backend |
| **Heartbeat Liveness** | Liveness judged by whether a worker is still *doing work*, not whether its process exists. A worker records a beat per completed unit of work and `/healthz` fails once the last beat exceeds its staleness window — the only way to detect a wedged consumer (process alive, loop dead) | Backend |
| **Worker Health Endpoint** | `/metrics`, `/healthz` and `/readyz` served on port 9109 by each background worker (`app/workers/health_server.py`). Before it existed the workers exposed nothing, so probes had no path to hit and Prometheus scraped nothing | Backend |
| **Staleness Window** | Per-worker `stale_after_seconds`. Set to 300s for ingestion (continuous telemetry, so a gap is genuinely wrong) and **disabled** for the event-driven export / compliance / OTA workers, which can legitimately idle for hours | Backend |
| **`opsgrid_worker_heartbeat_age_seconds`** | Gauge of seconds since a worker last completed a unit of work, labelled by `worker` so one scrape job covers all four. Drives the `WorkerStalled` alert | Backend |
| **`opsgrid_workers` (alert group)** | `WorkerStalled` (ingestion heartbeat > 10m — the probe's restart has failed to cure it), `WorkerDown` (metrics endpoint unreachable), `WorkerCrashLooping` (> 2 restarts in 30m). See [kafka-consumer-lag.md](docs/runbooks/kafka-consumer-lag.md) | Backend |
| **Systemd Watchdog** | Linux service monitoring and automatic restart on failure | Backend |
| **HA Failover** | High availability automatic failover to standby instance | Backend |
| **Disaster Recovery** | Process of restoring service after catastrophic failure | Backend |
| **pgBackRest** | PostgreSQL backup and WAL archiving solution | Backend |
| **Point-in-Time Recovery** | Database restoration to specific timestamp using WAL archives | Backend |
| **Continuous Aggregates** | TimescaleDB feature for automatic downsampling of time-series data | Backend |
| **Dashboard** | Grafana visualization panel displaying related metrics | Backend |
| **Alert Rule** | Prometheus rule defining when to trigger alert based on metric thresholds | Backend |
| **Notification Channel** | Destination for alert notifications (email, Slack, PagerDuty) | Backend |
| **Service Endpoint** | URL for accessing specific service (API, Grafana, Prometheus) | Both |

---

## Appendix: Protocol-Specific Terminology

### MQTT
| Term | Definition |
|------|------------|
| **MQTT** | Message Queuing Telemetry Transport - lightweight publish/subscribe protocol |
| **Broker** | MQTT server receiving and distributing messages |
| **Topic** | Hierarchical string for message routing (e.g., `printer/telemetry/temperature`) |
| **QoS** | Quality of Service level (0, 1, 2) for message delivery guarantees |
| **TLS** | Transport Layer Security for encrypted MQTT connections |
| **Bambu Labs** | 3D printer manufacturer using MQTT for telemetry |

### OPC-UA
| Term | Definition |
|------|------------|
| **OPC-UA** | Open Platform Communications Unified Architecture - industrial automation protocol |
| **Endpoint** | Network address of OPC-UA server |
| **Node** | Addressable object in OPC-UA address space |
| **Tag** | Data point identifier in OPC-UA server |
| **PLC** | Programmable Logic Controller - industrial computer controlling manufacturing equipment |

### Modbus
| Term | Definition |
|------|------------|
| **Modbus TCP** | Modbus protocol over Ethernet |
| **Modbus RTU** | Modbus protocol over serial RS-485 |
| **Register** | Memory location for data storage (holding register, input register) |
| **Slave ID** | Device identifier in Modbus network |
| **VFD** | Variable Frequency Drive - motor controller using Modbus |

### Screen Scraping/OCR
| Term | Definition |
|------|------------|
| **Screen Scraping** | Capturing display output from equipment without API access |
| **OCR** | Optical Character Recognition - extracting text from images |
| **OpenCV** | Computer vision library for image processing |
| **Tesseract** | OCR engine for text extraction from images |
| **QIDI/SOVOL** | 3D printer brands requiring screen scraping for data collection |

### File Watching
| Term | Definition |
|------|------------|
| **File Watcher** | Monitor for file system changes (creation, modification, deletion) |
| **G-code** | Numerical control programming language for CNC machines and 3D printers |
| **ORCA Slicer** | 3D printing slicer software generating G-code output |
| **Inotify** | Linux kernel subsystem for file system event notification |

### HTTP/REST
| Term | Definition |
|------|------------|
| **HTTP/REST Collector** | Polls REST endpoints at a configurable interval (GET/POST, custom headers, params, basic auth) |
| **httpx** | Async HTTP client library used by the collector |
| **Poll Interval** | Configurable seconds between endpoint reads (default 60s) |

### EtherNet/IP
| Term | Definition |
|------|------------|
| **EtherNet/IP** | Industrial protocol for Rockwell/Allen-Bradley PLCs (default port 44818) |
| **Slot** | CPU slot index in the PLC chassis |
| **Tag** | Named PLC variable read by the collector |
| **pylogix** | Driver library backing the collector |

### PROFINET
| Term | Definition |
|------|------------|
| **PROFINET** | Industrial Ethernet protocol for Siemens PLCs |
| **Rack / Slot** | Address of the S7 CPU within the PLC chassis |
| **DB Block** | Siemens data block read for telemetry |
| **Field** | Typed value (real/int/dint/word/bool/byte) decoded at an offset within a DB block |
| **python-snap7** | Driver library backing the collector |

### BACnet
| Term | Definition |
|------|------------|
| **BACnet** | Building Automation and Control network protocol (default port 47808) |
| **Device ID** | Unique identifier of a BACnet device |
| **Object** | Addressable point (e.g., analog input) read from a BACnet device |
| **presentValue** | Default property read from each object |
| **BAC0 / bacpypes** | Driver library backing the collector |

### CAN Bus
| Term | Definition |
|------|------------|
| **CAN Bus** | Controller Area Network for vehicle/machine controllers |
| **Channel** | CAN interface (e.g., `can0` via SocketCAN) |
| **Bitrate** | Bus speed in bits/sec (default 500000) |
| **CAN ID** | Arbitration identifier used to filter frames |
| **python-can** | Driver library backing the collector |

---

## Appendix: Database Schema Terminology

| Term | Definition |
|------|------------|
| **UUID** | Universally Unique Identifier - 128-bit identifier for database primary keys |
| **AsyncSession** | SQLAlchemy async database session for non-blocking queries |
| **Pydantic** | Data validation library using Python type annotations |
| **BaseModel** | Pydantic base class for schema definitions |
| **Field** | Pydantic field descriptor with validation rules |
| **from_attributes** | Pydantic config enabling ORM model to schema conversion |
| **Alembic** | Database migration tool for SQLAlchemy |
| **Migration** | Schema change script for database version control |
| **TimescaleDB Hypertable** | Time-series table partitioned by time for performance |
| **Continuous Aggregate** | Pre-computed aggregation of time-series data for faster queries |
| **WAL** | Write-Ahead Log - transaction log for database recovery |
| **S3** | Amazon Simple Storage Service for backup storage |

---

## Appendix: Frontend UI Components

| Component | Purpose |
|-----------|---------|
| **Button** | Clickable action trigger with variants (primary, secondary, danger, ghost, outline) |
| **Card** | Container for grouped content with elevation |
| **Input** | Text input field with validation; label/error auto-associated via `useId` + `aria-describedby` |
| **Modal** | Accessible dialog primitive — `role="dialog"` + `aria-modal`, focus trap, Escape/backdrop close, focus restore, scroll-lock. Base for all app modals |
| **DialogProvider / useDialog** | Promise-based, accessible replacements for native `alert`/`confirm`/`prompt`, rendered via `Modal`; mounted at the app root |
| **Select** | Dropdown selection from options |
| **Badge** | Small status indicator with color coding |
| **Table** | Data grid with sorting and pagination |
| **Skeleton** | Loading placeholder shimmer effect |
| **ChartContainer** | Wrapper for Recharts with responsive sizing |
| **PackMLBadge** | Badge displaying PackML state with color coding |
| **SeverityBadge** | Badge displaying alarm severity with color coding |
| **StatusIndicator** | Visual indicator (dot) showing online/offline status |
| **TimeAgo** | Relative time display (e.g., "5 minutes ago") |
| **CommandPanel** | UI for submitting and monitoring commands |
| **KanbanBoard** | Drag-and-drop task board with columns |
| **KanbanColumn** | Vertical swimlane for task grouping |
| **KanbanCard** | Individual task card with metadata |
| **TaskDetailModal** | Modal dialog for task editing and comments |
| **CreateTaskModal** | Modal dialog for new task creation |
| **FleetTrackerMap** | Leaflet map displaying vehicle positions |
| **GeoTabIntegration** | Panel for GeoTab device status |
| **GeofencingPanel** | UI for managing geofence zones |
| **HealthSecurityPanel** | Vehicle health and security status |
| **MaintenancePanel** | Maintenance scheduling and history |
| **PerformancePanel** | KPI widgets and metrics |
| **RealtimeTelemetryChart** | Live telemetry line chart with WebSocket updates |

---

**Document Version:** 1.3  
**Last Updated:** 2026-07-24  
**System:** OmniusGrid v0.1.0  
