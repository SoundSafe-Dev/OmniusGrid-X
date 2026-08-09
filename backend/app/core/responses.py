"""Machine-readable OpenAPI error-response docs (FS-80).

Every router registered in ``app.main`` runs behind the normalized error
envelope defined in :mod:`app.core.errors`:

    {"error": {"code", "message", "details", "trace_id"}, "detail": "..."}

FastAPI cannot infer those non-2xx responses from route signatures, so the
generated OpenAPI schema documented no error contract — which is also why the
schemathesis conformance suite reported "undocumented 401/404" (see FS-81).

This module models the envelope and exposes a ``common_responses`` map that is
attached at the ``include_router`` mount in ``app.main`` so every route inherits
the documented 401/403/404/422/429/500 contract without per-route churn.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    """The ``error`` object inside the response envelope."""

    code: str = Field(..., description="Stable machine code, e.g. 'not_found'.")
    message: str = Field(..., description="Human-readable error message.")
    details: Dict[str, Any] = Field(
        default_factory=dict, description="Optional structured context."
    )
    trace_id: Optional[str] = Field(
        None, description="Request correlation id (from the request-context middleware)."
    )


class ErrorEnvelope(BaseModel):
    """The full error body returned for every 4xx/5xx.

    Carries both the OmniusGrid envelope (``error``/``detail``) and the RFC-9457
    (``application/problem+json``) standard members (``type``/``title``/
    ``status``/``instance``) so a single body satisfies existing callers and
    standards-based consumers alike (FS-102). The four problem members are
    additive — existing fields are unchanged.
    """

    # RFC-9457 problem-details members (additive).
    type: str = Field(
        "about:blank",
        description="URI reference identifying the problem type (RFC-9457).",
    )
    title: str = Field(
        ..., description="Short, human-readable summary of the problem type (RFC-9457)."
    )
    status: int = Field(..., description="HTTP status code, mirrored per RFC-9457.")
    instance: Optional[str] = Field(
        None,
        description="URI reference (request path) or trace id identifying this occurrence.",
    )

    error: ErrorDetail
    detail: str = Field(
        ..., description="Backward-compatible mirror of error.message (FastAPI default shape)."
    )

    model_config = {
        "json_schema_extra": {
            "example": {
                "type": "https://omniusgrid.dev/problems/not_found",
                "title": "Not Found",
                "status": 404,
                "instance": "/api/v1/assets/123",
                "error": {
                    "code": "not_found",
                    "message": "Asset not found",
                    "details": {},
                    "trace_id": "b3f1c2a4-...",
                },
                "detail": "Asset not found",
            }
        }
    }


#: The media type ``app.core.errors`` actually sets on every error response.
#: Kept as one constant so the declaration below cannot drift from the code that
#: builds the response.
PROBLEM_JSON = "application/problem+json"


def _resp(description: str) -> Dict[str, Any]:
    """Document one error status.

    ``content`` is explicit because FastAPI defaults an additional response's media
    type to ``application/json``, while every error here is emitted as
    ``application/problem+json`` (RFC 9457) by ``app.core.errors._envelope``. FS-80
    documented the status codes and inherited that default, so the schema said
    ``application/json`` for responses the API has never sent — the OpenAPI document
    that the generated TypeScript SDK is built from was wrong for every 4xx/5xx on
    every route. The contract suite reported it 304 times, once per operation; it is
    one defect, not 304.
    """
    return {
        "model": ErrorEnvelope,
        "description": description,
        # The $ref is spelled out rather than left empty: FastAPI attaches the model's
        # schema to the DEFAULT media type only, so without this the problem+json entry
        # would be declared but schema-less, and response bodies for every error would
        # go unvalidated — the content-type check would pass while checking nothing.
        # `model` stays so ErrorEnvelope keeps its place in components/schemas; the
        # application/json entry FastAPI adds alongside is harmless, since the checks
        # ask whether what was RECEIVED is documented.
        "content": {
            PROBLEM_JSON: {"schema": {"$ref": "#/components/schemas/ErrorEnvelope"}}
        },
    }


# Attached at the include_router mount in app.main so every route documents the
# error contract it already returns via app.core.errors.
common_responses: Dict[int | str, Dict[str, Any]] = {
    # 400 and 405 are here because they arise from the SHARED machinery on any route,
    # not from a handler choosing to raise them:
    #   * 400 — app.core.errors maps `bad_request`, and Starlette raises it when a
    #     request body cannot be parsed. Observed on 26 operations, with real messages
    #     ("There was an error parsing the body", "Email already registered"), while
    #     no route declared it.
    #   * 405 — Starlette's router raises it for any path reached with a method it does
    #     not serve, which is every route.
    #
    # NOT added here, deliberately: 409 and 503. Both are in the envelope's status
    # table, but a handler raises 409 only where a conflict is possible and 503 comes
    # from the dependency checks in the health routers. Declaring them on all ~450
    # operations would document responses most of them cannot produce, and an OpenAPI
    # document that over-promises misleads the generated SDK exactly as much as one
    # that under-promises. They belong on the routes that raise them.
    400: _resp("The request was malformed or could not be parsed."),
    401: _resp("Missing or invalid authentication credentials."),
    403: _resp("Authenticated but not permitted to access this resource."),
    404: _resp("The requested resource does not exist."),
    405: _resp("The HTTP method is not supported for this resource."),
    422: _resp("Request validation failed."),
    429: _resp("Rate limit exceeded."),
    500: _resp("Unexpected server error."),
}


#: For routers that report a dependency's availability and therefore really can return
#: 503. Eleven modules raise it (health, rag, sso, exports, erp_integrations,
#: feature_flags, model_monitoring, query_performance, compliance_reports,
#: edge_enroll, bulk_operations); the other ~58 cannot, and declaring it on them would
#: tell the generated SDK to handle a response those routes never send.
#:
#: Grep for `status_code=503` before adding a router here — the point of a separate
#: mapping is that membership means something.
unavailable_responses: Dict[int | str, Dict[str, Any]] = {
    **common_responses,
    503: _resp("A dependency this endpoint reports on is unavailable."),
}
