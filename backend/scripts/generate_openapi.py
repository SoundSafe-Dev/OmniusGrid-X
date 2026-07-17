#!/usr/bin/env python3
"""Dump the FastAPI OpenAPI schema to a file, offline (task 11).

Imports the app and serializes ``app.openapi()`` without starting the server or
touching the database (schema generation only introspects routes). Output feeds
the TypeScript SDK codegen in ``generate_sdk.sh``.

Usage:
    python backend/scripts/generate_openapi.py [output_path]
    # default output: backend/openapi.json
"""

import json
import sys
from pathlib import Path

# Make `app` importable when run from the repo root or backend/.
BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))


def main() -> None:
    from app.main import app  # imported late so sys.path is set

    out = Path(sys.argv[1]) if len(sys.argv) > 1 else BACKEND / "openapi.json"
    schema = app.openapi()
    out.write_text(json.dumps(schema, indent=2, sort_keys=True))
    print(f"wrote {out} ({len(schema.get('paths', {}))} paths)")


if __name__ == "__main__":
    main()
