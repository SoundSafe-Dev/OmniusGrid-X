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
from datetime import datetime, timezone
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            # `sap_po` here was a NameError on EVERY call -- this function's parameter
            # is `sap_mo`. Nothing caught it because nothing called the function: the
            # SAP manufacturing-order route would have raised on the first record, been
            # caught by the per-record handler in correlate_synced_records, and counted
            # as a failure -- reading as bad vendor data rather than a typo.
            "unit": sap_mo.get("BaseUnit"),
            "status": self._map_mo_status(sap_mo.get("OrderStatus")),
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
    
    # ================================================================================
    # NetSuite (FS-557)
    # ================================================================================
    #
    # NetSuite has a working connector, stores raw records, and `route_for()` returned
    # None — so every NetSuite sync completed, wrote its rows, and reported
    # `skipped: unrouted` with no correlation ever produced. The customer sees a
    # successful integration and an empty analysis.
    #
    # THESE READ NETSUITE'S OWN FIELD NAMES, which is the entire point. The route
    # registry's header states the rule: "Reusing another vendor's transformer would
    # yield empty normalized records and a confident report of zero anomalies." SAP's
    # `transform_invoice` looks for `InvoiceId`/`DueDate`; SuiteTalk sends `tranId` and
    # `dueDate`, so the SAP transformer applied to a NetSuite payload emits a record of
    # Nones and the analyzer finds nothing wrong with it — the worst possible outcome,
    # because it is indistinguishable from clean data.
    #
    # Field names are SuiteTalk REST record fields. Two shapes need care and both are
    # handled below:
    #
    #   * `status` and `entity` arrive as OBJECTS (`{"id": "...", "refName": "Open"}`),
    #     not strings. Reading them directly yields a dict where the analyzer expects a
    #     scalar, and a dict is truthy — so an overdue check comparing it to "paid" is
    #     always unequal and every invoice reads as unpaid.
    #   * amounts arrive as STRINGS ("1234.56"), which is why `_parse_currency` is used
    #     rather than a bare float().

    @staticmethod
    def _netsuite_ref(value: Any) -> Optional[str]:
        """A SuiteTalk reference field, reduced to the scalar an analyzer can compare.

        NetSuite sends `{"id": "12", "refName": "Open"}` for status, customer, currency
        and location. `refName` is the human value; `id` is the internal key. Prefers
        `refName`, falls back to `id`, and passes a plain string through unchanged so a
        flattened payload still works.
        """
        if value is None:
            return None
        if isinstance(value, dict):
            reference = value.get("refName") or value.get("id")
            return str(reference) if reference is not None else None
        return str(value)

    def transform_netsuite_invoice(self, netsuite_invoice: Dict[str, Any]) -> Dict[str, Any]:
        """NetSuite invoice -> the five fields `analyze_invoice_anomalies` reads.

        Emits `invoice_number`, `due_date`, `status`, `supplier_id` and `total_amount`
        under exactly those names, because that analyzer reads those five and nothing
        else. Verified field-by-field, as the route registry requires.
        """
        return {
            "entity_type": "Invoice",
            # `tranId` is the document number a user recognises; `id` is internal.
            "invoice_number": netsuite_invoice.get("tranId") or netsuite_invoice.get("id"),
            "invoice_date": self._parse_date(netsuite_invoice.get("tranDate")),
            "due_date": self._parse_date(netsuite_invoice.get("dueDate")),
            # On an invoice `entity` is the CUSTOMER being billed. It occupies the
            # `supplier_id` slot because that is what the shared analyzer calls its
            # counterparty field; renaming the analyzer's contract per vendor is how
            # two vendors stop being comparable.
            "supplier_id": self._netsuite_ref(netsuite_invoice.get("entity")),
            "supplier_name": self._netsuite_ref(netsuite_invoice.get("entity")),
            "total_amount": self._parse_currency(netsuite_invoice.get("total")),
            "currency": self._netsuite_ref(netsuite_invoice.get("currency")),
            "status": self._map_netsuite_status(
                self._netsuite_ref(netsuite_invoice.get("status"))
            ),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_system": "NetSuite",
        }

    def transform_netsuite_sales_order(self, netsuite_order: Dict[str, Any]) -> Dict[str, Any]:
        """NetSuite salesOrder -> the normalized order shape."""
        return {
            "entity_type": "SalesOrder",
            "order_number": netsuite_order.get("tranId") or netsuite_order.get("id"),
            "order_date": self._parse_date(netsuite_order.get("tranDate")),
            "delivery_date": self._parse_date(
                netsuite_order.get("shipDate") or netsuite_order.get("dueDate")
            ),
            "customer_id": self._netsuite_ref(netsuite_order.get("entity")),
            "total_amount": self._parse_currency(netsuite_order.get("total")),
            "currency": self._netsuite_ref(netsuite_order.get("currency")),
            "status": self._map_netsuite_status(
                self._netsuite_ref(
                    netsuite_order.get("orderStatus") or netsuite_order.get("status")
                )
            ),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_system": "NetSuite",
        }

    def transform_netsuite_inventory(self, netsuite_item: Dict[str, Any]) -> Dict[str, Any]:
        """NetSuite inventoryItem -> the normalized inventory shape."""
        return {
            "entity_type": "Inventory",
            "material_id": netsuite_item.get("itemId") or netsuite_item.get("id"),
            "material_name": netsuite_item.get("displayName") or netsuite_item.get("itemId"),
            "plant": self._netsuite_ref(netsuite_item.get("location")),
            # `quantityAvailable` is on-hand minus committed, which is what a shortage
            # check needs. `quantityOnHand` overstates availability against open orders.
            "quantity": self._parse_currency(netsuite_item.get("quantityAvailable")),
            "quantity_on_hand": self._parse_currency(netsuite_item.get("quantityOnHand")),
            "reorder_point": self._parse_currency(netsuite_item.get("reorderPoint")),
            "unit": self._netsuite_ref(netsuite_item.get("unitsType")),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_system": "NetSuite",
        }

    @staticmethod
    def _map_netsuite_status(status: Optional[str]) -> Optional[str]:
        """NetSuite status text -> the vocabulary the shared analyzers compare against.

        `analyze_invoice_anomalies` tests `status != "paid"`. NetSuite says "Paid In
        Full", "Open", "Pending Approval" — none of which equals "paid", so without this
        mapping **every paid invoice would be reported as overdue**. That is FS-435's
        shape: two vocabularies, no translation, and the failure is a confident wrong
        answer rather than an error.
        """
        if not status:
            return None
        normalized = status.strip().lower()
        if "paid" in normalized:
            return "paid"
        if "open" in normalized or "pending" in normalized:
            return "open"
        if "cancel" in normalized or "void" in normalized:
            return "cancelled"
        if "closed" in normalized or "fulfilled" in normalized or "billed" in normalized:
            return "closed"
        return normalized

    # ================================================================================
    # Odoo (FS-558)
    # ================================================================================
    #
    # Odoo's JSON-RPC returns MANY2ONE fields as a two-element list — `[42, "Acme Co"]`,
    # the id and its display name. Reading one directly puts a list where the analyzer
    # expects a scalar, and a non-empty list is truthy: every comparison against a status
    # string silently takes the wrong branch, exactly as NetSuite's reference objects do.
    #
    # Models are `account.move` (invoices AND bills, distinguished by `move_type`),
    # `sale.order` and `product.product`.

    @staticmethod
    def _odoo_scalar(value: Any) -> Optional[str]:
        """An Odoo many2one `[id, name]` pair, reduced to its display name."""
        if value is None or value is False:
            # Odoo sends `false`, not null, for an unset field — and `False` is not None,
            # so a plain `or` chain downstream would treat it as a present value.
            return None
        if isinstance(value, (list, tuple)):
            return str(value[1]) if len(value) > 1 else str(value[0])
        return str(value)

    def transform_odoo_invoice(self, odoo_move: Dict[str, Any]) -> Dict[str, Any]:
        """Odoo `account.move` -> the five fields `analyze_invoice_anomalies` reads."""
        return {
            "entity_type": "Invoice",
            "invoice_number": odoo_move.get("name") or odoo_move.get("id"),
            "invoice_date": self._parse_date(odoo_move.get("invoice_date")),
            "due_date": self._parse_date(odoo_move.get("invoice_date_due")),
            "supplier_id": self._odoo_scalar(odoo_move.get("partner_id")),
            "supplier_name": self._odoo_scalar(odoo_move.get("partner_id")),
            "total_amount": self._parse_currency(odoo_move.get("amount_total")),
            "currency": self._odoo_scalar(odoo_move.get("currency_id")),
            "status": self._map_odoo_payment_state(
                odoo_move.get("payment_state"), odoo_move.get("state")
            ),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_system": "Odoo",
        }

    def transform_odoo_sales_order(self, odoo_order: Dict[str, Any]) -> Dict[str, Any]:
        """Odoo `sale.order` -> the normalized order shape."""
        return {
            "entity_type": "SalesOrder",
            "order_number": odoo_order.get("name") or odoo_order.get("id"),
            "order_date": self._parse_date(odoo_order.get("date_order")),
            "delivery_date": self._parse_date(odoo_order.get("commitment_date")),
            "customer_id": self._odoo_scalar(odoo_order.get("partner_id")),
            "total_amount": self._parse_currency(odoo_order.get("amount_total")),
            "currency": self._odoo_scalar(odoo_order.get("currency_id")),
            "status": self._map_odoo_order_state(odoo_order.get("state")),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_system": "Odoo",
        }

    @staticmethod
    def _map_odoo_payment_state(payment_state: Any, state: Any) -> Optional[str]:
        """Odoo's `payment_state` -> the analyzer's vocabulary.

        `payment_state` is the field that says whether money arrived: `not_paid`,
        `in_payment`, `paid`, `partial`, `reversed`. `state` is the DOCUMENT state
        (`draft`/`posted`/`cancel`) and a posted invoice is not a paid one — reading it
        instead would mark every posted invoice paid and suppress every overdue finding.
        """
        payment = str(payment_state).strip().lower() if payment_state else ""
        if payment == "paid":
            return "paid"
        if payment in {"partial", "in_payment"}:
            return "open"
        document = str(state).strip().lower() if state else ""
        if document == "cancel":
            return "cancelled"
        if document == "draft":
            return "draft"
        return "open"

    @staticmethod
    def _map_odoo_order_state(state: Any) -> Optional[str]:
        mapping = {
            "draft": "draft",
            "sent": "open",
            "sale": "open",
            "done": "closed",
            "cancel": "cancelled",
        }
        return mapping.get(str(state).strip().lower() if state else "", None)

    # ================================================================================
    # Infor (FS-559) and Epicor (FS-560)
    # ================================================================================
    #
    # Both are ION/OData-style REST services returning flat records with PascalCase
    # field names, so neither needs a reference-object unwrapper. What they DO need is
    # their own field names: Infor sends `InvoiceNumber`/`DueDate`, Epicor sends
    # `InvoiceNum`/`DueDate`/`InvoiceAmt`. Neither matches SAP's `InvoiceId`, and the
    # near-miss between them is the point — `InvoiceNumber` and `InvoiceNum` are one
    # careless copy apart, and a wrong one produces a null rather than an error.

    def transform_infor_invoice(self, infor_invoice: Dict[str, Any]) -> Dict[str, Any]:
        """Infor ION invoice -> the normalized invoice shape."""
        return {
            "entity_type": "Invoice",
            "invoice_number": infor_invoice.get("InvoiceNumber") or infor_invoice.get("ID"),
            "invoice_date": self._parse_date(infor_invoice.get("InvoiceDate")),
            "due_date": self._parse_date(infor_invoice.get("DueDate")),
            "supplier_id": infor_invoice.get("SupplierID") or infor_invoice.get("VendorID"),
            "supplier_name": infor_invoice.get("SupplierName"),
            "total_amount": self._parse_currency(infor_invoice.get("TotalAmount")),
            "currency": infor_invoice.get("CurrencyCode"),
            "status": self._map_generic_invoice_status(infor_invoice.get("Status")),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_system": "Infor",
        }

    def transform_infor_inventory(self, infor_item: Dict[str, Any]) -> Dict[str, Any]:
        """Infor inventory -> the normalized inventory shape."""
        return {
            "entity_type": "Inventory",
            "material_id": infor_item.get("ItemID") or infor_item.get("ID"),
            "material_name": infor_item.get("ItemDescription"),
            "plant": infor_item.get("WarehouseID") or infor_item.get("Location"),
            "quantity": self._parse_currency(infor_item.get("QuantityOnHand")),
            "reorder_point": self._parse_currency(infor_item.get("ReorderLevel")),
            "unit": infor_item.get("UnitOfMeasure"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_system": "Infor",
        }

    def transform_epicor_invoice(self, epicor_invoice: Dict[str, Any]) -> Dict[str, Any]:
        """Epicor `Erp.BO.InvoiceSvc` -> the normalized invoice shape.

        `InvoiceNum` is Epicor's abbreviation and it is NOT Infor's `InvoiceNumber`.
        Reading the wrong one yields None and an analyzer that reports nothing wrong.
        """
        return {
            "entity_type": "Invoice",
            "invoice_number": epicor_invoice.get("InvoiceNum"),
            "invoice_date": self._parse_date(epicor_invoice.get("InvoiceDate")),
            "due_date": self._parse_date(epicor_invoice.get("DueDate")),
            "supplier_id": epicor_invoice.get("CustNum") or epicor_invoice.get("VendorNum"),
            "supplier_name": epicor_invoice.get("CustomerName"),
            "total_amount": self._parse_currency(epicor_invoice.get("InvoiceAmt")),
            "currency": epicor_invoice.get("CurrencyCode"),
            # Epicor carries payment state as a BOOLEAN, not a status string. `OpenInvoice`
            # false means settled — so a status-string comparison finds nothing to compare
            # and every invoice stays "open", which is the overdue check firing on all of
            # them.
            "status": "open" if epicor_invoice.get("OpenInvoice") else "paid",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_system": "Epicor",
        }

    def transform_epicor_part(self, epicor_part: Dict[str, Any]) -> Dict[str, Any]:
        """Epicor `Erp.BO.PartSvc` -> the normalized inventory shape."""
        return {
            "entity_type": "Inventory",
            "material_id": epicor_part.get("PartNum"),
            "material_name": epicor_part.get("PartDescription"),
            "plant": epicor_part.get("Plant"),
            "quantity": self._parse_currency(epicor_part.get("OnHandQty")),
            "reorder_point": self._parse_currency(epicor_part.get("MinimumQty")),
            "unit": epicor_part.get("IUM"),
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_system": "Epicor",
        }

    # ================================================================================
    # Intuit QuickBooks (FS-561)
    # ================================================================================
    #
    # QBO nests money and references: `TotalAmt` is a bare number but `CustomerRef` is
    # `{"value": "42", "name": "Acme"}`, and `Balance` — not a status field — is what says
    # whether an invoice is settled. There is no `status` on a QBO Invoice at all, so a
    # transformer that looks for one leaves it None and the overdue check treats every
    # invoice as unpaid.

    @staticmethod
    def _qbo_ref(value: Any) -> Optional[str]:
        """A QBO `{"value": ..., "name": ...}` reference, reduced to a scalar."""
        if value is None:
            return None
        if isinstance(value, dict):
            reference = value.get("name") or value.get("value")
            return str(reference) if reference is not None else None
        return str(value)

    def transform_intuit_invoice(self, qbo_invoice: Dict[str, Any]) -> Dict[str, Any]:
        """QuickBooks Online Invoice -> the normalized invoice shape.

        STATUS IS DERIVED FROM `Balance`, because QBO has no status field on an invoice.
        A zero balance means settled. Looking for `Status` — as every other vendor here
        has — returns None, and `None != "paid"` is true, so every invoice ever synced
        would be reported overdue the moment its due date passed.
        """
        balance = self._parse_currency(qbo_invoice.get("Balance"))
        return {
            "entity_type": "Invoice",
            "invoice_number": qbo_invoice.get("DocNumber") or qbo_invoice.get("Id"),
            "invoice_date": self._parse_date(qbo_invoice.get("TxnDate")),
            "due_date": self._parse_date(qbo_invoice.get("DueDate")),
            "supplier_id": self._qbo_ref(qbo_invoice.get("CustomerRef")),
            "supplier_name": self._qbo_ref(qbo_invoice.get("CustomerRef")),
            "total_amount": self._parse_currency(qbo_invoice.get("TotalAmt")),
            "currency": self._qbo_ref(qbo_invoice.get("CurrencyRef")),
            "status": "paid" if balance is not None and balance <= 0 else "open",
            "balance": balance,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "source_system": "Intuit",
        }

    @staticmethod
    def _map_generic_invoice_status(status: Any) -> Optional[str]:
        """Shared status normalisation for the PascalCase REST vendors."""
        if not status:
            return None
        normalized = str(status).strip().lower()
        if "paid" in normalized or normalized == "closed":
            return "paid"
        if "cancel" in normalized or "void" in normalized:
            return "cancelled"
        if "draft" in normalized:
            return "draft"
        return "open"

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
            except (ValueError, TypeError):
                pass  # not ISO — try the next format
            
            # Try SAP timestamp format
            try:
                # SAP format: /Date(1234567890)/
                if date_value.startswith("/Date("):
                    timestamp = int(date_value[6:-2])
                    return datetime.fromtimestamp(timestamp / 1000).isoformat()
            except (ValueError, TypeError, OverflowError, OSError):
                pass  # not a SAP /Date(...)/ — fall through to None
        
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
        except (ValueError, TypeError) as exc:
            # A present-but-unparseable currency (e.g. "1,234.56", "$100") used
            # to become a silent NULL in financial records via a bare `except:`.
            # Surface it; the bare form also swallowed KeyboardInterrupt.
            logger.warning(
                "erp_currency_parse_failed",
                value=repr(value),
                organization_id=self.organization_id,
                integration_id=self.integration_id,
                error=str(exc),
            )
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
        except (ValueError, TypeError) as exc:
            logger.warning(
                "erp_number_parse_failed",
                value=repr(value),
                organization_id=self.organization_id,
                integration_id=self.integration_id,
                error=str(exc),
            )
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
            # "DLV" was listed twice, so the second silently won and "delivered" was
            # unreachable. DLV is SAP's delivered status; TECO below is the
            # technically-complete one, so "completed" was the duplicate to drop.
            "DLV": "delivered",
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
        # FIELD NAMES VERIFIED against Microsoft's invoice table reference. Three were
        # wrong, and each would have failed silently -- an unmapped field is None, the
        # analyzer finds nothing, and the sync reports a clean run over data it never
        # actually read:
        #
        #   invoiceid      is the GUID primary key, NOT the human invoice number.
        #                  `invoicenumber` is the real column.
        #   invoicedate    IS NOT A COLUMN on invoice. The date columns are `duedate`
        #                  and `datedelivered`; `createdon` is the record timestamp.
        #   customerid_account is a ReferencingEntityNavigationPropertyName -- an
        #                  $expand target, not a scalar. A Web API row carries the
        #                  lookup as `_customerid_value`.
        normalized = {
            "entity_type": "Invoice",
            "invoice_number": dynamics_invoice.get("invoicenumber") or dynamics_invoice.get("invoiceid"),
            "invoice_date": self._parse_date(
                dynamics_invoice.get("datedelivered") or dynamics_invoice.get("createdon")
            ),
            "due_date": self._parse_date(dynamics_invoice.get("duedate")),
            # `customerid` is accepted too, for a caller that passes an expanded row.
            "customer_id": dynamics_invoice.get("_customerid_value") or dynamics_invoice.get("customerid"),
            "customer_name": dynamics_invoice.get("customeridname"),
            "total_amount": self._parse_currency(dynamics_invoice.get("totalamount")),
            "currency": dynamics_invoice.get("transactioncurrencyid"),
            "status": self._map_dynamics_invoice_status(dynamics_invoice.get("statecode")),
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
            "created_at": datetime.now(timezone.utc).isoformat(),
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
