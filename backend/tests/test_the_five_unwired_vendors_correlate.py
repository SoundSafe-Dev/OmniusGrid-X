"""All five previously-unrouted vendors produce a correlation (FS-557..561).

Odoo, Infor, Epicor, Intuit and NetSuite each had a working connector, stored raw records, and
`route_for()` returning `None`. Every sync completed, wrote its rows, and reported
`skipped: unrouted` — **a successful integration with an empty correlation list, and nothing
anywhere saying the vendor was never analysed.**

WHAT THIS FILE ASSERTS THAT THE PER-VENDOR TESTS DO NOT. That the five behave the *same way* on
the same question. Each vendor spells settlement differently, and a per-vendor test can pass
while the five disagree about what "paid" means — at which point a cross-vendor correlation
view is comparing incomparable things and nothing fails.

**THE FIVE SPELLINGS OF "THIS INVOICE IS SETTLED":**

| vendor | field | settled looks like |
|---|---|---|
| NetSuite | `status` | the string `"Paid In Full"` |
| Odoo | `payment_state` | the string `"paid"` — and `state: "posted"` is NOT it |
| Infor | `Status` | the string `"Paid"` |
| Epicor | `OpenInvoice` | the **boolean** `False` |
| Intuit | `Balance` | the **number** `0` — there is no status field at all |

Two of the five carry settlement in a field that is not a status, and one of those is a
boolean whose *false* value means paid. A transformer that looks for a status string finds
nothing on either, leaves it `None`, and `None != "paid"` — so **every Epicor and every
QuickBooks invoice would be reported overdue the moment its due date passed**. Not an error: a
confident wrong answer, on a finance screen, for two entire vendors.

That is FS-435's shape — two vocabularies with no translation — five times over, which is why
it is asserted as a table here rather than five times separately.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from importlib import import_module
from typing import Any, Dict

import pytest

from app.services.erp_data_transformer import ERPDataTransformer
from app.services.erp_sync_correlation import (
    CORRELATION_ROUTES,
    PATTERN_CLASSES,
    route_for,
)

ORG = uuid.uuid4()
INTEGRATION = uuid.uuid4()

OVERDUE = (datetime.now(timezone.utc) - timedelta(days=45)).date().isoformat()

#: (vendor, entity, an overdue-unpaid payload, the same payload settled).
#:
#: Written as raw vendor records, not normalized ones — the transformer is half of what is
#: under test, and a normalized fixture would skip it.
VENDORS: Dict[str, Dict[str, Any]] = {
    "netsuite": {
        "entity": "invoice",
        "unpaid": {
            "tranId": "INV-1",
            "dueDate": OVERDUE,
            "total": "500.00",
            "status": {"refName": "Open"},
            "entity": {"refName": "Acme"},
        },
        "settled": {
            "tranId": "INV-1",
            "dueDate": OVERDUE,
            "total": "500.00",
            "status": {"refName": "Paid In Full"},
            "entity": {"refName": "Acme"},
        },
    },
    "odoo": {
        "entity": "account.move",
        "unpaid": {
            "name": "INV/2026/0001",
            "invoice_date_due": OVERDUE,
            "amount_total": 500.0,
            "partner_id": [7, "Acme"],
            "payment_state": "not_paid",
            "state": "posted",
        },
        "settled": {
            "name": "INV/2026/0001",
            "invoice_date_due": OVERDUE,
            "amount_total": 500.0,
            "partner_id": [7, "Acme"],
            "payment_state": "paid",
            "state": "posted",
        },
    },
    "infor": {
        "entity": "invoice",
        "unpaid": {
            "InvoiceNumber": "I-1",
            "DueDate": OVERDUE,
            "TotalAmount": "500.00",
            "Status": "Open",
        },
        "settled": {
            "InvoiceNumber": "I-1",
            "DueDate": OVERDUE,
            "TotalAmount": "500.00",
            "Status": "Paid",
        },
    },
    "epicor": {
        "entity": "Erp.BO.InvoiceSvc",
        # BOOLEAN, not a status string.
        "unpaid": {"InvoiceNum": "E-1", "DueDate": OVERDUE, "InvoiceAmt": "500.00",
                   "OpenInvoice": True},
        "settled": {"InvoiceNum": "E-1", "DueDate": OVERDUE, "InvoiceAmt": "500.00",
                    "OpenInvoice": False},
    },
    "intuit": {
        "entity": "Invoice",
        # NUMBER, and there is no status field on a QBO invoice at all.
        "unpaid": {"DocNumber": "1001", "DueDate": OVERDUE, "TotalAmt": 500.0,
                   "Balance": 500.0, "CustomerRef": {"name": "Acme"}},
        "settled": {"DocNumber": "1001", "DueDate": OVERDUE, "TotalAmt": 500.0,
                    "Balance": 0, "CustomerRef": {"name": "Acme"}},
    },
}


class _NoRows:
    """A session answering every query with nothing — the subject here is the pair."""

    async def execute(self, _statement):
        class _Result:
            def scalar(self):
                return None

            def all(self):
                return []

        return _Result()


def _analyzers(vendor: str):
    module_path, class_name = PATTERN_CLASSES[vendor]
    return getattr(import_module(module_path), class_name)(str(ORG), str(INTEGRATION))


@pytest.fixture
def transformer() -> ERPDataTransformer:
    return ERPDataTransformer(organization_id=ORG, integration_id=INTEGRATION)


@pytest.mark.parametrize("vendor", sorted(VENDORS))
class TestEveryVendorIsRoutedAndAnalysed:
    def test_the_entity_resolves(self, vendor: str, transformer):
        assert route_for(vendor, VENDORS[vendor]["entity"]) is not None, (
            f"{vendor} is unrouted, so its syncs report `skipped: unrouted` and produce no "
            f"correlation while reporting success"
        )

    def test_the_named_methods_exist(self, vendor: str, transformer):
        """A registry entry is a claim about two method names. A typo in either is an
        AttributeError inside a background sync, where it is swallowed and the vendor
        silently stops being analysed."""
        transform, analyze = route_for(vendor, VENDORS[vendor]["entity"])
        assert hasattr(transformer, transform), f"{vendor}: no transformer {transform!r}"
        assert hasattr(_analyzers(vendor), analyze), f"{vendor}: no analyzer {analyze!r}"

    def test_the_transformer_reads_the_vendors_own_names(self, vendor: str, transformer):
        """The registry's rule: a transformer must read THAT vendor's fields. If it returns
        a record of Nones the analyzer finds nothing wrong — a clean bill of health rather
        than an error, which is the failure that survives."""
        transform, _ = route_for(vendor, VENDORS[vendor]["entity"])
        record = getattr(transformer, transform)(VENDORS[vendor]["unpaid"])
        assert record["invoice_number"], f"{vendor}: invoice_number came through empty"
        assert record["due_date"], f"{vendor}: due_date came through empty"
        assert isinstance(record["total_amount"], float), (
            f"{vendor}: total_amount is {type(record['total_amount']).__name__}, and a "
            f"comparison against an average raises TypeError inside a swallowed sync"
        )

    @pytest.mark.asyncio
    async def test_an_overdue_unpaid_invoice_is_flagged(self, vendor: str, transformer):
        transform, analyze = route_for(vendor, VENDORS[vendor]["entity"])
        record = getattr(transformer, transform)(VENDORS[vendor]["unpaid"])
        result = await getattr(_analyzers(vendor), analyze)(_NoRows(), record)

        assert "overdue_invoice" in {a["type"] for a in result["anomalies"]}, (
            f"{vendor}: a 45-day-overdue unpaid invoice produced {result['anomalies']}. "
            f"This is the correlation the vendor has never produced."
        )

    @pytest.mark.asyncio
    async def test_a_settled_invoice_is_not_flagged(self, vendor: str, transformer):
        """THE ASSERTION THAT MATTERS MOST, and the one each vendor spells differently.

        Epicor carries settlement as `OpenInvoice: False` and Intuit as `Balance: 0` —
        neither is a status string. A transformer looking for one leaves `status` as None,
        and `None != "paid"` is true, so **every invoice from those two vendors reports
        overdue** the moment its due date passes. On a finance screen, for an entire
        vendor, with no error anywhere.
        """
        transform, analyze = route_for(vendor, VENDORS[vendor]["entity"])
        record = getattr(transformer, transform)(VENDORS[vendor]["settled"])
        assert record["status"] == "paid", (
            f"{vendor}: a settled invoice normalized to status={record['status']!r}. The "
            f"analyzer tests `status != 'paid'`, so anything else reports it overdue."
        )

        result = await getattr(_analyzers(vendor), analyze)(_NoRows(), record)
        assert "overdue_invoice" not in {a["type"] for a in result["anomalies"]}, (
            f"{vendor}: a settled invoice was reported overdue"
        )

    @pytest.mark.asyncio
    async def test_the_result_names_its_source_system(self, vendor: str, transformer):
        """A cross-vendor correlation view has to say which system a finding came from, or
        the five become indistinguishable the moment they are listed together."""
        transform, analyze = route_for(vendor, VENDORS[vendor]["entity"])
        record = getattr(transformer, transform)(VENDORS[vendor]["unpaid"])
        result = await getattr(_analyzers(vendor), analyze)(_NoRows(), record)
        assert result["source_system"].lower().replace(" ", "") == vendor.lower()


class TestTheFiveAgreeOnWhatSettledMeans:
    def test_every_vendor_normalizes_settlement_to_the_same_token(self, transformer):
        """One assertion over all five, because the failure this prevents is DISAGREEMENT.
        Five per-vendor tests can each pass while the vendors normalize to five different
        strings — and then a cross-vendor view compares incomparable values and nothing
        fails."""
        tokens = {}
        for vendor, spec in VENDORS.items():
            transform, _ = route_for(vendor, spec["entity"])
            tokens[vendor] = getattr(transformer, transform)(spec["settled"])["status"]

        assert set(tokens.values()) == {"paid"}, (
            f"the five vendors normalize a settled invoice to {tokens}. They must agree on "
            f"one token or the shared analyzer means something different per vendor."
        )

    def test_none_of_them_leaves_status_unset(self, transformer):
        """The specific failure for Epicor and Intuit, which have no status field. `None`
        is not `"paid"`, so an unset status reports every invoice overdue."""
        for vendor, spec in VENDORS.items():
            transform, _ = route_for(vendor, spec["entity"])
            for state in ("unpaid", "settled"):
                status = getattr(transformer, transform)(spec[state])["status"]
                assert status is not None, (
                    f"{vendor} left status unset for a {state} invoice. The analyzer tests "
                    f"`status != 'paid'`, and None satisfies that for every record."
                )


class TestTheRegistryCoversWhatTheConnectorsFetch:
    def test_no_vendor_has_a_pattern_class_and_no_routes(self):
        """A pattern class with no routes is unreachable, and reads as support for a vendor
        that is still skipped. The mirror of the case `route_for` already refuses."""
        routed = {vendor for vendor, _ in CORRELATION_ROUTES}
        orphaned = sorted(set(PATTERN_CLASSES) - routed)
        assert not orphaned, (
            f"{orphaned} have a pattern class registered and no entity routed to it, so "
            f"they are listed as supported and produce nothing"
        )

    def test_no_route_names_an_unregistered_vendor(self):
        """The half-finished registration `route_for` fails closed on. Asserted here so it
        is a build failure rather than a silently unrouted vendor."""
        unregistered = sorted(
            {vendor for vendor, _ in CORRELATION_ROUTES} - set(PATTERN_CLASSES)
        )
        assert not unregistered, (
            f"{unregistered} have routes and no PATTERN_CLASSES entry. `route_for` returns "
            f"None for them — correctly, and silently — so every sync reports "
            f"`skipped: unrouted` while the registry looks complete."
        )
