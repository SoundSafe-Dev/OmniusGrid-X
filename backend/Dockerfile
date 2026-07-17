# Build CONTEXT is the REPO ROOT (not backend/):
#   docker build -f backend/Dockerfile .
# because the image bakes in repo-root database/migrations for the k8s
# migration Job (compose prod bind-mounts them instead; k8s cannot).
# docker-compose.yml and .github/workflows/ci-cd.yml are set up accordingly.
FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/ .

# SQL migrations for `python scripts/migrate.py --dir /app/db-migrations`
# (k8s migration Job); compose prod keeps using its bind mount.
COPY database/migrations /app/db-migrations

# Non-root: the app never needs root at runtime. All root-only steps
# (apt/pip installs, COPYs) are above; create the user and hand it the app dir.
RUN groupadd --system --gid 1000 omnius \
    && useradd --system --uid 1000 --gid omnius --home-dir /app --shell /usr/sbin/nologin omnius \
    && chown -R omnius:omnius /app
USER omnius

# Expose port
EXPOSE 8000

# Default command (overridden in docker-compose)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
