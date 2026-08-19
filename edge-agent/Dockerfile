# UBI9, not python:3.11-slim (FS-761). Debian's OpenSSL has no FIPS 140-3 validated module
# and no path to one. The edge agent matters here as much as the backend and arguably more:
# it holds buffered CUI on a device that can be physically captured, and it is the half of
# the mTLS handshake running outside the datacentre.
#
# Measured on a freshly pulled ubi9/python-311: providers `default`, no kernel flag, MD5
# allowed. The image makes FIPS possible, the host kernel makes it real, and only a runtime
# probe can tell the two apart — which is what `REQUIRE_FIPS_MODE` does on the backend and
# what `EDGE_REQUIRE_FIPS` does here.
FROM registry.access.redhat.com/ubi9/python-311 AS wheel-builder

# UBI python images default to UID 1001, and `python -m build` writes an egg-info directory
# beside the sources. On the Debian base this stage ran as root and the write was invisible;
# here it failed with "could not create 'opsgrid_agent.egg-info': Permission denied". Root
# for the build stage only — nothing from this stage but the wheel reaches the final image.
USER root
WORKDIR /build

RUN pip install --no-cache-dir build==1.2.2.post1

COPY pyproject.toml .
COPY requirements.txt .
COPY opsgrid_agent ./opsgrid_agent

RUN python -m build --wheel --outdir /wheel


FROM registry.access.redhat.com/ubi9/python-311

# Debian -> RHEL package names, and ONE PACKAGE IS DELIBERATELY MISSING.
#
# `tesseract` and `libtesseract-dev` have no UBI9 equivalent. They are not in BaseOS,
# AppStream or CodeReady Builder, and EPEL9 does not carry `tesseract` for aarch64 at all —
# checked, not assumed. So the OCR dependency cannot come from a repository on this base.
#
# IT IS LEFT OUT RATHER THAN WORKED AROUND. Adding EPEL to an image chosen for FIPS
# provenance means adding a community repository, unsupported by Red Hat and outside the
# validation boundary, to the one image whose entire justification is that boundary. Trading
# the reason for the base image away to keep an optional feature is the wrong trade, and
# building tesseract from source into it is the same trade with more steps.
#
# WHAT IT COSTS, stated plainly: the two screen-scraper collectors (QIDI, SOVOL) are
# unavailable in this image. They import their drivers lazily, so a missing driver logs a
# clear error and disables THAT COLLECTOR ONLY rather than crashing the agent — the
# behaviour every fieldbus collector already has. A site that needs OCR on a fleet with no
# CUI obligation can keep the Debian-based build for that fleet; a site that needs both must
# supply tesseract itself.
USER root
RUN dnf install -y --setopt=install_weak_deps=False \
        gcc \
        mesa-libGL \
        glib2 \
    && dnf clean all \
    && rm -rf /var/cache/dnf

COPY requirements.txt /tmp/opsgrid-agent-requirements.txt
RUN pip install --no-cache-dir -r /tmp/opsgrid-agent-requirements.txt

COPY --from=wheel-builder /wheel /opt/opsgrid-agent/seed
COPY bootstrap /opt/opsgrid-agent/bootstrap

# Build metadata -> heartbeat manifest (versioning.build_manifest reads these).
# Injected by CI/compose: --build-arg AGENT_VERSION=... AGENT_BUILD_ID=... AGENT_GIT_SHA=...
ARG AGENT_VERSION=dev
ARG AGENT_BUILD_ID=local
ARG AGENT_GIT_SHA=unknown
ENV AGENT_VERSION=${AGENT_VERSION} \
    AGENT_BUILD_ID=${AGENT_BUILD_ID} \
    AGENT_GIT_SHA=${AGENT_GIT_SHA}

# Non-root: the agent only needs its state dir, never root.
RUN useradd --system --home-dir /var/lib/opsgrid-agent --shell /sbin/nologin opsgrid \
    && mkdir -p /var/lib/opsgrid-agent/runtime \
    && chown -R opsgrid:opsgrid /var/lib/opsgrid-agent
USER opsgrid

# Prometheus /metrics + /healthz (metrics_server; EXPOSE matches the default).
ENV METRICS_PORT=9108
EXPOSE 9108

# Health probe via /healthz. Uses python (already in the image, no curl) and
# passes when METRICS_ENABLED=false — a metrics-less agent is not unhealthy.
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s --retries=3 \
    CMD python -c "import os,sys,urllib.request; \
        sys.exit(0) if os.getenv('METRICS_ENABLED','true').lower()=='false' else \
        urllib.request.urlopen('http://localhost:'+os.getenv('METRICS_PORT','9108')+'/healthz', timeout=4)" \
        || exit 1

WORKDIR /var/lib/opsgrid-agent

ENV OPSGRID_RUNTIME_ROOT=/var/lib/opsgrid-agent/runtime \
    OPSGRID_SEED_WHEEL_GLOB=/opt/opsgrid-agent/seed/*.whl \
    PYTHONUNBUFFERED=1

CMD ["python", "/opt/opsgrid-agent/bootstrap/launcher.py"]
