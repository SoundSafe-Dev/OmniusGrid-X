#!/bin/bash

# OmniusGrid Startup Script
# This script ensures all backend services are running before starting the frontend

set -e

echo "🚀 Starting OmniusGrid..."

# Start core backend services
echo "📦 Starting backend services (Redpanda, TimescaleDB, Backend)..."
docker-compose up -d redpanda timescaledb backend

# Wait for services to be healthy
echo "⏳ Waiting for services to be healthy..."
max_attempts=60
attempt=0

while [ $attempt -lt $max_attempts ]; do
    # Check if backend is responding
    if curl -s http://localhost:8002/health > /dev/null 2>&1; then
        echo "✅ Backend is healthy!"
        break
    fi
    
    attempt=$((attempt + 1))
    echo "⏳ Waiting for backend... ($attempt/$max_attempts)"
    sleep 2
done

if [ $attempt -eq $max_attempts ]; then
    echo "❌ Backend failed to start within timeout"
    echo "📋 Backend logs:"
    docker logs omniusgrid-backend --tail 50
    exit 1
fi

echo "✅ All backend services are running"
echo "🌐 Backend API: http://localhost:8002"
echo ""
echo "📝 You can now start the frontend with:"
echo "   cd frontend && npm run dev"
echo ""
echo "Or start the frontend in Docker:"
echo "   docker-compose up -d frontend"
