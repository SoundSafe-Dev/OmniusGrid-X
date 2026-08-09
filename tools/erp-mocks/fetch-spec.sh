#!/usr/bin/env bash
# Fetch a vendor's machine-readable API spec FROM THE VENDOR'S OWN SYSTEM (Tier 2).
#
#   ./tools/erp-mocks/fetch-spec.sh sap
#   ./tools/erp-mocks/fetch-spec.sh netsuite customer,salesOrder
#   ./tools/erp-mocks/fetch-spec.sh dynamics
#
# WHY A SCRIPT AND NOT A DOC. Every one of these endpoints needs a DIFFERENT Accept
# header, and getting it wrong returns 406 or HTML rather than a spec. That is not a
# footnote — SAP's $metadata returns 406 for `Accept: application/json`, which cost
# a real debugging cycle against the live sandbox (see
# backend/tests/test_erp_sap_sandbox.py). Encoding the header per vendor here means
# nobody pays that twice.
#
# Specs land in specs/<vendor>.{json,xml} and are gitignored: they are vendor
# material, they are large, and a per-tenant spec contains that tenant's custom
# fields. run-mock.sh picks them up automatically.
set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUT="$DIR/specs"
VENDOR="${1:?usage: fetch-spec.sh <sap|netsuite|dynamics|epicor|infor> [filter]}"
FILTER="${2:-}"

need() {
  # Fails with the exact provisioning step, not just "unset variable" — a missing
  # credential should tell you where to get it.
  local var="$1" where="$2"
  if [[ -z "${!var:-}" ]]; then
    echo "error: \$$var is not set." >&2
    echo "       $where" >&2
    exit 2
  fi
}

