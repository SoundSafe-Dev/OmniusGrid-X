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
from client import RagClient, FORMATS, DOCS_DIR, ApiError  # noqa: E402,F401
from corpus import DOC_BY_ID, doc_format_pairs  # noqa: E402
from report import write_pytest_report  # noqa: E402

# The parametrization axis for the per-format isolation tests: one entry per
# (document, format) the corpus can ingest, e.g. "sop-qa-014-md". Content tests
# extend this with a query dimension (see test_content.py).
DOC_FORMAT_PARAMS = [pytest.param((doc_id, fmt), id=f"{doc_id}-{fmt}")
                     for (doc_id, fmt) in doc_format_pairs()]

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
    for m in ("mechanics", "retrieval", "synthesis", "negative", "hybrid",
              "isolation", "lifecycle", "robustness", "metrics", "corpus"):
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


@pytest.fixture(scope="module")
def indexed_doc_format(request, rag_client, run_id):
    """Isolate ONE (document, format): wipe everything, ingest just that one
    rendering, yield its ingestion result. Indirectly parametrized by each test
    over ``(doc_id, format)`` pairs, so pass/fail is attributable to an exact
    document+format cell and, at module scope, the same cell is ingested once and
    reused across every query that targets it. Teardown wipes so the next cell
    starts clean."""
    doc_id, fmt = request.param
    doc = DOC_BY_ID[doc_id]
    filename, ctype = doc.file(fmt)
    ingest_id = f"pytest-{doc_id}-{fmt}-{run_id}"
    rag_client.wipe_all()
    ing = rag_client.ingest(doc.path(fmt), ctype, ingest_id)
    yield {"doc_id": doc_id, "format": fmt, "ingest_id": ingest_id,
           "ingestion": ing, "client": rag_client, "doc": doc}
    rag_client.wipe_all()


# --------------------------------------------------------------------------- #
# Second-org client for tenant-isolation tests (best-effort provisioning)
# --------------------------------------------------------------------------- #
@pytest.fixture(scope="session")
def second_org_client(base_url, rag_client):
    """A client scoped to a DIFFERENT org than rag_client, for isolation tests.

    The dev-token bypass always maps to one fixed org, so a second org needs a
    real second identity. Resolution order:
      1. explicit creds — RAG_TEST_ORG_B_TOKEN, or RAG_TEST_ORG_B_EMAIL/PASSWORD
         (seed one org+user once and the cross-org tests run everywhere);
      2. best-effort self-provisioning (works only if the stack exposes a
         create-org path — this one does not, so it normally falls through);
      3. skip loudly (documented) rather than silently pass.
    """
    client = _second_org_from_env(base_url) or _try_provision_second_org(base_url, rag_client)
    if not client:
        pytest.skip(
            "No second org available. Seed one org+user and set RAG_TEST_ORG_B_TOKEN "
            "(or RAG_TEST_ORG_B_EMAIL/PASSWORD) to enable the cross-org isolation test; "
            "this stack has no create-org endpoint to self-provision one.")
    return client  # a RagClient bound to the second org's token


def _second_org_from_env(base_url):
    """A RagClient for a caller-supplied second org, or None if none configured."""
    token = os.environ.get("RAG_TEST_ORG_B_TOKEN")
    if token:
        return RagClient(base_url, token)
    email = os.environ.get("RAG_TEST_ORG_B_EMAIL")
    password = os.environ.get("RAG_TEST_ORG_B_PASSWORD")
    if email and password:
        try:
            return RagClient(base_url, RagClient.login(base_url, email, password))
        except ApiError:
            return None
    return None


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
