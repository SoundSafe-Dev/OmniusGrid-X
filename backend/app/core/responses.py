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


def _resp(description: str) -> Dict[str, Any]:
    return {"model": ErrorEnvelope, "description": description}


# Attached at the include_router mount in app.main so every route documents the
# error contract it already returns via app.core.errors.
common_responses: Dict[int | str, Dict[str, Any]] = {
    401: _resp("Missing or invalid authentication credentials."),
    403: _resp("Authenticated but not permitted to access this resource."),
    404: _resp("The requested resource does not exist."),
    422: _resp("Request validation failed."),
    429: _resp("Rate limit exceeded."),
    500: _resp("Unexpected server error."),
}
