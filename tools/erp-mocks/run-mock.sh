#!/usr/bin/env bash
# Run a spec-driven mock of a vendor ERP API (Tier 2).
#
# The point is NOT that a mock returns data — anything can do that. It is that
# `--errors` makes Prism VALIDATE the inbound request against the vendor's own
# specification and reject anything that does not conform. That is exactly the bug
# class found throughout these connectors: a wrong host, a wrong auth scheme, a
# missing query parameter, a header carrying the wrong value. A hand-written mock
# cannot catch those, because it encodes the same assumptions as the code.
#
#   ./tools/erp-mocks/run-mock.sh sap 4010
#
# Requires a spec in tools/erp-mocks/specs/<vendor>.{json,yaml}. See README.md
# there for where each vendor's spec comes from — all of them need account access,
# which is why none are committed.
set -euo pipefail

VENDOR="${1:?usage: run-mock.sh <vendor> [port]}"
PORT="${2:-4010}"
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/specs"

SPEC=""
for ext in json yaml yml; do
  if [[ -f "$DIR/$VENDOR.$ext" ]]; then SPEC="$DIR/$VENDOR.$ext"; break; fi
done

if [[ -z "$SPEC" ]]; then
  echo "No spec for '$VENDOR' in $DIR" >&2
  echo "Expected $DIR/$VENDOR.{json,yaml,yml} — see $DIR/../README.md for how to obtain it." >&2
  exit 1
fi

echo "mocking $VENDOR from $(basename "$SPEC") on :$PORT (requests are validated)"
exec npx --yes @stoplight/prism-cli@5.16.0 mock "$SPEC" --port "$PORT" --errors
