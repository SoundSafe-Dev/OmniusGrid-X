"""The HTTP/REST collector is live and had no test at all (FS-507).

`http_rest` is one of seventeen types in `UnifiedCollectorCoordinator.SUPPORTED_COLLECTORS`
(`collectors/coordinator.py:93`) — a registered collector an operator can name in a config
file and point at a device today. It is 186 lines and, before this file, **zero tests named
it**. It is the only registered type in that position.

WHY THAT IS WORSE THAN IT SOUNDS. Every failure path in this collector is swallowed.
`_collect` catches `httpx.HTTPError` and then bare `Exception`, logging and returning
(`http_rest.py:117-131`); `_poll_loop` wraps the same call in a second handler
(`:82-90`). So the collector cannot crash, cannot restart, and cannot tell the coordinator
anything is wrong — a poll that raises on every cycle looks exactly like a poll that works.
The supervision loop (FS-501) never sees it, the heartbeat (FS-497) never counts it, and the
asset simply goes quiet. That is the FS-495 shape — 100% failure with a log line — and the
only thing standing between this collector and that outcome was that nobody had run it.

So these tests drive the real object through the real adapter, with a stubbed transport, and
assert the things a swallowed exception would hide: that a reading is emitted at all, that the
payload survives normalisation, and that a failed poll does not stop the next one.
"""

from __future__ import annotations

import asyncio
import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

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


class ASuccessfulPollEmitsAReading(unittest.IsolatedAsyncioTestCase):
    async def test_the_reading_reaches_a_data_handler(self):
        """The assertion nothing made. Every exception on this path is swallowed, so a
        collector that emits nothing and a collector that works produce the same logs."""
        seen: list[dict] = []
        collector = _collector(responses=[_Response({"temperature": 41.2, "state": "RUN"})])
        collector.add_data_handler(seen.append)

        await collector._collect()

        self.assertEqual(
            len(seen),
            1,
            "a 200 with a JSON body produced no reading. `_collect` catches httpx.HTTPError "
            "and then bare Exception, so a failure anywhere in normalise-or-emit is logged "
            "and discarded — the asset goes quiet and nothing upstream can tell.",
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
        import httpx

        collector = _collector(responses=[httpx.ConnectError("refused")])
        await collector._collect()  # must not raise

    async def test_the_next_poll_still_happens(self):
        """The failure that matters: one bad response silently ending the poll loop looks
        identical to a device that stopped reporting."""
        import httpx

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
