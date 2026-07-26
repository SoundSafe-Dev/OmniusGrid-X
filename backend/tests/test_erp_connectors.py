"""ERP connector guards: importability, auth flow, and batch parsing.

THE HEADLINE DEFECT. Three of the seven connectors could not be IMPORTED. SAP and
Oracle did `from requests_oauthlib import OAuth2Session`; Dynamics did
`import msal`. Neither package is in requirements.txt, so every one of those
modules raised ImportError — and `erp_connector_factory` maps ERPType.SAP,
ERPType.ORACLE and ERPType.DYNAMICS straight at them. Constructing any of those
three integrations failed before a line of their own logic ran.

Nothing caught it because nothing imported them: the factory resolves lazily by
string, so the failure only appeared when a customer's integration was actually
configured. `test_every_connector_is_importable` is the guard.
"""

from __future__ import annotations

import importlib
from typing import Any, Dict, List
from unittest.mock import patch

import pytest

from app.services.erp_connector_base import AuthType, ERPConfig, ERPType
from app.services.erp_connectors.oauth2 import (
    OAuth2Error,
    fetch_client_credentials_token,
    parse_token_payload,
)
from app.services.erp_connectors.sap_batch import (
    extract_boundary,
    parse_batch_response,
    rows_from_batch,
)


# ---------------------------------------------------------------------------
# Importability
# ---------------------------------------------------------------------------

CONNECTOR_MODULES = [
    "app.services.erp_connectors.sap_connector",
    "app.services.erp_connectors.oracle_connector",
    "app.services.erp_connectors.dynamics_connector",
    "app.services.erp_connectors.netsuite_connector",
    "app.services.erp_connectors.infor_connector",
    "app.services.erp_connectors.epicor_connector",
    "app.services.erp_connectors.odoo_connector",
]


class TestImportability:
    @pytest.mark.parametrize("module", CONNECTOR_MODULES)
    def test_every_connector_is_importable(self, module: str):
        """A connector that cannot be imported is an integration that cannot exist.

        The factory resolves by string at call time, so an ImportError here does
        not surface until a real customer integration is configured — which is why
        this went unnoticed.
        """
        importlib.import_module(module)

    def test_every_factory_target_resolves(self):
        """Whatever the factory advertises must actually load."""
        from app.services.erp_connector_factory import _resolve_class
        from app.services.erp_connector_base import ERPType as T

        for erp_type in (T.SAP, T.ORACLE, T.DYNAMICS, T.NETSUITE, T.INFOR):
            cls = _resolve_class(erp_type)
            assert isinstance(cls, type), f"{erp_type} did not resolve to a class"

    def test_connectors_do_not_import_blocking_oauth_libraries(self):
        """`requests_oauthlib` and `msal` are synchronous.

        Installing them would have fixed the ImportError and introduced a worse
        bug: a blocking token round-trip inside an async connector stalls the whole
        event loop, so every other in-flight request waits on an ERP handshake.
        """
        import ast
        from pathlib import Path

        root = Path(__file__).resolve().parents[1] / "app" / "services" / "erp_connectors"
        offenders = []
        for path in root.glob("*.py"):
            tree = ast.parse(path.read_text())
            for node in ast.walk(tree):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name.split(".")[0] for a in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    names = [node.module.split(".")[0]]
                for name in names:
                    if name in {"requests_oauthlib", "msal", "requests"}:
                        offenders.append(f"{path.name}: {name}")
        assert not offenders, (
            f"blocking HTTP/OAuth libraries in async connectors: {offenders}. "
            "Use app/services/erp_connectors/oauth2.py."
        )


# ---------------------------------------------------------------------------
# OAuth2 client credentials
# ---------------------------------------------------------------------------

class _Resp:
    def __init__(self, status: int, text: str):
        self.status = status
        self._text = text

    async def text(self):
        return self._text

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


class _Session:
    def __init__(self, response: _Resp):
        self._response = response
        self.calls: List[Dict[str, Any]] = []

    def post(self, url, data=None, headers=None, **kw):
        self.calls.append({"url": url, "data": data, "headers": headers})
        return self._response

    async def close(self):
        return None


