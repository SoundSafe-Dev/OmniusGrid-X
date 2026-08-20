# OmniusGrid System Glossary

**Backend & Frontend Combined Terminology Reference**

Last reviewed **2026-08-18**. Terms are defined by what the code does rather than by what the
feature was called when it was planned — several rows below say "this used to claim X and did
Y", because a glossary that records only the intended meaning is how the intended meaning
survives the implementation diverging from it.

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
- [Interaction & Feedback](#interaction--feedback)
- [Security & Authentication](#security--authentication)
- [Compliance Frameworks](#compliance-frameworks)
- [DDIL & Edge Resilience](#ddil--edge-resilience)
- [Cryptography & FIPS](#cryptography--fips)
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
| **`timestamp_edge`** | When the reading was taken, by the device's clock, **corrected** by the measured server-clock offset at send time. See `time_quality` for how far to trust the correction | Both |
| **`timestamp_edge_raw`** | The same instant, uncorrected. Ground truth, kept because an estimate later found wrong is only recoverable if the unadjusted value survived | Both |
| **`time_quality`** | `synced` \| `holdover` \| `unsynced` \| `unknown` — what a row's timestamp is worth. Queryable, and indexed for the degraded values only, because the useful question is which readings *cannot* be trusted for ordering | Both |
| **`sequence_num`** | Per-asset monotonic counter from the edge, surviving backfill so gaps are detectable independently of timestamps | Both |
| **Backfilled reading** | A row delivered from the store-and-forward buffer after an outage rather than live. Carries `backfilled: true`; ordering within a priority tier is preserved | Both |
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
| **Quarantine (ingest)** | A reading that fails structural validation at `POST /api/v1/edge/ingest` is set aside rather than accepted. "Set aside" is literal: the reading is **retained** in `IngestResult.quarantined` and published to a dead-letter topic. It previously incremented a counter while the payload was discarded, so the endpoint reported `quarantined: N` for readings that existed nowhere | Backend |
| **Dead-letter topic (`telemetry.dlq.<agent_id>`)** | Where quarantined readings land, keyed on the **certificate-verified `agent_id`**, never on `asset_id`. A reading that failed validation cannot be trusted for routing — the malformed field may *be* `asset_id` — and "which agent is emitting garbage" is the question the topic exists to answer | Backend |

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
| **Tactical Engine** | Local edge inference engine for sub-100ms real-time control decisions. **Not currently started** — `start()` is absent from `main.py`, unlike the seven engines that are | Both |
| **Command dispatch (tactical)** | `_dispatch_command` returns `False` and `execute_decision` returns `False` with it, because the engine has no command sink wired. Deliberate: the real sink (`command_executor`) exists and runs, but connecting it switches on autonomous actuation of industrial assets — a decision with a safety review attached. It previously logged `tactical_decision_executed` and returned `True` for a command that reached no asset | Backend |
| **`dispatched` (training feedback)** | Field on the `tactical_decision` event queued to the cloud. A decision that never reached the asset produced no outcome to learn from, so labelling it as actuated would train the model on something that did not happen | Backend |
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
| **Timeout** | Two distinct things share the name. `timeout_seconds` on a dispatched command is how long execution may take — and since FS-752 it is also the basis of an EXPIRY check on the edge: a command whose issue time plus timeout has passed is refused before the actuator is touched. The field was validated and then discarded for years, so a days-old actuation replayed verbatim on reconnect | Both |
| **Retry** | Automatic re-queuing of failed commands with exponential backoff | Backend |
| **Emergency Stop** | Immediate halt for safety-critical situations. "Highest priority" is now enforced where it matters rather than only asserted: `emergency_stop` is a tier-1 metric in the edge buffer, so it drains ahead of every buffered reading when a link returns and is the last thing shed when the buffer fills. Before FS-754 it queued behind the backlog like anything else | Both |
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

## Interaction & Feedback

What the user sees while a request is in flight, when it fails, and when an action succeeds.
Every row was measured across all 37 pages before the primitive existed.

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **`ErrorState`** | The shared failure component: an announced message (`role="alert"`, not colour alone) and an optional retry. Replaces 65 dead ends that offered a sentence in red and nothing else | Frontend |
| **Dead-end failure state** | A failure whose only recovery is a full page reload — which discards filters, the selected time range, scroll position and anything half-typed elsewhere. A transient 502 on one panel therefore cost the operator their whole working state | Frontend |
| **`onRetry` is optional** | Deliberately. A deleted record, or a permission this session will never have, gets the message without a button: a retry that cannot work is worse than none, because the user clicks it repeatedly and concludes the product is broken rather than that the answer is no | Frontend |
| **Self-healing failure** | A failure on a polling query that says "Retrying automatically…" and genuinely carries a `refetchInterval`. **Not** a dead end — and counting it as one would have pressured somebody into adding a Retry button that duplicates a poll | Frontend |
| **`ToastProvider`** | Non-blocking confirmation. Successes auto-dismiss at 4s, errors at 10s and are dismissible: "it worked" expiring is fine, "it failed" vanishing before it is read is not | Frontend |
| **Modal vs non-blocking confirmation** | `DialogProvider.alert()` is modal and right for a decision; it is wrong for "it worked", because it takes focus and demands a dismissal for something the user already knows they asked for. A confirmation that interrupts gets dismissed unread — which is how a real warning later gets missed | Frontend |
| **Live region** | The `aria-live` container toasts render into. It is mounted ALWAYS, empty when idle, because a screen reader only announces changes to a region it was already watching — mounting a populated one announces nothing, which is the standard way this ships broken | Frontend |
| **Double-submit** | A mutation trigger left enabled while its request is in flight. Seven pages had it, and the cause was upstream: with no success feedback, clicking again is the reasonable response to uncertainty | Frontend |
| **Ratchet (UX)** | `errorStatesAreActionable.test.ts` — the dead-end count may fall and may not rise, with a second assertion that fails when the ceiling drifts far enough above reality to stop meaning anything | Frontend |
| **Counting the escape, not the component** | The ratchet looks for `onRetry`/a button, NOT for `<ErrorState>`. Accepting the component made it gameable by the person draining the backlog: swapping a `<p>` for the component satisfies the detector and leaves the user exactly as stuck | Frontend |
| **Ambiguous retry** | A failure inside a component with several queries, where wiring a retry means deciding which query the message describes. A retry wired to the wrong query is worse than none — it succeeds and looks like it worked — so the conversion tooling refuses to guess and names the component instead | Frontend |
| **Lifting a fetch** | Moving a `fetch`/`load` out of a `useEffect` into a `useCallback` so a Retry control can call it. Inline in the effect, the only way to run it again is to remount the component — closing a modal, or reloading the page, both of which discard what the user had typed | Frontend |
| **Retry that cannot help** | A 404, a permission this session will never have, an account with no organisation attached. These get the message and NO button: a control that cannot work is worse than none, because the user clicks it repeatedly and concludes the product is broken rather than that the answer is no | Frontend |
| **Nested alert** | Putting an `ErrorState` (which is `role="alert"`) inside a block that is already `role="alert"`. Two alerts in one region: a screen reader announces twice, and `getByRole('alert')` finds two elements and fails. Where the surrounding block already announces, add a plain retry control instead | Frontend |

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
| **Hash Chaining** | Linking log entries cryptographically so that alteration is DETECTABLE. It does not *prevent* tampering, and the difference is the whole point: `audit_logs` grants no append-only enforcement, so a role with UPDATE or DELETE can still alter rows — the chain proves it happened. Verifiable end-to-end via `verify_audit_hash_chain()`, per organisation | Backend |
| **Zero-Trust** | Security model assuming no implicit trust, requiring continuous verification | Backend |
| **Purdue Model** | Network segmentation isolating manufacturing from enterprise zones | Backend |
| **MFA (TOTP)** | Second factor at login, RFC 6238. Enrolment is two-step (`/mfa/enroll` then `/mfa/confirm`) so a half-configured factor cannot lock anyone out, and `/auth/login` demands a code once a factor is confirmed. See *Cryptography & FIPS* for the primitives | Backend |
| **Recovery code** | Single-use fallback for a lost authenticator, stored as SHA-256 hashes and consumed on use. High-entropy random, so a plain digest is correct here — SP 800-132 governs passwords, not 128-bit secrets | Backend |
| **`last_used_window`** | The TOTP window a user last authenticated with. Without it a code stays valid for the remainder of its 30-second window and can be replayed | Backend |
| **Branch protection** | Repository-level refusal of force-pushes and deletions, admins included. Enabled on `main` 2026-08-18. The control the 2026-08-15 incident needed — 23 blocking CI jobs gate pull requests, and gate nothing at all if a credential can push straight past them | Backend |
| **API Key** | Secret token for programmatic API access (e.g., GeoTab integration) | Backend |
| **API Key Hash** | SHA256 hash of API key stored in database for security | Backend |
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

### Pre-certification programme

These describe the CMMC-first workstream, which is separate from the in-product compliance
*features* above: the rows above are things the platform does for a tenant, the rows below are
how this repository evidences its own controls.

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **CMMC Level 2** | Cybersecurity Maturity Model Certification L2 — the first assessment target. Assessed by a C3PAO against the 110 NIST SP 800-171 practices over a defined CUI boundary. **Not claimed by this repository**; what exists is technical controls with evidence | Backend |
| **NIST SP 800-171** | The 110 practices across 14 families that CMMC L2 assesses. All 110 are covered by the control catalogue — *covered* meaning each has an honest answer, not necessarily a good one | Backend |
| **Control catalogue** | `backend/compliance/catalog/` — 59 OmniusGrid controls in YAML, each naming the code that implements it and the test that proves it. YAML because an assessor must read it without executing anything | Backend |
| **Deployment profile** | One of `commercial-cloud`, `gov-cloud`, `on-prem`, `air-gapped`. Every control carries a status per profile, because physical controls are `inherited` in cloud and `organizational` on-prem and a single global status would have to lie about one of them | Backend |
| **Control status** | `implemented` \| `partial` \| `absent` \| `organizational` \| `inherited`. `organizational` requires a `why_code_cannot`; `inherited` requires a provider and CRM reference | Backend |
| **`proved_by`** | The test node ids that evidence a control. A guard asserts each one is a *really collected* node — **deleting a cited test fails the build** rather than silently lowering a number | Backend |
| **SSP** | System Security Plan — the control-implementation narrative, generated from the catalogue, never hand-edited | Backend |
| **SoA** | Statement of Applicability — the ISO 27001 Annex A mapping. Partial, and says so | Backend |
| **POA&M** | Plan of Action and Milestones — every `absent`/`partial` control with an owner and a dated remediation, sorted by due date. Generated, so it cannot drift from the catalogue | Backend |
| **`make compliance`** | Regenerates the SSP, SoA and POA&M. Output is held byte-for-byte by `test_generated_compliance_docs_are_current.py`, so an edited catalogue with an unregenerated document fails CI | Backend |
| **Evidence bundle** | The per-run artifact set an assessor is given: junit XML from every lane, coverage, SBOMs, Trivy SARIF, kubeconform renders, promtool results, the catalogue snapshot and the rendered documents | Backend |
| **CUI** | Controlled Unclassified Information. Its handling boundary is the thing CMMC assesses, and defining that boundary is an organizational act no repository can perform | Backend |

---

## DDIL & Edge Resilience

**DDIL** — Denied, Degraded, Intermittent, Limited-bandwidth. The operating condition an edge
deployment is actually in: a factory basement, a vehicle, a site on a satellite backhaul. Every
term below exists because the happy path assumed a link that is usually there.

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Store-and-forward buffer** | `buffer.db` on the device — SQLite in WAL mode holding readings until the uplink accepts them. Encrypted at rest (AES-256-GCM), size-capped, and the **only** delivery path that has ever run in production | Edge |
| **Conservation law** | `produced == sent + still_buffered + dead_lettered + dropped + expired`. Asserted at the end of every DDIL scenario. A reading that is none of those has vanished, and no single counter can detect that — only the balance | Edge |
| **Priority tier** | 1 safety (`emergency_stop`, `alarm`, `packml_state`) · 2 operational · 3 process (the default) · 4 bulk telemetry · 5 diagnostic. Drives both drain order and shed order | Both |
| **Cheapest-first shedding** | A full buffer discards tier 5 before tier 4 before anything else, rather than discarding the oldest row. Age is all a FIFO ring can express; value is what actually matters | Edge |
| **Drain order** | `ORDER BY priority ASC, timestamp_edge ASC` — tier first, then oldest-first *within* a tier, so ordered delivery survives | Edge |
| **Local alert sink** | `local_alerts.db`, written with `synchronous=FULL` before anything is attempted over the network. Readable at `/alerts` on the agent's own HTTP server — the only alarm surface that does not cross the link | Edge |
| **Holdover** | A clock offset that was calibrated once and whose last sample is now stale. The estimate is still the best available and the device has drifted by an unknowable amount since | Edge |
| **`time_quality`** | Per-reading label — `synced` \| `holdover` \| `unsynced` \| `unknown` — recorded on the `telemetry` row. Stops a correction from an uncalibrated device looking identical to one from a synchronised device | Both |
| **`timestamp_edge_raw`** | The uncorrected device clock, sent alongside the corrected timestamp. Ground truth, so a correction later found wrong is recoverable | Both |
| **Adaptive backfill** | Batch size scales with the backlog instead of a fixed 100-every-5-seconds. The fixed form was a 20 msg/s ceiling *below* the agent's own ingest rate | Edge |
| **Retention suspension** | Age-based expiry pauses while a drain is in progress, because a backlog *is* the oldest data. The size cap keeps running, so the bound changes from age to value rather than disappearing | Edge |
| **Transport vs message failure** | A broker outage does not increment a row's `retry_count`; a message the broker refuses on its own merits does. Counting link failures per-message meant an outage condemned the backlog it created | Edge |
| **Uplink supervisor** | Background task that rebuilds the Kafka producer with backoff and a circuit breaker, and tears down a producer that delivers nothing for three consecutive batches. Without it, a broker down at boot was never retried | Edge |
| **Wire codec / framing** | Uplink messages are framed `codec_marker + body` (`0x00` raw, `0x01` gzip). Unambiguous against bare JSON, which starts with `{` (`0x7B`) | Both |
| **Codec negotiation** | The agent emits `raw` until a heartbeat ack advertises what the backend can decode. Fail-closed: a new agent against an older backend would send unparseable bytes that the buffer has already marked sent — loss, not delay | Both |
| **Resumable OTA** | Release artifacts stream to a `.part` file and resume with HTTP `Range`. Progress survives the process, not just the connection, and the range response is validated rather than trusted | Edge |
| **DDIL harness** | `edge-agent/tests/ddil/` — 109 scenarios with time compressed (a 72-hour outage is a timestamp, not three days of waiting). Run nightly via `pytest -m ddil` | Edge |

---

## Cryptography & FIPS

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **FIPS 140-3** | The validation standard for cryptographic *modules*. An application does not become validated; it **uses** a validated module, which is why the base image matters and the application code mostly did not | Backend |
| **FIPS-capable vs FIPS-enforcing** | A UBI9 image *can* run the validated OpenSSL provider; whether it *does* depends on the host kernel. A capable image with FIPS off is indistinguishable from an enforcing one unless something probes it | Backend |
| **`REQUIRE_FIPS_MODE`** | Opt-in setting. When set, startup probes whether the process actually **refuses** MD5 for a security purpose, and refuses to serve if it cannot prove it. Defaults off, because most deployments have no FIPS obligation | Backend |
| **UBI9** | Red Hat Universal Base Image 9. All three application images use it, because Debian and musl have no FIPS-validated OpenSSL and no path to one | Backend |
| **PBKDF2-HMAC-SHA256** | The approved password KDF, 600,000 rounds, with bcrypt kept deprecated-but-verifiable so the migration window does not lock anyone out | Backend |
| **HKDF** | Key-derivation function used to derive per-organisation ERP encryption keys. Replaced a bare unsalted SHA-256 of `master:org_id`, which was the actual defect rather than the cipher choice | Backend |
| **AES-256-GCM** | Authenticated encryption used for ERP fields, edge buffer payloads and MFA secrets. Versioned envelopes (`v2:`, `encv1:`, `mfav1:`) so a format change is detectable rather than silently mis-decrypted | Both |
| **TOTP** | RFC 6238 time-based one-time password for MFA. HMAC-SHA-1 by construction — approved under SP 800-131A, which retires SHA-1 for *signatures* rather than for HMAC | Backend |
| **Replay refusal** | An MFA code that has already been used is rejected, tracked by `last_used_window`. Without it a code stays valid for its whole 30-second window | Backend |
| **Approved-primitive guard** | AST sweep failing the build if application code imports passlib/bcrypt/Fernet or constructs an unapproved hash, cipher or curve. Files with a defensible exception are registered with the argument written out | Backend |

---

## Testing Infrastructure

| Term | Definition | Backend/Frontend |
|------|------------|------------------|
| **Offline Demo Seeder** | `backend/scripts/seed_demo_data.py` — populates every page with correlated demo data so the whole platform runs with no live edge/cloud/services (idempotent). Only Correlation-AI *inference* still needs its model. See `docs/DEMO.md` | Backend |
| **Schema-parity check** | Guard that ORM `Base.metadata` matches the migrated Postgres schema (columns, nullability, types **and server defaults**) — prevents the ORM↔migration drift that only surfaces on a real DB (SQLite `create_all` hides it) | Backend |
| **Tenant session (`get_tenant_db` / `tenant_session`)** | The FastAPI dependency that opens a session AND sets the `app.current_org_id` GUC that RLS policies read. Using plain `get_db` on an RLS-protected table returns ZERO rows without erroring — the failure mode behind the empty dashboard and the silently empty audit trail. Enforced by `test_tenant_session_guard.py`. The body lives in `tenant_session(org_id, session_maker)` so tests can swap the engine **without copying the logic** | Backend |
| **`after_begin` tenant binding** | The GUC is set from a per-transaction SQLAlchemy `after_begin` hook, not once per request. A single `set_config(..., false)` does **not** survive an endpoint's mid-request `commit()`: commit returns the connection to the pool and the next statement gets an unconfigured one, so RLS fails closed and the endpoint sees zero rows for data it just wrote. Because the hook re-runs per transaction, the value is written transaction-locally (`true`) and so cannot leak onto a pooled connection either | Backend |
| **Quiet-failure bug class** | A defect that returns empty/NULL instead of raising, so tests and UIs look healthy: RLS filtering every row when the tenant GUC is unset, or a raw INSERT writing NULL `created_at` so the row drops out of time-ordered queries. Both are now guarded | Backend |
| **Naming-honesty rule** | A helper named `_create_*` / `_send_*` / `_persist_*` / `_store_*` / `_publish_*` must produce that side effect, or be renamed for what it does. The claim sits in the identifier, so no log-scanning or response-shape guard sees it — the call site simply reads as though the work happened. Enforced across `app/` by `test_helper_names_match_behaviour.py`; refusing loudly is fine, claiming silently is not | Backend |
| **Defect-class sweep** | The practice this codebase uses for "code that looks wired and cannot work": fix the instance, then ask whether the same *shape* exists elsewhere and check exhaustively. Thirty classes swept so far, each with a mutation-tested guard; **negative results are recorded too**, because "proven clean" and "never checked" look identical afterwards. See `docs/engineering/defect-class-sweeps.md` | Backend |
| **Mutation test (as a guard check)** | Reintroducing the original defect and confirming the new test fails. A guard that cannot be made to fail is indistinguishable from one that passes; two guards here passed against the reintroduced bug on the first attempt and had to be rewritten | Both |
| **Vacuity guard** | An assertion that a sweep *discovered something* — e.g. "at least N claiming helpers found". Without it, a rename or a moved module makes the whole file pass while checking zero cases, which is how three of four hand-copied tenant overrides survived a guard that only inspected `conftest` | Backend |
| **Python-side vs. server default** | `Column(..., default={})` fills a value only for rows written **through SQLAlchemy**; a migration, a seeder or any raw `INSERT` leaves NULL. Treating the two as equivalent is why a response-model sweep reported the API clean while a raw-inserted dock door returned a live 500. Only `server_default` makes a nullable column safe to declare required | Backend |
| **Silently ignored query parameter** | FastAPI drops unknown query parameters without error, so a misspelled or invented filter returns the UNFILTERED set and the caller renders it as filtered. Guarded by `test_frontend_query_params_are_declared.py`; a non-scalar parameter belongs in the body, which is where `conversation_history` had to move | Both |
| **Provenance flag** | A field that says how far to trust the value beside it — `simulated`, `quality_measured`, `availability_only`. Its DEFAULT is a claim, not a neutral: `simulated: bool = False` asserts "this was a genuine inference", and the correlation chat's exception fallback — a reply that was not an analysis at all — was the only one making that claim, because it constructed the response without the field. Enforced by `test_provenance_flags_are_always_set.py` | Both |
| **Dropped caveat** | A qualifier the backend sends and the frontend never reads, so the number renders without its footnote while the backend author believes the caveat is shown. `quality` reads 1.0 for an asset with no part counters — the neutral OEE multiplier, not a measurement — and `OEEMetrics` did not carry `quality_measured`, so every uninstrumented asset displayed flawless quality. Swept by `test_qualifiers_reach_the_frontend.py`, which strips comments first: prose about "simulated GeoTab data" was standing in for code nobody had written | Both |
| **Cache-key completeness** | A React Query key must name everything its `queryFn` varies on. If it does not, changing that value serves the PREVIOUS result from cache — no refetch, no loading state, no error; the controls update and the data does not. Guarded by `queryKeysAreComplete.test.ts`, which strips object keys (`{ limit: 500 }` varies with nothing) and resolves derived values before reporting | Frontend |
| **Stale-after-write** | A write succeeds, the server changes, and nothing tells the screen to look again. Worst where the work runs off the request path: `POST /erp/…/sync` returns "triggered" honestly, and a single `invalidateQueries` on success re-reads the row the background sync has not written yet, then never fires again — it passes review and changes nothing on screen. Needs polling that stops when the work settles, not an invalidate | Both |
| **Unbound inline session** | A handler that opens `AsyncSessionLocal()` instead of taking `Depends(get_tenant_db)`. It sets no `app.current_org_id`, so an RLS-protected read matches nothing — three `/api/v1/oee/*` routes answered 404 for the caller's own asset while `/health-index` and `/simulation/fleet-summary` returned an empty fleet. `health_index` and `simulation` filtered on `organization_id` correctly and it changed nothing, because RLS had removed the rows first, which is why review never catches this | Backend |
| **Invisible call** | A frontend request a static guard's pattern never matches, so it is neither checked nor counted — worse than a skipped one, because the reported coverage looks complete. `api.get<{ items: Asset[]; meta: {…} }>(…)` broke two guards' patterns at once: six calls hidden from the query-parameter sweep and fourteen from the endpoint sweep, which claimed to check all 183 | Both |
| **Unbound audit write** | An INSERT into `audit_logs` from a session with no `app.current_org_id`. The table is FORCE ROW LEVEL SECURITY, so the row is REJECTED — and every one of these sat inside a broad `except` that logged and continued, so the audited action succeeded while its evidence was lost. Four of eight writers had it; guarded by `test_audit_writers_bind_a_tenant_realdb.py`, which writes a real row and counts it rather than trusting that a `set_config` call is present | Backend |
| **Undetectable truncation** | A list endpoint that caps at `limit` and returns a BARE ARRAY, so a full page is indistinguishable from the complete set. Twelve endpoints do it; `/api/v1/rul` is the one that mattered, because RUL is computed per asset in Python and the list is therefore ordered by asset NAME — the cap keeps the alphabetically-first N, so a machine near failure whose name sorts late is absent from the risk page while its tiles count the survivors as the fleet. Signalled by `X-Result-Truncated` from a `limit + 1` probe (a header, not an envelope, so the bare-array body every client consumes is unchanged) | Both |
| **Verdict from emptiness** | A conclusion drawn from a count that is zero because nothing was inspected. `drivers.filter(d => d.hosDriveHoursRemaining === 0).length === 0` rendered a green tick reading "No HOS violations detected" whenever the drivers query FAILED, and server-side `overall_compliant` required `hos_violations == 0`, which is trivially true for a carrier with no drivers on file. Both cleared a DOT-regulated check from an absence of evidence. The usable line: emptiness is only ambiguous where a COUNT stands in for an INSPECTION — a field that holds a valid date or does not is unaffected | Both |
| **Failure rendered as absence** | React Query sets `data` to `undefined` on error, so `data?.items ?? []` produces an empty list and the screen says "No trailers found" or "No model deployed" — a claim about the world, made because a request failed. Fourteen surfaces did this. Guarded by `failureIsNotEmptiness.test.ts`, which checks each empty state for a failure branch in its own conditional chain; the file-level and count-based versions both missed live defects | Frontend |
| **Fixture from the declared type** | Building a test fixture by copying the client's return signature rather than inventing fields. Pages call `.toFixed()` and `.filter()` on API data unguarded, so a missing field throws during render and yields an empty document — which reads as a component bug and cost time on three separate page tests before the habit stuck | Frontend |
| **Privileged-read conclusion** | Asserting an outcome through a superuser connection, which bypasses RLS. It proves the write was ACCEPTED and says nothing about whether the row is visible to the tenant — under row-level security those are different questions, and the second is usually the one that matters. Two fixes in this repo proved only the first until they were reworked to read back through `GET /api/v1/audit/logs` and `/fleet/agents/versions`. Use the privileged connection for setup and diagnosis, not to conclude. Method rule 20 | Backend |
| **Positive control** | An assertion that the mechanism under test can still FIRE, paired with the one asserting it does not. "devLogin was not called" is satisfied just as well by a bypass that has been deleted, so `Login.test.tsx` also stubs `VITE_DEV_MODE=true`, re-imports the module, and asserts the bypass *does* fire. Without the pair, a security check keeps passing after the thing it guards has stopped existing | Both |
| **Log noise as a source** | Reading the warnings your own test runs emit. `get_historical_oee` had never returned a row and four audit writers had never written one; no sweep found either, and both scrolled past during unrelated real-DB runs. Both had been failing on every request since they were written. Method rule 16 | Both |
| **Artifact under test** | Whether a check loads what is SHIPPED or what is convenient. A manual-chunk cycle white-screened the entire production bundle while `vite build` exited 0, `tsc` read the source, 1,211 unit tests imported the source, and Playwright drove a dev server that does no chunking. The Docker image had even been "verified" by checking nginx returned 200 for `index.html` — a 200 for a page that throws on load | Both |
| **Chunk cycle** | Two bundler output chunks importing each other. ES modules resolve the cycle with partially-initialised bindings, so whichever evaluates first sees `undefined` for the other's exports — here `React.createContext` inside react-query, before any component mounted | Frontend |
| **Equivalent mutant** | A mutation that changes no observable behaviour, so no test can distinguish it — deleting an `conn.commit()` where the sqlite3 context manager already commits, for instance. A surviving mutant asks "what would be different?" and *nothing* is a legitimate answer. Say so and leave the redundant line; writing a passing test around it looks like coverage and is noise | Both |
| **Harness drift** | A test stand-in that has stopped resembling the object it stands in for. When the real class gains a method the stub lacks, the `AttributeError` is swallowed by a catch-all and surfaces as an unrelated assertion failing — which reads exactly like a regression. Bind the real method off the real class (`EdgeAgent._time_fields.__get__(self)`); a stub with equivalent behaviour is a second implementation, and second implementations drift | Both |
| **Instrument measuring itself** | A resource assertion polluted by its own harness. A memory check on a streamed download failed at 47 MB, and 44 MB of that was the fake server slicing its own payload inside the measurement window. Correctness harnesses fail loudly when they misbehave; resource harnesses quietly become most of the reading. Prefer `tracemalloc` to `ru_maxrss`, which is a process-wide high-water mark that never decreases | Both |
| **Grep-vs-prose** | A source-scanning test defeated by the comment that explains it. `assert "usedforsecurity=True" in source` passed while the keyword was removed from the *call*, because the phrase also appears in the docstring above it. A test that greps for a word cannot tell code from prose — parse it | Both |
| **Near-side bias** | When a feature spans two deployables, the assertions cluster where the work started. Fifteen mutations against a new uplink protocol caught every backend defect and missed six consecutively on the agent. Count assertions per side before believing the coverage, and mutate the far side first | Both |
| **Blocked-on-access decay** | A backlog item parked behind a stated constraint that nobody re-tests. Branch protection sat open for weeks behind "needs an org admin token we do not have"; the token was in the keychain with admin on both repositories, and the only missing piece was a CLI wrapper over an API `curl` already reached | Both |
| **Self-vouching detector** | A sweep whose input includes the thing it is auditing. **Three further instances in one day, in three languages**: the `vi.mock` sweep matched the two dead mocks quoted in its own docstring; the doc-citation guard flagged the paragraph confessing a bad citation; and the dead-hook inventory counted its own list of names as usage, reporting every recorded entry as wired. A guard that scans the tree it lives in must exclude itself, and none of the three was obvious until it passed when it should have failed. The invalidation sweep collected query keys from every `queryKey:` in the tree, including the ones inside the `invalidateQueries` calls under test, so each call registered its own key as valid; all 18 matched and it reported zero while a dead invalidation sat in the command panel. It fails in the most convincing way available — clean | Both |
| **Counted swallow** | A broad `except` that logs and continues **and increments a counter**. Swallowing is usually right — ingestion must not stop because a WebSocket publish failed — but *"do not fail the request"* and *"do not tell anyone"* are separate decisions, and this codebase had made only the first three times: a buffer prune dropping 500 readings (FS-504), alarm rule evaluation failing so the alerting was off while telemetry flowed (FS-537), and **the audit trail silently empty on real deployments while every write appeared to succeed** (FS-536). 201 handlers swallow, 11 count; both numbers ratchet, and the pair matters because a cap alone is satisfied by deleting a handler | Backend |
| **False entry in a curated list** | Worse than a false alarm, because it reads as verified. A false alarm announces itself; a baseline entry saying "this module is dead", written by somebody who checked, invites a reader to delete live code. Two sat in the unreachable-module inventory — `oracle_correlation_patterns` and `infor_connector` are both loaded through `importlib` from a dotted string, so no `ast.Import` node exists and a walk that knows one idiom reported them dead | Backend |
| **Registry-driven import** | A module loaded by `importlib.import_module` from a string in a lookup table (`PATTERN_CLASSES`, `erp_connector_factory`). There is no import node anywhere, so a dead-code walk sees a live, routed, tested module as unreachable — and the fix a reader reaches for is deletion. The walk now counts a dotted `app.*` string in production code as the import it is | Backend |
| **Verified transformer/analyzer pair** | The ERP correlation registry's rule: a route may only be added when the named transformer reads *that vendor's* field names and emits exactly what the named analyzer reads, checked field by field. Reusing another vendor's transformer produces a record of `None`s — and an analyzer reading nulls **finds nothing wrong**, so the failure is a clean bill of health rather than an error. Demonstrated rather than asserted: a test runs SAP's transformer over a NetSuite payload and shows all three fields come back null | Backend |
| **Vendor vocabulary mismatch** | Two systems naming the same fact differently, with no translation, so the comparison silently takes the wrong branch. Settlement is spelled five ways across the ERP vendors — NetSuite `"Paid In Full"`, Odoo `payment_state: "paid"` (and `state: "posted"` is *not* it), Infor `"Paid"`, Epicor the **boolean** `OpenInvoice`, Intuit the **number** `Balance`. Two carry it in a field that is not a status at all, so a transformer looking for a status string leaves `None`, and `None != "paid"` — every Epicor and every QuickBooks invoice would report overdue. A confident wrong answer, not an error | Backend |
| **Posture switch set only in a comment** | A safety default documented and configured nowhere. Four edge-agent switches — `EDGE_REQUIRE_TLS`, `KAFKA_SECURITY_PROTOCOL`, `EDGE_REQUIRE_EXPLICIT_SOURCES`, `ENROLLMENT_CA_FINGERPRINT` — were "set" in a commented block headed *"Production posture"*, so they grep as present while every deployment ran the permissive default. Two consequences for a detector: parse the artefact (YAML as YAML, not as text), and treat *unset* as a value somebody must choose | Both |
| **Rendered count as an empty state** | `{items.length} Vehicles` rendering **"0 Vehicles"** after a failed fetch. The same lie as "No vehicles found" and more authoritative, because a figure looks computed — and structurally invisible to a phrase-matching sweep, since a number is not a phrase. A count read off an object (`{session && …{session.count}}`) is guarded by that object existing, which is a fourth guard shape a literal phrase never needs | Frontend |
| **Engine-not-running signal** | `X-Engine-Not-Running`, and the `running` field beside a status payload. Four engines expose status routes and none is started, so `connected: false` on the cloud gateway reads as *"the cloud is unreachable"* when it means *"we never tried"*, and an empty recommendation list means both "found nothing" and "never ran". A header rather than an envelope, for the reason `X-Result-Truncated` is one: clients already consume the bare array | Both |
| **Decision that leaves no record** | A rejection is a decision **not** to act, so unlike an approval it has no effects to be visible in — the only evidence is the record of it. `reject_recommendation` removed the item from the pending list and appended it nowhere, writing only to a cloud gateway that never starts, so the same recommendation returned next cycle with nothing to say it had already been refused | Backend |
| **Detector calibration cap** | An assertion that a sweep flags no more than a small fraction of its population, on the reasoning that above that the detector is broken rather than the codebase. Written after three sweeps in one day reported 57%, 75-of-97 and 55-of-60 — each a real class, each a detector that knew one idiom out of three or four. A sweep flagging most of a tree is dismissed rather than acted on, so the number itself is the failure | Both |
| **False negative in a sweep** | The detector error that does not announce itself. Every over-reporting sweep is noisy and gets fixed; an under-reporting one passes, and the finding stays hidden. Recursing a JSX tree with `forEachChild` descends into a child's **attributes**, so `<LogOut size={16} />` read as renderable content and both sidebar logout buttons — the control that ends a user's session — dropped out of the unnamed-button list | Frontend |
| **Duplicated subject list** | Two guards each keeping a private copy of the same fact, with nothing comparing them. 86 module-level collections live in `tests/`; three pairs described one fact twice and one had **already diverged** — `OTHER_LANES` and `_OTHER_LANES` disagreed about whether `rag` is another lane, silently, with neither file able to see it. FS-492's shape arriving in the guards rather than the code they check. Swept by `test_no_two_guards_keep_the_same_list.py`, which requires each overlapping pair to be either derived or recorded as two different questions | Backend |
| **Derived-list shrink** | The failure that replaces divergence when you fix it. Sharing a list hands the SOURCE control of the consumer's population: dropping `cloud_gateway` from `EXPECTED_DORMANT` took the engine-status suite from 16 tests to 14 **and it reported success**, having silently stopped checking the one engine whose dormancy costs something. Sharing a list is right; sharing it without asserting what came back is how a guard narrows to nothing one entry at a time | Both |
| **Recorded negative** | A sweep that found nothing, written down anyway — because *proven clean* and *never checked* are indistinguishable afterwards, and the second invites the same work again. FS-589 narrowed 40 numeric defaults to the seven that match the shape and found all seven are internal thresholds rather than figures a user reads; FS-592 found zero skipped tests across 110 frontend files. Neither is a fix, and both are results | Both |
| **Stale-after-switch** | A detail view that keeps the PREVIOUS record's data when the id changes. Three distinct failures hide in one hand-rolled effect: no clear (the old values sit under the new heading until the request returns), no catch (if it fails they stay there **permanently**, attributed to the new record), and no cancellation (a slow first request lands after a fast second and overwrites it — both succeeded and the screen is wrong). `getShipmentCosts` had all three, so one shipment's linehaul, fuel surcharge and total displayed under another's name. React Query does all three for you, which is why the class only appears in `useEffect`. Guarded by `idKeyedFetchesDoNotGoStale.test.ts`, which asserts each separately so a partial fix fails | Frontend |
| **Failure found through a later failure** | An error swallowed at one step, surfaced only by the next step failing for a reason that looks unrelated. `PlatformDataSourcePicker` caught a failed source-type fetch into `setTypes([])` and rendered an empty `<select>` beside an **enabled** Add button; the user picks nothing, presses Add, and gets a second error from the attach call. Nothing connects the two, so the diagnosis starts from the wrong end | Frontend |
| **Inverted instrumentation** | The most serious figure being the least instrumented, because the recoverable ones were easier to reason about. Of the edge agent's three buffer counters, `buffer_pending` (waiting to send) had a gauge and an alert, `dead_lettered` (replayable) had a gauge, and `dropped` — **data gone from the device that never arrived** — had no gauge, no alert and no field in the response model. Worth checking as a set rather than individually: each looked fine alone, and only the ordering showed the problem | Both |
| **Provably firable alert** | A rule with a promtool unit test that drives its expression TRUE, plus at least one must-stay-quiet case. `promtool check rules` validates syntax and says nothing about whether a series exists that would satisfy the expression — `EdgeAgentBufferHigh` was syntactically perfect and unfirable for its entire existence, because the heartbeat sent `collectors_total` and the rule read `total_collectors`. **An alert that cannot fire is indistinguishable from a healthy system.** 28 of 51 rules are tested; the untested set is NAMED rather than counted, so the ratchet cannot be satisfied by deleting a rule, and the nine guarding data loss or total outage may never be untested at all | Both |
| **Declaring a model narrows a wire** | Adding `response_model` to a route makes FastAPI **delete** every key the model does not declare, so a change made for documentation silently removes fields and the client sees 200 with something missing. Declaring 27 routes from five builders I had verified left ten wrong, because deactivate/assign/bulk/inventory return different shapes — and being sure about the five is what stopped me checking the ten. `test_response_models_match_their_returns` is the pairing that catches it | Backend |
| **A filename doing the work of a test** | `AdminPages.test.tsx` satisfied the routed-page walk while every describe inside it was about `UsersPage`. Three pages counted as covered because a file with the right name existed. Only visible when the file was deleted — the guard reads names, and a name is not a test | Frontend |
| **Preservation before integration** | Push the input somewhere durable before resolving it. A merge is not a backup: a resolution that goes wrong is only recoverable while the original still exists, and two of the three branches involved here existed in exactly one place — one of them a laptop | Both |
| **Work that is off the branch** | Commits that exist and are not where the product is. Found by asking where each contributor's *last commit lives*, not what it says — a question nothing in this repository had ever asked. It turned up nine of one developer's commits on the backup mirror only and three of another's on a branch with no remote at all. Invisible to every gate, every sweep and every plan, because all of them read the branch it is missing from | Both |
| **Stale trunk as a root cause** | `main` being 434 commits behind while everyone is told to branch from it. The instruction and the tree disagree, so developers either start from something two months old or keep their own branch — and the second is what happened. Stranded work is not a discipline problem when the documented starting point is wrong | Both |
| **A ratchet nothing runs** | A threshold that fails a command nobody invokes. The frontend coverage floors lived in `vitest.config.ts`, and both workflows ran `vitest run` **without** `--coverage` — so the numbers were documented, cited in the README, quoted in two task pools, and read by no job. They had already gone false before anyone noticed. The fix is not a higher number; it is wiring the command that reads it, even at the cost of lowering the number to the measured floor in the same change | Frontend |
| **A drop the browser rejects** | HTML5 drag-and-drop refuses by default: a drop only fires on an element that cancelled the preceding `dragover`. A missing `preventDefault` produces a column that accepts nothing, logs nothing, and shows only a card sliding back where it started — which a user reads as a failed request rather than a bug. Both handlers have to cancel, and only a test distinguishes the two states | Frontend |
| **Optimistic in the comment, pessimistic in the code** | `moveTask` awaits its POST before touching local state, while the note above it said "update local state optimistically". The code is the better of the two — a card that jumps and snaps back is indistinguishable from a board that reordered itself — but the comment described the version that would have had the defect, so a reader tidying "redundant" ordering would introduce it | Frontend |
| **A quiet case built from absence** | A must-stay-quiet assertion driven by *no data* rather than by healthy data. A buffer at zero and an asset with no series both keep an alert quiet — and prove only that the rule is silent when there is nothing to read, which is the one situation nobody worries about. The quiet case has to look like the system working: a buffer with traffic below the threshold, a timestamp that keeps up with `time()` | Infra |
| **Worth testing while unreachable** | A guard whose failure mode no current caller can trigger. `resolve_bundle_path` cannot be traversed through today's callers because both ids are UUIDs — which is the argument *for* the test, not against it: the check is the only thing between a future caller that passes a string and an arbitrary write, and "unreachable" is a property of the callers, not of the function | Backend |
| **`all([])` on a success verdict** | An empty collection satisfies `all(...)` vacuously, so "every target succeeded" is True when there were no targets. `FanoutResult.summary()` reported `fully_posted` for a shop-floor event that reached nothing — the operator is told the work went through when it went nowhere. The same shape as a failed read rendering as an empty list, but on the write side and with a physical consequence: the part is never issued. Guard the collection, not just its members | Both |
| **A stub is coverage** | A component replaced by `() => null` in every page test that mounts it reports as covered — a stub and an exercised component are indistinguishable to the tool. All five `components/common/` files were in that state, and `Select` sat at 100% line coverage while rendering an unlabelled combobox app-wide. Coverage answers "did this module execute", never "did anything render it" | Frontend |
| **Counting a register by grepping its file** | Reading entries with a regex over the source instead of importing the variable. A guard file contains more lists than its register: `test_no_new_unreachable_modules.py` also holds a **positive control** naming modules asserted to be *reachable*, and a grep for quoted paths swallows both. That inflated 16 modules / 6,955 lines into 19 / 8,101 and put `oee_calculator.py` — which `main.py` imports and starts — at the top of a dead-code list. Import the register; it is one line and it cannot include the control | Both |
| **A grep that finds prose** | Searching for a module name and counting mentions in *other modules' comments* as imports. `feature_extraction.py` read as having a production importer for exactly that reason; it has none. The check is what the name is doing — an `import` line, not an appearance | Both |
| **A pool that is too short** | The inverse of the failure every previous plan here had. A backlog derived from *what its author touched* rather than *what is open* narrows to that author's footprint, and whole lanes with no overlap vanish — producing no conflict, no failing check, and no complaint, because **a short pool looks like progress**. An inflated backlog eventually gets questioned; a deflated one gets celebrated. Caught only by someone asking where a specific person's work had gone | Both |
| **Age on a backlog item** | The pool an item first appeared in, carried forward with it. Without it a repeat reads as new work every fortnight, which is precisely how a decision nobody makes stays invisible — two items in this repository are on their third consecutive pool, and neither looked old until the marker was added | Both |
| **Floor capped by a fail-safe** | A gate's threshold bounded not by the code's quality but by the worst configuration its own degradation path allows. The contract suite scores 402 with a broker and 387 without, and the broker step deliberately removes itself when it cannot verify its advertised address — so the floor must sit below 387 minus the spread, however well a healthy run does. Raising it to the good number converts a fail-safe into a build failure, which is how the predecessor job became advisory. **The next raise is a CI change, not a code fix** | Both |
| **5xx that is the right answer** | A correctly-reported missing dependency, charged to the API because the checker counts status families rather than reasons. `/edge/enroll` and `/sso/login/callback` answer 503 because their dependency is absent — the behaviour you want — and appear in the gate's server-error list beside genuine faults. Distinguishing them takes reproducing each one; a count alone reads as fourteen tickets when it is two | Both |
| **Null is a third state** | A nullable boolean where `false` and "not recorded" mean different things, and collapsing them invents a finding. `correlation_routed` is `true` (analysed), `false` (no analyzer for this vendor — the correlations list is a gap, not a result) or `null` (the sync recorded no attempt, which is every row predating the column). Writing the check as `!routed` instead of `routed === false` puts a gap warning on the entire history of every integration. Guarded by `ERPIntegrations.unanalysed.test.tsx` | Both |
| **Closed limitation still written as open** | A documented caveat that a later fix resolved, where the prose motivating the fix outlived it. The contract gate's document said "this gate does not do the same yet" for two weeks after FS-307 gave it a restricted role. Worse than an unrecorded limitation: a reader either re-does the work or discounts the gate's results on a caveat that no longer applies. Paired against the workflow in both directions by `test_the_contract_gate_doc_matches_the_gate.py` | Both |
| **Dated figure** | A measurement written with its date and its command, where a live check would be *wrong*. The pre-commit reformat is 972 files only under the hook versions pinned in `.pre-commit-config.yaml`; a count from a locally-installed `ruff` is a different number presented as the same one. Every other figure in `docs/engineering/open-decisions.md` is asserted against reality — this one says in the entry why it is not, which is the difference between a limitation and an omission | Both |
| **Advisory that became a decision** | A gate left non-blocking "while the tree is brought into compliance", long enough that the sentence now describes a choice nobody made rather than a transition in progress. It looks like work in flight and is actually a fork in the road, which is why it belongs in the decision register with a pin rather than in a backlog | Both |
| **Re-runnable migration** | The only recovery `migrate.py` offers. It runs in autocommit and executes one statement at a time — continuous aggregates and `add_retention_policy` refuse a transaction block — so a file that fails at statement 7 has **committed 1–6 and recorded no version**. There is nothing to roll back; the operator runs the file again, which works only if every statement tolerates being executed twice. Four migrations do not, and none of them can be repaired: editing an applied migration is checksum drift and the runner then refuses to migrate at all. Guarded by `test_every_migration_can_be_rerun_realdb.py`, which applies the chain from empty and retries each file at its own point in it | Backend |
| **Line citation** | A reference into another document by line number. It expires without saying so: `defect-class-sweeps.md:777-786` was written when those lines held an argument about a route prefix, and by the time anyone followed it they held an unrelated paragraph. Nothing can fail — the file exists and the lines exist — so only a reader who already knows what they expected to find can tell. Cite the section heading; it moves with the text | Both |
| **Scope that did not move with the prose** | Splitting or relocating a document removes it from every check scoped to its old path, and the checks go on passing. FS-584 split a 7,239-line document into six files: two guards read only the index and found none of what they check, and a third had 7,100 lines of source-file citations leave its scope while its entry still resolved. **A check that has stopped looking and a document with nothing wrong produce the same green tick.** The comment predicting this was already in one of the three files | Both |
| **Shadowed default** | A value written twice, where only one copy takes effect. `ReconnectPolicy` declared seven tuning numbers as annotated class attributes — with explanatory comments — and repeated all seven as `__init__` parameter defaults, so the attributes were overwritten on every instance and decided nothing. **The copy a reader's eye lands on first was the dead one.** It survives review because both copies agree when written: the divergence arrives later as a single edit, and there is no moment where the mistake is visible. The fix is `@dataclass`, which generates `__init__` from the attributes. Guarded by `test_no_shadowed_class_defaults.py` | Both |
| **Exemption whose reason expired** | An allowlist entry that is still *correct* while its stated reason has stopped being true. `coordinator.py` was exempt from the backoff invariant as "owns no socket" — accurate, and then FS-501 gave it a supervision loop with a fixed 5-second delay, so the file gained a retry loop the reason did not describe. The entry stays; the reason is rewritten. A reason that no longer matches the code is how the next reader concludes the exemption is wrong and removes it, or concludes it is fine and stops looking | Both |
| **Shrink-only baseline** | A recorded list of pre-existing offenders that fails the build on a NEW one *and* on an entry that no longer offends. Used where a corrected detector surfaces more than can be responsibly fixed at once (158 response fields), so the debt is visible and cannot be topped up instead of drained | Backend |
| **Mock-branch blindness** | `VITE_USE_MOCK='true'` is forced in `src/test/setup.ts` before any module evaluates, so every frontend unit test takes the mock branch of the 213 `if (USE_MOCK)` forks. The real branch — what ships — is run by no test, so a wrong path or method survives until a user hits the 404. `test_frontend_calls_real_endpoints.py` checks all 183 real-mode calls against the backend's live route table; `src/test/realMode.ts` re-imports a module in real mode for per-module tests | Both |
| **Reimplementing test double** | A fake/override that hand-copies production logic instead of delegating to it. It mirrors production's *bugs* as well as its behaviour, so the suite proves only that the double works — and a fix to production never reaches the tests. Four copies of `get_tenant_db` hid an RLS defect this way; all now delegate to `tenant_session`, enforced by a sweeping source-level guard | Backend |
| **`NullPool` (in tests)** | Connection pool that opens a fresh connection per checkout. Used deliberately in the tenant-GUC guard: with a normal pool, `commit()` hands the same connection straight back, so a lost session-scoped GUC *appears* to survive and the guard passes against the real bug. NullPool forces the worst case a loaded server produces routinely | Backend |
| **Readiness check vs. log match** | Waiting for the condition you actually need rather than a log line that correlates with it. Redpanda prints "Started Kafka API server" when it binds *inside* the container; the host's published port can take longer to forward, and the gap widens with container count — producing a Kafka error that appeared only in full runs and read as flakiness. The fixture now waits for a connection to succeed | Backend |
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
| **TBA (Token-Based Auth)** | NetSuite's server-to-server mechanism: OAuth 1.0a with HMAC-SHA256, where EVERY request is individually signed over its own method, URL and query string. There is no token to cache and a `Bearer` header is rejected | Backend |
| **`$batch` (OData)** | A multipart/mixed request bundling several OData operations. The response carries a per-operation HTTP status, so a batch can return 202 overall while individual operations fail — parsing must read each part's status or a partial failure looks like a smaller success | Backend |
| **Changeset** | A nested `multipart/mixed` block inside a `$batch` response, with its own boundary, wrapping write operations. A single-level split walks straight past them | Backend |
| **client_credentials** | The correct OAuth2 grant for a scheduled server-to-server ERP sync. The authorization-code grant needs a browser redirect carrying a code, which a background job does not have | Backend |
| **Quarantine register** | `backend/tests/test_quarantine.py` — every CI test exclusion carries an owner, a diagnosis and an EXPIRY, and the suite fails when a window lapses, when a quarantined test starts passing, or when the register and the CI flags drift apart | Backend |
| **Real-mode test** | A frontend test that loads an API module with `VITE_USE_MOCK=false` (`src/test/realMode.ts`). Every other unit test runs against the mock branch, so the ~200 `if (USE_MOCK)` forks could drift from the real request shape undetected | Frontend |
| **Coverage ratchet** | Thresholds set from a MEASURED baseline rather than an aspiration, so they cannot be met by deleting tests and they fail when new untested code dilutes the total. Frontend 19/15/14/19, backend `--cov-fail-under=54` | Both |
| **Authenticated journey** | `frontend/e2e/authenticated.spec.ts` — the e2e that logs in and asserts the dashboard shows NON-ZERO values. An "element is visible" assertion would have passed against the FS-191 bug, where every tile rendered 0 with no error | Frontend |
| **False success** | Code that logs a `*_created` / `*_synced` success event for work it never performed. Worse than a crash or a silent no-op: the logs say it worked, so nobody looks. `tests/test_reporting_honesty.py` scans for the shape | Backend |
| **Simulated provenance** | `simulated: true` + a compliance warning stamped into every simulated GeoTab payload. HOS figures are DOT-regulated, so an invented `drive_hours_today` must not be indistinguishable from a measured one | Backend |
| **`quality_measured` / `performance_measured`** | Flags recording whether an OEE factor was actually measured. Quality falls back to 1.0 as a neutral multiplier when an asset has no part counters — reporting that as "Quality 100%" is a number the platform invented | Backend |
| **Deployed-but-dead** | A workload that starts, reports healthy and does nothing, because `default-deny-all` blocks it and no policy grants an exception. otel-collector and jaeger shipped this way; the coverage gate found four more instances on its first run | Backend |
| **NetworkPolicy coverage gate** | `tests/k8s/check_netpol_coverage.py` — asserts every workload in a default-deny namespace is selected by at least one ingress AND one egress policy. Broad and shallow; the enforcement matrix is narrow and exact. Neither replaces the other | Backend |
| **`opsgrid_auth_attempts_total`** | Auth outcomes by (outcome, reason). Deliberately NOT labelled by user or IP — an enumeration attack would create one series per attempt and the metric would become the outage | Backend |
| **`opsgrid_websocket_events_total`** | WebSocket lifecycle by event, separating a clean client close from an error teardown. The distinction is what makes a drop-RATIO alert meaningful; a busy system produces clean closes constantly | Backend |
| **`overlays/dr`** | The DR-site kustomize overlay. Brings up pods in a standby namespace; it does NOT replicate data (pgBackRest does), so applying it to an empty cluster yields a running platform with no data | Backend |
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
