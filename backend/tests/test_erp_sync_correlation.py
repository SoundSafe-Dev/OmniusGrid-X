"""Correlation on the polled-sync path — routing, honesty, and blast radius.

Correlations used to be produced ONLY by the SAP webhook path, so a polled sync
filled `erp_entities` and left `erp_correlations` empty. `/erp/correlations/recent`
read a table that nothing in the sync path ever wrote.

The risk in fixing that is subtler than the gap itself.
`ERPDataTransformer.transform_purchase_order` reads **SAP** field names despite its
generic name, so routing on `entity_type` alone would hand Dataverse records to an SAP
mapping, produce a dict of `None`s, find no anomalies, and report "analyzed 500
records, 0 correlations" — confident, plausible, wrong. These tests exist mostly to
keep that from being introduced later as a convenience.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.services import erp_sync_correlation as mod
from app.services.erp_sync_correlation import correlate_synced_records, route_for


class TestRouting:
    def test_sap_purchase_orders_are_routed(self):
        assert route_for("sap", "purchase_order") is not None
        assert route_for("sap", "PurchaseOrder") is not None
        assert route_for("sap", "A_PurchaseOrder") is not None

    @pytest.mark.parametrize(
        "spelling", ["purchase_order", "PURCHASE_ORDER", "PurchaseOrder", "purchase-order"]
    )
    def test_spelling_variants_resolve_to_the_same_route(self, spelling):
        """Entity type reaches this from stored configuration, typed by a human."""
        assert route_for("sap", spelling) == route_for("sap", "purchaseorder")

    @pytest.mark.parametrize("erp_type", ["dynamics", "odoo", "netsuite", "intuit", "oracle"])
    def test_other_vendors_are_not_routed_to_sap_transformers(self, erp_type):
        """THE ASSERTION THIS FILE EXISTS FOR.

        `transform_purchase_order` reads SAP field names. Routing another vendor to
        it yields an all-None normalized record, zero detected anomalies, and a
        confident report of a clean sync. Better to state we have no rules yet.
        """
        assert route_for(erp_type, "purchase_order") is None, (
            f"{erp_type} purchase orders are routed to a transformer that reads SAP "
            f"field names; it would report zero anomalies for every record"
        )

    def test_an_unknown_entity_type_is_not_routed(self):
        assert route_for("sap", "no_such_entity") is None

    def test_every_registry_key_is_reachable(self):
        """The bug this caught while being written: the registry is spelled readably
        (`a_purchaseorder`) but looked up through a normaliser that strips
        separators, so a key containing one can never match. The entry looks present
        and is unreachable — the worst kind of dead configuration."""
        for erp_type, entity in mod.CORRELATION_ROUTES:
            assert route_for(erp_type, entity) is not None, (
                f"registry key ({erp_type}, {entity}) is unreachable through route_for"
            )

    def test_every_route_names_methods_that_actually_exist(self):
        """A registry entry pointing at a renamed method fails only at runtime, deep
        inside a background sync, as a caught-and-counted failure."""
        from app.services.erp_correlation_patterns import ERPCorrelationPatterns
        from app.services.erp_data_transformer import ERPDataTransformer

        for (erp_type, entity), (transformer, analyzer) in mod.CORRELATION_ROUTES.items():
            assert hasattr(ERPDataTransformer, transformer), (
                f"{erp_type}/{entity} names transformer {transformer!r}, which does not exist"
            )
            assert hasattr(ERPCorrelationPatterns, analyzer), (
                f"{erp_type}/{entity} names analyzer {analyzer!r}, which does not exist"
            )


class _StubPatterns:
    def __init__(self, *args, **kwargs):
        self.calls: List[Dict[str, Any]] = []

    async def analyze_purchase_order_anomalies(self, db, normalized):
        self.calls.append(normalized)
        return {"requires_action": False}


class _ExplodingPatterns(_StubPatterns):
    async def analyze_purchase_order_anomalies(self, db, normalized):
        self.calls.append(normalized)
        raise RuntimeError("analyzer blew up")


def _sap_po(n: int) -> Dict[str, Any]:
    return {"PurchaseOrder": f"PO-{n}", "Supplier": "SUP-1", "PurchaseOrderAmount": "100.00"}


class TestCorrelateSyncedRecords:
    async def test_an_unrouted_pair_is_reported_not_silently_skipped(self):
        result = await correlate_synced_records(
            None,
            organization_id="org-1",
            integration_id="int-1",
            erp_type="dynamics",
            entity_type="purchase_order",
            records=[{"anything": 1}],
        )
        assert result["routed"] is False
        assert result["analyzed"] == 0
        assert result["reason"], "an unrouted pair must say why, or it reads as 'nothing found'"

    async def test_no_records_returns_early(self):
        result = await correlate_synced_records(
            None, organization_id="o", integration_id="i", erp_type="sap",
            entity_type="purchase_order", records=[],
        )
        assert result["analyzed"] == 0
        assert result["reason"] == "no records"

    async def test_routed_records_reach_the_analyzer(self):
        stub = _StubPatterns()
        with patch.object(mod, "_count_correlations", side_effect=[0, 3]), \
             patch("app.services.erp_correlation_patterns.ERPCorrelationPatterns",
                   return_value=stub):
            result = await correlate_synced_records(
                None, organization_id="o", integration_id="i", erp_type="sap",
                entity_type="purchase_order", records=[_sap_po(i) for i in range(4)],
            )
        assert result["routed"] is True
        assert result["analyzed"] == 4
        assert len(stub.calls) == 4
        # Proof the SAP transformer actually mapped the fields rather than passing
        # the raw record through.
        assert stub.calls[0]["po_number"] == "PO-0"
        assert stub.calls[0]["entity_type"] == "PurchaseOrder"

    async def test_correlations_created_is_measured_not_inferred(self):
        """"The analyzer returned without raising" is not evidence a correlation was
        written — most records are unremarkable and correctly produce none."""
        stub = _StubPatterns()
        with patch.object(mod, "_count_correlations", side_effect=[7, 7]), \
             patch("app.services.erp_correlation_patterns.ERPCorrelationPatterns",
                   return_value=stub):
            result = await correlate_synced_records(
                None, organization_id="o", integration_id="i", erp_type="sap",
                entity_type="purchase_order", records=[_sap_po(i) for i in range(3)],
            )
        assert result["analyzed"] == 3
        assert result["correlations_created"] == 0, (
            "reported correlations that the row count says were never written"
        )

    async def test_a_failing_record_does_not_abort_the_rest(self):
        """A correlation failure must never fail the sync that produced the data —
        the entities are already useful without it."""
        stub = _ExplodingPatterns()
        with patch.object(mod, "_count_correlations", side_effect=[0, 0]), \
             patch("app.services.erp_correlation_patterns.ERPCorrelationPatterns",
                   return_value=stub):
            result = await correlate_synced_records(
                None, organization_id="o", integration_id="i", erp_type="sap",
                entity_type="purchase_order", records=[_sap_po(i) for i in range(5)],
            )
        assert result["failed"] == 5
        assert result["analyzed"] == 0
        assert len(stub.calls) == 5, "it stopped early instead of continuing"

    async def test_the_record_cap_is_applied_and_reported(self):
        """Correlation issues several queries per record, so a 5000-row Dataverse
        page would mean tens of thousands inside one sync. Truncation nobody is told
        about reads as 'that is all there was'."""
        stub = _StubPatterns()
        with patch.object(mod, "_count_correlations", side_effect=[0, 0]), \
             patch("app.services.erp_correlation_patterns.ERPCorrelationPatterns",
                   return_value=stub):
            result = await correlate_synced_records(
                None, organization_id="o", integration_id="i", erp_type="sap",
                entity_type="purchase_order", records=[_sap_po(i) for i in range(10)],
                max_records=4,
            )
        assert result["analyzed"] == 4
        assert result["skipped_over_cap"] == 6
        assert len(stub.calls) == 4


class TestSyncPathIsWired:
    def test_run_erp_sync_calls_the_correlator(self):
        """The gap being closed. Asserted on the source because the alternative is a
        full background-sync harness for a one-line wiring question."""
        import inspect

        from app.api import erp_integrations

        source = inspect.getsource(erp_integrations.run_erp_sync)
        assert "correlate_synced_records" in source, (
            "the polled sync no longer runs correlation; /correlations/recent will "
            "read a table nothing writes"
        )

    def test_run_erp_sync_sets_the_tenant_guc(self):
        """Every erp_* table is RLS-protected with a FOR ALL USING policy, which
        Postgres also applies as the INSERT check. With the GUC unset that predicate
        is NULL and every insert is rejected — invisible today only because no ERP
        table has FORCE and the dev connection owns them."""
        import inspect

        from app.api import erp_integrations

        source = inspect.getsource(erp_integrations.run_erp_sync)
        assert "_set_tenant_guc" in source, (
            "the background sync does not set app.current_org_id; on a deployment "
            "where the app is not the table owner it writes nothing while reporting "
            "success"
        )
