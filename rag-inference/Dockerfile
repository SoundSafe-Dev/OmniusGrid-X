# rag-inference: BGE-M3 embeddings + BGE-Reranker-v2-m3
#
# CPU-first, GPU-ready. The default pip torch wheel runs on CPU and transparently
# uses CUDA when the container is started with GPU access (--gpus / device
# reservations). For a leaner GPU image you can instead base on a CUDA runtime
# (e.g. nvidia/cuda:12.x-runtime) - no application code change required.
FROM python:3.10-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY app ./app

# Cache model weights here; mount a volume to avoid re-downloading (~5 GB) on
# every container recreate.
ENV HF_HOME=/models
EXPOSE 8000

# Generous start-period: the first boot downloads BGE-M3 + reranker weights.
HEALTHCHECK --interval=30s --timeout=10s --start-period=300s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
