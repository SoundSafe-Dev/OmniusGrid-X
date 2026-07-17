#!/usr/bin/env bash
# Generate the typed TypeScript API client from the backend OpenAPI schema (task 11).
#
# Pipeline:
#   1. Dump backend OpenAPI schema offline  -> backend/openapi.json
#   2. Codegen TS types with openapi-typescript -> frontend/src/api/generated/schema.d.ts
#
# The generated client bridges FE<->BE: the frontend imports typed request/response
# shapes straight from the backend contract instead of hand-maintaining them.
#
# Requires: python (backend deps), npx (openapi-typescript is fetched on demand).
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
SCHEMA="$ROOT/backend/openapi.json"
OUT_DIR="$ROOT/frontend/src/api/generated"

echo "==> Dumping OpenAPI schema"
python "$ROOT/backend/scripts/generate_openapi.py" "$SCHEMA"

echo "==> Generating TypeScript types"
mkdir -p "$OUT_DIR"
npx --yes openapi-typescript "$SCHEMA" -o "$OUT_DIR/schema.d.ts"

echo "==> Done: $OUT_DIR/schema.d.ts"
