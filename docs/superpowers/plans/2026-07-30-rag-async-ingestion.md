# Async RAG Ingestion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `POST /api/v1/rag/ingest` store the blob and return `202` immediately, with a background worker doing the slow indexing and writing a status the caller can poll.

**Architecture:** A new `rag_documents` table is both the canonical per-document record and the work queue. The ingest request writes the blob to SeaweedFS then UPSERTs a `queued` row. A dedicated worker (`app/workers/rag_indexing.py`) polls, claims rows with `SELECT … FOR UPDATE SKIP LOCKED`, runs the existing parse/chunk/embed/upsert pipeline, and writes a terminal status. No Kafka — see the spec for why.

**Tech Stack:** Python 3.11, FastAPI, SQLAlchemy 2.0 async, asyncpg, Postgres 15 (TimescaleDB image), pytest + pytest-asyncio (`asyncio_mode = auto`), testcontainers, Docker Compose, Kustomize.

**Spec:** `docs/superpowers/specs/2026-07-30-rag-async-ingestion-design.md`

## Global Constraints

- Run all commands from `backend/`. The venv is `backend/venv` — invoke pytest as `./venv/Scripts/python.exe -m pytest` (Windows/Git-Bash).
- `doc_id` is **caller-supplied free text**, never a UUID. Its column is `TEXT`.
- `rag_documents` is a **plain table**. Never call `create_hypertable` on it — a hypertable cannot carry `UNIQUE (organization_id, doc_id)`.
- Every migration must be **idempotent and re-appliable**, and must reconcile a table that `init_db()` may already have created from ORM metadata.
- All new tables get `ENABLE` + `FORCE ROW LEVEL SECURITY` and a `tenant_isolation` policy on `app.current_org_id`.
- Because RLS is FORCED, any worker/service query must first run `SELECT set_config('app.current_org_id', :org, true)` on its session.
- `app/services/rag_index_queue.py` is **Postgres-only** by design (`ON CONFLICT`, `SKIP LOCKED`). Do not add a SQLite fallback.
- Status vocabulary is exactly: `queued`, `indexing`, `indexed`, `skipped`, `failed`.
- Kind vocabulary is exactly: `pdf`, `docx`, `markdown`, `csv`, `image`, `text`, `unsupported`.
- Compose services `qdrant`, `seaweedfs`, `rag-inference` sit behind `profiles: ["rag"]`. Anything depending on them must declare the same profile.
- Commit after every task. Branch is `feature/RAG-Compliance-Doc-Pipeline`; do not commit to `main`.

---

### Task 1: `rag_documents` table — migration + ORM model

**Files:**
- Create: `database/migrations/043_rag_documents.sql`
- Modify: `backend/app/db/models.py` (append a new model; imports at line 6 already include everything needed)
- Test: `backend/tests/test_rag_documents_migration.py`

