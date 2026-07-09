"""OpenAPI polish helpers (task 11).

FastAPI's default operationIds embed the full path and read badly as generated
SDK method names (e.g. ``list_operations_api_v1_operations__get``). A stable,
clean ``{tag}_{route_name}`` scheme makes the generated TypeScript client
readable and diff-stable across schema regenerations.
"""

import re

from fastapi.routing import APIRoute

_NON_ALNUM = re.compile(r"[^a-zA-Z0-9]+")


def custom_generate_unique_id(route: APIRoute) -> str:
    """Produce a clean, stable operationId: ``<tag>_<route_name>``.

    Uses the route's first tag (lower snake) + its handler name. Falls back to
    ``default`` when a route has no tag. Stable across runs, so regenerating the
    SDK yields minimal diffs.
    """
    tag = str(route.tags[0]) if route.tags else "default"
    tag = _NON_ALNUM.sub("_", tag).strip("_").lower()
    return f"{tag}_{route.name}"
