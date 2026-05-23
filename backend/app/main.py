"""OpsGrid Backend Application"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api import assets, telemetry, alarms, operations, auth, dashboard, health, engines
from app.api import yard, transportation, logistics_correlation, websocket, commands, oee, kanban, registries, geotab, correlation_integration, nlp_correlation, analysis_sessions
from app.core.config import settings
from app.db.database import init_db
from app.services.websocket_manager import websocket_manager
from app.services.command_executor import command_executor
from app.services.oee_calculator import oee_calculator


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    await init_db()
    await websocket_manager.connect()
    await command_executor.start()
    await oee_calculator.start()
    yield
    # Shutdown
    await oee_calculator.stop()
    await command_executor.stop()
    await websocket_manager.disconnect()


app = FastAPI(
    title="OpsGrid API",
    description="Universal Manufacturing Data Feed Dashboard API",
    version="0.1.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:9999",
        "http://localhost:5173",
        "http://localhost:3000",
        "http://192.168.1.235:3000",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth.router, prefix="/api/v1/auth", tags=["Authentication"])
app.include_router(assets.router, prefix="/api/v1/assets", tags=["Assets"])
app.include_router(telemetry.router, prefix="/api/v1/telemetry", tags=["Telemetry"])
app.include_router(alarms.router, prefix="/api/v1/alarms", tags=["Alarms"])
app.include_router(operations.router, prefix="/api/v1/operations", tags=["Operations"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["Dashboard"])
app.include_router(health.router, prefix="", tags=["Health"])
app.include_router(engines.router, prefix="/api/v1/engines", tags=["AI Engines"])
app.include_router(yard.router, prefix="/api/v1/yard", tags=["Yard Management"])
app.include_router(transportation.router, prefix="/api/v1/transportation", tags=["Transportation Management"])
app.include_router(logistics_correlation.router, prefix="/api/v1/logistics", tags=["Logistics Correlation"])
app.include_router(commands.router, prefix="/api/v1/commands", tags=["Commands"])
app.include_router(oee.router, prefix="/api/v1/oee", tags=["OEE"])
app.include_router(kanban.router, prefix="/api/v1/kanban", tags=["Kanban"])
app.include_router(registries.router, tags=["Registries"])
app.include_router(websocket.router, tags=["WebSocket"])
app.include_router(geotab.router, prefix="/api/v1", tags=["GeoTab"])
app.include_router(correlation_integration.router, tags=["Correlation Integration"])
app.include_router(nlp_correlation.router, tags=["NLP Correlation"])
app.include_router(analysis_sessions.router, tags=["Analysis Sessions"])


@app.get("/")
async def root():
    return {
        "message": "OpsGrid API",
        "version": "0.1.0",
        "docs": "/docs"
    }


@app.get("/health")
async def health_check():
    return {"status": "healthy"}
