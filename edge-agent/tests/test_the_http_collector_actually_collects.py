"""Behavior tests for HTTP collection, poll health, and recovery.

All transport is stubbed. Expected network/status/decode failures remain retryable,
but are distinct from unexpected programming errors and visible through metrics plus
the real adapter/coordinator status seam.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest
from unittest.mock import patch

import httpx
from prometheus_client import REGISTRY
from structlog.testing import capture_logs

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from opsgrid_agent.collectors.adapter import coordinator_adapter  # noqa: E402
from opsgrid_agent.collectors.coordinator import (  # noqa: E402
    CollectorConfig,
    UnifiedCollectorCoordinator,
)
from opsgrid_agent.collectors.http_rest import HTTPRestCollector  # noqa: E402


class _Response:
    """The parts of `httpx.Response` this collector touches."""

    def __init__(self, payload, status_code: int = 200):
        self._payload = payload
        self.status_code = status_code

    def raise_for_status(self):
        if self.status_code >= 400:
            import httpx

            raise httpx.HTTPStatusError(
                f"{self.status_code}", request=None, response=None
            )

    def json(self):
        return self._payload


class _Client:
    """A transport double recording every request and replaying scripted responses."""

    def __init__(self, responses):
        self._responses = list(responses)
        self.requests: list[dict] = []
        self.closed = False

    async def request(self, method=None, url=None, params=None):
        self.requests.append({"method": method, "url": url, "params": params})
        outcome = self._responses.pop(0) if self._responses else _Response({})
        if isinstance(outcome, Exception):
            raise outcome
        return outcome

    async def aclose(self):
        self.closed = True


def _collector(config=None, responses=()):
    collector = HTTPRestCollector({"asset_id": "a1", "url": "https://device/api", **(config or {})})
    collector.client = _Client(responses)
    collector._running = True
    return collector


def _metric(name, asset_id, failure_class=None):
    labels = {"asset_id": asset_id, "collector_type": "http_rest"}
    if failure_class is not None:
        labels["failure_class"] = failure_class
    return REGISTRY.get_sample_value(name, labels) or 0.0


class ASuccessfulPollEmitsAReading(unittest.IsolatedAsyncioTestCase):
    async def test_the_reading_reaches_a_data_handler(self):
        """A successful poll must be distinguishable by a real emitted reading."""
        seen: list[dict] = []
        collector = _collector(responses=[_Response({"temperature": 41.2, "state": "RUN"})])
        collector.add_data_handler(seen.append)

        await collector._collect()

        self.assertEqual(
            len(seen),
            1,
            "a 200 with a JSON body produced no reading",
        )

    async def test_the_payload_survives_normalisation(self):
        seen: list[dict] = []
        collector = _collector(responses=[_Response({"temperature": 41.2, "state": "RUN"})])
        collector.add_data_handler(seen.append)

        await collector._collect()

        message = seen[0]
        self.assertEqual(message["asset_id"], "a1")
        self.assertEqual(message["topic"], "telemetry")
        self.assertEqual(message["payload"]["temperature"], 41.2)
        self.assertEqual(message["payload"]["state"], "RUN")
        self.assertIn("timestamp_edge", message)

    async def test_a_nested_object_is_flattened_not_dropped(self):
        """`_normalize_data` flattens one level. A REST endpoint that groups its readings —
        which is the common shape — depends on this working."""
        seen: list[dict] = []
        collector = _collector(
            responses=[_Response({"sensors": {"temp": 20.5, "rpm": 1500}, "ok": True})]
        )
        collector.add_data_handler(seen.append)

        await collector._collect()

        payload = seen[0]["payload"]
        self.assertEqual(payload["sensors_temp"], 20.5)
        self.assertEqual(payload["sensors_rpm"], 1500)
        self.assertEqual(payload["ok"], True)

    async def test_a_list_response_uses_its_first_object(self):
        seen: list[dict] = []
        collector = _collector(responses=[_Response([{"temperature": 12.0}, {"temperature": 99.0}])])
        collector.add_data_handler(seen.append)

        await collector._collect()

        self.assertEqual(seen[0]["payload"]["temperature"], 12.0)

    async def test_a_primitive_list_keeps_the_complete_payload(self):
        seen: list[dict] = []
        collector = _collector(responses=[_Response([1, "two", False])])
        collector.add_data_handler(seen.append)

        await collector._collect()

        self.assertEqual(seen[0]["payload"]["value"], [1, "two", False])
        self.assertEqual(seen[0]["collector_type"], "http_rest")

    async def test_the_request_goes_where_it_was_configured(self):
        collector = _collector(
            config={"method": "POST", "params": {"since": "1h"}},
            responses=[_Response({"v": 1})],
        )
        await collector._collect()

        self.assertEqual(collector.client.requests[0]["method"], "POST")
        self.assertEqual(collector.client.requests[0]["url"], "https://device/api")
        self.assertEqual(collector.client.requests[0]["params"], {"since": "1h"})


class AFailedPollDoesNotEndTheCollector(unittest.IsolatedAsyncioTestCase):
    async def test_a_transport_error_does_not_propagate(self):
        """It must not, or the poll loop dies on the first network blip. This asserts the
        swallow is deliberate at this one point — the tests above assert it is not hiding
        everything else."""
        collector = _collector(responses=[httpx.ConnectError("refused")])
        await collector._collect()  # must not raise

    async def test_the_next_poll_still_happens(self):
        """The failure that matters: one bad response silently ending the poll loop looks
        identical to a device that stopped reporting."""
        seen: list[dict] = []
        collector = _collector(
            responses=[httpx.ConnectError("refused"), _Response({"temperature": 7.0})]
        )
        collector.add_data_handler(seen.append)
        collector.poll_interval = 0

        loop_task = asyncio.create_task(collector._poll_loop())
        for _ in range(20):
            await asyncio.sleep(0)
            if seen:
                break
        collector._running = False
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        self.assertTrue(
            seen,
            "the poll loop produced nothing after a single connection error — one blip and "
            "the asset is silent for the life of the process",
        )

    async def test_a_non_json_body_does_not_propagate(self):
        """A 200 carrying an HTML error page is what a captive portal or a misrouted proxy
        looks like, and it is not a transport error."""

        class _NotJSON(_Response):
            def json(self):
                raise ValueError("Expecting value: line 1 column 1")

        collector = _collector(responses=[_NotJSON(None)])
        await collector._collect()  # must not raise


class FailedPollsAreObservable(unittest.IsolatedAsyncioTestCase):
    async def test_an_http_status_emits_nothing_and_records_the_failure(self):
        asset_id = "http-status-test"
        before = _metric(
            "edge_collector_poll_failures_total", asset_id, "http_status"
        )
        seen: list[dict] = []
        collector = _collector(
            config={"asset_id": asset_id},
            responses=[_Response({"raw": "do-not-emit"}, status_code=503)],
        )
        collector.add_data_handler(seen.append)

        collected = await collector._collect()

        self.assertFalse(collected)
        self.assertEqual(seen, [])
        self.assertEqual(
            _metric("edge_collector_poll_failures_total", asset_id, "http_status"),
            before + 1,
        )
        self.assertEqual(
            collector.health_status,
            {
                "state": "degraded",
                "healthy": False,
                "consecutive_failures": 1,
                "last_success_at": None,
                "last_failure_at": collector.health_status["last_failure_at"],
                "last_failure_class": "http_status",
            },
        )
        self.assertIsNotNone(collector.health_status["last_failure_at"])

    async def test_repeated_failure_classes_are_bounded_and_do_not_leak_secrets(self):
        asset_id = "classified-failures-test"
        secret = "never-log-this-secret"

        class _NotJSON(_Response):
            def json(self):
                raise ValueError(f"response-body={secret}")

        before = {
            failure_class: _metric(
                "edge_collector_poll_failures_total", asset_id, failure_class
            )
            for failure_class in ("transport", "http_status", "decode")
        }
        collector = _collector(
            config={
                "asset_id": asset_id,
                "url": f"https://user:{secret}@device/api?token={secret}",
                "headers": {"Authorization": f"Bearer {secret}"},
                "params": {"api_key": secret},
            },
            responses=[
                httpx.ConnectError(f"password={secret}"),
                _Response({"raw": secret}, status_code=500),
                _NotJSON(None),
            ],
        )

        with capture_logs() as logs:
            await collector._collect()
            await collector._collect()
            await collector._collect()

        self.assertEqual(collector.health_status["consecutive_failures"], 3)
        self.assertEqual(collector.health_status["last_failure_class"], "decode")
        for failure_class, prior in before.items():
            self.assertEqual(
                _metric(
                    "edge_collector_poll_failures_total", asset_id, failure_class
                ),
                prior + 1,
            )
        self.assertEqual(
            _metric("edge_collector_poll_consecutive_failures", asset_id), 3
        )
        self.assertEqual(_metric("edge_collector_connection_state", asset_id), 0)
        self.assertEqual(
            [entry["event"] for entry in logs],
            [
                "http_poll_failed",
                "http_poll_still_failing",
                "http_poll_still_failing",
            ],
        )
        self.assertEqual(logs[0]["log_level"], "warning")
        self.assertTrue(
            all(entry["url"] == "https://device/api" for entry in logs)
        )
        self.assertNotIn(secret, str(logs))

    async def test_the_next_success_clears_degraded_state_once(self):
        asset_id = "recovery-test"
        before = _metric("edge_collector_poll_recoveries_total", asset_id)
        collector = _collector(
            config={"asset_id": asset_id},
            responses=[
                httpx.ConnectError("refused"),
                _Response({"temperature": 7.0}),
                _Response({"temperature": 8.0}),
            ],
        )
        seen: list[dict] = []
        collector.add_data_handler(seen.append)

        with capture_logs() as logs:
            await collector._collect()
            await collector._collect()
            await collector._collect()

        self.assertEqual([item["payload"]["temperature"] for item in seen], [7.0, 8.0])
        self.assertEqual(collector.health_status["state"], "healthy")
        self.assertTrue(collector.health_status["healthy"])
        self.assertEqual(collector.health_status["consecutive_failures"], 0)
        self.assertIsNotNone(collector.health_status["last_success_at"])
        self.assertEqual(
            _metric("edge_collector_poll_recoveries_total", asset_id), before + 1
        )
        self.assertEqual(
            _metric("edge_collector_poll_consecutive_failures", asset_id), 0
        )
        self.assertEqual(_metric("edge_collector_connection_state", asset_id), 1)
        self.assertEqual(
            [entry["event"] for entry in logs].count("http_poll_recovered"), 1
        )

    async def test_an_unexpected_normalization_bug_is_degraded_then_retried(self):
        asset_id = "unexpected-failure-test"
        before = _metric(
            "edge_collector_poll_failures_total", asset_id, "unexpected"
        )
        collector = _collector(
            config={"asset_id": asset_id, "poll_interval": 0},
            responses=[_Response({"v": 1}), _Response({"v": 2})],
        )
        normalize = collector._normalize_data
        calls = 0

        def fail_once(data):
            nonlocal calls
            calls += 1
            if calls == 1:
                raise RuntimeError("normalizer invariant failed")
            return normalize(data)

        collector._normalize_data = fail_once
        seen: list[dict] = []
        collector.add_data_handler(seen.append)

        loop_task = asyncio.create_task(collector._poll_loop())
        for _ in range(20):
            await asyncio.sleep(0)
            if seen:
                break
        collector._running = False
        loop_task.cancel()
        try:
            await loop_task
        except asyncio.CancelledError:
            pass

        self.assertTrue(seen)
        self.assertEqual(
            _metric("edge_collector_poll_failures_total", asset_id, "unexpected"),
            before + 1,
        )
        self.assertEqual(collector.health_status["state"], "healthy")


class ClientConfigurationIsAppliedSafely(unittest.IsolatedAsyncioTestCase):
    async def test_client_receives_headers_auth_and_timeout_without_logging_them(self):
        secret = "client-secret"
        client = _Client([])
        collector = HTTPRestCollector(
            {
                "asset_id": "client-config-test",
                "url": f"https://user:{secret}@device:8443/api?token={secret}",
                "headers": {"Authorization": f"Bearer {secret}"},
                "auth": {"username": "operator", "password": secret},
                "params": {"api_key": secret},
                "timeout": 12.5,
            }
        )

        with patch(
            "opsgrid_agent.collectors.http_rest.httpx.AsyncClient",
            return_value=client,
        ) as async_client, capture_logs() as logs:
            await collector.start()
            await collector.stop()

        kwargs = async_client.call_args.kwargs
        self.assertEqual(kwargs["headers"], {"Authorization": f"Bearer {secret}"})
        self.assertEqual(kwargs["timeout"], 12.5)
        self.assertIsInstance(kwargs["auth"], httpx.BasicAuth)
        self.assertIn(
            {
                "asset_id": "client-config-test",
                "url": "https://device:8443/api",
                "method": "GET",
                "poll_interval": 60,
                "event": "http_collector_started",
                "log_level": "info",
            },
            logs,
        )
        self.assertNotIn(secret, str(logs))


class CoordinatorReportsPollHealth(unittest.IsolatedAsyncioTestCase):
    async def test_a_repeatedly_failing_live_adapter_recovers_to_healthy(self):
        asset_id = "coordinator-health-test"
        Adapter = coordinator_adapter(HTTPRestCollector)
        adapter = Adapter(
            on_message_callback=None,
            asset_id=asset_id,
            url="https://device/api",
        )
        adapter._collector.client = _Client(
            [
                httpx.ConnectError("refused"),
                _Response({}, status_code=503),
                _Response({"temperature": 7.0}),
            ]
        )
        adapter._collector._running = True

        coordinator = UnifiedCollectorCoordinator(buffer=object())
        coordinator.configs[asset_id] = CollectorConfig(
            collector_type="http_rest",
            asset_id=asset_id,
            config={},
        )
        coordinator.collectors[asset_id] = adapter
        live_task = asyncio.create_task(asyncio.Event().wait())
        coordinator.collector_tasks[asset_id] = live_task
        try:
            await adapter._collector._collect()
            await adapter._collector._collect()
            degraded = coordinator.get_status()
            self.assertEqual(degraded["active_collectors"], 1)
            self.assertEqual(degraded["degraded_collectors"], 1)
            self.assertTrue(degraded["collectors"][asset_id]["running"])
            self.assertFalse(degraded["collectors"][asset_id]["healthy"])
            self.assertEqual(degraded["collectors"][asset_id]["state"], "degraded")
            self.assertEqual(
                degraded["collectors"][asset_id]["consecutive_failures"], 2
            )

            await adapter._collector._collect()
            healthy = coordinator.get_status()
            self.assertEqual(healthy["degraded_collectors"], 0)
            self.assertTrue(healthy["collectors"][asset_id]["healthy"])
            self.assertEqual(healthy["collectors"][asset_id]["state"], "healthy")
        finally:
            live_task.cancel()
            try:
                await live_task
            except asyncio.CancelledError:
                pass


class StoppingReleasesTheClient(unittest.IsolatedAsyncioTestCase):
    async def test_stop_closes_the_http_client(self):
        """A collector removed by a config reload that leaks its connection pool leaks it for
        the life of the agent — which is a process that runs for months on a device."""
        collector = _collector()
        collector._poll_task = asyncio.create_task(asyncio.sleep(3600))

        await collector.stop()

        self.assertTrue(collector.client.closed, "stop() left the httpx client open")
        self.assertFalse(collector.running, "stop() left the collector marked running")

    async def test_stop_cancels_the_poll_task(self):
        collector = _collector()
        collector.poll_interval = 3600
        task = asyncio.create_task(collector._poll_loop())
        collector._poll_task = task
        await asyncio.sleep(0)

        await collector.stop()

        self.assertTrue(task.cancelled() or task.done(), "the poll task outlived stop()")


if __name__ == "__main__":
    unittest.main()
