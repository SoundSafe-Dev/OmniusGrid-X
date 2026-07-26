#!/usr/bin/env python3
"""One-time interactive authorization for Intuit QuickBooks Online.

WHY THIS SCRIPT HAS TO EXIST. Intuit's discovery document advertises
`response_types_supported: ["code"]` and no client-credentials grant, so a client id
and secret cannot mint a token on their own. QuickBooks requires a human to approve
access to a specific company once; that hands back an authorization code, which is
exchanged for the refresh token the connector then lives on.

This is the only step in the whole ERP matrix that cannot be automated, so it is
worth making it a single command rather than a page of instructions.

USAGE

    export INTUIT_CLIENT_ID='...'
    export INTUIT_CLIENT_SECRET='...'
    python scripts/intuit_authorize.py

It prints a URL, waits for you to approve in a browser, and prints the refresh token
and realm id. Nothing is written to disk: the refresh token is a live credential, and
the point of this script is to hand it to you, not to leave copies around.

BEFORE RUNNING, register the redirect URI on the Intuit app (developer.intuit.com ->
your app -> Keys & OAuth -> Redirect URIs). It must match EXACTLY, including the port
and the absence of a trailing slash:

    http://localhost:8399/callback

Intuit permits http://localhost redirect URIs for development; production apps need
https. If the URI is not registered you get an Intuit error page rather than a
callback, which is the single most common way this fails.

AND IT CANNOT BE CHECKED IN ADVANCE. Probed on 2026-07-26: requesting the authorize
endpoint with a registered redirect URI and with
`https://definitely-not-registered.example.com/cb` returns byte-identical responses
(HTTP 200, 153,203 bytes, both the sign-in page). Intuit validates the redirect URI
only AFTER authentication, so an unregistered URI is indistinguishable from a
registered one until someone signs in. What IS verifiable up front is the client id:
an unrecognised one is rejected at the token endpoint with `invalid_client` (401),
whereas valid credentials with a bad refresh token give `invalid_grant` (400).

WHAT YOU GET, AND WHAT TO DO WITH IT

    refresh_token   the credential. Store it wherever the integration's config lives.
    realm_id        the company id. Every QBO path is scoped by it and it cannot be
                    derived from the credential.

Both go into the integration configuration:

    auth_config    = {"client_id": ..., "client_secret": ..., "refresh_token": ...}
    configuration  = {"realm_id": ..., "environment": "sandbox"}

AND THE PART THAT WILL BITE IF IGNORED. Intuit rotates the refresh token on every
refresh and retires the previous one, so the value printed here is only the FIRST in a
chain. Whatever stores it must also store each rotation --
`configuration["refresh_token_sink"]` on the connector exists for exactly this. Without
it the integration works once and then fails permanently with `invalid_grant`, which
reads as a revoked authorization rather than a bug in us.
"""

from __future__ import annotations

import base64
import http.server
import os
import secrets
import sys
import threading
import urllib.parse
import urllib.request
import json

AUTHORIZATION_ENDPOINT = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_ENDPOINT = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"

# The accounting scope. Intuit issues separate scopes for payments and payroll; asking
# for more than is needed makes the consent screen scarier and the grant broader.
SCOPE = "com.intuit.quickbooks.accounting"

PORT = int(os.environ.get("INTUIT_CALLBACK_PORT", "8399"))
REDIRECT_URI = os.environ.get("INTUIT_REDIRECT_URI", f"http://localhost:{PORT}/callback")


class _Result:
    code: str | None = None
    realm_id: str | None = None
    state: str | None = None
    error: str | None = None


