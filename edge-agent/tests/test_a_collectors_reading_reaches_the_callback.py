"""Every MQTT message and every watched file was lost on a thread boundary (FS-675).

`asyncio.create_task` requires the calling thread to be running the loop. Three collectors
called it from threads that are not:

  * `paho.mqtt` with `loop_start()` dispatches `on_message` from **its own network thread**;
  * `watchdog`'s `Observer` dispatches `on_created` / `on_modified` from **its own thread**.

On those threads it raises `RuntimeError: no running event loop` before the coroutine is ever
scheduled. In `MQTTCollector._on_message` the raise lands in a broad `except Exception` and is
logged as `mqtt_message_handler_error` — so **every reading from the collector this agent is
built around was dropped**, visibly, for as long as the code has existed. `OrcaSlicerCollector`
is a registered collector type (`orca_file`) that could not process a single file.

WHY NOTHING CAUGHT IT. There is no test for either collector's handler, and the shape is
invisible to reading: `asyncio.create_task(...)` inside a method is unremarkable, and nothing
at that line says which thread will run it. It was found by carrying the backend's
"discarded task" sweep (FS-674) into this codebase and then asking, per site, *who calls this*.

THE TESTS BELOW CALL FROM A REAL THREAD. That is the whole point — the previous behaviour is
reproducible only off the loop, and a test that calls `_on_message` directly passes against the
broken code. The first version of this file did exactly that and proved nothing.
"""

from __future__ import annotations

import asyncio
import json
import threading
import types

import pytest

from opsgrid_agent.collectors.file_watcher import OrcaSlicerHandler
from opsgrid_agent.collectors.mqtt import MQTTCollector
from opsgrid_agent.packml import create_mapper_for_asset_type
from opsgrid_agent.tasks import in_flight, spawn


def _message(state: str = "running") -> types.SimpleNamespace:
    return types.SimpleNamespace(
        topic="printer/status", payload=json.dumps({"state": state}).encode()
    )


def _call_off_loop(fn, *args) -> None:
    """Run `fn` on a thread that is NOT running the event loop, as paho and watchdog do."""
    thread = threading.Thread(target=fn, args=args)
    thread.start()
    thread.join()


class TestAnMqttMessageReachesTheCallback:
    @pytest.mark.asyncio
    async def test_a_message_dispatched_from_pahos_thread_is_delivered(self):
        delivered = []

        async def callback(message):
            delivered.append(message)

        collector = MQTTCollector(
            broker_host="broker.invalid", asset_id="asset-1", on_message_callback=callback
        )
        collector._loop = asyncio.get_running_loop()  # what `start()` does

        _call_off_loop(collector._on_message, None, None, _message())
        await asyncio.sleep(0.05)

        assert len(delivered) == 1, (
            "the reading never reached the callback. paho calls `_on_message` from its own "
            "network thread, where `asyncio.create_task` raises `RuntimeError: no running "
            "event loop` — caught by the broad handler and logged as a parse-ish error."
        )
        assert delivered[0]["topic"] == "printer/status"
        assert delivered[0]["collector_type"] == "mqtt"

    @pytest.mark.asyncio
    async def test_the_payload_survives_the_thread_hop_intact(self):
        """Delivering *something* is not the assertion. The normalised message is built on
        paho's thread and consumed on the loop, and that is where a shared mutable would
        show up."""
        delivered = []

        async def callback(message):
            delivered.append(message)

        collector = MQTTCollector(
            broker_host="broker.invalid", asset_id="asset-2", on_message_callback=callback
        )
        collector._loop = asyncio.get_running_loop()

        for state in ("running", "idle", "running"):
            _call_off_loop(collector._on_message, None, None, _message(state))
        await asyncio.sleep(0.05)

        assert len(delivered) == 3, "messages were coalesced or dropped under repetition"
        assert [m["payload"]["state"] for m in delivered] == ["running", "idle", "running"]

    @pytest.mark.asyncio
    async def test_no_captured_loop_is_reported_rather_than_swallowed(self):
        """The failure mode this replaces must not come back as a quieter one. A collector
        whose `start()` never ran has no loop, and that has to be loud."""
        import structlog

        async def callback(message):  # pragma: no cover - must never run
            raise AssertionError("delivered with no loop to deliver on")

        collector = MQTTCollector(
            broker_host="broker.invalid", asset_id="asset-3", on_message_callback=callback
        )
        assert collector._loop is None

        with structlog.testing.capture_logs() as logs:
            _call_off_loop(collector._on_message, None, None, _message())
            await asyncio.sleep(0.05)

        assert [e for e in logs if e.get("event") == "background_task_unscheduled"]


