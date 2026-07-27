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

    @pytest.mark.parametrize("erp_type", ["dynamics", "odoo", "netsuite", "intuit"])
    def test_unverified_vendors_are_not_routed_to_sap_transformers(self, erp_type):
        """THE ASSERTION THIS FILE EXISTS FOR.

        `transform_purchase_order` reads SAP field names. Routing another vendor to
        it yields an all-None normalized record, zero detected anomalies, and a
        confident report of a clean sync. Better to state we have no rules yet.
        """
        assert route_for(erp_type, "purchase_order") is None, (
            f"{erp_type} purchase orders are routed to a transformer that reads SAP "
            f"field names; it would report zero anomalies for every record"
        )

    def test_oracle_is_not_routed_for_entities_it_has_no_transformer_for(self):
        """Routing Oracle does not mean routing everything Oracle. A purchase order has
        no Oracle transformer, so it must still be skipped rather than handed to SAP's."""
        assert route_for("oracle", "purchase_order") is None

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
        inside a background sync, as a caught-and-counted failure.

        The analyzer is resolved through PATTERN_CLASSES because it is per-vendor now:
        SAP's analyzers live on the shared ERPCorrelationPatterns, Oracle's on its own
        class. Checking every route against the SAP class — as this did — would reject
        a correct Oracle route.
        """
        import importlib

        from app.services.erp_data_transformer import ERPDataTransformer

        for (erp_type, entity), (transformer, analyzer) in mod.CORRELATION_ROUTES.items():
            assert hasattr(ERPDataTransformer, transformer), (
                f"{erp_type}/{entity} names transformer {transformer!r}, which does not exist"
            )
            module_path, class_name = mod.PATTERN_CLASSES[mod._normalize(erp_type)]
            patterns_cls = getattr(importlib.import_module(module_path), class_name)
            assert hasattr(patterns_cls, analyzer), (
                f"{erp_type}/{entity} names analyzer {analyzer!r}, which does not exist "
                f"on {class_name}"
            )

    def test_every_routed_vendor_has_a_known_analyzer_class(self):
        """A route with no PATTERN_CLASSES entry would fail inside a background sync,
        caught and counted as a per-record failure — so it would look like bad data
        rather than bad configuration."""
        for erp_type, _entity in mod.CORRELATION_ROUTES:
            assert mod._normalize(erp_type) in mod.PATTERN_CLASSES, (
                f"{erp_type} is routed but its analyzer class is unknown"
            )

    def test_oracle_invoices_and_shipments_are_routed(self):
        """Both pairs were already written and simply never registered: Oracle's
        transformers and its analyzers both existed, so its correlations were reported
        as `skipped: unrouted` while the code to produce them sat unused."""
        for entity in ("invoice", "invoices", "shipment", "shipments"):
            assert route_for("oracle", entity) is not None, f"oracle/{entity} unrouted"

    def test_the_oracle_transformer_emits_what_its_analyzer_reads(self):
        """THE CHECK THAT MAKES A ROUTE SAFE TO ADD.

        Registering a pair whose fields do not line up produces an all-None normalized
        record, zero detected anomalies, and a confident report of a clean sync — the
        exact failure this module's routing exists to prevent. Verified here rather than
        assumed: `analyze_invoice_anomalies` reads exactly these five fields.
        """
        from app.services.erp_data_transformer import ERPDataTransformer

        transformer = ERPDataTransformer("org-1", "int-1")
        normalized = transformer.transform_invoice({
            "InvoiceId": "INV-1",
            "SupplierId": "SUP-1",
            "InvoiceAmount": "250.00",
        })
        for field in ("due_date", "invoice_number", "status", "supplier_id", "total_amount"):
            assert field in normalized, (
                f"transform_invoice does not emit {field!r}, which "
                f"analyze_invoice_anomalies reads"
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


class TestOracleRunsEndToEnd:
    """Routing Oracle is only worth anything if the analyzer is actually reached.

    Both halves were already written — `transform_invoice` and
    `analyze_invoice_anomalies` — and neither was registered, so Oracle syncs reported
    `skipped: unrouted` while the code to produce their correlations sat unused.
    """

    async def test_an_oracle_invoice_reaches_the_oracle_analyzer(self):
        seen = []

        class _Stub:
            def __init__(self, *a, **kw):
                pass

            async def analyze_invoice_anomalies(self, db, normalized):
                seen.append(normalized)
                return {"anomalies": []}

        with patch.object(mod, "_count_correlations", side_effect=[0, 1]), patch(
            "app.services.erp_connectors.oracle_correlation_patterns.OracleCorrelationPatterns",
            _Stub,
        ):
            result = await correlate_synced_records(
                None,
                organization_id="o",
                integration_id="i",
                erp_type="oracle",
                entity_type="invoices",
                records=[{"InvoiceId": "INV-9", "SupplierId": "SUP-1",
                          "InvoiceAmount": "1000.00"}],
            )

        assert result["routed"] is True
        assert result["analyzed"] == 1
        assert result["correlations_created"] == 1
        # The ORACLE transformer ran, not SAP's. `InvoiceId` and `SupplierId` are
        # Oracle Fusion field names; the SAP mapping reads `PurchaseOrder`/`Supplier`
        # and would have left every one of these None.
        assert seen[0]["invoice_number"] == "INV-9"
        assert seen[0]["supplier_id"] == "SUP-1"
        assert seen[0]["total_amount"] == 1000.0

    async def test_sap_still_uses_the_sap_analyzer_class(self):
        """The per-vendor lookup must not have redirected SAP anywhere."""
        seen = []

        class _Stub:
            def __init__(self, *a, **kw):
                pass

            async def analyze_purchase_order_anomalies(self, db, normalized):
                seen.append(normalized)
                return {}

        with patch.object(mod, "_count_correlations", side_effect=[0, 0]), patch(
            "app.services.erp_correlation_patterns.ERPCorrelationPatterns", _Stub
        ):
            result = await correlate_synced_records(
                None, organization_id="o", integration_id="i", erp_type="sap",
                entity_type="purchase_order",
                records=[{"PurchaseOrder": "PO-1", "Supplier": "S1"}],
            )

        assert result["analyzed"] == 1
        assert seen[0]["po_number"] == "PO-1"