_result = _Result()
_done = threading.Event()


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != urllib.parse.urlparse(REDIRECT_URI).path:
            self.send_response(404)
            self.end_headers()
            return

        params = urllib.parse.parse_qs(parsed.query)
        _result.code = (params.get("code") or [None])[0]
        _result.realm_id = (params.get("realmId") or [None])[0]
        _result.state = (params.get("state") or [None])[0]
        _result.error = (params.get("error") or [None])[0]

        body = (
            b"<h2>Authorization received.</h2><p>Return to the terminal.</p>"
            if _result.code
            else b"<h2>Authorization failed.</h2><p>See the terminal.</p>"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        _done.set()

    def log_message(self, *args):
        pass  # the script's own output is the interface


def _exchange(code: str, client_id: str, client_secret: str) -> dict:
    """Exchange the authorization code for tokens.

    `redirect_uri` is REQUIRED here and must byte-match the one used in the authorize
    request -- Intuit validates it a second time, and a mismatch returns
    `invalid_grant`, which looks identical to an expired code.
    """
    form = urllib.parse.urlencode(
        {"grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI}
    ).encode()

    basic = base64.b64encode(f"{client_id}:{client_secret}".encode()).decode()
    request = urllib.request.Request(
        TOKEN_ENDPOINT,
        data=form,
        headers={
            "Authorization": f"Basic {basic}",  # client_secret_basic
            "Accept": "application/json",
            "Content-Type": "application/x-www-form-urlencoded",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read())
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")
        raise SystemExit(
            f"token exchange failed ({exc.code}): {detail}\n\n"
            "If this says invalid_grant, the usual causes are (1) the redirect URI "
            "registered on the Intuit app does not byte-match "
            f"{REDIRECT_URI!r}, or (2) the code was already used -- they are "
            "single-use, so start over."
        )


def main() -> int:
    client_id = os.environ.get("INTUIT_CLIENT_ID")
    client_secret = os.environ.get("INTUIT_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise SystemExit(
            "set INTUIT_CLIENT_ID and INTUIT_CLIENT_SECRET.\n"
            "Pass them as environment variables, not arguments: arguments land in "
            "your shell history and in the process list."
        )

    # CSRF protection. Without checking `state`, a third party can hand you a
    # callback for THEIR authorization code and bind your integration to their
    # company.
    state = secrets.token_urlsafe(24)

    authorize_url = f"{AUTHORIZATION_ENDPOINT}?" + urllib.parse.urlencode(
        {
            "client_id": client_id,
            "response_type": "code",
            "scope": SCOPE,
            "redirect_uri": REDIRECT_URI,
            "state": state,
        }
    )

    server = http.server.HTTPServer(("127.0.0.1", PORT), _Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()

    print(f"listening on {REDIRECT_URI}\n")
    print("Open this URL, sign in, and pick the sandbox company:\n")
    print(f"  {authorize_url}\n")
    print("waiting for the callback (Ctrl-C to abort) ...")

    try:
        if not _done.wait(timeout=300):
            raise SystemExit(
                "timed out after 5 minutes.\n"
                f"If the browser showed an Intuit error instead of returning here, "
                f"{REDIRECT_URI!r} is almost certainly not registered on the app "
                "(developer.intuit.com -> your app -> Keys & OAuth -> Redirect URIs)."
            )
    finally:
        server.shutdown()

    if _result.error:
        raise SystemExit(f"authorization denied by Intuit: {_result.error}")
    if not _result.code:
        raise SystemExit("no authorization code in the callback")
    if _result.state != state:
        # Fail closed. A mismatch means the callback did not originate from the
        # request this process made.
        raise SystemExit(
            "STATE MISMATCH -- refusing to exchange the code. The callback did not "
            "come from this authorization request."
        )
    if not _result.realm_id:
        raise SystemExit(
            "no realmId in the callback. That means no company was selected, and "
            "without it no QBO path can be built."
        )

    payload = _exchange(_result.code, client_id, client_secret)

    refresh_token = payload.get("refresh_token")
    if not refresh_token:
        raise SystemExit(f"no refresh_token in the response (keys: {sorted(payload)})")

    print("\n" + "=" * 72)
    print("AUTHORIZED")
    print("=" * 72)
    print(f"  realm_id       {_result.realm_id}")
    print(f"  refresh_token  {refresh_token}")
    print(f"  access token   expires in {payload.get('expires_in')}s (not needed; the")
    print("                 connector refreshes on demand)")
    print(f"  refresh expiry {payload.get('x_refresh_token_expires_in')}s")
    print("=" * 72)
    print(
        "\nRun the sandbox harness with:\n\n"
        "  export INTUIT_CLIENT_ID INTUIT_CLIENT_SECRET\n"
        f"  export INTUIT_REFRESH_TOKEN='{refresh_token}'\n"
        f"  export INTUIT_REALM_ID='{_result.realm_id}'\n"
        "  pytest tests/test_erp_intuit_sandbox.py -q\n"
    )
    print(
        "NOTE: that refresh token is the FIRST of a chain. Intuit issues a new one on "
        "every refresh and retires the old one, so anything storing it must store "
        "each rotation too (configuration['refresh_token_sink']). Otherwise the "
        "integration works once and then fails permanently with invalid_grant."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
