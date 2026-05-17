"""
Fine-Tuning Dataset Schema for Gemma 4

Defines the JSONL conversation format for instruction-tuned models.
"""

from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
import json


class FineTuningMessage(BaseModel):
    role: str = Field(..., description="Message role: system, user, or model")
    content: str = Field(..., description="Message content")


class FineTuningExample(BaseModel):
    messages: List[FineTuningMessage]
    
    def to_jsonl(self) -> str:
        """Convert to JSONL string format"""
        return json.dumps({"messages": [m.model_dump() for m in self.messages]})
    
    @classmethod
    def from_scenario(
        cls,
        scenario_data: Dict[str, Any],
        system_prompt: str
    ) -> "FineTuningExample":
        """Create fine-tuning example from CorrelationScenario"""
        user_content = "DATA INGEST:\n"
        for metric in scenario_data.get("ingested_metrics", []):
            user_content += f"{metric['endpoint']}: {metric['payload_snapshot']}\n"
        
        model_content = f"**Correlation Analysis:** {scenario_data.get('predicted_root_cause', '')}\n\n"
        model_content += f"**Risk Score:** {scenario_data.get('risk_score', 0)}/100\n\n"
        
        if scenario_data.get("target_kanban_tasks"):
            model_content += "**Recommended Kanban Tasks:**\n"
            for task in scenario_data["target_kanban_tasks"]:
                model_content += f"- {task}\n"
        
        if scenario_data.get("remediation_commands"):
            model_content += "\n**Recommended Actions:**\n"
            for cmd in scenario_data["remediation_commands"]:
                model_content += f"- {cmd}\n"
        
        return cls(
            messages=[
                FineTuningMessage(role="system", content=system_prompt),
                FineTuningMessage(role="user", content=user_content),
                FineTuningMessage(role="model", content=model_content)
            ]
        )


# System prompt template
DEFAULT_SYSTEM_PROMPT = """You are the OmniusGrid Correlation Engine. Analyze the system states and output a root-cause correlation and recommended actions.

Your role is to:
1. Identify cross-domain relationships between edge telemetry, production, logistics, and compliance
2. Determine the root cause of operational issues
3. Calculate risk scores (0-100) based on severity and impact
4. Recommend specific Kanban tasks and API commands for remediation
5. Identify compliance implications (ISO, OSHA, DOT, CTPAT, etc.)

Always provide:
- Clear correlation analysis explaining the causal chain
- Quantified risk score
- Specific, actionable recommendations with API endpoints
- Compliance standards affected (if any)"""
