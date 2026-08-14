"""
Correlation AI Engine Service

Integrates the Domain Interaction Component with AI inference capabilities.
This service handles both training-time scenario generation and runtime inference.
"""

from typing import List, Dict, Any, Optional, Tuple, Set
from uuid import UUID
from datetime import datetime, timezone
from pathlib import Path
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


class CorrelationModelUnavailableError(RuntimeError):
    """The configured Gemma adapter cannot be loaded or used."""


class CorrelationAIEngine:
    """
    Main correlation AI engine service.
    
    Responsibilities:
    - Analyze correlation scenarios using AI inference
    - Generate synthetic scenarios for training data
    - Validate scenarios against Pydantic schemas
    - Execute AI-recommended commands
    """
    
    #: What `model_version` says before any model is loaded (FS-434).
    #:
    #: It said **"gemma-4-placeholder"**. There is no gemma-4 — the configured base is
    #: `settings.CORRELATION_BASE_MODEL` and the loaded version reads `<base>+lora`. So the
    #: default named a model that does not exist, in a version field, on a payload a
    #: consumer uses to decide how much to trust the analysis, and it reached the logs:
    #: `correlation_analysis_complete model_version=gemma-4-placeholder`.
    #:
    #: `_simulate_analysis` already carries `simulated: True` and a lowered confidence
    #: (FS-349), so the payload was honest about being a heuristic while this one field
    #: still claimed a model. A reader filtering logs by `model_version` would have grouped
    #: heuristic output under a plausible model name.
    #:
    #: The replacement is not a nicer placeholder. It states the only true thing available
    #: before load: no model produced this.
    NO_MODEL_VERSION = "none (no correlation model loaded)"

    def __init__(self):
        self._model_loaded = False
        self._model_version = self.NO_MODEL_VERSION
        self._tokenizer = None
        self._model = None
        self._model_load_error: Optional[str] = None
    
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
                # Enabling the adapter is an explicit deployment choice. Do not
                # quietly serve a heuristic result as model inference when that
                # deployment is broken.
                raise CorrelationModelUnavailableError(
                    "The configured Correlation AI model is unavailable. "
                    "Check the Gemma base-model and LoRA adapter configuration."
                ) from e

        if analysis is None:
            analysis = self._simulate_analysis(scenario, domain_names)
            analysis["simulated"] = True
            analysis["response_mode"] = "heuristic"
        else:
            analysis["simulated"] = False
            analysis["response_mode"] = "model"
        
        logger.info(
            "correlation_analysis_complete",
            scenario_id=scenario.scenario_id,
            risk_score=analysis["risk_score"],
            # In the log line too: "analysis_complete" with a risk score reads as a
            # model result, and was emitted for heuristics as well.
            simulated=analysis.get("simulated", False),
            model_version=analysis.get("model_version"),
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
        has_data = bool(context.get("data_sources"))

        route_message = message
        route_context = context
        interpreted_intent = None
        if has_data and settings.CORRELATION_MODEL_ENABLED and self._has_spreadsheet_context(context):
            interpreted_intent = await self._interpret_spreadsheet_question(message, context)
            if interpreted_intent:
                route_context = dict(context)
                route_context["interpreted_intent"] = interpreted_intent
                route_message = str(interpreted_intent.get("normalized_question") or message)

        deterministic_response = self._deterministic_spreadsheet_response(route_message, route_context)
        if deterministic_response:
            drafted_response = await self._draft_grounded_spreadsheet_answer(
                message,
                route_context,
                deterministic_response,
            )
            if drafted_response:
                drafted_response["simulated"] = False
                drafted_response["response_mode"] = "evidence"
                return drafted_response
            deterministic_response["simulated"] = False
            deterministic_response["response_mode"] = "evidence"
            return deterministic_response

        if settings.CORRELATION_MODEL_ENABLED and (has_data or not self._is_data_analysis_question(message)):
            try:
                await self._ensure_model_loaded()
                prompt = self._build_chat_prompt(message, context)
                generated_text = await asyncio.to_thread(
                    self._generate_text_with_system,
                    self._chat_system_prompt(),
                    prompt,
                )
                content = self._clean_chat_text(generated_text, context)
                if content:
                    follow_up_questions = self._generate_chat_follow_ups(message, context, content)
                    return {
                        "response_text": content,
                        "predicted_root_cause": content,
                        "risk_score": None,
                        "target_kanban_tasks": [],
                        "remediation_commands": [],
                        "compliance_implications": None,
                        "model_version": f"{settings.CORRELATION_BASE_MODEL}+{settings.CORRELATION_ADAPTER_PATH}",
                        "confidence": 0.85,
                        # Always present, so a consumer can rely on the key rather
                        # than inferring "real" from its absence.
                        "simulated": False,
                        "response_type": "conversational",
                        "follow_up_questions": follow_up_questions,
                        "simulated": False,
                        "response_mode": "model",
                    }
            except Exception as e:
                logger.exception("gemma_chat_inference_failed", error=str(e))
                raise CorrelationModelUnavailableError(
                    "The configured Correlation AI model is unavailable. "
                    "Check the Gemma base-model and LoRA adapter configuration."
                ) from e

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
            "simulated": True,
            "simulation_reason": "heuristic chat fallback, not a model inference",
            "response_type": "conversational_fallback",
            "follow_up_questions": self._generate_chat_follow_ups(message, context),
            "simulated": True,
            "response_mode": "heuristic",
        }

    def _simulate_analysis(
        self,
        scenario: CorrelationScenario,
        domain_names: List[str]
    ) -> Dict[str, Any]:
        """Fallback analysis used when the Gemma adapter is unavailable.

        MARKED AS SIMULATED, deliberately.

        This output was previously indistinguishable from a real inference: it carried
        `confidence: 0.85` and a `model_version` of "gemma-4-placeholder", and the
        caller then logged `correlation_analysis_complete` with a risk score. So with
        CORRELATION_MODEL_ENABLED false (the default) -- or whenever inference threw --
        every correlation in the product was a heuristic presented as a model result,
        with no way for a caller, a UI, or a reader of the logs to tell.

        The heuristic itself is fine and useful. Presenting it as an inference is not.
        `simulated: True` and a lowered confidence let consumers label it honestly;
        no analysis or scoring logic is changed here.

        (Cross-lane note: this file is Harsh's area. This is the minimum change that
        makes the output falsifiable -- a flag and a confidence value.)
        """
        return {
            "simulated": True,
            "simulation_reason": (
                "heuristic fallback: the Gemma correlation adapter was disabled or "
                "unavailable, so this is not a model inference"
            ),
            "scenario_id": scenario.scenario_id,
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
            "predicted_root_cause": self._simulate_root_cause(domain_names, scenario.domain_links),
            "risk_score": self._calculate_risk_score(scenario.domain_links),
            "target_kanban_tasks": self._generate_kanban_tasks(domain_names),
            "remediation_commands": self._generate_commands(domain_names),
            "compliance_implications": self._identify_compliance(domain_names),
            "model_version": self._model_version,
            # NOT 0.85: that is what the real inference path reports, so a heuristic
            # was claiming model-grade confidence.
            "confidence": 0.4,
            "response_text": self._format_business_response(
                self._simulate_root_cause(domain_names, scenario.domain_links),
                self._calculate_risk_score(scenario.domain_links),
                self._generate_kanban_tasks(domain_names),
                self._generate_commands(domain_names),
            ),
            "follow_up_questions": self._generate_follow_ups(domain_names),
            "simulated": True,
            "response_mode": "heuristic",
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
            "analysis_timestamp": datetime.now(timezone.utc).isoformat(),
            "model_version": f"{settings.CORRELATION_BASE_MODEL}+{settings.CORRELATION_ADAPTER_PATH}",
            "confidence": 0.85,
            "response_text": generated_text.strip(),
            "follow_up_questions": self._generate_follow_ups(domain_names),
            "simulated": False,
            "response_mode": "model",
        })
        return parsed

    async def _ensure_model_loaded(self) -> None:
        if self._model_loaded:
            return
        if self._model_load_error:
            raise CorrelationModelUnavailableError(self._model_load_error)

        adapter_path = Path(settings.CORRELATION_ADAPTER_PATH).expanduser()
        if not adapter_path.is_dir():
            self._model_load_error = (
                f"Correlation LoRA adapter directory does not exist: {adapter_path}"
            )
            raise CorrelationModelUnavailableError(self._model_load_error)

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

        try:
            self._tokenizer, self._model = await asyncio.to_thread(load_model)
        except Exception as exc:
            self._model_load_error = f"Could not load Correlation AI model: {exc}"
            raise CorrelationModelUnavailableError(self._model_load_error) from exc
        self._model_loaded = True
        self._model_version = f"{settings.CORRELATION_BASE_MODEL}+lora"
        logger.info("gemma_correlation_model_loaded", adapter=settings.CORRELATION_ADAPTER_PATH)

    async def ensure_model_ready(self) -> None:
        """Public startup preflight for a deliberately enabled model deployment."""
        await self._ensure_model_loaded()

    def _generate_text(self, prompt: str) -> str:
        return self._generate_text_with_system(self._system_prompt(), prompt)

    def _intent_parser_system_prompt(self) -> str:
        return (
            "You translate natural operations chat into a strict backend spreadsheet request. "
            "Return ONLY valid JSON. Do not answer the user's question. Do not compute metrics. "
            "Do not invent column names. Use the allowed columns and recent conversation to understand references like "
            "'that issue', 'these rows', 'reanswer', or 'what's hurting us'. "
            "JSON schema: {"
            "\"intent\": one of [\"overview\", \"rank_groups\", \"compare_metrics\", \"show_rows\", "
            "\"group_breakdown\", \"action_plan\", \"checklist\", \"common_pattern\", \"projection\", "
            "\"unavailable\", \"general\"], "
            "\"normalized_question\": string, "
            "\"group_by\": string|null, "
            "\"rank_by\": string|null, "
            "\"metrics\": string[], "
            "\"filters\": object, "
            "\"depth\": one of [\"brief\", \"normal\", \"thorough\", \"drilldown\"], "
            "\"answer_style\": one of [\"summary\", \"ranked\", \"rows\", \"checklist\", \"narrative\"], "
            "\"requested_fields\": string[], "
            "\"missing_fields\": string[]"
            "}. "
            "If the user asks for a metric/field that is not in allowed_columns, include it in missing_fields and set "
            "intent to \"unavailable\" unless the question can be answered by clearly available fields."
        )

    def _recent_conversation_for_intent(self, context: Dict[str, Any]) -> List[Dict[str, str]]:
        history = context.get("conversation_history") or []
        compact = []
        for item in history[-10:]:
            role = str(item.get("role") or "user")
            content = str(item.get("content") or "")[:700]
            if content:
                compact.append({"role": role, "content": content})
        return compact

    def _build_intent_parser_prompt(self, message: str, context: Dict[str, Any]) -> str:
        processed = self._first_spreadsheet_processed(context) or {}
        profile = processed.get("full_sheet_profile") or {}
        action_plan = processed.get("concrete_action_plan") or []
        columns = self._allowed_spreadsheet_columns(context)
        multi = context.get("multi_spreadsheet_analysis") or {}
        intent_context = {
            "allowed_columns": columns,
            "session_file_count": len(context.get("data_sources") or []),
            "multi_file_analysis": {
                "file_count": multi.get("file_count"),
                "yoy_trends": multi.get("yoy_trends"),
                "shared_assets": multi.get("shared_assets"),
            },
            "available_groupings": list((profile.get("group_summary") or {}).keys()),
            "available_row_sets": list((profile.get("highest_risk_rows") or {}).keys()),
            "top_issues": [
                {
                    "issue": item.get("issue"),
                    "owner": item.get("owner"),
                    "check_first": item.get("check_first"),
                }
                for item in action_plan[:5]
            ],
            "recent_conversation": self._recent_conversation_for_intent(context),
            "current_user_message": message,
        }
        return (
            "Translate the current user message into the backend request JSON.\n\n"
            f"{json.dumps(intent_context, default=str)[:12000]}\n\n"
            "Remember: output JSON only."
        )

    def _extract_json_object(self, text: str) -> Optional[Dict[str, Any]]:
        cleaned = text.strip()
        cleaned = re.sub(r"(?is)^```(?:json)?\s*|\s*```$", "", cleaned).strip()
        candidates = [cleaned]
        match = re.search(r"(?s)\{.*\}", cleaned)
        if match:
            candidates.insert(0, match.group(0))
        for candidate in candidates:
            try:
                parsed = json.loads(candidate)
                if isinstance(parsed, dict):
                    return parsed
            except json.JSONDecodeError:
                try:
                    parsed = ast.literal_eval(candidate)
                    if isinstance(parsed, dict):
                        return parsed
                except (SyntaxError, ValueError):
                    continue
        return None

    def _validate_interpreted_intent(
        self,
        intent: Dict[str, Any],
        message: str,
        context: Dict[str, Any],
    ) -> Dict[str, Any]:
        allowed_intents = {
            "overview", "rank_groups", "compare_metrics", "show_rows", "group_breakdown",
            "action_plan", "checklist", "common_pattern", "projection", "unavailable", "general",
        }
        allowed_depths = {"brief", "normal", "thorough", "drilldown"}
        allowed_styles = {"summary", "ranked", "rows", "checklist", "narrative"}

        normalized = str(intent.get("normalized_question") or message).strip()
        parsed_intent = str(intent.get("intent") or "general").strip()
        if parsed_intent not in allowed_intents:
            parsed_intent = "general"

        columns = self._allowed_spreadsheet_columns(context)
        lower_columns = " ".join(columns).lower()

        requested_fields = intent.get("requested_fields") or []
        if not isinstance(requested_fields, list):
            requested_fields = []
        requested_fields = [str(field).strip() for field in requested_fields if str(field).strip()]

        missing_fields = intent.get("missing_fields") or []
        if not isinstance(missing_fields, list):
            missing_fields = []
        missing_fields = [str(field).strip() for field in missing_fields if str(field).strip()]

        # Add obvious missing concepts even if the parser forgot.
        concept_terms = {
            "damages": ("damage", "damages"),
            "safety": ("safety", "incident", "injury"),
            "customer complaints": ("customer complaints", "complaints", "satisfaction"),
            "shipping": ("shipping", "delivery", "supplier", "lead time"),
            "staffing": ("staffing", "labor", "headcount", "turnover"),
            "energy": ("energy", "power"),
            "compliance": ("compliance", "audit", "regulatory"),
        }
        combined_text = f"{message} {normalized}".lower()
        for label, terms in concept_terms.items():
            if any(term in combined_text for term in terms) and not any(term in lower_columns for term in terms):
                if label not in missing_fields:
                    missing_fields.append(label)

        if missing_fields and parsed_intent == "general":
            parsed_intent = "unavailable"

        metrics = intent.get("metrics") or []
        if not isinstance(metrics, list):
            metrics = []
        filters = intent.get("filters") if isinstance(intent.get("filters"), dict) else {}
        depth = str(intent.get("depth") or "normal")
        style = str(intent.get("answer_style") or "summary")

        validated = {
            "intent": parsed_intent,
            "normalized_question": normalized,
            "group_by": intent.get("group_by") if intent.get("group_by") else None,
            "rank_by": intent.get("rank_by") if intent.get("rank_by") else None,
            "metrics": [str(metric) for metric in metrics],
            "filters": filters,
            "depth": depth if depth in allowed_depths else "normal",
            "answer_style": style if style in allowed_styles else "summary",
            "requested_fields": requested_fields,
            "missing_fields": missing_fields,
        }

        # Force deterministic routing to understand the interpreted intent.
        if parsed_intent == "rank_groups" and validated.get("group_by"):
            group_by = str(validated["group_by"]).replace("_", " ")
            rank_by = str(validated.get("rank_by") or "cost impact").replace("_", " ")
            validated["normalized_question"] = f"Rank {group_by} by total {rank_by} and explain the top driver"
        elif parsed_intent == "show_rows":
            validated["normalized_question"] = normalized if "row" in normalized.lower() else f"Show exact rows for {normalized}"
        elif parsed_intent == "checklist":
            validated["normalized_question"] = normalized if "checklist" in normalized.lower() else f"Give me a next-shift checklist for {normalized}"
        elif parsed_intent == "projection":
            validated["normalized_question"] = normalized if "if" in normalized.lower() else f"What would change if we implement {normalized}"
        elif parsed_intent == "group_breakdown" and validated.get("group_by"):
            validated["normalized_question"] = f"Which {validated['group_by']} is hurting us the most?"
        elif parsed_intent == "overview" and validated["depth"] in {"thorough", "drilldown"}:
            validated["normalized_question"] = f"Overall what are your thoughts on improving operations. Give me a thorough answer. {normalized}"

        return validated

    async def _interpret_spreadsheet_question(
        self,
        message: str,
        context: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """Use Gemma only to understand user intent; backend still computes the facts."""
        if not settings.CORRELATION_MODEL_ENABLED or not self._has_spreadsheet_context(context):
            return None
        try:
            await self._ensure_model_loaded()
            generated_text = await asyncio.to_thread(
                self._generate_text_with_system,
                self._intent_parser_system_prompt(),
                self._build_intent_parser_prompt(message, context),
            )
            parsed = self._extract_json_object(generated_text)
            if not parsed:
                logger.warning("gemma_intent_parse_failed", raw=generated_text[:500])
                return None
            return self._validate_interpreted_intent(parsed, message, context)
        except Exception as e:
            logger.exception("gemma_intent_parser_failed", error=str(e))
            return None

    def _should_draft_with_gemma(self, message: str, response_type: str) -> bool:
        """Use Gemma as a writer for grounded data answers, never as the source of facts."""
        if not settings.CORRELATION_MODEL_ENABLED:
            return False
        if response_type in {
            "spreadsheet_delay_ranking",
            "spreadsheet_projection",
            "spreadsheet_comparison",
        }:
            return True
        return response_type == "spreadsheet_overview" and self._is_reflective_question(message)

    def _grounded_writer_system_prompt(self) -> str:
        return (
            "You are Omnius Correlation AI's answer writer. You are NOT allowed to invent facts. "
            "The backend has already analyzed the spreadsheet and provided the only facts you may use. "
            "Your job is to rewrite those facts into a clear, practical answer for an operations supervisor. "
            "If the provided facts do not answer part of the user's question, say that the spreadsheet does not contain "
            "that field or metric. Do not mention targets, baselines, previous periods, compliance, safety, training, "
            "customer satisfaction, shipping, supplier delays, staffing, or budgets unless those exact words appear in the "
            "allowed columns or computed facts. Do not output hidden reasoning or a numbered planning scaffold. "
            "Keep the answer grounded, human, and specific. End with a short 'So what does it mean?' paragraph."
        )

    def _grounded_fact_packet(self, context: Dict[str, Any], computed_answer: str) -> Dict[str, Any]:
        columns: List[str] = []
        for source in context.get("data_sources") or []:
            processed = source.get("processed_data") or {}
            if processed.get("type") != "spreadsheet":
                continue
            for column in processed.get("column_names") or []:
                name = str(column)
                if name not in columns:
                    columns.append(name)

        multi = context.get("multi_spreadsheet_analysis") or {}
        packet: Dict[str, Any] = {
            "allowed_columns": columns or (self._first_spreadsheet_processed(context) or {}).get("column_names") or [],
            "computed_answer": computed_answer,
            "multi_file_analysis": {
                "file_count": multi.get("file_count"),
                "narrative_summary": multi.get("narrative_summary"),
                "yoy_trends": multi.get("yoy_trends"),
                "file_rollups": multi.get("file_rollups"),
                "shared_assets": multi.get("shared_assets"),
                "asset_trends": multi.get("asset_trends"),
            },
        }

        processed = self._first_spreadsheet_processed(context) or {}
        profile = processed.get("full_sheet_profile") or {}
        packet.update({
            "numeric_comparisons": processed.get("numeric_comparisons") or [],
            "concrete_action_plan": processed.get("concrete_action_plan") or [],
            "operational_summary": profile.get("operational_summary") or {},
            "group_summary": profile.get("group_summary") or {},
            "highest_risk_rows": profile.get("highest_risk_rows") or {},
        })
        return packet

    def _build_grounded_writer_prompt(
        self,
        message: str,
        context: Dict[str, Any],
        deterministic_response: Dict[str, Any],
    ) -> str:
        packet = self._grounded_fact_packet(
            context,
            str(deterministic_response.get("response_text") or ""),
        )
        return (
            "User question:\n"
            f"{message}\n\n"
            "Locked spreadsheet fact packet. Use only these facts:\n"
            f"{json.dumps(packet, default=str)[: settings.CORRELATION_GROUNDED_PACKET_MAX_CHARS]}\n\n"
            "Write the final user-facing answer now. Do not add any metric, percentage, trend, department, or cause "
            "that is not in the packet. If the user asks for a metric that is missing from allowed_columns, state that "
            "the spreadsheet does not include that metric and answer with the closest available fields."
        )

    def _numbers_in_text(self, text: str) -> set:
        numbers = set()
        for match in re.findall(r"\$?\b\d[\d,]*(?:\.\d+)?%?\b", text):
            normalized = match.replace("$", "").replace(",", "").replace("%", "")
            if normalized:
                numbers.add(normalized)
        return numbers

    def _validate_grounded_draft(self, draft: str, context: Dict[str, Any], fact_packet_text: str) -> bool:
        if not draft.strip():
            return False

        normalized = draft.lower()
        banned_phrases = [
            "customer satisfaction",
            "employee turnover",
            "safety enhancement",
            "supplier delivery",
            "shipping cost",
            "shipping costs",
            "supply chain",
            "compliance",
            "training",
            "previous period",
            "last month",
            "last 30 days",
            "6 months",
            "baseline",
            "target",
            "cycle time",
            "cycle times",
            "raci",
        ]
        if any(phrase in normalized for phrase in banned_phrases):
            return False

        if re.search(r"(?i)\b(up|down|increase|decrease|improve|improvement|reduce|reduction)\b.{0,40}\b\d+(?:\.\d+)?%", draft):
            allowed_text = fact_packet_text.lower()
            if not re.search(r"\b\d+(?:\.\d+)?%", allowed_text):
                return False

        allowed_numbers = self._numbers_in_text(fact_packet_text)
        draft_numbers = self._numbers_in_text(draft)
        unsupported = {
            number for number in draft_numbers
            if number not in allowed_numbers and float(number) > 2
        }
        if unsupported:
            return False

        allowed_columns = " ".join(self._allowed_spreadsheet_columns(context)).lower()
        if "damage" in normalized and "damage" not in allowed_columns:
            return False
        return True

    async def _draft_grounded_spreadsheet_answer(
        self,
        message: str,
        context: Dict[str, Any],
        deterministic_response: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        response_type = str(deterministic_response.get("response_type") or "")
        if not self._should_draft_with_gemma(message, response_type):
            return None

        try:
            await self._ensure_model_loaded()
            prompt = self._build_grounded_writer_prompt(message, context, deterministic_response)
            generated_text = await asyncio.to_thread(
                self._generate_text_with_system,
                self._grounded_writer_system_prompt(),
                prompt,
            )
            content = self._clean_chat_text(generated_text, context)
            fact_packet_text = prompt
            if not self._validate_grounded_draft(content, context, fact_packet_text):
                logger.warning("grounded_gemma_draft_rejected", response_type=response_type)
                return None

            drafted = dict(deterministic_response)
            drafted["response_text"] = content
            drafted["predicted_root_cause"] = content
            drafted["model_version"] = f"grounded-writer:{settings.CORRELATION_BASE_MODEL}+{settings.CORRELATION_ADAPTER_PATH}"
            drafted["confidence"] = min(float(drafted.get("confidence") or 0.95), 0.9)
            return drafted
        except Exception as e:
            logger.exception("grounded_gemma_draft_failed", error=str(e))
            return None

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
            "Use readable Markdown formatting: short section headings, bullet lists, and bold labels for important fields. "
            "Do not use raw JSON, Python dictionaries, or model jargon. "
            "Do not output hidden reasoning, scratchpad notes, chain-of-thought, or sections named thought. "
            "If you want to show your approach, provide only a brief user-facing analysis summary. "
            "If the user is just chatting, answer normally. If they ask about uploaded data, use the data context "
            "carefully and mention when the data looks synthetic, thin, or insufficient. Use the computed spreadsheet "
            "profile as source-of-truth for totals, trends, groups, and worst rows. Never invent percentages, cycle "
            "times, defect rates, or improvement claims that are not present in the provided profile. If the profile "
            "does not support a metric, say what is missing and use the closest available columns instead. "
            "When useful, cite actual column names, row values, facilities, lines, assets, or delay reasons from the data. "
            "Never mention targets, baselines, budgets, customer satisfaction, energy usage, staffing, training programs, "
            "compliance audits, delivery-time KPIs, or logistics performance unless those exact concepts appear in the "
            "allowed column list or must-use findings. When the context contains a concrete action plan, use it as the "
            "basis for recommendations: preserve the owner, check-first values, first next-shift action, and metric to watch. "
            "For action plans, put fields like Asset ID, Asset Name, Production Line, Shift, Maintenance Status, Priority, "
            "Downtime, Defects, Vibration, and Cost on separate bullet lines with bold labels. For broad overview questions, "
            "do not dump every row or every action field. Give a readable executive summary, the 2-3 strongest correlations, "
            "and only the most important next steps. For direct drill-down questions, be specific and detailed. "
            "When the user asks for your thoughts, your opinion, a thorough or in-depth answer, or how you would "
            "improve operations, do not return a bare list of stats. Think it through and write a thoughtful, "
            "multi-paragraph narrative that connects the dots: name the biggest issue group from the action plan, "
            "explain the likely root cause using the actual asset, line, shift, downtime, defect, vibration, and "
            "maintenance-status values, explain how the issues relate to each other and to the production shortfall, "
            "and close with prioritized, concrete advice on what to do first and what to watch. Reason only from the "
            "provided computed profile and action plan numbers; never invent any metric, percentage, or trend that is "
            "not in them. It is better to reason carefully about the real numbers than to pad the answer with invented ones."
        )

    def _has_spreadsheet_context(self, context: Dict[str, Any]) -> bool:
        return any(
            (source.get("processed_data") or {}).get("type") == "spreadsheet"
            for source in context.get("data_sources", [])
        )

    def _allowed_spreadsheet_columns(self, context: Dict[str, Any]) -> List[str]:
        columns: List[str] = []
        for source in context.get("data_sources", []):
            processed = source.get("processed_data") or {}
            if processed.get("type") != "spreadsheet":
                continue
            for column in processed.get("column_names") or []:
                column_name = str(column)
                if column_name not in columns:
                    columns.append(column_name)
        return columns

    def _spreadsheet_sources(self, context: Dict[str, Any]) -> List[Dict[str, Any]]:
        return [
            source for source in context.get("data_sources", [])
            if (source.get("processed_data") or {}).get("type") == "spreadsheet"
        ]

    def _is_multi_spreadsheet_question(self, message: str) -> bool:
        normalized = message.lower()
        return any(
            term in normalized
            for term in (
                "across files", "across spreadsheets", "multiple files", "all files",
                "all uploads", "each file", "between files", "compare files",
                "over time", "over the years", "10 year", "ten year", "multi-year",
                "multi year", "year over year", "yoy", "long term", "long-term",
                "historical", "extended period", "time series", "cross-file",
                "cross file", "correlate", "correlation across",
            )
        )

    def _should_use_multi_spreadsheet_analysis(self, message: str, context: Dict[str, Any]) -> bool:
        analysis = context.get("multi_spreadsheet_analysis") or {}
        if analysis.get("file_count", 0) < 2:
            return False
        if self._is_multi_spreadsheet_question(message):
            return True
        if self._is_consultant_advisory_question(message) and analysis.get("file_count", 0) >= 2:
            return True
        if len(self._spreadsheet_sources(context)) >= 2 and self._is_operations_overview_question(message):
            return True
        return False

    def _format_multi_spreadsheet_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._should_use_multi_spreadsheet_analysis(message, context):
            return None

        analysis = context.get("multi_spreadsheet_analysis") or {}
        findings = analysis.get("cross_file_findings") or []
        if not findings:
            return None

        lines = ["### Cross-file operational correlation", "", analysis.get("narrative_summary", "")]
        lines.append("")
        lines.append("**File-by-file snapshot**")
        for rollup in analysis.get("file_rollups") or []:
            bits = [f"**{rollup.get('file_name')}**", f"{rollup.get('rows')} rows"]
            if rollup.get("period"):
                bits.append(str(rollup["period"]))
            if rollup.get("attainment_pct") is not None:
                bits.append(f"attainment {self._format_metric_value(rollup['attainment_pct'])}%")
            if rollup.get("shortfall_total") is not None:
                bits.append(f"shortfall {self._format_metric_value(rollup['shortfall_total'])} units")
            if rollup.get("total_loss") is not None:
                bits.append(f"cost {self._format_metric_value(rollup['total_loss'])}")
            if rollup.get("total_downtime") is not None:
                bits.append(f"downtime {self._format_metric_value(rollup['total_downtime'])}")
            lines.append("- " + " | ".join(bits))

        shared = analysis.get("shared_assets") or {}
        if shared:
            lines.append("")
            lines.append("**Shared assets (anchor comparisons here)**")
            for asset, files in list(shared.items())[:8]:
                lines.append(f"- **{asset}** in {len(files)} file(s): {', '.join(files)}")

        trends = analysis.get("asset_trends") or []
        if trends:
            lines.append("")
            lines.append("**Cross-file signals on shared assets**")
            for trend in trends[:5]:
                direction_bits = []
                if trend.get("downtime_direction"):
                    direction_bits.append(f"downtime {trend['downtime_direction']}")
                if trend.get("loss_direction"):
                    direction_bits.append(f"cost {trend['loss_direction']}")
                header = trend.get("asset") or "Asset"
                if direction_bits:
                    lines.append(f"\n**{header}** ({', '.join(direction_bits)})")
                else:
                    lines.append(f"\n**{header}**")
                for pt in trend.get("files") or []:
                    period = (pt.get("period") or {}).get("min", "")
                    bits = [pt.get("file_name", "")]
                    if period:
                        bits.append(period[:10])
                    if pt.get("total_loss") is not None:
                        bits.append(f"cost {self._format_metric_value(pt['total_loss'])}")
                    if pt.get("total_downtime") is not None:
                        bits.append(f"downtime {self._format_metric_value(pt['total_downtime'])}")
                    lines.append(f"  - {' | '.join(bits)}")

        lines.append(
            "\n**How to use this:** compare the same asset or line across files before changing process "
            "floor-wide. If an asset shows up in every year/file with rising cost or downtime, that is your "
            "chronic issue; if it appears once, treat it as a slice-specific spike."
        )
        return "\n".join(lines)

    def _multi_analysis(self, context: Dict[str, Any]) -> Dict[str, Any]:
        return context.get("multi_spreadsheet_analysis") or {}

    def _is_cross_file_trends_question(self, message: str) -> bool:
        normalized = message.lower()
        return any(
            term in normalized
            for term in (
                "trend", "trends", "trending", "over time", "over the years",
                "year over year", "yoy", "year-on-year", "year on year",
                "across all files", "all files", "all uploads", "each year",
                "multi-year", "multi year", "historical", "pattern over",
            )
        )

    def _format_cross_file_trends_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_cross_file_trends_question(message):
            return None
        analysis = self._multi_analysis(context)
        if analysis.get("file_count", 0) < 2:
            return None

        yoy = analysis.get("yoy_trends") or {}
        metrics = yoy.get("metrics") or []
        if not metrics:
            return None

        years = yoy.get("years") or []
        year_span = f"{years[0]}–{years[-1]}" if len(years) >= 2 else "your uploaded period"
        lines = [
            f"### Trends across your files ({year_span})",
            "",
            f"I compared **{analysis.get('file_count')} files** as time slices — here's what moved:",
        ]

        for row in metrics:
            label = row.get("label") or row.get("metric")
            direction = row.get("direction") or "flat"
            first = row.get("first")
            last = row.get("last")
            delta = row.get("delta")
            year_bits = []
            for year, value in zip(row.get("years") or [], row.get("values") or []):
                if value is None:
                    continue
                year_bits.append(f"{year}: {self._format_metric_value(value)}")
            trend_phrase = {
                "improving": "**improving**",
                "worsening": "**worsening**",
                "flat": "**flat**",
            }.get(direction, direction)
            delta_text = ""
            if delta is not None:
                delta_text = f" (net change {self._format_metric_value(delta)})"
            lines.append(
                f"\n**{label}** — {trend_phrase}{delta_text}\n"
                + " → ".join(year_bits)
            )

        shared = analysis.get("shared_assets") or {}
        if shared:
            anchor = max(shared.items(), key=lambda kv: len(kv[1]))[0]
            lines.append(
                f"\n**Anchor asset:** **{anchor}** shows up in {len(shared[anchor])} files — "
                "use it to validate whether floor-wide trends hold on one machine or are spread across assets."
            )

        attainment_row = next((m for m in metrics if m.get("metric") == "attainment_pct"), None)
        shortfall_row = next((m for m in metrics if m.get("metric") == "shortfall_total"), None)
        takeaway_bits = []
        if attainment_row and attainment_row.get("direction"):
            takeaway_bits.append(f"attainment is **{attainment_row['direction']}**")
        if shortfall_row and shortfall_row.get("direction"):
            takeaway_bits.append(f"planned shortfall is **{shortfall_row['direction']}**")
        if attainment_row and attainment_row.get("last") is not None:
            gap = max(0.0, 100.0 - float(attainment_row["last"]))
            takeaway_bits.append(f"you're still ~{self._format_metric_value(gap)} points below plan")
        if takeaway_bits:
            lines.append("\n**Takeaway:** " + ", ".join(takeaway_bits) + ".")
        return "\n".join(lines)

    def _extract_asset_from_message(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        normalized = message.upper()
        match = re.search(r"\b([A-Z]{2,5}[-_]\d{2,5}(?:[-_]\d{2,5})?)\b", normalized)
        if match:
            return match.group(1).replace("_", "-")
        shared = self._multi_analysis(context).get("shared_assets") or {}
        if len(shared) == 1:
            return next(iter(shared.keys()))
        return None

    def _is_shared_asset_comparison_question(self, message: str) -> bool:
        normalized = message.lower()
        has_compare = any(
            term in normalized
            for term in ("compare", "across our uploaded", "across files", "performance improving", "slipping", "where is it")
        )
        has_asset = "asset" in normalized or bool(re.search(r"\b[a-z]{2,5}-\d", normalized))
        return has_compare and has_asset

    def _format_shared_asset_comparison_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_shared_asset_comparison_question(message):
            return None
        analysis = self._multi_analysis(context)
        if analysis.get("file_count", 0) < 2:
            return None

        asset_key = self._extract_asset_from_message(message, context)
        trends = analysis.get("asset_trends") or []
        trend = next((t for t in trends if t.get("asset") == asset_key), None)
        if not trend and trends:
            trend = trends[0]
            asset_key = trend.get("asset")
        if not trend:
            return None

        lines = [
            f"### {asset_key} across your files",
            "",
            "File-by-file read (same asset, different year slices):",
        ]
        for point in trend.get("files") or []:
            period = (point.get("period") or {}).get("min", "")[:4]
            bits = [f"**{period or point.get('file_name')}**"]
            if point.get("total_loss") is not None:
                bits.append(f"cost {self._format_metric_value(point['total_loss'])}")
            if point.get("total_downtime") is not None:
                bits.append(f"downtime {self._format_metric_value(point['total_downtime'])}")
            if point.get("total_defects") is not None:
                bits.append(f"defects {self._format_metric_value(point['total_defects'])}")
            lines.append("- " + " | ".join(bits))

        verdict_parts = []
        if trend.get("downtime_direction") == "improving":
            verdict_parts.append("downtime **improved** from the first to the last file")
        elif trend.get("downtime_direction") == "worsening":
            verdict_parts.append("downtime **worsened** across the period")
        if trend.get("loss_direction") == "improving":
            verdict_parts.append("cost impact **came down**")
        elif trend.get("loss_direction") == "worsening":
            verdict_parts.append("cost impact **rose**")
        if trend.get("defect_direction") == "improving":
            verdict_parts.append("defects **eased**")
        elif trend.get("defect_direction") == "worsening":
            verdict_parts.append("defects **increased**")

        if verdict_parts:
            lines.append("\n**Direction:** " + "; ".join(verdict_parts) + ".")
        else:
            lines.append("\n**Direction:** metrics are mixed — drill into the worst year before changing floor-wide.")

        lines.append(
            "\n**What to do:** if the middle year (often peak load) is the worst, target maintenance and changeover "
            "on this asset before the next high season — don't wait for finance to show the pain a quarter later."
        )
        return "\n".join(lines)

    def _is_consultant_advisory_question(self, message: str) -> bool:
        if self._is_cross_file_trends_question(message) or self._is_shared_asset_comparison_question(message):
            return False
        normalized = message.lower()
        return any(
            term in normalized
            for term in (
                "plan for growth", "prepare for growth", "more orders", "increase production",
                "ramp up", "ramp production", "scale up", "scale production", "growth plan",
                "expand capacity", "take more orders", "increase orders",
                "foresee", "bottleneck", "going smoothly", "looks steady", "no real issue",
                "high season", "low season", "peak season", "busy season", "seasonal",
                "prepare better", "prepare for the next",
                "do better", "do more of", "what's working", "whats working", "going well",
                "going good", "what is working", "how can we improve", "how do we improve",
                "cross reference", "cross-reference", "cross reference", "finance tab",
                "production tab", "three different", "multiple places", "consultant",
                "big picture", "plan for", "how best do we",
            )
        )

    def _format_consultant_advisory_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_consultant_advisory_question(message):
            return None

        from app.services.session_suggested_questions import _build_session_intelligence

        data_sources = context.get("data_sources") or []
        if not data_sources:
            return None

        intel = _build_session_intelligence(data_sources, context.get("multi_spreadsheet_analysis"))
        if not intel.get("spreadsheet_count") and not intel.get("document_count"):
            return None

        normalized = message.lower()
        line = (intel.get("lines") or [None])[0]
        asset = (intel.get("shared_assets") or intel.get("assets") or [None])[0]
        multi = intel.get("multi") or {}
        file_count = intel.get("spreadsheet_count") or 0
        years = intel.get("years") or []
        year_label = f"{years[0]}–{years[-1]}" if len(years) >= 2 else None
        yoy = multi.get("yoy_trends") or {}

        def _trend_hook() -> str:
            parts = []
            for key, label in (("attainment_pct", "attainment"), ("shortfall_total", "shortfall")):
                row = next((m for m in yoy.get("metrics") or [] if m.get("metric") == key), None)
                if row and row.get("direction"):
                    parts.append(f"{label} {row['direction']}")
            return " · ".join(parts)

        hook = _trend_hook()
        intro = ""
        if hook and file_count >= 2 and year_label:
            intro = f"Across **{file_count} files** ({year_label}), {hook}.\n\n"

        if any(term in normalized for term in ("season", "high season", "low season", "peak", "prepare")):
            return (
                "### Seasonal preparation\n\n"
                + intro
                + (
                    f"Before the next peak on **{line or 'your busiest lines'}**, pre-stage materials, "
                    f"pre-book maintenance on **{asset or 'repeat bottleneck assets'}**, and align finance on "
                    "inventory + temp labor cash — your historical files show shortfall tightening slowly, "
                    "but still ~20%+ below plan in peak years."
                )
            )

        if any(term in normalized for term in ("growth", "orders", "ramp", "scale", "capacity", "plan for")):
            target = line or asset or "your constrained line"
            return (
                "### Growth planning\n\n"
                + intro
                + (
                    f"If orders rise on **{target}**, stress-test finance (margin/cash) and production "
                    f"(throughput/downtime) together before adding volume. Sequence: (1) find today's cap, "
                    "(2) model +10–15% load, (3) only then expand orders or marketing."
                )
            )

        if any(term in normalized for term in ("foresee", "bottleneck", "smooth", "steady", "no real issue")):
            watch = line or asset or "changeovers and maintenance backlog"
            return (
                "### Bottlenecks you may not feel yet\n\n"
                + intro
                + (
                    f"Even flat KPIs hide queueing on **{watch}**. Watch downtime, defects per 1k units, "
                    "and shortfall vs plan weekly — not just monthly P&L."
                )
            )

        if any(term in normalized for term in ("working", "going well", "do more", "do better", "improve")):
            return (
                "### Double down on what's working\n\n"
                + intro
                + (
                    "Find lines/shifts with the smallest shortfall and lowest defect cost — that's where "
                    "extra volume is cheapest. Scale crew/setup/material flow there before fixing weaker areas."
                )
            )

        return None

    def _is_data_analysis_question(self, message: str) -> bool:
        normalized = message.lower()
        data_terms = (
            "operation", "operational", "data", "spreadsheet", "excel", "csv", "file",
            "analyze", "analysis", "bottleneck", "efficiency", "downtime", "defect",
            "cost", "loss", "production", "shift", "asset", "line", "rundown",
            "summary", "going on", "what's wrong", "what is wrong", "performance",
            "metric", "issue", "problem", "next step", "recommend", "rank", "rows",
            "planned", "actual", "delay", "quality", "maintenance", "vibration",
            "compare", "correlat", "root cause",
        )
        help_only = (
            "what can you help",
            "how can you help",
            "how exactly",
            "what do you do",
            "who are you",
        )
        if any(term in normalized for term in help_only):
            return False
        return any(term in normalized for term in data_terms)

    def _is_reflective_question(self, message: str) -> bool:
        """Open-ended questions that deserve real reasoning, not a templated snapshot."""
        normalized = message.lower()
        return any(
            term in normalized
            for term in (
                "your thoughts", "your think", "what do you think", "what are your thoughts",
                "your opinion", "your take", "your view", "how would you", "what would you",
                "thorough", "in depth", "in-depth", "deep dive", "deep-dive", "detailed answer",
                "elaborate", "walk me through", "talk me through", "explain in detail",
                "thoughtful", "reason through", "strategy", "strategize", "give me a thorough",
                "overall thoughts", "your honest", "comprehensive", "big picture", "step back",
            )
        )

    def _is_cost_delay_question(self, message: str) -> bool:
        normalized = message.lower()
        return any(
            keyword in normalized
            for keyword in ("cost", "delay", "loss", "correlat", "root issue", "root cause")
        )

    def _is_delay_ranking_question(self, message: str) -> bool:
        normalized = message.lower()
        return (
            "delay" in normalized
            and any(term in normalized for term in ("rank", "ranking", "ranked", "top", "biggest", "highest", "worst"))
            and any(term in normalized for term in ("cost", "loss", "impact", "downtime", "defect", "driver"))
        )

    def _is_numeric_comparison_question(self, message: str) -> bool:
        normalized = message.lower()
        return any(
            keyword in normalized
            for keyword in ("compare", "against", "versus", " vs ", " vs.", "vs.", " v.s", "relationship", "correlat")
        ) and any(
            keyword in normalized
            for keyword in ("defect", "planned", "actual", "downtime", "cost", "loss", "vibration")
        )

    def _is_operations_overview_question(self, message: str) -> bool:
        normalized = message.lower()
        overview_terms = (
            "run down",
            "rundown",
            "what is going on",
            "what's going on",
            "whats going on",
            "going on",
            "current operations",
            "operations",
            "operational data",
            "operational",
            "more efficient",
            "efficiency",
            "improve",
            "areas for improvement",
            "summary",
            "summarize",
            "is this bad",
            "are we okay",
            "main problem",
            "biggest problem",
            "what's wrong",
            "what is wrong",
            "looks bad",
            "trouble",
            "bottleneck",
            "bottlneck",
            "biggest bottleneck",
            "where are we losing",
            "where do we stand",
            "how are we doing",
            "status",
            "overview",
            "your thoughts",
            "what do you think",
            "your take",
            "your opinion",
            "thorough",
            "deep dive",
            "deep-dive",
            "in depth",
            "in-depth",
            "how would you",
            "what would you",
            "improving",
            "improvement",
            "big picture",
            "step back",
        )
        return any(term in normalized for term in overview_terms)

    def _is_row_drilldown_question(self, message: str) -> bool:
        normalized = message.lower()
        return any(
            term in normalized
            for term in (
                "exact rows", "top 5 rows", "top rows", "show rows", "show me the rows",
                "show the rows", "row behind", "rows behind", "which rows", "list the rows",
                "see the rows", "underlying rows", "raw rows", "actual rows", "specific rows",
            )
        )

    def _is_asset_frequency_question(self, message: str) -> bool:
        normalized = message.lower()
        return "asset" in normalized and any(
            term in normalized
            for term in ("shows up most", "most often", "appears most", "shows up the most", "common")
        )

    def _is_projection_question(self, message: str) -> bool:
        normalized = message.lower()
        outcome_terms = (
            "goal after", "goal of", "what is the goal", "what's the goal", "whats the goal",
            "after implementing", "after we implement", "after following", "once we follow",
            "what should we achieve", "what are we trying to", "expected result", "end goal",
            "purpose of", "why implement", "what does success look", "what will we accomplish",
            "what happens after", "point of the checklist", "goal of the checklist",
        )
        if any(term in normalized for term in outcome_terms):
            return True
        return any(
            term in normalized
            for term in (
                "what will it look like", "what would it look like", "if we implement", "if we fix",
                "if we resolve", "if we address", "what happens if", "expected outcome", "what's the impact if",
                "what is the impact if", "what would change", "after we fix", "once we fix", "what do we gain",
                "what would we gain", "worth it", "projected", "potential savings", "how much could we save",
                "what's the upside", "implement all", "implement everything", "implement these",
            )
        )

    def _is_common_pattern_question(self, message: str) -> bool:
        normalized = message.lower()
        return any(
            term in normalized
            for term in (
                "in common", "have in common", "what's the pattern", "whats the pattern",
                "the pattern", "what connects", "what links", "what do they share",
                "what do these share", "shared", "same thing", "common thread",
                "common theme", "any pattern", "see a pattern",
            )
        )

    def _is_checklist_question(self, message: str) -> bool:
        normalized = message.lower()
        # Meta questions about outcomes/goals after a checklist are not new checklist requests.
        if "checklist" in normalized and any(
            term in normalized
            for term in (
                "goal", "purpose", "outcome", "achieve", "after implementing", "after following",
                "success look", "what happens after", "point of",
            )
        ):
            return False
        return any(
            term in normalized
            for term in (
                "checklist", "check before", "check first before", "what to check",
                "what should the owner check", "before the shift", "before shift start",
                "turn this into a", "turn these rows into", "turn that into",
                "step by step", "step-by-step", "steps to", "to-do list", "to do list",
                "give me a list", "make a list", "what should they check",
            )
        )

    def _is_location_breakdown_question(self, message: str) -> bool:
        """Questions like 'which line/asset is hurting us most' belong to the group handler, not the action plan."""
        normalized = message.lower()
        has_location = any(term in normalized for term in ("line", "asset", "machine", "equipment", "facility"))
        has_superlative = any(
            term in normalized
            for term in ("most", "worst", "biggest", "highest", "hurting", "driving", "compare", "rank")
        )
        return has_location and has_superlative

    def _is_action_plan_question(self, message: str) -> bool:
        normalized = message.lower()
        # Defer "which line/asset is worst" style questions to the group breakdown handler.
        if self._is_location_breakdown_question(message):
            return False
        return any(
            term in normalized
            for term in (
                "what should we do",
                "what should i do",
                "fix first",
                "tackle first",
                "start first",
                "next shift",
                "action plan",
                "game plan",
                "recommend",
                "who should",
                "owner",
                "tell the team",
                "tell maintenance",
                "tell quality",
                "make it better",
                "how do we fix",
                "how do i fix",
                "how do i approach",
                "how do we approach",
                "how should we approach",
                "approach solving",
                "approach this",
                "how do i solve",
                "how do we solve",
                "how to solve",
                "solve these",
                "solve this",
                "where do i start",
                "where do we start",
                "where should i start",
                "what now",
                "what do we do",
                "what do i do",
                "help me solve",
                "help me fix",
                "prioritize",
                "priorities",
                "game plan",
                "what's the plan",
                "whats the plan",
                "bottleneck",
                "bottlneck",
                "biggest problem",
                "main problem",
                "biggest issue",
                "worst problem",
                "biggest concern",
                "biggest drain",
                "pain point",
                "holding us back",
                "slowing us down",
                "hurting us the most",
                "what's hurting",
                "what is hurting",
                "single biggest",
            )
        )

    def _is_group_question(self, message: str) -> bool:
        normalized = message.lower()
        return any(term in normalized for term in ("line", "asset", "shift", "day", "night", "facility")) and any(
            term in normalized
            for term in (
                "which",
                "worst",
                "best",
                "compare",
                "by ",
                "break down",
                "breakdown",
                "where",
                "biggest",
                "most",
                "least",
            )
        )

    def _is_issue_question(self, message: str) -> bool:
        normalized = message.lower()
        return any(
            term in normalized
            for term in (
                "quality",
                "defect",
                "maintenance",
                "sensor",
                "downtime",
                "cost",
                "loss",
                "delay",
                "material",
                "changeover",
                "inspection",
                "priority",
                "why",
                "root",
                "problem",
                "issue",
            )
        ) and any(
            term in normalized
            for term in ("what", "why", "where", "which", "explain", "driving", "causing", "reason", "issue", "problem")
        )

    def _first_spreadsheet_processed(self, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        for source in context.get("data_sources", []):
            processed = source.get("processed_data") or {}
            if processed.get("type") == "spreadsheet":
                return processed
        return None

    def _format_metric_value(self, value: Any) -> str:
        if value is None:
            return "n/a"
        if isinstance(value, float):
            return f"{value:,.1f}" if value % 1 else f"{value:,.0f}"
        if isinstance(value, int):
            return f"{value:,}"
        return str(value)

    def _format_check_first_lines(self, check_first: Dict[str, Any]) -> List[str]:
        labels = {
            "asset_id": "Asset ID",
            "asset_name": "Asset name",
            "production_line": "Production line",
            "shift": "Shift",
            "maintenance_status": "Maintenance status",
            "priority": "Priority",
            "estimated_cost": "Estimated cost impact",
            "downtime": "Downtime",
            "defect_count": "Defect count",
            "vibration": "Vibration",
        }
        lines = []
        for key, label in labels.items():
            if key in check_first and check_first[key] is not None:
                lines.append(f"  - **{label}:** {self._format_metric_value(check_first[key])}")
        return lines

    def _format_spreadsheet_row_detail(self, row: Dict[str, Any], index: int) -> List[str]:
        labels = [
            ("date", "Date"),
            ("shift", "Shift"),
            ("facility", "Facility"),
            ("production_line", "Production line"),
            ("asset_id", "Asset ID"),
            ("asset_name", "Asset name"),
            ("planned_units", "Planned units"),
            ("actual_units", "Actual units"),
            ("_actual_gap", "Unit gap"),
            ("downtime_minutes", "Downtime"),
            ("downtime", "Downtime"),
            ("defect_count", "Defect count"),
            ("vibration_mm_s", "Vibration"),
            ("vibration_level", "Vibration"),
            ("maintenance_status", "Maintenance status"),
            ("delay_reason", "Delay reason"),
            ("priority", "Priority"),
            ("estimated_cost_impact_usd", "Estimated cost impact"),
            ("estimated_loss", "Estimated loss"),
        ]
        lines = [f"**Row {index}**"]
        for key, label in labels:
            if key in row and row[key] is not None:
                lines.append(f"- **{label}:** {self._format_metric_value(row[key])}")
        return lines

    def _row_pool(self, profile: Dict[str, Any]) -> List[Dict[str, Any]]:
        """Collect every computed high-risk row into one deduped pool for filtering."""
        highest_rows = profile.get("highest_risk_rows") or {}
        pool: List[Dict[str, Any]] = []
        seen = set()
        identity_keys = (
            "date", "shift", "facility", "production_line", "asset_id", "asset_name",
            "planned_units", "actual_units", "downtime_minutes", "downtime", "defect_count",
            "delay_reason", "priority", "estimated_cost_impact_usd", "estimated_loss",
        )
        for rows in highest_rows.values():
            for row in rows or []:
                signature_values = {
                    key: row.get(key)
                    for key in identity_keys
                    if key in row and row.get(key) is not None
                }
                signature = json.dumps(signature_values or row, sort_keys=True, default=str)
                if signature in seen:
                    continue
                seen.add(signature)
                pool.append(row)
        return pool

    def _row_sort_value(self, row: Dict[str, Any], metric_key: str) -> float:
        candidates = {
            "cost": ("estimated_cost_impact_usd", "estimated_loss"),
            "defect": ("defect_count",),
            "downtime": ("downtime_minutes", "downtime"),
            "shortfall": ("_actual_gap",),
        }.get(metric_key, ("estimated_cost_impact_usd", "estimated_loss"))
        for key in candidates:
            if row.get(key) is not None:
                try:
                    return float(row.get(key))
                except (TypeError, ValueError):
                    return 0.0
        return 0.0

    def _format_row_drilldown_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_row_drilldown_question(message):
            return None

        processed = self._first_spreadsheet_processed(context)
        if not processed:
            return None

        profile = processed.get("full_sheet_profile") or {}
        highest_rows = profile.get("highest_risk_rows") or {}
        action_plan = processed.get("concrete_action_plan") or []
        group_summary = profile.get("group_summary") or {}
        normalized = message.lower()

        metric_key = "shortfall"
        if "defect" in normalized:
            metric_key = "defect"
        elif "downtime" in normalized:
            metric_key = "downtime"
        elif "cost" in normalized or "loss" in normalized:
            metric_key = "cost"

        # Resolve a specific issue (delay reason) if the user references one or "the top issue".
        issue_value: Optional[str] = None
        if action_plan:
            if any(term in normalized for term in ("top issue", "that issue", "biggest issue", "this issue", "worst issue", "main issue")):
                issue_value = self._issue_label(action_plan[0])
            else:
                for item in action_plan:
                    label = self._issue_label(item)
                    if label and label.lower() in normalized:
                        issue_value = label
                        break

        # Resolve a specific production line if referenced ("worst line" -> top line group).
        line_value: Optional[str] = None
        if "line" in normalized:
            line_rows = group_summary.get("production_line") or []
            if any(term in normalized for term in ("worst", "top", "biggest", "highest")) and line_rows:
                line_value = str(line_rows[0].get("value"))
            else:
                for group_row in line_rows:
                    value = str(group_row.get("value") or "")
                    if value and value.lower() in normalized:
                        line_value = value
                        break

        pool = self._row_pool(profile)
        rows: List[Dict[str, Any]] = []
        title = "Top rows by cost impact"

        if issue_value:
            rows = [r for r in pool if str(r.get("delay_reason") or "").lower() == issue_value.lower()]
            title = f"Rows behind {issue_value}"
        elif line_value:
            rows = [r for r in pool if str(r.get("production_line") or "").lower() == line_value.lower()]
            title = f"Rows behind {line_value}"
        else:
            row_key = {
                "defect": "highest_defect_rows",
                "downtime": "highest_downtime_rows",
                "cost": "highest_loss_rows",
                "shortfall": "largest_actual_vs_planned_shortfall_rows",
            }[metric_key]
            rows = list(highest_rows.get(row_key) or [])
            title = {
                "defect": "Top rows by defect count",
                "downtime": "Top rows by downtime",
                "cost": "Top rows by cost impact",
                "shortfall": "Top rows behind production shortfall",
            }[metric_key]

        # Fall back to the metric ranking if the filter found nothing concrete.
        if not rows:
            for key in ("highest_loss_rows", "highest_defect_rows", "highest_downtime_rows", "largest_actual_vs_planned_shortfall_rows"):
                if highest_rows.get(key):
                    rows = list(highest_rows[key])
                    break
        if not rows:
            return None

        rows = sorted(rows, key=lambda r: self._row_sort_value(r, metric_key), reverse=True)

        lines = [title]
        for index, row in enumerate(rows[:5], start=1):
            lines.append("")
            lines.extend(self._format_spreadsheet_row_detail(row, index))

        lines.append("")
        if issue_value:
            closing = (
                f"These are the worst records tied to {issue_value}. Start at the top one, contain it, "
                "and check whether the same asset, line, or shift keeps showing up before making a floor-wide change."
            )
        elif line_value:
            closing = (
                f"These are the heaviest records on {line_value}. If one asset or shift repeats here, treat it as a "
                "focused fix on that line rather than a plant-wide problem."
            )
        else:
            closing = (
                "Start with the rows above because they are the biggest contributors to the issue in the uploaded "
                "spreadsheet. Fix the top one first, then re-check the same metric next shift."
            )
        lines.append(f"**So what does it mean?** {closing}")
        return "\n".join(lines)

    def _format_thorough_narrative(self, processed: Dict[str, Any]) -> Optional[str]:
        """A reasoned, multi-paragraph answer built entirely from computed numbers (no model, no invented stats)."""
        profile = processed.get("full_sheet_profile") or {}
        operational = profile.get("operational_summary") or {}
        action_plan = processed.get("concrete_action_plan") or []
        if not action_plan:
            return None

        planned = operational.get("planned_vs_actual") or {}
        rows = processed.get("rows")

        paragraphs: List[str] = []

        # 1) The big picture.
        big = "Stepping back, the data tells a focused story rather than a plant-wide crisis. "
        if planned:
            big += (
                f"Across {self._format_metric_value(rows)} records, production is running "
                f"{self._format_metric_value(planned.get('average_attainment_pct'))}% of plan, a shortfall of "
                f"{self._format_metric_value(planned.get('shortfall_total'))} units. "
            )
        big += (
            "What stands out is that the lost time, defects, and cost impact are not evenly spread; they pile up on a "
            "small number of repeat issue groups. That is good news, because it means a few targeted fixes move the needle "
            "far more than a broad efficiency program would."
        )
        paragraphs.append(big)

        # 2) The dominant issue, reasoned out.
        top = action_plan[0]
        issue = self._issue_label(top)
        facts = top.get("why_it_matters") or {}
        check = top.get("check_first") or {}
        impact = self._impact_phrase(facts)
        where = self._where_to_look_phrase(check)
        lead = f"The single biggest opportunity is **{issue}**"
        if impact:
            lead += f", which alone accounts for {impact}"
        lead += ". "
        if where:
            lead += (
                f"It keeps tracing back to {where}, which points at a specific, fixable root cause rather than a vague "
                "process problem. Containing that one record is the fastest way to learn whether this is equipment, process, or scheduling."
            )
        paragraphs.append(lead)

        # 3) How the rest relate.
        runners = action_plan[1:3]
        if runners:
            runner_sentences = []
            for item in runners:
                r_issue = self._issue_label(item)
                r_impact = self._impact_phrase(item.get("why_it_matters") or {})
                if r_impact:
                    runner_sentences.append(f"**{r_issue}** ({r_impact})")
                else:
                    runner_sentences.append(f"**{r_issue}**")
            paragraphs.append(
                f"Behind it sit {self._join_natural(runner_sentences)}. These are worth watching, but they are second-order: "
                f"if you chase all three at once you will spread the crew thin and likely fix none of them well. The smarter "
                f"sequence is to resolve {issue} first, confirm the numbers move, then carry the same playbook to the next group."
            )

        # 4) Prioritized advice.
        owner = top.get("owner", "Operations")
        metrics = ", ".join(top.get("metric_to_watch") or []) or "cost impact, downtime, and defect count"
        paragraphs.append(
            f"**So what does it mean?** If I were running the next shift, I would put one owner on {issue} — {owner} — and "
            f"start at the worst record rather than launching a floor-wide review. Contain it, then watch {metrics} on that "
            f"asset over the shift. If those numbers ease off, you have confirmed the root cause and earned the right to scale "
            f"the fix to the next issue. My advice: one issue, one owner, one shift, measured by real movement in the numbers — "
            f"not a broad training push or a generic KPI cleanup."
        )

        return "\n\n".join(paragraphs)

    def _format_operations_overview_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_operations_overview_question(message):
            return None

        processed = self._first_spreadsheet_processed(context)
        if not processed:
            return None

        # Open-ended "what are your thoughts / give me a thorough answer" questions get a thoughtful,
        # grounded narrative (computed from the real numbers) instead of the templated snapshot.
        if self._is_reflective_question(message):
            narrative = self._format_thorough_narrative(processed)
            if narrative:
                return narrative

        profile = processed.get("full_sheet_profile") or {}
        operational = profile.get("operational_summary") or {}
        action_plan = processed.get("concrete_action_plan") or []
        rows = processed.get("rows")

        planned = operational.get("planned_vs_actual") or {}
        if planned:
            lines = [
                "Production is below plan, and the efficiency problem is concentrated around a few repeat issue groups rather than spread evenly across every operation.",
                "",
                "Operational snapshot",
            ]
        else:
            lines = [
                "The uploaded data points to a few concentrated operational signals worth investigating first.",
                "",
                "Operational snapshot",
            ]
        if rows:
            lines.append(f"- **Rows analyzed:** {self._format_metric_value(rows)}")

        if planned:
            lines.append(
                f"- **Overall:** production is below plan by "
                f"{self._format_metric_value(planned.get('shortfall_total'))} units "
                f"({self._format_metric_value(planned.get('average_attainment_pct'))}% attainment)."
            )

        issue_metrics = [
            ("downtime", "Downtime"),
            ("defects", "Defects"),
            ("estimated_loss", "Estimated cost impact"),
            ("vibration", "Vibration"),
        ]
        metric_lines = []
        for key, label in issue_metrics:
            metric = operational.get(key) or {}
            if not metric:
                continue
            metric_lines.append(
                f"- **{label}:** total {self._format_metric_value(metric.get('total'))}, "
                f"average {self._format_metric_value(metric.get('average'))}, "
                f"max {self._format_metric_value(metric.get('max'))}"
            )
        if metric_lines:
            lines.append("")
            lines.append("Key signals")
            lines.extend(metric_lines[:3])

        for counts_key, label in [
            ("delay_reason_counts", "Delay reasons"),
            ("maintenance_status_counts", "Maintenance status"),
            ("priority_counts", "Priority"),
        ]:
            counts = operational.get(counts_key) or {}
            if counts:
                counts_text = ", ".join(
                    f"{name}: {count}" for name, count in list(counts.items())[:5]
                )
                if label in {"Delay reasons", "Maintenance status"}:
                    lines.append(f"- **{label}:** {counts_text}")

        if action_plan:
            lines.append("")
            lines.append("Main correlations to act on")
            for item in action_plan[:3]:
                issue = str(item.get("issue", "Issue")).replace("_", " ")
                facts = item.get("why_it_matters") or {}
                check_first = item.get("check_first") or {}

                lines.append("")
                lines.append(f"**{issue}**")
                signal_bits = []
                if facts.get("total_estimated_cost") is not None:
                    signal_bits.append(f"cost {self._format_metric_value(facts.get('total_estimated_cost'))}")
                if facts.get("total_downtime") is not None:
                    signal_bits.append(f"downtime {self._format_metric_value(facts.get('total_downtime'))}")
                if facts.get("total_defects") is not None:
                    signal_bits.append(f"defects {self._format_metric_value(facts.get('total_defects'))}")
                if signal_bits:
                    lines.append(f"- **Signal:** {', '.join(signal_bits)}")
                compact_check = []
                for key, label in [
                    ("asset_id", "asset"),
                    ("production_line", "line"),
                    ("shift", "shift"),
                    ("maintenance_status", "maintenance"),
                ]:
                    if key in check_first and check_first[key] is not None:
                        compact_check.append(f"{label}: {self._format_metric_value(check_first[key])}")
                if compact_check:
                    lines.append(f"- **Check first:** {', '.join(compact_check)}")
                lines.append(f"- **Owner:** {item.get('owner', 'Operations')}")

        lines.append("")
        lines.append(self._build_overview_meaning(action_plan, planned))
        return "\n".join(lines)

    def _build_overview_meaning(self, action_plan: List[Dict[str, Any]], planned: Dict[str, Any]) -> str:
        """Write the closing summary from whatever issues this sheet actually contains."""
        issues = [self._issue_label(item) for item in action_plan[:3] if self._issue_label(item)]
        top_issue = issues[0] if issues else None
        runners = issues[1:3]

        opening = (
            "Operations are not failing everywhere at once; the file points to a concentrated set of drivers. "
        )
        if planned:
            opening += (
                f"Production is below plan by {self._format_metric_value(planned.get('shortfall_total'))} units, "
                "and the lost time, defects, and cost impact cluster around a few repeat issue groups rather than the whole floor. "
            )
        else:
            opening += "The lost time, defects, and cost impact cluster around a few repeat issue groups rather than the whole floor. "

        if top_issue:
            opening += (
                f"{top_issue.capitalize()} is the heaviest combined signal right now"
            )
            if runners:
                opening += f", with {self._join_natural(runners)} close behind. "
            else:
                opening += ". "
            opening += (
                "That means the fastest efficiency gain is not a broad training push or a vague KPI review; it is a focused "
                "next-shift response on the specific assets, lines, and shifts tied to those issues."
            )
        else:
            opening += (
                "The fastest efficiency gain is a focused response on the specific assets, lines, and shifts tied to the "
                "highest-cost rows rather than a broad, plant-wide push."
            )

        advice = ""
        if top_issue:
            advice = (
                f" My advice: start with {top_issue}, put one owner on it, fix the worst record first, and watch whether "
                "cost impact, downtime, and defects drop on that asset before moving to the next issue."
            )

        return f"**So what does it mean?** {opening}{advice}"

    def _row_key_from_text(self, text: str) -> str:
        normalized = text.lower()
        if "defect" in normalized:
            return "highest_defect_rows"
        if "downtime" in normalized:
            return "highest_downtime_rows"
        if "cost" in normalized or "loss" in normalized:
            return "highest_loss_rows"
        if "shortfall" in normalized or "gap" in normalized or ("planned" in normalized and "actual" in normalized):
            return "largest_actual_vs_planned_shortfall_rows"
        return "largest_actual_vs_planned_shortfall_rows"

    def _last_user_question(self, context: Dict[str, Any]) -> str:
        history = context.get("conversation_history") or []
        for item in reversed(history):
            if item.get("role") == "user":
                return str(item.get("content", ""))
        return ""

    def _format_asset_frequency_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_asset_frequency_question(message):
            return None

        processed = self._first_spreadsheet_processed(context)
        if not processed:
            return None

        profile = processed.get("full_sheet_profile") or {}
        highest_rows = profile.get("highest_risk_rows") or {}
        row_key = self._row_key_from_text(message)
        if row_key == "largest_actual_vs_planned_shortfall_rows":
            row_key = self._row_key_from_text(self._last_user_question(context))

        rows = highest_rows.get(row_key) or []
        if not rows:
            return None

        counts: Dict[str, Dict[str, Any]] = {}
        for row in rows:
            asset_id = str(row.get("asset_id") or "Unknown")
            asset = counts.setdefault(
                asset_id,
                {
                    "count": 0,
                    "asset_name": row.get("asset_name"),
                    "production_lines": set(),
                    "shifts": set(),
                    "total_gap": 0,
                    "total_downtime": 0,
                    "total_defects": 0,
                    "total_cost": 0,
                },
            )
            asset["count"] += 1
            if row.get("production_line"):
                asset["production_lines"].add(row.get("production_line"))
            if row.get("shift"):
                asset["shifts"].add(row.get("shift"))
            asset["total_gap"] += float(row.get("_actual_gap") or 0)
            asset["total_downtime"] += float(row.get("downtime_minutes") or row.get("downtime") or 0)
            asset["total_defects"] += float(row.get("defect_count") or 0)
            asset["total_cost"] += float(row.get("estimated_cost_impact_usd") or row.get("estimated_loss") or 0)

        ranked = sorted(
            counts.items(),
            key=lambda item: (
                item[1]["count"],
                item[1]["total_gap"],
                item[1]["total_cost"],
                item[1]["total_downtime"],
            ),
            reverse=True,
        )

        title_lookup = {
            "largest_actual_vs_planned_shortfall_rows": "production shortfall rows",
            "highest_defect_rows": "highest-defect rows",
            "highest_downtime_rows": "highest-downtime rows",
            "highest_loss_rows": "highest-cost rows",
        }
        lines = [f"Asset frequency in the {title_lookup.get(row_key, 'selected rows')}"]
        for asset_id, details in ranked[:5]:
            lines.append("")
            lines.append(f"**{asset_id}**")
            if details.get("asset_name"):
                lines.append(f"- **Asset name:** {details['asset_name']}")
            lines.append(f"- **Rows represented:** {self._format_metric_value(details['count'])}")
            if details["production_lines"]:
                lines.append(f"- **Production line(s):** {', '.join(sorted(map(str, details['production_lines'])))}")
            if details["shifts"]:
                lines.append(f"- **Shift(s):** {', '.join(sorted(map(str, details['shifts'])))}")
            if details["total_gap"]:
                lines.append(f"- **Total unit gap:** {self._format_metric_value(details['total_gap'])}")
            if details["total_downtime"]:
                lines.append(f"- **Total downtime:** {self._format_metric_value(details['total_downtime'])}")
            if details["total_defects"]:
                lines.append(f"- **Total defects:** {self._format_metric_value(details['total_defects'])}")
            if details["total_cost"]:
                lines.append(f"- **Estimated cost impact:** {self._format_metric_value(details['total_cost'])}")

        lines.append("")
        lines.append(
            "**So what does it mean?** Use this to decide whether the issue is asset-specific or spread across multiple assets. "
            "If one asset dominates the selected rows, inspect that asset first before launching a broad process review."
        )
        return "\n".join(lines)

    def _select_rows_for_metric(self, profile: Dict[str, Any], message: str) -> Tuple[List[Dict[str, Any]], str]:
        highest_rows = profile.get("highest_risk_rows") or {}
        normalized = message.lower()
        if "defect" in normalized:
            return list(highest_rows.get("highest_defect_rows") or []), "defect"
        if "downtime" in normalized:
            return list(highest_rows.get("highest_downtime_rows") or []), "downtime"
        if "cost" in normalized or "loss" in normalized:
            return list(highest_rows.get("highest_loss_rows") or []), "cost"
        if "shortfall" in normalized or "gap" in normalized or "planned" in normalized:
            return list(highest_rows.get("largest_actual_vs_planned_shortfall_rows") or []), "shortfall"
        return self._row_pool(profile), "cost"

    def _dominant_value(self, rows: List[Dict[str, Any]], key: str) -> Optional[Tuple[str, int]]:
        counts: Dict[str, int] = {}
        for row in rows:
            value = row.get(key)
            if value is None or str(value).strip() == "":
                continue
            counts[str(value)] = counts.get(str(value), 0) + 1
        if not counts:
            return None
        top_value, top_count = max(counts.items(), key=lambda kv: kv[1])
        return top_value, top_count

    def _format_common_pattern_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_common_pattern_question(message):
            return None

        processed = self._first_spreadsheet_processed(context)
        if not processed:
            return None

        profile = processed.get("full_sheet_profile") or {}
        rows, _ = self._select_rows_for_metric(profile, message)
        if not rows:
            rows = self._row_pool(profile)
        if not rows:
            return None

        total = len(rows)
        shared_bits: List[str] = []
        for key, label in [
            ("delay_reason", "delay reason"),
            ("asset_id", "asset"),
            ("asset_name", None),
            ("production_line", "production line"),
            ("shift", "shift"),
            ("maintenance_status", "maintenance status"),
            ("priority", "priority"),
        ]:
            dominant = self._dominant_value(rows, key)
            if not dominant:
                continue
            value, count = dominant
            if count <= 1:
                continue
            if key == "asset_name" and any("asset" in b for b in shared_bits):
                continue
            descriptor = f"{label} **{value}**" if label else f"**{value}**"
            if count == total:
                shared_bits.append(f"every one of them shares {descriptor}")
            else:
                shared_bits.append(f"{count} of {total} share {descriptor}")

        if not shared_bits:
            return None

        lead = (
            "These rows are not random; they line up tightly: "
            + self._join_natural(shared_bits[:4])
            + "."
        )

        # Pull a concrete takeaway from the strongest shared dimension.
        asset_dom = self._dominant_value(rows, "asset_id")
        line_dom = self._dominant_value(rows, "production_line")
        shift_dom = self._dominant_value(rows, "shift")
        focus_bits = []
        if asset_dom and asset_dom[1] > 1:
            focus_bits.append(f"asset {asset_dom[0]}")
        if line_dom and line_dom[1] > 1:
            focus_bits.append(line_dom[0])
        if shift_dom and shift_dom[1] > 1:
            focus_bits.append(f"the {shift_dom[0]} shift")
        focus = self._join_natural(focus_bits)

        meaning = (
            "**So what does it mean?** This is the opposite of a plant-wide problem. "
        )
        if focus:
            meaning += (
                f"The damage keeps coming back to {focus}, so that is a concentrated fix rather than a broad initiative. "
                "Put one owner on it, work the worst record first, and watch whether the numbers ease off before touching anything else."
            )
        else:
            meaning += (
                "The same handful of conditions repeat, so treat it as a focused fix on those records rather than a broad initiative."
            )
        return f"{lead}\n\n{meaning}"

    def _format_projection_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_projection_question(message):
            return None

        processed = self._first_spreadsheet_processed(context)
        if not processed:
            return None

        action_plan = processed.get("concrete_action_plan") or []
        if not action_plan:
            return None

        total_cost = 0.0
        total_downtime = 0.0
        total_defects = 0.0
        issue_names: List[str] = []
        for item in action_plan[:3]:
            facts = item.get("why_it_matters") or {}
            total_cost += float(facts.get("total_estimated_cost") or 0)
            total_downtime += float(facts.get("total_downtime") or 0)
            total_defects += float(facts.get("total_defects") or 0)
            label = self._issue_label(item)
            if label:
                issue_names.append(label)

        if not (total_cost or total_downtime or total_defects):
            return None

        impact_bits = []
        if total_cost:
            impact_bits.append(f"about ${self._format_metric_value(total_cost)} in estimated cost impact")
        if total_downtime:
            impact_bits.append(f"{self._format_metric_value(total_downtime)} minutes of downtime")
        if total_defects:
            impact_bits.append(f"{self._format_metric_value(total_defects)} defects")
        impact = self._join_natural(impact_bits)
        issues = self._join_natural([f"**{name}**" for name in issue_names])

        paragraphs = [
            f"If you work through the top issues in the plan ({issues}), you are going after the largest measured losses in "
            f"the file, not guesswork. Together those issue groups carry {impact}. That is the pool of loss you are actually "
            "targeting — clear it down and the shortfall, lost time, and quality damage should follow."
        ]
        paragraphs.append(
            "I want to be honest about the numbers though: the spreadsheet shows the cost and time tied to these issues, "
            "not a guaranteed recovery. Realistically you would not erase 100% of it on the first pass, but even containing "
            "the worst records on each issue removes the biggest single chunks of that total, and the rest of the floor is "
            "already running closer to plan."
        )
        owner = action_plan[0].get("owner", "Operations")
        top_issue = self._issue_label(action_plan[0])
        if "checklist" in message.lower():
            paragraphs.append(
                f"**So what is the goal?** Run the checklist on one issue with one owner ({owner}), prove the numbers move "
                f"on that worst record, then scale to the next issue. Success means lower cost impact, downtime, and "
                f"defects on the targeted asset — not completing paperwork. If those metrics improve by shift end, you "
                f"earned the right to widen the fix; if not, escalate before spreading effort across the floor."
            )
        else:
            paragraphs.append(
                f"**So what does it mean?** Treat the {self._format_metric_value(total_cost)} as the prize, not a promise. Start "
                f"with {top_issue} under {owner}, measure the actual drop in cost impact, downtime, and defects on that asset, and "
                "use that real result to project the rest. That way the savings you report are earned from the data, not assumed."
            )
        return "\n\n".join(paragraphs)

    def _format_unavailable_metric_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        processed = self._first_spreadsheet_processed(context)
        if not processed:
            return None

        columns = [str(column) for column in processed.get("column_names") or []]
        lower_columns = " ".join(columns).lower()
        normalized = message.lower()
        interpreted = context.get("interpreted_intent") or {}
        parsed_missing = interpreted.get("missing_fields") if isinstance(interpreted, dict) else []
        missing = [str(field) for field in parsed_missing or [] if str(field).strip()]
        unavailable_groups = {
            "damage": ("damage", "damages", "damage cost"),
            "safety": ("safety", "incident", "injury"),
            "customer satisfaction": ("customer satisfaction", "customer complaints", "complaints"),
            "shipping": ("shipping", "delivery", "supplier", "lead time"),
            "staffing": ("staffing", "labor", "headcount", "turnover"),
            "energy": ("energy", "power usage", "electricity"),
            "compliance": ("compliance", "audit", "regulatory"),
        }
        for label, terms in unavailable_groups.items():
            if any(term in normalized for term in terms) and not any(term in lower_columns for term in terms):
                missing.append(label)
        missing = list(dict.fromkeys(missing))

        if not missing:
            return None

        available = []
        for keyword, label in [
            ("cost", "cost impact"),
            ("loss", "estimated loss"),
            ("downtime", "downtime"),
            ("defect", "defects"),
            ("planned", "planned units"),
            ("actual", "actual units"),
            ("asset", "asset"),
            ("line", "production line"),
            ("shift", "shift"),
            ("delay", "delay reason"),
        ]:
            if keyword in lower_columns and label not in available:
                available.append(label)

        available_text = self._join_natural(available[:8]) if available else "the uploaded columns"
        missing_text = self._join_natural(missing)
        return (
            f"I can't answer the **{missing_text}** part from this spreadsheet because I don't see that field in the uploaded columns. "
            f"What I can analyze from this file is {available_text}.\n\n"
            "If you want, I can answer the closest available version of the question using cost impact, downtime, defects, "
            "delay reason, assets, lines, and shifts."
        )

    def _format_checklist_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_checklist_question(message):
            return None

        processed = self._first_spreadsheet_processed(context)
        if not processed:
            return None

        action_plan = processed.get("concrete_action_plan") or []
        if not action_plan:
            return None

        matched = [item for item in action_plan if self._action_plan_matches_message(item, message)]
        item = (matched or action_plan)[0]
        issue = self._issue_label(item)
        check = item.get("check_first") or {}
        owner = item.get("owner", "Operations")
        action = (item.get("first_next_shift_action") or "").strip()
        metrics = item.get("metric_to_watch") or []

        lines = [f"Next-shift checklist for **{issue}** ({owner}):", ""]
        step = 1

        where = self._where_to_look_phrase(check)
        if where:
            lines.append(f"{step}. Go to {where} first — that is the worst record behind this issue.")
            step += 1
        if check.get("priority"):
            lines.append(f"{step}. Confirm the high-priority items are contained before anything else.")
            step += 1
        if action:
            lines.append(f"{step}. {action}")
            step += 1
        if metrics:
            metric_text = ", ".join(metrics)
            lines.append(f"{step}. Before clocking out, log where these moved: {metric_text}.")
            step += 1
        lines.append(f"{step}. If the numbers improved, repeat this on the next-biggest issue; if not, escalate to {owner}.")

        lines.append("")
        lines.append(
            f"**So what does it mean?** Keep it simple for the floor: one owner ({owner}), one issue ({issue}), "
            "work the worst record first, and check the numbers at the end of the shift before widening the effort."
        )
        return "\n".join(lines)

    def _action_plan_matches_message(self, item: Dict[str, Any], message: str) -> bool:
        normalized = message.lower()
        issue = str(item.get("issue", "")).lower()
        owner = str(item.get("owner", "")).lower()
        combined = f"{issue} {owner}"

        keyword_groups = {
            "quality": ("quality", "defect", "hold"),
            "maintenance": ("maintenance", "inspection", "equipment"),
            "sensor": ("sensor", "vibration"),
            "downtime": ("downtime", "wait"),
            "cost": ("cost", "loss", "impact"),
            "delay": ("delay", "reason"),
            "material": ("material", "shortage"),
            "changeover": ("changeover", "setup"),
            "priority": ("priority", "high", "medium"),
        }

        for user_keyword, issue_keywords in keyword_groups.items():
            if user_keyword in normalized and any(keyword in combined for keyword in issue_keywords):
                return True
        return False

    def _format_action_plan_item(self, item: Dict[str, Any], compact: bool = False) -> List[str]:
        issue = str(item.get("issue", "Issue")).replace("_", " ")
        facts = item.get("why_it_matters") or {}
        check_first = item.get("check_first") or {}
        metrics = ", ".join(item.get("metric_to_watch") or [])

        lines = [f"**{issue}**"]
        signal_bits = []
        if facts.get("total_estimated_cost") is not None:
            signal_bits.append(f"cost {self._format_metric_value(facts.get('total_estimated_cost'))}")
        if facts.get("total_downtime") is not None:
            signal_bits.append(f"downtime {self._format_metric_value(facts.get('total_downtime'))}")
        if facts.get("total_defects") is not None:
            signal_bits.append(f"defects {self._format_metric_value(facts.get('total_defects'))}")
        if facts.get("rows") is not None:
            signal_bits.append(f"rows {self._format_metric_value(facts.get('rows'))}")
        if signal_bits:
            lines.append(f"- **Why it matters:** {', '.join(signal_bits)}")

        lines.append(f"- **Owner:** {item.get('owner', 'Operations')}")

        if compact:
            compact_check = []
            for key, label in [
                ("asset_id", "asset"),
                ("asset_name", "asset name"),
                ("production_line", "line"),
                ("shift", "shift"),
                ("maintenance_status", "maintenance"),
                ("priority", "priority"),
            ]:
                if key in check_first and check_first[key] is not None:
                    compact_check.append(f"{label}: {self._format_metric_value(check_first[key])}")
            if compact_check:
                lines.append(f"- **Check first:** {', '.join(compact_check)}")
        else:
            lines.append("- **Check first:**")
            lines.extend(self._format_check_first_lines(check_first) or ["  - **Starting point:** highest-impact row in this issue group"])

        lines.append(f"- **First next-shift action:** {item.get('first_next_shift_action')}")
        if metrics:
            lines.append(f"- **Metric to watch:** {metrics}")
        return lines

    def _issue_label(self, item: Dict[str, Any]) -> str:
        raw = str(item.get("issue", "")).split("=")[-1].strip()
        return raw or "the top issue"

    def _join_natural(self, parts: List[str]) -> str:
        parts = [part for part in parts if part]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        if len(parts) == 2:
            return f"{parts[0]} and {parts[1]}"
        return f"{', '.join(parts[:-1])}, and {parts[-1]}"

    def _impact_phrase(self, facts: Dict[str, Any]) -> str:
        bits = []
        if facts.get("total_estimated_cost") is not None:
            bits.append(f"about ${self._format_metric_value(facts.get('total_estimated_cost'))} in estimated cost impact")
        if facts.get("total_downtime") is not None:
            bits.append(f"{self._format_metric_value(facts.get('total_downtime'))} minutes of downtime")
        if facts.get("total_defects") is not None:
            bits.append(f"{self._format_metric_value(facts.get('total_defects'))} defects")
        return self._join_natural(bits)

    def _where_to_look_phrase(self, check: Dict[str, Any]) -> str:
        asset_id = check.get("asset_id")
        asset_name = check.get("asset_name")
        if asset_name and asset_id:
            asset = f"{asset_name} ({asset_id})"
        else:
            asset = asset_name or asset_id
        bits = []
        if asset:
            bits.append(asset)
        if check.get("production_line"):
            bits.append(f"on {check.get('production_line')}")
        if check.get("shift"):
            bits.append(f"during the {check.get('shift')} shift")
        location = " ".join(bits)
        status = check.get("maintenance_status")
        if location and status:
            return f"{location}, currently flagged \"{status}\""
        return location or ""

    def _format_action_plan_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_action_plan_question(message):
            return None

        processed = self._first_spreadsheet_processed(context)
        if not processed:
            return None

        action_plan = processed.get("concrete_action_plan") or []
        if not action_plan:
            return None

        matched = [item for item in action_plan if self._action_plan_matches_message(item, message)]
        selected = matched or action_plan
        if not selected:
            return None

        top = selected[0]
        issue = self._issue_label(top)
        facts = top.get("why_it_matters") or {}
        check = top.get("check_first") or {}
        owner = top.get("owner", "Operations")
        action = (top.get("first_next_shift_action") or "").strip()

        paragraphs: List[str] = []

        impact = self._impact_phrase(facts)
        rows = facts.get("rows")
        rows_phrase = f" across {self._format_metric_value(rows)} records" if rows is not None else ""
        lead = f"Tackle **{issue}** first."
        if impact:
            lead += f" It is the heaviest single drain in the data right now, tied to {impact}{rows_phrase}, so this is where the next shift should put its first hours."
        else:
            lead += f" It shows up the most across the file{rows_phrase}, so it is the right place to start the next shift."
        paragraphs.append(lead)

        where = self._where_to_look_phrase(check)
        if where:
            paragraphs.append(
                f"Send {owner} straight to {where}. That is the worst single record behind this issue, "
                f"so it is the fastest way to confirm whether the problem is the equipment, the process, or the schedule."
            )
        elif action:
            paragraphs.append(f"Put {owner} on it as the single owner so it does not get lost between teams.")

        if action:
            paragraphs.append(action)

        runners = [self._issue_label(item) for item in selected[1:3]]
        runner_phrase = self._join_natural(runners)
        meaning = (
            f"**So what does it mean?** Do not split the crew across everything at once. {issue.capitalize()} is the one issue "
            f"worth owning on the next shift, because it carries the most cost, lost time, and quality damage combined."
        )
        if runner_phrase:
            meaning += (
                f" Keep {runner_phrase} on the radar, but only move there once {issue} is contained. "
            )
        else:
            meaning += " "
        meaning += (
            "Fix it, watch whether cost impact, downtime, and defects drop on that asset, and if they do, "
            "run the exact same play on the next biggest issue. My advice: one issue, one owner, one shift, then re-check the numbers."
        )
        paragraphs.append(meaning)

        return "\n\n".join(paragraphs)

    def _group_key_from_message(self, message: str, group_summary: Dict[str, Any]) -> Optional[str]:
        normalized = message.lower()
        # Asset is the most specific grouping, so honor it first even if "line" also appears
        # (e.g. "which asset on the worst line is driving this?").
        if any(term in normalized for term in ("asset", "machine", "equipment")):
            if "asset_id" in group_summary:
                return "asset_id"
        if "shift" in normalized or "day" in normalized or "night" in normalized:
            return "shift" if "shift" in group_summary else None
        if "line" in normalized or "production" in normalized:
            return "production_line" if "production_line" in group_summary else None
        if "facility" in normalized or "site" in normalized:
            return "facility" if "facility" in group_summary else None
        for key in ("production_line", "asset_id", "shift", "facility"):
            if key in group_summary:
                return key
        return None

    def _format_group_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_group_question(message):
            return None

        processed = self._first_spreadsheet_processed(context)
        if not processed:
            return None

        profile = processed.get("full_sheet_profile") or {}
        group_summary = profile.get("group_summary") or {}
        group_key = self._group_key_from_message(message, group_summary)
        if not group_key:
            return None

        rows = group_summary.get(group_key) or []
        if not rows:
            return None

        label = group_key.replace("_", " ")
        lines = [f"Here is the breakdown by {label}."]
        for row in rows[:6]:
            lines.append("")
            lines.append(f"**{row.get('value')}**")
            lines.append(f"- **Rows:** {self._format_metric_value(row.get('rows'))}")
            for key, metric_label in [
                ("estimated_loss_total", "Cost impact"),
                ("downtime_total", "Downtime"),
                ("defect_total", "Defects"),
                ("actual_shortfall_total", "Production shortfall"),
                ("attainment_pct_avg", "Average attainment"),
                ("vibration_avg", "Average vibration"),
            ]:
                if row.get(key) is not None:
                    suffix = "%" if key == "attainment_pct_avg" else ""
                    lines.append(f"- **{metric_label}:** {self._format_metric_value(row.get(key))}{suffix}")

        lines.append("")
        lines.append(
            "**So what does it mean?** The top group above is where the supervisor should look first. If the same "
            "line, asset, or shift is repeatedly high on cost, downtime, or defects, treat it as a focused operating "
            "problem instead of a plant-wide issue."
        )
        return "\n".join(lines)

    def _format_delay_ranking_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_delay_ranking_question(message):
            return None

        processed = self._first_spreadsheet_processed(context)
        if not processed:
            return None

        action_plan = processed.get("concrete_action_plan") or []
        delay_items = [
            item for item in action_plan
            if str(item.get("issue", "")).lower().startswith("delay_reason=")
        ]
        if not delay_items:
            delay_items = action_plan
        if not delay_items:
            return None

        def sort_key(item: Dict[str, Any]) -> Tuple[float, float, float]:
            facts = item.get("why_it_matters") or {}
            return (
                float(facts.get("total_estimated_cost") or 0),
                float(facts.get("total_downtime") or 0),
                float(facts.get("total_defects") or 0),
            )

        ranked = sorted(delay_items, key=sort_key, reverse=True)
        top = ranked[0]

        lines = ["Delay reasons ranked by total cost impact"]
        for index, item in enumerate(ranked[:5], start=1):
            issue = self._issue_label(item)
            facts = item.get("why_it_matters") or {}
            signal_bits = []
            if facts.get("total_estimated_cost") is not None:
                signal_bits.append(f"cost ${self._format_metric_value(facts.get('total_estimated_cost'))}")
            if facts.get("total_downtime") is not None:
                signal_bits.append(f"downtime {self._format_metric_value(facts.get('total_downtime'))}")
            if facts.get("total_defects") is not None:
                signal_bits.append(f"defects {self._format_metric_value(facts.get('total_defects'))}")
            if facts.get("rows") is not None:
                signal_bits.append(f"rows {self._format_metric_value(facts.get('rows'))}")
            lines.append(f"{index}. **{issue}:** {', '.join(signal_bits)}")

        top_issue = self._issue_label(top)
        top_facts = top.get("why_it_matters") or {}
        top_check = top.get("check_first") or {}
        top_impact = self._impact_phrase(top_facts)
        top_where = self._where_to_look_phrase(top_check)
        owner = top.get("owner", "Operations")
        action = top.get("first_next_shift_action")

        lines.append("")
        if top_impact:
            lines.append(
                f"The top driver is **{top_issue}** because it carries {top_impact}. "
                "That is the largest combined cost, downtime, and quality signal in the delay-reason list."
            )
        if top_where:
            lines.append(
                f"The first place to check is {top_where}. Put {owner} on that record first, because it is the clearest "
                "starting point for confirming whether the driver is equipment, process, scheduling, or quality containment."
            )
        if action:
            lines.append(str(action))

        lines.append("")
        lines.append(
            f"**So what does it mean?** Start with {top_issue}, not a broad process review. The ranking shows where the "
            "money and time are actually going, so the next shift should contain the top driver first, measure whether cost "
            "impact, downtime, and defects move, then work down the ranked list."
        )
        return "\n\n".join(lines)

    def _format_issue_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_issue_question(message):
            return None

        processed = self._first_spreadsheet_processed(context)
        if not processed:
            return None

        action_plan = processed.get("concrete_action_plan") or []
        if not action_plan:
            return None

        matched = [item for item in action_plan if self._action_plan_matches_message(item, message)]
        if not matched:
            return None

        top = matched[0]
        issue = self._issue_label(top)
        facts = top.get("why_it_matters") or {}
        check = top.get("check_first") or {}
        owner = top.get("owner", "Operations")
        action = (top.get("first_next_shift_action") or "").strip()

        paragraphs: List[str] = []

        impact = self._impact_phrase(facts)
        rows = facts.get("rows")
        rows_phrase = f" over {self._format_metric_value(rows)} records" if rows is not None else ""
        if impact:
            paragraphs.append(
                f"**{issue}** is doing real damage{rows_phrase}: {impact}. That combination is why it stands out "
                f"from everything else in the file rather than reading like a normal day-to-day wobble."
            )
        else:
            paragraphs.append(
                f"**{issue}** is the pattern worth your attention{rows_phrase}. It keeps recurring instead of being a one-off."
            )

        where = self._where_to_look_phrase(check)
        if where:
            paragraphs.append(
                f"The worst single record points at {where}. Start there with {owner}; it is the clearest example of the "
                f"problem and the quickest way to tell whether you are dealing with equipment wear, a process gap, or a scheduling issue."
            )

        if action:
            paragraphs.append(action)

        meaning = (
            f"**So what does it mean?** {issue.capitalize()} is not a vague KPI to monitor, it is a specific, repeatable "
            f"problem you can act on. Hand it to {owner}, fix the worst record first, and watch cost impact, downtime, and "
            f"defect count on that asset over the next shift. If those numbers ease off, you have the right root cause and can "
            f"roll the same fix out wider. My advice: stay on this one issue until the numbers actually move before chasing anything else."
        )
        paragraphs.append(meaning)

        return "\n\n".join(paragraphs)

    def _parse_finding_parts(self, finding: str) -> Dict[str, str]:
        parts = [part.strip(" .") for part in finding.split("|")]
        parsed: Dict[str, str] = {"title": parts[0].replace("Numeric comparison:", "").strip()}
        for part in parts[1:]:
            if "=" not in part:
                continue
            key, value = part.split("=", 1)
            parsed[key.strip()] = value.strip()
        return parsed

    def _format_numeric_comparison_response(self, message: str, context: Dict[str, Any]) -> Optional[str]:
        if not self._is_numeric_comparison_question(message):
            return None

        spreadsheets = [
            source for source in context.get("data_sources", [])
            if (source.get("processed_data") or {}).get("type") == "spreadsheet"
        ]
        if not spreadsheets:
            return None

        processed = spreadsheets[0].get("processed_data") or {}
        comparisons = processed.get("numeric_comparisons") or []
        if not comparisons:
            return None

        normalized = message.lower()
        selected = comparisons
        if "defect" in normalized and "planned" in normalized:
            selected = [finding for finding in comparisons if "defect_count vs planned_units" in finding]
        elif "actual" in normalized and "planned" in normalized:
            selected = [finding for finding in comparisons if "actual_units vs planned_units" in finding]
        elif ("cost" in normalized or "loss" in normalized) and "downtime" in normalized:
            selected = [finding for finding in comparisons if "cost impact vs downtime" in finding]
        elif "vibration" in normalized and "defect" in normalized:
            selected = [finding for finding in comparisons if "vibration vs defects" in finding]

        if not selected:
            selected = comparisons[:2]

        parsed_findings = [self._parse_finding_parts(finding) for finding in selected[:4]]
        lines = ["### Direct spreadsheet comparison"]
        for parsed in parsed_findings:
            title = parsed.pop("title", "Comparison")
            lines.append(f"\n**{title}**")
            for key, value in parsed.items():
                pretty_key = key.replace("_", " ").title()
                lines.append(f"- **{pretty_key}:** {value}")

        lines.append(
            "\n**How to read this:** this uses only the uploaded spreadsheet columns and computed totals. "
            "It does not assume targets, baselines, training levels, logistics KPIs, or typical performance."
        )
        return "\n".join(lines)

    def _route_deterministic(self, message: str, context: Dict[str, Any]) -> Optional[Tuple[str, str]]:
        routes = [
            (self._format_unavailable_metric_response, "spreadsheet_unavailable_metric"),
            (self._format_cross_file_trends_response, "spreadsheet_cross_file_trends"),
            (self._format_shared_asset_comparison_response, "spreadsheet_asset_comparison"),
            (self._format_consultant_advisory_response, "consultant_advisory"),
            (self._format_multi_spreadsheet_response, "spreadsheet_multi_file"),
            (self._format_projection_response, "spreadsheet_projection"),
            (self._format_common_pattern_response, "spreadsheet_common_pattern"),
            (self._format_checklist_response, "spreadsheet_checklist"),
            (self._format_row_drilldown_response, "spreadsheet_row_drilldown"),
            (self._format_asset_frequency_response, "spreadsheet_asset_frequency"),
            (self._format_action_plan_response, "spreadsheet_action_plan"),
            (self._format_group_response, "spreadsheet_group_breakdown"),
            (self._format_delay_ranking_response, "spreadsheet_delay_ranking"),
            (self._format_issue_response, "spreadsheet_issue_explanation"),
            (self._format_numeric_comparison_response, "spreadsheet_comparison"),
            (self._format_operations_overview_response, "spreadsheet_overview"),
        ]
        for handler, response_type in routes:
            content = handler(message, context)
            if content:
                return content, response_type
        return None

    def _is_followup_message(self, message: str) -> bool:
        normalized = message.strip().lower()
        if len(normalized.split()) <= 6:
            return True
        referential = (
            "that", "this", "it", "them", "those", "these", "the issue", "the same",
            "next step", "what about", "and what", "ok ", "okay", "what now", "go deeper",
            "more", "expand", "drill", "again", "instead",
            "reanswer", "re-answer", "answer again", "answer the question", "answer my question",
            "answer that", "try again", "now that", "with the data", "with uploaded", "with the file",
            "with the spreadsheet", "use the data", "use the file", "based on the data",
            "now answer", "the original question", "same question", "redo",
        )
        return any(term in normalized for term in referential)

    def _contextual_message(self, message: str, context: Dict[str, Any]) -> str:
        """Blend the current message with recent session context so short follow-ups still route."""
        history = context.get("conversation_history") or []
        prior_user_turns = [
            str(item.get("content", "")).strip()
            for item in history
            if item.get("role") == "user" and str(item.get("content", "")).strip()
        ]
        prior_user_turns = [turn for turn in prior_user_turns if turn != message.strip()]
        recent_users = prior_user_turns[-2:]

        assistant_turns = [
            str(item.get("content", ""))
            for item in history
            if item.get("role") == "assistant" and str(item.get("content", "")).strip()
        ]
        topic_hint = ""
        if assistant_turns:
            topic_hint = " ".join(self._extract_response_topics(assistant_turns[-1]))

        blended = " ".join([message] + recent_users + ([topic_hint] if topic_hint else []))
        return blended.strip()

    def _deterministic_spreadsheet_response(self, message: str, context: Dict[str, Any]) -> Optional[Dict[str, Any]]:
        routed = self._route_deterministic(message, context)

        if not routed and self._first_spreadsheet_processed(context) and self._is_followup_message(message):
            enriched = self._contextual_message(message, context)
            if enriched and enriched != message:
                routed = self._route_deterministic(enriched, context)

        if not routed:
            return None

        content, response_type = routed
        return {
            "response_text": content,
            "predicted_root_cause": content,
            "risk_score": None,
            "target_kanban_tasks": [],
            "remediation_commands": [],
            "compliance_implications": None,
            "model_version": "computed-spreadsheet-profile",
            "confidence": 0.95,
            "response_type": response_type,
            "follow_up_questions": self._generate_chat_follow_ups(message, context, content, response_type),
        }

    def _extract_response_topics(self, response_text: str) -> List[str]:
        ignored_topics = {
            "rows analyzed",
            "rows",
            "planned units",
            "actual units",
            "performance snapshot",
            "operational snapshot",
            "key signals",
            "main correlations",
            "main correlations to act on",
            "so what does it mean?",
            "high-level answer",
            "operations rundown",
            "cost impact",
            "estimated cost impact",
            "downtime",
            "defects",
            "defect count",
            "production shortfall",
            "average attainment",
            "attainment",
            "average vibration",
            "vibration",
            "signal",
            "owner",
            "check first",
            "why it matters",
            "first next-shift action",
            "metric to watch",
            "analysis",
            "recommendations",
        }
        topics: List[str] = []
        patterns = [
            r"(?im)^#{1,4}\s*([^:\n]+)",
            r"(?im)^for\s+([^:\n]+):",
            r"(?im)^[-*]\s*\*\*([^*]+)\*\*",
            r"(?im)^\*\*([^*]+)\*\*$",
            r"delay_reason=([^|.\n]+)",
        ]
        for pattern in patterns:
            for match in re.findall(pattern, response_text):
                topic = str(match).strip(" -:*")
                normalized_topic = topic.lower()
                if normalized_topic in ignored_topics:
                    continue
                if normalized_topic.startswith(("rows ", "planned ", "actual ", "overall")):
                    continue
                if 3 <= len(topic) <= 60 and topic not in topics:
                    topics.append(topic)
        return topics[:3]

    def _generate_chat_follow_ups(
        self,
        message: str,
        context: Dict[str, Any],
        response_text: str = "",
        response_type: Optional[str] = None,
    ) -> List[str]:
        from app.services.session_suggested_questions import generate_suggested_questions

        data_sources = context.get("data_sources", [])
        if not data_sources:
            return []

        generated = generate_suggested_questions(
            data_sources,
            context.get("multi_spreadsheet_analysis"),
            exclude=[message.strip()],
            limit=6,
        )
        questions = generated.get("questions") or []
        if not questions:
            return []

        # Keep follow-ups adjacent to what was just answered, but still data-driven.
        legacy_map = {
            "consultant_advisory": ["cross_file_trends", "hidden_bottleneck", "asset_trend"],
            "spreadsheet_cross_file_trends": ["asset_trend", "cross_source_growth", "seasonal_prep"],
            "spreadsheet_asset_comparison": ["cross_file_trends", "hidden_bottleneck", "seasonal_prep"],
            "spreadsheet_multi_file": ["cross_file_trends", "cross_source_growth", "asset_trend"],
            "spreadsheet_action_plan": ["next_shift", "production_drilldown", "signal_hunt"],
            "spreadsheet_overview": ["cross_source_growth", "executive_rundown", "hidden_bottleneck"],
        }
        preferred = legacy_map.get(response_type or "", [])
        items = generated.get("items") or []
        by_category = {item["category"]: item["question"] for item in items}

        ordered: List[str] = []
        for category in preferred:
            question = by_category.get(category)
            if question and question not in ordered:
                ordered.append(question)
        for question in questions:
            if question not in ordered:
                ordered.append(question)
            if len(ordered) >= 3:
                break
        # Final de-dupe preserving order
        deduped: List[str] = []
        seen: Set[str] = set()
        for question in ordered:
            key = question.strip().lower()
            if key in seen:
                continue
            seen.add(key)
            deduped.append(question)
        return deduped[:3]

        return deduped[:3]

    def _build_multi_file_gemma_block(self, context: Dict[str, Any]) -> List[str]:
        """Compact cross-file summary — always safe to include for 10+ uploads."""
        multi = context.get("multi_spreadsheet_analysis") or {}
        if multi.get("file_count", 0) < 2:
            return []

        lines = [
            "Cross-file analysis (covers ALL uploaded spreadsheets — prefer this for trends and comparisons):",
            multi.get("narrative_summary", ""),
        ]
        yoy = multi.get("yoy_trends") or {}
        for row in yoy.get("metrics") or []:
            year_bits = [
                f"{year}: {self._format_metric_value(value)}"
                for year, value in zip(row.get("years") or [], row.get("values") or [])
                if value is not None
            ]
            if year_bits:
                lines.append(
                    f"- {row.get('label')}: {row.get('direction')} | " + " → ".join(year_bits)
                )

        rollups = multi.get("file_rollups") or []
        if rollups:
            lines.append("File rollups (all uploaded files):")
            for rollup in rollups:
                bits = [rollup.get("file_name", "file")]
                if rollup.get("period"):
                    bits.append(str(rollup["period"]))
                if rollup.get("attainment_pct") is not None:
                    bits.append(f"attainment {self._format_metric_value(rollup['attainment_pct'])}%")
                if rollup.get("shortfall_total") is not None:
                    bits.append(f"shortfall {self._format_metric_value(rollup['shortfall_total'])}")
                if rollup.get("total_loss") is not None:
                    bits.append(f"cost {self._format_metric_value(rollup['total_loss'])}")
                if rollup.get("total_downtime") is not None:
                    bits.append(f"downtime {self._format_metric_value(rollup['total_downtime'])}")
                lines.append("  - " + " | ".join(bits))

        shared = multi.get("shared_assets") or {}
        if shared:
            top = list(shared.items())[:12]
            lines.append(
                "Shared assets: "
                + "; ".join(f"{asset} ({len(files)} files)" for asset, files in top)
            )

        asset_trends = multi.get("asset_trends") or []
        for trend in asset_trends[:8]:
            dirs = []
            if trend.get("downtime_direction"):
                dirs.append(f"downtime {trend['downtime_direction']}")
            if trend.get("loss_direction"):
                dirs.append(f"cost {trend['loss_direction']}")
            suffix = f" ({', '.join(dirs)})" if dirs else ""
            lines.append(f"- Asset {trend.get('asset')}{suffix}")

        return lines

    def _compact_spreadsheet_source_lines(self, source: Dict[str, Any]) -> List[str]:
        processed = source.get("processed_data") or {}
        file_name = source.get("file_name") or "uploaded file"
        tab_names = processed.get("tab_names") or [
            t.get("name") for t in (processed.get("tabs") or []) if t.get("name")
        ]
        linking = processed.get("linking_metadata") or {}
        bits = [file_name, f"rows={processed.get('rows')}"]
        if linking.get("date_range"):
            dr = linking["date_range"]
            bits.append(f"{dr.get('min')} → {dr.get('max')}")
        if tab_names:
            bits.append("tabs=" + ", ".join(str(n) for n in tab_names[:8]))
        return ["- " + " | ".join(bits)]

    def _detailed_spreadsheet_source_lines(self, source: Dict[str, Any], profile_char_cap: int) -> List[str]:
        processed = source.get("processed_data") or {}
        file_name = source.get("file_name") or "uploaded file"
        profile = processed.get("full_sheet_profile") or {}
        findings = processed.get("distilled_findings") or []
        action_plan = processed.get("concrete_action_plan") or []
        column_names = processed.get("column_names") or []
        lines = [
            f"- {file_name}: rows={processed.get('rows')}, columns={column_names}",
            "  Allowed spreadsheet columns only: " + ", ".join(map(str, column_names)),
        ]
        if findings:
            lines.append("  Must-use spreadsheet findings:")
            for finding in findings[:12]:
                lines.append(f"  - {finding}")
        if action_plan:
            lines.append(
                "  Required concrete action plan: "
                + json.dumps(action_plan, default=str)[: min(8000, profile_char_cap // 2)]
            )
        if profile:
            lines.append(
                "  Whole-sheet computed profile: "
                + json.dumps(profile, default=str)[:profile_char_cap]
            )
        else:
            lines.append(
                f"  Sample rows only: first={processed.get('sample_data', [])[:5]}, "
                f"last={processed.get('tail_sample_data', [])[:5]}"
            )
        return lines

    def _build_chat_prompt(self, message: str, context: Dict[str, Any]) -> str:
        lines = [
            "Presentation rule: write in plain operational English. Convert underscores, file extensions, "
            "snake_case names, and technical unit labels into readable words. Do not expose raw filenames, "
            "sheet names, or internal identifiers unless the user explicitly asks for them or an exact identifier "
            "is necessary to distinguish evidence. Keep exact source identifiers in citations only.",
            "",
        ]

        multi_block = self._build_multi_file_gemma_block(context)
        if multi_block:
            lines.extend(multi_block)
            lines.append("")

        spreadsheet_sources = self._spreadsheet_sources(context)
        other_sources = [
            source for source in context.get("data_sources") or []
            if (source.get("processed_data") or {}).get("type") != "spreadsheet"
        ]

        use_compact = len(spreadsheet_sources) >= settings.CORRELATION_CHAT_COMPACT_THRESHOLD
        max_prompt = settings.CORRELATION_CHAT_MAX_PROMPT_CHARS
        max_detailed = settings.CORRELATION_CHAT_MAX_DETAILED_SOURCES
        budget = max_prompt - len("\n".join(lines))

        if spreadsheet_sources or other_sources:
            lines.append("Uploaded data context:")
            detailed_used = 0
            omitted = 0

            for index, source in enumerate(spreadsheet_sources):
                if use_compact and index >= max_detailed:
                    chunk = self._compact_spreadsheet_source_lines(source)
                else:
                    per_file_cap = max(2000, budget // max(1, max_detailed))
                    chunk = self._detailed_spreadsheet_source_lines(source, per_file_cap)
                    detailed_used += 1

                chunk_text = "\n".join(chunk)
                if budget > 0 and len(chunk_text) <= budget:
                    lines.extend(chunk)
                    budget -= len(chunk_text) + 1
                elif use_compact:
                    compact = self._compact_spreadsheet_source_lines(source)
                    compact_text = "\n".join(compact)
                    if len(compact_text) <= budget:
                        lines.extend(compact)
                        budget -= len(compact_text) + 1
                    else:
                        omitted += 1
                else:
                    omitted += 1

            for source in other_sources:
                processed = source.get("processed_data") or {}
                file_name = source.get("file_name") or "uploaded file"
                doc_line = f"- {file_name}: {json.dumps(processed, default=str)[:4000]}"
                if len(doc_line) <= budget:
                    lines.append(doc_line)
                    budget -= len(doc_line)

            if omitted:
                lines.append(
                    f"(Note: {omitted} additional source(s) omitted from detailed context; "
                    "cross-file analysis above still covers all uploaded spreadsheets.)"
                )
            lines.append("")

            lines.append(
                "Spreadsheet answer rules: base conclusions on the must-use findings first. "
                "Prefer concrete facts over generic advice. Do not claim a trend, percentage, cycle time, or defect rate "
                "unless it appears in the findings. Do not mention targets, baselines, budgets, customer satisfaction, energy, "
                "staffing, training, compliance audits, or delivery-time KPIs. If the user asks to dive deeper, do not "
                "repeat the prior summary; expand next actions tied to exact delay_reason, estimated_loss, asset_id, "
                "production_line, shift, downtime, defect_count, vibration, and maintenance_status values. Recommendations "
                "must include an owner/team, what to check first, the first next-shift action, and the metric to watch. "
                "Avoid phrases like 'review metrics', 'coordinate teams', or 'implement corrective actions' unless followed "
                "by a specific spreadsheet value and action. Format spreadsheet answers with Markdown headings and bullets. "
                "When listing what to check first, put each value on its own line, for example: "
                "- **Asset ID:** CV-017; - **Production line:** Line C; - **Shift:** Night."
            )
            if self._is_cost_delay_question(message):
                lines.append(
                    "Cost-delay focus: explain which delay_reason values drive the highest estimated_loss, downtime, and "
                    "defect_count. Name the worst asset_id, production_line, and shift from the findings. Give 3 specific "
                    "next actions tied to those exact values."
                )
            lines.append("")

        history = context.get("conversation_history", [])[-6:]
        if history:
            has_spreadsheet_context = bool(spreadsheet_sources)
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

    def _strip_ungrounded_ops_claims(self, text: str, allowed_columns: List[str]) -> str:
        allowed_text = " ".join(allowed_columns).lower()
        banned_phrases = [
            "customer satisfaction",
            "energy usage",
            "energy consumption",
            "staffing",
            "training metrics",
            "compliance audit",
            "delivery time",
            "delivery times",
            "over budget",
            "below target",
            "above target",
            "from baseline",
            "from target",
            "process compliance",
            "logistics performance",
            "continuous improvement",
            "cross-departmental",
        ]
        kept_sentences = []
        for sentence in re.split(r"(?<=[.!?])\s+", text):
            normalized = sentence.lower()
            if not normalized.strip():
                continue
            if any(phrase in normalized for phrase in banned_phrases):
                continue
            if "target" in normalized and "target" not in allowed_text:
                continue
            if "baseline" in normalized and "baseline" not in allowed_text:
                continue
            if "budget" in normalized and "budget" not in allowed_text:
                continue
            kept_sentences.append(sentence.strip())
        return " ".join(kept_sentences).strip()

    def _strip_reasoning_scaffold(self, text: str) -> str:
        """Remove leaked chain-of-thought / planning scaffolds so the user never sees them."""
        scaffold_markers = (
            "analyze the request",
            "scan available context",
            "self-correction",
            "self correction",
            "(simulated)",
            "determine the goal",
            "structure the response",
            "draft content",
            "review against constraints",
            "final polish",
            "persona:",
            "restrictions:",
            "assumption:",
            "thinking process",
            "let me think",
            "step 1:",
            "leads to the generated response",
        )
        lines = text.split("\n")
        kept = []
        for line in lines:
            normalized = line.strip().lower()
            normalized = re.sub(r"^\d+[\.\)]\s*", "", normalized)
            if any(marker in normalized for marker in scaffold_markers):
                continue
            kept.append(line)
        result = "\n".join(kept).strip()

        # If the model dumped a numbered plan, drop everything before the first real prose block.
        if any(marker in text.lower() for marker in scaffold_markers):
            paragraphs = [p.strip() for p in re.split(r"\n\s*\n", result) if p.strip()]
            prose = [
                p for p in paragraphs
                if len(p.split()) > 6 and not re.match(r"^\d+[\.\)]", p) and ":" not in p[:24]
            ]
            if prose:
                result = "\n\n".join(prose)
        return result

    def _clean_chat_text(self, text: str, context: Optional[Dict[str, Any]] = None) -> str:
        cleaned = text.strip()
        cleaned = re.sub(
            r"(?is)^\s*(thought|thinking process|scratchpad)\s*:?.*?\n\s*\n",
            "",
            cleaned,
        )
        cleaned = re.sub(
            r"(?is)^\s*(thought|thinking process|scratchpad)\s*:?.*?(?=\n\s*(answer|final|response)\s*:)",
            "",
            cleaned,
        )
        cleaned = re.sub(r"(?im)^\s*(answer|final|response)\s*:\s*", "", cleaned)
        cleaned = re.sub(r"^Assistant:\s*", "", cleaned, flags=re.I)
        cleaned = self._strip_reasoning_scaffold(cleaned)
        cleaned = cleaned.strip()
        if context and self._has_spreadsheet_context(context):
            cleaned = self._strip_ungrounded_ops_claims(
                cleaned,
                self._allowed_spreadsheet_columns(context),
            )
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
                    label = key.replace("_", " ").title()
                    pieces.append(f"  - **{label}:** {row[key]}")
            if pieces:
                notable_rows.append("\n".join(pieces))

        risk_sentence = (
            "The columns suggest useful risk signals around " + ", ".join(risk_clues) + "."
            if risk_clues else
            "The file uploaded successfully, but the column names do not clearly identify operational risk signals."
        )

        sample_sentence = (
            "A few sample rows include:\n\n" + "\n\n".join(
                f"**Sample row {index}:**\n{row_text}"
                for index, row_text in enumerate(notable_rows[:3], start=1)
            )
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
            "- Whether cost impact is being driven more by downtime, defects, or throughput loss."
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

        data_question_terms = (
            "operation", "operational", "data", "spreadsheet", "excel", "file", "analyze", "analysis",
            "bottleneck", "efficiency", "downtime", "defect", "cost", "production", "shift", "asset",
            "line", "rundown", "summary", "going on", "what's wrong", "what is wrong", "performance",
            "metric", "issue", "problem", "next step", "recommend",
        )
        if any(term in normalized for term in data_question_terms):
            return (
                "I don't have any operational data to look at yet, so I can't pull real numbers for you. "
                "Upload your Excel or CSV file in this session and I'll break down what's going on, where the "
                "biggest losses are, and what to fix first. If you have a specific question in mind, tell me and "
                "I'll point it at the right part of the data once it's loaded."
            )

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

        data_sources = context.get("data_sources") or []
        multi = context.get("multi_spreadsheet_analysis") or {}
        if multi.get("file_rollups"):
            lines.append("MULTI-FILE ROLLUPS:")
            for rollup in multi["file_rollups"]:
                lines.append(json.dumps(rollup, default=str))
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
            except (ValueError, SyntaxError, TypeError, MemoryError, RecursionError):
                # Everything `ast.literal_eval` documents itself raising on a string
                # that is not a literal — the case this fallback exists for. Mechanical
                # narrowing only (FS-693's ratchet payment): the broad catch also ate
                # KeyboardInterrupt-adjacent failures during a long parse, and any
                # future bug in the `isinstance` line, as "not a dict".
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
        
        # Anchored to the backend package, NOT the working directory (FS-431). This read
        # `StateSpaceLoader("state_space")`, so it resolved against wherever the process
        # happened to be started; under a server launched from the repo root it loaded
        # nothing and the endpoint 500'd with "Cannot choose from an empty sequence".
        state_space = StateSpaceLoader(
            str(Path(__file__).parent.parent.parent / "state_space")
        )
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