**Interfaces:**
- Consumes: nothing.
- Produces: table `rag_documents`; ORM class `RagDocument` importable from `app.db.models`, with `__tablename__ = "rag_documents"` and columns `id, organization_id, doc_id, uploaded_by, filename, s3_key, kind, status, attempts, num_blocks, num_chunks, reason, error, created_at, updated_at, started_at, completed_at`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_rag_documents_migration.py`. This mirrors `test_compliance_report_migration.py` — read that file first to match its fixture usage.

```python
"""Migration 043 tests for rag_documents table and RLS."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

MIGRATION_PATH = (
    Path(__file__).resolve().parents[2]
    / "database"
    / "migrations"
    / "043_rag_documents.sql"
)


def _tenant_conn(tenant_async_url: str):
    import psycopg2
    from urllib.parse import urlsplit

    parts = urlsplit(tenant_async_url.replace("postgresql+asyncpg", "postgresql"))
    return psycopg2.connect(
        host=parts.hostname,
        port=parts.port,
        user=parts.username,
        password=parts.password,
        dbname=parts.path.lstrip("/"),
    )


def test_migration_fresh_schema(admin_sync_url):
    import psycopg2

    schema = f"migration_043_{uuid4().hex}"
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}";')
            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute(
                """
                CREATE TABLE organizations (id UUID PRIMARY KEY);
                CREATE TABLE users (id UUID PRIMARY KEY);
                """
            )
            cur.execute(MIGRATION_PATH.read_text())
            cur.execute(
                """
                SELECT column_name, data_type
                FROM information_schema.columns
                WHERE table_schema = %s AND table_name = 'rag_documents';
                """,
                (schema,),
            )
            columns = {row[0]: row[1] for row in cur.fetchall()}
            assert columns["doc_id"] == "text", "doc_id must be TEXT, not uuid"
            for name in (
                "organization_id", "uploaded_by", "filename", "s3_key", "kind",
                "status", "attempts", "num_blocks", "num_chunks", "reason",
                "error", "started_at", "completed_at",
            ):
                assert name in columns


def test_migration_is_reappliable_over_orm_created_table(admin_sync_url):
    """Applying 043 twice, on a schema init_db() already built, is safe."""
    import psycopg2
    import sqlparse
    from sqlalchemy import create_engine

    from app.db.models import Base

    sync_engine = create_engine(admin_sync_url)
    Base.metadata.create_all(sync_engine)
    sync_engine.dispose()

    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            sql = MIGRATION_PATH.read_text()
            for _ in range(2):  # re-appliable
                for raw in sqlparse.split(sql):
                    stmt = sqlparse.format(raw, strip_comments=True).strip()
                    if stmt:
                        cur.execute(stmt)
            cur.execute(
                "SELECT relrowsecurity, relforcerowsecurity "
                "FROM pg_class WHERE relname = 'rag_documents';"
            )
            rls, force = cur.fetchone()
            assert rls is True
            assert force is True

            cur.execute(
                """
                SELECT conname FROM pg_constraint
                WHERE conrelid = 'rag_documents'::regclass AND contype = 'c';
                """
            )
            assert {r[0] for r in cur.fetchall()} == {
                "ck_rag_documents_status",
                "ck_rag_documents_kind",
            }

            cur.execute(
                """
                SELECT conname, confdeltype FROM pg_constraint
                WHERE conrelid = 'rag_documents'::regclass AND contype = 'f';
                """
            )
            fks = dict(cur.fetchall())
            assert fks["fk_rag_documents_organization"] == "c"   # CASCADE
            assert fks["fk_rag_documents_uploaded_by"] == "n"    # SET NULL
    finally:
        conn.close()


def test_constraints_and_indexes(admin_sync_url):
    import psycopg2

    schema = f"migration_043_idx_{uuid4().hex}"
    org_id = uuid4()
    conn = psycopg2.connect(admin_sync_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            cur.execute(f'CREATE SCHEMA "{schema}";')
            cur.execute(f'SET search_path TO "{schema}";')
            cur.execute("CREATE TABLE organizations (id UUID PRIMARY KEY);")
            cur.execute("CREATE TABLE users (id UUID PRIMARY KEY);")
            cur.execute(MIGRATION_PATH.read_text())
            cur.execute(
                "INSERT INTO organizations (id) VALUES (%s);", (str(org_id),)
            )
            cur.execute(
                """
                INSERT INTO rag_documents
                    (organization_id, doc_id, filename, s3_key, kind)
                VALUES (%s, 'doc-1', 'a.txt', 'k/doc-1/a.txt', 'text');
                """,
                (str(org_id),),
            )
            # duplicate (org, doc_id) is rejected
            with pytest.raises(Exception):
                cur.execute(
                    """
                    INSERT INTO rag_documents
                        (organization_id, doc_id, filename, s3_key, kind)
                    VALUES (%s, 'doc-1', 'b.txt', 'k/doc-1/b.txt', 'text');
                    """,
                    (str(org_id),),
                )
            # bogus status is rejected
            with pytest.raises(Exception):
                cur.execute(
                    """
                    INSERT INTO rag_documents
                        (organization_id, doc_id, filename, s3_key, kind, status)
                    VALUES (%s, 'doc-2', 'c.txt', 'k/doc-2/c.txt', 'text', 'bogus');
                    """,
                    (str(org_id),),
                )
            cur.execute(
                "SELECT indexname FROM pg_indexes "
                "WHERE schemaname = %s AND tablename = 'rag_documents';",
                (schema,),
            )
            indexes = {row[0] for row in cur.fetchall()}
            assert "idx_rag_documents_org_created" in indexes
            assert "idx_rag_documents_claimable" in indexes
            assert "idx_rag_documents_stale" in indexes
    finally:
        conn.close()


def test_rls_blocks_no_context_and_cross_tenant(
    admin_sync_url, tenant_async_url, seeded_orgs
):
    import psycopg2

    org_a = seeded_orgs["org_a_id"]
    org_b = seeded_orgs["org_b_id"]

    admin = psycopg2.connect(admin_sync_url)
    admin.autocommit = True
    try:
        with admin.cursor() as cur:
            cur.execute(
                """
                INSERT INTO rag_documents
                    (organization_id, doc_id, filename, s3_key, kind)
                VALUES (%s, 'b-doc', 'b.txt', 'k/b-doc/b.txt', 'text');
                """,
                (str(org_b),),
            )
    finally:
        admin.close()

    conn = _tenant_conn(tenant_async_url)
    conn.autocommit = True
    try:
        with conn.cursor() as cur:
            # no tenant context -> zero rows
            cur.execute("SELECT count(*) FROM rag_documents;")
            assert cur.fetchone()[0] == 0

            # org A context -> cannot read, update, or delete org B's row
            cur.execute(
                "SELECT set_config('app.current_org_id', %s, false);", (str(org_a),)
            )
            cur.execute(
                "SELECT count(*) FROM rag_documents WHERE doc_id = 'b-doc';"
            )
            assert cur.fetchone()[0] == 0
            cur.execute(
                "UPDATE rag_documents SET status = 'failed' WHERE doc_id = 'b-doc';"
            )
            assert cur.rowcount == 0
            cur.execute("DELETE FROM rag_documents WHERE doc_id = 'b-doc';")
            assert cur.rowcount == 0
    finally:
        conn.close()


def test_orm_contract_matches_migration():
    from sqlalchemy import CheckConstraint, UniqueConstraint

    from app.db.models import RagDocument

    table = RagDocument.__table__
    checks = {
        c.name for c in table.constraints if isinstance(c, CheckConstraint)
    }
    assert checks == {"ck_rag_documents_status", "ck_rag_documents_kind"}
    uniques = {
        c.name for c in table.constraints if isinstance(c, UniqueConstraint)
    }
    assert "uq_rag_documents_org_doc" in uniques
    assert {fk.parent.name: fk.ondelete for fk in table.foreign_keys} == {
        "organization_id": "CASCADE",
        "uploaded_by": "SET NULL",
    }
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_documents_migration.py -v`
Expected: FAIL — `test_orm_contract_matches_migration` with `ImportError: cannot import name 'RagDocument'`, and the others with a missing-file error for `043_rag_documents.sql`.

- [ ] **Step 3: Write the migration**

Create `database/migrations/043_rag_documents.sql`:

```sql
-- =============================================================================
-- Migration 043: RAG document registry (async ingestion status + work queue)
-- =============================================================================
-- One row per (organization_id, doc_id). Doubles as the indexing work queue:
-- the worker claims status='queued' rows with FOR UPDATE SKIP LOCKED.
-- Deliberately a PLAIN table, not a hypertable — TimescaleDB requires every
-- UNIQUE constraint on a hypertable to include the partitioning column, which
-- would break the one-row-per-document invariant this design depends on.

BEGIN;

CREATE TABLE IF NOT EXISTS rag_documents (
    id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    organization_id UUID NOT NULL,
    doc_id TEXT NOT NULL,
    uploaded_by UUID,
    filename VARCHAR(255) NOT NULL,
    s3_key TEXT NOT NULL,
    kind VARCHAR(20) NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'queued',
    attempts INTEGER NOT NULL DEFAULT 0,
    num_blocks INTEGER NOT NULL DEFAULT 0,
    num_chunks INTEGER NOT NULL DEFAULT 0,
    reason TEXT,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    started_at TIMESTAMPTZ,
    completed_at TIMESTAMPTZ,
    CONSTRAINT ck_rag_documents_status
        CHECK (status IN ('queued', 'indexing', 'indexed', 'skipped', 'failed')),
    CONSTRAINT ck_rag_documents_kind
        CHECK (kind IN ('pdf', 'docx', 'markdown', 'csv', 'image', 'text', 'unsupported')),
    CONSTRAINT uq_rag_documents_org_doc UNIQUE (organization_id, doc_id),
    CONSTRAINT fk_rag_documents_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    CONSTRAINT fk_rag_documents_uploaded_by
        FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL
);

-- init_db() may have created this table from ORM metadata before migrations
-- run. Reconcile defaults, constraints, and FK actions so both bootstrap paths
-- produce the same schema.
ALTER TABLE rag_documents
    ALTER COLUMN status SET DEFAULT 'queued',
    ALTER COLUMN attempts SET DEFAULT 0,
    ALTER COLUMN num_blocks SET DEFAULT 0,
    ALTER COLUMN num_chunks SET DEFAULT 0,
    ALTER COLUMN created_at SET DEFAULT NOW(),
    ALTER COLUMN updated_at SET DEFAULT NOW();

ALTER TABLE rag_documents
    DROP CONSTRAINT IF EXISTS ck_rag_documents_status,
    DROP CONSTRAINT IF EXISTS ck_rag_documents_kind;

ALTER TABLE rag_documents
    ADD CONSTRAINT ck_rag_documents_status
        CHECK (status IN ('queued', 'indexing', 'indexed', 'skipped', 'failed')),
    ADD CONSTRAINT ck_rag_documents_kind
        CHECK (kind IN ('pdf', 'docx', 'markdown', 'csv', 'image', 'text', 'unsupported'));

DO $$
DECLARE
    fk_name TEXT;
BEGIN
    FOR fk_name IN
        SELECT constraint_name
        FROM information_schema.key_column_usage
        WHERE table_schema = current_schema()
          AND table_name = 'rag_documents'
          AND column_name IN ('organization_id', 'uploaded_by')
          AND position_in_unique_constraint IS NOT NULL
    LOOP
        EXECUTE format('ALTER TABLE rag_documents DROP CONSTRAINT %I', fk_name);
    END LOOP;
END
$$;

ALTER TABLE rag_documents
    ADD CONSTRAINT fk_rag_documents_organization
        FOREIGN KEY (organization_id) REFERENCES organizations(id) ON DELETE CASCADE,
    ADD CONSTRAINT fk_rag_documents_uploaded_by
        FOREIGN KEY (uploaded_by) REFERENCES users(id) ON DELETE SET NULL;

-- The unique constraint may be absent on an ORM-created table.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'uq_rag_documents_org_doc'
          AND conrelid = 'rag_documents'::regclass
    ) THEN
        ALTER TABLE rag_documents
            ADD CONSTRAINT uq_rag_documents_org_doc
            UNIQUE (organization_id, doc_id);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_rag_documents_org_created
    ON rag_documents(organization_id, created_at DESC);

-- Partial indexes sized to the queue rather than the table: the claimable and
-- in-flight states are a small minority of rows.
CREATE INDEX IF NOT EXISTS idx_rag_documents_claimable
    ON rag_documents(organization_id, created_at) WHERE status = 'queued';

CREATE INDEX IF NOT EXISTS idx_rag_documents_stale
    ON rag_documents(updated_at) WHERE status = 'indexing';

ALTER TABLE rag_documents ENABLE ROW LEVEL SECURITY;
ALTER TABLE rag_documents FORCE ROW LEVEL SECURITY;

DROP POLICY IF EXISTS tenant_isolation ON rag_documents;
CREATE POLICY tenant_isolation ON rag_documents
    FOR ALL
    USING (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    )
    WITH CHECK (
        organization_id =
        NULLIF(current_setting('app.current_org_id', true), '')::uuid
    );

COMMIT;
```

- [ ] **Step 4: Add the ORM model**

Append to `backend/app/db/models.py` (after `ComplianceReportJob`, before `AgentRelease`). All names used are already imported at line 6.

```python
class RagDocument(Base):
    """Canonical per-document RAG record; doubles as the indexing work queue.

    One row per (organization_id, doc_id). ``doc_id`` is caller-supplied free
    text, not a UUID. ``status`` drives the worker: 'queued' rows are claimed
    with FOR UPDATE SKIP LOCKED, and terminal states are 'indexed' (vectors
    live), 'skipped' (nothing indexable — see ``reason``), or 'failed' (infra
    fault after retries — see ``error``).
    """
    __tablename__ = "rag_documents"
    __table_args__ = (
        CheckConstraint(
            "status IN ('queued', 'indexing', 'indexed', 'skipped', 'failed')",
            name="ck_rag_documents_status",
        ),
        CheckConstraint(
            "kind IN ('pdf', 'docx', 'markdown', 'csv', 'image', 'text', "
            "'unsupported')",
            name="ck_rag_documents_kind",
        ),
        UniqueConstraint(
            "organization_id", "doc_id", name="uq_rag_documents_org_doc"
        ),
    )

    id = UUIDColumn()
    organization_id = Column(
        UUIDString(),
        ForeignKey("organizations.id", ondelete="CASCADE"),
        nullable=False,
    )
    doc_id = Column(Text, nullable=False)
    uploaded_by = Column(
        UUIDString(),
        ForeignKey("users.id", ondelete="SET NULL"),
        nullable=True,
    )
    filename = Column(String(255), nullable=False)
    s3_key = Column(Text, nullable=False)
    kind = Column(String(20), nullable=False)
    status = Column(
        String(20), nullable=False, default="queued", server_default="queued"
    )
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    num_blocks = Column(Integer, nullable=False, default=0, server_default="0")
    num_chunks = Column(Integer, nullable=False, default=0, server_default="0")
    reason = Column(Text)
    error = Column(Text)
    created_at = Column(
        DateTime(timezone=True), default=datetime.utcnow, server_default=func.now()
    )
    updated_at = Column(
        DateTime(timezone=True),
        default=datetime.utcnow,
        onupdate=datetime.utcnow,
        server_default=func.now(),
    )
    started_at = Column(DateTime(timezone=True))
    completed_at = Column(DateTime(timezone=True))
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_documents_migration.py -v`
Expected: all 5 PASS. (Requires Docker for testcontainers; if unavailable the module skips — in that case run at minimum `./venv/Scripts/python.exe -m pytest tests/test_rag_documents_migration.py::test_orm_contract_matches_migration -v`, which needs no container.)

- [ ] **Step 6: Verify no regression in the schema contract suite**

Run: `./venv/Scripts/python.exe -m pytest tests/test_schema_migration_contract.py -v`
Expected: all PASS (unchanged).

- [ ] **Step 7: Commit**

```bash
git add database/migrations/043_rag_documents.sql backend/app/db/models.py backend/tests/test_rag_documents_migration.py
git commit -m "feat(rag): add rag_documents table for async ingestion status"
```

---

### Task 2: `doc_id` validation (tenant-isolation hardening)

**Files:**
- Modify: `backend/app/services/document_store.py:40-46` (`build_document_key`)
- Test: `backend/tests/test_document_key_validation.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `validate_doc_id(doc_id: str) -> str` and `class InvalidDocumentId(ValueError)`, both importable from `app.services.document_store`. `build_document_key` now raises `InvalidDocumentId` for unsafe input.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_document_key_validation.py`:

```python
"""doc_id must not escape the tenant prefix or break the 3-segment key layout.

