"""The exceptions that mean *a dependency did not answer*, as opposed to refused.

Extracted from `app/api/rag.py` when the RAG indexing worker needed the same
distinction (2026-08-28). It is the distinction that decides whether a failure is
someone else's outage — retry, report 503 — or a defect here, which must surface.

`HTTPStatusError`, `ClientError` and `UnexpectedResponse` are deliberately absent: they
mean the dependency ANSWERED and said no. That is a bug on this side, and catching it
here would bury it as an outage over there.
"""

from __future__ import annotations

_TRANSPORT: tuple[type[BaseException], ...] = (OSError,)
try:  # pragma: no cover - httpx is a hard dependency, guarded for symmetry
    import httpx

    # `httpx.TransportError` covers connect/read/write/pool failures and NOT
    # `HTTPStatusError`, which means the service answered — the same distinction the
    # `UnexpectedResponse` note above makes. Added because `httpx.ConnectError` is not an
    # `OSError` subclass, so an unreachable generator host escaped this tuple entirely.
    _TRANSPORT += (httpx.TransportError,)
except ImportError:  # pragma: no cover
    pass
try:  # pragma: no cover - import shape mirrors the services' optional dependencies
    from botocore.exceptions import BotoCoreError

    _TRANSPORT += (BotoCoreError,)
except ImportError:  # pragma: no cover
    pass
try:  # pragma: no cover
    from qdrant_client.http.exceptions import ResponseHandlingException

    _TRANSPORT += (ResponseHandlingException,)
except ImportError:  # pragma: no cover
    pass

#: The public name. `rag.py` re-exports it as `_StoreTransportError`, which reads better
#: in its `except` clauses.
TRANSPORT_ERRORS = _TRANSPORT
