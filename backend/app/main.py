"""OpsGrid Backend Application"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api import assets, telemetry, alarms, operations, auth, dashboard, health, engines
from app.api import yard, transportation, logistics_correlation, websocket, commands, oee, kanban, registries, geotab, correlation_integration, nlp_correlation, analysis_sessions, user_context, audit, api_keys, gdpr, compliance, data_residency, erp_integrations
from app.api import health_index, simulation, notifications
from app.api import edge_enroll, edge_ingest, edge_fleet
from app.core.config import settings
from app.db.database import init_db
from app.services.websocket_manager import websocket_manager
from app.services.command_executor import command_executor
from app.services.oee_calculator import oee_calculator
from app.core.errors import register_exception_handlers
from app.core.openapi import custom_generate_unique_id
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.idempotency import IdempotencyMiddleware
from app.middleware.audit import AuditLoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.rate_limit import limiter


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    await init_db()
    # await websocket_manager.connect()
    # await command_executor.start()
    # await oee_calculator.start()
    yield
    # Shutdown
    # await oee_calculator.stop()
    # await command_executor.stop()
    # await websocket_manager.disconnect()


app = FastAPI(
    title="OmniusGrid API",
    description="""
    Universal Manufacturing Data Feed Dashboard API for Industry 4.0 operations.
    
    ## Authentication
    
    The API uses JWT Bearer token authentication. Include the token in the Authorization header:
    
    ```
    Authorization: Bearer <your_jwt_token>
    ```
    
    ### Development Mode
    
    For development, you can use the `dev-token` bypass:
    
    ```
    Authorization: Bearer dev-token
    ```
    
    ## Error Codes
    
    - `401 Unauthorized`: Invalid or missing authentication token
    - `403 Forbidden`: Insufficient permissions for the requested resource
    - `404 Not Found`: Resource does not exist
    - `422 Unprocessable Entity`: Validation error in request body
    - `429 Too Many Requests`: Rate limit exceeded
    - `500 Internal Server Error`: Server-side error
    
    ## Rate Limiting
    
    Rate limiting is implemented with the following limits:
    - Per user: 100 requests per minute
    - Global: 1000 requests per minute
    
    Rate limit headers are included in responses:
    - `X-RateLimit-Limit`: Request limit
    - `X-RateLimit-Remaining`: Remaining requests
    - `X-RateLimit-Reset`: Reset time (Unix timestamp)
    """,
    version="0.1.0",
    lifespan=lifespan,
    # Clean, stable operationIds -> readable generated SDK method names (task 11).
    generate_unique_id_function=custom_generate_unique_id,
    contact={
        "name": "SoundSafe",
        "email": "support@soundsafe.ai",
    },
    license_info={
        "name": "Proprietary",
    },
    openapi_tags=[
        {
            "name": "Authentication",
            "description": "User authentication and token management"
        },
        {
            "name": "Assets",
            "description": "Manufacturing asset management and monitoring"
        },
        {
            "name": "Telemetry",
            "description": "Real-time sensor data and historical metrics"
        },
        {
            "name": "Alarms",
            "description": "Alarm notifications and acknowledgment"
        },
        {
            "name": "Commands",
            "description": "Command execution to industrial equipment"
        },
        {
            "name": "OEE",
            "description": "Overall Equipment Effectiveness metrics"
        },
        {
            "name": "Kanban",
            "description": "Task management and workflow tracking"
        },
        {
            "name": "Registries",
            "description": "Compliance and operational registries"
        },
        {
            "name": "Edge",
            "description": "Edge agent enrollment, authenticated telemetry ingest, and fleet health"
        },
    ]
)

# Consistent error envelope for all 4xx/5xx (keeps `detail` for back-compat).
register_exception_handlers(app)

# Distributed tracing (no-op unless OTEL_ENABLED).
from app.core.tracing import setup_tracing  # noqa: E402
from app.db.database import engine as _db_engine  # noqa: E402
setup_tracing(app, engine=_db_engine)

# Apply rate limiter to the app (disabled for debugging)
# app.state.limiter = limiter

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request-ID / correlation + structured access logging (outermost so every
# request — including error responses — gets an id and one access log line).
app.add_middleware(RequestContextMiddleware)

# Idempotency-Key replay for mutations on the unowned platform domains only.
app.add_middleware(
    IdempotencyMiddleware,
    protected_prefixes=(
        "/api/v1/operations",
        "/api/v1/dashboard",
        "/api/v1/yard",
        "/api/v1/transportation",
        "/api/v1/geotab",
    ),
)

# CSRF middleware (optional, can be disabled for API-only usage)
# Uncomment to enable CSRF protection
# app.add_middleware(CSRFMiddleware)

# Security headers middleware (disabled for debugging)
# app.add_middleware(SecurityHeadersMiddleware)

# Audit logging middleware (disabled for debugging)
# app.add_middleware(AuditLoggingMiddleware)

# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(assets.router, prefix="/api/v1/assets", tags=["Assets"])
app.include_router(telemetry.router, prefix="/api/v1/telemetry", tags=["Telemetry"])
app.include_router(alarms.router, prefix="/api/v1/alarms", tags=["Alarms"])
app.include_router(operations.router, prefix="/api/v1/operations", tags=["Operations"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(health.router, prefix="", tags=["Health"])
app.include_router(engines.router, prefix="/api/v1/engines", tags=["AI Engines"])
app.include_router(yard.router, prefix="/api/v1/yard", tags=["Yard Management"])
app.include_router(transportation.router, prefix="/api/v1/transportation", tags=["Transportation Management"])
app.include_router(logistics_correlation.router, prefix="/api/v1/logistics", tags=["Logistics Correlation"])
app.include_router(commands.router, prefix="/api/v1/commands", tags=["Commands"])
app.include_router(oee.router, prefix="/api/v1/oee", tags=["OEE"])
app.include_router(health_index.router, prefix="/api/v1/health-index", tags=["Asset Health Index"])
app.include_router(simulation.router, prefix="/api/v1/simulation", tags=["Simulation / Digital Twin"])
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"])
app.include_router(edge_enroll.router, tags=["Edge"])
app.include_router(edge_ingest.router, tags=["Edge"])
app.include_router(edge_fleet.router, tags=["Edge"])
app.include_router(kanban.router, prefix="/api/v1/kanban", tags=["Kanban"])
app.include_router(registries.router, tags=["Registries"])
app.include_router(websocket.router, tags=["WebSocket"])
app.include_router(geotab.router, prefix="/api/v1", tags=["GeoTab"])
app.include_router(correlation_integration.router, tags=["Correlation Integration"])
app.include_router(nlp_correlation.router, tags=["NLP Correlation"])
app.include_router(analysis_sessions.router, tags=["Analysis Sessions"])
app.include_router(user_context.router, tags=["User Context"])
app.include_router(audit.router, prefix="/api/v1/audit", tags=["Audit Logs"])
app.include_router(api_keys.router, prefix="/api/v1/api-keys", tags=["API Keys"])
app.include_router(gdpr.router, prefix="/api/v1/gdpr", tags=["GDPR Compliance"])
app.include_router(compliance.router, prefix="/api/v1/compliance", tags=["Compliance"])
app.include_router(data_residency.router, prefix="/api/v1/data-residency", tags=["Data Residency"])
app.include_router(erp_integrations.router, tags=["ERP Integrations"])


@app.get("/")
async def root():
    return {
        "message": "OpsGrid API",
        "version": "0.1.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