The object key is ``{org_id}/{doc_id}/{filename}`` and doc_id is caller-supplied
free text, so an unvalidated value can write outside the caller's org prefix.
"""

import pytest

from app.services.document_store import (
    InvalidDocumentId,
    build_document_key,
    validate_doc_id,
)


@pytest.mark.parametrize(
    "doc_id",
    [
        "simple",
        "eval-pdf-abc123",
        "with.dots_and-dashes",
        "0123456789abcdef0123456789abcdef",  # server-generated uuid4().hex
        "a" * 128,
    ],
)
def test_accepts_safe_doc_ids(doc_id):
    assert validate_doc_id(doc_id) == doc_id


@pytest.mark.parametrize(
    "doc_id",
    [
        "../victim-org",
        "a/b",
        "..",
        "",
        "a" * 129,
        "has space",
        "semi;colon",
        "null\x00byte",
    ],
)
def test_rejects_unsafe_doc_ids(doc_id):
    with pytest.raises(InvalidDocumentId):
        validate_doc_id(doc_id)


def test_build_document_key_rejects_traversal():
    with pytest.raises(InvalidDocumentId):
        build_document_key("org-1", "../org-2", "secret.pdf")


def test_build_document_key_still_builds_three_segments():
    key = build_document_key("org-1", "doc-9", "report.pdf")
    assert key == "org-1/doc-9/report.pdf"
    assert len(key.split("/")) == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_document_key_validation.py -v`
Expected: FAIL with `ImportError: cannot import name 'InvalidDocumentId'`.

- [ ] **Step 3: Implement the validator**

In `backend/app/services/document_store.py`, add `import re` to the stdlib imports at the top, then replace `build_document_key` (lines 40-46) with:

```python
_DOC_ID_RE = re.compile(r"^[A-Za-z0-9._-]{1,128}$")


class InvalidDocumentId(ValueError):
    """A caller-supplied doc_id that cannot safely be used in an object key."""


def validate_doc_id(doc_id: str) -> str:
    """Reject a doc_id that would escape the tenant prefix or break the key.

    Object keys are ``{org_id}/{doc_id}/{filename}``. Because ``doc_id`` comes
    straight from the client, an unvalidated ``../other-org`` would write
    outside the caller's own prefix, and any ``/`` silently breaks the
    three-segment layout that key parsers rely on.
    """
    if not isinstance(doc_id, str) or not _DOC_ID_RE.match(doc_id):
        raise InvalidDocumentId(
            "doc_id must be 1-128 characters of letters, digits, "
            "'.', '_' or '-'."
        )
    return doc_id


def build_document_key(org_id: str, doc_id: str, filename: str) -> str:
    """Build a stable object key for a source document.

    Structure: ``{org_id}/{doc_id}/{filename}``. The ``doc_id`` keeps keys
    unique and stable even when two uploads share a filename. ``doc_id`` is
    validated first — see ``validate_doc_id``.
    """
    validate_doc_id(doc_id)
    return f"{org_id}/{doc_id}/{filename}"
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_document_key_validation.py -v`
Expected: 14 PASS.

- [ ] **Step 5: Verify the existing RAG storage test still passes**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_documents_storage_unavailable.py -v`
Expected: 2 PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/app/services/document_store.py backend/tests/test_document_key_validation.py
git commit -m "fix(rag): validate caller-supplied doc_id before building object keys"
```

---

### Task 3: Settings + `rag_index_queue` service

**Files:**
- Modify: `backend/app/core/config.py` (add 4 settings next to the existing `RAG_*` block around line 238)
- Create: `backend/app/services/rag_index_queue.py`
- Test: `backend/tests/test_rag_index_queue.py`

**Interfaces:**
- Consumes: `RagDocument` from Task 1.
- Produces, all importable from `app.services.rag_index_queue`:
  - `@dataclass(frozen=True) class ClaimedDocument: org_id: str; doc_id: str; s3_key: str; filename: str; kind: str; attempts: int`
  - `async def upsert_queued(*, org_id: str, doc_id: str, uploaded_by: str | None, filename: str, s3_key: str, kind: str) -> None`
  - `async def claim_next(org_id: str) -> ClaimedDocument | None`
  - `async def finalize(*, org_id: str, doc_id: str, attempts: int, status: str, num_blocks: int = 0, num_chunks: int = 0, reason: str | None = None, error: str | None = None) -> bool`
  - `async def requeue_or_fail(*, org_id: str, doc_id: str, attempts: int, error: str) -> str` (returns the new status)
  - `async def recover_stale() -> int`
  - `async def get_status(org_id: str, doc_id: str) -> dict | None`
  - `async def list_for_org(org_id: str) -> list[dict]`
  - `async def delete_row(org_id: str, doc_id: str) -> bool`
  - `async def list_org_ids() -> list[str]`

- [ ] **Step 1: Add the settings**

In `backend/app/core/config.py`, immediately after the `RAG_MAX_CHUNKS_PER_DOC` line (~line 239):

```python
    # Async indexing worker (app/workers/rag_indexing.py). The worker claims
    # queued rag_documents rows with FOR UPDATE SKIP LOCKED, so it is safe at
    # any replica count — unlike the singleton OTA dispatcher.
    RAG_INDEX_WORKER_ENABLED: bool = True
    RAG_INDEX_POLL_INTERVAL_SECONDS: int = 5
    RAG_INDEX_MAX_ATTEMPTS: int = 3
    # Must exceed worst-case indexing time: compose runs RAG_INFERENCE_TIMEOUT
    # at 180s PER EMBED BATCH, and a large document has many batches.
    RAG_INDEX_STALE_INDEXING_SECONDS: int = 900
```

- [ ] **Step 2: Write the failing test**

Create `backend/tests/test_rag_index_queue.py`:

```python
"""rag_index_queue: claim/finalize semantics under concurrency and crashes."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

pytest.importorskip("testcontainers")

from sqlalchemy import text  # noqa: E402

from app.core.config import settings  # noqa: E402
from app.db.database import AsyncSessionLocal  # noqa: E402
from app.services import rag_index_queue as q  # noqa: E402


async def _queue_doc(org_id, doc_id="doc-1", kind="text"):
    await q.upsert_queued(
        org_id=str(org_id),
        doc_id=doc_id,
        uploaded_by=None,
        filename=f"{doc_id}.txt",
        s3_key=f"{org_id}/{doc_id}/{doc_id}.txt",
        kind=kind,
    )


async def test_claim_returns_queued_row_and_marks_it_indexing(app, seeded_orgs):
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)

    claimed = await q.claim_next(str(org_id))

    assert claimed is not None
    assert claimed.doc_id == "doc-1"
    assert claimed.attempts == 1
    status = await q.get_status(str(org_id), "doc-1")
    assert status["status"] == "indexing"


async def test_second_claim_skips_the_locked_row(app, seeded_orgs):
    """A row already claimed is never handed to a second worker."""
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)

    first = await q.claim_next(str(org_id))
    second = await q.claim_next(str(org_id))

    assert first is not None
    assert second is None, "a claimed row must not be claimable again"


async def test_finalize_writes_terminal_state(app, seeded_orgs):
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)
    claimed = await q.claim_next(str(org_id))

    ok = await q.finalize(
        org_id=str(org_id),
        doc_id=claimed.doc_id,
        attempts=claimed.attempts,
        status="indexed",
        num_blocks=3,
        num_chunks=7,
    )

    assert ok is True
    status = await q.get_status(str(org_id), "doc-1")
    assert status["status"] == "indexed"
    assert status["num_chunks"] == 7
    assert status["completed_at"] is not None


async def test_finalize_is_discarded_when_row_was_requeued_midflight(
    app, seeded_orgs
):
    """A re-ingest during indexing must not be overwritten by the stale pass."""
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)
    claimed = await q.claim_next(str(org_id))

    # caller re-ingests the same doc_id while the first pass is still running
    await _queue_doc(org_id)

    ok = await q.finalize(
        org_id=str(org_id),
        doc_id=claimed.doc_id,
        attempts=claimed.attempts,
        status="indexed",
        num_chunks=7,
    )

    assert ok is False, "stale finalize must not win"
    status = await q.get_status(str(org_id), "doc-1")
    assert status["status"] == "queued"


async def test_requeue_or_fail_retries_then_fails(app, seeded_orgs):
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)

    for _ in range(settings.RAG_INDEX_MAX_ATTEMPTS - 1):
        claimed = await q.claim_next(str(org_id))
        outcome = await q.requeue_or_fail(
            org_id=str(org_id),
            doc_id=claimed.doc_id,
            attempts=claimed.attempts,
            error="qdrant unreachable",
        )
        assert outcome == "queued"

    claimed = await q.claim_next(str(org_id))
    outcome = await q.requeue_or_fail(
        org_id=str(org_id),
        doc_id=claimed.doc_id,
        attempts=claimed.attempts,
        error="qdrant unreachable",
    )

    assert outcome == "failed"
    status = await q.get_status(str(org_id), "doc-1")
    assert status["status"] == "failed"
    assert "qdrant" in status["error"]


async def test_recover_stale_requeues_abandoned_indexing_rows(app, seeded_orgs):
    """A worker that died mid-index leaves an 'indexing' row; it must recover."""
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id)
    await q.claim_next(str(org_id))

    stale_at = datetime.now(timezone.utc) - timedelta(
        seconds=settings.RAG_INDEX_STALE_INDEXING_SECONDS + 60
    )
    async with AsyncSessionLocal() as session:
        await session.execute(
            text("SELECT set_config('app.current_org_id', :org, true)"),
            {"org": str(org_id)},
        )
        await session.execute(
            text(
                "UPDATE rag_documents SET updated_at = :ts "
                "WHERE doc_id = 'doc-1'"
            ),
            {"ts": stale_at},
        )
        await session.commit()

    recovered = await q.recover_stale()

    assert recovered == 1
    status = await q.get_status(str(org_id), "doc-1")
    assert status["status"] == "queued"


async def test_get_status_is_org_scoped(app, seeded_orgs):
    org_a = seeded_orgs["org_a_id"]
    org_b = seeded_orgs["org_b_id"]
    await _queue_doc(org_a, doc_id="a-doc")

    assert await q.get_status(str(org_a), "a-doc") is not None
    assert await q.get_status(str(org_b), "a-doc") is None


async def test_delete_row_removes_only_the_targeted_document(app, seeded_orgs):
    org_id = seeded_orgs["org_a_id"]
    await _queue_doc(org_id, doc_id="keep")
    await _queue_doc(org_id, doc_id="drop")

    assert await q.delete_row(str(org_id), "drop") is True
    assert await q.get_status(str(org_id), "drop") is None
    assert await q.get_status(str(org_id), "keep") is not None
```

- [ ] **Step 3: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_index_queue.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.services.rag_index_queue'`.

- [ ] **Step 4: Implement the queue service**

Create `backend/app/services/rag_index_queue.py`:

