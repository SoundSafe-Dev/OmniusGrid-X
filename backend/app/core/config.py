"""Application configuration"""

from pydantic_settings import BaseSettings
from functools import lru_cache


class Settings(BaseSettings):
    """Application settings"""
    
    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./opsgrid.db"
    
    # Message Broker
    REDPANDA_URL: str = "redpanda:29092"
    REDPANDA_TOPICS_PREFIX: str = "opsgrid"
    REDPANDA_COMMAND_TOPIC: str = "opsgrid.commands"
    
    # Security
    JWT_SECRET_KEY: str = "dev_secret_key_change_in_production"
    JWT_ALGORITHM: str = "HS256"
    JWT_ACCESS_TOKEN_EXPIRE_MINUTES: int = 30
    
    # Rate Limiting
    RATE_LIMIT_ENABLED: bool = False
    RATE_LIMIT_PER_USER: str = "100/minute"
    RATE_LIMIT_GLOBAL: str = "1000/minute"
    RATE_LIMIT_BURST: int = 10
    
    # Security Headers
    SECURITY_HEADERS_ENABLED: bool = True
    CSP_ENABLED: bool = True
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
    
    # Correlation AI / Gemma LoRA
    CORRELATION_MODEL_ENABLED: bool = False
    CORRELATION_BASE_MODEL: str = "google/gemma-4-E4B-it"
    CORRELATION_ADAPTER_PATH: str = "./checkpoints/best_lora_v2"
    CORRELATION_MAX_NEW_TOKENS: int = 512
    CORRELATION_TEMPERATURE: float = 0.2

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

    # Retrieval (query path). Hybrid search returns RAG_RETRIEVE_LIMIT fused
    # candidates; the reranker cuts them to RAG_RERANK_TOP_N passages, capped at
    # RAG_MAX_CONTEXT_CHARS of concatenated text fed to the LLM.
    RAG_RETRIEVE_LIMIT: int = 20  # fused candidates handed to the reranker
    RAG_RERANK_TOP_N: int = 5  # passages kept after rerank, sent to the LLM
    RAG_MAX_CONTEXT_CHARS: int = 12000  # cap on concatenated context

    # Application
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
