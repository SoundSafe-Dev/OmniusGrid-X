"""Run correlation analysis over records a polled ERP sync just fetched.

WHY THIS EXISTS. Correlations were only ever produced by the SAP *webhook* path
(`sap_webhook_integration.py`). A polled sync wrote `erp_entities` rows and stopped,
so `/erp/correlations/recent` read a table that nothing in the sync path ever wrote,
and the AI tab was empty for every integration that was not receiving SAP webhooks.

ROUTING IS KEYED ON (erp_type, entity_type), NOT entity_type ALONE.

`ERPDataTransformer.transform_purchase_order` reads **SAP** field names --
`PurchaseOrder`, `Supplier`, `PurchaseOrderAmount` -- despite its generic name. Handed
a Dataverse or Odoo record it returns a dict of `None`s. The analyzer then finds no
anomalies and the sync reports "analyzed 500 records, 0 correlations": a plausible,
confident, wrong answer, and precisely the silent-failure shape this subsystem keeps
producing.

So an unrouted (erp_type, entity_type) pair is reported as SKIPPED and named in the
log. Adding a vendor means writing a transformer that reads that vendor's field names
and registering it here -- not reusing one that happens to be importable.

The returned counts are what actually happened. `analyzed` counts records that reached
an analyzer; `correlations_created` is measured by counting rows, not inferred from
"we called the analyzer without an exception".
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

logger = structlog.get_logger()

#: Where a vendor's analyzers live. SAP's are on the shared `ERPCorrelationPatterns`;
#: Oracle has its own class. Naming the class per route is what lets a second vendor be
#: routed at all — the registry previously hardcoded the SAP class, so an Oracle entry
#: would have called a SAP analyzer.
PATTERN_CLASSES: Dict[str, Tuple[str, str]] = {
    "sap": ("app.services.erp_correlation_patterns", "ERPCorrelationPatterns"),
    "oracle": (
        "app.services.erp_connectors.oracle_correlation_patterns",
        "OracleCorrelationPatterns",
    ),
}

#: (erp_type, normalized entity type) -> (transformer method, analyzer method).
#:
#: Every entry is a claim that the named transformer reads THAT vendor's field names and
#: produces exactly what the analyzer reads. Both halves were verified field-by-field
#: before each route was added — `transform_invoice` emits `due_date`, `invoice_number`,
#: `status`, `supplier_id` and `total_amount`, and `analyze_invoice_anomalies` reads
#: those five and nothing else.
#:
#: Oracle's transformers and analyzers were both already written and simply never
#: registered, so its correlations were reported as `skipped: unrouted` while the code to
#: produce them sat unused.
#:
#: A vendor with no verified pair stays out. Reusing another vendor's transformer would
#: yield empty normalized records and a confident report of zero anomalies.
CORRELATION_ROUTES: Dict[Tuple[str, str], Tuple[str, str]] = {
    ("sap", "purchaseorder"): (
        "transform_purchase_order",
        "analyze_purchase_order_anomalies",
    ),
    ("sap", "a_purchaseorder"): (  # the OData entity set name
        "transform_purchase_order",
        "analyze_purchase_order_anomalies",
    ),
    ("sap", "manufacturingorder"): (
        "transform_manufacturing_order",
        "analyze_manufacturing_order_correlation",
    ),
    ("sap", "productionorder"): (
        "transform_manufacturing_order",
        "analyze_manufacturing_order_correlation",
    ),
    ("oracle", "invoice"): ("transform_invoice", "analyze_invoice_anomalies"),
    ("oracle", "invoices"): ("transform_invoice", "analyze_invoice_anomalies"),
    ("oracle", "shipment"): ("transform_shipment", "analyze_shipment_correlation"),
    ("oracle", "shipments"): ("transform_shipment", "analyze_shipment_correlation"),
}

#: Correlation analysis issues several DB queries PER RECORD (supplier averages, order
#: counts, delay counts). A 5000-row Dataverse page would therefore mean tens of
#: thousands of queries inside a sync. Bounded, and the cap is reported rather than
#: applied silently -- a truncation nobody is told about reads as "that is all there
#: was".
DEFAULT_MAX_RECORDS = 200


def _normalize(value: Optional[str]) -> str:
    return (value or "").strip().lower().replace("_", "").replace("-", "")


#: The registry is written readably above (`a_purchaseorder`) but looked up through
#: `_normalize`, which strips separators. Normalising the KEYS at import keeps the two
#: from drifting -- without this, a key containing an underscore can never match, and
#: the entry looks present while being unreachable.
_ROUTES_NORMALIZED: Dict[Tuple[str, str], Tuple[str, str]] = {
    (_normalize(erp), _normalize(entity)): route
    for (erp, entity), route in CORRELATION_ROUTES.items()
}


def route_for(erp_type: Optional[str], entity_type: Optional[str]) -> Optional[Tuple[str, str]]:
    """Resolve the transformer/analyzer pair, or None when the pair is unrouted.

    A route is only usable if we also know WHERE that vendor's analyzers live, so a
    registry entry without a matching PATTERN_CLASSES entry resolves to None rather than
    failing later inside a background sync.
    """
    vendor = _normalize(erp_type)
    if vendor not in PATTERN_CLASSES:
        return None
    return _ROUTES_NORMALIZED.get((vendor, _normalize(entity_type)))


async def _count_correlations(db: AsyncSession, organization_id: str) -> int:
    from app.db.models import ERPCorrelation

    result = await db.execute(
        select(func.count())
        .select_from(ERPCorrelation)
        .where(ERPCorrelation.organization_id == organization_id)
    )
    return int(result.scalar() or 0)


async def correlate_synced_records(
    db: AsyncSession,
    *,
    organization_id: str,
    integration_id: str,
    erp_type: Optional[str],
    entity_type: str,
    records: List[Dict[str, Any]],
    max_records: int = DEFAULT_MAX_RECORDS,
) -> Dict[str, Any]:
    """Analyse freshly-synced records and persist any correlations found.

    Never raises. A correlation failure must not fail the sync that produced the data
    -- the entities are already useful without it -- but it must not be invisible
    either, so every outcome is counted and returned.
    """
    outcome: Dict[str, Any] = {
        "routed": False,
        "analyzed": 0,
        "correlations_created": 0,
        "failed": 0,
        "skipped_over_cap": 0,
        "reason": None,
    }

    if not records:
        outcome["reason"] = "no records"
        return outcome

    route = route_for(erp_type, entity_type)
    if route is None:
        # Named, not swallowed: this is the difference between "we have no
        # correlation rules for Dataverse purchase orders yet" and "correlation
        # silently did nothing".
        outcome["reason"] = "no correlation route for this erp_type/entity_type"
        logger.info(
            "erp_correlation_skipped_unrouted",
            erp_type=erp_type,
            entity_type=entity_type,
            record_count=len(records),
            detail=(
                "no transformer is registered that reads this vendor's field names. "
                "Reusing another vendor's transformer would produce empty normalized "
                "records and a confident report of zero anomalies."
            ),
        )
        return outcome

    transformer_name, analyzer_name = route
    outcome["routed"] = True

    import importlib

    from app.services.erp_data_transformer import ERPDataTransformer

    module_path, class_name = PATTERN_CLASSES[_normalize(erp_type)]
    patterns_cls = getattr(importlib.import_module(module_path), class_name)

    transformer = ERPDataTransformer(organization_id, integration_id)
    patterns = patterns_cls(organization_id, integration_id)

    transform = getattr(transformer, transformer_name)
    analyze = getattr(patterns, analyzer_name)

    if len(records) > max_records:
        outcome["skipped_over_cap"] = len(records) - max_records
        logger.warning(
            "erp_correlation_record_cap_applied",
            entity_type=entity_type,
            total=len(records),
            analyzing=max_records,
            skipped=outcome["skipped_over_cap"],
            detail="correlation runs several queries per record; the remainder was "
                   "not analysed and is reported rather than dropped quietly",
        )

    before = await _count_correlations(db, organization_id)

    for record in records[:max_records]:
        try:
            normalized = transform(record)
            await analyze(db, normalized)
            outcome["analyzed"] += 1
        except Exception as exc:  # noqa: BLE001 - one bad record must not stop a sync
            outcome["failed"] += 1
            logger.warning(
                "erp_correlation_record_failed",
                entity_type=entity_type,
                error=str(exc)[:200],
            )

    after = await _count_correlations(db, organization_id)
    # MEASURED, not inferred. "The analyzer returned without raising" is not evidence
    # that a correlation was written -- most records are unremarkable and correctly
    # produce none.
    outcome["correlations_created"] = max(after - before, 0)

    logger.info(
        "erp_correlation_completed",
        entity_type=entity_type,
        erp_type=erp_type,
        analyzed=outcome["analyzed"],
        correlations_created=outcome["correlations_created"],
        failed=outcome["failed"],
    )
    return outcome
