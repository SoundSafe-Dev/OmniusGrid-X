"""Property-based API contract tests (task 12).

Schemathesis drives every operation in the app's own OpenAPI schema with
generated inputs and asserts the responses conform to the schema (status codes,
content types, declared response shapes) — catching drift between the code and
the contract the generated SDK (task 11) is built from.

Skips cleanly when schemathesis or the app's heavy deps aren't installed, so the
local suite stays green; CI installs requirements-dev.txt and runs it for real.
"""

import pytest

schemathesis = pytest.importorskip("schemathesis")

try:
    from app.main import app
except Exception as exc:  # pragma: no cover - missing optional deps locally
    pytest.skip(f"app import failed ({exc})", allow_module_level=True)

schema = schemathesis.from_asgi("/openapi.json", app)


@schema.parametrize()
def test_api_conforms_to_openapi(case):
    # Exercises the operation and validates the response against the schema.
    case.call_and_validate()
