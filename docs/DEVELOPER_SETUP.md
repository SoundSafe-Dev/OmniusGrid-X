# OmniusGrid Developer Setup Guide

## Overview

This guide provides step-by-step instructions for setting up a local development environment for OmniusGrid.

## Prerequisites

### System Requirements

- **Operating System**: macOS, Linux, or Windows with WSL2
- **RAM**: 16GB minimum (32GB recommended)
- **CPU**: 4 cores minimum (8 cores recommended)
- **Disk**: 50GB free space

### Software Requirements

- **Docker**: 20.10+ with Docker Compose
- **Python**: 3.11+
- **Node.js**: 20+ with npm
- **Git**: 2.40+
- **Make**: (optional, for convenience)
- **VS Code**: (recommended IDE)

### Optional Tools

- **Postman**: For API testing
- **DBeaver**: For database management
- **k9s**: For Kubernetes cluster management
- **kubectl**: For Kubernetes operations

## Initial Setup

### 1. Clone Repository

```bash
git clone https://github.com/your-org/OmniusGrid.git
cd OmniusGrid
```

### 2. Install Python Dependencies

```bash
cd backend

# Create virtual environment
python3 -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt

# Install development dependencies
pip install pytest pytest-asyncio pytest-cov flake8 black isort mypy
```

### 3. Install Node.js Dependencies

```bash
cd ../frontend

# Install dependencies
npm install

# Install development dependencies
npm install -D @types/react @types/react-dom @typescript-eslint/eslint-plugin @typescript-eslint/parser
```

### 4. Configure Environment Variables

```bash
# Copy example environment file
cp .env.example .env

# Edit .env with your settings
# Default development settings are provided
```

### 5. Start Development Services

```bash
# From project root
docker-compose up -d

# This starts:
# - Redpanda (Kafka-compatible)
# - TimescaleDB (PostgreSQL with time-series)
# - Backend API
# - Ingestion Worker
# - Frontend
# - Redis
# - Prometheus
# - Grafana
# - Loki
# - Promtail
```

### 6. Initialize Database

```bash
# Wait for TimescaleDB to be ready
docker-compose exec timescaledb psql -U omniusgrid -d omniusgrid -f /docker-entrypoint-initdb.d/001_init.sql
docker-compose exec timescaledb psql -U omniusgrid -d omniusgrid -f /docker-entrypoint-initdb.d/002_continuous_aggregates.sql
docker-compose exec timescaledb psql -U omniusgrid -d omniusgrid -f /docker-entrypoint-initdb.d/003_kanban_tables.sql
```

### 7. Seed Demo Data (Optional)

```bash
cd backend

# Seed demo assets
python scripts/seed_demo_assets.py

# Seed demo Kanban tasks
python scripts/seed_demo_kanban.py

# Initialize correlation registries
python scripts/initialize_correlation_registries.py dev-org
```

## Backend Development

### Running Backend Locally

```bash
cd backend

# Activate virtual environment
source venv/bin/activate

# Run development server
uvicorn app.main:app --reload --host 0.0.0.0 --port 8000
```

### Backend API Documentation

- **Swagger UI**: http://localhost:8000/docs
- **ReDoc**: http://localhost:8000/redoc
- **OpenAPI JSON**: http://localhost:8000/openapi.json

### Backend Testing

```bash
cd backend

# Run all tests
pytest

# Run with coverage
pytest --cov=app --cov-report=html

# Run specific test file
pytest tests/test_auth.py

# Run with verbose output
pytest -v
```

### Backend Code Quality

```bash
cd backend

# Format code
black app

# Sort imports
isort app

# Lint code
flake8 app

# Type check
mypy app
```

### Backend Debugging

```bash
# Enable debug logging
export LOG_LEVEL=DEBUG

# Run with debugger
python -m pdb app/main.py

# Or use VS Code debugger with launch configuration
```

## Frontend Development

### Running Frontend Locally

```bash
cd frontend

# Start development server
npm run dev

# This starts Vite dev server on http://localhost:3000
```

### Frontend Testing

```bash
cd frontend

# Run unit tests
npm test

# Run with coverage
npm test -- --coverage

# Run E2E tests (Playwright)
npx playwright test

# Run specific test file
npx playwright test login.spec.ts
```

### Frontend Code Quality

