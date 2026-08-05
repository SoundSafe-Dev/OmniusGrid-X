"""Routing a correlation analysis to a domain (FS-444).

`correlation_registry_integration` is 1,130 lines with one test reference, and it is the
service that turns an AI analysis into **work someone is assigned**: a registry item and a
Kanban task per detected domain. Everything downstream of `_extract_domains_from_analysis`
inherits whatever that function decides.

THE DEFECT THAT WAS IN IT. Domain detection was `keyword in analysis_lower` — a SUBSTRING
test — and the short keywords are inside ordinary words this domain uses constantly:

    "Line CAPAcity was reduced by 12%"       -> QUALITY_CONTROL        (capa)
    "The valve was ISOlated for servicing"   -> COMPLIANCE_REGISTRIES  (iso)
    "Throughput is exCELLent"                -> PRODUCTION_OEE         (cell)
    "Two orders were canCELLed"              -> PRODUCTION_OEE         (cell)

`capa` is Corrective And Preventive Action and `iso` is the standards body, so a routine note
about capacity opened a formal quality item and a valve isolation opened an ISO compliance
item. Not cosmetic: a task is created and assigned, and the analysis text is quoted into the
item — which makes the mismatch read as a judgement someone made rather than a string bug.

The fix is word boundaries. These tests assert both halves: the false positives are gone AND
the true positives still fire, because a matcher that matches nothing also has no false
positives.
"""

from __future__ import annotations

import inspect
import re

import pytest

from app.services.correlation_registry_integration import (
    DOMAIN_REGISTRY_MAPPING,
    correlation_registry_integration as integration,
)


def _domains(text: str) -> list[str]:
    return integration._extract_domains_from_analysis(text)


class TestASubstringIsNotAMatch:
    """Each of these routed work to a domain the analysis never mentioned."""

    @pytest.mark.parametrize(
        "text,wrong_domain,inner",
        [
            ("Line capacity was reduced by 12% during the shift.", "QUALITY_CONTROL", "capa"),
            ("The valve was isolated for servicing.", "COMPLIANCE_REGISTRIES", "iso"),
            ("Cycle counts are excellent this week.", "PRODUCTION_OEE", "cell"),
            ("Two customer orders were cancelled.", "PRODUCTION_OEE", "cell"),
        ],
    )
    def test_an_ordinary_word_does_not_route_work(self, text, wrong_domain, inner):
        assert wrong_domain not in _domains(text), (
            f"{text!r} was routed to {wrong_domain} because {inner!r} appears INSIDE a "
            f"word. A registry item and a Kanban task are created per detected domain, so "
            f"someone is assigned work in a domain nobody mentioned"
        )


class TestTheRealKeywordsStillMatch:
    """The other half. A matcher that matches nothing has no false positives either."""

    @pytest.mark.parametrize(
        "text,expected",
        [
            ("CAPA raised after the defect was confirmed.", "QUALITY_CONTROL"),
            ("ISO 9001 audit scheduled for March.", "COMPLIANCE_REGISTRIES"),
            ("Work cell 4 is down.", "PRODUCTION_OEE"),
            ("Trailer detention at the dock exceeded two hours.", "LOGISTICS_FLEET"),
            ("Vibration on the pump; work order raised.", "MAINTENANCE"),
            ("Near-miss reported in the packing area.", "SAFETY"),
            ("Warehouse slot utilisation is at 94%.", "WAREHOUSE_MANAGEMENT"),
            ("Database latency spiked overnight.", "SYSTEM_INFRASTRUCTURE"),
        ],
    )
    def test_the_domain_is_detected(self, text, expected):
        assert expected in _domains(text), (
            f"{text!r} no longer routes to {expected}; word-boundary matching has gone too "
            f"far and real analyses now reach no domain at all"
        )

    def test_a_multi_word_keyword_matches(self):
        """`work order`, `first pass yield`, `cycle time`, `error rate` and `near-miss` all
        contain spaces or hyphens, which `\\b` handles — but only if the escape is right."""
        assert "PRODUCTION_OEE" in _domains("Cycle time drifted on line 2.")
        assert "QUALITY_CONTROL" in _domains("First pass yield fell to 91%.")

    def test_matching_is_case_insensitive(self):
        assert _domains("TRAILER DETENTION AT THE DOCK") == _domains(
            "trailer detention at the dock"
        )

    def test_several_domains_can_match_one_analysis(self):
        """A correlation spans domains — that is the point of the service."""
        found = _domains(
            "Trailer detention at the dock delayed the work order on work cell 4."
        )
        assert {"LOGISTICS_FLEET", "MAINTENANCE", "PRODUCTION_OEE"} <= set(found)


