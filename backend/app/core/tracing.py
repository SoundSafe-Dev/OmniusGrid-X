"""OpenTelemetry tracing setup (task 13).

Distributed tracing across the platform, OFF by default and fully optional: when
``settings.OTEL_ENABLED`` is false this is a no-op and the OpenTelemetry packages
are never imported, so nothing changes for existing deployments. When enabled it
auto-instruments FastAPI (incoming spans + W3C traceparent extraction — which is
how edge-propagated context, task 15, links up), async SQLAlchemy, httpx
(outgoing calls) and aiokafka, exporting via OTLP to the collector (task 14).

All OTel imports are lazy (inside the setup functions) so the dependency is only
needed where tracing is turned on.

FS-791. TWO GAPS MADE THE INGESTION PATH UNTRACEABLE, and it is the path that matters:
device → Redpanda → ingestion worker → TimescaleDB is where `IngestionDataLost` and
`IngestionDeadLettering` fire, and an operator investigating either had no trace at all.

  1. Only FastAPI, httpx and SQLAlchemy were instrumented, so a span ended at the
     producer. The consumer's work started a NEW trace with no parent, and the two
     halves of one message's journey could not be joined.
  2. `setup_tracing` was called from `app/main.py` and nowhere else. **The four worker
     processes never called it**, so they emitted no spans of any kind — not Kafka, not
     even their database writes.

`setup_worker_tracing` exists because a worker has no ASGI app to instrument, and passing
`None` to a function whose first parameter is the thing being instrumented reads as an
oversight rather than a decision.
"""

import structlog

from app.core.config import settings

logger = structlog.get_logger()


def _provider(service: str):
    """Build and register the tracer provider. Returns None if the deps are absent."""
    from opentelemetry import trace
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
    from opentelemetry.sdk.resources import Resource
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    endpoint = getattr(settings, "OTEL_EXPORTER_OTLP_ENDPOINT", "http://otel-collector:4317")
    provider = TracerProvider(resource=Resource.create({"service.name": service}))
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=endpoint, insecure=True))
    )
    trace.set_tracer_provider(provider)
    return endpoint


def _instrument_kafka() -> bool:
    """Instrument aiokafka so a message keeps its trace across the broker.

    Separate and individually guarded: this instrumentor arrived after the other three,
    and an environment with the older pinned set installed must keep tracing the rest
    rather than losing all of it to one ImportError.
    """
    try:
        from opentelemetry.instrumentation.aiokafka import AIOKafkaInstrumentor
    except ImportError as exc:
        logger.warning("otel_aiokafka_missing", error=str(exc))
        return False
    AIOKafkaInstrumentor().instrument()
    return True


def setup_worker_tracing(engine=None, service: str | None = None) -> bool:
    """Instrument a background worker: Kafka, the database, and outgoing HTTP.

    The workers have never been traced (FS-791). `setup_tracing` takes an ASGI app and
    was called only from `app/main.py`, so every span from the ingestion, export,
    compliance-report and OTA-rollout processes was simply absent — including the
    consumer half of every telemetry message.
    """
    if not getattr(settings, "OTEL_ENABLED", False):
        return False

    try:
        from opentelemetry.instrumentation.httpx import HTTPXClientInstrumentor
        from opentelemetry.instrumentation.sqlalchemy import SQLAlchemyInstrumentor
    except ImportError as exc:  # deps not installed -> stay disabled, don't crash
        logger.warning("otel_deps_missing", error=str(exc))
        return False

    name = service or getattr(settings, "OTEL_SERVICE_NAME", "omniusgrid-worker")
    endpoint = _provider(name)
    kafka = _instrument_kafka()
    HTTPXClientInstrumentor().instrument()
    if engine is not None:
        SQLAlchemyInstrumentor().instrument(engine=getattr(engine, "sync_engine", engine))

    logger.info("otel_worker_tracing_enabled", service=name, endpoint=endpoint, kafka=kafka)
    return True


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

    service = getattr(settings, "OTEL_SERVICE_NAME", "omniusgrid-backend")
    endpoint = _provider(service)

    FastAPIInstrumentor.instrument_app(app)
    HTTPXClientInstrumentor().instrument()
    # The API produces to Redpanda too (commands, rollouts). Without this the span ends
    # at the producer and the worker's half starts an unparented trace.
    kafka = _instrument_kafka()
    if engine is not None:
        # Instrument the async engine's sync core.
        SQLAlchemyInstrumentor().instrument(engine=getattr(engine, "sync_engine", engine))

    logger.info("otel_tracing_enabled", service=service, endpoint=endpoint, kafka=kafka)
    return True