```python
"""Row lifecycle for the ``rag_documents`` registry / indexing queue.

Separate from ``rag_ingestion`` on purpose: that module owns the pipeline and
has no database awareness at all (it talks only to S3, rag-inference, and
Qdrant). This module owns persistence, tenant scoping, and claim/finalize
concurrency — the same split as ``compliance_report_queue`` beside
``compliance_report_service``.

**Postgres only.** Uses ``ON CONFLICT`` and ``FOR UPDATE SKIP LOCKED``; there
is deliberately no SQLite fallback, matching the RLS the table carries.

Every query sets ``app.current_org_id`` first: ``rag_documents`` has FORCE ROW
LEVEL SECURITY, so even the worker sees zero rows without a tenant context.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import structlog
from sqlalchemy import delete, select, text, update
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.core.config import settings
from app.db.database import AsyncSessionLocal
from app.db.models import Organization, RagDocument

logger = structlog.get_logger()

# Bounded work per org per pass, so one busy tenant cannot starve the others.
# Mirrors the range(100) cap in compliance_report_queue._publish_queued_for_org.
MAX_CLAIMS_PER_ORG_PER_PASS = 100

TERMINAL_STATUSES = ("indexed", "skipped", "failed")


@dataclass(frozen=True)
class ClaimedDocument:
    """A row this worker has exclusively claimed for one indexing pass."""

    org_id: str
    doc_id: str
    s3_key: str
    filename: str
    kind: str
    attempts: int


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def _set_org(session, org_id: Any) -> None:
    await session.execute(
        text("SELECT set_config('app.current_org_id', :org, true)"),
        {"org": str(org_id)},
    )


def _to_dict(row: RagDocument) -> Dict[str, Any]:
    return {
        "doc_id": row.doc_id,
        "status": row.status,
        "kind": row.kind,
        "filename": row.filename,
        "s3_key": row.s3_key,
        "num_blocks": row.num_blocks,
        "num_chunks": row.num_chunks,
        "reason": row.reason,
        "error": row.error,
        "attempts": row.attempts,
        "created_at": row.created_at,
        "started_at": row.started_at,
        "completed_at": row.completed_at,
    }


async def upsert_queued(
    *,
    org_id: str,
    doc_id: str,
    uploaded_by: Optional[str],
    filename: str,
    s3_key: str,
    kind: str,
) -> None:
    """Record a freshly stored blob as awaiting indexing.

    Re-ingesting an existing doc_id resets the SAME row back to 'queued' and
    clears prior outcome fields, so there is exactly one row per document and
    the status endpoint never has to disambiguate attempts.
    """
    now = _now()
    fresh = {
        "uploaded_by": uploaded_by,
        "filename": filename,
        "s3_key": s3_key,
        "kind": kind,
        "status": "queued",
        "attempts": 0,
        "num_blocks": 0,
        "num_chunks": 0,
        "reason": None,
        "error": None,
        "updated_at": now,
        "started_at": None,
        "completed_at": None,
    }
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        await session.execute(
            pg_insert(RagDocument.__table__)
            .values(
                organization_id=str(org_id),
                doc_id=doc_id,
                created_at=now,
                **fresh,
            )
            .on_conflict_do_update(
                constraint="uq_rag_documents_org_doc",
                set_=fresh,
            )
        )
        await session.commit()


async def claim_next(org_id: str) -> Optional[ClaimedDocument]:
    """Claim the oldest queued document for this org, or return None.

    SKIP LOCKED is what makes this safe to run from several worker replicas at
    once: a row another transaction already holds is stepped over rather than
    blocking.
    """
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        row = (
            await session.execute(
                select(RagDocument)
                .where(
                    RagDocument.organization_id == str(org_id),
                    RagDocument.status == "queued",
                )
                .order_by(RagDocument.created_at)
                .limit(1)
                .with_for_update(skip_locked=True)
            )
        ).scalar_one_or_none()
        if row is None:
            return None

        row.status = "indexing"
        row.attempts += 1
        row.started_at = _now()
        row.updated_at = _now()
        claimed = ClaimedDocument(
            org_id=str(org_id),
            doc_id=row.doc_id,
            s3_key=row.s3_key,
            filename=row.filename,
            kind=row.kind,
            attempts=row.attempts,
        )
        await session.commit()
        logger.info(
            "rag_index_queue.claimed",
            doc_id=claimed.doc_id,
            attempts=claimed.attempts,
        )
        return claimed


async def finalize(
    *,
    org_id: str,
    doc_id: str,
    attempts: int,
    status: str,
    num_blocks: int = 0,
    num_chunks: int = 0,
    reason: Optional[str] = None,
    error: Optional[str] = None,
) -> bool:
    """Write a terminal status, but only if our claim is still the current one.

    The ``status='indexing' AND attempts=:attempts`` filter is what makes a
    re-ingest safe: if the caller re-uploaded this doc_id mid-pass, the row is
    already back to 'queued' with attempts reset, this UPDATE matches nothing,
    and the stale result is discarded instead of overwriting the new work.
    Returns True if the write landed.
    """
    if status not in TERMINAL_STATUSES:
        raise ValueError(f"not a terminal status: {status}")
    now = _now()
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        result = await session.execute(
            update(RagDocument)
            .where(
                RagDocument.organization_id == str(org_id),
                RagDocument.doc_id == doc_id,
                RagDocument.status == "indexing",
                RagDocument.attempts == attempts,
            )
            .values(
                status=status,
                num_blocks=num_blocks,
                num_chunks=num_chunks,
                reason=reason,
                error=error,
                completed_at=now,
                updated_at=now,
            )
        )
        await session.commit()
    landed = result.rowcount > 0
    if not landed:
        logger.info("rag_index_queue.finalize_discarded", doc_id=doc_id)
    return landed


async def requeue_or_fail(
    *, org_id: str, doc_id: str, attempts: int, error: str
) -> str:
    """Return a failed pass to 'queued', or to 'failed' once attempts run out."""
    next_status = (
        "queued" if attempts < settings.RAG_INDEX_MAX_ATTEMPTS else "failed"
    )
    now = _now()
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        await session.execute(
            update(RagDocument)
            .where(
                RagDocument.organization_id == str(org_id),
                RagDocument.doc_id == doc_id,
                RagDocument.status == "indexing",
                RagDocument.attempts == attempts,
            )
            .values(
                status=next_status,
                error=error[:2000],
                completed_at=now if next_status == "failed" else None,
                updated_at=now,
            )
        )
        await session.commit()
    logger.warning(
        "rag_index_queue.pass_failed",
        doc_id=doc_id,
        attempts=attempts,
        next_status=next_status,
    )
    return next_status


async def recover_stale() -> int:
    """Re-queue rows abandoned in 'indexing' by a crashed or killed worker."""
    cutoff = _now() - timedelta(
        seconds=settings.RAG_INDEX_STALE_INDEXING_SECONDS
    )
    recovered = 0
    for org_id in await list_org_ids():
        async with AsyncSessionLocal() as session:
            await _set_org(session, org_id)
            rows = (
                await session.execute(
                    select(RagDocument).where(
                        RagDocument.organization_id == str(org_id),
                        RagDocument.status == "indexing",
                        RagDocument.updated_at <= cutoff,
                    )
                )
            ).scalars().all()
            for row in rows:
                exhausted = row.attempts >= settings.RAG_INDEX_MAX_ATTEMPTS
                row.status = "failed" if exhausted else "queued"
                if exhausted:
                    row.error = "Indexing abandoned; worker did not finish."
                    row.completed_at = _now()
                row.updated_at = _now()
                recovered += 1
            if rows:
                await session.commit()
    if recovered:
        logger.warning("rag_index_queue.recovered_stale", count=recovered)
    return recovered


async def get_status(org_id: str, doc_id: str) -> Optional[Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        row = (
            await session.execute(
                select(RagDocument).where(
                    RagDocument.organization_id == str(org_id),
                    RagDocument.doc_id == doc_id,
                )
            )
        ).scalar_one_or_none()
        return _to_dict(row) if row else None


async def list_for_org(org_id: str) -> List[Dict[str, Any]]:
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        rows = (
            await session.execute(
                select(RagDocument)
                .where(RagDocument.organization_id == str(org_id))
                .order_by(RagDocument.created_at.desc())
            )
        ).scalars().all()
        return [_to_dict(row) for row in rows]


async def delete_row(org_id: str, doc_id: str) -> bool:
    async with AsyncSessionLocal() as session:
        await _set_org(session, org_id)
        result = await session.execute(
            delete(RagDocument).where(
                RagDocument.organization_id == str(org_id),
                RagDocument.doc_id == doc_id,
            )
        )
        await session.commit()
        return result.rowcount > 0


async def list_org_ids() -> List[str]:
    """All tenant ids, so the worker can poll each with its own RLS context."""
    async with AsyncSessionLocal() as session:
        return [
            str(org_id)
            for org_id in (
                await session.execute(select(Organization.id))
            ).scalars().all()
        ]
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_index_queue.py -v`
Expected: 8 PASS.

If `test_second_claim_skips_the_locked_row` fails because both claims succeed, the two calls are reusing one connection — confirm `AsyncSessionLocal()` opens a distinct session per call and that `claim_next` commits before returning.

- [ ] **Step 6: Commit**

```bash
git add backend/app/core/config.py backend/app/services/rag_index_queue.py backend/tests/test_rag_index_queue.py
git commit -m "feat(rag): add rag_index_queue for document status and claim/finalize"
```

---

### Task 4: Split the ingestion pipeline

**Files:**
- Modify: `backend/app/services/rag_ingestion.py:59-72` (`IngestionResult`), `:364-479` (`ingest_document` → two methods), `:511-528` (`delete_document`)
- Test: `backend/tests/test_rag_ingestion_split.py`

**Interfaces:**
- Consumes: `rag_index_queue.upsert_queued`, `.finalize`, `.delete_row` from Task 3; `validate_doc_id` from Task 2.
- Produces on `IngestionPipeline`:
  - `async def store_document(*, content: bytes, filename: str, org_id: str, doc_id: str | None = None, content_type: str | None = None, uploaded_by: str | None = None) -> IngestionResult`
  - `async def index_document(claimed: ClaimedDocument, *, extra_metadata: dict | None = None) -> IngestionResult`
  - `IngestionResult` gains `status: str = "queued"`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_rag_ingestion_split.py`:

```python
"""The ingest pipeline splits at the blob-durable seam.

store_document must do only the fast work (blob + queued row) and must NOT
parse, chunk, embed, or upsert — that is the whole point of the 202 contract.
"""

from __future__ import annotations

import pytest

from app.services.rag_ingestion import IngestionPipeline
from app.services.rag_index_queue import ClaimedDocument


class _FakeDocs:
    available = True
    raw_bucket = "raw"

    def __init__(self, blob: bytes = b""):
        self.blob = blob
        self.put_calls = []

    async def ensure_bucket(self, bucket):
        return None

    async def put_document(self, *, key, data, content_type, metadata):
        self.put_calls.append(key)
        self.blob = data
        return key

    async def get_document(self, key, bucket=None):
        return self.blob


class _ExplodingInference:
    available = True

    async def embed(self, *args, **kwargs):
        raise AssertionError("store_document must not embed")


class _ExplodingVectors:
    available = True

    async def ensure_collection(self):
        raise AssertionError("store_document must not touch the vector store")

    async def delete_by_doc(self, doc_id):
        raise AssertionError("store_document must not touch the vector store")

    async def upsert_chunks(self, points):
        raise AssertionError("store_document must not touch the vector store")


def _pipeline(docs, inference=None, vectors=None) -> IngestionPipeline:
    pipeline = IngestionPipeline.__new__(IngestionPipeline)
    pipeline.docs = docs
    pipeline.inference = inference or _ExplodingInference()
    pipeline.vectors = vectors or _ExplodingVectors()
    pipeline.batch = 8
    return pipeline


async def test_store_document_stores_blob_and_queues_without_indexing(
    monkeypatch,
):
    docs = _FakeDocs()
    queued = {}

    async def _fake_upsert_queued(**kwargs):
        queued.update(kwargs)

    monkeypatch.setattr(
        "app.services.rag_ingestion.upsert_queued", _fake_upsert_queued
    )

    result = await _pipeline(docs).store_document(
        content=b"hello world",
        filename="a.txt",
        org_id="org-1",
        doc_id="doc-1",
        content_type="text/plain",
    )

    assert result.stored is True
    assert result.indexed is False
    assert result.status == "queued"
    assert result.s3_key == "org-1/doc-1/a.txt"
    assert docs.put_calls == ["org-1/doc-1/a.txt"]
    assert queued["doc_id"] == "doc-1"
    assert queued["kind"] == "text"


