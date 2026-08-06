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
from uuid import uuid4

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


class TestNoRegistryIsCreatedThatNothingCanFill:
    """CLOSED (FS-467). This class used to record the gap rather than assert a fix.

    `initialize_registries_for_organization` created a registry for every one of the 46
    mapped domains. Only 8 can be returned by `_extract_domains_from_analysis`, and 5 of
    those also get default items — so **38 were created empty and stayed empty**, which on
    a compliance screen reads as 38 programmes not started rather than 38 that cannot be
    started. A different fact, and the more alarming one.

    Of the two ways to close it, writing extractor keywords and default items for 38
    speculative domains would have been product scope invented to satisfy a count.
    `INNOVATION_RD` and `KNOWLEDGE_MANAGEMENT` do not become real because a registry exists
    for them. So: the initializer creates only what something can fill.

    TWO THINGS MADE THAT SAFE TO DO.

    The creation set is DERIVED — `_fillable_domains()` reads the extractor and the
    default-items table, the same way these tests do, so giving a domain keywords is the
    only step needed to have its registry created. A hand-maintained list would be a second
    place to remember and a third number to drift.

    And `_create_registry_item_from_analysis` now creates a registry on demand. It carried
    the comment "Get or create registry for domain" above code that only got, returning
    None when it found nothing — so an item from a real analysis was dropped because a row
    was missing. Harmless while all 46 were pre-created; a silent loss the moment they were
    not. **Narrowing creation without fixing that would have traded a cosmetic problem for
    a data-loss one.**
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

    def test_the_service_agrees_with_this_test_about_what_is_fillable(self):
        """The guard and the code must read the same thing, or the guard is checking its
        own copy of the answer."""
        assert integration._fillable_domains() == (
            (self._extractable() | self._with_defaults()) & set(DOMAIN_REGISTRY_MAPPING)
        )

    @pytest.mark.asyncio
    async def test_the_initializer_creates_only_what_can_be_filled(self):
        """BEHAVIOURAL, not a source-text search.

        The first version of this asserted `"_fillable_domains()" in source` — and passed
        with the fix mutated out, because the string also appears in the docstring right
        above the code. A guard that greps its own explanation is worse than none. So this
        runs the initializer against a session that reports no existing rows and counts
        what it tries to add.
        """
        added: list = []

        class _Result:
            @staticmethod
            def scalar_one_or_none():
                return None

        class _Session:
            async def execute(self, *_a, **_k):
                return _Result()

            def add(self, obj):
                added.append(obj)

            async def commit(self):
                pass

            async def refresh(self, obj):
                obj.id = uuid4()

        org, user = uuid4(), uuid4()
        await integration.initialize_registries_for_organization(org, _Session(), user)

        registries = [o for o in added if type(o).__name__ == "ActionableRegistry"]
        created = {r.meta_data["domain"] for r in registries}
        assert created == integration._fillable_domains(), (
            f"the initializer created {len(created)} registries and the fillable set has "
            f"{len(integration._fillable_domains())}. Creating one for every mapped domain "
            f"leaves 38 empty programmes on a compliance screen that read as not-started "
            f"rather than impossible.\n  unexpected: "
            f"{sorted(created - integration._fillable_domains())}"
        )

    def test_an_unfillable_domain_is_not_in_the_creation_set(self):
        fillable = integration._fillable_domains()
        for domain in ("INNOVATION_RD", "KNOWLEDGE_MANAGEMENT", "ESG"):
            assert domain in DOMAIN_REGISTRY_MAPPING, f"{domain} left the mapping"
            assert domain not in fillable, (
                f"{domain} is now treated as fillable; if it genuinely gained extractor "
                f"keywords that is correct and this list should shrink"
            )

    def test_a_fillable_domain_still_is(self):
        """The other direction. A `_fillable_domains` that returned nothing would pass
        every assertion above and create no registries at all."""
        for domain in ("MAINTENANCE", "SAFETY", "QUALITY_CONTROL"):
            assert domain in integration._fillable_domains()

    def test_the_item_path_creates_a_registry_rather_than_dropping_the_item(self):
        source = inspect.getsource(integration._create_registry_item_from_analysis)
        assert "_ensure_registry(" in source, (
            "the analysis-to-item path no longer creates a missing registry. With the "
            "initializer narrowed, an item for a newly-extractable domain would be "
            "silently discarded — which is worse than the empty registries this replaced"
        )

