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
from datetime import datetime

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


class LLMGenerator:
    """Generates realistic AI analysis using Google Gemini API"""
    
    def __init__(self, api_key: Optional[str] = None):
        self.api_key = api_key or os.getenv("GOOGLE_API_KEY")
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
        """
        Generate realistic ground truth using LLM
        
        Args:
            domains: List of active domain names
            metrics: List of operational metrics
            links: List of domain links
            
        Returns:
            Dictionary with predicted_root_cause, risk_score, kanban_tasks, etc.
        """
        if not self.is_available():
            return self._generate_mock_ground_truth(domains, links)
        
        # Construct prompt for LLM
        prompt = self._construct_prompt(domains, metrics, links)
        
        try:
            response = self.model.generate_content(prompt)
            return self._parse_llm_response(response.text, domains)
        except Exception as e:
            print(f"LLM generation failed: {e}, falling back to mock")
            return self._generate_mock_ground_truth(domains, links)
    
    def _construct_prompt(
        self,
        domains: List[str],
        metrics: List[Dict[str, Any]],
        links: List[Dict[str, Any]]
    ) -> str:
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
            # Extract JSON from response
            import re
            json_match = re.search(r'\{.*\}', response_text, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                return json.loads(json_str)
            else:
                raise ValueError("No JSON found in response")
        except Exception as e:
            print(f"Failed to parse LLM response: {e}")
            return self._generate_mock_ground_truth(domains, [])
    
    def _generate_mock_ground_truth(self, domains: List[str], links: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Generate mock ground truth when LLM is unavailable"""
        domain_names = [d.value if hasattr(d, 'value') else str(d) for d in domains]
        
        root_causes = [
            f"Cascading failure from {domain_names[0]} affecting {domain_names[1] if len(domain_names) > 1 else 'system'}",
            f"Synchronized anomaly detected across {', '.join(domain_names)}",
            f"Cross-domain dependency failure in {domain_names[0]} triggering {domain_names[1] if len(domain_names) > 1 else 'system-wide'} issues",
            f"Operational misalignment between {domain_names[0]} and {domain_names[1] if len(domain_names) > 1 else 'infrastructure'}"
        ]
        
        task_types = ["maintenance_pm", "maintenance_cm", "quality_inspection", "safety_check", "alarm_response"]
        priorities = ["low", "medium", "high", "critical"]
        
        kanban_tasks = [
            {
                "title": f"Investigate {domain_names[0]} anomaly",
                "priority": random.choice(priorities),
                "task_type": random.choice(task_types)
            }
        ]
        
        if len(domains) > 1:
            kanban_tasks.append({
                "title": f"Coordinate response with {domain_names[1]} team",
                "priority": random.choice(priorities),
                "task_type": "custom"
            })
        
        commands = []
        for domain in domain_names:
            if "EDGE" in domain:
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/commands/asset/{asset_id}/emergency-stop",
                    "description": "Execute emergency stop on affected asset"
                })
            elif "PROD" in domain:
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/kanban/boards/1/tasks",
                    "description": "Create maintenance task for production line"
                })
            elif "LOG" in domain:
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/yard/dock/appointments",
                    "description": "Reschedule dock appointment to prevent detention"
                })
            elif "COMP" in domain:
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/registries/{id}/items",
                    "description": "Log compliance near-miss incident"
                })
        
        compliance_items = []
        if any("COMP" in str(d) for d in domain_names):
            compliance_items.append("ISO 22000 Food Safety")
        if any("LOG" in str(d) for d in domain_names):
            compliance_items.append("DOT HOS compliance")
        
        return {
            "predicted_root_cause": random.choice(root_causes),
            "risk_score": round(random.uniform(40, 95), 1),
            "target_kanban_tasks": kanban_tasks,
            "remediation_commands": commands[:2],
            "compliance_implications": compliance_items if compliance_items else None
        }


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
    
    def get_random(self, category: str, key: str) -> Any:
        """Get random item from state space"""
        if category not in self.data:
            return None
        if key not in self.data[category]:
            return None
        return random.choice(self.data[category][key])
    
    def get_random_asset(self) -> str:
        """Get random asset from any category"""
        assets = []
        for category in self.data.values():
            for key, items in category.items():
                assets.extend(items)
        return random.choice(assets)


class ScenarioGenerator:
    """Generates synthetic correlation scenarios"""
    
    def __init__(self, state_space: StateSpaceLoader, llm_generator: Optional[LLMGenerator] = None):
        self.state_space = state_space
        self.llm_generator = llm_generator
        self.scenario_count = 0
    
    def generate_scenario(self) -> CorrelationScenario:
        """Generate a single random correlation scenario"""
        self.scenario_count += 1
        scenario_id = f"SCENARIO_{self.scenario_count:05d}"
        
        # Randomly select 2-3 domains
        num_domains = random.choice([2, 3])
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
        
        return metrics
    
    def _generate_ground_truth(self, domains: List[DomainType], links: List[CrossDomainLink], metrics: List[OperationalMetric]) -> Dict[str, Any]:
        """Generate simulated AI analysis for training"""
        domain_names = [d.value for d in domains]
        
        # Use LLM if available
        if self.llm_generator and self.llm_generator.is_available():
            metrics_dict = [m.model_dump() for m in metrics]
            links_dict = [l.model_dump() for l in links]
            return self.llm_generator.generate_ground_truth(domain_names, metrics_dict, links_dict)
        
        # Fallback to mock generation
        # Generate root cause analysis
        root_causes = [
            f"Cascading failure from {domain_names[0]} affecting {domain_names[1] if len(domain_names) > 1 else 'system'}",
            f"Synchronized anomaly detected across {', '.join(domain_names)}",
            f"Cross-domain dependency failure in {domain_names[0]} triggering {domain_names[1] if len(domain_names) > 1 else 'system-wide'} issues",
            f"Operational misalignment between {domain_names[0]} and {domain_names[1] if len(domain_names) > 1 else 'infrastructure'}"
        ]
        
        # Generate kanban tasks
        task_types = ["maintenance_pm", "maintenance_cm", "quality_inspection", "safety_check", "alarm_response"]
        priorities = ["low", "medium", "high", "critical"]
        
        kanban_tasks = [
            {
                "title": f"Investigate {domain_names[0]} anomaly",
                "priority": random.choice(priorities),
                "task_type": random.choice(task_types)
            }
        ]
        
        if len(domains) > 1:
            kanban_tasks.append({
                "title": f"Coordinate response with {domain_names[1]} team",
                "priority": random.choice(priorities),
                "task_type": "custom"
            })
        
        # Generate remediation commands
        commands = []
        for domain in domains:
            if domain == DomainType.EDGE:
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/commands/asset/{asset_id}/emergency-stop",
                    "description": "Execute emergency stop on affected asset"
                })
            elif domain == DomainType.PROD:
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/kanban/boards/1/tasks",
                    "description": "Create maintenance task for production line"
                })
            elif domain == DomainType.LOG:
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/yard/dock/appointments",
                    "description": "Reschedule dock appointment to prevent detention"
                })
            elif domain == DomainType.COMP:
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/registries/{id}/items",
                    "description": "Log compliance near-miss incident"
                })
        
        # Generate compliance implications
        compliance_items = []
        if DomainType.COMP in domains:
            compliance_items.append(self.state_space.get_random("compliance", "iso_standards"))
        if DomainType.LOG in domains:
            compliance_items.append(random.choice(["DOT HOS compliance", "CTPAT security", "FSMA transportation"]))
        
        return {
            "predicted_root_cause": random.choice(root_causes),
            "risk_score": round(random.uniform(40, 95), 1),
            "target_kanban_tasks": kanban_tasks,
            "remediation_commands": commands[:2],  # Limit to 2 commands
            "compliance_implications": compliance_items if compliance_items else None
        }


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
        llm_generator = LLMGenerator(api_key)
        if llm_generator.is_available():
            print("LLM generator ready - using Gemini Pro for realistic scenarios")
        else:
            print("LLM generator not available - falling back to mock generation")
    
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
        print("Generated using mock data")


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
