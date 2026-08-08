"""Odoo correlation patterns (FS-55x).

WHY THIS FILE EXISTS. Odoo has a working connector, stores raw records, and
`erp_sync_correlation.route_for()` returned `None` for every one of them — so every sync
completed and reported `skipped: unrouted`: a successful integration with an empty
correlation list.

WHY IT IS A SEPARATE CLASS FROM NETSUITE'S. The ANALYZERS here are the same, because they
read the same normalized shape. The **transformers** are not, and cannot be: the registry's
rule is that a route pairs one vendor's field names with an analyzer, and a shared analyzer
class would still need a per-vendor entry in `PATTERN_CLASSES` to be reachable. Keeping the
class per vendor means the domain mapping and the `source_system` stamp on every result are
the vendor's own — so a cross-vendor correlation view can say which system a finding came
from, which is the whole point of routing them separately.

The analyzers below read what `ERPDataTransformer.transform_odoo_*` produces, field
for field. See `netsuite_correlation_patterns.py` for why reusing another vendor's
TRANSFORMER produces a confident report of zero anomalies.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import ERPEntity

logger = structlog.get_logger()


class OdooCorrelationPatterns:
    """Anomaly analysis over NetSuite records, normalized by `ERPDataTransformer`."""

    #: Which operational domain each entity belongs to, matching the Oracle and Dynamics
    #: classes so a cross-vendor view groups them the same way.
    ODOO_DOMAIN_MAPPINGS = {
        "Invoice": "FINANCE",
        "SalesOrder": "SUPPLY_CHAIN",
        "Inventory": "SUPPLY_CHAIN",
    }

    def __init__(self, organization_id: str, integration_id: str):
        self.organization_id = organization_id
        self.integration_id = integration_id
        logger.info(
            "odoo_correlation_patterns_initialized",
            organization_id=organization_id,
            integration_id=integration_id,
        )

    # ------------------------------------------------------------------ invoices

    async def analyze_invoice_anomalies(
        self, db: AsyncSession, invoice_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Overdue, oversized and duplicated invoices.

        `status` is compared against the MAPPED vocabulary, not NetSuite's own. SuiteTalk
        sends "Paid In Full"; a direct comparison to "paid" is unequal for every settled
        invoice, so the overdue check would fire on all of them — a confident wrong answer
        rather than an error, which is FS-435's shape.
        """
        anomalies: List[Dict[str, Any]] = []
        risk_score = 0

        due_date = self._as_datetime(invoice_data.get("due_date"))
        if due_date and invoice_data.get("status") != "paid":
            if due_date < datetime.now(timezone.utc):
                anomalies.append(
                    {
                        "type": "overdue_invoice",
                        "severity": "high",
                        "message": (
                            f"Invoice {invoice_data.get('invoice_number')} is overdue "
                            f"(status {invoice_data.get('status')!r})"
                        ),
                    }
                )
                risk_score += 30

        total = invoice_data.get("total_amount")
        if total:
            average = await self._average_invoice_amount(db, invoice_data.get("supplier_id"))
            if average and total > average * 5:
                anomalies.append(
                    {
                        "type": "unusual_amount",
                        "severity": "high",
                        "message": (
                            f"Invoice amount {total} is more than 5x the average of "
                            f"{average:.2f} for this counterparty"
                        ),
                    }
                )
                risk_score += 40

        if await self._is_duplicate(db, invoice_data.get("invoice_number")):
            anomalies.append(
                {
                    "type": "duplicate_invoice",
                    "severity": "critical",
                    "message": (
                        f"Invoice number {invoice_data.get('invoice_number')} already exists "
                        f"for this integration"
                    ),
                }
            )
            risk_score += 50

        return self._result("Invoice", invoice_data.get("invoice_number"), anomalies, risk_score)

    # ------------------------------------------------------------------ inventory

    async def analyze_inventory_shortfall(
        self, db: AsyncSession, inventory_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Available stock against the reorder point.

        `quantity` is `quantityAvailable` — on hand MINUS committed. Using `quantityOnHand`
        would overstate availability against open orders and report a shortfall as healthy,
        which is the direction that looks like good news.
        """
        anomalies: List[Dict[str, Any]] = []
        risk_score = 0

        available = inventory_data.get("quantity")
        reorder_point = inventory_data.get("reorder_point")

        if available is not None and reorder_point:
            if available <= 0:
                anomalies.append(
                    {
                        "type": "stockout",
                        "severity": "critical",
                        "message": (
                            f"{inventory_data.get('material_id')} has no available stock at "
                            f"{inventory_data.get('plant') or 'an unspecified location'}"
                        ),
                    }
                )
                risk_score += 50
            elif available < reorder_point:
                anomalies.append(
                    {
                        "type": "below_reorder_point",
                        "severity": "medium",
                        "message": (
                            f"{inventory_data.get('material_id')} is at {available}, below its "
                            f"reorder point of {reorder_point}"
                        ),
                    }
                )
                risk_score += 20

        return self._result(
            "Inventory", inventory_data.get("material_id"), anomalies, risk_score
        )

    # ------------------------------------------------------------------ sales orders

    async def analyze_sales_order_correlation(
        self, db: AsyncSession, order_data: Dict[str, Any]
    ) -> Dict[str, Any]:
        """An order whose promised delivery has passed while it is still open."""
        anomalies: List[Dict[str, Any]] = []
        risk_score = 0

        delivery = self._as_datetime(order_data.get("delivery_date"))
        status = order_data.get("status")
        if delivery and delivery < datetime.now(timezone.utc) and status not in {
            "closed",
            "cancelled",
        }:
            anomalies.append(
                {
                    "type": "delivery_date_passed",
                    "severity": "high",
                    "message": (
                        f"Order {order_data.get('order_number')} promised "
                        f"{order_data.get('delivery_date')} and is still {status!r}"
                    ),
                }
            )
            risk_score += 35

        return self._result("SalesOrder", order_data.get("order_number"), anomalies, risk_score)

    # ------------------------------------------------------------------ helpers

    @staticmethod
    def _as_datetime(value: Any) -> Optional[datetime]:
        """Parse a normalized ISO date, tolerating a naive one.

        The transformer emits `datetime.isoformat()` output, which for a date-only NetSuite
        field has no timezone. Comparing a naive datetime to an aware one raises TypeError
        inside a background sync, where it becomes a swallowed failure and a vendor that
        silently stops being analysed — so the offset is supplied here rather than assumed.
        """
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)

    def _result(
        self, entity_type: str, entity_id: Any, anomalies: List[Dict[str, Any]], risk: int
    ) -> Dict[str, Any]:
        return {
            "entity_type": entity_type,
            "entity_id": entity_id,
            "domain": self.ODOO_DOMAIN_MAPPINGS.get(entity_type),
            "anomalies": anomalies,
            "anomaly_count": len(anomalies),
            "risk_score": min(100, risk),
            "analyzed_at": datetime.now(timezone.utc).isoformat(),
            "source_system": "Odoo",
        }

    async def _average_invoice_amount(
        self, db: AsyncSession, counterparty: Optional[str]
    ) -> Optional[float]:
        """Mean invoice total for this counterparty, from stored entities.

        AVERAGED IN PYTHON, over a bounded page. The amount lives inside `entity_data`,
        which is JSON — the first version of this queried `func.avg(ERPEntity.numeric_value)`
        against a column that does not exist on this table, and would have raised inside a
        background sync where the failure is swallowed and the vendor silently stops being
        analysed. `ERPEntity` has `entity_type`, `entity_id` and `entity_data`, and nothing
        else to average.

        Capped at 500 rows: this runs per invoice during a sync, and an unbounded scan of a
        large tenant's history would make the correlation pass quadratic in its own input.
        """
        if not counterparty:
            return None
        result = await db.execute(
            select(ERPEntity.entity_data)
            .where(
                and_(
                    ERPEntity.organization_id == self.organization_id,
                    ERPEntity.entity_type == "Invoice",
                    ERPEntity.source_system == "Odoo",
                )
            )
            .limit(500)
        )
        amounts = [
            float(row["total_amount"])
            for (row,) in result.all()
            if isinstance(row, dict)
            and row.get("supplier_id") == counterparty
            and isinstance(row.get("total_amount"), (int, float))
        ]
        return sum(amounts) / len(amounts) if amounts else None

    async def _is_duplicate(self, db: AsyncSession, invoice_number: Optional[str]) -> bool:
        """Whether this invoice number already exists for this organisation.

        Keys on `entity_id`, the column that actually holds the vendor's identifier. The
        first version used `external_id`, which is not a column on this table.
        """
        if not invoice_number:
            return False
        result = await db.execute(
            select(func.count(ERPEntity.id)).where(
                and_(
                    ERPEntity.organization_id == self.organization_id,
                    ERPEntity.entity_type == "Invoice",
                    ERPEntity.entity_id == str(invoice_number),
                )
            )
        )
        return int(result.scalar() or 0) > 1
