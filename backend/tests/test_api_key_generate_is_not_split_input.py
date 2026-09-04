"""POST /api-keys/generate reads name, scopes and expires_in_days from one body (FS-902).

THE DEFECT. `name` and `expires_in_days` were bare, non-Pydantic scalars -- FastAPI reads
those from the QUERY STRING -- while `scopes: List[str]` is a list, which FastAPI reads
from the BODY. No single request a client sends fills both halves: a body-only POST
(`{"name": ..., "scopes": [...], "expires_in_days": ...}`) had `scopes` accepted and
`name`/`expires_in_days` silently fall to their query-string defaults -- a credential
minted with a default name and no expiry, answering 200 rather than 422.
"""
from __future__ import annotations

import pytest


@pytest.mark.asyncio
class TestGenerateReadsEverythingFromOneBody:
    async def test_a_body_only_call_sets_the_name_and_expiry(self, client_a):
        response = await client_a.post(
            "/api/v1/api-keys/generate",
            json={
                "name": "ci-integration",
                "scopes": ["read", "write"],
                "expires_in_days": 30,
            },
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["name"] == "ci-integration", (
            "name fell back to a query-string default despite being sent in the body -- "
            "the split-input defect is back"
        )
        assert body["scopes"] == ["read", "write"]
        assert body["expires_at"] is not None, (
            "expires_in_days fell back to its query-string default (None/no expiry) "
            "despite being sent in the body"
        )

    async def test_a_query_string_call_is_refused_not_silently_defaulted(self, client_a):
        """The old shape -- name/expires_in_days as query params -- must now 422, not
        succeed with scopes silently dropped to the body's own default. A 422 here is
        the guard against the split ever coming back."""
        response = await client_a.post(
            "/api/v1/api-keys/generate",
            params={"name": "should-not-work", "expires_in_days": 1},
        )
        assert response.status_code == 422, (
            f"expected the body-only contract to refuse query-string input; got "
            f"{response.status_code}: {response.text}"
        )
