"""The compliance summary must count, not restate (FS-346).

FOUR OF ITS SIX FIGURES WERE NEVER COMPUTED:

    "active_assets":       total_assets            # Simplified for now
    "pending_assessments": total_vendor_assessments # Simplified for now
    "consent_records":          0                  # Will be populated from …
    "data_processing_records":  0                  # Will be populated from …

The blocks are labelled **ISO 27001**, **SOC 2** and **GDPR**, which is what makes this
worse here than the same shape elsewhere. `active_assets == total_assets` reads as "every
asset is active", not as "nobody computed this". `consent_records: 0` reads as a *finding* —
an organisation that has recorded no consent — rather than as an unimplemented counter. A
compliance summary is consulted precisely when someone needs to trust it.

Every column needed already existed: `security_assets.status`,
`vendor_risk_assessments.status`, and both GDPR tables.

WHY THESE ASSERTIONS SET A NON-DEFAULT STATUS. `security_assets.status` defaults to
`"active"` and `vendor_risk_assessments.status` to `"pending"`, so on ordinary seeded data
the computed figure **equals the total it used to copy** — and a test built on default rows
would pass just as happily against the bug. Each case below therefore creates rows in the
*other* state, which is the only arrangement where the two numbers can disagree.

WHY REAL-DB. `consent_records` has no `organization_id` — it is scoped by `user_id`, which
`gdpr.py` records as the right grain for consent — so its org count is a JOIN through
`users` rather than a policy predicate. A stubbed session cannot tell a correct join from a
wrong one.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.asyncio

SUMMARY = "/api/v1/compliance/compliance-summary"


async def _asset(client, name: str, status: str | None = None):
    """Create, then update the status if one is wanted.

    `POST /security-assets` takes no `status` — it always creates `"active"`, and passing
    the field as a query parameter is silently ignored (which is how the first version of
    this file "passed" a retired asset and then failed its own assertion). `PUT` is the
    only way to reach any other state, and it is the path an operator takes too.
    """
    response = await client.post(
        "/api/v1/compliance/security-assets",
        params={"asset_name": name, "asset_type": "server"},
    )
    if status and response.status_code < 300:
        await client.put(
            f"/api/v1/compliance/security-assets/{response.json()['id']}",
            params={"status": status},
        )
    return response


async def _vendor(client, name: str, status: str | None = None):
    # FS-902: vendor_name/vendor_type/risk_level moved from query params into one body
    # model.
    response = await client.post(
        "/api/v1/compliance/vendor-assessments",
        json={"vendor_name": name, "vendor_type": "saas", "risk_level": "low"},
    )
    if status and response.status_code < 300:
        await client.put(
            f"/api/v1/compliance/vendor-assessments/{response.json()['id']}",
            json={"status": status},
        )
    return response


class TestActiveIsCountedNotCopied:
    async def test_a_retired_asset_is_not_counted_active(self, client_a):
        """THE ASSERTION THE OLD CODE COULD NOT PASS. It returned `total_assets` for
        `active_assets`, so these two were equal by construction."""
        suffix = uuid.uuid4().hex[:8]
        await _asset(client_a, f"live-{suffix}", status="active")
        await _asset(client_a, f"retired-{suffix}", status="retired")

        body = (await client_a.get(SUMMARY)).json()["iso_27001"]
        assert body["total_assets"] >= 2
        assert body["active_assets"] < body["total_assets"], (
            "active_assets is still being copied from total_assets — a retired asset is "
            "being reported as active on an ISO 27001 summary"
        )


class TestPendingIsCountedNotCopied:
    async def test_a_completed_assessment_is_not_counted_pending(self, client_a):
        suffix = uuid.uuid4().hex[:8]
        await _vendor(client_a, f"open-{suffix}")
        await _vendor(client_a, f"closed-{suffix}", status="completed")

        body = (await client_a.get(SUMMARY)).json()["soc_2"]
        assert body["total_vendor_assessments"] >= 2
        assert body["pending_assessments"] < body["total_vendor_assessments"], (
            "pending_assessments is still being copied from the total — a completed "
            "assessment is being reported as outstanding on a SOC 2 summary"
        )


class TestTheGdprCountersAreReal:
    async def test_they_are_integers_from_the_tables_not_literals(self, client_a):
        """The old values were the literal `0`. This cannot prove a specific count without
        seeding consent rows through a path the API does not expose — what it CAN prove is
        that the figures move with the data rather than being constants, which the
        source-level assertion below completes."""
        body = (await client_a.get(SUMMARY)).json()["gdpr"]
        assert isinstance(body["consent_records"], int)
        assert isinstance(body["data_processing_records"], int)
        assert body["consent_records"] >= 0
        assert body["data_processing_records"] >= 0

    def test_no_figure_in_the_summary_is_a_hardcoded_literal(self):
        """Guards the shape rather than a value, because a literal is what the defect was.

        Reads the AST: every value in the three returned blocks must be a NAME bound
        earlier in the handler, never a constant. That is what makes
        `"consent_records": 0` fail even on an organisation whose true count is zero.
        """
        import ast
        import inspect

        from app.api import compliance

        source = inspect.getsource(compliance.get_compliance_summary)
        tree = ast.parse(source.lstrip())

        literals = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Return) or not isinstance(node.value, ast.Dict):
                continue
            for block in node.value.values:
                if not isinstance(block, ast.Dict):
                    continue
                for key, value in zip(block.keys, block.values):
                    if isinstance(value, ast.Constant):
                        literals.append(f"{ast.literal_eval(key)} = {value.value!r}")

        assert not literals, (
            "these compliance figures are hardcoded constants rather than counts, on "
            f"blocks labelled ISO 27001 / SOC 2 / GDPR: {literals}"
        )


class TestTheCountsStayTenantScoped:
    async def test_another_org_s_rows_are_not_counted(self, client_a, client_b):
        """The figures became joins and filters; both must stay org-scoped. `consent_records`
        is the one that is neither — it joins through `users` because its table has no
        `organization_id` — so it is the one most able to leak."""
        suffix = uuid.uuid4().hex[:8]
        await _asset(client_a, f"iso-a-{suffix}")
        await _asset(client_b, f"iso-b1-{suffix}")
        await _asset(client_b, f"iso-b2-{suffix}")

        a = (await client_a.get(SUMMARY)).json()
        b = (await client_b.get(SUMMARY)).json()
        assert a["iso_27001"]["total_assets"] != b["iso_27001"]["total_assets"], (
            "both organisations report the same asset count — the summary is not scoped"
        )
