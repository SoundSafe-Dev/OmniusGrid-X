"""OpenTelemetry tracing setup (task 13).

Distributed tracing across the platform, OFF by default and fully optional: when
``settings.OTEL_ENABLED`` is false this is a no-op and the OpenTelemetry packages
are never imported, so nothing changes for existing deployments. When enabled it
auto-instruments FastAPI (incoming spans + W3C traceparent extraction — which is
how edge-propagated context, task 15, links up), async SQLAlchemy, and httpx
(outgoing calls), exporting via OTLP to the collector (task 14).

All OTel imports are lazy (inside :func:`setup_tracing`) so the dependency is
only needed where tracing is turned on.
"""

import structlog

from app.core.config import settings

logger = structlog.get_logger()


def setup_tracing(app, engine=None) -> bool:
    """Instrument the app for tracing when enabled. Returns True if activated."""
    if not getattr(settings, "OTEL_ENABLED", False):
        return False

    try:
        from opentelemetry import trace
        from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # deps not installed -> stay disabled, don't crash
        logger.warning("otel_deps_missing", error=str(exc))
        return False

    endpoint = getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    service = getattr(settings, "OTEL_SERVICE_NAME", "omniusgrid-backend")

    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True)))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    if engine is not None:
        # Instrument the async engine's sync core.
        SQLAlchemyInstrumentor().instrument(engine=getattr(engine, "sync_engine", engine))

    logger.info("otel_tracing_enabled", service=service, endpoint=endpoint)
    return True