case "$VENDOR" in

  sap)
    # VERIFIED WORKING against the live sandbox on 2026-07-26.
    #
    # Accept MUST be application/xml. `application/json` returns 406: the document
    # is EDMX and SAP refuses to negotiate. This is the header lesson that motivated
    # this whole script.
    #
    # Yields EDMX/CSDL, which Prism cannot mock directly — convert to OpenAPI 3
    # (`odata-openapi3`, or api.sap.com -> the API -> Download Specification, which
    # hands you OpenAPI 3 straight off). The EDMX is still worth having: it is the
    # authoritative field list for the extraction layer.
    need SAP_SANDBOX_API_KEY "free key from https://api.sap.com -> your profile -> API Key (Show/Copy)"
    SERVICE="${SAP_SANDBOX_SERVICE:-API_PURCHASEORDER_PROCESS_SRV}"
    URL="https://sandbox.api.sap.com/s4hanacloud/sap/opu/odata/sap/$SERVICE/\$metadata"
    # `--compressed` is REQUIRED, not an optimization. SAP gzips $metadata whether or
    # not you ask, and curl only inflates when told to. Without it you get 13KB of
    # gzip in a file named .xml, which every EDMX converter rejects with an error
    # that says nothing about compression. Found by looking at the bytes.
    echo "GET $URL  (Accept: application/xml, gzip)"
    curl -fsS --compressed "$URL" \
      -H "apikey: $SAP_SANDBOX_API_KEY" \
      -H "Accept: application/xml" \
      -o "$OUT/sap.xml"
    # A file that is not the format we claim is worse than no file: it fails later,
    # somewhere else, for a reason that looks unrelated.
    if ! head -c 512 "$OUT/sap.xml" | grep -q 'Edmx\|EntityType'; then
      echo "error: response is not EDMX. First bytes:" >&2
      head -c 120 "$OUT/sap.xml" | od -c | head -3 >&2
      exit 1
    fi
    echo "wrote $OUT/sap.xml ($(wc -c <"$OUT/sap.xml" | tr -d ' ') bytes, EDMX)"
    echo "NOTE: EDMX, not OpenAPI. Convert before run-mock.sh can serve it."
    ;;

  netsuite)
    # NetSuite generates the OpenAPI 3 document from YOUR account, so it includes
    # your custom records and fields. There is no generic public file to download.
    #
    # Accept MUST be application/swagger+json to get OpenAPI 3 rather than the
    # catalog's own JSON-schema listing.
    #
    # FILTER HARD. The unfiltered catalog covers every record type in the account;
    # it is enormous and routinely times out. Pass a comma-separated record list:
    #   ./fetch-spec.sh netsuite customer,salesOrder,purchaseOrder
    #
    # The host here is the same one app/services/erp_connectors/netsuite_auth.py
    # builds (account lowercased, `_` -> `-`). That helper exists because the
    # connector originally pointed at `suitetalk.net`, which does not resolve.
    need NETSUITE_ACCOUNT_ID "your account number, e.g. 123456 or 123456-sb1 for a sandbox"
    need NETSUITE_BEARER_TOKEN "an OAuth2 access token, or swap the header below for OAuth 1.0a TBA"
    HOST="$(echo "$NETSUITE_ACCOUNT_ID" | tr '[:upper:]_' '[:lower:]-')"
    URL="https://$HOST.suitetalk.api.netsuite.com/services/rest/record/v1/metadata-catalog"
    [[ -n "$FILTER" ]] && URL="$URL?select=$FILTER"
    echo "GET $URL  (Accept: application/swagger+json)"
    [[ -z "$FILTER" ]] && echo "WARNING: no filter — the full catalog is very large and often times out." >&2
    curl -fsS --compressed --max-time 600 "$URL" \
      -H "Authorization: Bearer $NETSUITE_BEARER_TOKEN" \
      -H "Accept: application/swagger+json" \
      -o "$OUT/netsuite.json"
    echo "wrote $OUT/netsuite.json ($(wc -c <"$OUT/netsuite.json" | tr -d ' ') bytes)"
    ;;

  dynamics)
    # Dataverse exposes its schema two ways. Both are fetched here because they
    # answer different questions.
    #
    #   $metadata      -> CSDL/XML, the whole model, convertible to OpenAPI
    #   EntityDefinitions -> JSON, queryable with $select/$filter/$expand
    #
    # OData-MaxVersion and OData-Version are documented as required on Dataverse
    # Web API requests -- Microsoft sends them on every example. Our connector does
    # send both on its read path (dynamics_connector.py:139-140); its webhook path
    # does not, which is one of several problems there.
    #
    # Metadata queries are NOT paged: "There are no limits on the number of metadata
    # entities that a query returns." So one request returns everything -- and with
    # many languages provisioned it gets large. LabelLanguages=1033 trims it.
    #
    # Ref: https://learn.microsoft.com/en-us/power-apps/developer/data-platform/webapi/query-metadata-web-api
    need DATAVERSE_ORG_URL "your environment URL, e.g. https://contoso.crm.dynamics.com (free: a Power Apps developer plan)"
    need DATAVERSE_BEARER_TOKEN "an Azure AD access token with the Dataverse scope (\$DATAVERSE_ORG_URL/.default)"
    BASE="${DATAVERSE_ORG_URL%/}/api/data/v9.2"
    ODATA=(-H "Authorization: Bearer $DATAVERSE_BEARER_TOKEN"
           -H "OData-MaxVersion: 4.0" -H "OData-Version: 4.0")

    echo "GET $BASE/\$metadata  (Accept: application/xml)"
    curl -fsS --compressed "$BASE/\$metadata" "${ODATA[@]}" -H "Accept: application/xml" -o "$OUT/dynamics.xml"
    echo "wrote $OUT/dynamics.xml ($(wc -c <"$OUT/dynamics.xml" | tr -d ' ') bytes, CSDL)"

    # LogicalName + EntitySetName is what the extraction layer actually needs: the
    # entity set name is NOT derivable from the logical name (`account` -> `accounts`
    # happens to pluralize, plenty do not), and guessing it produces a 404 that
    # looks like an empty result.
    Q="EntityDefinitions?\$select=LogicalName,EntitySetName,PrimaryIdAttribute,PrimaryNameAttribute&LabelLanguages=1033"
    echo "GET $BASE/$Q  (Accept: application/json)"
    curl -fsS --compressed "$BASE/$Q" "${ODATA[@]}" -H "Accept: application/json" -o "$OUT/dynamics-entities.json"
    echo "wrote $OUT/dynamics-entities.json ($(wc -c <"$OUT/dynamics-entities.json" | tr -d ' ') bytes)"
    echo "NOTE: CSDL, not OpenAPI. Convert dynamics.xml before run-mock.sh can serve it."
    ;;

  epicor)
    # Epicor Kinetic serves OpenAPI per environment. Documented, not verified here.
    need EPICOR_BASE_URL "your environment root, e.g. https://kinetic.example.com/MyEnv"
    need EPICOR_API_KEY "Kinetic API key (x-api-key)"
    URL="${EPICOR_BASE_URL%/}/api/swagger/v1/swagger.json"
    echo "GET $URL"
    curl -fsS --compressed "$URL" -H "x-api-key: $EPICOR_API_KEY" -H "Accept: application/json" -o "$OUT/epicor.json"
    echo "wrote $OUT/epicor.json"
    ;;

  infor)
    # Infor ION: the portal hands you a Swagger file per API suite. There is no
    # stable unauthenticated URL to script, so this is deliberately a pointer.
    echo "Infor ION specs are downloaded from the ION API portal, per suite:" >&2
    echo "  ION API -> the suite -> Download Swagger, then save as $OUT/infor.json" >&2
    exit 2
    ;;

  *)
    echo "unknown vendor '$VENDOR' (sap|netsuite|dynamics|epicor|infor)" >&2
    exit 2
    ;;
esac

echo
echo "next: ./tools/erp-mocks/run-mock.sh $VENDOR 4010"
