"""
ERP Data Transformer

Data transformation and normalization service for ERP integrations:
- Field mapping engine
- Data type conversion
- Business rule application
- Master data management
- Data quality validation
"""

from typing import Dict, Any, Optional, List
from datetime import datetime
import structlog
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from app.db.models import ERPDataMapping

logger = structlog.get_logger()


class ERPDataTransformer:
    """
    Data transformer for ERP integrations.
    
    Transforms ERP-specific data formats into normalized
    OmniusGrid format using field mappings and business rules.
    """
    
    def __init__(self, organization_id: str, integration_id: str):
        self.organization_id = organization_id
        self.integration_id = integration_id
        self._field_mappings: Optional[Dict[str, Dict[str, Any]]] = None
        
        logger.info(
            "erp_data_transformer_initialized",
            organization_id=organization_id,
            integration_id=integration_id
        )
    
    async def load_field_mappings(self, db: AsyncSession):
        """
        Load field mappings from database.
        
        Args:
            db: Database session
        """
        result = await db.execute(
            select(ERPDataMapping).where(
                ERPDataMapping.integration_id == self.integration_id
            )
        )
        mappings = result.scalars().all()
        
        self._field_mappings = {}
        for mapping in mappings:
            key = f"{mapping.source_entity}.{mapping.source_field}"
            self._field_mappings[key] = {
                "target_entity": mapping.target_entity,
                "target_field": mapping.target_field,
                "transformation_rule": mapping.transformation_rule,
                "data_type": mapping.data_type,
                "is_required": mapping.is_required
            }
        
        logger.info(
            "field_mappings_loaded",
            count=len(self._field_mappings)
        )
    
    def transform_purchase_order(self, sap_po: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform SAP purchase order to normalized format.
        
        Args:
            sap_po: SAP purchase order data
            
        Returns:
            Normalized purchase order data
        """
        normalized = {
            "entity_type": "PurchaseOrder",
            "po_number": sap_po.get("PurchaseOrder"),
            "supplier_id": sap_po.get("Supplier"),
            "supplier_name": sap_po.get("SupplierName"),
            "po_date": self._parse_date(sap_po.get("PurchaseOrderDate")),
            "delivery_date": self._parse_date(sap_po.get("DeliveryDate")),
            "total_amount": self._parse_currency(sap_po.get("PurchaseOrderAmount")),
            "currency": sap_po.get("Currency"),
            "status": self._map_po_status(sap_po.get("PurchaseOrderStatus")),
            "items": self._transform_po_items(sap_po.get("to_PurchaseOrderItem", [])),
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "SAP"
        }
        
        return normalized
    
    def transform_manufacturing_order(self, sap_mo: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform SAP manufacturing order to normalized format.
        
        Args:
            sap_mo: SAP manufacturing order data
            
        Returns:
            Normalized manufacturing order data
        """
        normalized = {
            "entity_type": "ManufacturingOrder",
            "mo_number": sap_mo.get("ManufacturingOrder"),
            "material": sap_mo.get("Material"),
            "material_description": sap_mo.get("MaterialDescription"),
            "production_plant": sap_mo.get("ProductionPlant"),
            "order_type": sap_mo.get("OrderType"),
            "start_date": self._parse_date(sap_mo.get("BasicSchedStartDate")),
            "end_date": self._parse_date(sap_mo.get("BasicSchedFinishDate")),
            "quantity": self._parse_number(sap_mo.get("TotalQuantity")),
            "unit": sap_po.get("BaseUnit"),
            "status": self._map_mo_status(sap_mo.get("OrderStatus")),
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "SAP"
        }
        
        return normalized
    
    def transform_inventory(self, sap_inventory: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform SAP inventory data to normalized format.
        
        Args:
            sap_inventory: SAP inventory data
            
        Returns:
            Normalized inventory data
        """
        normalized = {
            "entity_type": "Inventory",
            "material": sap_inventory.get("Material"),
            "material_description": sap_inventory.get("MaterialDescription"),
            "plant": sap_inventory.get("Plant"),
            "storage_location": sap_inventory.get("StorageLocation"),
            "batch": sap_inventory.get("Batch"),
            "quantity": self._parse_number(sap_inventory.get("QuantityInBaseUnit")),
            "unit": sap_inventory.get("BaseUnit"),
            "valuation_price": self._parse_currency(sap_inventory.get("ValuationPrice")),
            "currency": sap_inventory.get("Currency"),
            "last_updated": self._parse_date(sap_inventory.get("LastChangeDateTime")),
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "SAP"
        }
        
        return normalized
    
    def transform_vendor(self, sap_vendor: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform SAP vendor data to normalized format.
        
        Args:
            sap_vendor: SAP vendor data
            
        Returns:
            Normalized vendor data
        """
        normalized = {
            "entity_type": "Vendor",
            "vendor_id": sap_vendor.get("Supplier"),
            "vendor_name": sap_vendor.get("SupplierName"),
            "country": sap_vendor.get("Country"),
            "city": sap_vendor.get("City"),
            "street": sap_vendor.get("Street"),
            "postal_code": sap_vendor.get("PostalCode"),
            "phone": sap_vendor.get("PhoneNumber"),
            "email": sap_vendor.get("EmailAddress"),
            "vat_number": sap_vendor.get("VATNumber"),
            "payment_terms": sap_vendor.get("PaymentTerms"),
            "currency": sap_vendor.get("Currency"),
            "is_active": sap_vendor.get("SupplierIsBlocked", "X") != "X",
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "SAP"
        }
        
        return normalized
    
    def transform_work_order(self, sap_wo: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform SAP work order to normalized format.
        
        Args:
            sap_wo: SAP work order data
            
        Returns:
            Normalized work order data
        """
        normalized = {
            "entity_type": "WorkOrder",
            "wo_number": sap_wo.get("MaintenanceOrder"),
            "equipment": sap_wo.get("Equipment"),
            "equipment_description": sap_wo.get("EquipmentDescription"),
            "functional_location": sap_wo.get("FunctionalLocation"),
            "order_type": sap_wo.get("OrderType"),
            "description": sap_wo.get("Description"),
            "start_date": self._parse_date(sap_wo.get("StartDate")),
            "end_date": self._parse_date(sap_wo.get("EndDate")),
            "priority": self._map_priority(sap_wo.get("Priority")),
            "status": self._map_wo_status(sap_wo.get("SystemStatus")),
            "created_by": sap_wo.get("EnteredBy"),
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "SAP"
        }
        
        return normalized
    
    def transform_invoice(self, oracle_invoice: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform Oracle invoice to normalized format.
        
        Args:
            oracle_invoice: Oracle invoice data
            
        Returns:
            Normalized invoice data
        """
        normalized = {
            "entity_type": "Invoice",
            "invoice_number": oracle_invoice.get("InvoiceId"),
            "invoice_date": self._parse_date(oracle_invoice.get("InvoiceDate")),
            "due_date": self._parse_date(oracle_invoice.get("DueDate")),
            "supplier_id": oracle_invoice.get("SupplierId"),
            "supplier_name": oracle_invoice.get("SupplierName"),
            "total_amount": self._parse_currency(oracle_invoice.get("InvoiceAmount")),
            "currency": oracle_invoice.get("CurrencyCode"),
            "status": self._map_invoice_status(oracle_invoice.get("InvoiceStatus")),
            "payment_status": oracle_invoice.get("PaymentStatus"),
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "Oracle"
        }
        
        return normalized
    
    def transform_shipment(self, oracle_shipment: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform Oracle shipment to normalized format.
        
        Args:
            oracle_shipment: Oracle shipment data
            
        Returns:
            Normalized shipment data
        """
        normalized = {
            "entity_type": "Shipment",
            "shipment_number": oracle_shipment.get("ShipmentNumber"),
            "origin": oracle_shipment.get("OriginLocation"),
            "destination": oracle_shipment.get("DestinationLocation"),
            "ship_date": self._parse_date(oracle_shipment.get("ShipDate")),
            "expected_delivery": self._parse_date(oracle_shipment.get("ExpectedDeliveryDate")),
            "carrier": oracle_shipment.get("CarrierName"),
            "tracking_number": oracle_shipment.get("TrackingNumber"),
            "status": self._map_shipment_status(oracle_shipment.get("ShipmentStatus")),
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "Oracle"
        }
        
        return normalized
    
    def transform_employee(self, oracle_employee: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform Oracle employee to normalized format.
        
        Args:
            oracle_employee: Oracle employee data
            
        Returns:
            Normalized employee data
        """
        normalized = {
            "entity_type": "Employee",
            "employee_id": oracle_employee.get("PersonId"),
            "first_name": oracle_employee.get("FirstName"),
            "last_name": oracle_employee.get("LastName"),
            "email": oracle_employee.get("EmailAddress"),
            "department": oracle_employee.get("DepartmentName"),
            "job_title": oracle_employee.get("JobTitle"),
            "hire_date": self._parse_date(oracle_employee.get("HireDate")),
            "is_active": oracle_employee.get("PersonStatus") == "A",
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "Oracle"
        }
        
        return normalized
    
    def transform_project(self, oracle_project: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform Oracle project to normalized format.
        
        Args:
            oracle_project: Oracle project data
            
        Returns:
            Normalized project data
        """
        normalized = {
            "entity_type": "Project",
            "project_id": oracle_project.get("ProjectId"),
            "project_name": oracle_project.get("ProjectName"),
            "project_number": oracle_project.get("ProjectNumber"),
            "description": oracle_project.get("Description"),
            "start_date": self._parse_date(oracle_project.get("StartDate")),
            "end_date": self._parse_date(oracle_project.get("EndDate")),
            "status": self._map_project_status(oracle_project.get("ProjectStatusCode")),
            "budget": self._parse_currency(oracle_project.get("BudgetAmount")),
            "currency": oracle_project.get("CurrencyCode"),
            "manager": oracle_project.get("ProjectManagerName"),
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "Oracle"
        }
        
        return normalized
    
    def _transform_po_items(self, sap_items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        Transform purchase order items.
        
        Args:
            sap_items: SAP PO items
            
        Returns:
            Normalized PO items
        """
        normalized_items = []
        
        for item in sap_items:
            normalized_item = {
                "item_number": item.get("PurchaseOrderItem"),
                "material": item.get("Material"),
                "material_description": item.get("MaterialDescription"),
                "quantity": self._parse_number(item.get("OrderQuantity")),
                "unit": item.get("PurchaseOrderQuantityUnit"),
                "price": self._parse_currency(item.get("NetPriceAmount")),
                "currency": item.get("Currency"),
                "delivery_date": self._parse_date(item.get("DeliveryDate")),
                "status": self._map_item_status(item.get("OrderStatus"))
            }
            normalized_items.append(normalized_item)
        
        return normalized_items
    
    def _parse_date(self, date_value: Any) -> Optional[str]:
        """
        Parse date value from SAP format.
        
        Args:
            date_value: Date value from SAP
            
        Returns:
            ISO format date string or None
        """
        if not date_value:
            return None
        
        # SAP often returns dates in various formats
        # Handle common formats
        if isinstance(date_value, str):
            # Try ISO format
            try:
                return datetime.fromisoformat(date_value.replace("Z", "+00:00")).isoformat()
            except:
                pass
            
            # Try SAP timestamp format
            try:
                # SAP format: /Date(1234567890)/
                if date_value.startswith("/Date("):
                    timestamp = int(date_value[6:-2])
                    return datetime.fromtimestamp(timestamp / 1000).isoformat()
            except:
                pass
        
        return None
    
    def _parse_currency(self, value: Any) -> Optional[float]:
        """
        Parse currency value.
        
        Args:
            value: Currency value
            
        Returns:
            Float value or None
        """
        if value is None:
            return None
        
        try:
            return float(value)
        except:
            return None
    
    def _parse_number(self, value: Any) -> Optional[float]:
        """
        Parse numeric value.
        
        Args:
            value: Numeric value
            
        Returns:
            Float value or None
        """
        if value is None:
            return None
        
        try:
            return float(value)
        except:
            return None
    
    def _map_po_status(self, sap_status: str) -> str:
        """
        Map SAP PO status to normalized status.
        
        Args:
            sap_status: SAP status
            
        Returns:
            Normalized status
        """
        status_mapping = {
            "N": "new",
            "A": "approved",
            "B": "rejected",
            "C": "completed",
            "D": "deleted",
            "E": "error"
        }
        
        return status_mapping.get(sap_status, "unknown")
    
    def _map_mo_status(self, sap_status: str) -> str:
        """
        Map SAP MO status to normalized status.
        
        Args:
            sap_status: SAP status
            
        Returns:
            Normalized status
        """
        status_mapping = {
            "CRTD": "created",
            "REL": "released",
            "PCNF": "partially_confirmed",
            "CNF": "confirmed",
            "DLV": "delivered",
            "DLV": "completed",
            "TECO": "technically_complete",
            "CLSD": "closed"
        }
        
        return status_mapping.get(sap_status, "unknown")
    
    def _map_wo_status(self, sap_status: str) -> str:
        """
        Map SAP work order status to normalized status.
        
        Args:
            sap_status: SAP status
            
        Returns:
            Normalized status
        """
        status_mapping = {
            "CRTD": "created",
            "REL": "released",
            "PCNF": "partially_confirmed",
            "CNF": "confirmed",
            "DLV": "delivered",
            "TECO": "technically_complete",
            "CLSD": "closed"
        }
        
        return status_mapping.get(sap_status, "unknown")
    
    def _map_item_status(self, sap_status: str) -> str:
        """
        Map SAP item status to normalized status.
        
        Args:
            sap_status: SAP status
            
        Returns:
            Normalized status
        """
        status_mapping = {
            "0": "open",
            "1": "partially_delivered",
            "2": "fully_delivered",
            "3": "closed"
        }
        
        return status_mapping.get(sap_status, "unknown")
    
    def _map_priority(self, sap_priority: str) -> str:
        """
        Map SAP priority to normalized priority.
        
        Args:
            sap_priority: SAP priority
            
        Returns:
            Normalized priority
        """
        priority_mapping = {
            "1": "critical",
            "2": "high",
            "3": "medium",
            "4": "low"
        }
        
        return priority_mapping.get(sap_priority, "medium")
    
    def _map_invoice_status(self, oracle_status: str) -> str:
        """
        Map Oracle invoice status to normalized status.
        
        Args:
            oracle_status: Oracle status
            
        Returns:
            Normalized status
        """
        status_mapping = {
            "VALIDATED": "validated",
            "PARTIALLY_PAID": "partially_paid",
            "PAID": "paid",
            "OVERDUE": "overdue",
            "CANCELLED": "cancelled"
        }
        
        return status_mapping.get(oracle_status, "unknown")
    
    def _map_shipment_status(self, oracle_status: str) -> str:
        """
        Map Oracle shipment status to normalized status.
        
        Args:
            oracle_status: Oracle status
            
        Returns:
            Normalized status
        """
        status_mapping = {
            "OPEN": "open",
            "SHIPPED": "shipped",
            "IN_TRANSIT": "in_transit",
            "DELIVERED": "delivered",
            "CANCELLED": "cancelled"
        }
        
        return status_mapping.get(oracle_status, "unknown")
    
    def _map_project_status(self, oracle_status: str) -> str:
        """
        Map Oracle project status to normalized status.
        
        Args:
            oracle_status: Oracle status
            
        Returns:
            Normalized status
        """
        status_mapping = {
            "PLANNING": "planning",
            "EXECUTING": "executing",
            "ON_HOLD": "on_hold",
            "COMPLETED": "completed",
            "CANCELLED": "cancelled"
        }
        
        return status_mapping.get(oracle_status, "unknown")
    
    def transform_dynamics_invoice(self, dynamics_invoice: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform Dynamics invoice to normalized format.
        
        Args:
            dynamics_invoice: Dynamics invoice data
            
        Returns:
            Normalized invoice data
        """
        normalized = {
            "entity_type": "Invoice",
            "invoice_number": dynamics_invoice.get("invoiceid"),
            "invoice_date": self._parse_date(dynamics_invoice.get("invoicedate")),
            "due_date": self._parse_date(dynamics_invoice.get("duedate")),
            "customer_id": dynamics_invoice.get("customerid_account"),
            "customer_name": dynamics_invoice.get("customerid_accountname"),
            "total_amount": self._parse_currency(dynamics_invoice.get("totalamount")),
            "currency": dynamics_invoice.get("transactioncurrencyid"),
            "status": self._map_dynamics_invoice_status(dynamics_invoice.get("statecode")),
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "Dynamics"
        }
        
        return normalized
    
    def transform_dynamics_payment(self, dynamics_payment: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform Dynamics payment to normalized format.
        
        Args:
            dynamics_payment: Dynamics payment data
            
        Returns:
            Normalized payment data
        """
        normalized = {
            "entity_type": "Payment",
            "payment_id": dynamics_payment.get("paymentid"),
            "payment_date": self._parse_date(dynamics_payment.get("paymentdate")),
            "amount": self._parse_currency(dynamics_payment.get("amount")),
            "currency": dynamics_payment.get("transactioncurrencyid"),
            "payment_method": dynamics_payment.get("paymentmethodcode"),
            "status": self._map_dynamics_payment_status(dynamics_payment.get("statecode")),
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "Dynamics"
        }
        
        return normalized
    
    def transform_dynamics_product(self, dynamics_product: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform Dynamics product to normalized format.
        
        Args:
            dynamics_product: Dynamics product data
            
        Returns:
            Normalized product data
        """
        normalized = {
            "entity_type": "Product",
            "product_id": dynamics_product.get("productid"),
            "product_number": dynamics_product.get("productnumber"),
            "product_name": dynamics_product.get("name"),
            "description": dynamics_product.get("description"),
            "price": self._parse_currency(dynamics_product.get("price")),
            "currency": dynamics_product.get("transactioncurrencyid"),
            "stock": dynamics_product.get("quantityonhand"),
            "is_active": dynamics_product.get("statecode") == 0,
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "Dynamics"
        }
        
        return normalized
    
    def transform_dynamics_sales_order(self, dynamics_order: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform Dynamics sales order to normalized format.
        
        Args:
            dynamics_order: Dynamics sales order data
            
        Returns:
            Normalized sales order data
        """
        normalized = {
            "entity_type": "SalesOrder",
            "order_id": dynamics_order.get("salesorderid"),
            "order_number": dynamics_order.get("ordernumber"),
            "customer_id": dynamics_order.get("customerid_account"),
            "customer_name": dynamics_order.get("customerid_accountname"),
            "order_date": self._parse_date(dynamics_order.get("datefulfilled")),
            "total_amount": self._parse_currency(dynamics_order.get("totalamount")),
            "currency": dynamics_order.get("transactioncurrencyid"),
            "status": self._map_dynamics_order_status(dynamics_order.get("statecode")),
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "Dynamics"
        }
        
        return normalized
    
    def transform_dynamics_account(self, dynamics_account: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform Dynamics CRM account to normalized format.
        
        Args:
            dynamics_account: Dynamics account data
            
        Returns:
            Normalized account data
        """
        normalized = {
            "entity_type": "Account",
            "account_id": dynamics_account.get("accountid"),
            "account_name": dynamics_account.get("name"),
            "account_number": dynamics_account.get("accountnumber"),
            "industry": dynamics_account.get("industrycode"),
            "revenue": self._parse_currency(dynamics_account.get("revenue")),
            "currency": dynamics_account.get("transactioncurrencyid"),
            "phone": dynamics_account.get("telephone1"),
            "email": dynamics_account.get("emailaddress1"),
            "address": {
                "street": dynamics_account.get("address1_line1"),
                "city": dynamics_account.get("address1_city"),
                "state": dynamics_account.get("address1_stateorprovince"),
                "country": dynamics_account.get("address1_country"),
                "postal_code": dynamics_account.get("address1_postalcode")
            },
            "is_active": dynamics_account.get("statecode") == 0,
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "Dynamics"
        }
        
        return normalized
    
    def transform_dynamics_project(self, dynamics_project: Dict[str, Any]) -> Dict[str, Any]:
        """
        Transform Dynamics project to normalized format.
        
        Args:
            dynamics_project: Dynamics project data
            
        Returns:
            Normalized project data
        """
        normalized = {
            "entity_type": "Project",
            "project_id": dynamics_project.get("msdyn_projectid"),
            "project_name": dynamics_project.get("msdyn_name"),
            "description": dynamics_project.get("msdyn_description"),
            "start_date": self._parse_date(dynamics_project.get("msdyn_scheduledstart")),
            "end_date": self._parse_date(dynamics_project.get("msdyn_scheduledend")),
            "status": self._map_dynamics_project_status(dynamics_project.get("statecode")),
            "budget": self._parse_currency(dynamics_project.get("msdyn_budgetamount")),
            "currency": dynamics_project.get("msdyn_transactioncurrencyid"),
            "created_at": datetime.utcnow().isoformat(),
            "source_system": "Dynamics"
        }
        
        return normalized
    
    def _map_dynamics_invoice_status(self, statecode: int) -> str:
        """Map Dynamics invoice statecode to normalized status."""
        status_mapping = {
            0: "draft",
            1: "active",
            2: "paid",
            3: "cancelled"
        }
        return status_mapping.get(statecode, "unknown")
    
    def _map_dynamics_payment_status(self, statecode: int) -> str:
        """Map Dynamics payment statecode to normalized status."""
        status_mapping = {
            0: "draft",
            1: "processed",
            2: "cancelled"
        }
        return status_mapping.get(statecode, "unknown")
    
    def _map_dynamics_order_status(self, statecode: int) -> str:
        """Map Dynamics order statecode to normalized status."""
        status_mapping = {
            0: "draft",
            1: "active",
            2: "fulfilled",
            3: "cancelled",
            4: "invoiced"
        }
        return status_mapping.get(statecode, "unknown")
    
    def _map_dynamics_project_status(self, statecode: int) -> str:
        """Map Dynamics project statecode to normalized status."""
        status_mapping = {
            0: "draft",
            1: "active",
            2: "on_hold",
            3: "completed",
            4: "cancelled"
        }
        return status_mapping.get(statecode, "unknown")
    
    def validate_data_quality(self, entity_type: str, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Validate data quality of transformed data.
        
        Args:
            entity_type: Type of entity
            data: Transformed data
            
        Returns:
            Dict with validation results
        """
        validation_result = {
            "is_valid": True,
            "errors": [],
            "warnings": []
        }
        
        # Common validations
        if not data.get("entity_type"):
            validation_result["is_valid"] = False
            validation_result["errors"].append("Missing entity_type")
        
        # Entity-specific validations
        if entity_type == "PurchaseOrder":
            if not data.get("po_number"):
                validation_result["is_valid"] = False
                validation_result["errors"].append("Missing po_number")
            
            if not data.get("supplier_id"):
                validation_result["warnings"].append("Missing supplier_id")
        
        elif entity_type == "ManufacturingOrder":
            if not data.get("mo_number"):
                validation_result["is_valid"] = False
                validation_result["errors"].append("Missing mo_number")
            
            if not data.get("material"):
                validation_result["warnings"].append("Missing material")
        
        elif entity_type == "Inventory":
            if not data.get("material"):
                validation_result["is_valid"] = False
                validation_result["errors"].append("Missing material")
            
            if data.get("quantity", 0) < 0:
                validation_result["is_valid"] = False
                validation_result["errors"].append("Negative quantity")
        
        return validation_result