class TestOAuth2ClientCredentials:
    async def test_sends_the_client_credentials_grant(self):
        session = _Session(_Resp(200, '{"access_token":"tok","expires_in":900}'))
        token, expires_in = await fetch_client_credentials_token(
            token_url="https://idp/token",
            client_id="cid",
            client_secret="csec",
            scope="https://erp/.default",
            session=session,
        )
        assert token == "tok"
        assert expires_in == 900
        form = session.calls[0]["data"]
        # The grant matters: SAP used authorization_code, which needs a browser
        # redirect a scheduled sync does not have.
        assert form["grant_type"] == "client_credentials"
        assert form["client_id"] == "cid"
        assert form["scope"] == "https://erp/.default"

    async def test_error_body_is_surfaced_not_swallowed(self):
        session = _Session(_Resp(401, '{"error":"invalid_client"}'))
        with pytest.raises(OAuth2Error, match="invalid_client"):
            await fetch_client_credentials_token(
                token_url="https://idp/token",
                client_id="cid",
                client_secret="bad",
                session=session,
            )

    async def test_non_json_response_is_reported_clearly(self):
        session = _Session(_Resp(200, "<html>gateway</html>"))
        with pytest.raises(OAuth2Error, match="non-JSON"):
            await fetch_client_credentials_token(
                token_url="https://idp/token", client_id="c", client_secret="s", session=session
            )

    def test_missing_access_token_is_an_error(self):
        with pytest.raises(OAuth2Error, match="access_token"):
            parse_token_payload({"token_type": "Bearer"})

    def test_expires_in_is_returned_for_the_caller_to_honour(self):
        """The base class used to assume one hour for every provider, so a shorter
        token was served from cache long after it died."""
        assert parse_token_payload({"access_token": "t", "expires_in": 300}) == ("t", 300.0)
        assert parse_token_payload({"access_token": "t"}) == ("t", None)


# ---------------------------------------------------------------------------
# SAP $batch parsing
# ---------------------------------------------------------------------------

BATCH_BODY = (
    "--batchresponse_abc\r\n"
    "Content-Type: application/http\r\n"
    "Content-ID: 1\r\n"
    "\r\n"
    "HTTP/1.1 200 OK\r\n"
    "Content-Type: application/json\r\n"
    "\r\n"
    '{"d":{"results":[{"PurchaseOrder":"4500000001"},{"PurchaseOrder":"4500000002"}]}}\r\n'
    "--batchresponse_abc\r\n"
    "Content-Type: application/http\r\n"
    "Content-ID: 2\r\n"
    "\r\n"
    "HTTP/1.1 400 Bad Request\r\n"
    "Content-Type: application/json\r\n"
    "\r\n"
    '{"error":{"message":"Invalid filter"}}\r\n'
    "--batchresponse_abc--\r\n"
)


class TestSapBatchParsing:
    def test_parses_every_part_with_its_own_status(self):
        """The old parser split each part on the first blank line and read element
        [1] as JSON — but that is the HTTP status line and headers, not the body.
        json.loads raised on every part and a bare except swallowed it, so $batch
        returned an empty list while reporting success."""
        parts = parse_batch_response(BATCH_BODY, "batchresponse_abc")
        assert len(parts) == 2
        assert parts[0].status == 200 and parts[0].ok
        assert parts[1].status == 400 and not parts[1].ok
        assert parts[0].content_id == "1"

    def test_extracts_rows_from_the_odata_v2_envelope(self):
        parts = parse_batch_response(BATCH_BODY, "batchresponse_abc")
        rows = rows_from_batch(parts, strict=False)
        assert [r["PurchaseOrder"] for r in rows] == ["4500000001", "4500000002"]

    def test_a_failed_operation_is_not_silently_dropped(self):
        """A batch where 2 of 5 operations 400 must not look like a smaller
        successful batch."""
        parts = parse_batch_response(BATCH_BODY, "batchresponse_abc")
        with pytest.raises(RuntimeError, match="failed"):
            rows_from_batch(parts, strict=True)

    def test_response_boundary_is_read_from_the_content_type(self):
        """The server picks the response boundary; parsing with the boundary that
        was SENT matches nothing, which looks exactly like an empty result."""
        assert extract_boundary('multipart/mixed; boundary=batchresponse_abc') == "batchresponse_abc"
        assert extract_boundary('multipart/mixed; boundary="quoted_bnd"') == "quoted_bnd"
        assert extract_boundary("") is None

    def test_handles_nested_changesets(self):
        """Write operations arrive inside a changeset with its OWN boundary; a
        single-level split walks straight past them."""
        body = (
            "--outer\r\n"
            "Content-Type: multipart/mixed; boundary=changeset_1\r\n"
            "\r\n"
            "--changeset_1\r\n"
            "Content-Type: application/http\r\n"
            "\r\n"
            "HTTP/1.1 201 Created\r\n"
            "Content-Type: application/json\r\n"
            "\r\n"
            '{"d":{"results":[{"Id":"new-1"}]}}\r\n'
            "--changeset_1--\r\n"
            "--outer--\r\n"
        )
        parts = parse_batch_response(body, "outer")
        assert len(parts) == 1
        assert parts[0].status == 201
        assert rows_from_batch(parts, strict=False) == [{"Id": "new-1"}]

    def test_tolerates_lf_line_endings(self):
        """The spec says CRLF, but fixtures and text-mode proxies produce LF. A
        CRLF-only parser silently yields zero parts."""
        body = BATCH_BODY.replace("\r\n", "\n")
        parts = parse_batch_response(body, "batchresponse_abc")
        assert len(parts) == 2

    def test_odata_v4_value_envelope(self):
        body = (
            "--b\r\nContent-Type: application/http\r\n\r\n"
            "HTTP/1.1 200 OK\r\nContent-Type: application/json\r\n\r\n"
            '{"value":[{"A":1}]}\r\n--b--\r\n'
        )
        rows = rows_from_batch(parse_batch_response(body, "b"), strict=False)
        assert rows == [{"A": 1}]

    def test_empty_body_yields_no_parts_rather_than_raising(self):
        assert parse_batch_response("", "b") == []


