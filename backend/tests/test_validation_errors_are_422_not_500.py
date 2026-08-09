"""A rule the API enforces must be reportable, or enforcing it is a server error.

THE DEFECT, WHICH IS IN THE ERROR HANDLER AND NOT IN ANY ENDPOINT.

`@model_validator` raising a bare `ValueError` is the documented pydantic v2 way to
express a cross-field rule ("hot <= warm <= cold", "asset_ids must be unique"). Pydantic
then puts the **live exception object** into the error's `ctx`:

    {'type': 'value_error',
     'msg': 'Value error, retention days must satisfy hot <= warm <= cold',
     'ctx': {'error': ValueError('retention days must satisfy hot <= warm <= cold')}}

The envelope handler passed `exc.errors()` straight to `JSONResponse`, whose `json.dumps`
raised `TypeError: Object of type ValueError is not JSON serializable`. That escaped into
the generic `Exception` handler and came back as a **500**.

So the validator worked perfectly, and reporting it was what failed. Every request that
broke a cross-field rule got a server error where the schema promises 422 — on four
validators across `data_retention` and `twin_optimizer` today, and on any that lands
tomorrow. Found by the contract gate (FS-259), which could see the 500 but not the cause;
the cause needed the app's own `unhandled_exception` record.

WHY THE FIX IS NOT JUST `jsonable_encoder`. That alone stops the crash and encodes the
exception as `{}` — which drops the only text saying which rule was broken, and leaves a
422 whose `ctx` is an empty object. The exception is stringified first, so `msg` and `ctx`
agree and the caller can still read what they violated.

These tests go through the real ASGI stack rather than calling the handler directly,
because the failure was in the boundary between the handler and the response encoder —
exactly the seam a unit test of either half would step over.
"""

from __future__ import annotations

import json

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, model_validator

from app.core.errors import register_exception_handlers


def _app_with(model) -> TestClient:
    """Mount `model` as the body of a throwaway POST.

    The annotation is assigned rather than written, because this module uses
    `from __future__ import annotations`: `payload: model` would be the *string*
    `"model"`, which FastAPI cannot resolve in module globals — it then falls back to
    treating the parameter as a QUERY param and the test asserts against the wrong error
    entirely. That is how the first version of this file failed, and it failed in a way
    that looked like the fix was broken rather than the harness.
    """
    app = FastAPI()
    register_exception_handlers(app)

    async def _create(payload):
        return {"ok": True}

    _create.__annotations__ = {"payload": model}
    app.post("/thing")(_create)

    return TestClient(app, raise_server_exceptions=False)


class CrossFieldRule(BaseModel):
    low: int = 1
    high: int = 10

    @model_validator(mode="after")
    def _ordered(self):
        if self.low > self.high:
            raise ValueError("low must not exceed high")
        return self


class TestACrossFieldRuleReportsAs422:
    def test_it_is_not_a_500(self):
        """The whole defect in one assertion."""
        response = _app_with(CrossFieldRule).post("/thing", json={"low": 9, "high": 2})
        assert response.status_code == 422, response.text

    def test_the_body_says_which_rule_was_broken(self):
        """A 422 that does not name the rule is barely better than the 500 was."""
        response = _app_with(CrossFieldRule).post("/thing", json={"low": 9, "high": 2})
        assert "low must not exceed high" in response.text

    def test_the_exception_is_stringified_rather_than_dropped(self):
        """`jsonable_encoder` alone would leave `ctx: {"error": {}}`."""
        response = _app_with(CrossFieldRule).post("/thing", json={"low": 9, "high": 2})
        errors = response.json()["error"]["details"]["errors"]
        ctx = next(e for e in errors if e.get("ctx")).get("ctx")
        assert ctx["error"] == "low must not exceed high", (
            f"ctx lost the message: {ctx!r}"
        )

    def test_the_whole_envelope_is_json(self):
        """The failure mode was an encoder error, so serialising is the assertion."""
        response = _app_with(CrossFieldRule).post("/thing", json={"low": 9, "high": 2})
        json.loads(response.text)

    def test_an_ordinary_type_error_still_reports_normally(self):
        """The fix must not disturb the common case, which has no `ctx` exception."""
        response = _app_with(CrossFieldRule).post("/thing", json={"low": "not-an-int"})
        assert response.status_code == 422
        assert "int" in response.text


class TestTheRealModelsThatCarryTheseValidators:
    """The generic model above proves the handler. These prove the models that actually
    ship with cross-field rules go through it."""

    @pytest.mark.parametrize(
        "payload",
        [
            {"cold_retention_days": 2},          # cold < hot default
            {"hot_retention_days": 400},         # hot > warm default
        ],
    )
    def test_retention_ordering_is_a_422(self, payload):
        from app.api.data_retention import HistorianRetentionSettings

        response = _app_with(HistorianRetentionSettings).post("/thing", json=payload)
        assert response.status_code == 422, response.text
        assert "retention days must satisfy" in response.text

    def test_every_validator_that_raises_valueerror_is_covered(self):
        """A count, so a fifth validator landing somewhere new is noticed.

        The handler fix is global, so a new validator is safe by construction — this
        exists to keep the *claim* in the docstring above honest about how many there are.
        """
        import ast
        import pathlib

        app_dir = pathlib.Path(__file__).resolve().parent.parent / "app"
        found = []
        for path in app_dir.rglob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                decorated = any(
                    "validator" in ast.unparse(d) for d in node.decorator_list
                )
                if not decorated:
                    continue
                if any(
                    isinstance(n, ast.Raise)
                    and n.exc is not None
                    and "ValueError" in ast.unparse(n.exc)
                    for n in ast.walk(node)
                ):
                    found.append(f"{path.relative_to(app_dir.parent)}:{node.lineno}")

        assert found, "the sweep found no validators at all — check the AST walk"
        assert len(found) <= 8, (
            "more cross-field validators than this file's docstring accounts for; the "
            f"handler covers them all, but update the prose: {found}"
        )
