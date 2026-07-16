"""OpsGrid Backend Application"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api import assets, telemetry, alarms, operations, auth, dashboard, health, engines
from app.api import yard, transportation, logistics_correlation, websocket, commands, oee, kanban, registries, geotab, correlation_integration, nlp_correlation, analysis_sessions, user_context, audit, api_keys, gdpr, compliance, compliance_reports, data_residency, feature_flags, sso, bulk_operations, exports, error_tracking, erp_integrations
from app.api import health_index, simulation, notifications
from app.api import edge_enroll, edge_ingest, edge_fleet
from app.api import erp_webhooks
from app.api import platform_correlation
from app.api import fleet_logistics
from app.api import fleet_agents, agent_releases, agent_rollouts, models
from app.api import kpi
from app.api import workcells
from app.api import fleet_health
# Integration branch (hridyansh): tenant historian/retention, model OTA releases,
# predictive-maintenance RUL, and the digital-twin optimizer.
from app.api import model_releases, historian, data_retention, rul, twin_optimizer
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
from app.core.errors import register_exception_handlers
from app.core.openapi import custom_generate_unique_id
from app.middleware.request_context import RequestContextMiddleware
from app.middleware.idempotency import IdempotencyMiddleware
from app.middleware.audit import AuditLoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.rate_limit import (
    auth_limiter,
    limiter,
    rate_limit_exceeded_handler,
)
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
    # Converged: integration branch enables the realtime/worker services that
    # fixed-sprints had commented out (the audit's "wire the machinery" item).
    await websocket_manager.connect()
    await oee_calculator.start()
    # Worker-backed schedulers: skip in the API when dedicated compose workers
    # own dispatch (SCHEDULERS_IN_API=false), so two pollers don't race the same
    # queues. export/compliance are mine; rollout_orchestrator is the OTA lane —
    # gating only WHETHER the API starts it, not its internals. Command dispatch
    # is now durable and worker-owned (integration branch), so it joins the set.
    if settings.SCHEDULERS_IN_API:
        await command_executor.start()
        await export_scheduler.start()
        await compliance_report_dispatcher.start()
        await rollout_orchestrator.start()
    await report_scheduler.start()
    await error_tracker.start()
    yield
    # Shutdown
    await error_tracker.stop()
    await report_scheduler.stop()
    if settings.SCHEDULERS_IN_API:
        await rollout_orchestrator.stop()
        await compliance_report_dispatcher.stop()
        await export_scheduler.stop()
        await command_executor.stop()
    await export_processor.close()
    await oee_calculator.stop()
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

    In non-production environments only (when `ALLOW_DEV_TOKEN=true`), the
    `dev-token` value is accepted as an admin bypass. It is rejected in
    production and the deploy fails fast if the flag is left enabled.

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

# GeoTab live mode without a wired client is an operator-actionable condition,
# not a server fault: return 503 with the message instead of a bare 500.
from app.services.geotab_service import GeoTabLiveModeNotConfigured  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402


@app.exception_handler(GeoTabLiveModeNotConfigured)
async def _geotab_live_mode_handler(request, exc):
    return JSONResponse(status_code=503, content={"detail": str(exc)})

# Fail fast on insecure production configuration (task 17).
from app.core.config import validate_settings as _validate_settings  # noqa: E402
_config_problems = _validate_settings()
if _config_problems:
    if settings.ENVIRONMENT.lower() == "production":
        raise RuntimeError("insecure production config: " + "; ".join(_config_problems))
    import structlog as _structlog  # noqa: E402
    _structlog.get_logger().warning("config_warnings", problems=_config_problems)

# Distributed tracing (no-op unless OTEL_ENABLED).
from app.core.tracing import setup_tracing  # noqa: E402
from app.db.database import engine as _db_engine  # noqa: E402
setup_tracing(app, engine=_db_engine)

# Register the limiter and handler unconditionally so explicitly enabled endpoint
# limits work in tests and dynamically configured deployments.
app.state.limiter = limiter
app.state.auth_limiter = auth_limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Application-wide middleware remains gated on settings.RATE_LIMIT_ENABLED.
if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(SlowAPIMiddleware)

# CORS middleware — explicit allowlist from config (settings.cors_origins parses
# it once; empty or any-'*' list is treated as wildcard). Wildcard is incompatible
# with credentialed requests (browsers reject it), so credentials are disabled
# whenever the allowlist is a wildcard rather than shipping the invalid combo.
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=not settings.cors_is_wildcard,
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

# CSRF protection — off by default (Bearer-JWT API, not cookie sessions).
if settings.CSRF_ENABLED:
    app.add_middleware(CSRFMiddleware, secret_key=settings.JWT_SECRET_KEY)

# Security headers (self-gates further via SECURITY_HEADERS_ENABLED / CSP_ENABLED).
if settings.SECURITY_HEADERS_ENABLED:
    app.add_middleware(SecurityHeadersMiddleware)

# Audit logging of sensitive operations (skips requests with no user context).
if settings.AUDIT_LOGGING_ENABLED:
    app.add_middleware(AuditLoggingMiddleware)

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
app.include_router(geotab.webhook_router, prefix="/api/v1", tags=["GeoTab"])
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
app.include_router(erp_integrations.router, tags=["ERP Integrations"])
app.include_router(erp_webhooks.router, tags=["ERP Integrations"])
app.include_router(platform_correlation.router, tags=["NLP Correlation"])
# Fleet logistics (D20-D21): geofencing, maintenance, and logistics aggregates.
app.include_router(fleet_logistics.geofencing_router, prefix="/api/v1/geofencing", tags=["Geofencing"])
app.include_router(fleet_logistics.maintenance_router, prefix="/api/v1/maintenance", tags=["Fleet Maintenance"])
app.include_router(fleet_logistics.logistics_router, prefix="/api/v1/logistics", tags=["Transportation Management"])
app.include_router(kpi.router, prefix="/api/v1/kpi", tags=["KPIs"])
app.include_router(workcells.workcells_router, prefix="/api/v1/workcells", tags=["Workcells"])
app.include_router(workcells.organizations_router, prefix="/api/v1/organizations", tags=["Organizations"])
app.include_router(fleet_health.router, prefix="/api/v1/fleet", tags=["Fleet Health"])
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
app.include_router(model_releases.router, prefix="/api/v1/fleet", tags=["Fleet"])
app.include_router(models.router, prefix="/api/v1", tags=["Models"])
app.include_router(models.public_router, prefix="/api/v1", tags=["Models"])
app.include_router(historian.router, prefix="/api/v1/historian", tags=["Historian"])
app.include_router(rul.router, prefix="/api/v1/rul", tags=["Predictive Maintenance"])
app.include_router(twin_optimizer.router, prefix="/api/v1/twin", tags=["Digital Twin"])
app.include_router(
    data_retention.tenant_router,
    prefix="/api/v1/data-retention",
    tags=["Data Retention"],
)


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
