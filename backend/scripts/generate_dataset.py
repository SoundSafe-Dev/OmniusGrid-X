"""
Synthetic Data Generation Pipeline for OmniusGrid Correlation AI

Generates 10,000+ JSONL scenarios for Gemma 4 fine-tuning by combining
state space arrays with domain interaction rules and LLM-based reasoning.
"""

import json
import random
import sys
import os
from pathlib import Path
from typing import Dict, List, Any, Optional
from datetime import datetime, timezone

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
    print("Warning: google-generativeai not installed. LLM generation disabled.")


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
    
    def get_random(self, category: str, key: str, subkey: Optional[str] = None) -> Any:
        """Get random item from state space"""
        if category not in self.data:
            return None
        if key not in self.data[category]:
            return None
        if subkey:
            if subkey not in self.data[category][key]:
                return None
            return random.choice(self.data[category][key][subkey])
        return random.choice(self.data[category][key])
    
    def get_random_asset(self) -> str:
        """Get random asset from any category"""
        assets = []
        for category in self.data.values():
            for key, items in category.items():
                assets.extend(items)
        return random.choice(assets)


class LLMGenerator:
    """Generates realistic AI analysis using Google Gemini API or state space rules"""
    
    def __init__(self, api_key: Optional[str] = None, state_space: Optional[StateSpaceLoader] = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
        self.state_space = state_space
        self.model = None
        
        if LLM_AVAILABLE and self.api_key:
            try:
                genai.configure(api_key=self.api_key)
                self.model = genai.GenerativeModel('gemini-pro')
                print("LLM Generator initialized with Gemini Pro")
            except Exception as e:
                print(f"Warning: Failed to initialize LLM: {e}")
                self.model = None
    
    def is_available(self) -> bool:
        """Check if LLM is available for generation"""
        return self.model is not None
    
    def generate_ground_truth(
        self,
        domains: List[str],
        metrics: List[Dict[str, Any]],
        links: List[Dict[str, Any]]
    ) -> Dict[str, Any]:
        """Generate realistic ground truth using LLM or state space rules"""
        if self.is_available():
            return self._generate_with_llm(domains, metrics, links)
        else:
            return self._generate_with_state_space(domains, links)
    
    def _generate_with_llm(self, domains: List[str], metrics: List[Dict[str, Any]], links: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate using LLM"""
        prompt = self._construct_prompt(domains, metrics, links)
        try:
            response = self.model.generate_content(prompt)
            return self._parse_llm_response(response.text, domains)
        except Exception as e:
            print(f"LLM generation failed: {e}, falling back to state space")
            return self._generate_with_state_space(domains, links)
    
    def _construct_prompt(self, domains: List[str], metrics: List[Dict[str, Any]], links: List[Dict[str, Any]]) -> str:
        """Construct prompt for LLM generation"""
        prompt = f"""You are an expert industrial operations analyst for OmniusGrid. Analyze the following cross-domain scenario and provide a realistic correlation analysis.

Active Domains: {', '.join(domains)}

Operational Metrics:
"""
        for metric in metrics:
            prompt += f"- {metric['endpoint']}: {metric['payload_snapshot']}\n"
        
        prompt += f"""
Domain Links:
"""
        for link in links:
            prompt += f"- {link['source_domain']} -> {link['target_domain']} (severity: {link['severity_impact']})\n"
        
        prompt += """
Provide your analysis in the following JSON format:
{
    "predicted_root_cause": "Clear explanation of the root cause",
    "risk_score": "Number between 0 and 100",
    "target_kanban_tasks": [
        {"title": "Task title", "priority": "low/medium/high/critical", "task_type": "type"}
    ],
    "remediation_commands": [
        {"method": "HTTP method", "endpoint": "API endpoint", "description": "Description"}
    ],
    "compliance_implications": ["List of compliance standards if applicable"]
}

Respond ONLY with valid JSON, no additional text."""
        return prompt
    
    def _parse_llm_response(self, response_text: str, domains: List[str]) -> Dict[str, Any]:
        """Parse LLM response into ground truth dictionary"""
        try:
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                return json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
        except Exception as e:
            print(f"Failed to parse LLM response: {e}")
            return self._generate_with_state_space(domains, [])
    
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
        """Analyze root cause using enhanced state space data with multi-perspective analysis"""
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
            edge_anomaly = self.state_space.get_random("errors", "edge_anomalies")
            packml_state = self.state_space.get_random("errors", "packml_states")
            alarm_code = self.state_space.get_random("errors", "alarm_codes")
            security_vuln = self.state_space.get_random("errors", "security_vulnerabilities")
            data_anomaly = self.state_space.get_random("errors", "data_anomalies")
            asset = self.state_space.get_random_asset()
            trailer = self.state_space.get_random("logistics", "trailers")
            dock = self.state_space.get_random("logistics", "dock_doors")
            detention_scenario = self.state_space.get_random("logistics", "detention_scenarios", "driver_liability")
            bottleneck = self.state_space.get_random("logistics", "yard_bottlenecks", "dock_congestion")
            shop_floor_issue = self.state_space.get_random("production_output", "shop_floor_scenarios", "production_bottlenecks")
            predictive_indicator = self.state_space.get_random("maintenance", "predictive_indicators", "vibration_analysis")
            safety_scenario = self.state_space.get_random("safety", "security_scenarios", "physical_security")
        else:
            edge_anomaly = "anomaly"
            packml_state = "unknown"
            alarm_code = "ALM-XXX"
            security_vuln = "vulnerability"
            data_anomaly = "data issue"
            asset = "asset"
            trailer = "TRK-XXX"
            dock = "DOCK-XX"
            detention_scenario = "detention scenario"
            bottleneck = "bottleneck"
            shop_floor_issue = "shop floor issue"
            predictive_indicator = "predictive indicator"
            safety_scenario = "safety scenario"
        
        avg_severity = sum(link.get("severity_impact", 0.5) for link in links) / len(links) if links else 0.5
        severity_level = "critical" if avg_severity > 0.8 else "high" if avg_severity > 0.6 else "medium" if avg_severity > 0.4 else "low"
        
        # Enhanced multi-perspective analysis
        if len(domains) == 1:
            domain = domains[0]
            if domain == "EDGE_AI_TELEMETRY":
                templates = [
                    f"Edge telemetry anomaly detected: {edge_anomaly} on {asset}. Sensor data indicates potential equipment degradation with progressive signal drift. Multi-sensor correlation suggests equipment performance issue requiring immediate investigation.",
                    f"Telemetry monitoring system flagged {edge_anomaly} on {asset}. Data quality metrics indicate calibration drift affecting measurement accuracy. Condition monitoring suggests predictive maintenance window approaching.",
                    f"Critical edge anomaly ({edge_anomaly}) detected on {asset}. Multi-sensor data fusion indicates equipment performance degradation. Predictive analysis recommends immediate intervention to prevent cascading failure."
                ]
            elif domain == "PRODUCTION_OEE":
                templates = [
                    f"Production line degradation detected: asset in {packml_state} state with {alarm_code}. OEE metrics below threshold indicating equipment performance or scheduling inefficiency. Root cause analysis suggests equipment maintenance or process optimization required.",
                    f"Production efficiency decline on {asset} with {packml_state} state. {alarm_code} indicates potential equipment bottleneck or process constraint. Performance metrics suggest operational efficiency degradation requiring corrective action.",
                    f"OEE metrics falling below acceptable threshold on {asset}. {alarm_code} in {packml_state} state indicates operational inefficiency. Analysis suggests equipment performance issue or scheduling constraint impacting production throughput."
                ]
            elif domain == "LOGISTICS_FLEET":
                liability = self.state_space.get_random("logistics", "detention_scenarios", random.choice(["driver_liability", "client_liability", "transport_liability", "yard_liability"])) if self.state_space else "driver_liability"
                templates = [
                    f"Logistics fleet issue detected: {trailer} experiencing operational delays at {dock}. Root cause analysis indicates {detention_scenario}. Liability determination suggests {liability.replace('_', ' ')} responsibility. Coordination required.",
                    f"Trailer {trailer} dwell time exceeding thresholds at {dock}. Detention analysis identifies {detention_scenario}. Liability assessment indicates {liability.replace('_', ' ')} responsibility for delay. Process improvement needed.",
                    f"Logistics coordination failure: {trailer} stuck at {dock} with {detention_scenario}. Multi-perspective analysis identifies {liability.replace('_', ' ')} as primary cause. Cross-functional coordination required to resolve."
                ]
            elif domain == "COMPLIANCE_REGISTRIES":
                iso = self.state_space.get_random("compliance", "iso_standards") if self.state_space else "ISO standard"
                templates = [
                    f"Compliance violation detected for {iso}. Operational procedures not meeting regulatory requirements. Gap analysis indicates process re-engineering required to achieve compliance.",
                    f"Regulatory non-compliance identified for {iso}. Operational audit reveals gaps in current procedures. Corrective action plan needed to address compliance deficiencies.",
                    f"Compliance audit failure for {iso}. Process deviations from regulatory standards identified. Risk assessment indicates immediate remediation required to prevent regulatory violations."
                ]
            elif domain == "SYSTEM_INFRASTRUCTURE":
                templates = [
                    f"Infrastructure degradation affecting {domain_map.get(domain, domain)}. Database or network performance issues causing operational impacts. Capacity analysis suggests resource scaling or optimization required.",
                    f"System performance degradation in {domain_map.get(domain, domain)}. Network latency or database bottlenecks affecting downstream operations. Performance monitoring indicates infrastructure constraint.",
                    f"Infrastructure reliability issues in {domain_map.get(domain, domain)}. Resource constraints causing service degradation. Capacity planning required to address infrastructure limitations."
                ]
            elif domain == "MAINTENANCE":
                templates = [
                    f"Maintenance operations issue detected: {predictive_indicator} indicates equipment degradation. Predictive maintenance analysis suggests preventive maintenance window approaching. Resource coordination required.",
                    f"Predictive maintenance alert: {predictive_indicator} on {asset} indicates impending failure. Condition monitoring recommends immediate preventive maintenance to prevent corrective action.",
                    f"Maintenance escalation scenario: {predictive_indicator} indicates equipment performance degradation. Risk assessment suggests transition from predictive to preventive maintenance required."
                ]
            elif domain == "SAFETY":
                templates = [
                    f"Safety management issue detected: {safety_scenario} identified. Risk assessment indicates immediate response required. Safety protocol activation and incident investigation needed.",
                    f"Security scenario detected: {safety_scenario} affecting operations. Multi-factor analysis indicates security protocol enhancement required. Incident response team activation recommended.",
                    f"Operational security concern: {safety_scenario} identified. Risk mitigation requires immediate action. Security assessment and protocol review recommended."
                ]
            else:
                templates = [
                    f"Operational anomaly detected in {domain_map.get(domain, domain)}. Process deviation detected with severity {avg_severity:.2f}. Root cause analysis required to identify underlying cause.",
                    f"Performance degradation in {domain_map.get(domain, domain)}. Operational metrics indicating process deviation. Investigation needed to determine root cause and corrective action.",
                    f"Process anomaly in {domain_map.get(domain, domain)}. Performance metrics outside normal operating range. Analysis required to identify cause and implement corrective action."
                ]
            return random.choice(templates)
        
        # Enhanced multi-domain correlation with liability and perspective analysis
        if "LOGISTICS_FLEET" in domains and "PRODUCTION_OEE" in domains:
            shop_floor_impact = self.state_space.get_random("logistics", "shop_floor_impacts", "material_starvation") if self.state_space else "material starvation"
            liability = self.state_space.get_random("logistics", "detention_scenarios", random.choice(["driver_liability", "client_liability", "transport_liability", "yard_liability"])) if self.state_space else "yard_liability"
            templates = [
                f"Logistics delays with {trailer} at {dock} causing production line inefficiencies. Detention analysis identifies {detention_scenario} with {liability.replace('_', ' ')} responsibility. {shop_floor_impact} impacting production OEE. Cross-domain coordination required.",
                f"Production bottleneck caused by logistics misalignment: {trailer} delayed at {dock} due to {detention_scenario}. Liability assessment indicates {liability.replace('_', ' ')} responsibility. {shop_floor_impact} causing production efficiency degradation.",
                f"Cross-domain failure: {trailer} stuck at {dock} causing {shop_floor_impact} on production line. Multi-perspective analysis identifies {liability.replace('_', ' ')} as primary cause. Integrated remediation strategy required."
            ]
            return random.choice(templates)
        
        if "LOGISTICS_FLEET" in domains and "WAREHOUSE_MANAGEMENT" in domains:
            receiving_issue = self.state_space.get_random("logistics", "shipping_receiving", "receiving_bottlenecks") if self.state_space else "receiving bottleneck"
            templates = [
                f"Logistics-warehouse coordination failure: {trailer} experiencing delays at {dock} due to {detention_scenario}. {receiving_issue} in warehouse operations causing detention. Cross-functional process integration required.",
                f"Yard-warehouse bottleneck: {trailer} delayed at {dock} with {detention_scenario}. {receiving_issue} preventing efficient receiving operations. Process synchronization needed between yard and warehouse.",
                f"Logistics-warehouse misalignment: {trailer} stuck at {dock} due to {detention_scenario}. {receiving_issue} in warehouse causing extended detention. Operational coordination required."
            ]
            return random.choice(templates)
        
        if "MAINTENANCE" in domains and "PRODUCTION_OEE" in domains:
            maintenance_conflict = self.state_space.get_random("maintenance", "maintenance_conflicts", "scheduling_conflicts") if self.state_space else "scheduling conflict"
            templates = [
                f"Maintenance-production conflict: {maintenance_conflict} causing production OEE degradation. {predictive_indicator} indicates equipment requiring maintenance. Coordination between maintenance and production scheduling required.",
                f"Production efficiency impacted by maintenance: {predictive_indicator} on {asset} indicates maintenance requirement. {maintenance_conflict} preventing optimal production scheduling. Integrated planning needed.",
                f"Maintenance-production misalignment: {maintenance_conflict} causing production line inefficiency. Predictive maintenance window conflicts with production requirements. Resource coordination required."
            ]
            return random.choice(templates)
        
        if "SYSTEM_INFRASTRUCTURE" in domains:
            other_domains = [d for d in domains if d != "SYSTEM_INFRASTRUCTURE"]
            templates = [
                f"Infrastructure degradation affecting {', '.join([domain_map.get(d, d) for d in other_domains])}. Network latency or database performance issues causing downstream operational impacts with severity {avg_severity:.2f}. Infrastructure optimization required.",
                f"System reliability issues impacting {', '.join([domain_map.get(d, d) for d in other_domains])}. Infrastructure bottlenecks causing cascading operational failures. Capacity planning and resource scaling needed.",
                f"Infrastructure performance degradation affecting {', '.join([domain_map.get(d, d) for d in other_domains])}. Database or network constraints limiting system throughput. Performance optimization required."
            ]
            return random.choice(templates)
        
        if "COMPLIANCE_REGISTRIES" in domains:
            iso = self.state_space.get_random("compliance", "iso_standards") if self.state_space else "ISO standard"
            other_domains = [d for d in domains if d != "COMPLIANCE_REGISTRIES"]
            templates = [
                f"Compliance violation for {iso} detected in {', '.join([domain_map.get(d, d) for d in other_domains])}. Operational procedures not meeting regulatory requirements. Process re-engineering required across affected domains.",
                f"Regulatory non-compliance identified across {', '.join([domain_map.get(d, d) for d in other_domains])}. {iso} requirements not met in current processes. Cross-domain corrective action plan needed.",
                f"Compliance audit failure for {iso} affecting {', '.join([domain_map.get(d, d) for d in other_domains])}. Process deviations from regulatory standards. Integrated remediation strategy required."
            ]
            return random.choice(templates)
        
        # Generic multi-domain correlation with enhanced narrative
        templates = [
            f"Cascading anomaly across {', '.join([domain_map.get(d, d) for d in domains])}. Cross-domain dependency failure with severity {avg_severity:.2f}. Multi-perspective analysis required to identify root cause and implement coordinated response.",
            f"Multi-domain operational failure detected in {', '.join([domain_map.get(d, d) for d in domains])}. Cross-correlation analysis reveals dependency chain failure. Integrated remediation strategy needed across affected domains.",
            f"Systemic anomaly affecting {', '.join([domain_map.get(d, d) for d in domains])}. Process dependencies causing cascading operational impacts. Cross-functional response team required for coordinated resolution."
        ]
        return random.choice(templates)
    
    def _generate_tasks_with_state_space(self, domains: List[str]) -> List[Dict[str, Any]]:
        """Generate contextual kanban tasks using state space data"""
        tasks = []
        
        if self.state_space:
            asset = self.state_space.get_random_asset()
            trailer = self.state_space.get_random("logistics", "trailers")
        else:
            asset = "asset"
            trailer = "TRK-XXX"
        
        task_templates = {
            "EDGE_AI_TELEMETRY": [
                {"title": f"Calibrate edge sensors for {asset}", "priority": "high", "task_type": "maintenance_cm"},
                {"title": "Review telemetry data quality metrics", "priority": "medium", "task_type": "quality_inspection"},
                {"title": "Check edge agent connectivity and data transmission", "priority": "high", "task_type": "alarm_response"}
            ],
            "PRODUCTION_OEE": [
                {"title": f"Analyze production line downtime for {asset}", "priority": "high", "task_type": "maintenance_cm"},
                {"title": "Review and optimize production scheduling", "priority": "medium", "task_type": "custom"},
                {"title": "Perform preventive maintenance on production equipment", "priority": "medium", "task_type": "maintenance_pm"}
            ],
            "LOGISTICS_FLEET": [
                {"title": f"Review dock appointment scheduling for {trailer}", "priority": "high", "task_type": "custom"},
                {"title": "Analyze detention and demurrage costs", "priority": "medium", "task_type": "custom"},
                {"title": "Optimize trailer yard flow and dock assignment", "priority": "high", "task_type": "custom"}
            ],
            "COMPLIANCE_REGISTRIES": [
                {"title": "Conduct compliance audit for affected processes", "priority": "critical", "task_type": "safety_check"},
                {"title": "Update standard operating procedures", "priority": "high", "task_type": "custom"},
                {"title": "Document compliance gaps and remediation plan", "priority": "high", "task_type": "custom"}
            ],
            "SYSTEM_INFRASTRUCTURE": [
                {"title": "Investigate database performance degradation", "priority": "critical", "task_type": "maintenance_cm"},
                {"title": "Review network latency and connectivity", "priority": "high", "task_type": "alarm_response"},
                {"title": "Scale infrastructure resources if needed", "priority": "medium", "task_type": "custom"}
            ]
        }
        
        # Generic task templates for new domains
        generic_task_templates = [
            {"title": "Investigate operational anomaly and root cause", "priority": "high", "task_type": "custom"},
            {"title": "Review process metrics and performance data", "priority": "medium", "task_type": "custom"},
            {"title": "Coordinate cross-domain response team", "priority": "high", "task_type": "custom"},
            {"title": "Implement corrective action plan", "priority": "high", "task_type": "custom"},
            {"title": "Monitor recovery and verify resolution", "priority": "medium", "task_type": "custom"}
        ]
        
        for domain in domains:
            if domain in task_templates:
                num_tasks = random.randint(1, 2)
                selected_tasks = random.sample(task_templates[domain], min(num_tasks, len(task_templates[domain])))
                tasks.extend(selected_tasks)
            else:
                # Use generic tasks for new domains
                num_tasks = random.randint(1, 2)
                selected_tasks = random.sample(generic_task_templates, num_tasks)
                tasks.extend(selected_tasks)
        
        return tasks[:4]
    
    def _generate_commands_with_state_space(self, domains: List[str]) -> List[Dict[str, Any]]:
        """Generate relevant API commands using state space data"""
        commands = []
        
        if self.state_space:
            asset = self.state_space.get_random_asset()
            trailer = self.state_space.get_random("logistics", "trailers")
        else:
            asset = "asset"
            trailer = "TRK-XXX"
        
        command_templates = {
            "EDGE_AI_TELEMETRY": [
                {"method": "POST", "endpoint": f"/api/v1/commands/asset/{asset}/emergency-stop", "description": f"Execute emergency stop on {asset}"},
                {"method": "POST", "endpoint": f"/api/v1/commands/asset/{asset}/restart", "description": f"Restart edge agent for {asset}"},
                {"method": "GET", "endpoint": f"/api/v1/telemetry/latest/{asset}", "description": f"Verify current telemetry for {asset}"}
            ],
            "PRODUCTION_OEE": [
                {"method": "POST", "endpoint": "/api/v1/kanban/boards/1/tasks", "description": "Create maintenance task for production line"},
                {"method": "POST", "endpoint": "/api/v1/operations/{operation_id}/pause", "description": "Pause production operation for maintenance"},
                {"method": "GET", "endpoint": f"/api/v1/oee/current/{asset}", "description": f"Check current OEE for {asset}"}
            ],
            "LOGISTICS_FLEET": [
                {"method": "POST", "endpoint": "/api/v1/yard/dock/appointments", "description": f"Reschedule dock appointment for {trailer}"},
                {"method": "POST", "endpoint": "/api/v1/logistics/predict-detention", "description": "Run detention risk prediction"},
                {"method": "GET", "endpoint": "/api/v1/yard/dwell-times", "description": "Review current dwell time analytics"}
            ],
            "COMPLIANCE_REGISTRIES": [
                {"method": "POST", "endpoint": "/api/v1/registries/{id}/items", "description": "Log compliance near-miss incident"},
                {"method": "GET", "endpoint": "/api/v1/registries/{id}/compliance-score", "description": "Calculate current compliance score"},
                {"method": "POST", "endpoint": "/api/v1/registries/{id}/items", "description": "Create corrective action item"}
            ],
            "SYSTEM_INFRASTRUCTURE": [
                {"method": "GET", "endpoint": "/admin/system/status", "description": "Check system health status"},
                {"method": "POST", "endpoint": "/admin/collectors/{id}/restart", "description": "Restart affected collectors"},
                {"method": "GET", "endpoint": "/api/v1/dashboard/oee", "description": "Review system-wide metrics"}
            ]
        }
        
        # Generic command templates for new domains
        generic_command_templates = [
            {"method": "GET", "endpoint": "/api/v1/operations/status", "description": "Check operational status"},
            {"method": "POST", "endpoint": "/api/v1/kanban/tasks", "description": "Create remediation task"},
            {"method": "POST", "endpoint": "/api/v1/commands/execute", "description": "Execute corrective action"},
            {"method": "GET", "endpoint": "/api/v1/metrics/current", "description": "Review current metrics"},
            {"method": "POST", "endpoint": "/api/v1/notifications/alert", "description": "Send alert notification"}
        ]
        
        for domain in domains:
            if domain in command_templates:
                selected = random.choice(command_templates[domain])
                commands.append(selected)
            else:
                # Use generic commands for new domains
                selected = random.choice(generic_command_templates)
                commands.append(selected)
        
        return commands
    
    def _identify_compliance_with_state_space(self, domains: List[str]) -> Optional[List[str]]:
        """Identify compliance implications using state space data"""
        if not self.state_space:
            return None
        
        implications = []
        
        # Original domain compliance mappings
        if "EDGE_AI_TELEMETRY" in domains:
            iso = self.state_space.get_random("compliance", "iso_standards")
            if iso:
                implications.append(iso)
        
        if "PRODUCTION_OEE" in domains:
            iso = self.state_space.get_random("compliance", "iso_standards")
            osha = self.state_space.get_random("compliance", "osha_standards")
            if iso:
                implications.append(iso)
            if osha:
                implications.append(osha)
        
        if "LOGISTICS_FLEET" in domains:
            dot = self.state_space.get_random("compliance", "dot_regulations")
            fsma = self.state_space.get_random("compliance", "fsma_requirements")
            if dot:
                implications.append(dot)
            if fsma:
                implications.append(fsma)
        
        if "COMPLIANCE_REGISTRIES" in domains:
            ctpat = self.state_space.get_random("compliance", "ctpat_rules")
            if ctpat:
                implications.append(ctpat)
        
        if "SYSTEM_INFRASTRUCTURE" in domains:
            iso = self.state_space.get_random("compliance", "iso_standards")
            if iso:
                implications.append(iso)
        
        # New domain compliance mappings
        compliance_sensitive_domains = [
            "SAFETY", "ENVIRONMENTAL", "CYBERSECURITY", "HR_ORGANIZATIONAL",
            "FINANCE", "SUPPLY_CHAIN", "QUALITY_CONTROL", "DATA_ANALYTICS"
        ]
        
        for domain in domains:
            if domain in compliance_sensitive_domains:
                iso = self.state_space.get_random("compliance", "iso_standards")
                if iso and iso not in implications:
                    implications.append(iso)
        
        # Add GDPR/CCPA for data-related domains
        if any(d in domains for d in ["DATA_ANALYTICS", "CYBERSECURITY", "HR_ORGANIZATIONAL"]):
            gdpr = self.state_space.get_random("compliance", "gdpr_requirements")
            if gdpr and gdpr not in implications:
                implications.append(gdpr)
        
        return list(set(implications)) if implications else None
    
    def _calculate_risk_with_state_space(self, domains: List[str], links: List[Dict[str, Any]]) -> float:
        """Calculate risk score using domain criticality and link severity"""
        criticality_weights = {
            "EDGE_AI_TELEMETRY": 0.7,
            "PRODUCTION_OEE": 0.9,
            "LOGISTICS_FLEET": 0.6,
            "COMPLIANCE_REGISTRIES": 0.95,
            "SYSTEM_INFRASTRUCTURE": 0.85,
            "MATERIAL_REPLENISHMENT": 0.75,
            "PRODUCTION_OUTPUT": 0.85,
            "PACKAGING": 0.65,
            "DISTRIBUTION": 0.7,
            "MAINTENANCE": 0.8,
            "QUALITY_CONTROL": 0.85,
            "ENERGY_MANAGEMENT": 0.6,
            "WORKFORCE_MANAGEMENT": 0.7,
            "SUPPLY_CHAIN": 0.75,
            "WAREHOUSE_MANAGEMENT": 0.65,
            "CUSTOMER_SERVICE": 0.7,
            "FINANCE": 0.8,
            "SAFETY": 0.95,
            "ENVIRONMENTAL": 0.85,
            "PLANNING_SCHEDULING": 0.7,
            "CYBERSECURITY": 0.95,
            "DIGITAL_TWIN": 0.6,
            "IT_OT_INTEGRATION": 0.8,
            "DATA_ANALYTICS": 0.7,
            "PROJECT_MANAGEMENT": 0.6,
            "HR_ORGANIZATIONAL": 0.65,
            "REGULATORY_AUDIT": 0.85,
            "RISK_MANAGEMENT": 0.8,
            "INNOVATION_RD": 0.5,
            "CONTRACT_MANAGEMENT": 0.7,
            "ASSET_LIFECYCLE": 0.75,
            "PROCESS_OPTIMIZATION": 0.65,
            "SUPPLIER_RELATIONSHIP": 0.7,
            "INVENTORY_OPTIMIZATION": 0.7,
            "CHANGE_MANAGEMENT": 0.7,
            "KNOWLEDGE_MANAGEMENT": 0.5,
            "BUSINESS_INTELLIGENCE": 0.6,
            "CONTINUOUS_IMPROVEMENT": 0.6,
            "PRODUCT_LIFECYCLE": 0.75,
            "MANUFACTURING_EXECUTION_SYSTEM": 0.85,
            "FACILITIES_MANAGEMENT": 0.65,
            "TOOL_MANAGEMENT": 0.6,
            "CALIBRATION": 0.7,
            "SPARE_PARTS": 0.7,
            "DOCUMENT_MANAGEMENT": 0.5,
            "WORKFLOW_MANAGEMENT": 0.6,
            "ESG": 0.8
        }
        
        base_score = sum(criticality_weights.get(d, 0.5) for d in domains) / len(domains)
        avg_severity = sum(link.get("severity_impact", 0.5) for link in links) / len(links) if links else 0.5
        
        risk_score = (base_score * 0.6 + avg_severity * 0.4) * 100
        variance = random.uniform(-5, 5)
        
        return round(max(0, min(100, risk_score + variance)), 1)


class ScenarioGenerator:
    """Generates synthetic correlation scenarios"""
    
    def __init__(self, state_space: StateSpaceLoader, llm_generator: Optional[LLMGenerator] = None):
        self.state_space = state_space
        # Initialize LLMGenerator with state_space if not provided
        if llm_generator is None:
            self.llm_generator = LLMGenerator(state_space=state_space)
        else:
            # Update existing LLMGenerator with state_space
            llm_generator.state_space = state_space
            self.llm_generator = llm_generator
        self.scenario_count = 0
    
    def generate_scenario(self) -> CorrelationScenario:
        """Generate a single random correlation scenario"""
        self.scenario_count += 1
        scenario_id = f"SCENARIO_{self.scenario_count:05d}"
        
        # Randomly select 3-5 domains (increased from 2-3 for larger domain space)
        num_domains = random.choice([3, 4, 5])
        active_domains = random.sample(list(DomainType), num_domains)
        
        # Generate domain links
        domain_links = []
        for i in range(len(active_domains) - 1):
            link = CrossDomainLink(
                source_domain=active_domains[i],
                target_domain=active_domains[i + 1],
                interaction_key=self.state_space.get_random_asset(),
                severity_impact=round(random.uniform(0.3, 0.95), 2),
                correlation_type=random.choice(["causal", "temporal", "spatial", "logical"])
            )
            domain_links.append(link)
        
        # Generate ingested metrics based on active domains
        ingested_metrics = self._generate_metrics(active_domains)
        
        # Generate ground truth (simulated AI analysis)
        ground_truth = self._generate_ground_truth(active_domains, domain_links, ingested_metrics)
        
        return CorrelationScenario(
            scenario_id=scenario_id,
            active_domains=active_domains,
            domain_links=domain_links,
            ingested_metrics=ingested_metrics,
            **ground_truth
        )
    
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
            if domain == DomainType.EDGE:
                metrics.append(OperationalMetric(
                    endpoint="/api/v1/telemetry/latest/" + self.state_space.get_random("assets", "chillers"),
                    payload_snapshot={
                        "metric": random.choice(["temperature", "pressure", "vibration", "flow"]),
                        "value": round(random.uniform(0, 100), 2),
                        "status": random.choice(["normal", "warning", "critical"])
                    }
                ))
            elif domain == DomainType.PROD:
                metrics.append(OperationalMetric(
                    endpoint="/api/v1/oee/current/" + self.state_space.get_random("assets", "plcs"),
                    payload_snapshot={
                        "availability": round(random.uniform(50, 100), 1),
                        "performance": round(random.uniform(50, 100), 1),
                        "quality": round(random.uniform(50, 100), 1),
                        "oee": round(random.uniform(30, 95), 1),
                        "state": self.state_space.get_random("errors", "packml_states")
                    }
                ))
            elif domain == DomainType.LOG:
                metrics.append(OperationalMetric(
                    endpoint="/api/v1/logistics/predict-detention",
                    payload_snapshot={
                        "trailer_id": self.state_space.get_random("logistics", "trailers"),
                        "detention_risk": random.choice(["Low", "Medium", "High", "Critical"]),
                        "dwell_hours": round(random.uniform(0.5, 8.0), 1)
                    }
                ))
            elif domain == DomainType.COMP:
                metrics.append(OperationalMetric(
                    endpoint="/api/v1/registries/" + str(random.randint(1, 20)) + "/risk-score",
                    payload_snapshot={
                        "compliance_score": round(random.uniform(40, 100), 1),
                        "risk_level": random.choice(["Low", "Medium", "High", "Critical"]),
                        "standard": self.state_space.get_random("compliance", "iso_standards")
                    }
                ))
            elif domain == DomainType.SYS:
                metrics.append(OperationalMetric(
                    endpoint="/admin/system/status",
                    payload_snapshot={
                        "database_status": random.choice(["healthy", "degraded", "down"]),
                        "gateway_status": random.choice(["connected", "disconnected"]),
                        "mlops_status": random.choice(["active", "idle", "error"])
                    }
                ))
            else:
                # Generic metric generation for new domains
                file_name = domain_to_file.get(domain, "assets")
                if file_name in self.state_space.data:
                    categories = list(self.state_space.data[file_name].keys())
                    if categories:
                        category = random.choice(categories)
                        item = self.state_space.get_random(file_name, category)
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
    
    def _generate_ground_truth(self, domains: List[DomainType], links: List[CrossDomainLink], metrics: List[OperationalMetric]) -> Dict[str, Any]:
        """Generate simulated AI analysis for training"""
        domain_names = [d.value for d in domains]
        
        # Use LLMGenerator for ground truth (uses state space rules if LLM unavailable)
        metrics_dict = [m.model_dump() for m in metrics]
        links_dict = [l.model_dump() for l in links]
        return self.llm_generator.generate_ground_truth(domain_names, metrics_dict, links_dict)


def generate_dataset(
    num_scenarios: int = 10000,
    output_file: str = "dataset/training_data.jsonl",
    state_space_dir: str = "state_space",
    use_llm: bool = False,
    api_key: Optional[str] = None
):
    """Generate synthetic training dataset"""
    print(f"Loading state space from {state_space_dir}...")
    state_space = StateSpaceLoader(state_space_dir)
    
    # Initialize LLM generator if requested
    llm_generator = None
    if use_llm:
        print("Initializing LLM generator...")
        llm_generator = LLMGenerator(api_key, state_space)
        if llm_generator.is_available():
            print("LLM generator ready - using Gemini Pro for realistic scenarios")
        else:
            print("LLM generator not available - using state space-based generation")
    else:
        print("Using state space-based generation (no external API required)")
    
    print(f"Generating {num_scenarios} scenarios...")
    generator = ScenarioGenerator(state_space, llm_generator)
    
    output_path = Path(output_file)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    
    with open(output_path, 'w') as f:
        for i in range(num_scenarios):
            scenario = generator.generate_scenario()
            
            # Convert to fine-tuning format
            example = FineTuningExample.from_scenario(
                scenario.model_dump(),
                DEFAULT_SYSTEM_PROMPT
            )
            
            # Write JSONL line
            f.write(example.to_jsonl() + '\n')
            
            if (i + 1) % 1000 == 0:
                print(f"Generated {i + 1}/{num_scenarios} scenarios...")
    
    print(f"Dataset generation complete! Output: {output_file}")
    print(f"Total scenarios: {num_scenarios}")
    if use_llm and llm_generator.is_available():
        print("Generated using LLM (Gemini Pro)")
    else:
        print("Generated using state space-based rules (assets, errors, logistics, compliance data)")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Generate synthetic correlation AI training data")
    parser.add_argument("num_scenarios", type=int, nargs="?", default=10000, help="Number of scenarios to generate")
    parser.add_argument("output_file", type=str, nargs="?", default="dataset/training_data.jsonl", help="Output JSONL file path")
    parser.add_argument("--use-llm", action="store_true", help="Use LLM (Gemini Pro) for realistic scenario generation")
    parser.add_argument("--api-key", type=str, help="Google API key for Gemini (or set GOOGLE_API_KEY env var)")
    
    args = parser.parse_args()
    
    generate_dataset(
        num_scenarios=args.num_scenarios,
        output_file=args.output_file,
        use_llm=args.use_llm,
        api_key=args.api_key
    )
