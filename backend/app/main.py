"""OpsGrid Backend Application"""

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from contextlib import asynccontextmanager

from app.api import assets, telemetry, alarms, operations, auth, dashboard
from app.core.config import settings
from app.db.database import init_db
from app.services.websocket_manager import websocket_manager


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan events"""
    # Startup
    await init_db()
    await websocket_manager.connect()
    yield
    # Shutdown
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
    allow_origins=["*"],  # Configure for production
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
