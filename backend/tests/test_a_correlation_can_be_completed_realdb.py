"""The behavioural half of FS-676, against a real database.

`test_a_correlation_can_be_completed.py` proves the route declares a JSON body and the schema
carries the endpoint fields. Neither says the update is applied: a body can be accepted,
validated, and dropped — which is precisely what the previous version of this route did with
one, and it answered 200 while doing it.

So this creates a correlation with **no source and no target**, sends a body naming both, and
reads it back through the API.
"""

from __future__ import annotations

from uuid import uuid4

import pytest

pytestmark = pytest.mark.asyncio

CORRELATIONS = "/api/v1/registries/correlations"


def _drop(admin_sync_url, correlation_id):
    import psycopg2

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute("DELETE FROM data_correlations WHERE id = %s;", (str(correlation_id),))
    finally:
        conn.close()


async def _create_endpointless(client_a):
    response = await client_a.post(
        CORRELATIONS,
        json={
            "correlation_type": "task_to_asset",
            "source_type": "task",
            "target_type": "asset",
        },
    )
    assert response.status_code in (200, 201), response.text
    body = response.json()
    assert body["source_id"] is None and body["target_id"] is None, (
        "the premise is gone: a correlation can no longer be created without endpoints, so "
        "the defect this file describes cannot occur and the reasoning needs re-reading"
    )
    return body["id"]


async def test_a_correlation_created_without_endpoints_can_be_given_them(
    client_a, admin_sync_url
):
    correlation_id = await _create_endpointless(client_a)
    source, target = uuid4(), uuid4()
    try:
        response = await client_a.put(
            f"{CORRELATIONS}/{correlation_id}",
            json={"source_id": str(source), "target_id": str(target)},
        )
        assert response.status_code == 200, response.text
        assert response.json()["source_id"] == str(source)
        assert response.json()["target_id"] == str(target)
    finally:
        _drop(admin_sync_url, correlation_id)


async def test_the_three_original_fields_still_update(client_a, admin_sync_url):
    """Moving from query parameters to a body must not lose the three fields that did work,
    which is the failure mode of every contract change made in a hurry."""
    correlation_id = await _create_endpointless(client_a)
    try:
        response = await client_a.put(
            f"{CORRELATIONS}/{correlation_id}",
            json={"correlation_strength": 90, "confidence_score": 75, "is_active": False},
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["correlation_strength"] == 90
        assert body["confidence_score"] == 75
        assert body["is_active"] is False
    finally:
        _drop(admin_sync_url, correlation_id)


async def test_an_omitted_field_is_left_alone(client_a, admin_sync_url):
    """`exclude_unset` asserted where it matters — against the row, not the model."""
    correlation_id = await _create_endpointless(client_a)
    try:
        await client_a.put(
            f"{CORRELATIONS}/{correlation_id}", json={"correlation_strength": 90}
        )
        response = await client_a.put(
            f"{CORRELATIONS}/{correlation_id}", json={"confidence_score": 60}
        )
        assert response.status_code == 200, response.text
        body = response.json()
        assert body["confidence_score"] == 60
        assert body["correlation_strength"] == 90, (
            "the second update blanked a field it never mentioned; the handler is applying "
            "the whole model rather than the fields the caller set"
        )
    finally:
        _drop(admin_sync_url, correlation_id)


async def test_another_tenants_correlation_is_not_updatable(
    client_a, client_b, admin_sync_url
):
    """The route filters on `organization_id` and the widening gave callers eight more
    fields to write. That check is worth asserting now rather than assuming."""
    correlation_id = await _create_endpointless(client_a)
    try:
        response = await client_b.put(
            f"{CORRELATIONS}/{correlation_id}", json={"correlation_strength": 1}
        )
        assert response.status_code in (403, 404), response.text

        mine = await client_a.get(f"{CORRELATIONS}/{correlation_id}")
        if mine.status_code == 200:
            assert mine.json()["correlation_strength"] != 1, (
                "another tenant's write landed on this row"
            )
    finally:
        _drop(admin_sync_url, correlation_id)
