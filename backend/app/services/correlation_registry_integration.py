"""
Correlation AI to Registry and Kanban Integration Service

This service integrates the correlation AI engine with the actionable registries
and Kanban task management system to automatically create tasks, registry items,
and correlations based on AI analysis results.
"""

import re
from typing import List, Dict, Any, Optional, Tuple
from uuid import UUID
from datetime import datetime, timedelta, timezone
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_
import structlog

from app.db.models import (
    ActionableRegistry, ActionableRegistryItem, DataCorrelation,
    Task, TaskBoard, TaskColumn, TaskRule, TaskEscalation,
    User, Organization
)
from app.services.correlation_ai_engine import correlation_ai_engine

logger = structlog.get_logger()


# Domain to Registry Mapping
DOMAIN_REGISTRY_MAPPING = {
    # Logistics domains
    "LOGISTICS_FLEET": {
        "registry_type": "operational",
        "registry_name": "Logistics Fleet Operations",
        "registry_category": "yard_management",
        "frequency": "daily",
        "priority_level": "high",
        "compliance_standards": ["DOT HOS", "CTPAT Security"]
    },
    "WAREHOUSE_MANAGEMENT": {
        "registry_type": "operational",
        "registry_name": "Warehouse Operations",
        "registry_category": "inventory",
        "frequency": "daily",
        "priority_level": "high",
        "compliance_standards": ["OSHA 1910.176"]
    },
    "DISTRIBUTION": {
        "registry_type": "operational",
        "registry_name": "Distribution Operations",
        "registry_category": "shipping",
        "frequency": "daily",
        "priority_level": "high",
        "compliance_standards": ["DOT Regulations"]
    },
    "SUPPLY_CHAIN": {
        "registry_type": "operational",
        "registry_name": "Supply Chain Management",
        "registry_category": "procurement",
        "frequency": "weekly",
        "priority_level": "high",
        "compliance_standards": ["ISO 28000"]
    },
    "MATERIAL_REPLENISHMENT": {
        "registry_type": "operational",
        "registry_name": "Material Replenishment",
        "registry_category": "inventory",
        "frequency": "daily",
        "priority_level": "medium",
        "compliance_standards": []
    },
    "SPARE_PARTS": {
        "registry_type": "operational",
        "registry_name": "Spare Parts Management",
        "registry_category": "maintenance",
        "frequency": "weekly",
        "priority_level": "medium",
        "compliance_standards": []
    },
    "INVENTORY_OPTIMIZATION": {
        "registry_type": "operational",
        "registry_name": "Inventory Optimization",
        "registry_category": "inventory",
        "frequency": "weekly",
        "priority_level": "medium",
        "compliance_standards": []
    },
    
    # Production domains
    "PRODUCTION_OEE": {
        "registry_type": "operational",
        "registry_name": "Production OEE Monitoring",
        "registry_category": "production",
        "frequency": "hourly",
        "priority_level": "critical",
        "compliance_standards": []
    },
    "PRODUCTION_OUTPUT": {
        "registry_type": "operational",
        "registry_name": "Production Output Tracking",
        "registry_category": "production",
        "frequency": "hourly",
        "priority_level": "high",
        "compliance_standards": []
    },
    "MANUFACTURING_EXECUTION_SYSTEM": {
        "registry_type": "operational",
        "registry_name": "MES Operations",
        "registry_category": "production",
        "frequency": "realtime",
        "priority_level": "critical",
        "compliance_standards": []
    },
    "PROCESS_OPTIMIZATION": {
        "registry_type": "operational",
        "registry_name": "Process Optimization",
        "registry_category": "production",
        "frequency": "daily",
        "priority_level": "medium",
        "compliance_standards": []
    },
    "PACKAGING": {
        "registry_type": "operational",
        "registry_name": "Packaging Operations",
        "registry_category": "production",
        "frequency": "hourly",
        "priority_level": "high",
        "compliance_standards": ["FDA 21 CFR"]
    },
    "ASSET_LIFECYCLE": {
        "registry_type": "operational",
        "registry_name": "Asset Lifecycle Management",
        "registry_category": "maintenance",
        "frequency": "monthly",
        "priority_level": "medium",
        "compliance_standards": []
    },
    "TOOL_MANAGEMENT": {
        "registry_type": "operational",
        "registry_name": "Tool Management",
        "registry_category": "maintenance",
        "frequency": "daily",
        "priority_level": "medium",
        "compliance_standards": []
    },
    "CALIBRATION": {
        "registry_type": "operational",
        "registry_name": "Calibration Management",
        "registry_category": "quality",
        "frequency": "monthly",
        "priority_level": "high",
        "compliance_standards": ["ISO 17025"]
    },
    
    # Maintenance domains
    "MAINTENANCE": {
        "registry_type": "operational",
        "registry_name": "Maintenance Operations",
        "registry_category": "maintenance",
        "frequency": "daily",
        "priority_level": "critical",
        "compliance_standards": ["OSHA 1910.119"]
    },
    "FACILITIES_MANAGEMENT": {
        "registry_type": "operational",
        "registry_name": "Facilities Management",
        "registry_category": "facilities",
        "frequency": "daily",
        "priority_level": "medium",
        "compliance_standards": ["OSHA 1910"]
    },
    "ENERGY_MANAGEMENT": {
        "registry_type": "operational",
        "registry_name": "Energy Management",
        "registry_category": "utilities",
        "frequency": "hourly",
        "priority_level": "medium",
        "compliance_standards": ["ISO 50001"]
    },
    
    # Quality domains
    "QUALITY_CONTROL": {
        "registry_type": "compliance",
        "registry_name": "Quality Control",
        "registry_category": "quality",
        "frequency": "hourly",
        "priority_level": "critical",
        "compliance_standards": ["ISO 9001", "ISO 13485"]
    },
    "REGULATORY_AUDIT": {
        "registry_type": "compliance",
        "registry_name": "Regulatory Audit",
        "registry_category": "compliance",
        "frequency": "quarterly",
        "priority_level": "critical",
        "compliance_standards": ["FDA 21 CFR", "ISO 13485"]
    },
    
    # Safety domains
    "SAFETY": {
        "registry_type": "compliance",
        "registry_name": "Safety Management",
        "registry_category": "safety",
        "frequency": "daily",
        "priority_level": "critical",
        "compliance_standards": ["OSHA 1910", "ANSI Z10"]
    },
    
    # Compliance domains
    "COMPLIANCE_REGISTRIES": {
        "registry_type": "compliance",
        "registry_name": "Compliance Registries",
        "registry_category": "compliance",
        "frequency": "monthly",
        "priority_level": "critical",
        "compliance_standards": ["ISO 9001", "ISO 14001", "ISO 27001"]
    },
    "ENVIRONMENTAL": {
        "registry_type": "compliance",
        "registry_name": "Environmental Compliance",
        "registry_category": "environmental",
        "frequency": "monthly",
        "priority_level": "high",
        "compliance_standards": ["ISO 14001", "EPA Regulations"]
    },
    "ESG": {
        "registry_type": "compliance",
        "registry_name": "ESG Compliance",
        "registry_category": "sustainability",
        "frequency": "quarterly",
        "priority_level": "medium",
        "compliance_standards": ["SASB", "GRI"]
    },
    
    # System domains
    "SYSTEM_INFRASTRUCTURE": {
        "registry_type": "operational",
        "registry_name": "System Infrastructure",
        "registry_category": "it",
        "frequency": "realtime",
        "priority_level": "critical",
        "compliance_standards": ["ISO 27001", "SOC 2"]
    },
    "CYBERSECURITY": {
        "registry_type": "compliance",
        "registry_name": "Cybersecurity",
        "registry_category": "security",
        "frequency": "realtime",
        "priority_level": "critical",
        "compliance_standards": ["ISO 27001", "NIST CSF"]
    },
    "IT_OT_INTEGRATION": {
        "registry_type": "operational",
        "registry_name": "IT/OT Integration",
        "registry_category": "integration",
        "frequency": "daily",
        "priority_level": "high",
        "compliance_standards": ["ISA/IEC 62443"]
    },
    
    # Data & Analytics domains
    "DATA_ANALYTICS": {
        "registry_type": "operational",
        "registry_name": "Data Analytics",
        "registry_category": "analytics",
        "frequency": "daily",
        "priority_level": "medium",
        "compliance_standards": []
    },
    "BUSINESS_INTELLIGENCE": {
        "registry_type": "operational",
        "registry_name": "Business Intelligence",
        "registry_category": "analytics",
        "frequency": "daily",
        "priority_level": "medium",
        "compliance_standards": []
    },
    "DIGITAL_TWIN": {
        "registry_type": "operational",
        "registry_name": "Digital Twin",
        "registry_category": "simulation",
        "frequency": "realtime",
        "priority_level": "medium",
        "compliance_standards": []
    },
    
    # Edge AI domains
    "EDGE_AI_TELEMETRY": {
        "registry_type": "operational",
        "registry_name": "Edge AI Telemetry",
        "registry_category": "telemetry",
        "frequency": "realtime",
        "priority_level": "critical",
        "compliance_standards": []
    },
    
    # Project & Change Management
    "PROJECT_MANAGEMENT": {
        "registry_type": "operational",
        "registry_name": "Project Management",
        "registry_category": "projects",
        "frequency": "daily",
        "priority_level": "medium",
        "compliance_standards": []
    },
    "CHANGE_MANAGEMENT": {
        "registry_type": "operational",
        "registry_name": "Change Management",
        "registry_category": "changes",
        "frequency": "as_needed",
        "priority_level": "high",
        "compliance_standards": ["ITIL"]
    },
    "CONTINUOUS_IMPROVEMENT": {
        "registry_type": "operational",
        "registry_name": "Continuous Improvement",
        "registry_category": "improvement",
        "frequency": "monthly",
        "priority_level": "medium",
        "compliance_standards": []
    },
    
    # Knowledge & Document Management
    "KNOWLEDGE_MANAGEMENT": {
        "registry_type": "operational",
        "registry_name": "Knowledge Management",
        "registry_category": "knowledge",
        "frequency": "weekly",
        "priority_level": "low",
        "compliance_standards": []
    },
    "DOCUMENT_MANAGEMENT": {
        "registry_type": "operational",
        "registry_name": "Document Management",
        "registry_category": "documents",
        "frequency": "daily",
        "priority_level": "medium",
        "compliance_standards": ["ISO 15489"]
    },
    "WORKFLOW_MANAGEMENT": {
        "registry_type": "operational",
        "registry_name": "Workflow Management",
        "registry_category": "workflows",
        "frequency": "daily",
        "priority_level": "medium",
        "compliance_standards": []
    },
    
    # HR & Organizational
    "HR_ORGANIZATIONAL": {
        "registry_type": "operational",
        "registry_name": "HR & Organizational",
        "registry_category": "hr",
        "frequency": "weekly",
        "priority_level": "medium",
        "compliance_standards": ["ISO 45001"]
    },
    "WORKFORCE_MANAGEMENT": {
        "registry_type": "operational",
        "registry_name": "Workforce Management",
        "registry_category": "workforce",
        "frequency": "daily",
        "priority_level": "high",
        "compliance_standards": ["ISO 45001"]
    },
    
    # Customer & Finance
    "CUSTOMER_SERVICE": {
        "registry_type": "operational",
        "registry_name": "Customer Service",
        "registry_category": "customer",
        "frequency": "daily",
        "priority_level": "high",
        "compliance_standards": []
    },
    "FINANCE": {
        "registry_type": "operational",
        "registry_name": "Finance",
        "registry_category": "finance",
        "frequency": "daily",
        "priority_level": "high",
        "compliance_standards": ["SOX", "GAAP"]
    },
    "CONTRACT_MANAGEMENT": {
        "registry_type": "operational",
        "registry_name": "Contract Management",
        "registry_category": "legal",
        "frequency": "weekly",
        "priority_level": "medium",
        "compliance_standards": []
    },
    "SUPPLIER_RELATIONSHIP": {
        "registry_type": "operational",
        "registry_name": "Supplier Relationship",
        "registry_category": "procurement",
        "frequency": "monthly",
        "priority_level": "medium",
        "compliance_standards": ["ISO 28000"]
    },
    "RISK_MANAGEMENT": {
        "registry_type": "compliance",
        "registry_name": "Risk Management",
        "registry_category": "risk",
        "frequency": "quarterly",
        "priority_level": "critical",
        "compliance_standards": ["ISO 31000"]
    },
    
    # Innovation & Product
    "INNOVATION_RD": {
        "registry_type": "operational",
        "registry_name": "Innovation & R&D",
        "registry_category": "innovation",
        "frequency": "monthly",
        "priority_level": "medium",
        "compliance_standards": []
    },
    "PRODUCT_LIFECYCLE": {
        "registry_type": "operational",
        "registry_name": "Product Lifecycle",
        "registry_category": "product",
        "frequency": "as_needed",
        "priority_level": "medium",
        "compliance_standards": []
    },
}


