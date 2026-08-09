"""Validate the SAP connector against SAP's public sandbox (Tier 4).

SAP publishes a live, free sandbox on the Business Accelerator Hub. It answers real
OData — real `$metadata`, real entity sets, real `$batch` — which makes it the only
way to exercise our multipart parser against genuine SAP output rather than the
fixture I wrote for it.

WHAT IS ALREADY ESTABLISHED (probed, not assumed):

    endpoint  https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap/<SERVICE>
    auth      an `apikey: <key>` REQUEST HEADER — not OAuth, not Bearer.
              Without it the sandbox returns 401 with
              {"fault":{"faultstring":"Failed to resolve API Key variable
              request.header.apikey", ...}}

WHAT YOU MUST SUPPLY: the key itself. It is free — a personal account on
api.sap.com issues one — but it is issued to a person, so it cannot be obtained
here. Set SAP_SANDBOX_API_KEY and these tests run; leave it unset and they skip.

NOTE ON AUTH SHAPE. The sandbox uses an API key where a real S/4HANA system uses
OAuth2 client-credentials. So this validates the URL construction, the OData query
options, the response envelope and — the valuable part — the `$batch` multipart
parsing against real SAP bytes. It does NOT validate the OAuth2 flow, which stays
covered by the request-shape tests.
"""

from __future__ import annotations

import os

import aiohttp
import pytest

from app.services.erp_connectors.sap_batch import (
    extract_boundary,
    parse_batch_response,
    rows_from_batch,
)

API_KEY = os.environ.get("SAP_SANDBOX_API_KEY")

pytestmark = pytest.mark.skipif(
    not API_KEY,
    reason=(
        "needs a free SAP Business Accelerator Hub key: set SAP_SANDBOX_API_KEY "
        "(https://api.sap.com -> profile -> API Key)"
    ),
)

SANDBOX = "https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap"
SERVICE = os.environ.get("SAP_SANDBOX_SERVICE", "API_PURCHASEORDER_PROCESS_SRV")
ENTITY_SET = os.environ.get("SAP_SANDBOX_ENTITY_SET", "A_PurchaseOrder")


def _headers(accept: str = "application/json") -> dict:
    # `apikey`, lowercase, as a request header — established by probing the
    # sandbox's 401 body, which names the variable it could not resolve.
    return {"apikey": API_KEY, "Accept": accept}


async def _get(path: str, params: dict | None = None, accept: str = "application/json"):
    async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
        async with session.get(
            f"{SANDBOX}/{SERVICE}/{path}", headers=_headers(accept), params=params
        ) as r:
            return r.status, dict(r.headers), await r.text()


class TestSandboxReachability:
    async def test_metadata_is_reachable_with_the_key(self):
        """Fails loudly on 401 rather than skipping, so a stale or wrong key is
        distinguishable from an absent one.

        `Accept: application/xml` is required. Real SAP returns 406 for
        `application/json` on $metadata — the document is EDMX, and SAP refuses
        rather than negotiating. Learned from the sandbox: my first version of this
        test sent JSON and got
        "only capable of generating response entities which have content
        characteristics not acceptable according to the accept headers sent".
        No connector fetches $metadata, so this is a property of the probe, not a
        connector defect.
        """
        status, _, body = await _get("$metadata", accept="application/xml")
        assert status == 200, f"sandbox rejected the key ({status}): {body[:300]}"
        assert "EntityType" in body, "response does not look like OData metadata"

    async def test_entity_set_returns_real_rows(self):
        """Query options must target an ENTITY SET, not the service root.

        Requesting the service document with `$top` returns 400: "System query
        options ... are not allowed in the requested URI". Another thing the
        sandbox taught rather than the documentation.
        """
        status, _, body = await _get(ENTITY_SET, params={"$top": "2", "$format": "json"})
        assert status == 200, body[:400]
        assert '"d"' in body or '"value"' in body


class TestBatchAgainstRealSapOutput:
    """The reason this harness is worth building.

    `sap_batch.py` was written against a fixture I authored, so it encodes my own
    assumptions about SAP's multipart formatting — boundary style, line endings,
    whether Content-ID appears, how the HTTP part is framed. Only real SAP bytes
    can disconfirm those.
    """

    async def test_batch_response_parses(self):
        boundary = "batch_omniusgrid_probe"
        body = (
            f"--{boundary}\r\n"
            "Content-Type: application/http\r\n"
            "Content-Transfer-Encoding: binary\r\n"
            "\r\n"
            f"GET {ENTITY_SET}?$top=1&$format=json HTTP/1.1\r\n"
            "Accept: application/json\r\n"
            "\r\n"
            "\r\n"
            f"--{boundary}--\r\n"
        )

        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=60)) as session:
            async with session.post(
                f"{SANDBOX}/{SERVICE}/$batch",
                headers={**_headers(), "Content-Type": f"multipart/mixed; boundary={boundary}"},
                data=body,
            ) as response:
                status = response.status
                content_type = response.headers.get("Content-Type", "")
                text = await response.text()

        assert status in (200, 202), f"{status}: {text[:400]}"

        # The RESPONSE boundary is chosen by SAP and is not the one we sent —
        # parsing with the sent boundary matches nothing, which looks exactly like
        # an empty result. This asserts we read it from Content-Type.
        response_boundary = extract_boundary(content_type)
        assert response_boundary, f"no boundary in Content-Type: {content_type!r}"
        assert response_boundary != boundary, (
            "SAP echoed our boundary — the assumption that it differs is worth "
            "revisiting, but parsing must still read it from the header"
        )

        parts = parse_batch_response(text, response_boundary)
        assert parts, f"parsed zero parts from a real SAP batch response:\n{text[:600]}"
        assert parts[0].status == 200, f"part status {parts[0].status}: {parts[0].raw_body[:200]}"

        rows = rows_from_batch(parts, strict=True)
        assert isinstance(rows, list)