```bash
cd frontend

# Lint code
npm run lint

# Type check
npx tsc --noEmit

# Format code (if using Prettier)
npm run format
```

### Frontend Debugging

```bash
# Start with debug port
npm run dev -- --debug

# Or use VS Code debugger with launch configuration
```

## Edge Agent Development

### Running Edge Agent Locally

```bash
cd edge-agent

# Create virtual environment
python3 -m venv venv
source venv/bin/activate

# Install dependencies
pip install -r requirements.txt

# Run edge agent. Collectors come from the COLLECTORS env var (JSON) by
# default, or from a YAML file when COLLECTORS_FILE is set:
COLLECTORS_FILE=config/local_collectors.yml python -m opsgrid_agent.main

# Optional: expose Prometheus metrics on :9108/metrics
METRICS_PORT=9108 COLLECTORS_FILE=config/local_collectors.yml python -m opsgrid_agent.main
```

### Edge Agent Configuration

```bash
# Start from the example (covers all supported collector types) and edit it
cp config/poc_collectors.yml config/local_collectors.yml
```

Each entry is envelope-validated at startup (`opsgrid_agent/config_schema.py`);
invalid entries are logged and skipped. Both `collector_type` (YAML style) and
`type` (env-JSON style) are accepted. Supported types: `bambu_mqtt`, `mqtt`,
`qidi_screen`, `sovol_screen`, `orca_file`, `opcua`, `modbus`, `ethernet_ip`,
`profinet`, `bacnet`, `can_bus`, `http_rest`.

```yaml
collectors:
  - asset_id: printer-001
    collector_type: mqtt
    config:
      host: localhost
      port: 1883
      topic: bambu/printer/001

  # Optional: normalize a raw state field to PackML (OEE/state analytics).
  - asset_id: ab-plc-001
    collector_type: ethernet_ip
    config:
      ip_address: 192.168.1.210
      tags: ["Program:MainProgram.MachineState"]
      packml:
        asset_type: industrial_plc
        state_key: state
        mappings: { "1": "Execute", "0": "Stopped" }
```

### Edge Agent Testing

```bash
cd edge-agent

# Install the test toolchain (protocol drivers are faked in tests, so the
# pylogix/python-snap7/BAC0/python-can libs are not required).
pip install -r requirements-dev.txt

# Run tests (pytest.ini sets testpaths + pythonpath)
pytest
```

## Database Development

### Connecting to Database

```bash
# Using psql
docker-compose exec timescaledb psql -U omniusgrid -d omniusgrid

# Using DBeaver
# Host: localhost
# Port: 5432
# Database: omniusgrid
# User: omniusgrid
# Password: omniusgrid_dev_password
```

### Running Migrations

```bash
# Using Alembic (if configured)
cd backend
alembic upgrade head

# Manual SQL migration
docker-compose exec timescaledb psql -U omniusgrid -d omniusgrid -f database/migrations/004_new_feature.sql
```

### Database Queries

```bash
# View all assets
docker-compose exec timescaledb psql -U omniusgrid -d omniusgrid -c "SELECT * FROM assets LIMIT 10;"

# View recent telemetry
docker-compose exec timescaledb psql -U omniusgrid -d omniusgrid -c "SELECT * FROM telemetry ORDER BY time DESC LIMIT 10;"

# View PackML states
docker-compose exec timescaledb psql -U omniusgrid -d omniusgrid -c "SELECT * FROM packml_states ORDER BY state_entered_at DESC LIMIT 10;"
```

## Message Broker Development

### Accessing Redpanda Console

- **Redpanda Console**: http://localhost:9644
- **Default credentials**: admin / (no password)

### Producing Messages

```bash
# Using rpk (Redpanda CLI)
docker-compose exec redpanda rpk topic create test-topic
docker-compose exec redpanda rpk topic produce test-topic
# Enter message and press Ctrl-D

# Using Python
python -c "
from aiokafka import AIOKafkaProducer
import asyncio
import json

async def produce():
    producer = AIOKafkaProducer(bootstrap_servers='localhost:9092')
    await producer.start()
    await producer.send_and_wait('test-topic', json.dumps({'key': 'value'}).encode())
    await producer.stop()

asyncio.run(produce())
"
```

### Consuming Messages