# Kanban Task Type Mapping
KANBAN_TASK_TYPE_MAPPING = {
    "Coordinate cross-domain response team": "custom",
    "Investigate operational anomaly and root cause": "custom",
    "Monitor recovery and verify resolution": "custom",
    "Implement corrective action plan": "maintenance_cm",
    "Review process metrics and performance data": "custom",
    "Execute corrective action": "command_execution",
    "Send alert notification": "alarm_response",
    "Create remediation task": "custom",
    "Check operational status": "custom",
    "Review current metrics": "custom",
    "Schedule preventive maintenance window": "maintenance_pm",
    "Adjust production schedule for maintenance": "production_job",
    "Update quality documentation": "quality_inspection",
    "Resolve network latency issue": "maintenance_cm",
    "Monitor production system availability": "custom",
    "Verify logistics system connectivity": "custom",
    "Ensure compliance system access": "safety_check",
    "Coordinate infrastructure recovery": "custom",
}


class CorrelationRegistryIntegration:
    """
    Integration service for correlation AI, registries, and Kanban system.
    
    This service handles:
    - Creating registries and registry items for operational domains
    - Automatically creating Kanban tasks from correlation AI analysis
    - Creating correlations between registry items and Kanban tasks
    - Alerting system integration
    """
    
    def __init__(self):
        self._initialized = False
    
    async def initialize_registries_for_organization(
        self,
        organization_id: UUID,
        db: AsyncSession,
        created_by: UUID
    ) -> Dict[str, UUID]:
        """
        Initialize registries for every mapped operational domain (46 of them).

        THE COUNT WAS WRONG AND THE SHAPE IS WORTH KNOWING (FS-444). This said "all 47";
        `DOMAIN_REGISTRY_MAPPING` has 46. More importantly, of those 46:

          *  8 can be returned by `_extract_domains_from_analysis`, so only those can ever
             receive an item derived from a correlation analysis
          *  5 also receive default items — a SUBSET of those 8, not a separate group
          * 38 have neither, and are created empty and stay empty

        So an organisation is initialised with 46 registries, 38 of which nothing in this
        service can populate. On a compliance screen that reads as 38 programmes not started
        rather than 38 that cannot be started, which is a different fact. Pinned by
        `test_correlation_registry_integration.py`; closing it means either giving those
        domains default items and keywords, or not creating a registry nothing can fill.
        
        Args:
            organization_id: Organization UUID
            db: Database session
            created_by: User UUID who is creating the registries
            
        Returns:
            Dictionary mapping domain names to registry UUIDs
        """
        logger.info("initializing_registries_for_organization", organization_id=str(organization_id))
        
        registry_ids = {}
        
        for domain_name, registry_config in DOMAIN_REGISTRY_MAPPING.items():
            # Check if registry already exists
            result = await db.execute(
                select(ActionableRegistry).where(
                    and_(
                        ActionableRegistry.organization_id == organization_id,
                        ActionableRegistry.registry_name == registry_config["registry_name"]
                    )
                )
            )
            existing = result.scalar_one_or_none()
            
            if existing:
                registry_ids[domain_name] = existing.id
                continue
            
            # Create new registry
            registry = ActionableRegistry(
                organization_id=organization_id,
                registry_name=registry_config["registry_name"],
                registry_type=registry_config["registry_type"],
                registry_category=registry_config["registry_category"],
                description=f"Operational registry for {domain_name} domain",
                is_active=True,
                is_compliance=registry_config["registry_type"] == "compliance",
                frequency=registry_config["frequency"],
                priority_level=registry_config["priority_level"],
                created_by=created_by,
                meta_data={
                    "domain": domain_name,
                    "compliance_standards": registry_config["compliance_standards"]
                }
            )
            
            db.add(registry)
            await db.commit()
            await db.refresh(registry)
            
            registry_ids[domain_name] = registry.id
            
            # Create default registry items
            await self._create_default_registry_items(
                registry.id, domain_name, db, created_by
            )
        
        logger.info("registries_initialized", count=len(registry_ids))
        return registry_ids
    
    async def _create_default_registry_items(
        self,
        registry_id: UUID,
        domain_name: str,
        db: AsyncSession,
        created_by: UUID
    ):
        """Create default registry items for a domain registry"""
        
        # Define default items based on domain
        default_items = self._get_default_items_for_domain(domain_name)
        
        for item_config in default_items:
            item = ActionableRegistryItem(
                registry_id=registry_id,
                item_code=item_config["item_code"],
                item_name=item_config["item_name"],
                item_description=item_config["item_description"],
                severity_level=item_config["severity_level"],
                is_active=True,
                is_required=item_config["is_required"],
                completion_criteria=item_config["completion_criteria"],
                verification_method=item_config["verification_method"],
                estimated_effort_minutes=item_config["estimated_effort_minutes"],
                completion_frequency=item_config["completion_frequency"],
                created_at=datetime.now(timezone.utc),
                meta_data={"domain": domain_name}
            )
            
            db.add(item)
        
        await db.commit()
    
    def _get_default_items_for_domain(self, domain_name: str) -> List[Dict[str, Any]]:
        """Get default registry items for a specific domain"""
        
        # Common items for most domains
        common_items = [
            {
                "item_code": "MON-001",
                "item_name": "Monitor operational metrics",
                "item_description": "Monitor key performance indicators and operational metrics",
                "severity_level": "medium",
                "is_required": True,
                "completion_criteria": "All metrics within acceptable ranges",
                "verification_method": "automated_check",
                "estimated_effort_minutes": 15,
                "completion_frequency": "hourly"
            },
            {
                "item_code": "INC-001",
                "item_name": "Investigate anomalies",
                "item_description": "Investigate and resolve operational anomalies",
                "severity_level": "high",
                "is_required": True,
                "completion_criteria": "Anomaly root cause identified and resolved",
                "verification_method": "inspection",
                "estimated_effort_minutes": 60,
                "completion_frequency": "as_needed"
            },
            {
                "item_code": "DOC-001",
                "item_name": "Documentation review",
                "item_description": "Review and update operational documentation",
                "severity_level": "low",
                "is_required": False,
                "completion_criteria": "Documentation up to date",
                "verification_method": "documentation",
                "estimated_effort_minutes": 30,
                "completion_frequency": "weekly"
            }
        ]
        
        # Domain-specific items
        domain_specific = {
            "LOGISTICS_FLEET": [
                {
                    "item_code": "DET-001",
                    "item_name": "Monitor detention costs",
                    "item_description": "Track and analyze detention costs and root causes",
                    "severity_level": "high",
                    "is_required": True,
                    "completion_criteria": "Detention costs within budget",
                    "verification_method": "audit",
                    "estimated_effort_minutes": 30,
                    "completion_frequency": "daily"
                },
                {
                    "item_code": "HOS-001",
                    "item_name": "HOS compliance check",
                    "item_description": "Verify driver hours of service compliance",
                    "severity_level": "critical",
                    "is_required": True,
                    "completion_criteria": "All drivers HOS compliant",
                    "verification_method": "automated_check",
                    "estimated_effort_minutes": 15,
                    "completion_frequency": "daily"
                }
            ],
            "MAINTENANCE": [
                {
                    "item_code": "PM-001",
                    "item_name": "Preventive maintenance",
                    "item_description": "Execute scheduled preventive maintenance",
                    "severity_level": "high",
                    "is_required": True,
                    "completion_criteria": "PM completed on schedule",
                    "verification_method": "inspection",
                    "estimated_effort_minutes": 120,
                    "completion_frequency": "as_needed"
                },
                {
                    "item_code": "PDM-001",
                    "item_name": "Predictive maintenance monitoring",
                    "item_description": "Monitor predictive maintenance indicators",
                    "severity_level": "medium",
                    "is_required": True,
                    "completion_criteria": "Equipment health indicators normal",
                    "verification_method": "automated_check",
                    "estimated_effort_minutes": 30,
                    "completion_frequency": "daily"
                }
            ],
            "QUALITY_CONTROL": [
                {
                    "item_code": "QI-001",
                    "item_name": "Quality inspection",
                    "item_description": "Perform quality inspections",
                    "severity_level": "critical",
                    "is_required": True,
                    "completion_criteria": "Quality standards met",
                    "verification_method": "inspection",
                    "estimated_effort_minutes": 45,
                    "completion_frequency": "hourly"
                },
                {
                    "item_code": "CAPA-001",
                    "item_name": "CAPA execution",
                    "item_description": "Execute corrective and preventive actions",
                    "severity_level": "high",
                    "is_required": True,
                    "completion_criteria": "CAPA completed and verified",
                    "verification_method": "audit",
                    "estimated_effort_minutes": 180,
                    "completion_frequency": "as_needed"
                }
            ],
            "SAFETY": [
                {
                    "item_code": "SAFE-001",
                    "item_name": "Safety inspection",
                    "item_description": "Perform safety inspections",
                    "severity_level": "critical",
                    "is_required": True,
                    "completion_criteria": "No safety hazards identified",
                    "verification_method": "inspection",
                    "estimated_effort_minutes": 60,
                    "completion_frequency": "daily"
                },
                {
                    "item_code": "INC-002",
                    "item_name": "Incident investigation",
                    "item_description": "Investigate safety incidents",
                    "severity_level": "critical",
                    "is_required": True,
                    "completion_criteria": "Root cause identified and corrective actions implemented",
                    "verification_method": "audit",
                    "estimated_effort_minutes": 240,
                    "completion_frequency": "as_needed"
                }
            ],
            "COMPLIANCE_REGISTRIES": [
                {
                    "item_code": "COM-001",
                    "item_name": "Compliance audit",
                    "item_description": "Perform compliance audit",
                    "severity_level": "critical",
                    "is_required": True,
                    "completion_criteria": "Audit completed with no findings",
                    "verification_method": "audit",
                    "estimated_effort_minutes": 480,
                    "completion_frequency": "quarterly"
                },
                {
                    "item_code": "REG-001",
                    "item_name": "Regulatory reporting",
                    "item_description": "Submit regulatory reports",
                    "severity_level": "critical",
                    "is_required": True,
                    "completion_criteria": "Reports submitted on time",
                    "verification_method": "documentation",
                    "estimated_effort_minutes": 120,
                    "completion_frequency": "monthly"
                }
            ]
        }
        
        items = common_items.copy()
        if domain_name in domain_specific:
            items.extend(domain_specific[domain_name])
        
        return items
    
    async def process_correlation_analysis(
        self,
        analysis_result: Dict[str, Any],
        organization_id: UUID,
        db: AsyncSession,
        created_by: UUID
    ) -> Dict[str, Any]:
        """
        Process correlation AI analysis and create corresponding registries, tasks, and correlations.
        
        Args:
            analysis_result: Correlation AI analysis result
            organization_id: Organization UUID
            db: Database session
            created_by: User UUID
            
        Returns:
            Dictionary with created registry IDs, task IDs, and correlation IDs
        """
        logger.info("processing_correlation_analysis", organization_id=str(organization_id))
        
        result = {
            "registry_items": [],
            "kanban_tasks": [],
            "correlations": [],
            "alerts": []
        }
        
        # Extract analysis components
        correlation_analysis = analysis_result.get("correlation_analysis", "")
        risk_score = analysis_result.get("risk_score", 0)
        recommended_tasks = analysis_result.get("recommended_kanban_tasks", [])
        recommended_actions = analysis_result.get("recommended_actions", [])
        compliance_implications = analysis_result.get("compliance_implications", [])
        
        # Determine affected domains from analysis
        affected_domains = self._extract_domains_from_analysis(correlation_analysis)
        
        # Create or update registry items for affected domains
        for domain in affected_domains:
            registry_item_id = await self._create_registry_item_from_analysis(
                domain, correlation_analysis, risk_score, organization_id, db, created_by
            )
            if registry_item_id:
                result["registry_items"].append(registry_item_id)
        
        # Create Kanban tasks from recommendations
        for task_recommendation in recommended_tasks:
            task_id = await self._create_kanban_task_from_recommendation(
                task_recommendation, correlation_analysis, risk_score, organization_id, db, created_by
            )
            if task_id:
                result["kanban_tasks"].append(task_id)
        
        # Create correlations between registry items and tasks
        for registry_item_id in result["registry_items"]:
            for task_id in result["kanban_tasks"]:
                correlation_id = await self._create_correlation(
                    registry_item_id, task_id, "registry_item", "task", organization_id, db, created_by
                )
                if correlation_id:
                    result["correlations"].append(correlation_id)
        
        # Create alert notifications
        if risk_score > 50:
            alert_id = await self._create_alert_notification(
                correlation_analysis, risk_score, recommended_actions, organization_id, db, created_by
            )
            if alert_id:
                result["alerts"].append(alert_id)
        
        logger.info("correlation_analysis_processed", result=result)
        return result
    
    def _extract_domains_from_analysis(self, analysis_text: str) -> List[str]:
        """Extract affected domain names from correlation analysis text"""
        domains = []
        
        # Check for domain keywords in analysis
        domain_keywords = {
            "LOGISTICS_FLEET": ["trailer", "truck", "dock", "yard", "detention", "carrier", "driver", "shipment"],
            "MAINTENANCE": ["maintenance", "equipment", "vibration", "temperature", "work order", "technician"],
            "PRODUCTION_OEE": ["production", "oee", "throughput", "cycle time", "quality rate", "asset", "cell"],
            "QUALITY_CONTROL": ["quality", "inspection", "defect", "first pass yield", "capa", "non-conformance"],
            "SAFETY": ["safety", "incident", "security", "hazard", "compliance", "near-miss"],
            "COMPLIANCE_REGISTRIES": ["compliance", "audit", "regulatory", "iso", "osha", "dot", "violation"],
            "WAREHOUSE_MANAGEMENT": ["warehouse", "inventory", "slot", "storage", "fulfillment", "stockout"],
            "SYSTEM_INFRASTRUCTURE": ["network", "database", "latency", "infrastructure", "availability", "error rate"]
        }
        
        # WHOLE WORDS, not substrings (FS-444).
        #
        # This was `keyword in analysis_lower`, and the short keywords are inside ordinary
        # words this domain uses constantly:
        #
        #   "Line CAPAcity was reduced by 12%"      -> QUALITY_CONTROL   (capa)
        #   "The valve was ISOlated for servicing"  -> COMPLIANCE_REGISTRIES (iso)
        #   "Throughput is exCELLent"               -> PRODUCTION_OEE    (cell)
        #   "Two orders were canCELLed"             -> PRODUCTION_OEE    (cell)
        #
        # `capa` is Corrective And Preventive Action and `iso` is the standards body, so a
        # routine note about capacity opened a formal quality item and a valve isolation
        # opened an ISO compliance item. Not cosmetic: `process_correlation_analysis` creates
        # a registry item AND a Kanban task per detected domain, so someone is assigned work
        # in a domain the analysis never mentioned — and the analysis text is quoted into the
        # item, which makes the mismatch look like a judgement rather than a string bug.
        analysis_lower = analysis_text.lower()
        for domain, keywords in domain_keywords.items():
            if any(
                re.search(rf"\b{re.escape(keyword)}\b", analysis_lower)
                for keyword in keywords
            ):
                domains.append(domain)
        
        return domains
    
    async def _create_registry_item_from_analysis(
        self,
        domain: str,
        analysis: str,
        risk_score: float,
        organization_id: UUID,
        db: AsyncSession,
        created_by: UUID
    ) -> Optional[UUID]:
        """Create a registry item from correlation analysis"""
        
        # Get or create registry for domain
        registry_config = DOMAIN_REGISTRY_MAPPING.get(domain)
        if not registry_config:
            return None
        
        result = await db.execute(
            select(ActionableRegistry).where(
                and_(
                    ActionableRegistry.organization_id == organization_id,
                    ActionableRegistry.registry_name == registry_config["registry_name"]
                )
            )
        )
        registry = result.scalar_one_or_none()
        
        if not registry:
            return None
        
        # Determine severity from risk score
        if risk_score > 75:
            severity = "critical"
        elif risk_score > 50:
            severity = "high"
        elif risk_score > 25:
            severity = "medium"
        else:
            severity = "low"
        
        # Create registry item
        item = ActionableRegistryItem(
            registry_id=registry.id,
            item_code=f"AI-{domain[:4].upper()}-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}",
            item_name=f"Correlation AI: {analysis[:100]}...",
            item_description=analysis,
            severity_level=severity,
            is_active=True,
            is_required=risk_score > 50,
            completion_criteria="Root cause identified and corrective actions implemented",
            verification_method="inspection",
            estimated_effort_minutes=60 if risk_score > 50 else 30,
            risk_score=int(risk_score),
            meta_data={
                "source": "correlation_ai",
                "domain": domain,
                "risk_score": risk_score
            },
            created_at=datetime.now(timezone.utc)
        )
        
        db.add(item)
        await db.commit()
        await db.refresh(item)
        
        return item.id
    
    async def _create_kanban_task_from_recommendation(
        self,
        task_recommendation: Dict[str, Any],
        analysis: str,
        risk_score: float,
        organization_id: UUID,
        db: AsyncSession,
        created_by: UUID
    ) -> Optional[UUID]:
        """Create a Kanban task from correlation AI recommendation"""
        
        # Get organization board
        result = await db.execute(
            select(TaskBoard).where(
                and_(
                    TaskBoard.organization_id == organization_id,
                    TaskBoard.is_active == True
                )
            )
        )
        board = result.scalar_one_or_none()
        
        if not board:
            return None
        
        # Get triage column for new tasks
        result = await db.execute(
            select(TaskColumn).where(
                and_(
                    TaskColumn.board_id == board.id,
                    TaskColumn.column_type == "triage"
                )
            )
        )
        column = result.scalar_one_or_none()
        
        if not column:
            # Fallback to backlog
            result = await db.execute(
                select(TaskColumn).where(
                    and_(
                        TaskColumn.board_id == board.id,
                        TaskColumn.column_type == "backlog"
                    )
                )
            )
            column = result.scalar_one_or_none()
        
        if not column:
            return None
        
        # Map task title to task type
        task_title = task_recommendation.get("title", "Custom task")
        task_type = KANBAN_TASK_TYPE_MAPPING.get(task_title, "custom")
        
        # Map priority from risk score
        if risk_score > 75:
            priority = "critical"
        elif risk_score > 50:
            priority = "high"
        elif risk_score > 25:
            priority = "medium"
        else:
            priority = "low"
        
        # Get max position in column
        from sqlalchemy import func
        result = await db.execute(
            select(func.max(Task.position)).where(Task.column_id == column.id)
        )
        max_position = result.scalar() or 0
        
        # Create task
        task = Task(
            board_id=board.id,
            column_id=column.id,
            position=max_position + 1,
            title=task_title,
            description=analysis,
            task_type=task_type,
            priority=priority,
            status="ready",
            estimated_effort_minutes=60 if risk_score > 50 else 30,
            tags=["correlation_ai", "auto_generated"],
            custom_fields={
                "source": "correlation_ai",
                "risk_score": risk_score,
                "ai_generated": True
            },
            approval_status="approved",  # Auto-approve AI-generated tasks
            approved_by=created_by,
            approved_at=datetime.now(timezone.utc),
            created_by=created_by,
            created_at=datetime.now(timezone.utc)
        )
        
        db.add(task)
        await db.commit()
        await db.refresh(task)
        
        return task.id
    
    async def _create_correlation(
        self,
        source_id: UUID,
        target_id: UUID,
        source_type: str,
        target_type: str,
        organization_id: UUID,
        db: AsyncSession,
        created_by: UUID
    ) -> Optional[UUID]:
        """Create a data correlation between entities"""
        
        correlation = DataCorrelation(
            organization_id=organization_id,
            correlation_type=f"{source_type}_to_{target_type}",
            source_type=source_type,
            source_id=source_id,
            target_type=target_type,
            target_id=target_id,
            correlation_strength=75,  # Strong correlation for AI-generated links
            correlation_method="ai_suggested",
            confidence_score=85,  # High confidence for AI-generated
            is_active=True,
            is_bidirectional=True,
            correlation_meta_data={
                "source": "correlation_ai",
                "auto_generated": True
            },
            created_by=created_by,
            created_at=datetime.now(timezone.utc)
        )
        
        db.add(correlation)
        await db.commit()
        await db.refresh(correlation)
        
        return correlation.id
    
    async def _create_alert_notification(
        self,
        analysis: str,
        risk_score: float,
        recommended_actions: List[Dict[str, Any]],
        organization_id: UUID,
        db: AsyncSession,
        created_by: UUID
    ) -> Optional[str]:
        """Dispatch a correlation alert through the notification service.

        THIS LOGGED AND RETURNED AN INVENTED IDENTIFIER (FS-351). The body was
        `# This would integrate with the notification/alerting system / # For now, log the
        alert`, a `logger.warning`, and then

            return f"alert-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"

        That id went into `result["alerts"]`, which `process_correlation_analysis` returns
        — so a caller received a list of alert references for alerts that did not exist,
        on a path that classifies `severity: "critical"` above a risk score of 75. Worse
        than a silent no-op: it reported success with an identifier, which is the shape
        `test_reporting_honesty.py` exists to catch.

        The notification service was already there. `notification_service.dispatch` loads
        the tenant's subscription rules, delivers to the configured channels, records the
        deliveries, and reports failed ones into error-triage.

        DELIVERY FAILURE MUST NOT LOSE THE CORRELATION. The analysis and its correlations
        are already committed by the time this runs, so an exception here would discard
        completed work over an undeliverable email. It is caught and surfaced the same way
        `rul.py` handles its own dispatch failures — and, unlike before, the return value
        then says no alert exists rather than inventing a reference to one.
        """
        event = {
            "event_type": "correlation_alert",
            "severity": "critical" if risk_score > 75 else "high",
            "domain": "correlation",
            "organization_id": str(organization_id),
            "title": f"Correlation risk score {risk_score:.0f}",
            "message": analysis,
            "metadata": {
                "risk_score": risk_score,
                "recommended_actions": recommended_actions,
            },
        }

        try:
            from app.services.notifications import notification_service

            deliveries = await notification_service.dispatch(
                event, organization_id=str(organization_id)
            )
        except Exception as exc:  # the correlation is already committed; keep it
            logger.warning(
                "correlation_alert_dispatch_failed",
                organization_id=str(organization_id),
                risk_score=risk_score,
                error=str(exc),
            )
            from app.services.error_tracker import error_tracker

            await error_tracker.report_subsystem_error(
                exc,
                subsystem="correlation",
                operation="alert.dispatch",
                organization_id=str(organization_id),
            )
            return None

        # `dispatch` returns [] when the tenant has no matching subscription — that is a
        # legitimate outcome and NOT an alert. Returning an id for it would put the old
        # lie back in a quieter form.
        if not deliveries:
            logger.info(
                "correlation_alert_no_subscribers",
                organization_id=str(organization_id),
                risk_score=risk_score,
            )
            return None

        delivered = [d for d in deliveries if d.get("delivered")]
        logger.info(
            "correlation_alert_dispatched",
            organization_id=str(organization_id),
            risk_score=risk_score,
            channels=len(deliveries),
            delivered=len(delivered),
        )
        return event["event_type"] if delivered else None


# Global instance
correlation_registry_integration = CorrelationRegistryIntegration()
