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
    REDPANDA_EXPORT_TOPIC: str = "opsgrid.exports"
    REDPANDA_COMPLIANCE_REPORTS_TOPIC: str = "opsgrid.compliance-reports"
    
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
    
    # Edge
    EDGE_NODE_ID: str = "edge-001"
    ORGANIZATION_ID: str = "dev-org"
    
    # Redis
    REDIS_URL: str = "redis://redis:6379/0"

    # Scheduled exports / company SMTP (Task 5)
    EXPORT_SCHEDULER_ENABLED: bool = True
    EXPORT_SCHEDULER_INTERVAL_SECONDS: int = 30
    EXPORT_STORAGE_PATH: str = "/var/lib/omniusgrid/exports"
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

    # Application
    DEBUG: bool = True
    LOG_LEVEL: str = "INFO"
    
    class Config:
        env_file = ".env"


@lru_cache()
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