```bash
# Using rpk
docker-compose exec redpanda rpk topic consume test-topic

# Using Python
python -c "
from aiokafka import AIOKafkaConsumer
import asyncio
import json

async def consume():
    consumer = AIOKafkaConsumer('test-topic', bootstrap_servers='localhost:9092')
    await consumer.start()
    async for msg in consumer:
        print(json.loads(msg.value))
    await consumer.stop()

asyncio.run(consume())
"
```

## Monitoring Development

### Accessing Grafana

- **Grafana**: http://localhost:3001
- **Default credentials**: admin / omniusgrid_admin

### Accessing Prometheus

- **Prometheus**: http://localhost:9090

### Viewing Logs

```bash
# View Loki logs
# Access Grafana -> Explore -> Select Loki datasource

# View container logs
docker-compose logs backend
docker-compose logs frontend
docker-compose logs -f  # Follow logs
```

## Common Development Tasks

### Adding a New API Endpoint

1. **Create route file** in `backend/app/api/`
```python
# backend/app/api/new_feature.py
from fastapi import APIRouter, Depends
from app.db.database import get_db

router = APIRouter()

@router.get("/new-feature")
async def get_new_feature(db = Depends(get_db)):
    return {"message": "New feature"}
```

2. **Register router** in `backend/app/main.py`
```python
from app.api import new_feature
app.include_router(new_feature.router, prefix="/api/v1/new-feature", tags=["New Feature"])
```

3. **Add tests** in `backend/tests/`
```python
# backend/tests/test_new_feature.py
import pytest
from fastapi.testclient import TestClient
from app.main import app

client = TestClient(app)

def test_get_new_feature():
    response = client.get("/api/v1/new-feature")
    assert response.status_code == 200
```

### Adding a New Frontend Page

1. **Create page component** in `frontend/src/pages/`
```tsx
// frontend/src/pages/NewFeature.tsx
import { FC } from 'react';

export const NewFeature: FC = () => {
  return (
    <div>
      <h1>New Feature</h1>
    </div>
  );
};
```

2. **Add route** in `frontend/src/App.tsx`
```tsx
import { NewFeature } from './pages/NewFeature';

<Route path="/new-feature" element={<NewFeature />} />
```

3. **Add API client** in `frontend/src/api/`
```typescript
// frontend/src/api/newFeature.ts
import axios from 'axios';

export const getNewFeature = async () => {
  const response = await axios.get('/api/v1/new-feature');
  return response.data;
};
```

### Adding a New Collector

There are two collector patterns. Prefer the **BaseCollector** pattern for new
protocol collectors — it keeps the collector focused on driver I/O and is bridged
to the coordinator by the adapter (which also provides optional PackML mapping).

1. **Create collector** in `edge-agent/opsgrid_agent/collectors/` as a
   `BaseCollector` subclass (see `ethernet_ip.py`/`http_rest.py` as templates):
```python
# edge-agent/opsgrid_agent/collectors/new_collector.py
from .base import BaseCollector

class NewCollector(BaseCollector):
    def __init__(self, config: dict):
        super().__init__(config)
        # read config.get(...) for your params; import drivers lazily

    async def start(self):
        await super().start()   # sets running; spawn your poll task
        ...

    async def stop(self):
        await super().stop()    # clears running; cancel your poll task
        ...
    # emit() readings as {timestamp_edge, asset_id, topic, collector_type, payload}
```

2. **Register** it in `edge-agent/opsgrid_agent/collectors/coordinator.py`
   using the adapter, and add the type to `SUPPORTED_COLLECTOR_TYPES` in
   `config_schema.py`:
```python
from .new_collector import NewCollector
# inside SUPPORTED_COLLECTORS:
'new_collector': coordinator_adapter(NewCollector),
```
(Mature collectors — mqtt/opcua/modbus/screen/file — instead take
`on_message_callback` and a blocking `start()`; register those classes directly.)

3. **Add example configuration** in `edge-agent/config/poc_collectors.yml`
```yaml
collectors:
  - asset_id: asset-001
    collector_type: new_collector
    config:
      # collector-specific config
      # packml: { asset_type: ..., state_key: state }   # optional
```

## Troubleshooting

### Backend Issues

**Port already in use**
```bash
# Find process using port 8000
lsof -i :8000

# Kill process
kill -9 <PID>
```

