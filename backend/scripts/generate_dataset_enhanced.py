"""
Enhanced Synthetic Data Generation Pipeline for OmniusGrid Correlation AI

Generates 50,000 JSONL scenarios for Gemma 4 fine-tuning with:
- Balanced distribution across 47 domains
- Single/multi-domain ratio control (50/50)
- Comprehensive scenario type coverage
- Output organized by domain/scenario_type
- Full validation framework
"""

import json
import random
import sys
import os
import hashlib
from pathlib import Path
from typing import Dict, List, Any, Optional, Set, Tuple
from datetime import datetime, timezone
from collections import defaultdict, Counter
from dataclasses import dataclass, asdict

# Add backend to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from app.models.domain_interaction import (
    DomainType,
    OperationalMetric,
    CrossDomainLink,
    CorrelationScenario
)
from app.models.finetuning_schema import FineTuningExample, DEFAULT_SYSTEM_PROMPT

# LLM Integration
try:
    import google.generativeai as genai
    LLM_AVAILABLE = True
except ImportError:
    LLM_AVAILABLE = False


class StateSpaceLoader:
    """Loads state space JSON files for randomization"""
    
    def __init__(self, state_space_dir: str):
        self.state_space_dir = Path(state_space_dir)
        self.data = {}
        self._load_all()
    
    def _load_all(self):
        """Load all JSON files from state_space directory"""
        for json_file in self.state_space_dir.glob("*.json"):
            with open(json_file, 'r') as f:
                self.data[json_file.stem] = json.load(f)
    
    def get_random_asset(self) -> str:
        """Get random asset from any category"""
        assets = []
        for category in self.data.values():
            for key, items in category.items():
                if isinstance(items, list):
                    assets.extend(items)
                elif isinstance(items, dict):
                    assets.extend(items.keys())
        return random.choice(assets) if assets else "asset"


