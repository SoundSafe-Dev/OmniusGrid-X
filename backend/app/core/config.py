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

    # Edge-agent enrollment / internal CA (edge transport security).
    EDGE_CA_CERT_PATH: str = "/certs/edge-ca.crt"
    EDGE_CA_KEY_PATH: str = "/certs/edge-ca.key"
    EDGE_BOOTSTRAP_TOKEN: str = ""   # one-time token agents present to enroll
    EDGE_CERT_TTL_DAYS: int = 30     # validity of issued agent certificates

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
    
    # Application
    ENVIRONMENT: str = "development"   # development | staging | production
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"

    class Config:
        env_file = ".env"


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
    return problems
