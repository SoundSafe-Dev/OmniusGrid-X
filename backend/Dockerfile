# Build CONTEXT is the REPO ROOT (not backend/):
#   docker build -f backend/Dockerfile .
# because the image bakes in repo-root database/migrations for the k8s
# migration Job (compose prod bind-mounts them instead; k8s cannot).
# docker-compose.yml and .github/workflows/ci-cd.yml are set up accordingly.

# UBI9, NOT python:3.11-slim (FS-761). Debian's OpenSSL has no FIPS 140-3 validated module
# and no path to one — the FIPS provider Red Hat ships is part of what is validated, and
# `python:3.11-slim` cannot get there by configuration. This is the only one of the three
# FIPS deltas that could not be closed in application code.
#
# WHAT THIS IMAGE DOES AND DOES NOT GIVE YOU. It makes FIPS *possible*: the OpenSSL 3 FIPS
# provider is available and the userspace is the validated one. It does not make FIPS *on* —
# a container inherits the host kernel's FIPS state, so this identical image is enforcing on
# a node booted with `fips=1` and permissive on the node beside it, with nothing in any
# manifest to tell them apart. Measured on a freshly pulled ubi9/python-311: providers
# `default`, no kernel flag, MD5 allowed. That is why `REQUIRE_FIPS_MODE` exists and why it
# probes behaviour at startup rather than trusting this line.
# FS-821 (continued). BASE IMAGES ARE DIGEST-PINNED.
#
# Every FROM in this repository named an image with no digest, and three of them named it
# with NO TAG EITHER — which resolves to `:latest`. So two builds of the same release could
# be built on different base images, and "rebuild last month's release" was not a thing that
# could be done.
#
# The k8s manifests were pinned first; Dockerfiles are the other half of the same supply
# chain, and the half that decides what is IN the image rather than which image runs.
#
# Measured 2026-08-20 with trivy against this base: 6,139 vulnerabilities, of which 0
# CRITICAL and 193 HIGH (102 with a published fix). That is why the image gate in
# ci-cd.yml blocks on CRITICAL rather than HIGH — at HIGH it would fail on the first run,
# on findings whose fix is a Red Hat base-image bump we do not control the cadence of.
#
# PINNING WITHOUT A BUMP PROCESS TRADES ONE PROBLEM FOR ANOTHER: floating and
# unreproducible becomes frozen and stale. `.github/workflows/nightly-e2e.yml` runs
# `check_base_images_are_current.py`, which compares each digest below against what the tag
# resolves to today and fails when one has drifted — so the pin is deliberate and its
# staleness is visible.
FROM registry.access.redhat.com/ubi9/python-311@sha256:a0bdb55576fc5b8d6704279307817828ef027e1065533ceba133fe9516003a6c

WORKDIR /app

# `gcc` and `libpq-dev` become `gcc` and `postgresql-devel` under dnf. Installed as root,
# then dropped — the UBI python images run as user 1001 by default, so this is a deliberate
# escalation for the build steps only.
USER root
RUN dnf install -y --setopt=install_weak_deps=False \
        gcc \
        postgresql-devel \
    && dnf clean all \
    && rm -rf /var/cache/dnf

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ .

# SQL migrations for `python scripts/migrate.py --dir /app/db-migrations`
# (k8s migration Job); compose prod keeps using its bind mount.
COPY database/migrations /app/db-migrations

# Non-root: the app never needs root at runtime. All root-only steps
# (dnf/pip installs, COPYs) are above; create the user and hand it the app dir.
#
# UID 1000 is kept from the Debian image on purpose. The k8s manifests set
# `runAsUser: 1000` and a PersistentVolume's files are owned by it; changing the UID here to
# UBI's default 1001 would leave a running deployment unable to read its own data, which is
# a migration this change has no business forcing.
RUN groupadd --system --gid 1000 omnius \
    && useradd --system --uid 1000 --gid omnius --home-dir /app --shell /sbin/nologin omnius \
    && chown -R omnius:omnius /app
USER omnius

# Expose port
EXPOSE 8000

# Default command (overridden in docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
