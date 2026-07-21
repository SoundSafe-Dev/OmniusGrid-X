"""
Zero-dependency HTTP client for the RAG API (stdlib urllib only).

Shared by the pytest suite (conftest fixtures) and the standalone matrix runner.
Model-agnostic: it never assumes which LLM/embedder is behind the API — call
``RagClient.health()`` to discover the active models and tag results with them.

Auth resolution (RagClient.resolve_token): explicit token > email/password
login > the ``dev-token`` bypass (needs ALLOW_DEV_TOKEN, which self-provisions
the dev org+user).
"""

import json
import os
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

DOCS_DIR = Path(__file__).resolve().parent.parent / "docs"
BASENAME = "SOP-QA-014_Allergen_Control_Sanitation"

FORMATS = {
    "pdf":  (f"{BASENAME}.pdf",  "application/pdf"),
    "docx": (f"{BASENAME}.docx", "application/vnd.openxmlformats-officedocument.wordprocessingml.document"),
    "md":   (f"{BASENAME}.md",   "text/markdown"),
    "txt":  (f"{BASENAME}.txt",  "text/plain"),
    "csv":  (f"{BASENAME}.csv",  "text/csv"),
}


class ApiError(Exception):
    def __init__(self, status: int, body: str):
        self.status, self.body = status, body
        super().__init__(f"HTTP {status}: {body[:400]}")


def _do(method: str, url: str, headers=None, data=None, timeout=180):
    req = urllib.request.Request(url, data=data, method=method, headers=headers or {})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        raise ApiError(e.code, e.read().decode("utf-8", "replace"))
    except urllib.error.URLError as e:
        raise ApiError(0, f"connection error: {e.reason}")


class RagClient:
    def __init__(self, base_url: str, token: str):
        self.base = base_url.rstrip("/")
        self.token = token

    # -- auth ------------------------------------------------------------- #
    @classmethod
    def login(cls, base_url: str, email: str, password: str) -> str:
        form = urllib.parse.urlencode({"username": email, "password": password}).encode()
        headers = {"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"}
        _, raw = _do("POST", f"{base_url.rstrip('/')}/api/v1/auth/login", headers, form)
        return json.loads(raw)["access_token"]

    @classmethod
    def resolve_token(cls, base_url, token=None, email=None, password=None) -> str:
        token = token or os.environ.get("RAG_TEST_TOKEN")
        if token:
            return token
        email = email or os.environ.get("RAG_TEST_EMAIL")
        password = password or os.environ.get("RAG_TEST_PASSWORD")
        if email and password:
            return cls.login(base_url, email, password)
        return "dev-token"  # ALLOW_DEV_TOKEN self-provisions the dev org+user

    def _json(self, method, path, body=None, timeout=180):
        headers = {"Accept": "application/json", "Authorization": f"Bearer {self.token}"}
        data = None
        if body is not None:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
        status, raw = _do(method, f"{self.base}{path}", headers, data, timeout)
        return status, (json.loads(raw) if raw else {})

    # -- RAG endpoints ---------------------------------------------------- #
    def health(self) -> Dict[str, Any]:
        _, resp = self._json("GET", "/api/v1/rag/health")
        return resp

    def llm_available(self) -> bool:
        llm = self.health().get("llm", {})
        return bool(llm.get("available", False)) if isinstance(llm, dict) else False

    def model_tag(self) -> Dict[str, Any]:
        """The active model triple, for tagging a report/run."""
        h = self.health()
        inf = h.get("inference", {}) if isinstance(h.get("inference"), dict) else {}
        llm = h.get("llm", {}) if isinstance(h.get("llm"), dict) else {}
        return {
            "llm": llm.get("model"),
            "llm_available": llm.get("available", False),
            "embedder": inf.get("embedding_model"),
            "reranker": inf.get("reranker_model"),
            "device": inf.get("device"),
        }

    def ingest(self, path: Path, content_type: str, doc_id: str, timeout=300) -> Dict[str, Any]:
        body, boundary = _multipart({"doc_id": doc_id}, "file", path.name, path.read_bytes(), content_type)
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        status, raw = _do("POST", f"{self.base}/api/v1/rag/ingest", headers, body, timeout)
        return json.loads(raw)

    def ingest_bytes(self, filename, content_type, data: bytes, doc_id: str, timeout=120):
        """Ingest raw bytes (for robustness tests: empty, oversized, corrupt…).

        Unlike ``ingest``, this RETURNS the 4xx status instead of raising, so a
        robustness test can assert on the rejection code (400/413/415)."""
        body, boundary = _multipart({"doc_id": doc_id}, "file", filename, data, content_type)
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
            "Content-Type": f"multipart/form-data; boundary={boundary}",
        }
        try:
            status, raw = _do("POST", f"{self.base}/api/v1/rag/ingest", headers, body, timeout)
        except ApiError as e:
            try:
                return e.status, json.loads(e.body)
            except (ValueError, TypeError):
                return e.status, {"detail": e.body}
        return status, (json.loads(raw) if raw else {})

    def query(self, q: str, generate=True, top_n: Optional[int] = None) -> Dict[str, Any]:
        body = {"query": q, "generate": generate}
        if top_n:
            body["top_n"] = top_n
        _, resp = self._json("POST", "/api/v1/rag/query", body)
        return resp

    def list_doc_ids(self) -> set:
        try:
            _, resp = self._json("GET", "/api/v1/rag/documents")
        except ApiError as e:
            if e.status in (500, 404, 503):  # bucket not created yet
                return set()
            raise
        ids = set()
        for key in resp.get("keys", []):
            parts = key.split("/")
            if len(parts) >= 2:
                ids.add(parts[1])
        return ids

    def delete_doc(self, doc_id: str):
        return self._json("DELETE", f"/api/v1/rag/documents/{urllib.parse.quote(doc_id)}")

    def wipe_all(self) -> int:
        n = 0
        for doc_id in self.list_doc_ids():
            try:
                self.delete_doc(doc_id)
                n += 1
            except ApiError:
                pass
        return n


def _multipart(fields, file_field, filename, file_bytes, content_type):
    boundary = f"----ragEval{uuid.uuid4().hex}"
    parts: List[bytes] = []
    for name, value in fields.items():
        parts.append(f"--{boundary}\r\n".encode())
        parts.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        parts.append(f"{value}\r\n".encode())
    parts.append(f"--{boundary}\r\n".encode())
    parts.append(f'Content-Disposition: form-data; name="{file_field}"; filename="{filename}"\r\n'.encode())
    parts.append(f"Content-Type: {content_type}\r\n\r\n".encode())
    parts.append(file_bytes)
    parts.append(f"\r\n--{boundary}--\r\n".encode())
    return b"".join(parts), boundary
