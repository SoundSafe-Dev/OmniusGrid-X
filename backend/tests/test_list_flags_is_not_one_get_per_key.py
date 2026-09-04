"""list_flags issues one round trip for the whole list, not one per key (FS-897).

THE DEFECT. `list_flags` looped over the index set and ran one Redis `GET` per key. A
tenant with many flags paid one round trip per flag on every admin page load. Fixed with
`MGET`, which fetches every key in one call.

THE FAILURE MODE `MGET` INTRODUCES, and why this file exists rather than just asserting
the call count: `MGET` returns positional results — `None` for any key that has no value.
A key can be in `feature_flags:index` with no document behind it (delete removes the doc
before the index entry, so a `WATCH`-aborted delete can leave the two briefly out of
step); the per-key loop skipped that with `if raw:` and the batched version must do the
same over the positional result list.
"""
from __future__ import annotations

import ast
import pathlib

import fakeredis.aioredis as fakeredis
import pytest
import pytest_asyncio

from app.services.feature_flags import FLAG_INDEX_KEY, FeatureFlagService

APP = pathlib.Path(__file__).resolve().parents[1] / "app"


def _list_flags_source() -> ast.AST:
    tree = ast.parse((APP / "services/feature_flags.py").read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name == "list_flags":
            return node
    raise AssertionError("list_flags moved or was renamed; this guard is blind")


class TestNoGetInsideTheKeyLoop:
    def test_no_client_get_inside_a_loop_over_keys(self):
        """THE DEFECT ITSELF. A `client.get` whose nearest enclosing loop iterates the
        index keys is a round trip per key."""
        handler = _list_flags_source()
        offenders = []
        for node in ast.walk(handler):
            if not isinstance(node, ast.For):
                continue
            target = ast.unparse(node.target)
            if "key" not in target:
                continue
            body = ast.unparse(node)
            if "client.get(" in body or ".get(" in body:
                offenders.append(target)
        assert not offenders, (
            f"a per-key GET runs inside a loop over the index keys ({offenders}) -- a "
            f"list call with N flags costs N round trips again"
        )

    def test_mget_is_used(self):
        body = ast.unparse(_list_flags_source())
        assert "mget(" in body, (
            "list_flags no longer batches its reads with MGET -- either the N+1 is "
            "back, or the batching was removed some other way"
        )


@pytest_asyncio.fixture
async def svc():
    service = FeatureFlagService()
    service._client = fakeredis.FakeRedis(decode_responses=True)

    async def _noaudit(*args, **kwargs):
        return None

    service._audit = _noaudit  # type: ignore[assignment]
    yield service
    await service._client.aclose()


class TestAnIndexEntryWithNoDocumentIsSkipped:
    """The failure MGET introduces: a positional None for a key whose document is gone."""

    @pytest.mark.asyncio
    async def test_a_dangling_index_entry_does_not_crash_or_appear(self, svc):
        await svc.create_flag("real_flag", description="present")
        # Simulate the WATCH-abort window: the index still names a key whose document
        # was already removed.
        await svc._redis().sadd(FLAG_INDEX_KEY, "ghost_flag")

        flags = await svc.list_flags()

        keys = {f["key"] for f in flags}
        assert keys == {"real_flag"}, (
            f"a dangling index entry with no document either crashed list_flags or "
            f"produced a phantom flag; got {keys}"
        )

    @pytest.mark.asyncio
    async def test_many_flags_all_come_back_in_one_call(self, svc):
        """Not a query-count assertion (fakeredis doesn't expose one) -- a correctness
        check that batching didn't drop or reorder anything across a realistic count."""
        for i in range(25):
            await svc.create_flag(f"flag_{i:02d}")

        flags = await svc.list_flags()

        assert {f["key"] for f in flags} == {f"flag_{i:02d}" for i in range(25)}
