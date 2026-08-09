"""Answer an unhandled exception from INSIDE the middleware stack.

THE DEFECT THIS EXISTS FOR. Starlette wires a catch-all ``@app.exception_handler(Exception)``
onto ``ServerErrorMiddleware``, which is the outermost layer of the stack — outside
``CORSMiddleware``. So the 500 it produces never passes back through CORS, and it goes to
the browser with no ``Access-Control-Allow-Origin``. What a browser does with that is not
show a 500: it refuses the response and reports a CORS violation, so the frontend's axios
client sees ``Network Error`` with **no status, no body and no trace id**.

Found by a page-by-page QA sweep (2026-08-01). Measured on the running stack:

    200 /api/v1/assets/           -> access-control-allow-origin: *
    404 /api/v1/nope              -> access-control-allow-origin: *
    500 /api/v1/nlp/sessions/…    -> (no CORS header at all)

Handled errors were fine because ``ExceptionMiddleware`` sits *inside* CORS; only the
catch-all was outside. The consequence is worse than a cosmetic header: this repo ships an
error-triage feature, and the failures it most needs — unhandled 500s — were the exact ones
arriving at the client stripped of the trace id that makes them triageable.

WHY A MIDDLEWARE RATHER THAN HEADERS ON THE HANDLER. Re-deriving the CORS decision by hand
(origin allowlist, wildcard-vs-credentials, preflight) would be a second implementation of
``CORSMiddleware`` that can disagree with the first. Returning a normal response from below
it instead lets the real one do its job — the 500 becomes an ordinary response to every
layer above, and gets exactly the headers every other response gets.

ORDERING. ``add_middleware`` inserts at position 0, so the LAST registered is the OUTERMOST.
This must therefore be registered BEFORE ``CORSMiddleware`` in ``app/main.py`` to sit
*inside* it. ``test_unhandled_errors_reach_the_browser.py`` asserts that ordering directly,
because getting it backwards restores the defect while leaving the code looking correct.
"""

from __future__ import annotations

from typing import Any, Callable

from starlette.requests import Request
from starlette.types import ASGIApp, Message, Receive, Scope, Send

from app.core.errors import unhandled_exception_response


class UnhandledExceptionMiddleware:
    """Convert an escaping exception into the standard problem+json envelope.

    Pure ASGI rather than ``BaseHTTPMiddleware``: the latter runs the downstream app in a
    task group, which changes how exceptions and background tasks propagate. There is
    nothing to gain from that here — this needs to see the exception and nothing else.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        started = False

        async def _send(message: Message) -> None:
            nonlocal started
            if message["type"] == "http.response.start":
                started = True
            await send(message)

        try:
            await self.app(scope, receive, _send)
        except Exception as exc:
            # ONCE THE STATUS LINE IS OUT, THE RESPONSE IS NOT OURS TO REPLACE. A handler
            # that fails midway through streaming a body has already told the client
            # "200, content-length N"; sending a second response start is an ASGI protocol
            # violation, and the client would read the envelope as body bytes. Re-raising
            # hands it to ServerErrorMiddleware, which is the correct owner of that case —
            # it aborts the connection, which is the only honest signal left.
            if started:
                raise
            response = unhandled_exception_response(Request(scope, receive), exc)
            await response(scope, receive, send)
