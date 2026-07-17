# Generated API client (do not edit by hand)

`schema.d.ts` is generated from the backend OpenAPI contract. Regenerate with:

```bash
./scripts/generate_sdk.sh
```

which dumps `backend/openapi.json` (via `backend/scripts/generate_openapi.py`)
and runs `openapi-typescript` into this directory. Import the typed request/
response shapes from here instead of hand-maintaining them in the api clients.