# ---------------------------------------------------------------------------
# Epicor + Odoo
# ---------------------------------------------------------------------------

def _cfg(erp_type, auth_type, auth, configuration):
    return ERPConfig(
        erp_type=erp_type,
        base_url="https://erp.example.com",
        auth_type=auth_type,
        auth_config=auth,
        rate_limit={"requests_per_minute": 600},
        configuration=configuration,
    )


class TestEpicorHeaders:
    def test_api_key_header_no_longer_carries_the_company_id(self):
        """`X-API-Key` was set to `self.company_id` — the company IDENTIFIER, not a
        credential — so Epicor received the wrong value in the API-key header and
        the real key was sent as a Bearer token it does not accept."""
        from app.services.erp_connectors.epicor_connector import EpicorConnector

        conn = EpicorConnector(
            _cfg(ERPType.EPICOR, AuthType.API_KEY, {"api_key": "real-key"},
                 {"company_id": "EPIC01", "site_id": "MAIN"}),
            "org", "int",
        )
        headers = conn._auth_headers("real-key")

        assert headers["X-API-Key"] == "real-key"
        assert headers["X-API-Key"] != "EPIC01"
        # Company/site scoping belongs in CallSettings, which is where Epicor reads it.
        assert "EPIC01" in headers["CallSettings"]
        assert "Authorization" not in headers, "an API key must not be sent as a bearer"

    def test_basic_auth_builds_a_basic_header(self):
        from app.services.erp_connectors.epicor_connector import EpicorConnector

        conn = EpicorConnector(
            _cfg(ERPType.EPICOR, AuthType.BASIC, {"username": "u", "password": "p"},
                 {"company_id": "EPIC01"}),
            "org", "int",
        )
        headers = conn._auth_headers("unused")
        assert headers["Authorization"].startswith("Basic ")

    def test_oauth2_uses_a_bearer(self):
        from app.services.erp_connectors.epicor_connector import EpicorConnector

        conn = EpicorConnector(
            _cfg(ERPType.EPICOR, AuthType.OAUTH2, {"client_id": "c"}, {"company_id": "E"}),
            "org", "int",
        )
        assert conn._auth_headers("tok")["Authorization"] == "Bearer tok"


class TestOdooRpc:
    def test_filters_become_an_odoo_domain(self):
        """RPC needs (field, op, value) triples. Passing the REST filter STRING
        would raise a server-side fault."""
        from app.services.erp_connectors.odoo_connector import OdooConnector

        conn = OdooConnector(
            _cfg(ERPType.ODOO, AuthType.API_KEY, {"api_key": "k", "username": "u"},
                 {"db_name": "db", "api_type": "jsonrpc"}),
            "org", "int",
        )
        assert conn._build_rpc_domain({"state": "done"}) == [("state", "=", "done")]
        assert conn._build_rpc_domain(None) == []

    async def test_rpc_fault_in_a_200_body_is_raised(self):
        """JSON-RPC reports application errors with HTTP 200. Treating 200 as
        success turns an Odoo access-rights failure into an empty result set."""
        from app.services.erp_connectors.odoo_connector import OdooConnector

        conn = OdooConnector(
            _cfg(ERPType.ODOO, AuthType.API_KEY, {"api_key": "k", "username": "u"},
                 {"db_name": "db", "api_type": "jsonrpc"}),
            "org", "int",
        )

        class _S:
            def post(self, *a, **kw):
                return _Resp(200, '{"error":{"data":{"message":"Access Denied"}}}')

            async def close(self):
                return None

            async def __aenter__(self):
                return self

            async def __aexit__(self, *e):
                return False

        with patch("aiohttp.ClientSession", return_value=_S()):
            with pytest.raises(Exception, match="Access Denied"):
                await conn._jsonrpc("object", "execute_kw", [])
