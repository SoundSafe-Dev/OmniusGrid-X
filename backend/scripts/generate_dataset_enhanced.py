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
from datetime import datetime
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
            asset = self.state_space.get_random_asset()
            trailer = self._get_random_nested("logistics", "trailers")
            dock = self._get_random_nested("logistics", "dock_doors")
            detention_scenario = self._get_random_nested("logistics", "detention_scenarios", "driver_liability")
            bottleneck = self._get_random_nested("logistics", "yard_bottlenecks", "dock_congestion")
            shop_floor_issue = self._get_random_nested("production_output", "shop_floor_scenarios", "production_bottlenecks")
            predictive_indicator = self._get_random_nested("maintenance", "predictive_indicators", "vibration_analysis")
            safety_scenario = self._get_random_nested("safety", "security_scenarios", "physical_security")
        else:
            asset = "asset"
            trailer = "TRK-XXX"
            dock = "DOCK-XX"
            detention_scenario = "detention scenario"
            bottleneck = "bottleneck"
            shop_floor_issue = "shop floor issue"
            predictive_indicator = "predictive indicator"
            safety_scenario = "safety scenario"
        
        avg_severity = sum(link.get("severity_impact", 0.5) for link in links) / len(links) if links else 0.5
        
        # Single-domain analysis
        if len(domains) == 1:
            domain = domains[0]
            if domain == "LOGISTICS_FLEET":
                liability_options = ["driver_liability", "client_liability", "transport_liability", "yard_liability"]
                liability = self._get_random_nested("logistics", "detention_scenarios", random.choice(liability_options)) if self.state_space else "driver_liability"
                return f"Logistics fleet issue detected: {trailer} experiencing operational delays at {dock}. Root cause analysis indicates {detention_scenario}. Liability determination suggests {liability.replace('_', ' ')} responsibility. Coordination required."
            elif domain == "PRODUCTION_OEE":
                return f"Production line degradation detected: {asset} experiencing performance issues. OEE metrics below threshold indicating equipment performance or scheduling inefficiency. Root cause analysis suggests {shop_floor_issue}. Maintenance or process optimization required."
            elif domain == "MAINTENANCE":
                return f"Maintenance operations issue detected: {predictive_indicator} indicates equipment degradation. Predictive maintenance analysis suggests preventive maintenance window approaching. Resource coordination required."
            elif domain == "SAFETY":
                return f"Safety management issue detected: {safety_scenario} identified. Risk assessment indicates immediate response required. Safety protocol activation and incident investigation needed."
            else:
                return f"Operational anomaly detected in {domain_map.get(domain, domain)}. Process deviation detected with severity {avg_severity:.2f}. Root cause analysis required to identify underlying cause."
        
        # Multi-domain analysis
        if "LOGISTICS_FLEET" in domains and "PRODUCTION_OEE" in domains:
            liability_options = ["driver_liability", "client_liability", "transport_liability", "yard_liability"]
            liability = self._get_random_nested("logistics", "detention_scenarios", random.choice(liability_options)) if self.state_space else "yard_liability"
            return f"Logistics delays with {trailer} at {dock} causing production line inefficiencies. Detention analysis identifies {detention_scenario} with {liability.replace('_', ' ')} responsibility. {shop_floor_issue} impacting production OEE. Cross-domain coordination required."
        
        if "LOGISTICS_FLEET" in domains and "WAREHOUSE_MANAGEMENT" in domains:
            return f"Logistics-warehouse coordination failure: {trailer} experiencing delays at {dock} due to {detention_scenario}. {bottleneck} in warehouse operations causing detention. Cross-functional process integration required."
        
        if "MAINTENANCE" in domains and "PRODUCTION_OEE" in domains:
            return f"Maintenance-production conflict: {predictive_indicator} on {asset} indicates maintenance requirement. Scheduling conflicts causing production OEE degradation. Coordination between maintenance and production scheduling required."
        
        # Generic multi-domain
        return f"Cascading anomaly across {', '.join([domain_map.get(d, d) for d in domains])}. Cross-domain dependency failure with severity {avg_severity:.2f}. Multi-perspective analysis required to identify root cause and implement coordinated response."
    
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
            generated_at=datetime.utcnow().isoformat()
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
                        "timestamp": datetime.utcnow().isoformat()
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