class TestAWatchedFileIsProcessed:
    @pytest.mark.asyncio
    async def test_a_file_event_from_the_observer_thread_is_processed(self):
        """`orca_file` is a registered collector type. Before this it could not process a
        single file, because watchdog dispatches from its own thread."""
        processed = []

        handler = OrcaSlicerHandler(
            asset_id="printer-1",
            watch_path=None,
            on_file_callback=None,
            packml_mapper=create_mapper_for_asset_type("3d_printer"),
            loop=asyncio.get_running_loop(),
        )

        async def record(path):
            processed.append(path)

        handler._process_gcode = record
        event = types.SimpleNamespace(is_directory=False, src_path="/tmp/part.gcode")

        _call_off_loop(handler.on_created, event)
        await asyncio.sleep(0.05)

        assert processed == ["/tmp/part.gcode"]

    @pytest.mark.asyncio
    async def test_a_directory_and_a_non_gcode_file_are_still_ignored(self):
        """The filter has to survive the fix. Scheduling everything would be a different
        bug wearing the same commit."""
        processed = []
        handler = OrcaSlicerHandler(
            asset_id="printer-2",
            watch_path=None,
            on_file_callback=None,
            packml_mapper=create_mapper_for_asset_type("3d_printer"),
            loop=asyncio.get_running_loop(),
        )

        async def record(path):
            processed.append(path)

        handler._process_gcode = record

        _call_off_loop(
            handler.on_created, types.SimpleNamespace(is_directory=True, src_path="/tmp/d")
        )
        _call_off_loop(
            handler.on_created,
            types.SimpleNamespace(is_directory=False, src_path="/tmp/notes.txt"),
        )
        await asyncio.sleep(0.05)

        assert processed == []


class TestSpawnItself:
    @pytest.mark.asyncio
    async def test_it_retains_the_work_until_it_finishes(self):
        release = asyncio.Event()
        started = asyncio.Event()

        async def work():
            started.set()
            await release.wait()

        before = in_flight()
        handle = spawn(work(), name="test.retained")
        await started.wait()
        assert in_flight() == before + 1
        release.set()
        await handle
        await asyncio.sleep(0)
        assert in_flight() == before

    @pytest.mark.asyncio
    async def test_an_off_loop_failure_is_logged(self):
        import structlog

        async def explode():
            raise RuntimeError("the buffer is full")

        loop = asyncio.get_running_loop()
        with structlog.testing.capture_logs() as logs:
            _call_off_loop(lambda: spawn(explode(), name="test.offloop", loop=loop))
            await asyncio.sleep(0.05)

        failures = [e for e in logs if e.get("event") == "background_task_failed"]
        assert failures, "a coroutine scheduled from another thread failed and said nothing"
        assert failures[0]["error"] == "the buffer is full"

    @pytest.mark.asyncio
    async def test_an_unschedulable_coroutine_does_not_leak_a_warning(self):
        """`coroutine was never awaited` is a RuntimeWarning printed by the interpreter at
        collection time, which is neither actionable nor attributable. `spawn` closes the
        coroutine so the structured log line is the only record."""
        import warnings

        async def never_runs():  # pragma: no cover
            pass

        coro = never_runs()
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            _call_off_loop(lambda: spawn(coro, name="test.nowhere"))
        assert not [w for w in caught if "never awaited" in str(w.message)]


class TestTheClassIsClosed:
    """The structural half. The tests above pin three collectors; this one asks whether a
    fourth has appeared — the backend's `test_background_tasks_have_an_owner.py` asks the
    same question of `app/`, and the two together are the reason this is a closed class
    rather than three fixed instances.

    `create_task` is not banned. Thirteen sites in this agent already assign the task to
    something that outlives it, which is the property that matters and also this sweep's
    negative control.
    """

    @staticmethod
    def _sites():
        import ast
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1] / "opsgrid_agent"
        for path in sorted(root.rglob("*.py")):
            tree = ast.parse(path.read_text())
            seen = set()
            for parent in ast.walk(tree):
                for _field, value in ast.iter_fields(parent):
                    for child in value if isinstance(value, list) else [value]:
                        if not isinstance(child, ast.stmt):
                            continue
                        call = getattr(child, "value", None)
                        if not isinstance(call, ast.Call):
                            continue
                        func = call.func
                        if not (
                            isinstance(func, ast.Attribute)
                            and func.attr in ("create_task", "ensure_future")
                        ):
                            continue
                        if child.lineno in seen:
                            continue
                        seen.add(child.lineno)
                        yield (
                            str(path.relative_to(root)),
                            child.lineno,
                            not isinstance(child, ast.Expr),
                        )

    def test_the_walk_finds_sites(self):
        assert len(list(self._sites())) >= 10, "the AST walk has stopped descending"

    def test_the_retained_sites_are_the_negative_control(self):
        retained = [s for s in self._sites() if s[2]]
        assert len(retained) >= 10, (
            f"only {len(retained)} tasks are retained; an assignment is being read as a "
            f"bare statement and this guard would condemn the whole package"
        )

    def test_no_task_is_created_and_discarded(self):
        discarded = sorted(f"{p}:{line}" for p, line, retained in self._sites() if not retained)
        assert not discarded, (
            f"{discarded}\n\n"
            f"A discarded task may be garbage-collected mid-execution, and if the caller is "
            f"a driver's own thread — paho's network loop, watchdog's observer — "
            f"`create_task` raises before the coroutine is ever scheduled. Use "
            f"`opsgrid_agent.tasks.spawn(coro, name=..., loop=...)`, passing the loop "
            f"captured at start whenever a third-party library owns the calling thread."
        )
