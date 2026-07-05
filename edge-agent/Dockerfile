FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    tesseract-ocr \
    libtesseract-dev \
    libgl1-mesa-glx \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Install Python dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY . .

# Create buffer directory
RUN mkdir -p /var/lib/opsgrid-agent

# Prometheus metrics endpoint (served when METRICS_PORT is set)
EXPOSE 9108

# Default command (overridden in docker-compose)
CMD ["python", "-m", "opsgrid_agent.main"]