class TestTheDegenerateInputs:
    @pytest.mark.parametrize("text", ["", "   ", "12345", "?!?!"])
    def test_nothing_recognisable_routes_nowhere(self, text):
        assert _domains(text) == []

    def test_it_does_not_raise_on_regex_metacharacters(self):
        """Analysis text is free-form model output. A `(` or `[` in it must not blow up the
        matcher now that keywords are compiled into a pattern — hence `re.escape`."""
        assert _domains("Rate was (high) [see appendix] +/- 3% \\\\ ^end$") == []


class TestEveryDetectableDomainCanReceiveAnItem:
    def test_no_extractable_domain_is_unmapped(self):
        """`_create_registry_item_from_analysis` returns None for a domain with no mapping —
        silently. A domain the extractor can name but the mapping does not know is an
        analysis that produces no item and no error."""
        source = inspect.getsource(integration._extract_domains_from_analysis)
        extractable = set(re.findall(r'"([A-Z_]+)":\s*\[', source))
        assert extractable, "the extractor's keyword table could not be read"
        unmapped = sorted(extractable - set(DOMAIN_REGISTRY_MAPPING))
        assert not unmapped, (
            f"these domains can be returned by the extractor and have no entry in "
            f"DOMAIN_REGISTRY_MAPPING, so an analysis matching them creates nothing and "
            f"reports nothing: {unmapped}"
        )

    def test_every_mapping_entry_has_the_keys_the_creator_reads(self):
        required = {"registry_type", "registry_name", "registry_category"}
        missing = {
            domain: sorted(required - set(config))
            for domain, config in DOMAIN_REGISTRY_MAPPING.items()
            if required - set(config)
        }
        assert not missing, f"mapping entries missing keys the creator reads: {missing}"

    def test_registry_names_are_unique(self):
        """Registries are looked up BY NAME (`registry_name == …`), not by domain. Two
        domains sharing a name would resolve to one registry and silently merge their
        items."""
        names = [c["registry_name"] for c in DOMAIN_REGISTRY_MAPPING.values()]
        duplicates = {n for n in names if names.count(n) > 1}
        assert not duplicates, (
            f"these registry names are shared by more than one domain, and lookup is by "
            f"name, so their items would merge into whichever registry was created first: "
            f"{sorted(duplicates)}"
        )


class TestTheRegistriesNothingCanFill:
    """RECORDED, NOT ASSERTED-AS-CORRECT (FS-444).

    `initialize_registries_for_organization` creates a registry for every mapped domain.
    Of the 46:

      *  8 can be returned by the extractor, so only those can receive an analysis-derived
         item
      *  5 also receive default items — a SUBSET of those 8, not a separate group, which is
         how a first reading of these numbers gets "13 reachable" instead of 8
      * 38 have neither and are created empty and stay empty

    On a compliance screen that reads as 38 programmes **not started** rather than 41 that
    **cannot be started**, which is a different fact and the more alarming one. Closing it
    means either giving those domains keywords and default items, or not creating a registry
    nothing can fill — a product decision, not a bug fix.

    These tests pin the numbers so the gap cannot drift silently in either direction.
    Whoever closes it should delete this class.
    """

    def _extractable(self) -> set[str]:
        source = inspect.getsource(integration._extract_domains_from_analysis)
        return set(re.findall(r'"([A-Z_]+)":\s*\[', source))

    def _with_defaults(self) -> set[str]:
        source = inspect.getsource(integration._get_default_items_for_domain)
        return set(re.findall(r'"([A-Z_]+)":\s*\[', source))

    def test_the_mapping_is_the_size_the_docstring_says(self):
        assert len(DOMAIN_REGISTRY_MAPPING) == 46, (
            f"the mapping now has {len(DOMAIN_REGISTRY_MAPPING)} domains; the docstring on "
            f"initialize_registries_for_organization names a count and is now wrong"
        )

    def test_the_reachable_fraction_has_not_shrunk(self):
        reachable = self._extractable() | self._with_defaults()
        assert len(reachable) >= 8, (
            f"only {len(reachable)} of {len(DOMAIN_REGISTRY_MAPPING)} domains can be "
            f"populated at all; the fraction that is a permanently empty shell has grown"
        )

    def test_the_unfillable_count_is_recorded(self):
        unfillable = set(DOMAIN_REGISTRY_MAPPING) - self._extractable() - self._with_defaults()
        assert len(unfillable) <= 38, (
            f"{len(unfillable)} registries are created with no default items and no way to "
            f"receive one from an analysis, up from 38. Each is an empty programme on a "
            f"compliance screen that looks not-started rather than impossible:\n  "
            + ", ".join(sorted(unfillable)[:12])
        )