class LLMGenerator:
    """Generates realistic AI analysis using state space rules"""
    
    def __init__(self, state_space: Optional[StateSpaceLoader] = None):
        self.state_space = state_space
        self.model = None
    
    def is_available(self) -> bool:
        """Check if LLM is available for generation"""
        return False  # Always use state space for this implementation
    
    def generate_ground_truth(
        self,
        domains: List[str],
        metrics: List[Dict[str, Any]],
        links: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate realistic ground truth using state space rules"""
        return self._generate_with_state_space(domains, links)
    
    def _generate_with_state_space(self, domains: List[str], links: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate realistic ground truth using state space rules"""
        root_cause = self._analyze_root_cause_with_state_space(domains, links)
        kanban_tasks = self._generate_tasks_with_state_space(domains)
        commands = self._generate_commands_with_state_space(domains)
        compliance_items = self._identify_compliance_with_state_space(domains)
        risk_score = self._calculate_risk_with_state_space(domains, links)
        
        return {
            "predicted_root_cause": root_cause,
            "risk_score": risk_score,
            "target_kanban_tasks": kanban_tasks,
            "remediation_commands": commands[:3],
            "compliance_implications": compliance_items if compliance_items else None
        }
    
    def _analyze_root_cause_with_state_space(self, domains: List[str], links: List[Dict[str, Any]]) -> str:
        """Analyze root cause using enhanced state space data with detailed multi-perspective analysis"""
        domain_map = {
            "EDGE_AI_TELEMETRY": "edge telemetry",
            "PRODUCTION_OEE": "production line",
            "LOGISTICS_FLEET": "logistics fleet",
            "COMPLIANCE_REGISTRIES": "compliance system",
            "SYSTEM_INFRASTRUCTURE": "system infrastructure",
            "MATERIAL_REPLENISHMENT": "material replenishment",
            "PRODUCTION_OUTPUT": "production output",
            "PACKAGING": "packaging operations",
            "DISTRIBUTION": "distribution network",
            "MAINTENANCE": "maintenance operations",
            "QUALITY_CONTROL": "quality control",
            "ENERGY_MANAGEMENT": "energy management",
            "WORKFORCE_MANAGEMENT": "workforce management",
            "SUPPLY_CHAIN": "supply chain",
            "WAREHOUSE_MANAGEMENT": "warehouse management",
            "CUSTOMER_SERVICE": "customer service",
            "FINANCE": "financial operations",
            "SAFETY": "safety management",
            "ENVIRONMENTAL": "environmental management",
            "PLANNING_SCHEDULING": "planning and scheduling",
            "CYBERSECURITY": "cybersecurity",
            "DIGITAL_TWIN": "digital twin",
            "IT_OT_INTEGRATION": "IT/OT integration",
            "DATA_ANALYTICS": "data analytics",
            "PROJECT_MANAGEMENT": "project management",
            "HR_ORGANIZATIONAL": "HR and organizational",
            "REGULATORY_AUDIT": "regulatory audit",
            "RISK_MANAGEMENT": "risk management",
            "INNOVATION_RD": "innovation and R&D",
            "CONTRACT_MANAGEMENT": "contract management",
            "ASSET_LIFECYCLE": "asset lifecycle",
            "PROCESS_OPTIMIZATION": "process optimization",
            "SUPPLIER_RELATIONSHIP": "supplier relationship",
            "INVENTORY_OPTIMIZATION": "inventory optimization",
            "CHANGE_MANAGEMENT": "change management",
            "KNOWLEDGE_MANAGEMENT": "knowledge management",
            "BUSINESS_INTELLIGENCE": "business intelligence",
            "CONTINUOUS_IMPROVEMENT": "continuous improvement",
            "PRODUCT_LIFECYCLE": "product lifecycle",
            "MANUFACTURING_EXECUTION_SYSTEM": "manufacturing execution system",
            "FACILITIES_MANAGEMENT": "facilities management",
            "TOOL_MANAGEMENT": "tool management",
            "CALIBRATION": "calibration",
            "SPARE_PARTS": "spare parts",
            "DOCUMENT_MANAGEMENT": "document management",
            "WORKFLOW_MANAGEMENT": "workflow management",
            "ESG": "ESG"
        }
        
        if self.state_space:
            asset = self.state_space.get_random_asset()
            trailer = self._get_random_nested("logistics", "trailers")
            dock = self._get_random_nested("logistics", "dock_doors")
            detention_scenario = self._get_random_nested("logistics", "detention_scenarios", "driver_liability")
            bottleneck = self._get_random_nested("logistics", "yard_bottlenecks", "dock_congestion")
            shop_floor_issue = self._get_random_nested("production_output", "shop_floor_scenarios", "production_bottlenecks")
            predictive_indicator = self._get_random_nested("maintenance", "predictive_indicators", "vibration_analysis")
            safety_scenario = self._get_random_nested("safety", "security_scenarios", "physical_security")
            edge_anomaly = self._get_random_nested("errors", "edge_anomalies")
            packml_state = self._get_random_nested("errors", "packml_states")
            alarm_code = self._get_random_nested("errors", "alarm_codes")
            security_vuln = self._get_random_nested("errors", "security_vulnerabilities")
            data_anomaly = self._get_random_nested("errors", "data_anomalies")
            iso = self._get_random_nested("compliance", "iso_standards")
            osha = self._get_random_nested("compliance", "osha_standards")
            dot = self._get_random_nested("compliance", "dot_regulations")
            receiving_issue = self._get_random_nested("logistics", "shipping_receiving", "receiving_bottlenecks")
            maintenance_conflict = self._get_random_nested("maintenance", "maintenance_conflicts", "scheduling_conflicts")
            shop_floor_impact = self._get_random_nested("logistics", "shop_floor_impacts", "material_starvation")
            
            # New exhaustive variables
            dwell_time = self._get_random_nested("logistics", "dwell_times")
            detention_cost = self._get_random_nested("logistics", "detention_costs")
            appointment_adherence = self._get_random_nested("logistics", "appointment_adherence")
            yard_utilization = self._get_random_nested("logistics", "yard_utilization")
            shipment_count = self._get_random_nested("logistics", "shipment_counts")
            production_risk = self._get_random_nested("logistics", "production_risk")
            
            vibration_level = self._get_random_nested("maintenance", "vibration_levels")
            temperature_reading = self._get_random_nested("maintenance", "temperature_readings")
            time_to_failure = self._get_random_nested("maintenance", "time_to_failure")
            maintenance_backlog = self._get_random_nested("maintenance", "maintenance_backlog")
            downtime_cost = self._get_random_nested("maintenance", "downtime_costs")
            technician_availability = self._get_random_nested("maintenance", "technician_availability")
            maintenance_duration = self._get_random_nested("maintenance", "maintenance_duration")
            
            oee_metric = self._get_random_nested("production_output", "oee_metrics")
            throughput_reduction = self._get_random_nested("production_output", "throughput_reduction")
            cycle_time_increase = self._get_random_nested("production_output", "cycle_time_increase")
            quality_rate = self._get_random_nested("production_output", "quality_rate")
            downtime_hours = self._get_random_nested("production_output", "downtime_hours")
            production_loss = self._get_random_nested("production_output", "production_loss")
            scrap_cost = self._get_random_nested("production_output", "scrap_costs")
            rework_rate = self._get_random_nested("production_output", "rework_rate")
            customer_return = self._get_random_nested("production_output", "customer_returns")
            production_order = self._get_random_nested("production_output", "production_orders")
            schedule_adherence = self._get_random_nested("production_output", "schedule_adherence")
            equipment_efficiency = self._get_random_nested("production_output", "equipment_efficiency")
            line_utilization = self._get_random_nested("production_output", "line_utilization")
            
            incident_severity = self._get_random_nested("safety", "incident_severity")
            personnel_affected = self._get_random_nested("safety", "personnel_affected")
            root_cause_deadline = self._get_random_nested("safety", "root_cause_deadline")
            access_point = self._get_random_nested("safety", "access_points")
            unauthorized_attempt = self._get_random_nested("safety", "unauthorized_attempts")
            data_exposure = self._get_random_nested("safety", "data_exposure")
            remediation_time = self._get_random_nested("safety", "remediation_time")
            safety_cost = self._get_random_nested("safety", "safety_costs")
            regulatory_fine = self._get_random_nested("safety", "regulatory_fines")
            contributing_factor = self._get_random_nested("safety", "contributing_factors")
            corrective_action = self._get_random_nested("safety", "corrective_actions")
            near_miss_severity = self._get_random_nested("safety", "near_miss_severity")
            incident_location = self._get_random_nested("safety", "incident_location")
            injury_type = self._get_random_nested("safety", "injury_types")
            
            inventory_level = self._get_random_nested("material_replenishment", "inventory_levels")
            replenishment_time = self._get_random_nested("material_replenishment", "replenishment_times")
            safety_stock_level = self._get_random_nested("material_replenishment", "safety_stock_levels")
            stockout_risk = self._get_random_nested("material_replenishment", "stockout_risk")
            inventory_accuracy = self._get_random_nested("material_replenishment", "inventory_accuracy")
            pick_rate_degradation = self._get_random_nested("material_replenishment", "pick_rate_degradation")
            putaway_time_increase = self._get_random_nested("material_replenishment", "putaway_time_increase")
            space_utilization = self._get_random_nested("material_replenishment", "space_utilization")
            slot_availability = self._get_random_nested("material_replenishment", "slot_availability")
            sku_stockout = self._get_random_nested("material_replenishment", "sku_stockouts")
            inventory_buffer_day = self._get_random_nested("material_replenishment", "inventory_buffer_days")
            order_fulfillment_accuracy = self._get_random_nested("material_replenishment", "order_fulfillment_accuracy")
            supplier_scorecard = self._get_random_nested("material_replenishment", "supplier_scorecard")
            supplier_performance = self._get_random_nested("material_replenishment", "supplier_performance")
            supplier_defect_rate = self._get_random_nested("material_replenishment", "supplier_defect_rate")
            inventory_turnover = self._get_random_nested("material_replenishment", "inventory_turnover")
            carrying_cost = self._get_random_nested("material_replenishment", "carrying_costs")
            stockout_cost = self._get_random_nested("material_replenishment", "stockout_costs")
            expediting_cost = self._get_random_nested("material_replenishment", "expediting_costs")
            transportation_cost = self._get_random_nested("material_replenishment", "transportation_costs")
            warehouse_zone = self._get_random_nested("material_replenishment", "warehouse_zones")
            zone_congestion = self._get_random_nested("material_replenishment", "zone_congestion")
            material_starvation_risk = self._get_random_nested("material_replenishment", "material_starvation_risk")
            receiving_throughput_degradation = self._get_random_nested("material_replenishment", "receiving_throughput_degradation")
            dock_utilization = self._get_random_nested("material_replenishment", "dock_utilization")
            trailer_queue = self._get_random_nested("material_replenishment", "trailer_queue")
            detention_accumulation = self._get_random_nested("material_replenishment", "detention_accumulation")
            
            defect_rate = self._get_random_nested("quality_control", "defect_rates")
            quality_scrap_cost = self._get_random_nested("quality_control", "scrap_costs")
            quality_rework_rate = self._get_random_nested("quality_control", "rework_rate")
            quality_customer_return = self._get_random_nested("quality_control", "customer_returns")
            first_pass_yield = self._get_random_nested("quality_control", "first_pass_yield")
            inspection_backlog = self._get_random_nested("quality_control", "inspection_backlog")
            inspection_cycle_time = self._get_random_nested("quality_control", "inspection_cycle_time")
            quality_assurance_resource = self._get_random_nested("quality_control", "quality_assurance_resources")
            customer_complaint_rate = self._get_random_nested("quality_control", "customer_complaint_rate")
            field_failure_rate = self._get_random_nested("quality_control", "field_failure_rate")
            warranty_claim = self._get_random_nested("quality_control", "warranty_claims")
            quality_cost = self._get_random_nested("quality_control", "quality_cost")
            ppm_defect = self._get_random_nested("quality_control", "ppm_defects")
            quality_gate = self._get_random_nested("quality_control", "quality_gates")
            non_conformance = self._get_random_nested("quality_control", "non_conformances")
            inspection_pass_rate = self._get_random_nested("quality_control", "inspection_pass_rate")
            test_pass_rate = self._get_random_nested("quality_control", "test_pass_rate")
            measurement_accuracy = self._get_random_nested("quality_control", "measurement_accuracy")
            calibration_status = self._get_random_nested("quality_control", "calibration_status")
            quality_metrics_deviation = self._get_random_nested("quality_control", "quality_metrics_deviation")
            process_variation = self._get_random_nested("quality_control", "process_variation")
            specification_deviation = self._get_random_nested("quality_control", "specification_deviation")
            quality_documentation_gap = self._get_random_nested("quality_control", "quality_documentation_gap")
            traceability_issue = self._get_random_nested("quality_control", "traceability_issue")
            quality_hold_duration = self._get_random_nested("quality_control", "quality_hold_duration")
            quality_rework_time = self._get_random_nested("quality_control", "rework_time")
            quality_impact = self._get_random_nested("quality_control", "quality_impact")
            capa_required = self._get_random_nested("quality_control", "capa_required")
            regulatory_impact = self._get_random_nested("quality_control", "regulatory_impact")
            quality_equipment_failure = self._get_random_nested("quality_control", "quality_equipment_failure")
            inspection_frequency = self._get_random_nested("quality_control", "inspection_frequency")
            sample_size = self._get_random_nested("quality_control", "sample_size")
            acceptance_quality_limit = self._get_random_nested("quality_control", "acceptance_quality_limit")
            
            compliance_status = self._get_random_nested("compliance", "compliance_status")
            violation_severity = self._get_random_nested("compliance", "violation_severity")
            audit_frequency = self._get_random_nested("compliance", "audit_frequency")
            compliance_regulatory_fine = self._get_random_nested("compliance", "regulatory_fines")
            audit_finding = self._get_random_nested("compliance", "audit_findings")
            corrective_action_deadline = self._get_random_nested("compliance", "corrective_action_deadline")
            compliance_score = self._get_random_nested("compliance", "compliance_score")
            certification_status = self._get_random_nested("compliance", "certification_status")
            training_compliance = self._get_random_nested("compliance", "training_compliance")
            documentation_compliance = self._get_random_nested("compliance", "documentation_compliance")
            non_compliance_area = self._get_random_nested("compliance", "non_compliance_areas")
            regulatory_deadline = self._get_random_nested("compliance", "regulatory_deadline")
            audit_duration = self._get_random_nested("compliance", "audit_duration")
            compliance_risk = self._get_random_nested("compliance", "compliance_risk")
            standard_version = self._get_random_nested("compliance", "standard_version")
            audit_type = self._get_random_nested("compliance", "audit_type")
            certification_expiry = self._get_random_nested("compliance", "certification_expiry")
            compliance_cost = self._get_random_nested("compliance", "compliance_cost")
            penalty_accumulation = self._get_random_nested("compliance", "penalty_accumulation")
            reporting_deadline = self._get_random_nested("compliance", "reporting_deadline")
            compliance_data_breach_impact = self._get_random_nested("compliance", "data_breach_impact")
            privacy_compliance = self._get_random_nested("compliance", "privacy_compliance")
            environmental_compliance = self._get_random_nested("compliance", "environmental_compliance")
            safety_compliance = self._get_random_nested("compliance", "safety_compliance")
            quality_compliance = self._get_random_nested("compliance", "quality_compliance")
            regulatory_authority = self._get_random_nested("compliance", "regulatory_authorities")
            compliance_gap = self._get_random_nested("compliance", "compliance_gaps")
            compliance_remediation_time = self._get_random_nested("compliance", "remediation_time")
            audit_scope = self._get_random_nested("compliance", "audit_scope")
            certification_body = self._get_random_nested("compliance", "certification_body")
        else:
            asset = "asset"
            trailer = "TRK-XXX"
            dock = "DOCK-XX"
            detention_scenario = "detention scenario"
            bottleneck = "bottleneck"
            shop_floor_issue = "shop floor issue"
            predictive_indicator = "predictive indicator"
            safety_scenario = "safety scenario"
            edge_anomaly = "anomaly"
            packml_state = "unknown"
            alarm_code = "ALM-XXX"
            security_vuln = "vulnerability"
            data_anomaly = "data issue"
            iso = "ISO standard"
            osha = "OSHA standard"
            dot = "DOT regulation"
            receiving_issue = "receiving bottleneck"
            maintenance_conflict = "scheduling conflict"
            shop_floor_impact = "material starvation"
            
            # Default values for exhaustive variables
            dwell_time = "2 hours"
            detention_cost = "$500"
            appointment_adherence = "75%"
            yard_utilization = "85%"
            shipment_count = "10 shipments"
            production_risk = "2 production lines at risk"
            
            vibration_level = "5mm/s"
            temperature_reading = "80°C"
            time_to_failure = "72 hours"
            maintenance_backlog = "10 work orders"
            downtime_cost = "$2,000/hour"
            technician_availability = "2 technicians available"
            maintenance_duration = "8 hours"
            
            oee_metric = "70%"
            throughput_reduction = "25%"
            cycle_time_increase = "30%"
            quality_rate = "90%"
            downtime_hours = "4 hours"
            production_loss = "500 units"
            scrap_cost = "$2,000"
            rework_rate = "8%"
            customer_return = "10%"
            production_order = "3 production orders delayed"
            schedule_adherence = "75%"
            equipment_efficiency = "75%"
            line_utilization = "80%"
            
            incident_severity = "Moderate"
            personnel_affected = "2 personnel affected"
            root_cause_deadline = "48 hours"
            access_point = "2 access points"
            unauthorized_attempt = "3 unauthorized access attempts"
            data_exposure = "500 records"
            remediation_time = "24 hours"
            safety_cost = "$5,000"
            regulatory_fine = "$10,000"
            contributing_factor = "3 contributing factors identified"
            corrective_action = "4 corrective actions recommended"
            near_miss_severity = "Medium severity near-miss"
            incident_location = "Production area"
            injury_type = "Laceration"
            
            inventory_level = "1,000 units"
            replenishment_time = "24 hours"
            safety_stock_level = "500 units"
            stockout_risk = "2 production lines at risk"
            inventory_accuracy = "90%"
            pick_rate_degradation = "20%"
            putaway_time_increase = "30%"
            space_utilization = "85%"
            slot_availability = "10 slots available"
            sku_stockout = "3 SKUs experiencing stockouts"
            inventory_buffer_day = "15 days"
            order_fulfillment_accuracy = "90%"
            supplier_scorecard = "75/100"
            supplier_performance = "80% on-time delivery"
            supplier_defect_rate = "2%"
            inventory_turnover = "10 turns/year"
            carrying_cost = "$5,000/month"
            stockout_cost = "$5,000"
            expediting_cost = "$500"
            transportation_cost = "$1,000"
            warehouse_zone = "Zone A"
            zone_congestion = "3 zones experiencing congestion"
            material_starvation_risk = "2 production lines at risk"
            receiving_throughput_degradation = "30%"
            dock_utilization = "90%"
            trailer_queue = "5 trailers queued"
            detention_accumulation = "$100/hour"
            
            defect_rate = "3%"
            quality_scrap_cost = "$2,000"
            quality_rework_rate = "8%"
            quality_customer_return = "10%"
            first_pass_yield = "92%"
            inspection_backlog = "100 units"
            inspection_cycle_time = "40%"
            quality_assurance_resource = "4 QA inspectors"
            customer_complaint_rate = "1%"
            field_failure_rate = "1%"
            warranty_claim = "50 claims"
            quality_cost = "$15,000"
            ppm_defect = "500 PPM"
            quality_gate = "3 quality gates failing"
            non_conformance = "3 non-conformances logged"
            inspection_pass_rate = "92%"
            test_pass_rate = "92%"
            measurement_accuracy = "98%"
            calibration_status = "Calibration current"
            quality_metrics_deviation = "10%"
            process_variation = "10%"
            specification_deviation = "0.5mm"
            quality_documentation_gap = "Documentation incomplete"
            traceability_issue = "Lot traceability issue"
            quality_hold_duration = "8 hours"
            quality_rework_time = "2 hours"
            quality_impact = "10% increase in defects"
            capa_required = "2 CAPAs required"
            regulatory_impact = "ISO standard violation"
            quality_equipment_failure = "CMM calibration drift"
            inspection_frequency = "Daily"
            sample_size = "25 units"
            acceptance_quality_limit = "AQL 1.5"
            
            compliance_status = "Partially Compliant"
            violation_severity = "Major Violation"
            audit_frequency = "Annual"
            compliance_regulatory_fine = "$25,000"
            audit_finding = "3 findings"
            corrective_action_deadline = "30 days"
            compliance_score = "80/100"
            certification_status = "Certified"
            training_compliance = "90% trained"
            documentation_compliance = "85% complete"
            non_compliance_area = "3 areas non-compliant"
            regulatory_deadline = "90 days"
            audit_duration = "3 days"
            compliance_risk = "Medium Risk"
            standard_version = "ISO 9001:2015"
            audit_type = "Internal Audit"
            certification_expiry = "180 days to expiry"
            compliance_cost = "$25,000"
            penalty_accumulation = "$1,000/month"
            reporting_deadline = "30 days"
            compliance_data_breach_impact = "1,000 records affected"
            privacy_compliance = "85% compliant"
            environmental_compliance = "85% compliant"
            safety_compliance = "90% compliant"
            quality_compliance = "90% compliant"
            regulatory_authority = "OSHA"
            compliance_gap = "3 gaps identified"
            compliance_remediation_time = "4 weeks"
            audit_scope = "Full Scope Audit"
            certification_body = "Registrar-A"
        
        avg_severity = sum(link.get("severity_impact", 0.5) for link in links) / len(links) if links else 0.5
        severity_level = "critical" if avg_severity > 0.8 else "high" if avg_severity > 0.6 else "medium" if avg_severity > 0.4 else "low"
        
        # Enhanced single-domain analysis with detailed templates
        if len(domains) == 1:
            domain = domains[0]
            if domain == "EDGE_AI_TELEMETRY":
                templates = [
                    f"Edge telemetry anomaly detected: {edge_anomaly} on {asset}. Sensor data indicates potential equipment degradation with progressive signal drift. Multi-sensor correlation suggests equipment performance issue requiring immediate investigation. Temperature readings show {random.randint(65, 85)}°C deviation from baseline, vibration patterns indicate mechanical stress. Predictive analysis recommends maintenance intervention within 24 hours to prevent cascading failure.",
                    f"Telemetry monitoring system flagged {edge_anomaly} on {asset}. Data quality metrics indicate calibration drift affecting measurement accuracy by {random.randint(10, 25)}%. Condition monitoring suggests predictive maintenance window approaching. Historical trend analysis shows similar patterns preceded equipment failure in previous incidents. Immediate recalibration recommended to maintain measurement integrity.",
                    f"Critical edge anomaly ({edge_anomaly}) detected on {asset}. Multi-sensor data fusion indicates equipment performance degradation with {random.randint(30, 50)}% efficiency loss. Predictive analysis recommends immediate intervention to prevent cascading failure. Correlated with {random.randint(2, 5)} other edge devices showing similar degradation patterns, suggesting systemic issue requiring fleet-wide assessment."
                ]
            elif domain == "PRODUCTION_OEE":
                templates = [
                    f"Production line degradation detected: asset {asset} in {packml_state} state with {alarm_code}. OEE metrics at {oee_metric} below threshold indicating equipment performance or scheduling inefficiency. Root cause analysis suggests {shop_floor_issue} with {throughput_reduction} throughput reduction. Equipment cycle time increased by {cycle_time_increase}, quality rate dropped to {quality_rate}. Maintenance intervention required within {downtime_hours} to prevent production stop. Production loss: {production_loss}, scrap cost: {scrap_cost}.",
                    f"Production efficiency decline on {asset} with {packml_state} state. {alarm_code} indicates potential equipment bottleneck or process constraint. Performance metrics suggest operational efficiency degradation requiring corrective action. Downtime accumulated {downtime_hours} this shift, scrap rate increased to {rework_rate}. Analysis suggests equipment performance issue or scheduling constraint impacting production throughput. Rework rate: {rework_rate}, customer returns: {customer_return}.",
                    f"OEE metrics falling below acceptable threshold on {asset}. {alarm_code} in {packml_state} state indicates operational inefficiency. Analysis suggests equipment performance issue or scheduling constraint impacting production throughput. Overall Equipment Effectiveness at {oee_metric} (target: 85%+). Schedule adherence at {schedule_adherence}, equipment efficiency at {equipment_efficiency}, line utilization at {line_utilization}. {production_order} delayed."
                ]
            elif domain == "LOGISTICS_FLEET":
                liability_options = ["driver_liability", "client_liability", "transport_liability", "yard_liability"]
                liability = self._get_random_nested("logistics", "detention_scenarios", random.choice(liability_options)) if self.state_space else "driver_liability"
                templates = [
                    f"Logistics fleet issue detected: {trailer} experiencing operational delays at {dock}. Dwell time exceeded threshold by {dwell_time}. Root cause analysis indicates {detention_scenario}. Liability determination suggests {liability.replace('_', ' ')} responsibility. Detention costs estimated at {detention_cost}. Coordination required between transport management, yard operations, and receiving to resolve bottleneck. Yard utilization at {yard_utilization}, appointment adherence at {appointment_adherence}.",
                    f"Trailer {trailer} dwell time exceeding thresholds at {dock}. Detention analysis identifies {detention_scenario}. Liability assessment indicates {liability.replace('_', ' ')} responsibility for delay. Process improvement needed in dock appointment scheduling. Current appointment adherence at {appointment_adherence}, target 95%+. Estimated demurrage costs {detention_cost}. {shipment_count} affected, {production_risk} if not resolved.",
                    f"Logistics coordination failure: {trailer} stuck at {dock} with {detention_scenario}. Multi-perspective analysis identifies {liability.replace('_', ' ')} as primary cause. Cross-functional coordination required to resolve. Impact on downstream operations: {shipment_count} delayed, {production_risk} if not resolved within {dwell_time}. Yard utilization at {yard_utilization} causing capacity constraints."
                ]
            elif domain == "COMPLIANCE_REGISTRIES":
                templates = [
                    f"Compliance violation detected for {iso} ({standard_version}). Operational procedures not meeting regulatory requirements. Gap analysis indicates process re-engineering required to achieve compliance. Compliance status: {compliance_status}, violation severity: {violation_severity}. Audit findings: {audit_finding}, {non_compliance_area}. Corrective action plan needed within {corrective_action_deadline} to avoid regulatory fines of {compliance_regulatory_fine}. Compliance score: {compliance_score} (passing: 85+).",
                    f"Regulatory non-compliance identified for {iso} by {regulatory_authority}. Operational audit reveals gaps in current procedures. Corrective action plan needed to address compliance deficiencies. Risk assessment: {compliance_risk}, audit type: {audit_type}. Potential fines up to {compliance_regulatory_fine} if not remediated within {regulatory_deadline}. Training compliance at {training_compliance}, documentation compliance at {documentation_compliance}.",
                    f"Compliance audit failure for {iso}. Process deviations from regulatory standards identified. Risk assessment indicates immediate remediation required to prevent regulatory violations. Audit duration: {audit_duration}, audit scope: {audit_scope}. Certification status: {certification_status}, certification expiry: {certification_expiry}. Compliance cost: {compliance_cost}, penalty accumulation: {penalty_accumulation}. {compliance_gap} identified, remediation time: {compliance_remediation_time}."
                ]
            elif domain == "SYSTEM_INFRASTRUCTURE":
                templates = [
                    f"Infrastructure degradation affecting {domain_map.get(domain, domain)}. Database or network performance issues causing operational impacts. Capacity analysis suggests resource scaling or optimization required. Database query response time increased by {random.randint(200, 500)}%, network latency averaging {random.randint(50, 150)}ms above baseline. System availability at {random.randint(92, 98)}% (target: 99.9%+).",
                    f"System performance degradation in {domain_map.get(domain, domain)}. Network latency or database bottlenecks affecting downstream operations. Performance monitoring indicates infrastructure constraint. Memory utilization at {random.randint(75, 95)}%, CPU at {random.randint(60, 85)}%. Disk I/O throughput degraded by {random.randint(30, 50)}%. Capacity planning and resource scaling needed.",
                    f"Infrastructure reliability issues in {domain_map.get(domain, domain)}. Resource constraints causing service degradation. Capacity planning required to address infrastructure limitations. Error rate increased to {random.uniform(0.5, 3):.1f}% (baseline: <0.1%). {random.randint(2, 5)} services experiencing intermittent failures. Load balancer showing uneven distribution across {random.randint(4, 8)} nodes."
                ]
            elif domain == "MAINTENANCE":
                templates = [
                    f"Maintenance operations issue detected: {predictive_indicator} indicates equipment degradation on {asset}. Predictive maintenance analysis suggests preventive maintenance window approaching. Resource coordination required. Vibration levels at {vibration_level} (threshold: 5mm/s), temperature {temperature_reading} above normal. Estimated time to failure: {time_to_failure} if not addressed. Maintenance backlog: {maintenance_backlog}, downtime cost: {downtime_cost}. Technician availability: {technician_availability}.",
                    f"Predictive maintenance alert: {predictive_indicator} on {asset} indicates impending failure. Condition monitoring recommends immediate preventive maintenance to prevent corrective action. Oil analysis shows metal particle increase, thermal imaging indicates hotspot. Maintenance backlog: {maintenance_backlog} work orders pending. Estimated maintenance duration: {maintenance_duration}. Downtime cost: {downtime_cost}.",
                    f"Maintenance escalation scenario: {predictive_indicator} indicates equipment performance degradation. Risk assessment suggests transition from predictive to preventive maintenance required. Current maintenance schedule has conflicts with production requirements. Resource allocation: {technician_availability}, {maintenance_duration} estimated for intervention. Time to failure: {time_to_failure} if not addressed."
                ]
            elif domain == "SAFETY":
                templates = [
                    f"Safety management issue detected: {safety_scenario} identified at {incident_location}. Risk assessment indicates immediate response required. Safety protocol activation and incident investigation needed. Incident severity: {incident_severity}. Potential impact: {personnel_affected}, estimated downtime {downtime_hours}. Root cause analysis required within {root_cause_deadline} per OSHA regulations. Safety cost: {safety_cost}. Injury type: {injury_type}.",
                    f"Security scenario detected: {safety_scenario} affecting operations. Multi-factor analysis indicates security protocol enhancement required. Incident response team activation recommended. Security breach detected at {access_point}, {unauthorized_attempt} logged. Data exposure: {data_exposure}. Remediation time: {remediation_time}. Regulatory fine: {regulatory_fine}. Contributing factors: {contributing_factor}. Corrective actions: {corrective_action}.",
                    f"Operational safety concern: {safety_scenario} identified. Risk mitigation requires immediate action. Safety assessment and protocol review recommended. Near-miss incident recorded, potential severity: {near_miss_severity}. Incident location: {incident_location}. Contributing factors: {contributing_factor}. Corrective actions: {corrective_action} to prevent recurrence. Safety compliance at {safety_compliance}."
                ]
            elif domain == "WAREHOUSE_MANAGEMENT":
                templates = [
                    f"Warehouse management issue detected: {bottleneck} in operations affecting throughput. Inventory accuracy at {inventory_accuracy} (target: 99%+). Pick rate degraded by {pick_rate_degradation}, put-away time increased by {putaway_time_increase}. Root cause analysis suggests process inefficiency or resource constraint. {zone_congestion}. Space utilization at {space_utilization}, slot availability: {slot_availability}.",
                    f"Warehouse operations bottleneck: {bottleneck} causing operational delays. Space utilization at {space_utilization}, slot availability limited to {slot_availability}. Order fulfillment cycle time increased. Analysis suggests layout optimization or process re-engineering required. {sku_stockout}. Inventory buffer days: {inventory_buffer_day}, order fulfillment accuracy at {order_fulfillment_accuracy}.",
                    f"Warehouse performance degradation: {bottleneck} in specific operations area. Labor productivity down, equipment utilization degraded. Root cause indicates process or resource constraint affecting operations. Inventory turnover rate: {inventory_turnover} (target: 20+). Carrying cost: {carrying_cost}. Stockout cost: {stockout_cost}. Warehouse zone: {warehouse_zone} experiencing issues."
                ]
            elif domain == "SUPPLY_CHAIN":
                templates = [
                    f"Supply chain disruption detected: Supplier performance degradation affecting material availability. On-time delivery rate dropped to {supplier_performance} (target: 95%+). Suppliers experiencing delivery delays. Risk assessment suggests diversification or inventory buffer required. Impact on production: {material_starvation_risk}. Supplier scorecard: {supplier_scorecard}.",
                    f"Supply chain bottleneck: Critical components experiencing supply constraints. Lead times increased by {replenishment_time}. Supplier quality issues detected: defect rate {supplier_defect_rate} (acceptable: <1%). Risk mitigation requires supplier development or alternative sourcing. Inventory buffer days: {inventory_buffer_day} (target: 30+). Expediting cost: {expediting_cost}.",
                    f"Supply chain performance degradation: Multiple suppliers showing performance issues. Order fulfillment accuracy at {order_fulfillment_accuracy}, response time increased. Analysis suggests systemic supply chain risk requiring strategic review. Supplier performance at {supplier_performance} average across suppliers. Transportation cost: {transportation_cost}. Inventory level: {inventory_level}."
                ]
            elif domain == "QUALITY_CONTROL":
                templates = [
                    f"Quality control issue detected: Defect rate increased to {defect_rate} (target: <1%). {quality_gate} failing inspection. Root cause analysis suggests process or equipment issue. Scrap costs: {quality_scrap_cost} this shift. Rework rate: {quality_rework_rate} of production. Customer returns increased by {quality_customer_return} month-over-month. First pass yield dropped to {first_pass_yield}.",
                    f"Quality degradation alert: {quality_gate} product lines showing quality issues. First pass yield dropped to {first_pass_yield} (target: 98%+). Analysis indicates process variation or equipment calibration issue. CAPA (Corrective and Preventive Action) required per {iso} standards. {non_conformance} logged. Inspection backlog: {inspection_backlog} units, inspection cycle time increased by {inspection_cycle_time}.",
                    f"Quality control bottleneck: Inspection backlog of {inspection_backlog} units. Quality assurance resources constrained, inspection cycle time increased by {inspection_cycle_time}. Risk assessment suggests potential quality escapes if not addressed. Customer complaint rate: {customer_complaint_rate} (target: <0.1%). Field failure rate: {field_failure_rate}. Warranty claims: {warranty_claim}. Quality cost: {quality_cost}. PPM defects: {ppm_defect}."
                ]
            elif domain == "ENERGY_MANAGEMENT":
                templates = [
                    f"Energy management issue detected: Power consumption exceeding baseline by {random.randint(15, 35)}%. {random.randint(2, 4)} production lines showing energy inefficiency. Root cause suggests equipment performance degradation or process optimization opportunity. Energy cost impact: ${random.randint(2000, 8000)} per month. Carbon footprint increased by {random.randint(10, 30)}%.",
                    f"Energy consumption anomaly: {random.randint(3, 6)} assets showing abnormal power usage patterns. Peak demand exceeded threshold {random.randint(2, 5)} times this week. Analysis suggests equipment maintenance or process adjustment required. Energy intensity: {random.uniform(1.5, 3.5):.1f} kWh/unit (target: <1.5 kWh/unit).",
                    f"Operational efficiency concern: Energy utilization efficiency degraded. Power factor at {random.uniform(0.75, 0.92):.2f} (target: 0.95+). {random.randint(2, 5)} motors showing efficiency loss. Energy management system alerts: {random.randint(3, 8)} active. Recommendations: equipment maintenance or process optimization."
                ]
            elif domain == "CYBERSECURITY":
                templates = [
                    f"Cybersecurity incident detected: {security_vuln} identified in system. Risk assessment indicates immediate patching required. Vulnerability severity: {severity_level.upper()}. Potential impact: unauthorized access to {random.randint(1, 5)} systems. Security team activation recommended. Estimated remediation time: {random.randint(4, 48)} hours.",
                    f"Security breach attempt detected: {random.randint(2, 6)} unauthorized access attempts logged. IP addresses: {random.randint(3, 8)} unique sources. Security protocols activated, investigation ongoing. Risk level: {severity_level.upper()}. Potential data exposure: {random.randint(100, 1000)} records. Incident response team engaged.",
                    f"Cybersecurity vulnerability: {security_vuln} requires immediate attention. Security assessment reveals {random.randint(2, 5)} systems at risk. Patch management backlog: {random.randint(5, 15)} critical patches pending. Compliance impact: potential {iso} violation if not addressed within {random.randint(7, 30)} days."
                ]
            elif domain == "FINANCE":
                templates = [
                    f"Financial operations issue detected: Accounts receivable aging increased by {random.randint(15, 40)}%. {random.randint(2, 5)} customers showing payment delays. Cash flow impact: ${random.randint(50000, 200000)} at risk. Root cause analysis suggests billing process or customer communication issue. Days Sales Outstanding (DSO): {random.randint(40, 65)} days (target: 30 days).",
                    f"Financial anomaly detected: {random.randint(2, 4)} transactions flagged for review. Discrepancy amount: ${random.randint(5000, 25000)}. Risk assessment suggests process control or system issue. Audit trail review required. Compliance implications: potential {dot} reporting requirements if material misstatement identified.",
                    f"Financial performance degradation: Budget variance of {random.randint(10, 30)}% in {random.randint(2, 4)} cost centers. Expense review required. Working capital position: {random.randint(15, 35)}% below target. Analysis suggests operational efficiency or cost control issue. Financial forecasting accuracy: {random.randint(75, 90)}% (target: 95%+)."
                ]
            else:
                templates = [
                    f"Operational anomaly detected in {domain_map.get(domain, domain)}. Process deviation detected with severity {avg_severity:.2f} ({severity_level}). Performance metrics indicate {random.randint(15, 40)}% degradation from baseline. Root cause analysis required to identify underlying cause. {random.randint(2, 5)} operational indicators showing deviation. Impact assessment: {random.randint(1, 3)} downstream processes affected.",
                    f"Performance degradation in {domain_map.get(domain, domain)}. Operational metrics indicating process deviation. Investigation needed to determine root cause and corrective action. Efficiency loss: {random.randint(20, 45)}%. Quality impact: {random.randint(5, 20)}% increase in defects or errors. Resource utilization: {random.randint(10, 30)}% above optimal.",
                    f"Process anomaly in {domain_map.get(domain, domain)}. Performance metrics outside normal operating range. Analysis required to identify cause and implement corrective action. Cycle time increased by {random.randint(25, 60)}%, throughput decreased by {random.randint(15, 40)}%. {random.randint(2, 4)} contributing factors identified through preliminary analysis."
                ]
            return random.choice(templates)
        
        # Enhanced multi-domain analysis with detailed templates
        if "LOGISTICS_FLEET" in domains and "PRODUCTION_OEE" in domains:
            liability_options = ["driver_liability", "client_liability", "transport_liability", "yard_liability"]
            liability = self._get_random_nested("logistics", "detention_scenarios", random.choice(liability_options)) if self.state_space else "yard_liability"
            templates = [
                f"Logistics delays with {trailer} at {dock} causing production line inefficiencies. Detention analysis identifies {detention_scenario} with {liability.replace('_', ' ')} responsibility. {shop_floor_impact} impacting production OEE. Production throughput reduced by {throughput_reduction}, {production_order} delayed. Cross-domain coordination required between logistics, production planning, and yard management. Dwell time: {dwell_time}, detention cost: {detention_cost}.",
                f"Production bottleneck caused by logistics misalignment: {trailer} delayed at {dock} due to {detention_scenario}. Liability assessment indicates {liability.replace('_', ' ')} responsibility. {shop_floor_impact} causing production efficiency degradation. Material starvation risk for {stockout_risk}. Estimated production loss: {production_loss}, revenue impact {scrap_cost}. OEE metrics at {oee_metric}, schedule adherence at {schedule_adherence}.",
                f"Cross-domain failure: {trailer} stuck at {dock} causing {shop_floor_impact} on production line. Multi-perspective analysis identifies {liability.replace('_', ' ')} as primary cause. Integrated remediation strategy required. Production schedule adherence dropped to {schedule_adherence}, customer delivery risk for {shipment_count}. Root cause: process misalignment between logistics appointment scheduling and production material requirements. Yard utilization at {yard_utilization}."
            ]
            return random.choice(templates)
        
        if "LOGISTICS_FLEET" in domains and "WAREHOUSE_MANAGEMENT" in domains:
            templates = [
                f"Logistics-warehouse coordination failure: {trailer} experiencing delays at {dock} due to {detention_scenario}. {receiving_issue} in warehouse operations causing detention. Cross-functional process integration required. Warehouse receiving throughput degraded by {receiving_throughput_degradation}, dock utilization at {dock_utilization}. {trailer_queue} queued for unloading. Detention accumulation: {detention_accumulation}.",
                f"Yard-warehouse bottleneck: {trailer} delayed at {dock} with {detention_scenario}. {receiving_issue} preventing efficient receiving operations. Process synchronization needed between yard and warehouse. Put-away time increased by {putaway_time_increase}, inventory accuracy at risk due to rushed processing. Space utilization at {space_utilization}, slot availability: {slot_availability}.",
                f"Logistics-warehouse misalignment: {trailer} stuck at {dock} due to {detention_scenario}. {receiving_issue} in warehouse causing extended detention. Operational coordination required. Impact on downstream: {sku_stockout}, potential stockout for material. Root cause: lack of real-time visibility between yard operations and warehouse receiving. Inventory level: {inventory_level}, replenishment time: {replenishment_time}."
            ]
            return random.choice(templates)
        
        if "MAINTENANCE" in domains and "PRODUCTION_OEE" in domains:
            templates = [
                f"Maintenance-production conflict: {maintenance_conflict} causing production OEE degradation. {predictive_indicator} indicates equipment requiring maintenance. Coordination between maintenance and production scheduling required. Production stop risk: {downtime_hours} if maintenance deferred. Equipment efficiency at {equipment_efficiency}, quality rate dropping to {quality_rate}. OEE metrics at {oee_metric}. Maintenance backlog: {maintenance_backlog}, downtime cost: {downtime_cost}.",
                f"Production efficiency impacted by maintenance: {predictive_indicator} on {asset} indicates maintenance requirement. {maintenance_conflict} preventing optimal production scheduling. Integrated planning needed. Maintenance backlog: {maintenance_backlog} work orders, critical. Production capacity loss: {throughput_reduction} due to equipment performance degradation. Maintenance duration: {maintenance_duration}, technician availability: {technician_availability}.",
                f"Maintenance-production misalignment: {maintenance_conflict} causing production line inefficiency. Predictive maintenance window conflicts with production requirements. Resource coordination required. Downtime cost: {downtime_cost} for affected production line. Risk of cascading equipment failure if maintenance deferred beyond {time_to_failure}. Schedule adherence at {schedule_adherence}, production loss: {production_loss}."
            ]
            return random.choice(templates)
        
        if "SYSTEM_INFRASTRUCTURE" in domains:
            other_domains = [d for d in domains if d != "SYSTEM_INFRASTRUCTURE"]
            templates = [
                f"Infrastructure degradation affecting {', '.join([domain_map.get(d, d) for d in other_domains])}. Network latency or database performance issues causing downstream operational impacts with severity {avg_severity:.2f} ({severity_level}). Infrastructure optimization required. System response time increased by {random.randint(200, 600)}ms, error rate {random.uniform(0.5, 3):.1f}%. {random.randint(3, 8)} services experiencing degraded performance.",
                f"System reliability issues impacting {', '.join([domain_map.get(d, d) for d in other_domains])}. Infrastructure bottlenecks causing cascading operational failures. Capacity planning and resource scaling needed. Database connection pool utilization at {random.randint(80, 98)}%, memory usage {random.randint(75, 95)}%. {random.randint(2, 5)} applications experiencing timeout errors.",
                f"Infrastructure performance degradation affecting {', '.join([domain_map.get(d, d) for d in other_domains])}. Database or network constraints limiting system throughput. Performance optimization required. Disk I/O wait time increased by {random.randint(150, 400)}%, network packet loss {random.uniform(0.1, 1.5):.1f}%. {random.randint(4, 10)} critical processes showing degraded performance."
            ]
            return random.choice(templates)
        
        if "COMPLIANCE_REGISTRIES" in domains:
            other_domains = [d for d in domains if d != "COMPLIANCE_REGISTRIES"]
            templates = [
                f"Compliance violation for {iso} detected in {', '.join([domain_map.get(d, d) for d in other_domains])}. Operational procedures not meeting regulatory requirements. Process re-engineering required across affected domains. Audit findings: {audit_finding}, {non_compliance_area}. Corrective action timeline: {corrective_action_deadline}. Compliance status: {compliance_status}, violation severity: {violation_severity}. Compliance score: {compliance_score} (passing: 85+). Regulatory authority: {regulatory_authority}.",
                f"Regulatory non-compliance identified across {', '.join([domain_map.get(d, d) for d in other_domains])}. {iso} requirements not met in current processes. Cross-domain corrective action plan needed. Risk assessment: {compliance_risk}, audit type: {audit_type}. Potential regulatory penalties up to {compliance_regulatory_fine}. Training compliance at {training_compliance}, documentation compliance at {documentation_compliance}. Audit frequency: {audit_frequency}.",
                f"Compliance audit failure for {iso} affecting {', '.join([domain_map.get(d, d) for d in other_domains])}. Process deviations from regulatory standards. Integrated remediation strategy required. Compliance score: {compliance_score} (passing: 85+). {compliance_gap} across affected domains. Audit duration: {audit_duration}, audit scope: {audit_scope}. Certification status: {certification_status}, certification expiry: {certification_expiry}. Compliance cost: {compliance_cost}."
            ]
            return random.choice(templates)
        
        # Generic multi-domain with enhanced detail
        templates = [
            f"Cascading anomaly across {', '.join([domain_map.get(d, d) for d in domains])}. Cross-domain dependency failure with severity {avg_severity:.2f} ({severity_level}). Multi-perspective analysis required to identify root cause and implement coordinated response. {random.randint(3, 8)} operational indicators showing deviation. Impact assessment: {random.randint(2, 5)} downstream processes affected, estimated efficiency loss {random.randint(20, 50)}%.",
            f"Multi-domain operational failure detected in {', '.join([domain_map.get(d, d) for d in domains])}. Cross-correlation analysis reveals dependency chain failure. Integrated remediation strategy needed across affected domains. Root cause indicators: {random.randint(2, 5)} identified. Recovery time estimate: {random.randint(4, 24)} hours. Business impact: ${random.randint(10000, 100000)} estimated.",
            f"Systemic anomaly affecting {', '.join([domain_map.get(d, d) for d in domains])}. Process dependencies causing cascading operational impacts. Cross-functional response team required for coordinated resolution. {random.randint(4, 10)} contributing factors identified through preliminary analysis. Risk escalation: {severity_level.upper()} priority. Stakeholder notification required for {random.randint(2, 6)} business units."
        ]
        return random.choice(templates)
    
    def _get_random_nested(self, file_name: str, key: str, default_value: str = None) -> str:
        """Get random value from nested state space structure"""
        if not self.state_space or file_name not in self.state_space.data:
            return default_value or key
        
        data = self.state_space.data[file_name]
        if key not in data:
            return default_value or key
        
        value = data[key]
        if isinstance(value, list):
            return random.choice(value) if value else (default_value or key)
        elif isinstance(value, dict):
            keys = list(value.keys())
            if keys:
                nested_key = random.choice(keys)
                nested_value = value[nested_key]
                if isinstance(nested_value, list):
                    return random.choice(nested_value) if nested_value else nested_key
                else:
                    return str(nested_value) if nested_value else nested_key
            else:
                return default_value or key
        else:
            return str(value) if value else (default_value or key)
    
    def _generate_tasks_with_state_space(self, domains: List[str]) -> List[Dict[str, Any]]:
        """Generate contextual kanban tasks using state space data"""
        tasks = []
        generic_task_templates = [
            {"title": "Investigate operational anomaly and root cause", "priority": "high", "task_type": "custom"},
            {"title": "Review process metrics and performance data", "priority": "medium", "task_type": "custom"},
            {"title": "Coordinate cross-domain response team", "priority": "high", "task_type": "custom"},
            {"title": "Implement corrective action plan", "priority": "high", "task_type": "custom"},
            {"title": "Monitor recovery and verify resolution", "priority": "medium", "task_type": "custom"}
        ]
        
        for domain in domains:
            num_tasks = random.randint(1, 2)
            selected_tasks = random.sample(generic_task_templates, min(num_tasks, len(generic_task_templates)))
            tasks.extend(selected_tasks)
        
        return tasks[:4]
    
    def _generate_commands_with_state_space(self, domains: List[str]) -> List[Dict[str, Any]]:
        """Generate relevant API commands using state space data"""
        commands = []
        generic_command_templates = [
            {"method": "GET", "endpoint": "/api/v1/operations/status", "description": "Check operational status"},
            {"method": "POST", "endpoint": "/api/v1/kanban/tasks", "description": "Create remediation task"},
            {"method": "POST", "endpoint": "/api/v1/commands/execute", "description": "Execute corrective action"},
            {"method": "GET", "endpoint": "/api/v1/metrics/current", "description": "Review current metrics"},
            {"method": "POST", "endpoint": "/api/v1/notifications/alert", "description": "Send alert notification"}
        ]
        
        for domain in domains:
            selected = random.choice(generic_command_templates)
            commands.append(selected)
        
        return commands
    
    def _identify_compliance_with_state_space(self, domains: List[str]) -> Optional[List[str]]:
        """Identify compliance implications using state space data"""
        if not self.state_space:
            return None
        
        implications = []
        
        compliance_sensitive_domains = [
            "SAFETY", "ENVIRONMENTAL", "CYBERSECURITY", "HR_ORGANIZATIONAL",
            "FINANCE", "SUPPLY_CHAIN", "QUALITY_CONTROL", "DATA_ANALYTICS"
        ]
        
        for domain in domains:
            if domain in compliance_sensitive_domains:
                iso = self._get_random_nested("compliance", "iso_standards")
                if iso:
                    implications.append(iso)
        
        return list(set(implications)) if implications else None
    
    def _calculate_risk_with_state_space(self, domains: List[str], links: List[Dict[str, Any]]) -> float:
        """Calculate risk score using domain criticality and link severity"""
        criticality_weights = {
            "EDGE_AI_TELEMETRY": 0.7,
            "PRODUCTION_OEE": 0.9,
            "LOGISTICS_FLEET": 0.6,
            "COMPLIANCE_REGISTRIES": 0.95,
            "SYSTEM_INFRASTRUCTURE": 0.85,
            "SAFETY": 0.95,
            "CYBERSECURITY": 0.95
        }
        
        base_score = sum(criticality_weights.get(d, 0.5) for d in domains) / len(domains)
        avg_severity = sum(link.get("severity_impact", 0.5) for link in links) / len(links) if links else 0.5
        
        risk_score = (base_score * 0.6 + avg_severity * 0.4) * 100
        variance = random.uniform(-5, 5)
        
        return round(max(0, min(100, risk_score + variance)), 1)


@dataclass
class ScenarioMetadata:
    """Metadata for tracking scenario generation"""
    scenario_id: str
    domains: List[str]
    scenario_type: str
    is_single_domain: bool
    severity_level: str
    generated_at: str


class EnhancedScenarioGenerator:
    """Enhanced scenario generator with balance control and validation"""
    
    def __init__(self, state_space: StateSpaceLoader, llm_generator: Optional[LLMGenerator] = None):
        self.state_space = state_space
        if llm_generator is None:
            self.llm_generator = LLMGenerator(state_space=state_space)
        else:
            llm_generator.state_space = state_space
            self.llm_generator = llm_generator
        
        self.scenario_count = 0
        self.metadata: List[ScenarioMetadata] = []
        
        # Distribution tracking
        self.domain_counts = defaultdict(int)
        self.scenario_type_counts = defaultdict(int)
        self.single_multi_count = {"single": 0, "multi": 0}
        
        # Scenario type classification
        self.scenario_types = [
            "detention_liability",
            "shop_floor_operations",
            "shipping_receiving",
            "yard_management",
            "preventative_maintenance",
            "predictive_maintenance",
            "security_physical",
            "security_cyber",
            "safety_incident",
            "operational_efficiency",
            "general_operational"
        ]
    
    def generate_balanced_scenario(
        self,
        target_domains: Optional[List[DomainType]] = None,
        force_single_domain: bool = False,
        force_multi_domain: bool = False,
        target_scenario_type: Optional[str] = None
    ) -> Tuple[CorrelationScenario, ScenarioMetadata]:
        """Generate a scenario with controlled balance"""
        self.scenario_count += 1
        scenario_id = f"SCENARIO_{self.scenario_count:06d}"
        
        # Determine single vs multi-domain
        if force_single_domain:
            num_domains = 1
            is_single_domain = True
        elif force_multi_domain:
            num_domains = random.choice([3, 4, 5])
            is_single_domain = False
        else:
            # 50/50 split
            is_single_domain = random.random() < 0.5
            num_domains = 1 if is_single_domain else random.choice([3, 4, 5])
        
        # Select domains
        if target_domains:
            active_domains = target_domains[:num_domains]
        else:
            all_domains = list(DomainType)
            active_domains = random.sample(all_domains, num_domains)
        
        # Update domain counts
        for domain in active_domains:
            self.domain_counts[domain.value] += 1
        
        # Update single/multi count
        if is_single_domain:
            self.single_multi_count["single"] += 1
        else:
            self.single_multi_count["multi"] += 1
        
        # Determine scenario type
        scenario_type = target_scenario_type or self._classify_scenario_type(active_domains)
        self.scenario_type_counts[scenario_type] += 1
        
        # Generate domain links
        domain_links = []
        if len(active_domains) > 1:
            for i in range(len(active_domains) - 1):
                link = CrossDomainLink(
                    source_domain=active_domains[i],
                    target_domain=active_domains[i + 1],
                    interaction_key=self.state_space.get_random_asset(),
                    severity_impact=round(random.uniform(0.3, 0.95), 2),
                    correlation_type=random.choice(["causal", "temporal", "spatial", "logical"])
                )
                domain_links.append(link)
        
        # Generate ingested metrics
        ingested_metrics = self._generate_metrics(active_domains)
        
        # Generate ground truth
        ground_truth = self.llm_generator.generate_ground_truth(
            [d.value for d in active_domains],
            [m.model_dump() for m in ingested_metrics],
            [l.model_dump() for l in domain_links]
        )
        
        # Determine severity level with random distribution
        if domain_links:
            avg_severity = sum(l.severity_impact for l in domain_links) / len(domain_links)
        else:
            # Random severity for single-domain scenarios
            avg_severity = random.uniform(0.2, 0.95)
        
        severity_level = "critical" if avg_severity > 0.8 else "high" if avg_severity > 0.6 else "medium" if avg_severity > 0.4 else "low"
        
        # Create scenario
        scenario = CorrelationScenario(
            scenario_id=scenario_id,
            active_domains=active_domains,
            domain_links=domain_links,
            ingested_metrics=ingested_metrics,
            **ground_truth
        )
        
        # Create metadata
        metadata = ScenarioMetadata(
            scenario_id=scenario_id,
            domains=[d.value for d in active_domains],
            scenario_type=scenario_type,
            is_single_domain=is_single_domain,
            severity_level=severity_level,
            generated_at=datetime.now(timezone.utc).isoformat()
        )
        
        self.metadata.append(metadata)
        
        return scenario, metadata
    
    def _classify_scenario_type(self, domains: List[DomainType]) -> str:
        """Classify scenario type based on active domains"""
        domain_values = [d.value for d in domains]
        
        # Logistics-related scenarios
        if "LOGISTICS_FLEET" in domain_values:
            if "PRODUCTION_OEE" in domain_values:
                return "detention_liability"
            elif "WAREHOUSE_MANAGEMENT" in domain_values:
                return "shipping_receiving"
            else:
                return "yard_management"
        
        # Production-related scenarios
        if "PRODUCTION_OEE" in domain_values or "PRODUCTION_OUTPUT" in domain_values:
            if "MAINTENANCE" in domain_values:
                return "preventative_maintenance"
            else:
                return "shop_floor_operations"
        
        # Maintenance scenarios
        if "MAINTENANCE" in domain_values:
            if any(d in domain_values for d in ["PRODUCTION_OEE", "PRODUCTION_OUTPUT"]):
                return "preventative_maintenance"
            else:
                return "predictive_maintenance"
        
        # Security scenarios
        if "CYBERSECURITY" in domain_values:
            return "security_cyber"
        elif "SAFETY" in domain_values:
            return "safety_incident"
        elif any(d in domain_values for d in ["SYSTEM_INFRASTRUCTURE", "IT_OT_INTEGRATION"]):
            return "security_physical"
        
        # Efficiency scenarios
        if any(d in domain_values for d in ["ENERGY_MANAGEMENT", "PROCESS_OPTIMIZATION", "CONTINUOUS_IMPROVEMENT"]):
            return "operational_efficiency"
        
        # Default to general operational
        return "general_operational"
    
    def _generate_metrics(self, domains: List[DomainType]) -> List[OperationalMetric]:
        """Generate realistic metrics based on active domains"""
        metrics = []
        
        domain_to_file = {
            DomainType.EDGE: "assets",
            DomainType.PROD: "assets",
            DomainType.LOG: "logistics",
            DomainType.COMP: "compliance",
            DomainType.MAT: "material_replenishment",
            DomainType.OUT: "production_output",
            DomainType.PKG: "packaging",
            DomainType.DST: "distribution",
            DomainType.MNT: "maintenance",
            DomainType.QUA: "quality_control",
            DomainType.ENG: "energy_management",
            DomainType.WRK: "workforce",
            DomainType.SUP: "supply_chain",
            DomainType.WHS: "warehouse",
            DomainType.CUS: "customer_service",
            DomainType.FIN: "finance",
            DomainType.SAF: "safety",
            DomainType.ENV: "environmental",
            DomainType.PLN: "planning"
        }
        
        for domain in domains:
            file_name = domain_to_file.get(domain, domain.value.lower())
            
            if self.state_space and file_name in self.state_space.data:
                categories = list(self.state_space.data[file_name].keys())
                if categories:
                    category = random.choice(categories)
                    # Get random item from the category
                    category_data = self.state_space.data[file_name][category]
                    if isinstance(category_data, list):
                        item = random.choice(category_data) if category_data else "unknown"
                    elif isinstance(category_data, dict):
                        # If it's a dict, get a random key or value
                        keys = list(category_data.keys())
                        if keys:
                            key = random.choice(keys)
                            value = category_data[key]
                            if isinstance(value, list):
                                item = random.choice(value) if value else key
                            else:
                                item = value if value else key
                        else:
                            item = "unknown"
                    else:
                        item = str(category_data) if category_data else "unknown"
                    metrics.append(OperationalMetric(
                        endpoint=f"/api/v1/{domain.value.lower().replace('_', '-')}/metrics",
                        payload_snapshot={
                            "category": category,
                            "item": item,
                            "value": round(random.uniform(0, 100), 2),
                            "status": random.choice(["normal", "warning", "critical"])
                        }
                    ))
            else:
                # Fallback generic metric
                metrics.append(OperationalMetric(
                    endpoint=f"/api/v1/{domain.value.lower().replace('_', '-')}/status",
                    payload_snapshot={
                        "status": random.choice(["normal", "warning", "critical"]),
                        "metric_value": round(random.uniform(0, 100), 2),
                        "timestamp": datetime.now(timezone.utc).isoformat()
                    }
                ))
        
        return metrics
    
    def get_distribution_stats(self) -> Dict[str, Any]:
        """Get current distribution statistics"""
        return {
            "total_scenarios": self.scenario_count,
            "domain_distribution": dict(self.domain_counts),
            "scenario_type_distribution": dict(self.scenario_type_counts),
            "single_multi_ratio": self.single_multi_count,
            "severity_distribution": Counter(m.severity_level for m in self.metadata)
        }


class DatasetValidator:
    """Validation framework for dataset quality assurance"""
    
    @staticmethod
    def validate_json_format(scenario: Dict[str, Any]) -> Tuple[bool, Optional[str]]:
        """Validate JSON format and structure"""
        try:
            # Check required fields
            required_fields = ["scenario_id", "active_domains", "domain_links", "ingested_metrics", "predicted_root_cause", "risk_score"]
            for field in required_fields:
                if field not in scenario:
                    return False, f"Missing required field: {field}"
            
            # Validate predicted_root_cause
            if not scenario["predicted_root_cause"] or len(scenario["predicted_root_cause"]) < 10:
                return False, "predicted_root_cause too short or empty"
            
            # Validate risk_score
            risk_score = scenario.get("risk_score")
            if not isinstance(risk_score, (int, float)) or not (0 <= risk_score <= 100):
                return False, f"Invalid risk_score: {risk_score}"
            
            return True, None
        except Exception as e:
            return False, f"JSON validation error: {str(e)}"
    
    @staticmethod
    def detect_duplicates(scenarios: List[Dict[str, Any]]) -> Tuple[int, List[str]]:
        """Detect duplicate scenarios using hash-based deduplication"""
        seen_hashes = {}
        duplicates = []
        
        for scenario in scenarios:
            # Create hash of scenario content
            scenario_str = json.dumps(scenario, sort_keys=True)
            scenario_hash = hashlib.sha256(scenario_str.encode()).hexdigest()
            
            if scenario_hash in seen_hashes:
                duplicates.append(scenario["scenario_id"])
            else:
                seen_hashes[scenario_hash] = scenario["scenario_id"]
        
        return len(duplicates), duplicates
    
    @staticmethod
    def validate_domain_coverage(metadata: List[ScenarioMetadata], target_count: int, tolerance: float = 0.1) -> Dict[str, Any]:
        """Validate domain coverage is within tolerance"""
        domain_counts = Counter()
        for m in metadata:
            for domain in m.domains:
                domain_counts[domain] += 1
        
        expected_per_domain = target_count / 47
        min_threshold = expected_per_domain * (1 - tolerance)
        max_threshold = expected_per_domain * (1 + tolerance)
        
        out_of_tolerance = {}
        for domain, count in domain_counts.items():
            if count < min_threshold or count > max_threshold:
                out_of_tolerance[domain] = {
                    "count": count,
                    "expected": expected_per_domain,
                    "min_threshold": min_threshold,
                    "max_threshold": max_threshold
                }
        
        return {
            "in_tolerance": len(out_of_tolerance) == 0,
            "out_of_tolerance": out_of_tolerance,
            "domain_distribution": dict(domain_counts)
        }
    
    @staticmethod
    def validate_single_multi_ratio(metadata: List[ScenarioMetadata], target_ratio: float = 0.5, tolerance: float = 0.05) -> Dict[str, Any]:
        """Validate single/multi-domain ratio is within tolerance"""
        single_count = sum(1 for m in metadata if m.is_single_domain)
        multi_count = sum(1 for m in metadata if not m.is_single_domain)
        total = len(metadata)
        
        actual_ratio = single_count / total if total > 0 else 0
        min_threshold = target_ratio - tolerance
        max_threshold = target_ratio + tolerance
        
        in_tolerance = min_threshold <= actual_ratio <= max_threshold
        
        return {
            "in_tolerance": in_tolerance,
            "actual_ratio": actual_ratio,
            "target_ratio": target_ratio,
            "single_count": single_count,
            "multi_count": multi_count,
            "min_threshold": min_threshold,
            "max_threshold": max_threshold
        }
    
    @staticmethod
    def validate_severity_distribution(metadata: List[ScenarioMetadata]) -> Dict[str, Any]:
        """Validate severity distribution is balanced"""
        severity_counts = Counter(m.severity_level for m in metadata)
        total = len(metadata)
        
        distribution = {
            severity: count / total for severity, count in severity_counts.items()
        }
        
        return {
            "distribution": distribution,
            "counts": dict(severity_counts),
            "total": total
        }
    
    @staticmethod
    def generate_sample_review(scenarios: List[Dict[str, Any]], sample_size: int = 100) -> List[Dict[str, Any]]:
        """Generate random sample for manual review"""
        if len(scenarios) <= sample_size:
            return scenarios
        
        return random.sample(scenarios, sample_size)


def generate_balanced_dataset(
    num_scenarios: int = 50000,
    output_dir: str = "dataset",
    state_space_dir: str = "state_space",
    single_multi_ratio: float = 0.5
):
    """Generate balanced dataset with controlled distribution"""
    print(f"Loading state space from {state_space_dir}...")
    state_space = StateSpaceLoader(state_space_dir)
    
    print("Initializing enhanced scenario generator...")
    generator = EnhancedScenarioGenerator(state_space)
    
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # Create output structure: dataset/domain/scenario_type/
    all_domains = list(DomainType)
    
    # Calculate scenarios per domain
    domains_per_scenario = num_scenarios // 47
    
    print(f"Generating {num_scenarios} scenarios with balanced distribution...")
    print(f"Target: ~{domains_per_scenario} scenarios per domain")
    print(f"Single/multi-domain ratio: {single_multi_ratio}")
    
    # Phase 1: Generate scenarios with controlled distribution
    scenarios_by_domain_type: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
    all_scenarios: List[Dict[str, Any]] = []
    all_metadata: List[ScenarioMetadata] = []
    
    total_generated = 0
    for domain in all_domains:
        if total_generated >= num_scenarios:
            break
            
        print(f"Generating scenarios for domain: {domain.value}")
        
        scenarios_for_domain = 0
        target_for_domain = min(domains_per_scenario, num_scenarios - total_generated)
        
        while scenarios_for_domain < target_for_domain:
            # Alternate between single and multi-domain to ensure 50/50 split
            force_single = (scenarios_for_domain % 2 == 0)
            force_multi = not force_single
            
            # Generate scenario
            scenario, metadata = generator.generate_balanced_scenario(
                target_domains=[domain],
                force_single_domain=force_single,
                force_multi_domain=force_multi
            )
            
            # Convert to dict
            scenario_dict = scenario.model_dump()
            all_scenarios.append(scenario_dict)
            all_metadata.append(metadata)
            
            # Organize by domain and scenario type
            domain_key = domain.value.lower().replace('_', '-')
            scenario_type_key = metadata.scenario_type
            scenarios_by_domain_type[domain_key][scenario_type_key].append(scenario_dict)
            
            scenarios_for_domain += 1
            total_generated += 1
            
            if scenarios_for_domain % 100 == 0:
                print(f"  Generated {scenarios_for_domain}/{target_for_domain} for {domain.value}")
    
    print(f"Total scenarios generated: {len(all_scenarios)}")
    
    # Phase 2: Write scenarios to organized files
    print("Writing scenarios to organized files...")
    for domain_key, scenario_types in scenarios_by_domain_type.items():
        domain_path = output_path / domain_key
        domain_path.mkdir(parents=True, exist_ok=True)
        
        for scenario_type_key, scenarios in scenario_types.items():
            scenario_type_path = domain_path / scenario_type_key
            scenario_type_path.mkdir(parents=True, exist_ok=True)
            
            output_file = scenario_type_path / "scenarios.jsonl"
            with open(output_file, 'w') as f:
                for scenario in scenarios:
                    # Convert to fine-tuning format
                    example = FineTuningExample.from_scenario(scenario, DEFAULT_SYSTEM_PROMPT)
                    f.write(example.to_jsonl() + '\n')
            
            print(f"  Wrote {len(scenarios)} scenarios to {output_file}")
    
    # Phase 3: Generate distribution report
    print("Generating distribution report...")
    distribution_stats = generator.get_distribution_stats()
    
    report_path = output_path / "metadata" / "distribution_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(report_path, 'w') as f:
        json.dump(distribution_stats, f, indent=2)
    
    print(f"Distribution report saved to {report_path}")
    
    # Phase 4: Validation
    print("Running validation checks...")
    validator = DatasetValidator()
    
    # JSON format validation
    print("Validating JSON format...")
    json_errors = []
    for i, scenario in enumerate(all_scenarios):
        is_valid, error = validator.validate_json_format(scenario)
        if not is_valid:
            json_errors.append((i, error))
    
    print(f"JSON validation: {len(all_scenarios) - len(json_errors)}/{len(all_scenarios)} valid")
    if json_errors:
        print(f"  Errors: {len(json_errors)}")
    
    # Duplicate detection
    print("Detecting duplicates...")
    dup_count, dup_ids = validator.detect_duplicates(all_scenarios)
    print(f"Duplicate detection: {dup_count} duplicates found")
    
    # Domain coverage validation
    print("Validating domain coverage...")
    domain_validation = validator.validate_domain_coverage(all_metadata, num_scenarios)
    print(f"Domain coverage: {'PASS' if domain_validation['in_tolerance'] else 'FAIL'}")
    
    # Single/multi ratio validation
    print("Validating single/multi-domain ratio...")
    ratio_validation = validator.validate_single_multi_ratio(all_metadata, single_multi_ratio)
    print(f"Single/multi ratio: {'PASS' if ratio_validation['in_tolerance'] else 'FAIL'}")
    print(f"  Actual: {ratio_validation['actual_ratio']:.2f}, Target: {ratio_validation['target_ratio']:.2f}")
    
    # Severity distribution validation
    print("Validating severity distribution...")
    severity_validation = validator.validate_severity_distribution(all_metadata)
    print(f"Severity distribution: {severity_validation['distribution']}")
    
    # Generate validation report
    validation_report = {
        "json_validation": {
            "total": len(all_scenarios),
            "valid": len(all_scenarios) - len(json_errors),
            "invalid": len(json_errors),
            "errors": json_errors[:10]  # First 10 errors
        },
        "duplicate_detection": {
            "duplicates_found": dup_count,
            "duplicate_ids": dup_ids[:10]  # First 10 duplicates
        },
        "domain_coverage": domain_validation,
        "single_multi_ratio": ratio_validation,
        "severity_distribution": severity_validation
    }
    
    validation_report_path = output_path / "metadata" / "validation_report.json"
    with open(validation_report_path, 'w') as f:
        json.dump(validation_report, f, indent=2)
    
    print(f"Validation report saved to {validation_report_path}")
    
    # Phase 5: Generate sample review
    print("Generating sample for review...")
    sample_scenarios = validator.generate_sample_review(all_scenarios, sample_size=100)
    
    sample_path = output_path / "metadata" / "sample_review.jsonl"
    with open(sample_path, 'w') as f:
        for scenario in sample_scenarios:
            example = FineTuningExample.from_scenario(scenario, DEFAULT_SYSTEM_PROMPT)
            f.write(example.to_jsonl() + '\n')
    
    print(f"Sample review saved to {sample_path}")
    
    print(f"\nDataset generation complete!")
    print(f"Total scenarios: {len(all_scenarios)}")
    print(f"Output directory: {output_dir}")
    print(f"Estimated size: ~{len(all_scenarios) * 10 / 1024 / 1024:.2f} MB")


def split_dataset(
    input_dir: str = "dataset",
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1
):
    """Split dataset into train/validation/test sets maintaining balance"""
    input_path = Path(input_dir)
    
    print("Splitting dataset into train/validation/test sets...")
    print(f"Ratios: {train_ratio}/{val_ratio}/{test_ratio}")
    
    # Collect all scenarios
    all_scenarios = []
    for domain_path in input_path.iterdir():
        if domain_path.is_dir() and domain_path.name != "metadata":
            for scenario_type_path in domain_path.iterdir():
                if scenario_type_path.is_dir():
                    scenarios_file = scenario_type_path / "scenarios.jsonl"
                    if scenarios_file.exists():
                        with open(scenarios_file, 'r') as f:
                            for line in f:
                                scenario = json.loads(line)
                                scenario["_domain"] = domain_path.name
                                scenario["_scenario_type"] = scenario_type_path.name
                                all_scenarios.append(scenario)
    
    print(f"Total scenarios to split: {len(all_scenarios)}")
    
    # Shuffle scenarios
    random.shuffle(all_scenarios)
    
    # Calculate split indices
    total = len(all_scenarios)
    train_end = int(total * train_ratio)
    val_end = train_end + int(total * val_ratio)
    
    train_scenarios = all_scenarios[:train_end]
    val_scenarios = all_scenarios[train_end:val_end]
    test_scenarios = all_scenarios[val_end:]
    
    print(f"Train: {len(train_scenarios)}, Val: {len(val_scenarios)}, Test: {len(test_scenarios)}")
    
    # Create output directories
    for split in ["train", "validation", "test"]:
        split_path = input_path / split
        split_path.mkdir(exist_ok=True)
    
    # Write split datasets maintaining organization
    for split_name, scenarios in [("train", train_scenarios), ("validation", val_scenarios), ("test", test_scenarios)]:
        print(f"Writing {split_name} split...")
        
        # Organize by domain/scenario_type
        scenarios_by_type: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for scenario in scenarios:
            domain = scenario.pop("_domain")
            scenario_type = scenario.pop("_scenario_type")
            scenarios_by_type[domain][scenario_type].append(scenario)
        
        # Write to organized files
        for domain, scenario_types in scenarios_by_type.items():
            domain_path = input_path / split_name / domain
            domain_path.mkdir(parents=True, exist_ok=True)
            
            for scenario_type, type_scenarios in scenario_types.items():
                scenario_type_path = domain_path / scenario_type
                scenario_type_path.mkdir(parents=True, exist_ok=True)
                
                output_file = scenario_type_path / "scenarios.jsonl"
                with open(output_file, 'w') as f:
                    for scenario in type_scenarios:
                        f.write(json.dumps(scenario) + '\n')
        
        print(f"  {split_name}: {len(scenarios)} scenarios written")
    
    print("Dataset split complete!")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Enhanced synthetic data generation with balance control")
    parser.add_argument("num_scenarios", type=int, default=50000, nargs="?", help="Number of scenarios to generate")
    parser.add_argument("output_dir", type=str, default="dataset", nargs="?", help="Output directory")
    parser.add_argument("--state-space-dir", type=str, default="state_space", help="State space directory")
    parser.add_argument("--split-only", action="store_true", help="Only split existing dataset")
    parser.add_argument("--train-ratio", type=float, default=0.8, help="Train ratio")
    parser.add_argument("--val-ratio", type=float, default=0.1, help="Validation ratio")
    parser.add_argument("--test-ratio", type=float, default=0.1, help="Test ratio")
    
    args = parser.parse_args()
    
    if args.split_only:
        split_dataset(args.output_dir, args.train_ratio, args.val_ratio, args.test_ratio)
    else:
        generate_balanced_dataset(
            num_scenarios=args.num_scenarios,
            output_dir=args.output_dir,
            state_space_dir=args.state_space_dir
        )
        
        # Automatically split after generation
        split_dataset(args.output_dir, args.train_ratio, args.val_ratio, args.test_ratio)
