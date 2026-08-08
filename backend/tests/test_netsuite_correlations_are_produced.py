"""A real NetSuite payload produces a correlation (FS-557).

WHAT WAS WRONG. NetSuite has a working connector, it stores raw records, and
`erp_sync_correlation.route_for("netsuite", …)` returned `None` for every entity — so every
sync completed, wrote its rows, and reported `skipped: unrouted`. The customer saw a
successful integration and an empty correlation list, with nothing saying the vendor was
never analysed.

WHY A NEW TRANSFORMER RATHER THAN SAP'S. The route registry states the rule in its own
header: *"A vendor with no verified pair stays out. Reusing another vendor's transformer would
yield empty normalized records and a confident report of zero anomalies."*

That is not a stylistic preference, and this file proves it: `transform_invoice` reads
`InvoiceId` and `DueDate`; SuiteTalk sends `tranId` and `dueDate`. The SAP transformer applied
to a NetSuite payload emits a record of `None`s — and an analyzer reading a record of `None`s
finds nothing wrong. **The failure is a clean bill of health, not an error**, which is the
worst possible outcome because it is indistinguishable from working.

THE PAYLOADS BELOW ARE SUITETALK-SHAPED, not hand-tidied. Two properties of the real API are
what make this test worth having:

  * `status`, `entity` and `currency` arrive as OBJECTS — `{"id": "3", "refName": "Open"}` —
    not strings. A dict is truthy, so a status comparison against `"paid"` is unequal for
    every invoice including the settled ones.
  * amounts arrive as STRINGS. `"4820.50" > average * 5` is a TypeError in Python 3, inside a
    background sync where the failure is swallowed and the vendor silently stops producing
    correlations.

Both are handled in the transformer, and both are asserted here rather than assumed.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone

import pytest

from app.services.erp_connectors.netsuite_correlation_patterns import (
    NetSuiteCorrelationPatterns,
)
from app.services.erp_data_transformer import ERPDataTransformer
from app.services.erp_sync_correlation import (
    CORRELATION_ROUTES,
    PATTERN_CLASSES,
    route_for,
)

ORG = uuid.uuid4()
INTEGRATION = uuid.uuid4()


@pytest.fixture
def transformer() -> ERPDataTransformer:
    return ERPDataTransformer(organization_id=ORG, integration_id=INTEGRATION)


@pytest.fixture
def patterns() -> NetSuiteCorrelationPatterns:
    return NetSuiteCorrelationPatterns(str(ORG), str(INTEGRATION))


def _overdue_invoice() -> dict:
    """A SuiteTalk invoice record, past due and unpaid."""
    return {
        "id": "5501",
        "tranId": "INV-1001",
        "tranDate": "2026-01-02",
        "dueDate": (datetime.now(timezone.utc) - timedelta(days=45)).date().isoformat(),
        "total": "4820.50",
        "status": {"id": "A", "refName": "Open"},
        "entity": {"id": "42", "refName": "Acme Manufacturing"},
        "currency": {"id": "1", "refName": "USD"},
    }


class TestTheVendorIsRouted:
    @pytest.mark.parametrize(
        "entity", ["invoice", "salesOrder", "inventoryItem", "inventory"]
    )
    def test_the_entity_resolves_to_a_pair(self, entity: str):
        assert route_for("netsuite", entity) is not None, (
            f"netsuite/{entity} is unrouted, so a sync of it reports `skipped: unrouted` "
            f"and produces no correlation while reporting success"
        )

    def test_the_pattern_class_is_registered(self):
        """Both halves. `route_for` returns None for a vendor with routes and no pattern
        class — which is how a half-finished registration of this very vendor behaved, and
        is the design working: it failed closed rather than calling a nonexistent class
        inside a swallowed background task."""
        assert "netsuite" in PATTERN_CLASSES

    def test_every_registered_route_names_a_method_that_exists(self):
        """The registry is a claim about two method names. A typo in either produces an
        AttributeError inside a background sync, where it is swallowed and the vendor
        silently stops being analysed."""
        transformer = ERPDataTransformer(organization_id=ORG, integration_id=INTEGRATION)
        analyzers = NetSuiteCorrelationPatterns(str(ORG), str(INTEGRATION))
        for (vendor, entity), (transform, analyze) in CORRELATION_ROUTES.items():
            if vendor != "netsuite":
                continue
            assert hasattr(transformer, transform), (
                f"netsuite/{entity} names transformer {transform!r}, which does not exist"
            )
            assert hasattr(analyzers, analyze), (
                f"netsuite/{entity} names analyzer {analyze!r}, which does not exist"
            )


class TestTheTransformerReadsNetSuitesFieldNames:
    def test_it_extracts_the_five_fields_the_analyzer_reads(self, transformer):
        normalized = transformer.transform_netsuite_invoice(_overdue_invoice())

        assert normalized["invoice_number"] == "INV-1001"
        assert normalized["due_date"] is not None
        assert normalized["supplier_id"] == "Acme Manufacturing"
        assert normalized["total_amount"] == pytest.approx(4820.50)
        assert normalized["status"] == "open"

    def test_a_reference_object_becomes_a_scalar(self, transformer):
        """SuiteTalk sends `{"id": …, "refName": …}` for status, entity and currency. A
        dict reaching the analyzer is truthy and never equal to a status string, so every
        comparison silently takes the wrong branch."""
        normalized = transformer.transform_netsuite_invoice(_overdue_invoice())
        for field in ("status", "supplier_id", "currency"):
            assert isinstance(normalized[field], str), (
                f"{field} came through as {type(normalized[field]).__name__}; a dict here "
                f"is truthy and compares unequal to every expected value"
            )

    def test_a_string_amount_becomes_a_number(self, transformer):
        """`"4820.50" > average * 5` raises TypeError in a swallowed background task."""
        normalized = transformer.transform_netsuite_invoice(_overdue_invoice())
        assert isinstance(normalized["total_amount"], float)

    @pytest.mark.parametrize(
        "netsuite_status,expected",
        [
            ("Paid In Full", "paid"),
            ("Open", "open"),
            ("Pending Approval", "open"),
            ("Voided", "cancelled"),
            ("Fully Billed", "closed"),
        ],
    )
    def test_the_status_vocabulary_is_translated(
        self, transformer, netsuite_status: str, expected: str
    ):
        """THE ONE THAT WOULD HAVE BEEN A CONFIDENT WRONG ANSWER. The analyzer tests
        `status != "paid"`. NetSuite never says "paid" — it says "Paid In Full" — so without
        this mapping **every settled invoice reports as overdue**. FS-435's shape: two
        vocabularies, no translation, and the result is wrong rather than broken."""
        record = {**_overdue_invoice(), "status": {"refName": netsuite_status}}
        assert transformer.transform_netsuite_invoice(record)["status"] == expected

    def test_the_sap_transformer_would_have_produced_nothing(self, transformer):
        """The registry's rule, demonstrated rather than asserted.

        Running SAP's invoice transformer over a SuiteTalk payload is what "reusing another
        vendor's transformer" means in practice, and the output is the argument against it.
        """
        wrong = transformer.transform_invoice(_overdue_invoice())
        assert wrong["invoice_number"] is None
        assert wrong["due_date"] is None
        assert wrong["total_amount"] is None, (
            "SAP's transformer produced a value from a NetSuite payload, which would make "
            "the registry's rule look over-cautious. It does not — every field it reads has "
            "a different name in SuiteTalk."
        )


@pytest.mark.asyncio
class TestARealPayloadProducesACorrelation:
    """The property the plan asks for: a vendor payload in, an anomaly out."""

    async def test_an_overdue_invoice_is_flagged(self, transformer, patterns):
        normalized = transformer.transform_netsuite_invoice(_overdue_invoice())
        result = await patterns.analyze_invoice_anomalies(_NoRows(), normalized)

        types = {a["type"] for a in result["anomalies"]}
        assert "overdue_invoice" in types, (
            f"a 45-day-overdue unpaid NetSuite invoice produced {result['anomalies']}. This "
            f"is the correlation the vendor has never produced."
        )
        assert result["risk_score"] > 0
        assert result["domain"] == "FINANCE"

    async def test_a_settled_invoice_is_not_flagged(self, transformer, patterns):
        """The other direction, and the one the status mapping exists for. Without it this
        invoice reports as overdue too, and every anomaly the vendor emits is noise."""
        record = {**_overdue_invoice(), "status": {"refName": "Paid In Full"}}
        normalized = transformer.transform_netsuite_invoice(record)
        result = await patterns.analyze_invoice_anomalies(_NoRows(), normalized)

        assert "overdue_invoice" not in {a["type"] for a in result["anomalies"]}, (
            "a fully paid invoice was reported overdue — the status vocabulary is not "
            "being translated"
        )

    async def test_stock_below_the_reorder_point_is_flagged(self, transformer, patterns):
        normalized = transformer.transform_netsuite_inventory(
            {
                "itemId": "WIDGET-9",
                "quantityAvailable": "12",
                "quantityOnHand": "80",
                "reorderPoint": "50",
                "location": {"refName": "Plant A"},
            }
        )
        result = await patterns.analyze_inventory_shortfall(_NoRows(), normalized)

        assert "below_reorder_point" in {a["type"] for a in result["anomalies"]}

    async def test_available_stock_is_used_not_on_hand(self, transformer, patterns):
        """`quantityOnHand` is 80 and `quantityAvailable` is 12 against a reorder point of
        50. Reading on-hand reports this as healthy — the direction that looks like good
        news, and the reason the field choice is asserted rather than commented."""
        normalized = transformer.transform_netsuite_inventory(
            {"itemId": "W-1", "quantityAvailable": "12", "quantityOnHand": "80",
             "reorderPoint": "50"}
        )
        assert normalized["quantity"] == pytest.approx(12.0)
        result = await patterns.analyze_inventory_shortfall(_NoRows(), normalized)
        assert result["anomalies"], "a real shortfall was reported as healthy"

    async def test_a_healthy_record_produces_no_anomaly(self, transformer, patterns):
        """Vacuity. An analyzer that flags everything is as useless as one that flags
        nothing, and only this direction distinguishes them."""
        normalized = transformer.transform_netsuite_inventory(
            {"itemId": "W-2", "quantityAvailable": "900", "reorderPoint": "50"}
        )
        result = await patterns.analyze_inventory_shortfall(_NoRows(), normalized)
        assert result["anomalies"] == []
        assert result["risk_score"] == 0


class _NoRows:
    """A session that answers every query with nothing.

    The two invoice checks that need history — the supplier average and the duplicate
    count — are exercised against real data elsewhere; here the subject is the transformer
    and analyzer pair, and a database would make the test about fixtures instead.
    """

    async def execute(self, _statement):
        class _Result:
            def scalar(self):
                return None

            def all(self):
                return []

        return _Result()
