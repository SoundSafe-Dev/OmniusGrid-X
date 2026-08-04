"""Direct behavioral coverage for :class:`HTTPRestCollector`.

The collector is exercised with an asynchronous fake client so parsing,
normalization, emission, and error recovery run without opening a socket.
"""

import json
from datetime import datetime
from unittest import mock

import httpx
import pytest

import opsgrid_agent.collectors.http_rest as http_rest_module
from opsgrid_agent.collectors.http_rest import HTTPRestCollector


FIXED_TIME = datetime(2026, 9, 28, 12, 30, 0)
URL = "https://gateway.example.test/api/telemetry"


def _response(payload):
    response = mock.Mock(status_code=200)
    response.json.return_value = payload
    return response


def _collector(responses):
    collector = HTTPRestCollector({
        "asset_id": "gateway-001",
        "url": URL,
        "method": "POST",
        "params": {"line": "A"},
    })
    collector.client = mock.Mock()
    collector.client.request = mock.AsyncMock(side_effect=responses)
    return collector


@pytest.mark.asyncio
async def test_collect_requests_endpoint_and_emits_normalized_json():
    collector = _collector([_response({
        "temperature": 72.5,
        "running": True,
        "metadata": {
            "line": "A",
            "sequence": 41,
            "ignored": ["nested", "list"],
        },
        "ignored": ["top-level", "list"],
        "missing": None,
    })])
    emitted = []
    collector.add_data_handler(emitted.append)

    with mock.patch.object(http_rest_module, "datetime") as fake_datetime:
        fake_datetime.now.return_value = FIXED_TIME
        await collector._collect()

    collector.client.request.assert_awaited_once_with(
        method="POST",
        url=URL,
        params={"line": "A"},
    )
    assert emitted == [{
        "timestamp_edge": "2026-09-28T12:30:00",
        "asset_id": "gateway-001",
        "topic": "telemetry",
        "payload": {
            "temperature": 72.5,
            "running": True,
            "metadata_line": "A",
            "metadata_sequence": 41,
        },
    }]


@pytest.mark.asyncio
async def test_collect_preserves_a_primitive_list_response_as_one_batch():
    batch = [10.5, 11.0, 12.25]
    collector = _collector([_response(batch)])
    emitted = []
    collector.add_data_handler(emitted.append)

    with mock.patch.object(http_rest_module, "datetime") as fake_datetime:
        fake_datetime.now.return_value = FIXED_TIME
        await collector._collect()

    assert [message["payload"] for message in emitted] == [{"value": batch}]


@pytest.mark.asyncio
async def test_malformed_json_is_skipped_and_the_next_poll_still_emits():
    malformed = _response(None)
    malformed.json.side_effect = json.JSONDecodeError(
        "Expecting value",
        "<html>secret-response-body</html>",
        0,
    )
    valid = _response({"temperature": 68.0})
    collector = _collector([malformed, valid])
    emitted = []
    collector.add_data_handler(emitted.append)

    with (
        mock.patch.object(http_rest_module, "datetime") as fake_datetime,
        mock.patch.object(http_rest_module, "logger") as collector_logger,
    ):
        fake_datetime.now.return_value = FIXED_TIME
        await collector._collect()
        await collector._collect()

    assert [message["payload"] for message in emitted] == [{"temperature": 68.0}]
    assert collector.client.request.await_count == 2
    collector_logger.error.assert_called_once()
    error_call = collector_logger.error.call_args
    assert error_call.args == ("http_collection_error",)
    assert error_call.kwargs["asset_id"] == "gateway-001"
    assert error_call.kwargs["url"] == URL
    assert "secret-response-body" not in error_call.kwargs["error"]


@pytest.mark.asyncio
async def test_http_error_is_logged_without_emitting_a_record():
    request = httpx.Request("POST", URL)
    upstream_response = httpx.Response(503, request=request)
    response = mock.Mock(status_code=503)
    response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "upstream unavailable",
        request=request,
        response=upstream_response,
    )
    collector = _collector([response])
    emitted = []
    collector.add_data_handler(emitted.append)

    with mock.patch.object(http_rest_module, "logger") as collector_logger:
        await collector._collect()

    assert emitted == []
    collector_logger.error.assert_called_once_with(
        "http_request_failed",
        asset_id="gateway-001",
        url=URL,
        error="upstream unavailable",
    )