async def test_store_document_generates_a_doc_id_when_omitted(monkeypatch):
    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("app.services.rag_ingestion.upsert_queued", _noop)

    result = await _pipeline(_FakeDocs()).store_document(
        content=b"x", filename="a.txt", org_id="org-1"
    )

    assert result.doc_id
    assert result.s3_key == f"org-1/{result.doc_id}/a.txt"


async def test_store_document_rejects_unsafe_doc_id(monkeypatch):
    from app.services.document_store import InvalidDocumentId

    async def _noop(**kwargs):
        return None

    monkeypatch.setattr("app.services.rag_ingestion.upsert_queued", _noop)

    with pytest.raises(InvalidDocumentId):
        await _pipeline(_FakeDocs()).store_document(
            content=b"x", filename="a.txt", org_id="org-1", doc_id="../org-2"
        )


async def test_index_document_reports_skipped_for_unsupported_kind():
    claimed = ClaimedDocument(
        org_id="org-1",
        doc_id="doc-1",
        s3_key="org-1/doc-1/a.bin",
        filename="a.bin",
        kind="unsupported",
        attempts=1,
    )

    result = await _pipeline(_FakeDocs(b"binary")).index_document(claimed)

    assert result.status == "skipped"
    assert result.indexed is False
    assert "Unsupported file type" in result.reason


async def test_index_document_reports_skipped_when_no_text_extracted():
    claimed = ClaimedDocument(
        org_id="org-1",
        doc_id="doc-1",
        s3_key="org-1/doc-1/a.txt",
        filename="a.txt",
        kind="text",
        attempts=1,
    )

    result = await _pipeline(_FakeDocs(b"   ")).index_document(claimed)

    assert result.status == "skipped"
    assert result.num_blocks == 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_ingestion_split.py -v`
Expected: FAIL — `AttributeError: 'IngestionPipeline' object has no attribute 'store_document'`.

- [ ] **Step 3: Add `status` to `IngestionResult` and new imports**

In `backend/app/services/rag_ingestion.py`, change the import on line 39 and add the queue import:

```python
from app.services.document_store import (
    get_document_store,
    build_document_key,
    validate_doc_id,
)
from app.services.rag_index_queue import ClaimedDocument, upsert_queued
```

Then add one field to `IngestionResult` (after `indexed`, line 69):

```python
    status: str = "queued"  # queued | indexing | indexed | skipped | failed
```

- [ ] **Step 4: Replace `ingest_document` with the two-phase methods**

Replace the whole of `async def ingest_document` (lines 364-479) with:

```python
    async def store_document(
        self,
        *,
        content: bytes,
        filename: str,
        org_id: str,
        doc_id: Optional[str] = None,
        content_type: Optional[str] = None,
        uploaded_by: Optional[str] = None,
    ) -> IngestionResult:
        """Persist the blob and queue the document for indexing.

        This is the fast half of ingestion and the only half that runs inside
        the HTTP request: two S3 calls and one row UPSERT. Everything slow
        (parse/chunk/embed/upsert) is left to ``index_document`` on the worker,
        so the request cannot outlive the ingress read timeout.

        Blob first, row second, deliberately: a crash between them orphans a
        blob and the client's retry overwrites the same key, whereas row-first
        would queue a document whose blob does not exist.
        """
        doc_id = validate_doc_id(doc_id) if doc_id else str(uuid.uuid4())
        kind = _detect_kind(filename, content_type)
        s3_key = build_document_key(org_id, doc_id, filename)

        if not self.docs.available:
            raise RuntimeError(
                "Document store unavailable (aioboto3 not installed) - cannot ingest."
            )
        await self.docs.ensure_bucket(self.docs.raw_bucket)
        await self.docs.put_document(
            key=s3_key,
            data=content,
            content_type=content_type or "application/octet-stream",
            metadata={"org_id": org_id, "doc_id": doc_id, "filename": filename},
        )

        await upsert_queued(
            org_id=org_id,
            doc_id=doc_id,
            uploaded_by=uploaded_by,
            filename=filename,
            s3_key=s3_key,
            kind=kind,
        )
        logger.info("rag_ingestion.queued", doc_id=doc_id, kind=kind)

        return IngestionResult(
            doc_id=doc_id,
            org_id=org_id,
            filename=filename,
            s3_key=s3_key,
            kind=kind,
            stored=True,
            indexed=False,
            status="queued",
        )

    async def index_document(
        self,
        claimed: "ClaimedDocument",
        *,
        extra_metadata: Optional[Dict[str, Any]] = None,
    ) -> IngestionResult:
        """Parse, chunk, embed and index an already-stored document.

        Runs on the worker against a row it has claimed. Returns a result whose
        ``status`` is one of 'indexed' or 'skipped'. Infrastructure faults are
        raised, not returned, so the caller can decide to retry.
        """
        org_id, doc_id = claimed.org_id, claimed.doc_id
        result = IngestionResult(
            doc_id=doc_id,
            org_id=org_id,
            filename=claimed.filename,
            s3_key=claimed.s3_key,
            kind=claimed.kind,
            stored=True,
            indexed=False,
            status="skipped",
        )

        if claimed.kind == "unsupported":
            result.reason = (
                f"Unsupported file type for RAG indexing: {claimed.filename}"
            )
            return result

        # Raises on failure: an unreadable blob is an infra fault, so the
        # worker should retry rather than mark the document permanently skipped.
        content = await self.docs.get_document(claimed.s3_key)

        try:
            blocks = _parse_to_blocks(claimed.kind, content, claimed.filename)
        except Exception as exc:  # parsing failed (e.g. optional lib missing)
            logger.warning(
                "rag_ingestion.parse_failed", doc_id=doc_id, error=str(exc)
            )
            result.reason = f"Parse failed: {exc}"
            return result

        result.num_blocks = len(blocks)
        if not blocks:
            result.reason = _empty_reason(claimed.kind)
            return result

        chunks = chunk_blocks(
            blocks,
            target_tokens=settings.RAG_CHUNK_TOKENS,
            overlap_tokens=settings.RAG_CHUNK_OVERLAP_TOKENS,
            chars_per_token=settings.RAG_CHARS_PER_TOKEN,
            min_chars=settings.RAG_MIN_CHUNK_CHARS,
        )
        result.num_chunks = len(chunks)
        if not chunks:
            result.reason = "No chunkable text produced."
            return result

        # Durability guard: never let one document explode the embed/upsert path.
        cap = settings.RAG_MAX_CHUNKS_PER_DOC
        if len(chunks) > cap:
            logger.warning(
                "rag_ingestion.chunk_cap", doc_id=doc_id, produced=len(chunks), cap=cap
            )
            result.reason = (
                f"Chunk cap reached: indexed the first {cap} of {len(chunks)} "
                f"chunks. Split this document into smaller files."
            )
            chunks = chunks[:cap]

        if not self.inference.available or not self.vectors.available:
            raise RuntimeError(
                "Inference or vector store unavailable - cannot index."
            )

        await self.vectors.ensure_collection()
        # Idempotent re-ingest: drop any prior chunks for this document first.
        await self.vectors.delete_by_doc(doc_id)

        written = 0
        for start in range(0, len(chunks), self.batch):
            batch = chunks[start : start + self.batch]
            embeddings = await self.inference.embed(
                [c.text for c in batch], is_query=False
            )
            points = [
                self._to_point(
                    doc_id, org_id, claimed.s3_key, claimed.filename,
                    chunk, emb, extra_metadata,
                )
                for chunk, emb in zip(batch, embeddings)
            ]
            written += await self.vectors.upsert_chunks(points)

        result.indexed = True
        result.status = "indexed"
        result.num_chunks = written
        logger.info(
            "rag_ingestion.indexed",
            doc_id=doc_id,
            kind=claimed.kind,
            blocks=result.num_blocks,
            chunks=written,
        )
        return result
```

Note the deliberate behavior change: an unavailable inference/vector store now **raises** instead of returning `indexed=False`, because on the worker that is a retryable infra fault, not a terminal outcome.

- [ ] **Step 5: Make `delete_document` remove the row**

In `delete_document` (line 511), import and call the row delete. Add to the imports at the top:

```python
from app.services.rag_index_queue import ClaimedDocument, upsert_queued, delete_row
```

Then, in `delete_document`, after the blob-deletion loop and before the `logger.info` call, add:

```python
        # Row last: an interrupted delete must never leave queryable vectors
        # behind, so vectors -> blobs -> row is the only safe order.
        row_deleted = await delete_row(org_id, doc_id)
```

and add `"row_deleted": row_deleted,` to the returned dict.

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_ingestion_split.py -v`
Expected: 5 PASS.

- [ ] **Step 7: Commit**

```bash
git add backend/app/services/rag_ingestion.py backend/tests/test_rag_ingestion_split.py
git commit -m "refactor(rag): split ingestion into store_document and index_document"
```

---

### Task 5: The indexing worker

**Files:**
- Create: `backend/app/workers/rag_indexing.py`
- Test: `backend/tests/test_rag_indexing_worker.py`

**Interfaces:**
- Consumes: everything from Tasks 3 and 4.
- Produces: `async def run(*, stop_event=None, poll_interval=None, pipeline=None, max_passes=None) -> None` and `async def run_once(pipeline=None) -> int` (returns documents processed), both in `app.workers.rag_indexing`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_rag_indexing_worker.py`:

```python
"""One worker pass: claim -> index -> terminal status, including failure paths."""

from __future__ import annotations

import asyncio

import pytest

from app.services.rag_ingestion import IngestionResult
from app.workers import rag_indexing


class _StubPipeline:
    """Stands in for IngestionPipeline; records what it was asked to index."""

    def __init__(self, outcome=None, raises=None):
        self.outcome = outcome
        self.raises = raises
        self.seen = []

    async def index_document(self, claimed, *, extra_metadata=None):
        self.seen.append(claimed.doc_id)
        if self.raises:
            raise self.raises
        return self.outcome or IngestionResult(
            doc_id=claimed.doc_id,
            org_id=claimed.org_id,
            filename=claimed.filename,
            s3_key=claimed.s3_key,
            kind=claimed.kind,
            stored=True,
            indexed=True,
            status="indexed",
            num_blocks=2,
            num_chunks=5,
        )


