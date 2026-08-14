"""OpsGrid Backend Application"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from contextlib import asynccontextmanager

from app.api import assets, telemetry, alarms, operations, auth, dashboard, health, engines
from app.api import alarm_rules
# TWO user-administration surfaces after the 2026-08-08 merge, at DIFFERENT prefixes, and
# both are mounted rather than one being dropped. `user_management` serves /api/v1/users
# (FS-221); Hridyansh's `users` serves /api/v1/auth/users and adds invitations, reactivate
# and per-user reads. Which one the product keeps is a design call for his lane — deleting
# either during a merge is how a fortnight's work disappears quietly.
from app.api import user_management
from app.api import users
from app.api import dashboard_analytics
from app.api import yard
from app.api import insight_activation
from app.api import shop_floor, transportation, logistics_correlation, websocket, commands, oee, kanban, registries, geotab, correlation_integration, nlp_correlation, analysis_sessions, user_context, audit, api_keys, gdpr, compliance, compliance_reports, data_residency, feature_flags, sso, bulk_operations, exports, error_tracking, erp_integrations
from app.api import health_index, simulation, notifications
from app.api import edge_enroll, edge_ingest, edge_fleet
from app.api import erp_webhooks
from app.api import platform_correlation
from app.api import correlation_evidence, operations_assistant
from app.api import fleet_logistics
from app.api import fleet_agents, fleet_targeting, maintenance_windows, agent_releases, agent_rollouts, models
from app.api import kpi
from app.api import workcells
from app.api import fleet_health
# Integration branch (hridyansh): tenant historian/retention, model OTA releases,
# predictive-maintenance RUL, and the digital-twin optimizer.
from app.api import model_releases, historian, data_retention, rul, twin_optimizer
# RAG compliance-doc pipeline (Hudson): retrieval + ingestion router.
from app.api import rag
# Previously-orphaned routers (present in the tree but never mounted): MLOps
# model-monitoring/drift (Harsh's lane) and admin query-performance diagnostics.
from app.api import model_monitoring, query_performance
from app.core.config import settings
from app.core.responses import common_responses, unavailable_responses
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
from app.middleware.unhandled import UnhandledExceptionMiddleware
from app.middleware.idempotency import IdempotencyMiddleware, make_idempotency_store
from app.middleware.audit import AuditLoggingMiddleware
from app.middleware.security_headers import SecurityHeadersMiddleware
from app.middleware.csrf import CSRFMiddleware
from app.middleware.rate_limit import (
    auth_limiter,
    limiter,
    rate_limit_exceeded_handler,
    remote_operation_limiter,
)
from app.middleware.profiling import setup_profiling
from app.middleware.error_tracking import setup_error_tracking
from app.services.error_tracker import error_tracker
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.core.startup_checks import verify_installed_dependencies

install_sensitive_query_access_log_filter()

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    # FIRST, before anything that needs a package to be present (FS-446). compose mounts
    # ./backend over /app, so the CODE is current while the PACKAGES are as old as the last
    # image build — and the symptom is whichever import happens to come first, eight frames
    # deep. A two-month-old image died on `import jwt` three weeks after PyJWT replaced
    # python-jose, restart-looping with nothing saying "rebuild the image".
    verify_installed_dependencies()
    await init_db()
    # When an operator enables Gemma, confirm the configured base model and
    # LoRA adapter before accepting traffic. A broken adapter must be visible
    # at deployment time rather than silently falling back to heuristics.
    if settings.CORRELATION_MODEL_ENABLED:
        from app.services.correlation_ai_engine import correlation_ai_engine
        await correlation_ai_engine.ensure_model_ready()
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
        # FS-427: attempt queued systems-of-record postings without waiting for
        # somebody to open the Shop Floor page and press the button.
        from app.services.posting_drain_scheduler import posting_drain_scheduler
        await posting_drain_scheduler.start()
    await report_scheduler.start()
    await error_tracker.start()
    # FS-704: DB-backed refresh of the fleet liveness gauges, so an agent that died
    # before a backend restart still alerts (gauges live in process memory; the
    # database's last_seen survives).
    from app.services.edge_fleet_sweep import edge_fleet_sweep
    await edge_fleet_sweep.start()
    # Offline demo: the cloud strategic listener never connects, so seed a few
    # recommendations into the in-memory engine (same process as the API) to make
    # the Strategic Engine approve/reject workflow demo-able. Gated on the same
    # dev flag as the dev-token bypass, so it never runs in production.
    if settings.ALLOW_DEV_TOKEN:
        from app.services.strategic_engine import strategic_engine
        strategic_engine.load_demo_recommendations()
    # Best-effort: create the RAG vector collection if the store is reachable
    # (Hudson). Never blocks startup — storage/retrieval-only deployments run
    # without it.
    try:
        from app.services.vector_store import get_vector_store
        vector_store = get_vector_store()
        if vector_store.available:
            await vector_store.ensure_collection()
    except Exception as exc:  # noqa: BLE001 - startup must not crash on RAG
        import structlog
        structlog.get_logger().warning("rag.collection_bootstrap_failed", error=str(exc))
    yield
    # Shutdown
    from app.services.edge_fleet_sweep import edge_fleet_sweep
    await edge_fleet_sweep.stop()
    await error_tracker.stop()
    await report_scheduler.stop()
    if settings.SCHEDULERS_IN_API:
        from app.services.posting_drain_scheduler import posting_drain_scheduler
        await posting_drain_scheduler.stop()
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
app.state.remote_operation_limiter = remote_operation_limiter
app.add_exception_handler(RateLimitExceeded, rate_limit_exceeded_handler)

# Application-wide middleware remains gated on settings.RATE_LIMIT_ENABLED.
if settings.RATE_LIMIT_ENABLED:
    app.add_middleware(SlowAPIMiddleware)

# Unhandled-exception envelope, registered FIRST and therefore INNERMOST — deliberately
# inside CORS below. Starlette's catch-all exception handler lives on the outermost
# ServerErrorMiddleware, so its 500 never passes back through CORSMiddleware and reaches a
# browser with no Access-Control-Allow-Origin; the browser then reports a CORS failure
# instead of the 500, and the client loses the status, the body and the trace id. See
# app/middleware/unhandled.py. Moving this after add_middleware(CORSMiddleware) silently
# restores the defect, which is why a test asserts the order.
app.add_middleware(UnhandledExceptionMiddleware)

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
# Prefixes are HAMAD-lane mutation surfaces where at-least-once retries are safe
# to dedupe (FS-103). Correlation/kanban/intake/OTA/auth/RBAC surfaces are
# deliberately excluded — they are owned by other lanes.
app.add_middleware(
    IdempotencyMiddleware,
    # Redis-backed when REDIS_URL is set (the deployed stack has Redis), so the
    # dedup cache is shared across uvicorn workers and replicas. Without an
    # explicit store the middleware defaulted to a per-process in-memory cache,
    # so a retried Idempotency-Key hitting a different worker re-executed.
    store=make_idempotency_store(),
    protected_prefixes=(
        "/api/v1/operations",
        "/api/v1/dashboard",
        "/api/v1/yard",
        "/api/v1/transportation",
        "/api/v1/geotab",
        # FS-103: additional HAMAD-lane mutation surfaces.
        "/api/v1/assets",
        "/api/v1/alarms",
        "/api/v1/alarm-rules",
        "/api/v1/users",
        "/api/v1/telemetry",
        "/api/v1/maintenance",
        "/api/v1/notifications",
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
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"], responses=common_responses)
app.include_router(
    users.router,
    prefix="/api/v1/auth/users",
    # A DISTINCT TAG, because operationIds are derived from it and both routers export
    # list_users / get_user / update_user / deactivate_user. Mounting both produced four
    # duplicate operationIds, which the generated SDK cannot represent — the concrete cost
    # of keeping two user-administration surfaces, and a reason to resolve that decision.
    tags=["Tenant Users & Invitations"],
    responses=common_responses,
)
app.include_router(
    users.public_router,
    prefix="/api/v1/auth/invitations",
    tags=["User Invitations"],
    responses=common_responses,
)
app.include_router(assets.router, prefix="/api/v1/assets", tags=["Assets"], responses=common_responses)
app.include_router(telemetry.router, prefix="/api/v1/telemetry", tags=["Telemetry"], responses=common_responses)
app.include_router(alarms.router, prefix="/api/v1/alarms", tags=["Alarms"], responses=common_responses)
# Server-side threshold rules (FS-218). Mounted on its own prefix rather than
# under /alarms so the collection routes do not collide with /alarms/{alarm_id}.
app.include_router(alarm_rules.router, prefix="/api/v1/alarm-rules", tags=["Alarm Rules"], responses=common_responses)
# Admin user management (FS-221). Its own prefix rather than under /auth so the
# admin-only gate on the router cannot be confused with the public auth routes.
app.include_router(user_management.router, prefix="/api/v1/users", tags=["User Management"], responses=common_responses)
app.include_router(operations.router, prefix="/api/v1/operations", tags=["Operations"], responses=common_responses)
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"], responses=common_responses)
# Fleet-wide trends/aggregates for the operations dashboard (FS-192). Same
# prefix as above: these are dashboard resources, just aggregate-shaped.
app.include_router(dashboard_analytics.router, prefix="/api/v1/dashboard", tags=["Dashboard"], responses=common_responses)
app.include_router(health.router, prefix="", tags=["Health"], responses=unavailable_responses)
app.include_router(engines.router, prefix="/api/v1/engines", tags=["AI Engines"], responses=common_responses)
app.include_router(yard.router, prefix="/api/v1/yard", tags=["Yard Management"], responses=common_responses)
# Shop-floor events (FS-405): part issues, the labour clock, quality events and downtime,
# each fanned out to the systems of record that need it, with an explicit posting ledger.
app.include_router(shop_floor.router, prefix="/api/v1/shop-floor", tags=["Shop Floor"], responses=common_responses)
# Insight activation (FS-406): a correlation-AI recommendation becomes a Kanban task plus
# postings to every system of record its domain implies — issue, confirm, reject.
app.include_router(insight_activation.router, prefix="/api/v1/insights", tags=["Insight Activation"], responses=common_responses)
app.include_router(transportation.router, prefix="/api/v1/transportation", tags=["Transportation Management"], responses=common_responses)
app.include_router(logistics_correlation.router, prefix="/api/v1/logistics", tags=["Logistics Correlation"], responses=common_responses)
app.include_router(commands.router, prefix="/api/v1/commands", tags=["Commands"], responses=common_responses)
app.include_router(oee.router, prefix="/api/v1/oee", tags=["OEE"], responses=common_responses)
app.include_router(health_index.router, prefix="/api/v1/health-index", tags=["Asset Health Index"], responses=common_responses)
app.include_router(simulation.router, prefix="/api/v1/simulation", tags=["Simulation / Digital Twin"], responses=common_responses)
app.include_router(notifications.router, prefix="/api/v1/notifications", tags=["Notifications"], responses=common_responses)
app.include_router(edge_enroll.router, tags=["Edge"], responses=unavailable_responses)
app.include_router(edge_ingest.router, tags=["Edge"], responses=common_responses)
app.include_router(edge_fleet.router, tags=["Edge"], responses=common_responses)
app.include_router(kanban.router, prefix="/api/v1/kanban", tags=["Kanban"], responses=common_responses)
app.include_router(registries.router, tags=["Registries"], responses=common_responses)
app.include_router(websocket.router, tags=["WebSocket"], responses=common_responses)
app.include_router(geotab.router, prefix="/api/v1", tags=["GeoTab"], responses=common_responses)
app.include_router(geotab.webhook_router, prefix="/api/v1", tags=["GeoTab"], responses=common_responses)
app.include_router(correlation_integration.router, tags=["Correlation Integration"], responses=common_responses)
app.include_router(nlp_correlation.router, tags=["NLP Correlation"], responses=common_responses)
app.include_router(correlation_evidence.router, tags=["Evidence Correlation"], responses=common_responses)
app.include_router(operations_assistant.router, tags=["Operations Lead Assistant"], responses=common_responses)
app.include_router(analysis_sessions.router, tags=["Analysis Sessions"], responses=common_responses)
app.include_router(user_context.router, tags=["User Context"], responses=common_responses)
app.include_router(audit.router, prefix="/api/v1/audit", tags=["Audit Logs"], responses=common_responses)
app.include_router(api_keys.router, prefix="/api/v1/api-keys", tags=["API Keys"], responses=common_responses)
app.include_router(gdpr.router, prefix="/api/v1/gdpr", tags=["GDPR Compliance"], responses=common_responses)
app.include_router(compliance.router, prefix="/api/v1/compliance", tags=["Compliance"], responses=common_responses)
app.include_router(compliance_reports.router, prefix="/api/v1/compliance", tags=["Compliance Reports"], responses=unavailable_responses)
app.include_router(
    compliance_reports.public_router,
    prefix="/api/v1/compliance",
    tags=["Compliance Reports"],
    responses=common_responses,
)
app.include_router(data_residency.router, prefix="/api/v1/data-residency", tags=["Data Residency"], responses=common_responses)
app.include_router(erp_integrations.router, tags=["ERP Integrations"], responses=unavailable_responses)
app.include_router(erp_webhooks.router, tags=["ERP Integrations"], responses=common_responses)
app.include_router(platform_correlation.router, tags=["NLP Correlation"], responses=common_responses)
# Fleet logistics (D20-D21): geofencing, maintenance, and logistics aggregates.
app.include_router(fleet_logistics.geofencing_router, prefix="/api/v1/geofencing", tags=["Geofencing"], responses=common_responses)
app.include_router(fleet_logistics.maintenance_router, prefix="/api/v1/maintenance", tags=["Fleet Maintenance"], responses=common_responses)
app.include_router(fleet_logistics.logistics_router, prefix="/api/v1/logistics", tags=["Transportation Management"], responses=common_responses)
app.include_router(kpi.router, prefix="/api/v1/kpi", tags=["KPIs"], responses=common_responses)
app.include_router(workcells.workcells_router, prefix="/api/v1/workcells", tags=["Workcells"], responses=common_responses)
app.include_router(workcells.organizations_router, prefix="/api/v1/organizations", tags=["Organizations"], responses=common_responses)
app.include_router(fleet_health.router, prefix="/api/v1/fleet", tags=["Fleet Health"], responses=common_responses)
app.include_router(feature_flags.router, prefix="/api/v1/feature-flags", tags=["Feature Flags"], responses=unavailable_responses)
app.include_router(sso.router, prefix="/api/v1/sso", tags=["SSO"], responses=unavailable_responses)
app.include_router(bulk_operations.router, prefix="/api/v1/bulk", tags=["Bulk Operations"], responses=unavailable_responses)
app.include_router(exports.router, prefix="/api/v1/exports", tags=["Exports"], responses=unavailable_responses)
# Signature-authorized export downloads (no bearer; used by delivery email links).
app.include_router(exports.public_router, prefix="/api/v1/exports", tags=["Exports"], responses=common_responses)
app.include_router(error_tracking.router, prefix="/api/v1/admin/errors", tags=["Error Triage"], responses=common_responses)
app.include_router(fleet_agents.router, prefix="/api/v1/fleet", tags=["Fleet"], responses=common_responses)
app.include_router(fleet_targeting.router, prefix="/api/v1/fleet", tags=["Fleet"], responses=common_responses)
app.include_router(maintenance_windows.router, prefix="/api/v1/fleet", tags=["Fleet"], responses=common_responses)
app.include_router(agent_releases.router, prefix="/api/v1/fleet", tags=["Fleet"], responses=common_responses)
app.include_router(agent_releases.public_router, prefix="/api/v1/fleet", tags=["Fleet"], responses=common_responses)
app.include_router(agent_rollouts.router, prefix="/api/v1/fleet", tags=["Fleet"], responses=common_responses)
app.include_router(model_releases.router, prefix="/api/v1/fleet", tags=["Fleet"], responses=common_responses)
app.include_router(models.router, prefix="/api/v1", tags=["Models"], responses=common_responses)
app.include_router(models.public_router, prefix="/api/v1", tags=["Models"], responses=common_responses)
app.include_router(historian.router, prefix="/api/v1/historian", tags=["Historian"], responses=common_responses)
app.include_router(rul.router, prefix="/api/v1/rul", tags=["Predictive Maintenance"], responses=common_responses)
app.include_router(twin_optimizer.router, prefix="/api/v1/twin", tags=["Digital Twin"], responses=common_responses)
app.include_router(
    data_retention.tenant_router,
    prefix="/api/v1/data-retention",
    tags=["Data Retention"],
    responses=common_responses,
)
app.include_router(rag.router, prefix="/api/v1/rag", tags=["RAG"], responses=unavailable_responses)
# Newly wired (were unmounted): model-monitoring/drift + admin query diagnostics.
app.include_router(model_monitoring.router, prefix="/api/v1/model-monitoring", tags=["Model Monitoring"], responses=unavailable_responses)
app.include_router(query_performance.router, prefix="/api/v1/admin/query-performance", tags=["Query Performance"], responses=unavailable_responses)


class RootInfo(BaseModel):
    message: str
    version: str
    docs: str


class BasicHealth(BaseModel):
    """`/health` — WHAT THE LIVENESS AND STARTUP PROBES ACTUALLY HIT.

    `infrastructure/k8s/base/backend-deployment.yaml` points both at this path, not at
    `/health/live`. It is a static literal with no I/O behind it, which is the correct
    shape for a liveness check: it answers "is this process serving requests", and it
    cannot fail for a reason that restarting would not fix. Readiness — the one that
    touches the database, Redis and the broker — is `/health/ready` in `app/api/health.py`.
    """

    status: str


@app.get("/", response_model=RootInfo)
async def root():
    return {
        "message": "OpsGrid API",
        "version": "0.1.0",
        "docs": "/docs"
    }


@app.get("/health", response_model=BasicHealth)
async def health_check():
    return {"status": "healthy"}
