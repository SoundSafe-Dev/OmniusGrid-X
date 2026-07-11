FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    tesseract-ocr \
    libtesseract-dev \
    libgl1 \
    libglib2.0-0 \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Build metadata -> heartbeat manifest (versioning.build_manifest reads these).
# Injected by CI/compose: --build-arg AGENT_VERSION=... AGENT_BUILD_ID=... AGENT_GIT_SHA=...
ARG AGENT_VERSION=dev
ARG AGENT_BUILD_ID=local
ARG AGENT_GIT_SHA=unknown
ENV AGENT_VERSION=${AGENT_VERSION} \
    AGENT_BUILD_ID=${AGENT_BUILD_ID} \
    AGENT_GIT_SHA=${AGENT_GIT_SHA}

# Non-root: the agent only needs its state dir, never root.
RUN useradd --system --home-dir /var/lib/opsgrid-agent --shell /usr/sbin/nologin opsgrid \
    && mkdir -p /var/lib/opsgrid-agent \
    && chown -R opsgrid:opsgrid /var/lib/opsgrid-agent /app
USER opsgrid

# Prometheus /metrics + /healthz (metrics_server; EXPOSE matches the default).
ENV METRICS_PORT=9108
EXPOSE 9108

HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD curl -fsS "http://localhost:${METRICS_PORT}/healthz" || exit 1

# Default command (overridden in docker-compose)
CMD ["python", "-m", "opsgrid_agent.main"]