@pytest.fixture
def queue_calls(monkeypatch):
    """Capture queue interactions without a database."""
    calls = {"finalize": [], "requeue": []}
    claimed_box = {}

    async def _list_org_ids():
        return ["org-1"]

    async def _recover_stale():
        return 0

    async def _claim_next(org_id):
        return claimed_box.pop("next", None)

    async def _finalize(**kwargs):
        calls["finalize"].append(kwargs)
        return True

    async def _requeue_or_fail(**kwargs):
        calls["requeue"].append(kwargs)
        return "queued"

    monkeypatch.setattr(rag_indexing, "list_org_ids", _list_org_ids)
    monkeypatch.setattr(rag_indexing, "recover_stale", _recover_stale)
    monkeypatch.setattr(rag_indexing, "claim_next", _claim_next)
    monkeypatch.setattr(rag_indexing, "finalize", _finalize)
    monkeypatch.setattr(rag_indexing, "requeue_or_fail", _requeue_or_fail)
    calls["box"] = claimed_box
    return calls


def _claimed(doc_id="doc-1", kind="text"):
    from app.services.rag_index_queue import ClaimedDocument

    return ClaimedDocument(
        org_id="org-1",
        doc_id=doc_id,
        s3_key=f"org-1/{doc_id}/a.txt",
        filename="a.txt",
        kind=kind,
        attempts=1,
    )


async def test_pass_indexes_a_claimed_document(queue_calls):
    queue_calls["box"]["next"] = _claimed()
    pipeline = _StubPipeline()

    processed = await rag_indexing.run_once(pipeline=pipeline)

    assert processed == 1
    assert pipeline.seen == ["doc-1"]
    assert queue_calls["finalize"][0]["status"] == "indexed"
    assert queue_calls["finalize"][0]["num_chunks"] == 5


async def test_skipped_outcome_is_recorded_with_reason(queue_calls):
    queue_calls["box"]["next"] = _claimed(kind="unsupported")
    pipeline = _StubPipeline(
        outcome=IngestionResult(
            doc_id="doc-1", org_id="org-1", filename="a.bin",
            s3_key="k", kind="unsupported", stored=True, indexed=False,
            status="skipped", reason="Unsupported file type for RAG indexing: a.bin",
        )
    )

    await rag_indexing.run_once(pipeline=pipeline)

    finalized = queue_calls["finalize"][0]
    assert finalized["status"] == "skipped"
    assert "Unsupported" in finalized["reason"]
    assert queue_calls["requeue"] == []


async def test_infra_error_requeues_instead_of_finalizing(queue_calls):
    queue_calls["box"]["next"] = _claimed()
    pipeline = _StubPipeline(raises=RuntimeError("qdrant unreachable"))

    await rag_indexing.run_once(pipeline=pipeline)

    assert queue_calls["finalize"] == []
    assert queue_calls["requeue"][0]["error"] == "qdrant unreachable"
    assert queue_calls["requeue"][0]["attempts"] == 1


async def test_empty_queue_is_a_no_op(queue_calls):
    processed = await rag_indexing.run_once(pipeline=_StubPipeline())

    assert processed == 0
    assert queue_calls["finalize"] == []


async def test_run_stops_when_the_stop_event_is_set(queue_calls):
    stop_event = asyncio.Event()
    stop_event.set()

    await asyncio.wait_for(
        rag_indexing.run(
            stop_event=stop_event,
            poll_interval=0.01,
            pipeline=_StubPipeline(),
        ),
        timeout=2,
    )


async def test_run_honours_max_passes(queue_calls):
    await asyncio.wait_for(
        rag_indexing.run(
            poll_interval=0.001, pipeline=_StubPipeline(), max_passes=2
        ),
        timeout=2,
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_indexing_worker.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.workers.rag_indexing'`.

- [ ] **Step 3: Implement the worker**

Create `backend/app/workers/rag_indexing.py`:

```python
"""Standalone worker that indexes queued RAG documents.

Unlike the other three workers this one has no Kafka consumer: the
``rag_documents`` row IS the queue, claimed with FOR UPDATE SKIP LOCKED. That
removes the singleton dispatcher a Redpanda outbox would need, so this worker
is safe to run at any replica count — see the design spec for the reasoning.

Loop shape, signal handling and injectable collaborators follow
``app/workers/ota_rollouts.py`` so the worker is testable without infrastructure.
"""

from __future__ import annotations

import asyncio
import signal
from typing import Optional

import structlog

from app.core.config import settings
from app.services.rag_index_queue import (
    MAX_CLAIMS_PER_ORG_PER_PASS,
    claim_next,
    finalize,
    list_org_ids,
    recover_stale,
    requeue_or_fail,
)
from app.services.rag_ingestion import get_ingestion_pipeline

logger = structlog.get_logger()


async def _process_one(claimed, pipeline) -> None:
    """Index one claimed document and record its outcome.

    An exception here is an infrastructure fault (inference down, Qdrant
    unreachable, blob unreadable), so the row goes back to 'queued' until
    attempts run out. A returned result is a decided outcome — 'indexed' or
    'skipped' — and is written as terminal.
    """
    try:
        result = await pipeline.index_document(claimed)
    except Exception as exc:  # noqa: BLE001 - retryable by definition
        logger.warning(
            "rag_indexing.pass_failed", doc_id=claimed.doc_id, error=str(exc)
        )
        await requeue_or_fail(
            org_id=claimed.org_id,
            doc_id=claimed.doc_id,
            attempts=claimed.attempts,
            error=str(exc),
        )
        return

    await finalize(
        org_id=claimed.org_id,
        doc_id=claimed.doc_id,
        attempts=claimed.attempts,
        status=result.status,
        num_blocks=result.num_blocks,
        num_chunks=result.num_chunks,
        reason=result.reason,
    )


async def run_once(pipeline=None) -> int:
    """One full pass: recover stale rows, then drain every org. Returns count."""
    pipeline = pipeline or get_ingestion_pipeline()
    await recover_stale()

    processed = 0
    for org_id in await list_org_ids():
        for _ in range(MAX_CLAIMS_PER_ORG_PER_PASS):
            claimed = await claim_next(org_id)
            if claimed is None:
                break
            await _process_one(claimed, pipeline)
            processed += 1
    return processed


async def run(
    *,
    stop_event: Optional[asyncio.Event] = None,
    poll_interval: Optional[float] = None,
    pipeline=None,
    max_passes: Optional[int] = None,
) -> None:
    """Poll until stopped. ``max_passes`` bounds the loop for tests."""
    stop_event = stop_event or asyncio.Event()
    if poll_interval is None:
        poll_interval = settings.RAG_INDEX_POLL_INTERVAL_SECONDS

    def _stop() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    registered_signals = []
    for sig in (signal.SIGTERM, signal.SIGINT):
        try:
            loop.add_signal_handler(sig, _stop)
            registered_signals.append(sig)
        except NotImplementedError:  # Windows / non-main thread
            pass

    passes = 0
    try:
        while not stop_event.is_set():
            try:
                await run_once(pipeline=pipeline)
            except Exception as exc:  # noqa: BLE001 - a bad pass must not kill the loop
                logger.error("rag_indexing.pass_errored", error=str(exc))

            passes += 1
            if max_passes is not None and passes >= max_passes:
                return
            try:
                await asyncio.wait_for(stop_event.wait(), timeout=poll_interval)
            except asyncio.TimeoutError:
                pass
    finally:
        for sig in registered_signals:
            loop.remove_signal_handler(sig)


if __name__ == "__main__":
    if not settings.RAG_INDEX_WORKER_ENABLED:
        logger.info("rag_indexing_worker_disabled")
    else:
        logger.info("rag_indexing_worker_starting")
        asyncio.run(run())
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_indexing_worker.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/workers/rag_indexing.py backend/tests/test_rag_indexing_worker.py
git commit -m "feat(rag): add rag_indexing worker draining the document queue"
```

---

### Task 6: API contract — 202, status endpoint, additive listing

**Files:**
- Modify: `backend/app/api/rag.py` (whole file — ingest, list, delete, plus a new status route)
- Test: `backend/tests/test_rag_ingest_async_api.py`

**Interfaces:**
- Consumes: `store_document` (Task 4), `get_status`/`list_for_org` (Task 3), `validate_doc_id` (Task 2).
- Produces: `POST /api/v1/rag/ingest` → 202; `GET /api/v1/rag/documents/{doc_id}/status` → 200/404; `GET /api/v1/rag/documents` gains a `documents` key.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_rag_ingest_async_api.py`:

```python
"""POST /rag/ingest returns 202 and the status endpoint is org-scoped."""

from __future__ import annotations

import pytest

pytest.importorskip("testcontainers")

from app.services import rag_index_queue as q  # noqa: E402


class _FakeDocs:
    available = True
    raw_bucket = "raw"

    async def ensure_bucket(self, bucket):
        return None

    async def put_document(self, *, key, data, content_type, metadata):
        return key

    async def list_documents(self, prefix="", bucket=None):
        return []


@pytest.fixture(autouse=True)
def _stub_document_store(monkeypatch):
    """No SeaweedFS in the test env; the blob write is not what we're testing."""
    import app.services.rag_ingestion as ingestion
    import app.api.rag as rag_api

    pipeline = ingestion.get_ingestion_pipeline()
    monkeypatch.setattr(pipeline, "docs", _FakeDocs())
    monkeypatch.setattr(rag_api, "get_document_store", lambda: _FakeDocs())


async def test_ingest_returns_202_and_queues_the_document(client_a, seeded_orgs):
    resp = await client_a.post(
        "/api/v1/rag/ingest",
        files={"file": ("a.txt", b"hello world", "text/plain")},
        data={"doc_id": "api-doc-1"},
    )

    assert resp.status_code == 202, resp.text
    body = resp.json()
    assert body["stored"] is True
    assert body["indexed"] is False
    assert body["status"] == "queued"
    assert body["doc_id"] == "api-doc-1"

    row = await q.get_status(str(seeded_orgs["org_a_id"]), "api-doc-1")
    assert row["status"] == "queued"


async def test_status_endpoint_round_trips(client_a):
    await client_a.post(
        "/api/v1/rag/ingest",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"doc_id": "api-doc-2"},
    )

    resp = await client_a.get("/api/v1/rag/documents/api-doc-2/status")

    assert resp.status_code == 200
    body = resp.json()
    assert body["doc_id"] == "api-doc-2"
    assert body["status"] == "queued"
    assert body["kind"] == "text"


async def test_status_404_for_unknown_document(client_a):
    resp = await client_a.get("/api/v1/rag/documents/never-uploaded/status")
    assert resp.status_code == 404


async def test_status_is_not_readable_across_orgs(client_a, client_b):
    await client_a.post(
        "/api/v1/rag/ingest",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"doc_id": "org-a-secret"},
    )

    resp = await client_b.get("/api/v1/rag/documents/org-a-secret/status")

    assert resp.status_code == 404, "org B must not observe org A's document"


