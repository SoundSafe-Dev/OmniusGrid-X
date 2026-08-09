"""OpenAPI schema quality guards (FS-215).

The generated SDK is built from this schema, so defects here become defects in
every consumer. These only surfaced as `UserWarning: Duplicate Operation ID ...`
during app import — buried among dozens of other warnings and easy to scroll past
for as long as they existed.
"""

from __future__ import annotations

from collections import Counter

import pytest


@pytest.fixture(scope="module")
def spec():
    from app.main import app

    return app.openapi()


def _operations(spec) -> list[tuple[str, str, dict]]:
    out = []
    for path, methods in spec["paths"].items():
        for method, op in methods.items():
            if isinstance(op, dict):
                out.append((method.upper(), path, op))
    return out


class TestOperationIds:
    def test_no_duplicate_operation_ids(self, spec):
        """A duplicate id makes an SDK generator collide or drop an operation.

        Four of these existed: /health/{system,db,redis,kafka} are each declared
        with STACKED decorators — an unprefixed path for probes that predate the
        /api/v1 convention, plus the versioned one — and FastAPI derives the
        operationId from the function name, so both routes got the same id.
        """
        ids = [op["operationId"] for _, _, op in _operations(spec) if "operationId" in op]
        dupes = {k: v for k, v in Counter(ids).items() if v > 1}
        assert not dupes, (
            "duplicate operationIds — the generated SDK cannot represent these: "
            f"{ {k: v for k, v in sorted(dupes.items())} }\n"
            "Give each route an explicit, distinct operation_id."
        )

    def test_every_operation_has_an_id(self, spec):
        """An operation without an id gets an auto-generated one that changes when
        the function moves, silently renaming an SDK method."""
        missing = [
            f"{method} {path}"
            for method, path, op in _operations(spec)
            if "operationId" not in op
        ]
        assert not missing, f"operations without an operationId: {missing}"
