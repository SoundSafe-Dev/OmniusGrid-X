"""Application configuration"""

from pydantic_settings import BaseSettings, SettingsConfigDict
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings"""
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./opsgrid.db"
    
    # Message Broker
    REDPANDA_URL: str = "redpanda:29092"
    REDPANDA_TOPICS_PREFIX: str = "opsgrid"
    REDPANDA_COMMAND_TOPIC: str = "opsgrid.commands"
    REDPANDA_COMMAND_ACK_TOPIC: str = "opsgrid.commands.acks"
    REDPANDA_COMMAND_DLQ_TOPIC: str = "opsgrid.commands.dlq"
    # Poison telemetry/state/alarm messages the ingestion worker can't process
    # go here instead of being silently dropped as the offset auto-commits past
    # them. Lets them be inspected/replayed rather than lost.
    REDPANDA_INGESTION_DLQ_TOPIC: str = "opsgrid.ingestion.dlq"
    REDPANDA_EXPORT_TOPIC: str = "opsgrid.exports"
    REDPANDA_COMPLIANCE_REPORTS_TOPIC: str = "opsgrid.compliance-reports"
    AGENT_STATUS_TOPIC: str = "opsgrid.agent-status"

    # Edge-agent OTA release registry
    OTA_STORAGE_PATH: str = "/var/lib/omniusgrid/ota"
    OTA_SIGNATURE_ALG: str = "ed25519"
    OTA_SIGNING_PRIVATE_KEY_PATH: str = ""
    OTA_SIGNING_PUBLIC_KEY: str = ""
    OTA_ROLLOUT_DISPATCH_ENABLED: bool = True
    OTA_ROLLOUT_DISPATCH_INTERVAL_SECONDS: int = 30

    # Draining the systems-of-record ledger (FS-427). Slower than the rollout dispatcher on
    # purpose: a posting is an obligation to a far system, not a device waiting on a
    # command, and hammering an ERP every 30s to be told again that it has no write path
    # helps nobody. Five minutes is well inside any operator's patience for "did purchasing
    # hear about this" and well outside a third party's rate limit.
    POSTING_DRAIN_ENABLED: bool = True
    POSTING_DRAIN_INTERVAL_SECONDS: int = 300
    #: Per organisation, per pass. Bounded so one tenant with a large backlog cannot hold
    #: the loop while every other tenant waits.
    POSTING_DRAIN_BATCH_SIZE: int = 50
    OTA_ROLLOUT_DEFAULT_COMMAND_TIMEOUT_SECONDS: int = 120
    OTA_ROLLOUT_DEFAULT_HEALTH_TIMEOUT_SECONDS: int = 300
    OTA_ROLLOUT_DEFAULT_MIN_SUCCESS_RATIO: float = 1.0
    
    # Security
    JWT_SECRET_KEY: str = "dev_secret_key_change_in_production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    JWT_REFRESH_TOKEN_EXPIRE_DAYS: int = 7

    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = False
    RATE_LIMIT_PER_USER: str = "100/minute"
    RATE_LIMIT_GLOBAL: str = "1000/minute"
    RATE_LIMIT_BURST: int = 10
    AUTH_LOGIN_RATE_LIMIT: str = "10/minute"
    AUTH_REGISTER_RATE_LIMIT: str = "5/hour"
    AUTH_REFRESH_RATE_LIMIT: str = "30/minute"
    AUTH_LOGOUT_RATE_LIMIT: str = "30/minute"
    
    # Security Headers
    SECURITY_HEADERS_ENABLED: bool = True
    CSP_ENABLED: bool = True
    AUDIT_LOGGING_ENABLED: bool = True
    # CSRF is a cookie+header token scheme; this API authenticates via Bearer
    # JWT (not cookies), so CSRF is off by default. Enable only for a
    # cookie-session deployment, and teach the SPA to echo X-CSRF-Token.
    CSRF_ENABLED: bool = False
    HSTS_ENABLED: bool = True
    HSTS_MAX_AGE: int = 31536000  # 1 year
    HSTS_INCLUDE_SUBDOMAINS: bool = True
    HSTS_PRELOAD: bool = True
    
    # mTLS (for production)
    MTLS_ENABLED: bool = False
    MTLS_CA_CERT_PATH: str = "/certs/ca.crt"
    MTLS_SERVER_CERT_PATH: str = "/certs/server.crt"
    MTLS_SERVER_KEY_PATH: str = "/certs/server.key"
    MTLS_CLIENT_CERT_PATH: str = "/certs/edge-client.crt"
    MTLS_CLIENT_KEY_PATH: str = "/certs/edge-client.key"

    # Edge-agent enrollment / internal CA (edge transport security).
    EDGE_CA_CERT_PATH: str = "/certs/edge-ca.crt"
    EDGE_CA_KEY_PATH: str = "/certs/edge-ca.key"
    EDGE_BOOTSTRAP_TOKEN: str = ""   # one-time token agents present to enroll
    EDGE_CERT_TTL_DAYS: int = 30     # validity of issued agent certificates
    # The tenant enrolling agents are issued certificates for. Server-side and
    # deliberately NOT a field on the enrolment request: an agent that names its
    # own organisation is the tenant-from-the-body defect. Blank means "resolve
    # it", which succeeds only where the answer is unambiguous — exactly one
    # organisation exists. A multi-tenant deployment must set this per edge
    # gateway; enrolment refuses rather than guessing.
    EDGE_ENROLLMENT_ORGANIZATION_ID: str = ""

    # Distributed tracing (OpenTelemetry). Off by default; a no-op when disabled.
    OTEL_ENABLED: bool = False
    OTEL_SERVICE_NAME: str = "omniusgrid-backend"
    OTEL_EXPORTER_OTLP_ENDPOINT: str = "http://otel-collector:4317"
    
    # Cloud Gateway
    CLOUD_MQTT_HOST: str = "cloud.opsgrid.io"
    CLOUD_MQTT_PORT: int = 8883
    CLOUD_TOPIC_PREFIX: str = "opsgrid/factories/dev"
    
    # MLOps
    MODEL_REGISTRY_URL: str = "https://models.opsgrid.io"
    MODEL_REGISTRY_API_KEY: str = ""
    LOCAL_MODEL_DIR: str = "./models"
    MODEL_POLL_INTERVAL: int = 300  # 5 minutes
    TACTICAL_MODEL_PATH: str = "./models/tactical_v1.pt"
    # Cloud-side registry artifact store (backend writes trained .pt here)
    MODEL_STORAGE_PATH: str = "/var/lib/omniusgrid/models"
    
    # Correlation AI / Gemma LoRA
    CORRELATION_MODEL_ENABLED: bool = False
    CORRELATION_BASE_MODEL: str = "google/gemma-4-E4B-it"
    CORRELATION_ADAPTER_PATH: str = "./checkpoints/best_lora_v2"
    CORRELATION_MAX_NEW_TOKENS: int = 512
    CORRELATION_TEMPERATURE: float = 0.2
    # Gemma prompt budget — multi-file summary is always included; per-file depth scales down.
    CORRELATION_CHAT_MAX_PROMPT_CHARS: int = 64000
    CORRELATION_CHAT_MAX_DETAILED_SOURCES: int = 3
    CORRELATION_CHAT_COMPACT_THRESHOLD: int = 4
    CORRELATION_GROUNDED_PACKET_MAX_CHARS: int = 24000

    # Vision / image text extraction (Gemma multimodal or Gemini fallback)
    VISION_MODEL_ENABLED: bool = False
    VISION_MODEL_PROVIDER: str = "gemini"  # "gemini" | "gemma"
    VISION_MODEL_NAME: str = "gemini-1.5-flash"
    VISION_MAX_IMAGE_BYTES: int = 5 * 1024 * 1024  # prompt user above this
    
    # Edge
    EDGE_NODE_ID: str = "edge-001"
    ORGANIZATION_ID: str = "dev-org"
    
    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Scheduled exports / company SMTP (Task 5)
    EXPORT_SCHEDULER_ENABLED: bool = True
    EXPORT_SCHEDULER_INTERVAL_SECONDS: int = 30
    EXPORT_STORAGE_PATH: str = "/var/lib/omniusgrid/exports"
    # When true, generated export/compliance artifacts are stored in object
    # storage (S3/SeaweedFS) instead of the pod's local disk, and downloads
    # stream from there. This is required in any multi-pod deployment: a worker
    # generates the file on its own node while the API serves the download from a
    # DIFFERENT pod, so a pod-local file is invisible to the API and the download
    # 404s. Off by default so dev/single-node keeps the simple local path.
    EXPORT_USE_S3: bool = False
    S3_EXPORT_BUCKET: str = "omniusgrid-exports"
    EXPORT_PUBLIC_BASE_URL: str = "http://localhost:8002"
    EXPORT_LINK_EXPIRE_MINUTES: int = 1440
    SIGNED_URL_SECRET_KEY: str = ""
    SIGNED_URL_ALGORITHM: str = "HS256"
    SIGNED_URL_ISSUER: str = "omniusgrid-signed-links"
    SIGNED_URL_AUDIENCE: str = "omniusgrid-report-download"
    SIGNED_URL_ACCEPT_LEGACY_EXPORT_TOKENS: bool = True
    COMPLIANCE_REPORT_DISPATCH_ENABLED: bool = True
    COMPLIANCE_REPORT_DISPATCH_INTERVAL_SECONDS: int = 30
    COMPLIANCE_REPORT_STALE_PUBLISHING_SECONDS: int = 300
    COMPLIANCE_REPORT_STALE_RUNNING_SECONDS: int = 900
    COMPLIANCE_REPORT_STALE_SENDING_SECONDS: int = 300
    COMPLIANCE_REPORT_GENERATION_MAX_ATTEMPTS: int = 3
    COMPLIANCE_REPORT_EMAIL_MAX_ATTEMPTS: int = 3
    # Task 8 enables this after signed public download links are available.
    COMPLIANCE_REPORT_EMAIL_ENABLED: bool = False
    COMPLIANCE_REPORT_SCHEDULER_ENABLED: bool = True
    COMPLIANCE_REPORT_SCHEDULER_INTERVAL_SECONDS: int = 30
    SMTP_HOST: str = ""
    SMTP_PORT: int = 587
    SMTP_USERNAME: str = ""
    SMTP_PASSWORD: str = ""
    SMTP_FROM_EMAIL: str = "reports@omniusgrid.local"
    SMTP_FROM_NAME: str = "OmniusGrid Reports"
    SMTP_USE_TLS: bool = False
    SMTP_START_TLS: bool = True

    # ERP integrations (revived from WIP 527e14a5, disabled by default)
    ERP_SYNC_MAX_RETRIES: int = 3
    ERP_SYNC_DEFAULT_LIMIT: int = 100
    ERP_ALERTS_ENABLED: bool = False
    ERP_ALERT_FAILURE_THRESHOLD: int = 5
    ERP_ALERT_EMAIL_RECIPIENTS: str = ""
    ERP_ALERT_SLACK_WEBHOOK_URL: str = ""
    ERP_ALERT_PAGERDUTY_WEBHOOK_URL: str = ""

    # Master key for ERP field encryption. Per-org keys are derived from it
    # deterministically (stable across restarts). REQUIRED in production — a
    # runtime-generated key would make previously-encrypted credentials
    # undecryptable after a restart.
    ERP_ENCRYPTION_KEY: str = ""

    # Keycloak / SSO (Task 6 — disabled by default)
    KEYCLOAK_ENABLED: bool = False
    KEYCLOAK_URL: str = ""
    KEYCLOAK_REALM: str = ""
    KEYCLOAK_CLIENT_ID: str = ""
    KEYCLOAK_CLIENT_SECRET: str = ""
    KEYCLOAK_ADMIN_USERNAME: str = ""
    KEYCLOAK_ADMIN_PASSWORD: str = ""
    # Fallback org for JIT-provisioning SSO users whose token carries no
    # organization_id claim (per Hamad: option (a) primary, (b) safety net).
    # Defaults to the seeded dev org (see auth.py / migrations 005-008); admins
    # can move users to the right org afterward.
    # NOTE: in a real multi-tenant deployment where Keycloak brokers several
    # customer orgs through one realm, rely on the token claim and set this to ""
    # so users aren't silently merged into one tenant.
    KEYCLOAK_DEFAULT_ORGANIZATION_ID: str = "00000000-0000-0000-0000-000000000001"


    # Document Object Store (SeaweedFS S3 gateway)
    # Endpoint is the SeaweedFS S3 gateway. The same client config works against
    # MinIO or real AWS S3 by swapping these values - no code change required.
    S3_ENDPOINT_URL: str = "http://seaweedfs:8333"
    S3_ACCESS_KEY: str = "omniusgrid"
    S3_SECRET_KEY: str = "omniusgrid_dev_secret"
    S3_REGION: str = "us-east-1"  # dummy; SeaweedFS ignores it but boto3 requires one
    S3_RAW_BUCKET: str = "raw-documents"
    S3_TEXT_BUCKET: str = "extracted-text"
    S3_PRESIGN_EXPIRE_SECONDS: int = 3600

    # RAG embeddings + reranker (BGE via the rag-inference service)
    # The ENDPOINT varies per deployment topology (own node / on-prem / RunPod);
    # the MODEL is fixed - it is a data contract with the vector store. Changing
    # EMBEDDING_MODEL means re-indexing everything. Do not make it per-deployment.
    RAG_INFERENCE_URL: str = "http://rag-inference:8000"
    RAG_INFERENCE_API_KEY: str = ""  # bearer token; empty = trusted local network
    RAG_INFERENCE_TIMEOUT: float = 60.0
    EMBEDDING_MODEL: str = "BAAI/bge-m3"  # pinned; must match indexed vectors
    EMBEDDING_DIM: int = 1024  # BGE-M3 dense size (Qdrant collection dimension)
    RERANKER_MODEL: str = "BAAI/bge-reranker-v2-m3"

    # LLM inference (generation) - the swappable seam.
    # OpenAI-compatible endpoint: vLLM / Ollama / TGI / hosted / a CUSTOM-BUILT
    # Gemma all work by changing these values only - no application code change.
    LLM_BASE_URL: str = "http://gemma:8000/v1"
    LLM_MODEL: str = "gemma-12b"  # whatever the LLM server registers (e.g. a custom fine-tune)
    LLM_API_KEY: str = ""  # bearer; empty for local/trusted network
    LLM_TIMEOUT: float = 120.0
    LLM_MAX_TOKENS: int = 1024
    LLM_TEMPERATURE: float = 0.2

    # Vector store (Qdrant) - self-hosted or Qdrant Cloud by endpoint alone.
    # The dense dimension must equal EMBEDDING_DIM (data contract with BGE-M3).
    QDRANT_URL: str = "http://qdrant:6333"
    QDRANT_API_KEY: str = ""  # required for Qdrant Cloud; empty for self-hosted
    QDRANT_COLLECTION: str = "documents"
    QDRANT_PREFETCH_LIMIT: int = 50  # candidates per mode retrieved before fusion

    # Chunking (document -> chunks, before embedding). Sizes are in *approximate
    # tokens*: the backend carries no BGE tokenizer, so we approximate token
    # counts with a chars-per-token ratio (BGE-M3 uses an XLM-RoBERTa
    # sentencepiece tokenizer; ~4 chars/token is a safe English heuristic).
    # Overlap repeats trailing context into the next chunk so a fact that
    # straddles a boundary is still retrievable from at least one chunk.
    RAG_CHUNK_TOKENS: int = 512  # target chunk size (approx tokens)
    RAG_CHUNK_OVERLAP_TOKENS: int = 64  # overlap between adjacent chunks
    RAG_CHARS_PER_TOKEN: float = 4.0  # heuristic used to convert tokens<->chars
    RAG_MIN_CHUNK_CHARS: int = 40  # merge a trailing chunk shorter than this
    RAG_EMBED_BATCH: int = 32  # chunks embedded per rag-inference request
    # Ingestion guardrails (durability). Upload cap matches the k8s ingress
    # proxy-body-size so local and prod reject the same files; the per-doc chunk
    # cap stops a pathological document from exploding embeddings/Qdrant/memory.
    RAG_MAX_UPLOAD_BYTES: int = 50 * 1024 * 1024  # 50 MiB, mirrors ingress
    RAG_MAX_CHUNKS_PER_DOC: int = 2000  # hard cap; larger docs are truncated + flagged
    # Per-citation snippet preview length. A citation shows a window of its source
    # chunk; too short and the cited fact falls outside the preview (e.g. a long
    # table row or an unstructured .txt chunk whose match sits past the cutoff).
    RAG_CITATION_SNIPPET_CHARS: int = 600
    RAG_TABLE_ROWS_PER_BLOCK: int = 1  # table rows per citable block (1 = one row/block)

    # Retrieval (query path). Hybrid search returns RAG_RETRIEVE_LIMIT fused
    # candidates; the reranker cuts them to RAG_RERANK_TOP_N passages, capped at
    # RAG_MAX_CONTEXT_CHARS of concatenated text fed to the LLM.
    RAG_RETRIEVE_LIMIT: int = 20  # fused candidates handed to the reranker
    RAG_RERANK_TOP_N: int = 5  # passages kept after rerank, sent to the LLM
    RAG_MAX_CONTEXT_CHARS: int = 12000  # cap on concatenated context

    # Operational context (ERP) blended into the generation prompt.
    # A SECOND retrieval leg, deliberately not a second corpus: ERP rows are read
    # live from Postgres at query time and appended to the prompt UNNUMBERED, so
    # they inform the answer while only document chunks carry [n] citations.
    # Keeping them out of Qdrant means no re-index on every ERP sync, no synthetic
    # "documents" with no blob behind them, and no competition for the rerank slots
    # that belong to policy text.
    #
    # CANDIDATE_ROWS is the DB read (most recent rows, filtered in Python because
    # entity_data is JSON not JSONB - see rag_erp_context); CONTEXT_ROWS/CHARS are
    # what survives into the prompt. The prompt budget is deliberately ~4x smaller
    # than RAG_MAX_CONTEXT_CHARS: operational records qualify the documents, they
    # do not replace them.
    RAG_ERP_CONTEXT_ENABLED: bool = True
    RAG_ERP_CANDIDATE_ROWS: int = 300  # rows read from Postgres before filtering
    RAG_ERP_CONTEXT_ROWS: int = 40  # rows that reach the prompt
    RAG_ERP_CONTEXT_CHARS: int = 3000  # cap on the rendered operational block

    # Application
    ENVIRONMENT: str = "development"   # development | staging | production
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    # CORS: comma-separated allowlist. "*" is permitted ONLY outside production
    # (and is incompatible with credentialed requests, which browsers reject).
    CORS_ALLOW_ORIGINS: str = "*"

    # Shared secret for the GeoTab webhook (external callback, no user JWT).
    # When set, callers must send it as X-Webhook-Secret; empty allows all
    # (dev only — validate_settings flags an empty secret in production).
    GEOTAB_WEBHOOK_SECRET: str = ""

    # GeoTab telematics: simulated (random demo data) vs a real MyGeotab client.
    # Default true so demos work offline. When false the service uses the live
    # client and raises loudly if credentials are missing — never a silent fake.
    GEOTAB_SIMULATED: bool = True
    GEOTAB_DATABASE: str = ""   # MyGeotab database name (live mode)
    GEOTAB_USERNAME: str = ""
    GEOTAB_PASSWORD: str = ""

    # Routing/distance provider for shipment ETA + freight costing.
    # "haversine" (default, always available) | "osrm" (self-hosted road routing).
    ROUTING_PROVIDER: str = "haversine"
    ROUTING_OSRM_URL: str = ""   # e.g. http://osrm:5000

    # FLEET COSTING ASSUMPTIONS (FS-348). These were four literals buried in
    # `RouteOptimizer.optimize_route` — `total_distance / 50`, `/ 6`, `* 3.50`, `* 0.05` —
    # whose outputs are PERSISTED onto `routes.fuel_cost_estimate` /
    # `.toll_cost_estimate` / `.estimated_duration_hours` and served from
    # `GET /transportation/routes`.
    #
    # The distance they multiply is real (haversine, or OSRM road distance when
    # configured). These four are not measurements of anything: they are a national
    # average from an unrecorded date, and a fleet of electric vans or a region with no
    # toll roads gets a confidently wrong number. Deterministic output reads as computed,
    # which makes this harder to spot than a random one.
    #
    # Named and configurable so an operator can set them to their own fleet, and so the
    # values are visible in one place instead of inline in an arithmetic expression. The
    # estimate still is not a quote — `optimize_route` returns the assumptions it used
    # alongside the figures, so a consumer can see what the number rests on.
    FLEET_AVERAGE_SPEED_MPH: float = 50.0
    FLEET_STOP_MINUTES: float = 30.0
    FLEET_AVERAGE_MPG: float = 6.0
    FUEL_PRICE_USD_PER_GALLON: float = 3.50
    TOLL_COST_USD_PER_MILE: float = 0.05

    # Require edge requests to carry a proof-of-possession signature
    # (X-Agent-Timestamp/X-Agent-Signature) in addition to the CA-verified
    # certificate header. The cert is public material — without the signature a
    # captured header is replayable. Default false for rolling upgrades (old
    # agents don't sign yet); flagged in production.
    EDGE_REQUIRE_PROOF_OF_POSSESSION: bool = False

    # Run the worker-backed schedulers (export, compliance-report, OTA rollout)
    # inside the API process. Default true so a standalone API still dispatches;
    # set false when the dedicated compose workers own dispatch, to avoid two
    # pollers racing the same queues.
    SCHEDULERS_IN_API: bool = True

    # Dev-only auth conveniences. Both MUST be false in production; the
    # startup hook (validate_settings) hard-fails if they are left on.
    ALLOW_DEV_TOKEN: bool = True   # accept "dev-token" as an admin bypass
    ALLOW_OPEN_REGISTRATION: bool = True  # unauthenticated POST /auth/register

    model_config = SettingsConfigDict(env_file=".env")

    @property
    def cors_origins(self) -> list[str]:
        """Parsed CORS allowlist. Empty/whitespace collapses to wildcard."""
        origins = [o.strip() for o in self.CORS_ALLOW_ORIGINS.split(",") if o.strip()]
        return origins or ["*"]

    @property
    def cors_is_wildcard(self) -> bool:
        """True when any parsed origin is '*' (wildcard is credential-incompatible)."""
        return "*" in self.cors_origins


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()

# Insecure defaults that must not ship to production (task 17).
_INSECURE_JWT = "dev_secret_key_change_in_production"


def validate_settings(s: "Settings" = None) -> list[str]:
    """Return a list of production-safety problems (empty when OK).

    Advisory in non-prod; the startup hook escalates to a hard failure when
    ENVIRONMENT=production so a misconfigured deploy fails fast instead of
    running with dev secrets.
    """
    s = s or settings
    problems: list[str] = []
    if s.ENVIRONMENT.lower() == "production":
        if not s.JWT_SECRET_KEY or s.JWT_SECRET_KEY == _INSECURE_JWT:
            problems.append("JWT_SECRET_KEY is unset or the insecure dev default")
        if s.DEBUG:
            problems.append("DEBUG must be false in production")
        if not s.EDGE_BOOTSTRAP_TOKEN:
            problems.append("EDGE_BOOTSTRAP_TOKEN is empty; edge enrollment is disabled")
        if s.ALLOW_DEV_TOKEN:
            problems.append("ALLOW_DEV_TOKEN must be false in production (admin auth bypass)")
        if s.ALLOW_OPEN_REGISTRATION:
            problems.append("ALLOW_OPEN_REGISTRATION must be false in production")
        if s.cors_is_wildcard:
            problems.append("CORS_ALLOW_ORIGINS must be an explicit allowlist in production, not '*' (empty also means '*')")
        if not s.GEOTAB_WEBHOOK_SECRET:
            problems.append("GEOTAB_WEBHOOK_SECRET is empty; the GeoTab webhook is unauthenticated")
        if not s.ERP_ENCRYPTION_KEY:
            problems.append("ERP_ENCRYPTION_KEY is unset; ERP field encryption would use an unstable runtime key")
        if s.GEOTAB_SIMULATED:
            problems.append("GEOTAB_SIMULATED must be false in production (random demo telematics would be served as real data)")
        if not s.EDGE_REQUIRE_PROOF_OF_POSSESSION:
            problems.append("EDGE_REQUIRE_PROOF_OF_POSSESSION should be true in production (unsigned edge requests are replayable)")
    return problems
