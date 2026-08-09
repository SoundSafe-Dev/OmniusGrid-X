"""A residency check must not score 100% on data it never looked at (FS-347).

THE DEFECT. `validate_data_residency` set `total_records = tagged_records`, so
`untagged_records` was always `0` and `compliance_percentage` divided the correctly-tagged
rows by the tagged rows. An organisation with one tagged row and ten thousand untagged ones
scored **100%** — on a check whose entire purpose is finding data that is not where it
should be. **The untagged rows are the finding, and they were exactly what it could not
see.**

WHY THE FIX IS AN ADMISSION RATHER THAN A REAL COUNT. Counting the target table is not
safely available from this endpoint:

  * `table_names` is caller-supplied, so a real count means putting a caller's string in an
    identifier position;
  * the handler runs on `get_db`, which binds no tenant GUC — counting an RLS-protected
    table through it returns 0, so the "real" total would be a fresh wrong number;
  * `data_residency_tags` has no `organization_id`, so its rows and a per-tenant row count
    are not the same population.

A cross-tenant count needs the platform-admin role that does not exist (FS-311). So the
endpoint reports the ratio it genuinely computes, names it `tagged_region_percentage` after
what it is over, and returns `None` for the two figures it cannot know.

THIS FILE EXISTS BECAUSE THE ENDPOINT HAD NO BEHAVIOURAL TEST. Only `test_route_auth_walk`
touched it, which checks that it requires auth and nothing else — so when the rename left a
stale `validation_results["compliance_percentage"]` in the logger call, a **full green
suite** ran straight past a `KeyError` on the response path. A route that is only walked is
a route whose body is unexecuted.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio

VALIDATE = "/api/v1/data-residency/validate"
TAG = "/api/v1/data-residency/tag"


async def _tag(client, table: str, record_id: str, region: str):
    return await client.post(
        TAG,
        params={"table_name": table, "record_id": record_id, "region": region},
    )


class TestTheEndpointRuns:
    async def test_validate_returns_200_and_not_a_key_error(self, client_a):
        """The assertion that would have caught the stale logger key. Deliberately the
        first test in the file: everything below is worthless if the body cannot execute."""
        response = await client_a.post(VALIDATE, json=["assets"])
        assert response.status_code == 200, response.text


class TestItDoesNotClaimCoverageItLacks:
    async def test_untagged_and_total_are_null_not_zero(self, client_a):
        """Zero would assert that nothing is untagged, which is the original defect stated
        as a number instead of a formula."""
        body = (await client_a.post(VALIDATE, json=["assets"])).json()
        assert body["untagged_records"] is None
        assert body["total_records"] is None

    async def test_the_response_says_what_it_could_not_see(self, client_a):
        body = (await client_a.post(VALIDATE, json=["assets"])).json()
        assert "not visible to this check" in body["coverage_warning"]

    async def test_the_old_field_name_is_gone(self, client_a):
        """`compliance_percentage` is the claim this endpoint cannot support: it reads as a
        statement about the table while being computed over the tagged subset."""
        body = (await client_a.post(VALIDATE, json=["assets"])).json()
        assert "compliance_percentage" not in body
        assert "tagged_region_percentage" in body


class TestTheRatioItDoesComputeIsRight:
    async def test_a_tag_outside_the_expected_region_lowers_the_percentage(self, client_a):
        """The mismatch has to come from the QUERY, not the tag.

        `POST /tag` accepts `"USA"` and nothing else (`data_residency.py:112`), so a
        wrong-region tag cannot be created through the API at all — an earlier version of
        this test tried and got a 400. Asking whether USA-tagged rows are in `EU` is the
        reachable way to make `correct` and `incorrect` differ, and it is also the real
        question an auditor asks: *is this data where THIS regulation requires?*
        """
        table = f"probe_{uuid.uuid4().hex[:8]}"
        await _tag(client_a, table, "rec-1", "USA")
        await _tag(client_a, table, "rec-2", "USA")

        body = (
            await client_a.post(VALIDATE, json=[table], params={"expected_region": "EU"})
        ).json()
        assert body["tagged_records"] == 2
        assert body["correct_region_records"] == 0
        assert body["incorrect_region_records"] == 2
        assert body["tagged_region_percentage"] == pytest.approx(0.0), (
            "two USA-tagged rows must not score as compliant with an EU expectation"
        )

    async def test_all_correct_is_a_hundred_percent_of_the_tagged_subset(self, client_a):
        """100% is still reachable — and now it means "every tagged row is in the expected
        region", which is what the field name says, rather than "the table is compliant"."""
        table = f"probe_{uuid.uuid4().hex[:8]}"
        await _tag(client_a, table, "rec-1", "USA")

        body = (await client_a.post(VALIDATE, json=[table])).json()
        assert body["tagged_region_percentage"] == pytest.approx(100.0)
        assert body["untagged_records"] is None, (
            "100% of the tagged rows must still not imply that none are untagged"
        )

    async def test_no_tags_is_zero_percent_and_not_a_division_error(self, client_a):
        table = f"empty_{uuid.uuid4().hex[:8]}"
        body = (await client_a.post(VALIDATE, json=[table])).json()
        assert body["tagged_records"] == 0
        assert body["tagged_region_percentage"] == 0.0
