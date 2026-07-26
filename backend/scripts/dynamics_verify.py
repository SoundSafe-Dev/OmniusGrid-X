#!/usr/bin/env python3
"""Verify a Dataverse app registration end to end, and name the failure precisely.

WHY THIS EXISTS. Dataverse server-to-server auth has a failure mode that is almost
impossible to read from the error alone: **the token succeeds and every data request
fails**. Getting a token only proves Microsoft Entra ID trusts the app registration.
It says nothing about whether that app has a *Dataverse user* — and without one, the
Web API answers 401 with a body that does not mention application users at all.

So this checks the two things separately and reports which one broke:

    STEP 1  can we get a token from Entra ID?          -> app registration + secret
    STEP 2  does WhoAmI answer with that token?        -> Dataverse application user

`WhoAmI` is the right probe: it is a function every caller can invoke, needs no table
privileges, and returns the `UserId` of whoever the token represents — which is
exactly the fact in question.

USAGE

    export DATAVERSE_ORG='org1a2b3c4d'          # the subdomain, NOT the full URL
    export DATAVERSE_TENANT_ID='<guid>'
    export DATAVERSE_CLIENT_ID='<guid>'
    export DATAVERSE_CLIENT_SECRET='<secret>'
    python scripts/dynamics_verify.py

The org value is the prefix of your environment URL: for
`https://org1a2b3c4d.crm.dynamics.com` it is `org1a2b3c4d`. That is also what the
connector takes as `configuration["environment"]`, since it builds
`https://{environment}.api.crm.dynamics.com/api/data/v9.2/`.

ON THE SCOPE. Confirmed against Microsoft's own documentation rather than assumed:
their example sets `resource = "https://contoso.api.crm.dynamics.com"` and the guidance
states "For a confidential client, use a scope of <environment-url>/.default". So the
`.api.` infix is valid in the scope, which is what the connector uses. Worth recording
because it looks like a mistake and is not one.
"""

from __future__ import annotations

import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from typing import NoReturn

API_VERSION = "v9.2"


def _fail(message: str) -> NoReturn:
    raise SystemExit(f"\nFAILED\n{message}\n")


