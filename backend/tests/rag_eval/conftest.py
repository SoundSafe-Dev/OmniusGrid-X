"""
Pytest fixtures + reporting for the RAG suite.

Run against a live stack (docker compose up). Selection:
  pytest backend/tests/rag_eval                 # everything + a model-tagged report
  pytest backend/tests/rag_eval -m retrieval    # one category
  pytest backend/tests/rag_eval -k "Q3 and csv" # one case

Auth defaults to the dev-token bypass; override with --rag-token / --rag-email /
--rag-password or RAG_TEST_* env. The active model is read from /rag/health and
stamped on the report, so runs across models are directly comparable.
"""

import os
import sys
import uuid
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))
from client import RagClient, FORMATS, DOCS_DIR, ApiError  # noqa: E402
from report import write_pytest_report  # noqa: E402

# Session result sink (written to a report at the end).
_RESULTS = []
_METRICS = {}


def pytest_addoption(parser):
    g = parser.getgroup("rag_eval")
    g.addoption("--rag-base-url", default=os.environ.get("RAG_BASE_URL", "http://localhost:8000"))
    g.addoption("--rag-token", default=os.environ.get("RAG_TEST_TOKEN"))
    g.addoption("--rag-email", default=os.environ.get("RAG_TEST_EMAIL"))
    g.addoption("--rag-password", default=os.environ.get("RAG_TEST_PASSWORD"))


def pytest_configure(config):
    for m in ("mechanics", "retrieval", "synthesis", "negative",
              "isolation", "lifecycle", "robustness", "metrics"):
        config.addinivalue_line("markers", f"{m}: RAG eval category")


# --------------------------------------------------------------------------- #
# Core fixtures
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def base_url(pytestconfig):
    return pytestconfig.getoption("--rag-base-url").rstrip("/")


@pytest.fixture(scope="session")
def rag_client(pytestconfig, base_url):
    token = RagClient.resolve_token(
        base_url,
        token=pytestconfig.getoption("--rag-token"),
        email=pytestconfig.getoption("--rag-email"),
        password=pytestconfig.getoption("--rag-password"),
    )
    client = RagClient(base_url, token)
    try:
        client.health()
        _METRICS["_model"] = client.model_tag()  # stamp every report with the model
    except ApiError as e:
        # Skip (not exit) so running the wider backend suite without a live RAG
        # stack doesn't abort — these are live integration tests.
        pytest.skip(f"RAG stack not reachable at {base_url}: {e}")
    return client


@pytest.fixture(scope="session")
def model_tag(rag_client):
    tag = rag_client.model_tag()
    _METRICS["_model"] = tag
    return tag


@pytest.fixture(scope="session")
def llm_available(rag_client):
    return rag_client.llm_available()


@pytest.fixture(scope="session")
def run_id():
    return uuid.uuid4().hex[:8]


@pytest.fixture(scope="module", params=list(FORMATS.keys()))
def indexed_format(request, rag_client, run_id):
    """Isolate ONE format: wipe everything, ingest just this format, yield its
    ingestion result. Module-scoped so each content module ingests each format
    once (5 ingests/module) and pass/fail is attributable to that format.
    Teardown wipes so the next format/module starts clean."""
    fmt = request.param
    filename, ctype = FORMATS[fmt]
    doc_id = f"pytest-{fmt}-{run_id}"
    rag_client.wipe_all()
    ing = rag_client.ingest(DOCS_DIR / filename, ctype, doc_id)
    yield {"format": fmt, "doc_id": doc_id, "ingestion": ing, "client": rag_client}
    rag_client.wipe_all()


# --------------------------------------------------------------------------- #
# Second-org client for tenant-isolation tests (best-effort provisioning)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def second_org_client(base_url, rag_client):
    """A client scoped to a DIFFERENT org than rag_client, for isolation tests.

    The dev-token bypass always maps to one fixed org, so a second org needs a
    real second user. We try open registration into a freshly created org; if the
    environment doesn't allow provisioning a distinct org, the isolation tests
    skip (documented) rather than silently pass."""
    org_id = _try_provision_second_org(base_url, rag_client)
    if not org_id:
        pytest.skip("No way to provision a second org in this environment; "
                    "seed a second org+user to enable tenant-isolation tests.")
    return org_id  # a RagClient bound to the second org's token


def _try_provision_second_org(base_url, rag_client):
    """Return a RagClient for a second org, or None if not provisionable."""
    import json
    import urllib.request
    import urllib.error
    # Attempt: create an org via an admin endpoint, then register a user in it.
    # Endpoints vary; probe a couple of likely shapes and give up cleanly.
    email = f"rageval+{uuid.uuid4().hex[:8]}@example.com"
    password = "RagEval-2nd-Org-123!"
    for org_path in ("/api/v1/organizations", "/api/v1/admin/organizations"):
        try:
            status, body = rag_client._json(
                "POST", org_path, {"name": f"rageval-{uuid.uuid4().hex[:6]}",
                                   "slug": f"rageval-{uuid.uuid4().hex[:6]}"}
            )
        except ApiError:
            continue
        new_org = (body or {}).get("id") or (body or {}).get("organization_id")
        if not new_org:
            continue
        try:
            reg = urllib.request.Request(
                f"{base_url}/api/v1/auth/register",
                data=json.dumps({"email": email, "password": password,
                                 "full_name": "RAG Eval 2nd Org",
                                 "organization_id": new_org}).encode(),
                headers={"Content-Type": "application/json"}, method="POST",
            )
            urllib.request.urlopen(reg, timeout=30).read()
            token = RagClient.login(base_url, email, password)
            return RagClient(base_url, token)
        except (urllib.error.HTTPError, urllib.error.URLError, ApiError, KeyError):
            continue
    return None


# --------------------------------------------------------------------------- #
# Result capture -> model-tagged report
# --------------------------------------------------------------------------- #
def record_result(category, name, passed, fmt="", note=""):
    _RESULTS.append({"category": category, "name": name, "passed": bool(passed),
                     "format": fmt, "note": note})


@pytest.fixture
def record():
    return record_result


def pytest_sessionfinish(session, exitstatus):
    if not _RESULTS:
        return
    tag = _METRICS.get("_model", {"llm": "unknown"})
    metrics = {k: v for k, v in _METRICS.items() if not k.startswith("_")}
    try:
        out = write_pytest_report(_RESULTS, tag, metrics)
        print(f"\n[rag_eval] report written: {out}")
    except Exception as e:  # never fail the run on report writing
        print(f"\n[rag_eval] report write failed: {e}")


def set_metric(key, value):
    _METRICS[key] = value
