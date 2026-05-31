"""
Correlation AI Engine Service

Integrates the Domain Interaction Component with AI inference capabilities.
This service handles both training-time scenario generation and runtime inference.
"""

from typing import List, Dict, Any, Optional
from uuid import UUID
from datetime import datetime
import asyncio
import ast
import json
import re
import structlog
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.models.domain_interaction import (
    DomainType,
    CorrelationScenario,
    CrossDomainLink,
    OperationalMetric
)
from app.models.finetuning_schema import DEFAULT_SYSTEM_PROMPT

logger = structlog.get_logger()


class CorrelationAIEngine:
    """
    Main correlation AI engine service.
    
    Responsibilities:
    - Analyze correlation scenarios using AI inference
    - Generate synthetic scenarios for training data
    - Validate scenarios against Pydantic schemas
    - Execute AI-recommended commands
    """
    
    def __init__(self):
        self._model_loaded = False
        self._model_version = "gemma-4-placeholder"
        self._tokenizer = None
        self._model = None
    
    async def analyze_scenario(
        self,
        scenario: CorrelationScenario,
        db: AsyncSession,
        organization_id: Optional[UUID] = None,
        user_id: Optional[UUID] = None,
        auto_integrate: bool = True,
        context: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Run AI correlation analysis on a scenario.
        
        Args:
            scenario: The correlation scenario to analyze
            db: Database session for context
            organization_id: Organization ID for integration (optional)
            user_id: User ID for integration (optional)
            auto_integrate: Whether to automatically integrate with registries and kanban
            
        Returns:
            AI analysis with root cause, risk score, and recommendations
        """
        logger.info(
            "analyzing_correlation_scenario",
            scenario_id=scenario.scenario_id,
            active_domains=[d.value for d in scenario.active_domains],
            auto_integrate=auto_integrate
        )
        # Extract domain names for analysis
        domain_names = [d.value for d in scenario.active_domains]

        analysis = None
        if settings.CORRELATION_MODEL_ENABLED:
            try:
                analysis = await self._analyze_with_gemma(scenario, domain_names, context or {})
            except Exception as e:
                logger.error("gemma_correlation_inference_failed", error=str(e))

        if analysis is None:
            analysis = self._simulate_analysis(scenario, domain_names)
        
        logger.info(
            "correlation_analysis_complete",
            scenario_id=scenario.scenario_id,
            risk_score=analysis["risk_score"]
        )
        
        # Auto-integrate with registries and kanban if requested
        if auto_integrate and organization_id and user_id:
            try:
                from app.services.correlation_registry_integration import correlation_registry_integration
                
                integration_input = {
                    "correlation_analysis": analysis["predicted_root_cause"],
                    "risk_score": analysis["risk_score"],
                    "recommended_kanban_tasks": analysis["target_kanban_tasks"],
                    "recommended_actions": analysis["remediation_commands"],
                    "compliance_implications": analysis["compliance_implications"]
                }
                
                integration_result = await correlation_registry_integration.process_correlation_analysis(
                    integration_input,
                    organization_id,
                    db,
                    user_id
                )
                
                analysis["integration_result"] = integration_result
                logger.info("auto_integration_complete", integration_result=integration_result)
                
            except Exception as e:
                logger.error("auto_integration_failed", error=str(e))
                analysis["integration_error"] = str(e)
        
        return analysis

    async def chat(
        self,
        message: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Answer session chat naturally, using uploaded context when it helps."""
        context = context or {}

        if settings.CORRELATION_MODEL_ENABLED:
            try:
                await self._ensure_model_loaded()
                prompt = self._build_chat_prompt(message, context)
                generated_text = await asyncio.to_thread(
                    self._generate_text_with_system,
                    self._chat_system_prompt(),
                    prompt,
                )
                content = self._clean_chat_text(generated_text)
                if content:
                    return {
                        "response_text": content,
                        "predicted_root_cause": content,
                        "risk_score": None,
                        "target_kanban_tasks": [],
                        "remediation_commands": [],
                        "compliance_implications": None,
                        "model_version": f"{settings.CORRELATION_BASE_MODEL}+{settings.CORRELATION_ADAPTER_PATH}",
                        "confidence": 0.85,
                        "response_type": "conversational",
                    }
            except Exception as e:
                logger.exception("gemma_chat_inference_failed", error=str(e))

        content = self._fallback_chat_response(message, context)
        return {
            "response_text": content,
            "predicted_root_cause": content,
            "risk_score": None,
            "target_kanban_tasks": [],
            "remediation_commands": [],
            "compliance_implications": None,
            "model_version": "fallback-chat",
            "confidence": 0.4,
            "response_type": "conversational_fallback",
        }

    def _simulate_analysis(
        self,
        scenario: CorrelationScenario,
        domain_names: List[str]
    ) -> Dict[str, Any]:
        """Fallback analysis used when the Gemma adapter is unavailable."""
        return {
            "scenario_id": scenario.scenario_id,
            "analysis_timestamp": datetime.utcnow().isoformat(),
            "predicted_root_cause": self._simulate_root_cause(domain_names, scenario.domain_links),
            "risk_score": self._calculate_risk_score(scenario.domain_links),
            "target_kanban_tasks": self._generate_kanban_tasks(domain_names),
            "remediation_commands": self._generate_commands(domain_names),
            "compliance_implications": self._identify_compliance(domain_names),
            "model_version": self._model_version,
            "confidence": 0.85,
            "response_text": self._format_business_response(
                self._simulate_root_cause(domain_names, scenario.domain_links),
                self._calculate_risk_score(scenario.domain_links),
                self._generate_kanban_tasks(domain_names),
                self._generate_commands(domain_names),
            ),
            "follow_up_questions": self._generate_follow_ups(domain_names),
        }

    async def _analyze_with_gemma(
        self,
        scenario: CorrelationScenario,
        domain_names: List[str],
        context: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Run the configured Gemma base model + LoRA adapter and parse output."""
        await self._ensure_model_loaded()
        prompt = self._build_prompt(scenario, domain_names, context)
        generated_text = await asyncio.to_thread(self._generate_text, prompt)
        parsed = self._parse_model_output(generated_text)
        parsed.update({
            "scenario_id": scenario.scenario_id,
            "analysis_timestamp": datetime.utcnow().isoformat(),
            "model_version": f"{settings.CORRELATION_BASE_MODEL}+{settings.CORRELATION_ADAPTER_PATH}",
            "confidence": 0.85,
            "response_text": generated_text.strip(),
            "follow_up_questions": self._generate_follow_ups(domain_names),
        })
        return parsed

    async def _ensure_model_loaded(self) -> None:
        if self._model_loaded:
            return

        def load_model():
            import torch
            from peft import PeftModel
            from transformers import AutoModelForCausalLM, AutoTokenizer

            tokenizer = AutoTokenizer.from_pretrained(settings.CORRELATION_BASE_MODEL)
            base_model = AutoModelForCausalLM.from_pretrained(
                settings.CORRELATION_BASE_MODEL,
                torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
            )
            model = PeftModel.from_pretrained(base_model, settings.CORRELATION_ADAPTER_PATH)
            model.eval()
            return tokenizer, model

        self._tokenizer, self._model = await asyncio.to_thread(load_model)
        self._model_loaded = True
        self._model_version = f"{settings.CORRELATION_BASE_MODEL}+lora"
        logger.info("gemma_correlation_model_loaded", adapter=settings.CORRELATION_ADAPTER_PATH)

    def _generate_text(self, prompt: str) -> str:
        return self._generate_text_with_system(self._system_prompt(), prompt)

    def _encode_chat_messages(self, messages: List[Dict[str, str]]):
        import torch

        if hasattr(self._tokenizer, "apply_chat_template"):
            encoded = self._tokenizer.apply_chat_template(
                messages,
                add_generation_prompt=True,
                return_tensors="pt",
                tokenize=True,
            )
        else:
            text = "\n".join(f"{m['role']}: {m['content']}" for m in messages)
            encoded = self._tokenizer(text, return_tensors="pt")

        if isinstance(encoded, torch.Tensor):
            if encoded.ndim == 1:
                encoded = encoded.unsqueeze(0)
            return {"input_ids": encoded}
        if hasattr(encoded, "input_ids"):
            return {
                "input_ids": encoded["input_ids"],
                "attention_mask": encoded.get("attention_mask"),
            }
        return {"input_ids": encoded["input_ids"], "attention_mask": encoded.get("attention_mask")}

    def _generate_text_with_system(self, system_prompt: str, prompt: str) -> str:
        import torch

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt},
        ]
        model_inputs = self._encode_chat_messages(messages)
        input_ids = model_inputs["input_ids"].to(self._model.device)
        attention_mask = model_inputs.get("attention_mask")
        if attention_mask is not None:
            attention_mask = attention_mask.to(self._model.device)

        pad_token_id = self._tokenizer.eos_token_id
        if pad_token_id is None and getattr(self._tokenizer, "pad_token", None) is not None:
            pad_token_id = self._tokenizer.pad_token_id

        generate_kwargs = {
            "input_ids": input_ids,
            "max_new_tokens": settings.CORRELATION_MAX_NEW_TOKENS,
            "pad_token_id": pad_token_id,
        }
        if attention_mask is not None:
            generate_kwargs["attention_mask"] = attention_mask
        if settings.CORRELATION_TEMPERATURE > 0:
            generate_kwargs["temperature"] = settings.CORRELATION_TEMPERATURE
            generate_kwargs["do_sample"] = True
        else:
            generate_kwargs["do_sample"] = False

        with torch.no_grad():
            output_ids = self._model.generate(**generate_kwargs)

        prompt_len = input_ids.shape[-1]
        generated_ids = output_ids[0, prompt_len:]
        return self._tokenizer.decode(generated_ids, skip_special_tokens=True)

    def _chat_system_prompt(self) -> str:
        return (
            "You are Omnius Correlation AI, a helpful, natural conversational assistant for operations teams. "
            "Speak plainly like a senior operations analyst: specific, slightly descriptive, and practical. "
            "Do not force every answer into a risk score or task list. "
            "Do not use raw JSON, Python dictionaries, markdown bold markers, or model jargon. "
            "If the user is just chatting, answer normally. If they ask about uploaded data, use the data context "
            "carefully and mention when the data looks synthetic, thin, or insufficient. Use the computed spreadsheet "
            "profile as source-of-truth for totals, trends, groups, and worst rows. Never invent percentages, cycle "
            "times, defect rates, or improvement claims that are not present in the provided profile. If the profile "
            "does not support a metric, say what is missing and use the closest available columns instead. "
            "When useful, cite actual column names, row values, facilities, lines, assets, or delay reasons from the data."
        )

    def _build_chat_prompt(self, message: str, context: Dict[str, Any]) -> str:
        lines = []

        data_sources = context.get("data_sources", [])[:5]
        if data_sources:
            lines.append("Uploaded data context:")
            for source in data_sources:
                processed = source.get("processed_data") or {}
                file_name = source.get("file_name") or "uploaded file"
                if processed.get("type") == "spreadsheet":
                    profile = processed.get("full_sheet_profile") or {}
                    findings = processed.get("distilled_findings") or []
                    profile_text = json.dumps(profile, default=str)[:12000]
                    lines.append(
                        f"- {file_name}: rows={processed.get('rows')}, "
                        f"columns={processed.get('column_names')}"
                    )
                    if findings:
                        lines.append("  Must-use spreadsheet findings:")
                        for finding in findings[:18]:
                            lines.append(f"  - {finding}")
                    if profile:
                        lines.append("  Whole-sheet computed profile:")
                        lines.append(f"  {profile_text}")
                    else:
                        lines.append(
                            f"  Sample rows only: first={processed.get('sample_data', [])[:5]}, "
                            f"last={processed.get('tail_sample_data', [])[:5]}"
                        )
                else:
                    lines.append(f"- {file_name}: {processed}")
            lines.append("")

            lines.append(
                "Spreadsheet answer rules: base conclusions on the whole-sheet computed profile above. "
                "Prefer concrete facts over generic advice. Do not claim a trend, percentage, cycle time, or defect rate "
                "unless it appears in the profile. If the user asks for a leadership summary, write a concise analyst-style "
                "paragraph followed by practical next actions only when helpful. If the user asks to dive deeper, do not "
                "repeat the prior summary; expand the next actions into concrete owners/checks tied to exact rows, groups, "
                "assets, delay reasons, maintenance statuses, downtime, defects, vibration, or estimated loss."
            )
            lines.append("")

        history = context.get("conversation_history", [])[-6:]
        if history:
            has_spreadsheet_context = any(
                (source.get("processed_data") or {}).get("type") == "spreadsheet"
                for source in data_sources
            )
            lines.append("Recent conversation:")
            for item in history:
                role = item.get("role", "user")
                if has_spreadsheet_context and role == "assistant":
                    continue
                content = str(item.get("content", ""))[:800]
                lines.append(f"{role}: {content}")
            lines.append("")

        lines.append(f"User: {message}")
        lines.append("Assistant:")
        return "\n".join(lines)

    def _clean_chat_text(self, text: str) -> str:
        cleaned = text.strip()
        cleaned = re.sub(r"\*\*(.*?)\*\*", r"\1", cleaned)
        cleaned = re.sub(r"^Assistant:\s*", "", cleaned, flags=re.I)
        return cleaned.strip()

    def _fallback_spreadsheet_summary(self, context: Dict[str, Any]) -> Optional[str]:
        data_sources = context.get("data_sources", [])
        spreadsheets = [
            source for source in data_sources
            if (source.get("processed_data") or {}).get("type") == "spreadsheet"
        ]
        if not spreadsheets:
            return None

        source = spreadsheets[0]
        processed = source.get("processed_data") or {}
        file_name = source.get("file_name") or "the uploaded spreadsheet"
        rows = processed.get("rows", 0)
        columns = processed.get("column_names") or []
        sample_rows = processed.get("sample_data") or []

        column_text = ", ".join(map(str, columns[:12]))
        if len(columns) > 12:
            column_text += f", and {len(columns) - 12} more"

        risk_clues = []
        lower_columns = {str(column).lower(): column for column in columns}
        for keyword, label in [
            ("downtime", "downtime or lost time"),
            ("defect", "quality defects"),
            ("delay", "delays"),
            ("maintenance", "maintenance status"),
            ("priority", "priority or severity"),
            ("cost", "cost impact"),
            ("temperature", "temperature drift"),
            ("vibration", "equipment vibration"),
        ]:
            if any(keyword in name for name in lower_columns):
                risk_clues.append(label)

        notable_rows = []
        for row in sample_rows[:5]:
            if not isinstance(row, dict):
                continue
            pieces = []
            for key in ["date", "shift", "production_line", "asset_id", "downtime_minutes", "defect_count", "delay_reason", "priority"]:
                if key in row:
                    pieces.append(f"{key.replace('_', ' ')}={row[key]}")
            if pieces:
                notable_rows.append("; ".join(pieces))

        risk_sentence = (
            "The columns suggest useful risk signals around " + ", ".join(risk_clues) + "."
            if risk_clues else
            "The file uploaded successfully, but the column names do not clearly identify operational risk signals."
        )

        sample_sentence = (
            "A few sample rows include: " + " | ".join(notable_rows[:3]) + "."
            if notable_rows else
            "I can see the file structure, but the sample rows are too generic to infer much by themselves."
        )

        return (
            f"I can summarize {file_name}. It has {rows} rows and {len(columns)} columns. "
            f"The main columns I see are: {column_text}.\n\n"
            f"{risk_sentence} {sample_sentence}\n\n"
            "Top things I would check next:\n"
            "- Which line, asset, or shift has the highest downtime or defect concentration.\n"
            "- Whether high-priority rows cluster around one delay reason or maintenance status.\n"
            "- Whether cost impact is being driven more by downtime, defects, or throughput loss.\n\n"
            "Recommended next action: ask me to rank the worst lines/assets, or upload a file with real operational history so I can separate signal from demo data."
        )

    def _fallback_chat_response(self, message: str, context: Dict[str, Any]) -> str:
        normalized = message.strip().lower()
        data_sources = context.get("data_sources", [])

        if normalized in {"hi", "hello", "hey", "yo", "sup"}:
            if data_sources:
                return (
                    "Hey. I see you have a file attached in this session. I can help summarize it, explain the columns, "
                    "or sanity-check whether there is enough real operational signal to analyze."
                )
            return "Hey. I can chat normally, and I can also help analyze operational data when you upload a file."

        if "what" in normalized and "help" in normalized:
            return (
                "I can help you talk through operational questions, inspect uploaded Excel or CSV files, summarize what the "
                "data contains, call out weak or fake-looking data, and suggest practical next steps. I should not force "
                "everything into a risk score unless you are actually asking for analysis."
            )

        if data_sources:
            spreadsheet_summary = self._fallback_spreadsheet_summary(context)
            if spreadsheet_summary:
                return spreadsheet_summary
            return "I can see an uploaded file in this session, but I could not extract enough structured spreadsheet context from it to summarize it well."

        return "I can help with that. Tell me what you want to look at, or upload a spreadsheet if you want data-specific analysis."

    def _system_prompt(self) -> str:
        return (
            f"{DEFAULT_SYSTEM_PROMPT}\n\n"
            "Write like a helpful operations analyst, not a JSON API. Be conversational and practical. "
            "Do not use markdown bold markers, raw Python dictionaries, raw JSON, equations, or model jargon. "
            "If the uploaded data looks synthetic or too thin, say so plainly and explain what can still be inferred.\n\n"
            "Use this plain-text structure:\n\n"
            "Correlation analysis: <plain-English answer with likely cause, impact, and confidence>\n\n"
            "Risk score: <number>/100\n\n"
            "Recommended tasks:\n"
            "- <short task title and priority in words>\n\n"
            "Recommended actions:\n"
            "- <specific next action in plain English>"
        )

    def _build_prompt(
        self,
        scenario: CorrelationScenario,
        domain_names: List[str],
        context: Dict[str, Any]
    ) -> str:
        lines = ["DATA INGEST:"]
        for metric in scenario.ingested_metrics:
            lines.append(f"{metric.endpoint}: {metric.payload_snapshot}")

        data_sources = context.get("data_sources", [])[:5]
        for source in data_sources:
            processed = source.get("processed_data") or {}
            file_name = source.get("file_name") or "uploaded file"
            if processed.get("type") == "spreadsheet":
                lines.append(
                    f"/api/v1/uploads/{file_name}: "
                    f"rows={processed.get('rows')}, columns={processed.get('column_names')}, "
                    f"sample_data={processed.get('sample_data', [])[:5]}, "
                    f"summary={processed.get('summary', {})}"
                )
            else:
                lines.append(f"/api/v1/uploads/{file_name}: {processed}")

        user_question = context.get("user_question")
        if user_question:
            lines.append("")
            lines.append(f"BUSINESS QUESTION: {user_question}")

        if domain_names:
            lines.append(f"DETECTED DOMAINS: {', '.join(domain_names)}")

        lines.append("")
        lines.append("Answer the business question using the uploaded data context when available.")
        return "\n".join(lines)

    def _parse_model_output(self, text: str) -> Dict[str, Any]:
        risk_score = self._extract_risk_score(text)
        tasks = self._extract_list_section(text, "Recommended Kanban Tasks")
        actions = self._extract_list_section(text, "Recommended Actions")
        return {
            "predicted_root_cause": self._extract_section(text, "Correlation Analysis") or text.strip(),
            "risk_score": risk_score if risk_score is not None else 50.0,
            "target_kanban_tasks": tasks,
            "remediation_commands": actions,
            "compliance_implications": None,
        }

    def _extract_section(self, text: str, heading: str) -> Optional[str]:
        pattern = rf"(?:\*\*)?{re.escape(heading)}:(?:\*\*)?\s*(.*?)(?=\n\s*(?:\*\*)?[^:\n]+:(?:\*\*)?|\Z)"
        match = re.search(pattern, text, flags=re.S)
        return match.group(1).strip() if match else None

    def _extract_risk_score(self, text: str) -> Optional[float]:
        patterns = [
            r"\*\*Risk Score:\*\*\s*([0-9]+(?:\.[0-9]+)?)\s*/\s*100",
            r"Risk Score[:\s*]+([0-9]+(?:\.[0-9]+)?)\s*/\s*100",
            r"risk_score[\"']?\s*[:=]\s*([0-9]+(?:\.[0-9]+)?)",
        ]
        for pattern in patterns:
            match = re.search(pattern, text, flags=re.I)
            if match:
                return float(match.group(1))
        return None

    def _extract_list_section(self, text: str, heading: str) -> List[Dict[str, Any]]:
        section = self._extract_section(text, heading)
        if not section:
            return []

        items = []
        for line in section.splitlines():
            stripped = line.strip()
            if not stripped.startswith("-"):
                continue
            value = stripped.lstrip("-").strip()
            try:
                parsed = ast.literal_eval(value)
                if isinstance(parsed, dict):
                    items.append(parsed)
                    continue
            except Exception:
                pass
            items.append({"description": value})
        return items

    def _format_business_response(
        self,
        analysis: str,
        risk_score: float,
        tasks: List[Dict[str, Any]],
        actions: List[Dict[str, Any]]
    ) -> str:
        def describe_task(task: Dict[str, Any]) -> str:
            title = task.get("title") or task.get("description") or "Review the uploaded data"
            priority = task.get("priority")
            return f"{title} ({priority} priority)" if priority else title

        def describe_action(action: Dict[str, Any]) -> str:
            return action.get("description") or action.get("command") or "Review current metrics and supporting data"

        task_lines = "\n".join([f"- {describe_task(task)}" for task in tasks]) or "- Review process metrics and uploaded data"
        action_lines = "\n".join([f"- {describe_action(action)}" for action in actions]) or "- Review the uploaded file and identify which columns represent time, asset, status, and outcome."
        return (
            f"Correlation analysis: {analysis}\n\n"
            f"Risk score: {risk_score}/100\n\n"
            f"Recommended tasks:\n{task_lines}\n\n"
            f"Recommended actions:\n{action_lines}"
        )

    def _generate_follow_ups(self, domains: List[str]) -> List[str]:
        if "PRODUCTION_OEE" in domains:
            return [
                "Show bottleneck risk by production line",
                "Suggest mitigation steps",
                "Estimate impact over the next shift",
            ]
        return [
            "Break this down further",
            "Show impact over the last 2 months",
            "Suggest mitigation steps",
        ]
    
    def _simulate_root_cause(
        self,
        domains: List[str],
        links: List[CrossDomainLink]
    ) -> str:
        """Simulate root cause analysis"""
        if not domains:
            return (
                "Uploaded data is available for analysis, but the question does not specify an operational domain. "
                "Ask about delays, utilization, risk, maintenance, compliance, inventory, or another business outcome "
                "to get a targeted correlation analysis."
            )

        if len(domains) == 1:
            return f"Anomaly detected in {domains[0]} domain requiring investigation"
        
        # Generate causal chain explanation
        causal_chain = " → ".join([d.replace("_", " ") for d in domains])
        return f"Cascading failure detected across domains: {causal_chain}. Primary trigger in {domains[0]} propagating to {domains[-1]}."
    
    def _calculate_risk_score(self, links: List[CrossDomainLink]) -> float:
        """Calculate overall risk score from domain links"""
        if not links:
            return 50.0
        
        # Average severity impact converted to 0-100 scale
        avg_severity = sum(link.severity_impact for link in links) / len(links)
        return round(avg_severity * 100, 1)
    
    def _generate_kanban_tasks(self, domains: List[str]) -> List[Dict[str, Any]]:
        """Generate recommended Kanban tasks"""
        tasks = []
        
        task_types = {
            "EDGE_AI_TELEMETRY": "maintenance_cm",
            "PRODUCTION_OEE": "production_job",
            "LOGISTICS_FLEET": "custom",
            "COMPLIANCE_REGISTRIES": "safety_check",
            "SYSTEM_INFRASTRUCTURE": "alarm_response"
        }
        
        for domain in domains:
            tasks.append({
                "title": f"Investigate {domain.replace('_', ' ')} anomaly",
                "priority": "high",
                "task_type": task_types.get(domain, "custom")
            })
        
        return tasks
    
    def _generate_commands(self, domains: List[str]) -> List[Dict[str, Any]]:
        """Generate recommended API commands"""
        commands = []
        
        for domain in domains:
            if domain == "EDGE_AI_TELEMETRY":
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/commands/asset/{asset_id}/emergency-stop",
                    "description": "Execute emergency stop on affected asset"
                })
            elif domain == "PRODUCTION_OEE":
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/kanban/boards/1/tasks",
                    "description": "Create maintenance task for production line"
                })
            elif domain == "LOGISTICS_FLEET":
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/yard/dock/appointments",
                    "description": "Reschedule dock appointment to prevent detention"
                })
            elif domain == "COMPLIANCE_REGISTRIES":
                commands.append({
                    "method": "POST",
                    "endpoint": "/api/v1/registries/{id}/items",
                    "description": "Log compliance near-miss incident"
                })
        
        return commands[:3]  # Limit to 3 commands
    
    def _identify_compliance(self, domains: List[str]) -> Optional[List[str]]:
        """Identify compliance implications"""
        if "COMPLIANCE_REGISTRIES" in domains:
            return ["ISO 22000 Food Safety", "OSHA 1910.119"]
        elif "LOGISTICS_FLEET" in domains:
            return ["DOT HOS compliance", "CTPAT security"]
        return None
    
    async def generate_synthetic_scenarios(
        self,
        count: int,
        db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """
        Generate synthetic correlation scenarios for training.
        
        Args:
            count: Number of scenarios to generate
            db: Database session
            
        Returns:
            List of generated scenarios
        """
        logger.info("generating_synthetic_scenarios", count=count)
        
        # Import the scenario generator from scripts
        import sys
        from pathlib import Path
        sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
        
        from generate_dataset import StateSpaceLoader, ScenarioGenerator
        
        # Load state space
        state_space = StateSpaceLoader("state_space")
        generator = ScenarioGenerator(state_space)
        
        # Generate scenarios
        scenarios = []
        for _ in range(count):
            scenario = generator.generate_scenario()
            scenarios.append(scenario.model_dump())
        
        logger.info("synthetic_scenarios_generated", count=len(scenarios))
        return scenarios
    
    async def list_scenarios(
        self,
        limit: int,
        offset: int,
        db: AsyncSession
    ) -> List[Dict[str, Any]]:
        """
        List generated correlation scenarios.
        
        Args:
            limit: Maximum number of scenarios to return
            offset: Offset for pagination
            db: Database session
            
        Returns:
            List of scenarios
        """
        # Placeholder - in production this would query a database
        # For now, return empty list
        return []
    
    def validate_scenario(self, scenario: CorrelationScenario) -> bool:
        """
        Validate a scenario against Pydantic schema.
        
        Args:
            scenario: The scenario to validate
            
        Returns:
            True if valid, False otherwise
        """
        try:
            # Pydantic validation happens automatically on instantiation
            # This method is for explicit validation if needed
            CorrelationScenario(**scenario.model_dump())
            return True
        except Exception as e:
            logger.error("scenario_validation_failed", error=str(e))
            return False


# Global instance
correlation_ai_engine = CorrelationAIEngine()
