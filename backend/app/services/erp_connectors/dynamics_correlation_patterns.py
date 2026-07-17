"""
Dynamics 365 Correlation Patterns

Correlation patterns for Dynamics 365-specific scenarios:
- Financial + operational correlation (invoices + production)
- CRM correlations (accounts + sales velocity)
- Supply chain correlations (products + inventory)
- Project correlations (projects + resource allocation)
"""

from typing import Dict, Any, List, Optional
from datetime import datetime, timedelta, timezone
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, and_, or_

from app.db.models import (
    ERPEntity,
    ERPCorrelation,
    ERPIntegrationEvent
)

logger = structlog.get_logger()


class DynamicsCorrelationPatterns:
    """
    Dynamics 365 correlation patterns for detecting anomalies and insights.
    
    Maps Dynamics events to operational domains and creates
    correlation patterns with sensor data.
    """
    
    # Domain mappings for Dynamics entities
    DYNAMICS_DOMAIN_MAPPINGS = {
        "Invoice": "FINANCE",
        "Payment": "FINANCE",
        "Product": "SUPPLY_CHAIN",
        "SalesOrder": "CRM",
        "Account": "CRM",
        "Project": "PROJECT_MANAGEMENT"
    }
    
    def __init__(self, organization_id: str, integration_id: str):
        self.organization_id = organization_id
        self.integration_id = integration_id
        
        logger.info(
            "dynamics_correlation_patterns_initialized",
            organization_id=organization_id,
            integration_id=integration_id
        )
    
    async def analyze_invoice_correlation(
        self,
        db: AsyncSession,
        invoice_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Correlate invoice with operational data.
        
        Args:
            db: Database session
            invoice_data: Invoice data
            
        Returns:
            Dict with correlation analysis results
        """
        correlations = []
        
        # Check for overdue invoices
        if invoice_data.get("due_date"):
            due_date = datetime.fromisoformat(invoice_data["due_date"])
            if due_date < datetime.now(timezone.utc) and invoice_data.get("status") != "paid":
                correlations.append({
                    "type": "overdue_invoice",
                    "severity": "high",
                    "message": f"Invoice {invoice_data.get('invoice_number')} is overdue"
                })
        
        # Check for high-value invoices
        if invoice_data.get("total_amount"):
            if invoice_data["total_amount"] > 100000:  # $100k threshold
                correlations.append({
                    "type": "high_value_invoice",
                    "severity": "medium",
                    "message": f"High-value invoice: {invoice_data['total_amount']}"
                })
        
        # Correlate with customer account
        if invoice_data.get("customer_id"):
            customer_analysis = await self._analyze_customer_account(
                db,
                invoice_data.get("customer_id")
            )
            
            if customer_analysis:
                correlations.append({
                    "type": "customer_analysis",
                    "message": "Customer account analysis",
                    "analysis": customer_analysis
                })
        
        logger.info(
            "dynamics_invoice_correlation_completed",
            invoice_number=invoice_data.get("invoice_number"),
            correlation_count=len(correlations)
        )
        
        return {
            "invoice_number": invoice_data.get("invoice_number"),
            "correlations": correlations
        }
    
    async def analyze_sales_velocity(
        self,
        db: AsyncSession,
        account_id: str
    ) -> Dict[str, Any]:
        """
        Analyze sales velocity for CRM account.
        
        Args:
            db: Database session
            account_id: Account ID
            
        Returns:
            Dict with sales velocity analysis
        """
        # Get sales orders for this account
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.entity_type == "SalesOrder",
                    ERPEntity.entity_data["customer_id"].astext == account_id,
                    ERPEntity.is_active == True
                )
            )
        )
        orders = result.scalars().all()
        
        if not orders:
            return {
                "account_id": account_id,
                "sales_velocity": "no_data",
                "order_count": 0
            }
        
        # Calculate metrics
        total_amount = sum(
            order.entity_data.get("total_amount", 0)
            for order in orders
        )
        
        # Calculate velocity (orders in last 90 days)
        ninety_days_ago = datetime.now(timezone.utc) - timedelta(days=90)
        recent_orders = [
            order for order in orders
            if order.created_at >= ninety_days_ago
        ]
        
        velocity_score = len(recent_orders) / 3  # Orders per month average
        
        # Determine velocity category
        if velocity_score > 10:
            velocity_category = "high"
        elif velocity_score > 5:
            velocity_category = "medium"
        else:
            velocity_category = "low"
        
        logger.info(
            "dynamics_sales_velocity_analysis_completed",
            account_id=account_id,
            velocity_category=velocity_category,
            velocity_score=velocity_score
        )
        
        return {
            "account_id": account_id,
            "total_orders": len(orders),
            "recent_orders": len(recent_orders),
            "total_amount": total_amount,
            "velocity_score": velocity_score,
            "velocity_category": velocity_category
        }
    
    async def analyze_product_inventory_correlation(
        self,
        db: AsyncSession,
        product_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Correlate product data with inventory levels.
        
        Args:
            db: Database session
            product_data: Product data
            
        Returns:
            Dict with correlation analysis results
        """
        correlations = []
        
        # Check for low stock
        if product_data.get("stock"):
            stock_level = product_data["stock"]
            if stock_level < 10:  # Low stock threshold
                correlations.append({
                    "type": "low_stock",
                    "severity": "high",
                    "message": f"Product {product_data.get('product_name')} has low stock: {stock_level}"
                })
            elif stock_level < 50:
                correlations.append({
                    "type": "low_stock_warning",
                    "severity": "medium",
                    "message": f"Product {product_data.get('product_name')} stock is low: {stock_level}"
                })
        
        # Check for inactive products with stock
        if not product_data.get("is_active") and product_data.get("stock", 0) > 0:
            correlations.append({
                "type": "inactive_with_stock",
                "severity": "medium",
                "message": f"Inactive product has {product_data.get('stock')} units in stock"
            })
        
        logger.info(
            "dynamics_product_inventory_correlation_completed",
            product_id=product_data.get("product_id"),
            correlation_count=len(correlations)
        )
        
        return {
            "product_id": product_data.get("product_id"),
            "correlations": correlations
        }
    
    async def analyze_project_resource_correlation(
        self,
        db: AsyncSession,
        project_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Correlate project data with resource allocation.
        
        Args:
            db: Database session
            project_data: Project data
            
        Returns:
            Dict with correlation analysis results
        """
        correlations = []
        
        # Check for projects nearing deadline
        if project_data.get("end_date"):
            end_date = datetime.fromisoformat(project_data["end_date"])
            days_remaining = (end_date - datetime.now(timezone.utc)).days
            
            if days_remaining < 30 and project_data.get("status") == "active":
                correlations.append({
                    "type": "deadline_approaching",
                    "severity": "high",
                    "message": f"Project ending in {days_remaining} days, status still active"
                })
        
        # Check for budget overruns
        if project_data.get("budget"):
            # Would need to compare with actual spend
            # For now, just flag if project is on hold
            if project_data.get("status") == "on_hold":
                correlations.append({
                    "type": "project_on_hold",
                    "severity": "medium",
                    "message": "Project is currently on hold"
                })
        
        logger.info(
            "dynamics_project_resource_correlation_completed",
            project_id=project_data.get("project_id"),
            correlation_count=len(correlations)
        )
        
        return {
            "project_id": project_data.get("project_id"),
            "correlations": correlations
        }
    
    async def analyze_churn_prediction(
        self,
        db: AsyncSession,
        account_id: str
    ) -> Dict[str, Any]:
        """
        Predict customer churn based on CRM data.
        
        Args:
            db: Database session
            account_id: Account ID
            
        Returns:
            Dict with churn prediction
        """
        # Get account data
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.entity_type == "Account",
                    ERPEntity.entity_id == account_id,
                    ERPEntity.is_active == True
                )
            )
        )
        account = result.scalar_one_or_none()
        
        if not account:
            return {
                "account_id": account_id,
                "churn_risk": "unknown",
                "message": "Account not found"
            }
        
        account_data = account.entity_data
        
        # Get sales velocity
        sales_velocity = await self.analyze_sales_velocity(db, account_id)
        
        # Calculate churn risk based on factors
        risk_factors = []
        churn_score = 0
        
        # Low sales velocity
        if sales_velocity.get("velocity_category") == "low":
            risk_factors.append("low_sales_velocity")
            churn_score += 30
        
        # Inactive account
        if not account_data.get("is_active"):
            risk_factors.append("account_inactive")
            churn_score += 50
        
        # No recent orders
        if sales_velocity.get("recent_orders", 0) == 0:
            risk_factors.append("no_recent_orders")
            churn_score += 40
        
        # Determine churn risk category
        if churn_score > 70:
            churn_risk = "high"
        elif churn_score > 40:
            churn_risk = "medium"
        else:
            churn_risk = "low"
        
        logger.info(
            "dynamics_churn_prediction_completed",
            account_id=account_id,
            churn_risk=churn_risk,
            churn_score=churn_score
        )
        
        return {
            "account_id": account_id,
            "churn_risk": churn_risk,
            "churn_score": churn_score,
            "risk_factors": risk_factors,
            "requires_action": churn_risk in ["high", "medium"]
        }
    
    async def _analyze_customer_account(
        self,
        db: AsyncSession,
        customer_id: str
    ) -> Optional[Dict[str, Any]]:
        """Analyze customer account for correlations."""
        # Get account data
        result = await db.execute(
            select(ERPEntity).where(
                and_(
                    ERPEntity.entity_type == "Account",
                    ERPEntity.entity_id == customer_id,
                    ERPEntity.is_active == True
                )
            )
        )
        account = result.scalar_one_or_none()
        
        if not account:
            return None
        
        account_data = account.entity_data
        
        # Get sales velocity
        sales_velocity = await self.analyze_sales_velocity(db, customer_id)
        
        return {
            "account_name": account_data.get("account_name"),
            "industry": account_data.get("industry"),
            "revenue": account_data.get("revenue"),
            "sales_velocity": sales_velocity
        }