async def test_malformed_doc_id_is_rejected(client_a):
    resp = await client_a.post(
        "/api/v1/rag/ingest",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"doc_id": "../escape"},
    )
    assert resp.status_code == 422


async def test_documents_listing_keeps_keys_and_adds_metadata(client_a):
    await client_a.post(
        "/api/v1/rag/ingest",
        files={"file": ("a.txt", b"hello", "text/plain")},
        data={"doc_id": "listed-doc"},
    )

    resp = await client_a.get("/api/v1/rag/documents")

    assert resp.status_code == 200
    body = resp.json()
    assert "keys" in body and "count" in body, "back-compat fields must remain"
    assert any(d["doc_id"] == "listed-doc" for d in body["documents"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_ingest_async_api.py -v`
Expected: FAIL — ingest returns 200, not 202.

- [ ] **Step 3: Update the router**

In `backend/app/api/rag.py`: update the module docstring's route list to include the status route, then apply these changes.

Imports:

```python
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form, status as http_status

from app.services.document_store import get_document_store, InvalidDocumentId, validate_doc_id
from app.services.rag_index_queue import get_status, list_for_org
```

Add a helper beside `_org_id`:

```python
def _validated_doc_id(doc_id: str) -> str:
    """Translate an unsafe doc_id into a 422 rather than a 500."""
    try:
        return validate_doc_id(doc_id)
    except InvalidDocumentId as exc:
        raise HTTPException(status_code=422, detail=str(exc))
```

Replace the `ingest` route (lines 44-77) with:

```python
@router.post(
    "/ingest",
    response_model=IngestionResult,
    status_code=http_status.HTTP_202_ACCEPTED,
    summary="Queue a document for ingestion",
)
async def ingest(
    file: UploadFile = File(...),
    doc_id: Optional[str] = Form(None),
    current_user: User = Depends(get_current_active_user),
) -> IngestionResult:
    """Store a file and queue it for indexing.

    Returns ``202`` as soon as the blob is durable, with ``status="queued"``.
    Indexing happens on the rag-indexing worker; poll
    ``GET /rag/documents/{doc_id}/status`` for the outcome. Previously this
    endpoint indexed inline and could outlive the ingress read timeout on large
    documents.
    """
    content = await file.read()
    if not content:
        raise HTTPException(status_code=400, detail="Empty file.")
    if len(content) > settings.RAG_MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=(
                f"File too large ({len(content)} bytes); the limit is "
                f"{settings.RAG_MAX_UPLOAD_BYTES} bytes."
            ),
        )
    if doc_id is not None:
        doc_id = _validated_doc_id(doc_id)
    try:
        return await get_ingestion_pipeline().store_document(
            content=content,
            filename=file.filename or "upload",
            org_id=_org_id(current_user),
            doc_id=doc_id,
            content_type=file.content_type,
            uploaded_by=str(current_user.id),
        )
    except RuntimeError as exc:  # document store not configured/reachable
        raise HTTPException(status_code=503, detail=str(exc))
```

Replace `list_documents` with:

```python
@router.get("/documents", summary="List this org's documents")
async def list_documents(
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """List stored documents.

    ``count``/``keys`` keep their original meaning and S3 source for backward
    compatibility; ``documents`` adds the Postgres registry view. The two can
    differ: blobs ingested before the registry existed have no row.
    """
    org_id = _org_id(current_user)
    docs = get_document_store()
    if not docs.available:
        raise HTTPException(status_code=503, detail="Document store unavailable.")
    try:
        keys = await docs.list_documents(prefix=f"{org_id}/")
    except RuntimeError as exc:  # object store unreachable (e.g. SeaweedFS down)
        raise HTTPException(status_code=503, detail=str(exc))
    return {
        "count": len(keys),
        "keys": keys,
        "documents": await list_for_org(org_id),
    }


@router.get("/documents/{doc_id}/status", summary="Ingestion status of a document")
async def document_status(
    doc_id: str,
    current_user: User = Depends(get_current_active_user),
) -> Dict[str, Any]:
    """Poll a queued document until it reaches a terminal status.

    Terminal statuses are ``indexed`` (vectors are queryable), ``skipped``
    (nothing indexable — see ``reason``) and ``failed`` (infrastructure fault
    after retries — see ``error``). Unknown ids 404 regardless of which tenant
    owns them, so this cannot be used to probe another org.
    """
    row = await get_status(_org_id(current_user), _validated_doc_id(doc_id))
    if row is None:
        raise HTTPException(status_code=404, detail="Document not found.")
    return row
```

In `delete_document`, validate the path param:

```python
    return await get_ingestion_pipeline().delete_document(
        doc_id=_validated_doc_id(doc_id), org_id=_org_id(current_user)
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_ingest_async_api.py -v`
Expected: 6 PASS.

- [ ] **Step 5: Verify the route-level guard suites still pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_route_auth_walk.py tests/test_rag_documents_storage_unavailable.py -v`
Expected: all PASS. The new GET must be rejected for anonymous callers by `test_every_route_rejects_unauthenticated_requests`.

- [ ] **Step 6: Commit**

```bash
git add backend/app/api/rag.py backend/tests/test_rag_ingest_async_api.py
git commit -m "feat(rag): return 202 from ingest and add document status endpoint"
```

---

### Task 7: Compose + k8s deployment

**Files:**
- Modify: `docker-compose.yml` (new service after `ota-rollout-worker`, ~line 313)
- Create: `infrastructure/k8s/base/rag-indexing-worker-deployment.yaml`
- Modify: `infrastructure/k8s/base/kustomization.yaml`
- Test: `backend/tests/test_rag_indexing_topology.py`

**Interfaces:**
- Consumes: the worker module from Task 5.
- Produces: compose service `rag-indexing-worker`; k8s Deployment `rag-indexing-worker`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_rag_indexing_topology.py`:

```python
"""The rag-indexing worker is deployed exactly once, with its RAG wiring.

Mirrors test_ota_worker_topology.py. The critical assertion is the compose
`rag` profile: qdrant/seaweedfs/rag-inference are all profiled, so a worker
without it would start with no dependencies present.
"""

from pathlib import Path

import yaml

REPO_ROOT = Path(__file__).resolve().parents[2]


def _env_map(container):
    return {item["name"]: item.get("value") for item in container["env"]}


def test_compose_service_is_profiled_and_needs_no_redpanda():
    compose = yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())
    worker = compose["services"]["rag-indexing-worker"]

    assert worker["command"] == "python -m app.workers.rag_indexing"
    assert worker["profiles"] == ["rag"], (
        "qdrant/seaweedfs/rag-inference are profiled; the worker must match"
    )
    assert "redpanda" not in worker["depends_on"], (
        "the DB-queue design must not reintroduce a Kafka dependency"
    )
    assert worker["depends_on"]["migrate"] == {
        "condition": "service_completed_successfully"
    }
    required = {
        "DATABASE_URL", "S3_ENDPOINT_URL", "QDRANT_URL", "RAG_INFERENCE_URL",
        "RAG_INDEX_WORKER_ENABLED", "RAG_INDEX_POLL_INTERVAL_SECONDS",
        "RAG_INDEX_MAX_ATTEMPTS", "RAG_INDEX_STALE_INDEXING_SECONDS",
    }
    assert required <= set(worker["environment"])


def test_k8s_deployment_registered_once_with_rag_namespace_fqdns():
    base = REPO_ROOT / "infrastructure/k8s/base"
    kustomization = yaml.safe_load((base / "kustomization.yaml").read_text())
    assert kustomization["resources"].count(
        "rag-indexing-worker-deployment.yaml"
    ) == 1

    manifest = yaml.safe_load(
        (base / "rag-indexing-worker-deployment.yaml").read_text()
    )
    container = manifest["spec"]["template"]["spec"]["containers"][0]
    assert container["command"] == ["python", "-m", "app.workers.rag_indexing"]

    env = _env_map(container)
    assert env["QDRANT_URL"].endswith("qdrant.omniusgrid-rag.svc.cluster.local:6333")
    assert env["S3_ENDPOINT_URL"].endswith(
        "seaweedfs.omniusgrid-rag.svc.cluster.local:8333"
    )
    assert env["SCHEDULERS_IN_API"] == "false"

    security = container["securityContext"]
    assert security["allowPrivilegeEscalation"] is False
    assert security["readOnlyRootFilesystem"] is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_indexing_topology.py -v`
Expected: FAIL — `KeyError: 'rag-indexing-worker'`.

- [ ] **Step 3: Add the compose service**

In `docker-compose.yml`, after the `ota-rollout-worker` block (ends line 312), insert:

```yaml
  # Drains the rag_documents queue: claims 'queued' rows and indexes them.
  # Profiled with the rest of the RAG stack because it depends on seaweedfs,
  # qdrant and rag-inference. Deliberately has NO redpanda dependency - the
  # rag_documents row is the queue (FOR UPDATE SKIP LOCKED), so there is no
  # outbox dispatcher to run and this is safe to scale past one replica.
  rag-indexing-worker:
    build:
      context: .
      dockerfile: backend/Dockerfile
    container_name: omniusgrid-rag-indexing-worker
    restart: unless-stopped
    profiles: ["rag"]
    environment:
      DATABASE_URL: postgresql://omniusgrid:${POSTGRES_PASSWORD:-omniusgrid_dev_password}@timescaledb:5432/omniusgrid
      JWT_SECRET_KEY: ${JWT_SECRET_KEY:-dev_secret_key_change_in_production}
      SCHEDULERS_IN_API: "false"
      QDRANT_URL: http://qdrant:6333
      S3_ENDPOINT_URL: http://seaweedfs:8333
      RAG_INFERENCE_URL: http://rag-inference:8000
      RAG_EMBED_BATCH: ${RAG_EMBED_BATCH:-8}
      RAG_INFERENCE_TIMEOUT: ${RAG_INFERENCE_TIMEOUT:-180}
      RAG_INDEX_WORKER_ENABLED: ${RAG_INDEX_WORKER_ENABLED:-true}
      RAG_INDEX_POLL_INTERVAL_SECONDS: ${RAG_INDEX_POLL_INTERVAL_SECONDS:-5}
      RAG_INDEX_MAX_ATTEMPTS: ${RAG_INDEX_MAX_ATTEMPTS:-3}
      RAG_INDEX_STALE_INDEXING_SECONDS: ${RAG_INDEX_STALE_INDEXING_SECONDS:-900}
      VISION_MODEL_ENABLED: "false"
    volumes:
      - ./backend:/app
    depends_on:
      migrate:
        condition: service_completed_successfully
      timescaledb:
        condition: service_healthy
      seaweedfs:
        condition: service_started
      qdrant:
        condition: service_started
    networks:
      - omniusgrid-network
    command: python -m app.workers.rag_indexing
```

- [ ] **Step 4: Add the k8s Deployment**

Create `infrastructure/k8s/base/rag-indexing-worker-deployment.yaml`. Read `infrastructure/k8s/base/export-worker-deployment.yaml` first and copy its `envFrom`/secret references verbatim for `DATABASE_URL` and `JWT_SECRET_KEY`; the RAG env block is copied from `backend-deployment.yaml:88-108`.

```yaml
apiVersion: apps/v1
kind: Deployment
metadata:
  name: rag-indexing-worker
  namespace: omniusgrid
  labels:
    app.kubernetes.io/name: rag-indexing-worker
    app.kubernetes.io/component: worker
    app.kubernetes.io/part-of: omniusgrid
spec:
  # Safe to raise, unlike ota-rollout-worker: this worker claims rows with
  # FOR UPDATE SKIP LOCKED, so concurrent replicas never take the same
  # document. Starts at 1 only to match its siblings' footprint.
  replicas: 1
  selector:
    matchLabels:
      app.kubernetes.io/name: rag-indexing-worker
  template:
    metadata:
      labels:
        app.kubernetes.io/name: rag-indexing-worker
        app.kubernetes.io/component: worker
    spec:
      securityContext:
        runAsNonRoot: true
        runAsUser: 1000
        runAsGroup: 1000
        fsGroup: 1000
        seccompProfile:
          type: RuntimeDefault
      containers:
        - name: rag-indexing-worker
          image: omniusgrid/backend:latest
          imagePullPolicy: Always
          command: ["python", "-m", "app.workers.rag_indexing"]
          securityContext:
            allowPrivilegeEscalation: false
            readOnlyRootFilesystem: true
            capabilities:
              drop:
                - ALL
          env:
            - name: SCHEDULERS_IN_API
              value: "false"
            # RAG stack lives in its own namespace (infrastructure/k8s/base/rag),
            # applied separately - these FQDNs only resolve where that base is
            # also applied, same caveat as backend-deployment.yaml.
            - name: QDRANT_URL
              value: "http://qdrant.omniusgrid-rag.svc.cluster.local:6333"
            - name: S3_ENDPOINT_URL
              value: "http://seaweedfs.omniusgrid-rag.svc.cluster.local:8333"
            - name: RAG_INFERENCE_URL
              value: "http://rag-inference.omniusgrid-rag.svc.cluster.local:8000"
            - name: RAG_EMBED_BATCH
              value: "8"
            - name: RAG_INFERENCE_TIMEOUT
              value: "180"
            - name: RAG_INDEX_WORKER_ENABLED
              value: "true"
            - name: RAG_INDEX_POLL_INTERVAL_SECONDS
              value: "5"
            - name: RAG_INDEX_MAX_ATTEMPTS
              value: "3"
            - name: RAG_INDEX_STALE_INDEXING_SECONDS
              value: "900"
```

Then append `DATABASE_URL` and `JWT_SECRET_KEY` to that `env:` list using the exact `secretKeyRef` blocks copied from `export-worker-deployment.yaml`, and add the same `resources:` block that file uses.

- [ ] **Step 5: Register it in the kustomization**

In `infrastructure/k8s/base/kustomization.yaml`, add `- rag-indexing-worker-deployment.yaml` to `resources`, next to the other worker deployments. Do **not** add it to `base/rag/kustomization.yaml` — that base is deliberately standalone.

- [ ] **Step 6: Run tests to verify they pass**

Run: `./venv/Scripts/python.exe -m pytest tests/test_rag_indexing_topology.py tests/test_ota_worker_topology.py -v`
Expected: all PASS.

- [ ] **Step 7: Validate the manifests render**

Run: `kubectl kustomize infrastructure/k8s/base > /dev/null && echo OK`
Expected: `OK`. If `kubectl` is unavailable, skip and note it.

- [ ] **Step 8: Commit**

```bash
git add docker-compose.yml infrastructure/k8s/base/rag-indexing-worker-deployment.yaml infrastructure/k8s/base/kustomization.yaml backend/tests/test_rag_indexing_topology.py
git commit -m "feat(rag): deploy rag-indexing worker in compose and k8s"
```

---

### Task 8: Migrate the eval and e2e callers

**Files:**
- Modify: `backend/tests/rag_eval/client.py:101-109` (`ingest`)
- Modify: `scripts/verify_rag_e2e.py:144-163` (`ingest_document`)
- Test: manual verification (these are runtime scripts, not pytest suites)

**Interfaces:**
- Consumes: the 202 contract and status endpoint from Task 6.
- Produces: `client.ingest()` returns the same dict shape as before (`indexed`, `num_blocks`, `num_chunks`, `reason`), so `run_rag_eval.py` needs no changes.

- [ ] **Step 1: Add polling to the eval client**

In `backend/tests/rag_eval/client.py`, replace `ingest` (lines 101-109) with:

```python
    def ingest(self, path: Path, content_type: str, doc_id: str, timeout=300) -> Dict[str, Any]:
        """Upload, then poll until indexing reaches a terminal status.

        Ingestion is asynchronous (202 + worker), but this returns the SAME
        shape the synchronous endpoint used to, so callers and their assertions
        are unchanged.
        """
        body, boundary = _multipart({"doc_id": doc_id}, "file", path.name, path.read_bytes(), content_type)
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        status, raw = _do("POST", f"{self.base}/api/v1/rag/ingest", headers, body, timeout)
        accepted = json.loads(raw)
        return self.await_indexed(accepted["doc_id"], timeout=timeout)

    def await_indexed(self, doc_id: str, timeout=300, interval=2.0) -> Dict[str, Any]:
        """Poll a document's status until terminal, or raise on timeout."""
        deadline = time.monotonic() + timeout
        last = {}
        while time.monotonic() < deadline:
            _, last = self._json(
                "GET",
                f"/api/v1/rag/documents/{urllib.parse.quote(doc_id)}/status",
            )
            if last.get("status") in ("indexed", "skipped", "failed"):
                return {
                    **last,
                    "stored": True,
                    "indexed": last["status"] == "indexed",
                }
            time.sleep(interval)
        raise ApiError(
            408, f"doc {doc_id} still {last.get('status')} after {timeout}s"
        )
```

Add `import time` to the imports at the top of that file if it is not already present.

- [ ] **Step 2: Verify the eval assertions still type-check against the new shape**

Read `backend/tests/rag_eval/run_rag_eval.py:278-285`. It reads `ing.get("indexed")` and `ing.get("num_chunks", 0)`. Confirm both are present in the dict returned by `await_indexed` — `indexed` is set explicitly and `num_chunks` comes from the status row. No changes to `run_rag_eval.py`.

- [ ] **Step 3: Update the e2e verification script**

In `scripts/verify_rag_e2e.py`, replace lines 156-162 of `ingest_document` with:

```python
    r = httpx.post(f"{BACKEND}/api/v1/rag/ingest", files=files, headers=headers, timeout=120)
    if not check("POST /ingest 202", r.status_code == 202, f"(status {r.status_code}: {r.text[:200]})"):
        die("ingest failed")
    accepted = r.json()
    check("stored=true", accepted.get("stored") is True)
    check("status=queued", accepted.get("status") == "queued")

    # Indexing is asynchronous now: poll until the worker reaches a terminal state.
    doc_id = accepted["doc_id"]
    deadline = time.monotonic() + 300
    res = {}
    while time.monotonic() < deadline:
        s = httpx.get(
            f"{BACKEND}/api/v1/rag/documents/{doc_id}/status",
            headers=headers, timeout=30,
        )
        if s.status_code == 200:
            res = s.json()
            if res.get("status") in ("indexed", "skipped", "failed"):
                break
        time.sleep(2)
    else:
        die("indexing did not finish within 300s")

    check("indexed", res.get("status") == "indexed", f"(status {res.get('status')}, reason: {res.get('reason')}, error: {res.get('error')})")
    check("chunks written > 0", res.get("num_chunks", 0) > 0, f"({res.get('num_chunks')} chunks)")
    res["s3_key"] = accepted["s3_key"]
    res["doc_id"] = doc_id
    return res, content, sentinel
```

Add `import time` at the top of `verify_rag_e2e.py` if absent. The `res["s3_key"]` line matters: `verify_seaweedfs` (line 168) reads `res["s3_key"]`, which the status row also carries, but setting it explicitly from the 202 body keeps that contract obvious.

- [ ] **Step 4: Run the full backend suite for regressions**

Run: `./venv/Scripts/python.exe -m pytest tests/ -x -q --ignore=tests/rag_eval`
Expected: no new failures versus the pre-change baseline. If `test_realdb_endpoint_smoke.py` reports the new status route as a 5xx, that is a real bug — fix it rather than adding it to `KNOWN_LANE_FAILURES`.

- [ ] **Step 5: Commit**

```bash
git add backend/tests/rag_eval/client.py scripts/verify_rag_e2e.py
git commit -m "test(rag): poll ingestion status in eval client and e2e script"
```

- [ ] **Step 6: Update the followups doc**

In `docs/rag_ingestion_followups.md`, replace section "## 1. Ingestion is inline in the HTTP request (large-doc blocker)" with a short note that it was resolved by `docs/superpowers/specs/2026-07-30-rag-async-ingestion-design.md`, and move it under the "Already handled" heading at the bottom. Leave items 2-5 untouched.

```bash
git add docs/rag_ingestion_followups.md
git commit -m "docs(rag): mark inline-ingestion followup as resolved"
```

---

## Self-Review

**Spec coverage:** table + RLS → Task 1; `doc_id` validation → Task 2; settings and queue service → Task 3; pipeline split → Task 4; worker → Task 5; 202/status/additive-listing/delete → Task 6; compose + k8s → Task 7; caller migration → Task 8. Every spec section maps to a task.

**Deliberate omissions**, matching the spec's out-of-scope list: streaming uploads (#2), inference pool separation (#3), `delete_by_doc` atomicity (#4), per-tenant quotas (#5).

**Type consistency check:** `ClaimedDocument` fields (`org_id, doc_id, s3_key, filename, kind, attempts`) are defined in Task 3 and consumed identically in Tasks 4 and 5. `finalize(...)` is called in Task 5 with exactly the keyword arguments declared in Task 3. `IngestionResult.status` is added in Task 4 and read in Tasks 5 and 6. `validate_doc_id`/`InvalidDocumentId` are defined in Task 2 and imported in Tasks 4 and 6.

**Known risk:** Task 4 changes `index_document` to *raise* when inference/vectors are unavailable, where `ingest_document` previously returned `indexed=False`. That is intentional — on the worker it must be retryable — and Task 5's `test_infra_error_requeues_instead_of_finalizing` pins the new behavior.
