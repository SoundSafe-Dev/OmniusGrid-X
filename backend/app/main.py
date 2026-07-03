"""OpsGrid Backend Application"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api import assets, telemetry, alarms, operations, auth, dashboard, health, engines
from app.api import yard, transportation, logistics_correlation, websocket, commands, oee, kanban, registries, geotab, correlation_integration, nlp_correlation, analysis_sessions, user_context, audit, api_keys, gdpr, compliance, compliance_reports, data_residency, feature_flags, sso, bulk_operations, exports, error_tracking, fleet_agents, agent_releases, agent_rollouts
from app.core.config import settings
from app.core.logging_filters import install_sensitive_query_access_log_filter
from app.db.database import init_db
from app.services.websocket_manager import websocket_manager
from app.services.command_executor import command_executor
from app.services.compliance_report_queue import compliance_report_dispatcher
from app.services.rollout_orchestrator import rollout_orchestrator
from app.services.export_delivery import export_scheduler
from app.services.report_scheduler import report_scheduler
from app.services.export_processor import export_processor
from app.services.oee_calculator import oee_calculator
from app.middleware.audit import AuditLoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.rate_limit import limiter, rate_limit_exceeded_handler
from app.middleware.profiling import setup_profiling
from app.middleware.error_tracking import setup_error_tracking
from app.services.error_tracker import error_tracker
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

install_sensitive_query_access_log_filter()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    await init_db()
    await websocket_manager.connect()
    await command_executor.start()
    await oee_calculator.start()
    await export_scheduler.start()
    await compliance_report_dispatcher.start()
    await rollout_orchestrator.start()
    await report_scheduler.start()
    await error_tracker.start()
    yield
    # Shutdown
    await error_tracker.stop()
    await report_scheduler.stop()
    await rollout_orchestrator.stop()
    await compliance_report_dispatcher.stop()
    await export_scheduler.stop()
    await export_processor.close()
    await oee_calculator.stop()
    await command_executor.stop()
    await websocket_manager.disconnect()


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
    ]
)

# Register the limiter and handler unconditionally so explicitly enabled endpoint
# limits work in tests and dynamically configured deployments.
app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Application-wide middleware remains gated on settings.RATE_LIMIT_ENABLED.
if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(SlowAPIMiddleware)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# CSRF middleware (optional, can be disabled for API-only usage)
# Uncomment to enable CSRF protection
# app.add_middleware(CSRFMiddleware)

# Security headers middleware (disabled for debugging)
# app.add_middleware(SecurityHeadersMiddleware)

# Audit logging middleware (disabled for debugging)
# app.add_middleware(AuditLoggingMiddleware)

# Error tracking (gated off via ERROR_TRACKING_ENABLED, default False). Registered
# before profiling so it sits *inside* the profiling middleware — both observe an
# unhandled exception, and this layer re-raises it unchanged.
setup_error_tracking(app)

# Performance profiling (Task 2 — gated off via PROFILING_ENABLED, default False)
setup_profiling(app)

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
app.include_router(compliance_reports.router, prefix="/api/v1/compliance", tags=["Compliance Reports"])
app.include_router(
    compliance_reports.public_router,
    prefix="/api/v1/compliance",
    tags=["Compliance Reports"],
)
app.include_router(data_residency.router, prefix="/api/v1/data-residency", tags=["Data Residency"])
app.include_router(feature_flags.router, prefix="/api/v1/feature-flags", tags=["Feature Flags"])
app.include_router(sso.router, prefix="/api/v1/sso", tags=["SSO"])
app.include_router(bulk_operations.router, prefix="/api/v1/bulk", tags=["Bulk Operations"])
app.include_router(exports.router, prefix="/api/v1/exports", tags=["Exports"])
# Signature-authorized export downloads (no bearer; used by delivery email links).
app.include_router(exports.public_router, prefix="/api/v1/exports", tags=["Exports"])
app.include_router(error_tracking.router, prefix="/api/v1/admin/errors", tags=["Error Triage"])
app.include_router(fleet_agents.router, prefix="/api/v1/fleet", tags=["Fleet"])
app.include_router(agent_releases.router, prefix="/api/v1/fleet", tags=["Fleet"])
app.include_router(agent_releases.public_router, prefix="/api/v1/fleet", tags=["Fleet"])
app.include_router(agent_rollouts.router, prefix="/api/v1/fleet", tags=["Fleet"])


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