**Database connection failed**
```bash
# Check if TimescaleDB is running
docker-compose ps timescaledb

# Check logs
docker-compose logs timescaledb

# Restart database
docker-compose restart timescaledb
```

### Frontend Issues

**Module not found**
```bash
# Clear node_modules and reinstall
rm -rf node_modules package-lock.json
npm install
```

**Build errors**
```bash
# Clear Vite cache
rm -rf node_modules/.vite

# Rebuild
npm run build
```

### Docker Issues

**Container won't start**
```bash
# Check logs
docker-compose logs <service>

# Rebuild container
docker-compose build <service>

# Restart container
docker-compose restart <service>
```

**Out of disk space**
```bash
# Remove unused containers
docker container prune

# Remove unused images
docker image prune -a

# Remove unused volumes
docker volume prune
```

## IDE Configuration

### VS Code Extensions

Recommended extensions for OmniusGrid development:

- **Python**: Python extension by Microsoft
- **Pylance**: Python language server
- **ESLint**: JavaScript/TypeScript linting
- **Prettier**: Code formatting
- **Docker**: Docker support
- **GitLens**: Git supercharged
- **Thunder Client**: API testing
- **PostgreSQL**: Database management

### VS Code Settings

Create `.vscode/settings.json`:
```json
{
  "python.defaultInterpreterPath": "./backend/venv/bin/python",
  "python.linting.enabled": true,
  "python.linting.pylintEnabled": true,
  "python.formatting.provider": "black",
  "editor.formatOnSave": true,
  "editor.codeActionsOnSave": {
    "source.fixAll.eslint": true
  },
  "typescript.tsdk": "node_modules/typescript/lib"
}
```

### VS Code Launch Configurations

Create `.vscode/launch.json`:
```json
{
  "version": "0.2.0",
  "configurations": [
    {
      "name": "Python: Backend",
      "type": "python",
      "request": "launch",
      "program": "backend/app/main.py",
      "console": "integratedTerminal",
      "env": {
        "PYTHONPATH": "${workspaceFolder}/backend"
      }
    },
    {
      "name": "Chrome: Frontend",
      "type": "chrome",
      "request": "launch",
      "url": "http://localhost:3000",
      "webRoot": "${workspaceFolder}/frontend/src"
    }
  ]
}
```

## Performance Tips

### Backend Performance

- Use async/await for I/O operations
- Implement database connection pooling
- Add caching with Redis
- Use database indexes for frequent queries
- Implement pagination for large datasets

### Frontend Performance

- Use React.memo for expensive components
- Implement code splitting with React.lazy
- Use virtual scrolling for large lists
- Optimize bundle size with tree shaking
- Implement service worker for caching

### Database Performance

- Use TimescaleDB hypertables for time-series data
- Implement continuous aggregates for pre-computed data
- Add appropriate indexes
- Use connection pooling
- Implement query caching

## Security Best Practices

### Development Security

- Never commit secrets to repository
- Use environment variables for sensitive data
- Implement rate limiting in development
- Use HTTPS in development (with self-signed certs)
- Regularly update dependencies

### API Security

- Validate all input
- Implement authentication and authorization
- Use HTTPS in production
- Implement rate limiting
- Add CORS headers appropriately

### Database Security

- Use parameterized queries
- Implement row-level security
- Regularly backup database
- Use strong passwords
- Limit database user permissions

## Resources

### Documentation

- [FastAPI Documentation](https://fastapi.tiangolo.com/)
- [React Documentation](https://react.dev/)
- [TimescaleDB Documentation](https://docs.timescale.com/)
- [Redpanda Documentation](https://docs.redpanda.com/)

### Community

- [GitHub Issues](https://github.com/your-org/OmniusGrid/issues)
- [Discord Server](https://discord.gg/omniusgrid)
- [Stack Overflow](https://stackoverflow.com/questions/tagged/omniusgrid)

### Training

- [FastAPI Tutorial](https://fastapi.tiangolo.com/tutorial/)
- [React Tutorial](https://react.dev/learn)
- [TimescaleDB Tutorial](https://docs.timescale.com/tutorials/)

---

**Document Version:** 1.0  
**Last Updated:** 2026-05-25  
**Component:** Developer Setup Guide