def _post_form(url: str, form: dict, timeout: int = 30) -> tuple[int, dict | str]:
    data = urllib.parse.urlencode(form).encode()
    request = urllib.request.Request(
        url,
        data=data,
        headers={
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, body


def _get(url: str, token: str, timeout: int = 30) -> tuple[int, dict | str]:
    request = urllib.request.Request(
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            # Documented as required on Dataverse Web API requests; Microsoft sends
            # them on every example.
            "OData-MaxVersion": "4.0",
            "OData-Version": "4.0",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            return response.status, json.loads(response.read())
    except urllib.error.HTTPError as exc:
        body = exc.read().decode(errors="replace")
        try:
            return exc.code, json.loads(body)
        except ValueError:
            return exc.code, body


def main() -> int:
    org = os.environ.get("DATAVERSE_ORG")
    tenant_id = os.environ.get("DATAVERSE_TENANT_ID")
    client_id = os.environ.get("DATAVERSE_CLIENT_ID")
    client_secret = os.environ.get("DATAVERSE_CLIENT_SECRET")

    missing = [
        name
        for name, value in (
            ("DATAVERSE_ORG", org),
            ("DATAVERSE_TENANT_ID", tenant_id),
            ("DATAVERSE_CLIENT_ID", client_id),
            ("DATAVERSE_CLIENT_SECRET", client_secret),
        )
        if not value
    ]
    if missing:
        raise SystemExit(
            "set " + ", ".join(missing) + "\n"
            "Pass them as environment variables, not arguments: arguments land in "
            "shell history and in the process list."
        )

    if "." in org or "//" in org:
        raise SystemExit(
            f"DATAVERSE_ORG should be the SUBDOMAIN only, not a URL. Got {org!r}.\n"
            "For https://org1a2b3c4d.crm.dynamics.com use 'org1a2b3c4d'."
        )

    resource = f"https://{org}.api.crm.dynamics.com"
    token_url = f"https://login.microsoftonline.com/{tenant_id}/oauth2/v2.0/token"

    # ---------------------------------------------------------------- step 1
    print(f"STEP 1  token from Entra ID for {resource}")
    status, payload = _post_form(
        token_url,
        {
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            # `.default` is required for client-credentials: Entra ID grants the
            # app's configured permissions rather than an ad-hoc scope list.
            "scope": f"{resource}/.default",
        },
    )

    if status != 200 or not isinstance(payload, dict) or "access_token" not in payload:
        error = payload.get("error") if isinstance(payload, dict) else None
        description = payload.get("error_description", "") if isinstance(payload, dict) else str(payload)
        # Matched on the exact code, not as a bare substring: "AADSTS90002" is a
        # prefix of "AADSTS900021", which is a DIFFERENT error, so a substring test
        # silently attributes one to the other.
        def _has(code: str) -> bool:
            return bool(re.search(rf"\b{code}\b", description))

        hint = ""
        if _has("AADSTS700016") or error == "unauthorized_client":
            hint = "The client id is not a registered app in this tenant."
        elif _has("AADSTS7000215"):
            hint = "The client secret is wrong or has expired."
        elif _has("AADSTS500011"):
            hint = (
                f"Entra ID does not recognise {resource} as a resource in this tenant.\n"
                "  Usually this means DATAVERSE_ORG is wrong, or the environment lives\n"
                "  in a different tenant than DATAVERSE_TENANT_ID."
            )
        elif _has("AADSTS90002"):
            hint = "That tenant does not exist."
        elif _has("AADSTS900021"):
            hint = "The tenant identifier is malformed (not a valid GUID or domain)."
        _fail(
            f"could not get a token ({status}).\n"
            f"  error: {error}\n"
            f"  {description[:400]}\n"
            + (f"\n  LIKELY CAUSE: {hint}\n" if hint else "")
        )

    token = payload["access_token"]
    print(f"        OK  token acquired, expires_in={payload.get('expires_in')}s")
    print("        NOTE: this proves the app registration and secret only. It does")
    print("              NOT prove the app can read Dataverse. That is step 2.\n")

    # ---------------------------------------------------------------- step 2
    whoami_url = f"{resource}/api/data/{API_VERSION}/WhoAmI"
    print(f"STEP 2  WhoAmI against {whoami_url}")
    status, payload = _get(whoami_url, token)

    if status == 200 and isinstance(payload, dict) and payload.get("UserId"):
        print(f"        OK  UserId={payload['UserId']}")
        print(f"            BusinessUnitId={payload.get('BusinessUnitId')}")
        print(f"            OrganizationId={payload.get('OrganizationId')}\n")
        print("=" * 72)
        print("VERIFIED — this app registration can read Dataverse.")
        print("=" * 72)
        print("\nConnector configuration:\n")
        print("  auth_config = {")
        print(f'      "tenant_id":     "{tenant_id}",')
        print(f'      "client_id":     "{client_id}",')
        print('      "client_secret": "<the secret>",')
        print("  }")
        print("  configuration = {")
        print(f'      "environment": "{org}",')
        print('      "api_type":    "dataverse",')
        print("  }")
        print("\nRun the harness:\n")
        print("  export DATAVERSE_ORG DATAVERSE_TENANT_ID DATAVERSE_CLIENT_ID \\")
        print("         DATAVERSE_CLIENT_SECRET")
        print("  pytest tests/test_erp_dynamics_sandbox.py -q")
        print("\nAnd fetch the schema for a Tier 2 mock:\n")
        print("  export DATAVERSE_ORG_URL='https://%s.crm.dynamics.com'" % org)
        print("  export DATAVERSE_BEARER_TOKEN='<a token from step 1>'")
        print("  ./tools/erp-mocks/fetch-spec.sh dynamics")
        return 0

    # THE FAILURE THIS SCRIPT EXISTS FOR.
    detail = json.dumps(payload)[:400] if isinstance(payload, dict) else str(payload)[:400]

    # Dataverse's own wording for this is actively misleading: 403 with
    # 0x80072560 "The user is not a member of the organization." Nothing in that
    # points at an application user, and it reads like an account was removed from
    # something. Confirmed against a real environment on 2026-07-26: this is
    # precisely what a correct app registration with NO application user returns.
    signature = "0x80072560" in detail or "not a member of the organization" in detail
    certainty = (
        "THIS IS THE MISSING APPLICATION USER -- confirmed by the error signature."
        if signature
        else "THIS IS ALMOST CERTAINLY THE MISSING APPLICATION USER."
    )

    _fail(
        f"the token WORKED but Dataverse rejected the request ({status}).\n"
        f"  {detail}\n\n"
        f"  {certainty}\n\n"
        "  A token proves only that Entra ID trusts the app registration. To read\n"
        "  data, the app also needs a Dataverse USER bound to it:\n\n"
        "    Power Platform admin center -> Environments -> your environment\n"
        "      -> Settings -> Users + permissions -> Application users\n"
        "      -> + New app user -> add your app registration\n"
        "      -> assign a security role (System Administrator is fine for a dev\n"
        "         environment; a custom least-privilege role for anything real)\n\n"
        "  Two things that catch people here:\n"
        "    - S2S needs NO API permissions on the app registration. Adding\n"
        "      'Access Dynamics 365 as organization users' is for the DELEGATED\n"
        "      flow and does not substitute for an application user.\n"
        "    - An application user consumes no paid licence, so this is not a\n"
        "      licensing problem.\n"
    )


if __name__ == "__main__":
    sys.exit(main())
